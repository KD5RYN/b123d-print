"""Remixing: start a part from someone else's model (STL, 3MF or STEP) and change it.

    from b123d_print import import_model
    base = import_model("ref/bracket.stl")         # parts/<name>/ref/bracket.stl, as a solid
    part = base - Pos(10, 0, 0) * Cylinder(2.6, 20)

STEP gives the exact solid. A mesh (STL, 3MF) becomes a solid: coincident vertices welded,
degenerate and duplicate triangles dropped, small holes (up to SMALL_HOLE edges) closed, triangles
turned to face one way and outward, then adjacent coplanar triangles merged into one planar face
each (so a box is 6 faces again). Curved surfaces stay faceted: there is no curve fitting. Open
or non-manifold meshes that this does not fix are refused with what is wrong and where.

The result is cached in the part's out/.cache/ (keyed by the file's content and the options), so
build, render, section and check do not convert the same file again.

The script's original (the imported base, or what `original(d)` returns) is also checked with the
same automatic checks, so findings it already had are labeled "inherited from the original".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .refs import REF_DIR, SHARED_DIR, SUFFIXES

CONVERTER = 1  # bump when the mesh conversion changes, to invalidate cached results
SMALL_HOLE = 8  # open loops of up to this many edges are closed (a missing triangle or a sliver gap)
LIN_TOL = 1e-4  # mm: triangles merge when every vertex is this close to the face's plane
ANG_TOL = 2e-4  # rad between neighbors' normals for a coplanar merge
SOFT_ANGLE = 20.0  # deg: neighboring faces meeting flatter than this are facets of a curved surface
OCC_TOL = 2e-4  # mm: tolerance on the built vertices, edges and faces
UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4, "in": 25.4, "ft": 304.8, "micron": 0.001}
SMALL_PART = 10.0  # mm: a model whose largest side is under this was probably saved in inches or cm
LARGE_PART = 2000.0  # mm: one whose largest side is over this, in microns or tenths of a mm


class MeshError(ValueError):
    """The mesh cannot be made into a solid (open, non-manifold, too big...). The message says why."""


@dataclass
class ImportInfo:
    """What import_model did; the checks of the part that imports it report it ("import")."""

    file: str
    format: str  # "stl" | "3mf" | "step"
    units: str  # the file's own units, as far as it says
    scale: float = 1.0  # applied after the file's own unit conversion
    triangles: int | None = None  # meshes: triangles read
    repairs: list = field(default_factory=list)
    faces_before: int | None = None  # meshes: triangles kept; STEP: faces
    faces_after: int = 0
    planar_faces: int = 0
    faceted: dict = field(default_factory=dict)  # meshes: faces that are facets of curved surfaces
    solids: int = 0
    size: list = field(default_factory=list)
    volume: float = 0.0
    metadata: dict = field(default_factory=dict)  # 3MF metadata, STEP header: designer, license, ...
    notes: list = field(default_factory=list)  # for information (curves stay faceted, units converted)
    warnings: list = field(default_factory=list)  # probably wrong (units): the import check warns
    cached: bool = False
    seconds: float = 0.0

    def summary(self) -> str:
        s = f"{self.format.upper()}, {' x '.join(f'{x:.2f}' for x in self.size)} mm, " \
            f"{self.solids} solid(s), {self.faces_after} faces"
        if self.triangles is not None:
            s += f" (from {self.triangles} triangles; {self.faceted.get('faces', 0)} faceted curve faces)"
        return s


# registry of what import_model returned during the current build (project.run_checks reads it)
IMPORTED: list[tuple[object, ImportInfo]] = []


def reset_imports() -> None:
    IMPORTED.clear()


# ---------------------------------------------------------------------------------------------
# Mesh topology: weld, repair, orient


def _weld(verts: np.ndarray, tris: np.ndarray, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """Merge vertices closer than tol (exact duplicates first, then a k-d tree for near ones)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    uniq, inv = np.unique(verts, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    pairs = cKDTree(uniq).query_pairs(tol, output_type="ndarray")
    if len(pairs):
        n = len(uniq)
        g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        _, lab = connected_components(g, directed=False)
        _, first = np.unique(lab, return_index=True)
        uniq, inv = uniq[first], lab[inv]  # labels are 0..k-1 in order of first appearance
    return uniq, inv[tris]


def _edges(tris: np.ndarray, nv: int):
    """Directed edges (3T, 2) in triangle order, their undirected ids and the count per id."""
    d = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1).reshape(-1, 2)
    key = np.minimum(d[:, 0], d[:, 1]) * nv + np.maximum(d[:, 0], d[:, 1])
    _, eid, counts = np.unique(key, return_inverse=True, return_counts=True)
    return d, eid.reshape(-1), counts


def _where(verts, idx, n=4) -> str:
    pts = verts[np.asarray(idx)[:n]]
    return ", ".join("(" + ", ".join(f"{x:.2f}" for x in p) + ")" for p in pts)


def _open_loops(d: np.ndarray, open_mask: np.ndarray) -> list[list[int]] | None:
    """The open directed edges as closed vertex loops; None if they do not form simple loops."""
    nxt: dict[int, int] = {}
    for a, b in d[open_mask].tolist():
        if a in nxt:
            return None
        nxt[a] = b
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, v = [], start
        while v not in seen:
            seen.add(v)
            loop.append(v)
            v = nxt.get(v)
            if v is None:
                return None
        if v != start:
            return None
        loops.append(loop)
    return loops


def repair(verts: np.ndarray, tris: np.ndarray, weld_tol: float = 1e-4) -> tuple[np.ndarray, np.ndarray, list[int], list[str]]:
    """Make a triangle soup into closed, consistently outward-oriented shells.
    Returns (verts, tris, component id per triangle, repairs done). Raises MeshError."""
    repairs = []
    verts, tris = _weld(verts, tris, weld_tol)
    t = verts[tris]
    area2 = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    bad = (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2]) | (area2 < 1e-12)
    if bad.any():
        repairs.append(f"dropped {int(bad.sum())} degenerate triangle(s)")
        tris = tris[~bad]
    # duplicates: the same three vertices twice (same way round: one is extra; opposite: an internal double wall)
    key = np.sort(tris, axis=1)
    _, first, inv, cnt = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
    if (cnt > 1).any():
        inv = inv.reshape(-1)
        keep = np.zeros(len(tris), bool)
        keep[first] = True
        dup_ids = np.flatnonzero(cnt > 1)
        drop_both = 0
        for g in dup_ids:  # few
            members = np.flatnonzero(inv == g)
            if len(members) == 2 and _opposite(tris[members[0]], tris[members[1]]):
                keep[members] = False
                drop_both += 1
        tris = tris[keep]
        repairs.append(f"dropped {int((cnt[cnt > 1] - 1).sum())} duplicate triangle(s)"
                       + (f" ({drop_both} back-to-back pair(s) removed entirely)" if drop_both else ""))
    if not len(tris):
        raise MeshError("no triangles left after removing degenerate ones")
    d, eid, counts = _edges(tris, len(verts))
    nonman = counts[eid] > 2
    if nonman.any():
        raise MeshError(f"non-manifold: {int((counts > 2).sum())} edge(s) shared by more than two triangles, e.g. at "
                        f"{_where(verts, d[nonman][:, 0])}. Repair the mesh first (PrusaSlicer or Bambu Studio: "
                        "right-click > Fix model; Meshmixer: Analysis > Inspector), then try again")
    open_mask = counts[eid] == 1
    if open_mask.any():
        loops = _open_loops(d, open_mask)
        small = loops is not None and all(len(lp) <= SMALL_HOLE for lp in loops)
        if not small:
            n_open = int(open_mask.sum())
            raise MeshError(f"open mesh: {n_open} edge(s) belong to one triangle only (holes in the surface), e.g. at "
                            f"{_where(verts, d[open_mask][:, 0])}. Only gaps of up to {SMALL_HOLE} edges are closed "
                            "automatically. Repair the mesh first (PrusaSlicer or Bambu Studio: right-click > Fix "
                            "model; Meshmixer: Analysis > Inspector > Auto Repair All), then try again")
        new = [(lp[0], lp[i + 1], lp[i]) for lp in loops for i in range(1, len(lp) - 1)]
        tris = np.concatenate([tris, np.array(new, dtype=tris.dtype).reshape(-1, 3)])
        repairs.append(f"closed {len(loops)} small hole(s) in the surface ({len(new)} triangle(s) added)")
        d, eid, counts = _edges(tris, len(verts))
        if (counts != 2).any():
            raise MeshError("open mesh: closing its small holes did not make it closed; repair it in a mesh tool first")
    tris, comp, flipped = _orient(tris, d, eid, verts)
    if flipped:
        repairs.append(f"turned {flipped} triangle(s) to face outward")
    return verts, tris, comp, repairs


def _opposite(a, b) -> bool:
    a, b = list(a), list(b)
    i = b.index(a[0])
    return b[(i + 1) % 3] == a[2]


def _orient(tris, d, eid, verts):
    """Flip triangles so neighbors traverse their shared edge in opposite directions, then each
    connected shell so it encloses positive volume. Returns (tris, component per tri, flipped)."""
    T = len(tris)
    order = np.argsort(eid, kind="stable")
    a, b = order[0::2], order[1::2]  # the two directed edges of each undirected edge
    ta, tb = a // 3, b // 3
    same = (d[a] == d[b]).all(axis=1)  # same direction: one of the two triangles must flip
    nbr = [[] for _ in range(T)]
    for x, y, s in zip(ta.tolist(), tb.tolist(), same.tolist()):
        nbr[x].append((y, s))
        nbr[y].append((x, s))
    flip = np.full(T, -1, np.int8)
    comp = np.full(T, -1, np.int64)
    ncomp = 0
    for s0 in range(T):
        if flip[s0] >= 0:
            continue
        flip[s0] = 0
        comp[s0] = ncomp
        stack = [s0]
        while stack:
            t = stack.pop()
            for u, s in nbr[t]:
                want = flip[t] ^ int(s)
                if flip[u] < 0:
                    flip[u] = want
                    comp[u] = ncomp
                    stack.append(u)
                elif flip[u] != want:
                    raise MeshError("the surface cannot be oriented (a Moebius-like or self-overlapping shell); "
                                    "repair the mesh in a mesh tool first")
        ncomp += 1
    tris = tris.copy()
    f = flip.astype(bool)
    tris[f] = tris[f][:, ::-1]
    t = verts[tris]
    vol = np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])) / 6.0
    cvol = np.bincount(comp, weights=vol, minlength=ncomp)
    inward = cvol[comp] < 0
    tris[inward] = tris[inward][:, ::-1]
    flipped = int((f ^ inward).sum())
    return tris, comp, flipped


# ---------------------------------------------------------------------------------------------
# Coplanar merge and the B-rep


def _neighbors(tris, nv):
    """(T, 3) the triangle across each edge of each triangle (closed manifold mesh)."""
    d, eid, _ = _edges(tris, nv)
    order = np.argsort(eid, kind="stable")
    a, b = order[0::2], order[1::2]
    nbr = np.empty(3 * len(tris), np.int64)
    nbr[a], nbr[b] = b // 3, a // 3
    return nbr.reshape(-1, 3), d


def coplanar_groups(verts, tris, normals, nbr, lin_tol=LIN_TOL, ang_tol=ANG_TOL, apart=None) -> np.ndarray:
    """Group id per triangle: connected triangles with (nearly) the same normal whose vertices all lie
    within lin_tol of the group's plane. A group failing the plane test is split back into triangles,
    and so are the triangles in `apart` (a boolean mask)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    T = len(tris)
    rows = np.repeat(np.arange(T), 3)
    cols = nbr.reshape(-1)
    flat = np.einsum("ij,ij->i", normals[rows], normals[cols]) > np.cos(ang_tol)
    if apart is not None:
        flat &= ~apart[rows] & ~apart[cols]
    g = coo_matrix((np.ones(int(flat.sum())), (rows[flat], cols[flat])), shape=(T, T))
    _, grp = connected_components(g, directed=False)
    sizes = np.bincount(grp)
    multi = np.flatnonzero(sizes > 1)
    if len(multi):
        # plane test per merged group: area-weighted normal, through the mean vertex
        t = verts[tris]
        area = 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        nsum = np.zeros((grp.max() + 1, 3))
        np.add.at(nsum, grp, normals * area[:, None])
        nrm = nsum / np.maximum(np.linalg.norm(nsum, axis=1)[:, None], 1e-30)
        csum = np.zeros((grp.max() + 1, 3))
        np.add.at(csum, grp, t.mean(1))
        ctr = csum / sizes[:, None]
        dist = np.abs(np.einsum("ijk,ik->ij", t - ctr[grp][:, None, :], nrm[grp])).max(1)
        worst = np.zeros(grp.max() + 1)
        np.maximum.at(worst, grp, dist)
        bad = worst > lin_tol
        if bad.any():
            nxt = grp.max() + 1
            for gi in np.flatnonzero(bad & (sizes > 1)):
                members = np.flatnonzero(grp == gi)
                grp[members[1:]] = np.arange(nxt, nxt + len(members) - 1)
                nxt += len(members) - 1
    _, grp = np.unique(grp, return_inverse=True)
    return grp.reshape(-1)


def _plane_basis(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def build_shape(verts, tris, comp, merge: bool = True, apart=None):
    """The B-rep: one planar face per coplanar group (or per triangle), shared edges, one shell and
    solid per connected component. Returns (TopoDS shape, stats)."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.Geom import Geom_Plane
    from OCP.gp import gp_Dir, gp_Pnt
    from OCP.TopoDS import TopoDS_Compound, TopoDS_Face, TopoDS_Shell, TopoDS_Solid, TopoDS_Vertex, TopoDS_Wire

    t = verts[tris]
    cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    area = 0.5 * np.linalg.norm(cr, axis=1)
    normals = cr / np.maximum(2 * area[:, None], 1e-30)
    nbr, d = _neighbors(tris, len(verts))
    grp = coplanar_groups(verts, tris, normals, nbr, apart=apart) if merge else np.arange(len(tris))
    ng = int(grp.max()) + 1
    sizes = np.bincount(grp, minlength=ng)

    # facets of curved surfaces: neighboring groups meeting at a shallow angle
    gn, ga = np.zeros((ng, 3)), np.bincount(grp, weights=area, minlength=ng)
    np.add.at(gn, grp, normals * area[:, None])
    gn /= np.maximum(np.linalg.norm(gn, axis=1)[:, None], 1e-30)
    ga_, gb_ = np.repeat(grp, 3), grp[nbr.reshape(-1)]
    cross = ga_ != gb_
    soft = cross & (np.einsum("ij,ij->i", gn[ga_], gn[gb_]) > np.cos(np.radians(SOFT_ANGLE)))
    soft_groups = np.unique(np.concatenate([ga_[soft], gb_[soft]]))
    faceted = {"faces": int(len(soft_groups)), "area_share": round(float(ga[soft_groups].sum() / ga.sum()), 3) if len(soft_groups) else 0.0}

    # vertices interior to a straight boundary between two merged faces are dropped
    vg = np.unique(np.stack([tris.reshape(-1), np.repeat(grp, 3)], axis=1), axis=0)
    ngroups = np.bincount(vg[:, 0], minlength=len(verts))
    single = np.zeros(len(verts), bool)
    single[vg[sizes[vg[:, 1]] == 1, 0]] = True
    maybe_drop = (ngroups == 2) & ~single

    B = BRep_Builder()
    V: dict[int, TopoDS_Vertex] = {}
    E: dict[tuple, object] = {}

    def vertex(i):
        v = V.get(i)
        if v is None:
            v = TopoDS_Vertex()
            B.MakeVertex(v, gp_Pnt(*map(float, verts[i])), OCC_TOL)
            V[i] = v
        return v

    def edge(i, j):
        k = (i, j) if i < j else (j, i)
        e = E.get(k)
        if e is None:
            e = BRepBuilderAPI_MakeEdge(vertex(k[0]), vertex(k[1])).Edge()
            B.UpdateEdge(e, OCC_TOL)  # merged faces' vertices are up to LIN_TOL off their plane
            E[k] = e
        return e if i < j else e.Reversed()

    def wire(loop):
        w = TopoDS_Wire()
        B.MakeWire(w)
        for i in range(len(loop)):
            B.Add(w, edge(loop[i], loop[(i + 1) % len(loop)]))
        w.Closed(True)
        return w

    def face(loops, n, p0):
        f = TopoDS_Face()
        B.MakeFace(f, Geom_Plane(gp_Pnt(*map(float, p0)), gp_Dir(*map(float, n))), OCC_TOL)
        for lp in loops:
            B.Add(f, wire(lp))
        return f

    # boundary loops of the merged groups
    loops_of: dict[int, list] = {}
    bmask = grp[nbr.reshape(-1)] != np.repeat(grp, 3)
    bt = np.repeat(np.arange(len(tris)), 3)[bmask]
    bd = d[bmask]
    bg = grp[bt]
    sel = sizes[bg] > 1
    by_group: dict[int, list] = {}
    for g, (a, b) in zip(bg[sel].tolist(), bd[sel].tolist()):
        by_group.setdefault(g, []).append((a, b))
    fallback = set()
    for g, edges_ in by_group.items():
        nxt = {}
        for a, b in edges_:
            if a in nxt:
                fallback.add(g)
                break
            nxt[a] = b
        if g in fallback:
            continue
        n = gn[g]
        u, w = _plane_basis(n)
        loops, seen, outer = [], set(), 0
        for start in nxt:
            if start in seen:
                continue
            lp, v = [], start
            while v not in seen:
                seen.add(v)
                lp.append(v)
                v = nxt[v]
            kept = []
            for k, v in enumerate(lp):
                if maybe_drop[v]:  # on a straight boundary between two merged faces: drop it if it is in line
                    p, q, r = verts[lp[k - 1]], verts[v], verts[lp[(k + 1) % len(lp)]]
                    if np.linalg.norm(np.cross(r - p, q - p)) <= LIN_TOL * np.linalg.norm(r - p) and np.dot(q - p, r - q) > 0:
                        continue
                kept.append(v)
            if len(kept) < 3:
                fallback.add(g)
                break
            P = verts[kept]
            x, y = P @ u, P @ w
            signed = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
            outer += signed > 0
            loops.append((signed, kept))
        if g in fallback or outer != 1:
            fallback.add(g)
            continue
        loops.sort(key=lambda s: -s[0])  # outer first
        loops_of[g] = [lp for _, lp in loops]
    merged = {}
    for g, loops in loops_of.items():
        f = face(loops, gn[g], verts[loops[0]].mean(0))
        if BRepCheck_Analyzer(f).IsValid():
            merged[g] = f
        else:
            fallback.add(g)
    if fallback:  # those groups go back to one face per triangle (and the vertices they dropped come back)
        if apart is not None:
            return build_shape(verts, tris, comp, merge=False)
        shape, stats = build_shape(verts, tris, comp, apart=np.isin(grp, list(fallback)))
        stats["fallback_groups"] = len(fallback)
        return shape, stats

    shells: dict[int, TopoDS_Shell] = {}

    def shell(c):
        s = shells.get(c)
        if s is None:
            s = TopoDS_Shell()
            B.MakeShell(s)
            shells[c] = s
        return s

    planar = 0
    first_tri = np.full(ng, -1)
    first_tri[grp[::-1]] = np.arange(len(tris))[::-1]
    for g in range(ng):
        ti = first_tri[g]
        if sizes[g] == 1:
            a, b, c = tris[ti].tolist()
            f = face([[a, b, c]], normals[ti], verts[a])
        else:
            f = merged[g]
            planar += 1
        B.Add(shell(int(comp[ti])), f)
    comp_shape = TopoDS_Compound()
    B.MakeCompound(comp_shape)
    solids = []
    for c, s in sorted(shells.items()):
        s.Closed(True)
        so = TopoDS_Solid()
        B.MakeSolid(so)
        B.Add(so, s)
        solids.append(so)
        B.Add(comp_shape, so)
    stats = {"faces_after": ng, "merged_faces": planar, "faceted": faceted, "fallback_groups": len(fallback)}
    return comp_shape, stats


# ---------------------------------------------------------------------------------------------
# Units and metadata


def step_units(path: Path) -> str:
    """The length unit a STEP file declares ("mm", "inch", "m", ...; "" if it does not say)."""
    head = path.read_bytes()[:2_000_000].decode("latin-1", errors="replace").upper()
    if re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'(INCH|IN)'", head):
        return "inch"
    if re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'(FOOT|FT)'", head):
        return "ft"
    m = re.search(r"SI_UNIT\s*\(\s*(\.\w+\.|\$)\s*,\s*\.METRE\.\s*\)", head)
    if m:
        return {".MILLI.": "mm", ".CENTI.": "cm", ".MICRO.": "micron", "$": "m"}.get(m.group(1), m.group(1).strip("."))
    return ""


def step_header(path: Path) -> dict:
    """FILE_NAME author / organization / originating system from a STEP header."""
    head = path.read_bytes()[:20_000].decode("latin-1", errors="replace")
    m = re.search(r"FILE_NAME\s*\((.*?)\);", head, re.S)
    if not m:
        return {}
    strs = re.findall(r"'((?:[^']|'')*)'", m.group(1))
    out = {}
    if len(strs) >= 3 and strs[2].strip():
        out["author"] = strs[2].strip()
    if len(strs) >= 4 and strs[3].strip():
        out["organization"] = strs[3].strip()
    if len(strs) >= 6 and strs[5].strip():
        out["system"] = strs[5].strip()
    return out


def metadata_3mf(path: Path) -> tuple[str, dict]:
    """(unit, metadata) of a 3MF's root model: Title, Designer, LicenseTerms, Copyright, ..."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".model") and n.startswith("3D/")), None)
        if not name:
            return "", {}
        with z.open(name) as f:
            unit, meta = "millimeter", {}
            for ev, el in ET.iterparse(f, events=("start",)):
                tag = el.tag.rsplit("}", 1)[-1]
                if tag == "model":
                    unit = el.get("unit", "millimeter")
                elif tag == "metadata" and el.get("name"):
                    meta[el.get("name")] = (el.text or "").strip()[:500]
                elif tag in ("resources", "build"):
                    break
    unit = {"millimeter": "mm", "centimeter": "cm", "meter": "m", "inch": "inch", "foot": "ft", "micron": "micron"}.get(unit, unit)
    keep = ("Title", "Designer", "Description", "Copyright", "LicenseTerms", "License", "Origin", "Application", "CreationDate")
    return unit, {k: v for k, v in meta.items() if k in keep and v}


def unit_warnings(size, units: str) -> list[str]:
    big = float(max(size))
    if big < SMALL_PART:
        alt = ", ".join(f"x{f:g} = {big * f:.1f} mm" for f in (25.4, 10.0))
        return [f"largest side is only {big:.3g} mm: the file may be in inches or cm ({alt}). If so, pass "
                f"scale='inch' (or scale='cm' / a number) to import_model"]
    if big > LARGE_PART:
        return [f"largest side is {big:.0f} mm: the file may be in microns or 0.1 mm units; if so, pass "
                f"scale=0.001 (or another factor) to import_model"]
    return []


def _scale_factor(scale) -> float:
    if isinstance(scale, str):
        if scale not in UNITS:
            raise ValueError(f"scale {scale!r}: a number or one of {sorted(UNITS)}")
        return UNITS[scale]
    f = float(scale)
    if not f > 0:
        raise ValueError(f"scale must be positive, got {scale!r}")
    return f


# ---------------------------------------------------------------------------------------------
# Loading


def max_triangles_setting(start=None) -> int:
    from .config import load_settings

    return int(load_settings(start).max_triangles)


def load(path: str | Path, scale=1.0, max_triangles: int | None = None, merge: bool = True):
    """Read a model file into (Part, ImportInfo); no caching. Raises MeshError / ValueError."""
    from build123d import Compound, Part, import_step, scale as b3d_scale
    from OCP.BRepCheck import BRepCheck_Analyzer

    from .compare import MAX_FILE_BYTES, load_mesh

    path = Path(path)
    t0 = time.time()
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError(f"{path.name}: use {', '.join(SUFFIXES)}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name}: larger than {MAX_FILE_BYTES // 1_000_000} MB")
    factor = _scale_factor(scale)
    if suffix in (".step", ".stp"):
        units = step_units(path)
        shape = import_step(path)  # OCC converts the file's units to mm
        solids = shape.solids()
        if not solids:
            raise MeshError(f"{path.name}: the STEP file has no solids (only surfaces?); export it as a solid body")
        part = Part(Compound(solids).wrapped)
        if factor != 1.0:
            part = Part(Compound(b3d_scale(part, factor).solids()).wrapped)
        info = ImportInfo(file=str(path), format="step", units=units or "not stated", scale=factor,
                          faces_before=len(part.faces()), metadata=step_header(path))
        info.faces_after = info.faces_before
        info.planar_faces = sum(f.geom_type.name == "PLANE" for f in part.faces())
        if units and units != "mm":
            info.notes.append(f"the STEP file is in {units}; it was converted to mm on import")
    else:
        mesh = load_mesh(path)
        units, meta = metadata_3mf(path) if suffix == ".3mf" else ("none (STL has no units: read as mm)", {})
        limit = max_triangles if max_triangles is not None else max_triangles_setting(path)
        if len(mesh.tris) > limit:
            raise MeshError(f"{path.name} has {len(mesh.tris):,} triangles, over the limit of {limit:,} (the "
                            "max_triangles setting). Converting and checking a mesh that fine is slow and gains "
                            "nothing for printing: simplify it first (Blender: Decimate modifier; Meshmixer: "
                            "Select all > Reduce; PrusaSlicer: right-click > Simplify model) to under the "
                            "limit, or raise max_triangles")
        verts = mesh.verts * factor
        size = mesh.size * factor
        verts, tris, comp, repairs = repair(verts, mesh.tris, weld_tol=1e-6 * max(1.0, float(size.max())))
        shape, stats = build_shape(verts, tris, comp, merge=merge)
        part = Part(shape)
        info = ImportInfo(file=str(path), format=suffix[1:], units=units, scale=factor, triangles=int(len(mesh.tris)),
                          repairs=repairs, faces_before=int(len(tris)), faces_after=stats["faces_after"],
                          planar_faces=stats["faces_after"] - stats["faceted"]["faces"], faceted=stats["faceted"],
                          metadata=meta)
        if stats["fallback_groups"]:
            info.repairs.append(f"{stats['fallback_groups']} coplanar region(s) kept as triangles (their outline was not simple)")
        if not BRepCheck_Analyzer(shape).IsValid():
            raise MeshError(f"{path.name}: the solid built from the mesh is not valid (self-intersecting triangles?); "
                            "repair the mesh in a mesh tool first")
    if part.volume <= 0:
        raise MeshError(f"{path.name}: the result has no volume")
    bb = part.bounding_box()
    info.size = [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)]
    info.volume = round(part.volume, 2)
    info.solids = len(part.solids())
    if factor == 1.0:
        info.warnings += unit_warnings(info.size, info.units)
    if info.faceted.get("faces"):
        info.notes.append(f"{info.faceted['faces']} faces ({info.faceted['area_share']:.0%} of the surface) are facets of "
                             "curved surfaces: curves stay faceted (no curve fitting). To make a hole or fillet "
                             "round again, cut it again as a real cylinder, or redraw the part")
    info.seconds = round(time.time() - t0, 2)
    return part, info


def _cache_key(path: Path, factor: float, merge: bool) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(f"|{factor!r}|{merge}|{CONVERTER}".encode())
    return h.hexdigest()[:32]


def _caller_file() -> str | None:
    f = sys._getframe(2)
    while f is not None:
        name = f.f_globals.get("__name__", "")
        if not name.startswith("b123d_print."):
            return f.f_globals.get("__file__")
        f = f.f_back
    return None


def resolve(path: str | Path, script: str | Path | None) -> Path:
    """A reference file for a part script: relative paths are looked up in the script's folder
    (`ref/x.stl` is <parts_dir>/<part>/ref/x.stl), then in the workspace (`refs/x.stl`). The file
    must be inside the workspace (without one, inside the script's folder) and not a symlink."""
    from .config import find_workspace

    base = Path(script).resolve().parent if script else Path.cwd().resolve()
    root = find_workspace(base) or base
    root = Path(os.path.realpath(root))
    p = Path(path)
    cands = [p] if p.is_absolute() else [base / p, root / p]
    for c in cands:
        if os.path.lexists(c):
            if Path(c).is_symlink():
                raise ValueError(f"{path}: refusing a symlink; copy the file into {REF_DIR}/ instead")
            real = Path(os.path.realpath(c))
            if not real.is_relative_to(root):
                raise ValueError(f"{path}: outside the workspace ({root}); put reference files in "
                                 f"<parts_dir>/<part>/{REF_DIR}/ or {SHARED_DIR}/")
            if not real.is_file():
                raise ValueError(f"{path}: not a file")
            return real
    raise FileNotFoundError(f"no reference file {str(path)!r} (looked in {base} and {root}); put it in "
                            f"{base / REF_DIR}/ (b123d-print push, or the upload_reference tool)")


def import_model(path: str | Path, scale=1.0, max_triangles: int | None = None, merge: bool = True,
                 script: str | Path | None = None):
    """Load an STL, 3MF or STEP file as a build123d Part, ready to change: `base = import_model("ref/x.stl")`.

    path: relative to the part script's folder (ref/...) or the workspace (refs/...).
    scale: a factor or a unit the file was drawn in ('inch', 'cm', ...), for files that are not mm.
    max_triangles: refuse meshes with more (default: the max_triangles setting).
    merge: merge coplanar triangles into faces (default True).
    script: the part script (default: the caller's __file__).
    The conversion is cached in the script's out/.cache/; the result is recorded so the checks can
    tell findings the original already had from new ones."""
    from build123d import Part, import_brep

    script = script or _caller_file()
    src = resolve(path, script)
    factor = _scale_factor(scale)
    cache = Path(script).resolve().parent / "out" / ".cache" if script else None
    part = info = None
    if cache is not None:
        key = _cache_key(src, factor, merge)
        brep, meta = cache / f"{key}.brep", cache / f"{key}.json"
        if brep.is_file() and meta.is_file():
            try:
                info = ImportInfo(**json.loads(meta.read_text(encoding="utf-8")))
                part = Part(import_brep(brep).wrapped)
                info.cached = True
            except Exception:  # noqa: BLE001 - a broken cache entry is rebuilt
                part = info = None
    if part is None:
        part, info = load(src, factor, max_triangles, merge)
        if cache is not None:
            try:
                from build123d import export_brep

                cache.mkdir(parents=True, exist_ok=True)
                tmp = cache / f".{key}.{os.getpid()}.tmp"
                export_brep(part, tmp)
                os.replace(tmp, brep)
                meta.write_text(json.dumps(asdict(info)), encoding="utf-8")
            except Exception:  # noqa: BLE001 - no cache (read-only folder): convert every time
                pass
    info.file = os.path.relpath(src, Path(script).resolve().parent) if script else str(src)
    IMPORTED.append((part, info))
    return part


# ---------------------------------------------------------------------------------------------
# Describing a model


def circle_fit(pts: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Least-squares circle through 2D points: (center, radius, rms residual)."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.stack([x, y, np.ones_like(x)], axis=1)
    b = x * x + y * y
    (a, bb, c), *_ = np.linalg.lstsq(A, b, rcond=None)  # x^2 + y^2 = a x + b y + c
    cx, cy = a / 2, bb / 2
    r = float(np.sqrt(max(c + cx * cx + cy * cy, 0.0)))
    res = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - r) ** 2)))
    return np.array([cx, cy]), r, res


def section_holes(part, cap: int = 12) -> list[dict]:
    """Round holes found as round inner outlines of sections across each axis (works on faceted
    meshes too), cut halfway between the flat faces along that axis: [{"d", "axis", "center", "found_at"}]."""
    from .checks import section_levels
    from .render import AXES, section_faces

    bb = part.bounding_box()
    found = []
    for plane, ax in AXES.items():
        others = [i for i in range(3) if i != ax]
        span = (bb.size.X, bb.size.Y, bb.size.Z)[ax]
        for at in section_levels(part, plane, step=span / 3 + 1e-6, cap=cap):
            for face in section_faces(part, plane, at):
                for w in face.inner_wires():
                    pts = np.array([[v.X, v.Y, v.Z] for v in w.vertices()])
                    if len(pts) < 6:
                        edges = w.edges()
                        if not (len(edges) <= 2 and all(e.geom_type.name == "CIRCLE" for e in edges)):
                            continue
                        pts = np.array([[p.X, p.Y, p.Z] for e in edges for p in (e @ t for t in np.linspace(0, 1, 9))])
                    c2, r, res = circle_fit(pts[:, others])
                    if r <= 0 or res > 0.02 * r + 0.01:
                        continue
                    c3 = np.zeros(3)
                    c3[others] = c2
                    c3[ax] = at
                    axis = [0, 0, 0]
                    axis[ax] = 1
                    hit = next((h for h in found if h["axis"] == axis and abs(h["d"] - 2 * r) < 0.2
                                and np.hypot(*(np.array(h["center"])[others] - c2)) < 0.3), None)
                    if hit:
                        hit["found_at"].append(round(float(at), 2))
                    else:
                        found.append({"d": round(2 * r, 2), "axis": axis, "center": [round(float(x), 2) for x in c3],
                                      "found_at": [round(float(at), 2)]})
    return found


def describe(path: str | Path, scale=1.0, max_triangles: int | None = None) -> tuple[dict, object]:
    """Everything worth knowing before remixing a file: format, units, size, faces before/after the
    merge, curved (faceted) share, round holes, metadata (designer, license) and a suggestion
    whether to modify it or redraw it. Returns (summary, part)."""
    from .checks import holes as exact_holes

    part, info = load(path, scale, max_triangles)
    exact = [{k: v for k, v in h.items() if k != "faces"} for h in exact_holes(part)]
    found = exact if exact else section_holes(part)
    out = {k: v for k, v in asdict(info).items() if k not in ("cached",)}
    out["file"] = Path(path).name
    out["holes"] = found[:24]
    out["holes_note"] = ("exact cylinders" if exact else
                         "from round outlines in sections across each axis (faceted on a mesh: cut them again as "
                         "real cylinders to change them)") if found else "no round holes found"
    out["suggestion"] = suggest(info)
    out["license_note"] = ("record the source URL, the author and the license in the script's docstring; "
                           "check the license before remixing (-ND: no remixes allowed; -NC: no commercial use; "
                           "BY: credit the author)")
    return out, part


def suggest(info: ImportInfo) -> dict:
    """MODIFY (load the original and change it) or REDRAW (model it again parametrically), with why."""
    if info.format == "step":
        return {"path": "modify", "why": "STEP is an exact solid: load it and change it; nothing is lost"}
    share = info.faceted.get("area_share", 0.0)
    if share > 0.3 or info.faces_after > 400:
        return {"path": "modify", "why": f"{share:.0%} of the surface is curved (faceted) or the model is detailed "
                f"({info.faces_after} faces): redrawing it would lose detail; load it and change it"}
    return {"path": "modify or redraw", "why": f"mostly flat ({info.planar_faces} planar faces, {share:.0%} curved): "
            "modify for small changes (a hole, a boss, a cut); offer a parametric REDRAW if proportions change "
            "(longer, wider, another screw size), verified against the original with compare"}


# ---------------------------------------------------------------------------------------------
# Inherited findings


INHERITABLE = ("overhang", "bridge", "thin", "holes", "bed edge", "gap")
MATCH_MM = 1.5  # an item of a finding counts as the original's when one of the original's is this close


def _items(f) -> list[np.ndarray]:
    """The located items of a finding (face centers, thin spots, holes), as points."""
    d = f.data or {}
    keys = {"overhang": ("faces",), "bridge": ("bridges",), "thin": ("spots",), "holes": ("round_top", "small"),
            "bed edge": ("faces",)}.get(f.check, ())
    pts = []
    for k in keys:
        for it in d.get(k) or []:
            p = it.get("center") or it.get("at")
            if p is not None and len(p) == 3:
                pts.append(np.asarray(p, float))
    return pts


def _kind(f) -> str:
    """Findings of one check that report different things (thin walls vs knife edges, round-topped vs small holes)."""
    m = f.message
    if f.check == "thin":
        return "edge" if "knife edge" in m else "wall"
    if f.check == "holes":
        return "small" if "under" in m and "too small" in m else "round"
    return ""


def mark_inherited(findings: list, original: list) -> list:
    """Label the findings the original already had: all of a finding's items (spots, faces, holes)
    within MATCH_MM of the original's -> one inherited finding (WARN at most: it is not the
    remix's to fix); some of them -> the finding stays, saying which are new. Others are new."""
    from .checks import FAIL, OK, WARN, Finding

    orig = {}
    for f in original:
        if f.level != OK and f.check in INHERITABLE:
            orig.setdefault((f.check, _kind(f)), []).extend(_items(f) or [None])
    out = []
    for f in findings:
        key = (f.check, _kind(f))
        if f.level == OK or f.check not in INHERITABLE or key not in orig:
            out.append(f)
            continue
        mine = _items(f)
        theirs = [p for p in orig[key] if p is not None]
        if not mine:  # nothing located (a gap between solids): same check failing on both
            inherited = [True]
        else:
            inherited = [bool(theirs) and min(float(np.linalg.norm(p - q)) for q in theirs) <= MATCH_MM for p in mine]
        if all(inherited):
            level = WARN if f.level == FAIL else f.level
            note = " (a FAIL on the original too)" if f.level == FAIL else ""
            out.append(Finding(level, f.check, f.target, f"inherited from the original{note}: {f.message}",
                               {**f.data, "inherited": True}))
        elif any(inherited):
            new = [p for p, i in zip(mine, inherited) if not i]
            where = "; ".join("(" + ", ".join(f"{x:.4g}" for x in p) + ")" for p in new[:4])
            out.append(Finding(f.level, f.check, f.target,
                               f"{f.message} [{sum(inherited)} of {len(mine)} listed spots inherited from the original; "
                               f"new in the remix: {where}]", {**f.data, "inherited": "partly"}))
        else:
            out.append(f)
    return out
