"""Built-in print checks.

- overlap:  intersection volume between parts in their assembled position (incl. stand-ins).
- overhang: downward-facing surfaces in print orientation, angle measured from vertical
            (vertical wall = 0 deg, flat ceiling/bridge = 90 deg). The bed face is ignored.
            Flat ceilings are bridges (held on two opposite sides; span measured) or cantilevers.
- wall:     thinnest material in a cross-section, optionally only around a point (a hole, a
            counterbore, a dimple). Use it wherever a cut goes deeper than the wall it starts
            in: `is_valid` and hole-diameter checks do not catch a 0.05 mm skin.
- thin:     the same measurement on sections all over the part: thinner than a line width fails.
- holes:    round holes; horizontal ones with a round top sag, tiny ones do not print round.
- bed edge: fillets that start on the bed flare.
- gap:      distance between parts, or between solids printed in place.

The rules behind each check are in docs/BEST_PRACTICES.md; `BP-<id>` comments cite them.
Part scripts declare checks with the spec classes (`Wall`, `Overhang`, `Probe`, `Gap`, ...) from
a `checks(d)` function; `b123d-print check` runs them (see b123d_print.project), adding the
automatic ones for every part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import numpy as np
from build123d import Part

from .render import AXES, section_faces, tessellate

FAIL, WARN, OK = "fail", "warn", "ok"
CORNER = 4.0  # see wall_thickness
REACH = 2.0  # mm: first round of wall_thickness's ray cast (see _face_thinnest)
CHUNK = 128  # rays cast at once (fewer: a tighter box around them, so fewer segments to test)
PARALLEL = float(np.cos(np.radians(10)))  # walls whose normals are within 10 deg of opposite are parallel


@dataclass
class Finding:
    level: str  # "ok" | "warn" | "fail"
    check: str  # "overlap" | "overhang" | "wall" | "valid" | "error"
    target: str  # part name(s)
    message: str
    data: dict = field(default_factory=dict)

    def line(self) -> str:
        return f"[{self.level.upper():4}] {self.check:8} {self.target}: {self.message}"


# ---------------------------------------------------------------------------------------------
# Overlap


def overlap(parts: list[tuple[Part, str]], tol: float = 0.01, ignore=()) -> list[Finding]:
    """Pairwise intersection volume (mm^3) of [(part, label)]; > tol is a failure.
    ignore: label pairs that are meant to overlap (e.g. a screw stand-in in its hole)."""
    skip = {frozenset(p) for p in ignore}
    out = []
    for (a, an), (b, bn) in combinations(parts, 2):
        if frozenset((an, bn)) in skip:
            continue
        if not _bbox_overlap(a, b):
            v = 0.0
        else:
            v = (a & b).volume
        level = FAIL if v > tol else OK
        msg = f"intersect {v:.3f} mm^3" if v > tol else "no overlap"
        out.append(Finding(level, "overlap", f"{an} / {bn}", msg, {"volume": round(v, 4)}))
    return out


def _bbox_overlap(a: Part, b: Part) -> bool:
    ba, bb = a.bounding_box(), b.bounding_box()
    amin, amax, bmin, bmax = (tuple(v) for v in (ba.min, ba.max, bb.min, bb.max))
    return all(amin[i] <= bmax[i] and bmin[i] <= amax[i] for i in range(3))


# ---------------------------------------------------------------------------------------------
# Overhang, bridges, holes, bed edges


def _down_tris(face, tol: float = 0.05):
    """Tessellated face: (triangles (n,3,3), unit normals pointing out of the material, areas,
    angle from vertical of each downward normal in degrees: 0 = wall, 90 = ceiling)."""
    v, tris = tessellate(face, tol, 0.1)
    if not len(tris):
        return None
    tri = v[tris]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    keep = area > 1e-9
    if not keep.any():
        return None
    tri, n, area = tri[keep], n[keep], area[keep]
    n = n / (2 * area[:, None])
    # orient the triangles with the face (tessellation winding is not guaranteed outward)
    c = tri[0].mean(0)
    fn = face.normal_at(face.center()) if face.geom_type.name == "PLANE" else face.normal_at(_vec(c))
    if np.dot(n[0], [fn.X, fn.Y, fn.Z]) < 0:
        n = -n
    nz = np.clip(n[:, 2], -1, 1)
    ang = np.degrees(np.arcsin(np.clip(-nz, 0, 1)))
    return tri, n, area, ang


def _cylinder(face):
    """(axis direction, a point on the axis, radius) of a cylindrical face; the direction points up
    (or +Y, +X when horizontal) so both halves of a split hole agree."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    c = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax = c.Axis()
    d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
    loc = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
    for k in (2, 1, 0):
        if abs(d[k]) > 1e-9:
            if d[k] < 0:
                d = -d
            break
    return d, loc, c.Radius()


def _concave(face, d, loc) -> bool:  # also used by fit._cyl_axes
    """A cylindrical face curving around empty space (a hole, a concave fillet)."""
    p = face.position_at(0.5, 0.5)
    n = face.normal_at(0.5, 0.5)
    p = np.array([p.X, p.Y, p.Z]) - loc
    radial = p - np.dot(p, d) * d
    return float(np.dot([n.X, n.Y, n.Z], radial)) < 0


def holes(part: Part) -> list[dict]:
    """Round holes: concave cylindrical faces grouped by axis and radius, covering at least
    260 deg around (a full hole, or a teardrop's 270 deg; fillets and arched roofs cover less).
    Each: {"d", "axis": [x,y,z], "vertical", "center", "length", "span" deg, "faces"}."""
    from OCP.BRepTools import BRepTools

    groups: dict = {}
    for f in part.faces():
        if f.geom_type.name != "CYLINDER":
            continue
        d, loc, r = _cylinder(f)
        if not _concave(f, d, loc):
            continue
        foot = loc - np.dot(loc, d) * d  # axis point closest to the origin: same for both halves
        key = (*np.round(d, 3), *np.round(foot, 2), round(r, 3))
        u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
        g = groups.setdefault(key, {"d": 2 * r, "axis": d, "foot": foot, "span": 0.0, "v": [], "faces": []})
        g["span"] += np.degrees(u1 - u0)
        g["v"] += [v0, v1]
        g["faces"].append(f)
    out = []
    for g in groups.values():
        if g["span"] < 260:
            continue
        d, foot = g["axis"], g["foot"]
        loc = np.array([[c.X, c.Y, c.Z] for c in (f.center() for f in g["faces"])]).mean(0)
        center = foot + np.dot(loc - foot, d) * d
        out.append({
            "d": round(g["d"], 3),
            "axis": [round(float(x), 3) for x in d],
            "vertical": bool(abs(d[2]) > 0.98),
            "center": [round(float(x), 2) for x in center],
            "length": round(float(max(g["v"]) - min(g["v"])), 2),
            "span": round(float(min(g["span"], 360.0)), 1),
            "faces": g["faces"],
        })
    out.sort(key=lambda h: (h["center"][2], h["center"][1], h["center"][0]))
    return out


BRIDGE_TOL = 1.0  # mm: a flat ceiling this close to a wall it rests on counts as supported


def _edge_faces(part: Part) -> dict:
    """hash(edge) -> the faces that share it."""
    m: dict = {}
    for f in part.faces():
        for e in f.edges():
            m.setdefault(hash(e), []).append(f)
    return m


class Inside:
    """solid.is_inside(point) (inside or on a face) with one OCC classifier for the solid:
    Shape.is_inside builds a new one per call, which costs about as much as the test."""

    def __init__(self, solid: Part):
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier

        self.c = BRepClass3d_SolidClassifier(solid.wrapped)

    def __call__(self, x: float, y: float, z: float) -> bool:
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN

        self.c.Perform(gp_Pnt(float(x), float(y), float(z)), 1e-6)
        return self.c.State() == TopAbs_IN or self.c.IsOnAFace()


def bridge_span(face, solid: Part, step: float | None = None, rays: int = 24, edge_faces: dict | None = None,
                inside: Inside | None = None) -> dict:
    """How a flat downward face (a ceiling) of `solid` is held. An edge is anchored when there is
    material just beyond it and just below the ceiling (a wall the bridge rests on), or when the
    face next to it carries on tangentially and curves down (a rounded corner into a wall). From points on a grid over the face,
    rays find the boundary in `rays` directions; a point is bridged when two opposite rays both
    end on anchored edges, and its span is the sum of the two. Returns {"span": mm (longest
    bridged span), "hanging": mm (how far unbridged material reaches from an anchor, 0 if none),
    "kind": "bridge" | "cantilever"}. inside: the solid's Inside, when already made."""
    z = face.center().Z
    area = face.area
    st = step or max(0.25, min(1.0, np.sqrt(area) / 40))
    edges, loops = [], []
    for w in [face.outer_wire(), *face.inner_wires()]:
        pts = []
        for e in wire_edges(w):
            xy = [(p[0], p[1]) for p in edge_points(e, st).tolist()]
            if pts and np.hypot(xy[0][0] - pts[-1][0], xy[0][1] - pts[-1][1]) > np.hypot(xy[-1][0] - pts[-1][0], xy[-1][1] - pts[-1][1]):
                xy.reverse()
            edges.append((e, xy))
            pts.extend(xy if not pts else xy[1:])
        if len(pts) >= 3:
            loops.append(np.array(pts))
    if not edges or not loops:
        return {"span": 0.0, "hanging": 0.0, "kind": "bridge"}
    from matplotlib.path import Path as MPath

    paths = [MPath(lp) for lp in loops]

    def in_face(pt) -> bool:
        return bool(paths[0].contains_point(pt)) and not any(p.contains_point(pt) for p in paths[1:])

    if edge_faces is None:
        edge_faces = _edge_faces(solid)
    if inside is None:
        inside = Inside(solid)
    segs, anchored = [], []
    for e, xy in edges:
        # anchored: just beyond the edge (away from the ceiling) and just below it is material
        m = e.position_at(0.5)
        tg = e.tangent_at(0.5)
        perp = np.array([-tg.Y, tg.X])
        nrm = np.linalg.norm(perp)
        anch = False
        if nrm > 1e-9:
            perp /= nrm
            eps = 0.05
            out = -perp if in_face((m.X + perp[0] * eps, m.Y + perp[1] * eps)) else perp
            anch = inside(m.X + out[0] * eps, m.Y + out[1] * eps, z - eps)
            if not anch:  # tangent continuation curving down: the rounded top corner of a window
                for g in edge_faces.get(hash(e), []):
                    if g.is_same(face) or g.geom_type.name == "PLANE" or g.bounding_box().min.Z > z - 0.3:
                        continue
                    if g.normal_at(m).Z < -0.98:
                        anch = True
        for p0, p1 in zip(xy, xy[1:]):
            segs.append((p0, p1))
            anchored.append(anch)
    segs, anchored = np.array(segs), np.array(anchored)
    if not anchored.any():
        return {"span": 0.0, "hanging": float("inf"), "kind": "cantilever"}
    from matplotlib.path import Path as MPath

    lo, hi = loops[0].min(0), loops[0].max(0)
    g = max(0.2, np.sqrt(area / 400))
    gx, gy = np.meshgrid(np.arange(lo[0] + g / 2, hi[0], g), np.arange(lo[1] + g / 2, hi[1], g))
    pts = np.c_[gx.ravel(), gy.ravel()]
    inside = MPath(loops[0]).contains_points(pts)
    for lp in loops[1:]:
        inside &= ~MPath(lp).contains_points(pts)
    pts = pts[inside]
    if not len(pts):
        c = face.center()
        pts = np.array([[c.X, c.Y]])
    a, d = segs[:, 0], segs[:, 1] - segs[:, 0]
    th = np.linspace(0, 2 * np.pi, rays, endpoint=False)
    dirs = np.c_[np.cos(th), np.sin(th)]
    t_hit = np.full((len(pts), rays), np.inf)
    a_hit = np.zeros((len(pts), rays), bool)
    for k, r in enumerate(dirs):
        denom = r[0] * d[:, 1] - r[1] * d[:, 0]
        w = a[None] - pts[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (w[..., 0] * d[None, :, 1] - w[..., 1] * d[None, :, 0]) / denom[None]
            s = (w[..., 0] * r[1] - w[..., 1] * r[0]) / denom[None]
        t = np.where((np.abs(denom)[None] > 1e-12) & (t > 1e-9) & (s >= -1e-9) & (s <= 1 + 1e-9), t, np.inf)
        j = t.argmin(1)
        t_hit[:, k] = t[np.arange(len(pts)), j]
        a_hit[:, k] = anchored[j] & np.isfinite(t_hit[:, k])
    half = rays // 2
    both = a_hit[:, :half] & a_hit[:, half:]
    sums = np.where(both, t_hit[:, :half] + t_hit[:, half:], np.inf)
    span_pt = sums.min(1)
    to_anchor = np.where(a_hit, t_hit, np.inf).min(1)
    hanging = ~np.isfinite(span_pt) & (to_anchor > BRIDGE_TOL)
    span = float(span_pt[np.isfinite(span_pt)].max(initial=0.0))
    hang = float(to_anchor[hanging].max(initial=0.0)) if hanging.any() else 0.0
    return {"span": round(span, 2), "hanging": round(hang, 2) if np.isfinite(hang) else hang,
            "kind": "cantilever" if hanging.any() else "bridge"}


def overhang_faces(part: Part, max_angle: float = 45.0, bed_tol: float = 0.05, tol: float = 0.05, angle_tol: float = 0.5,
                   ignore_below: float = 0.0) -> dict:
    """Downward faces steeper than max_angle from vertical, part in print orientation (bed at min Z).

    Returns {"faces": [...], "area": total flagged mm^2, "max_angle": deg}. Each face entry has
    its flagged area, max angle, Z range, center and kind: "bridge" (a flat ceiling resting on
    walls; with its "span"), "cantilever" (a flat ceiling not held on two opposite sides; with how
    far it "hangs"), "hole" (the top of a horizontal round hole) or the surface type.
    Faces lying on the bed are ignored. angle_tol absorbs tessellation noise on surfaces designed
    at exactly max_angle. ignore_below: skip triangles lying entirely within this height above the bed."""
    zmin = part.bounding_box().min.Z
    found = []
    edge_faces = inside = None
    hole_faces = None
    for face in part.faces():
        t = _down_tris(face, tol)
        if t is None:
            continue
        tri, n, area, ang = t
        nz = n[:, 2]
        down = nz < 0
        on_bed = (tri[:, :, 2].max(1) < zmin + bed_tol) & (nz < -0.99)
        low = tri[:, :, 2].max(1) < zmin + ignore_below
        flag = down & ~on_bed & ~low & (ang > max_angle + angle_tol)
        if not flag.any():
            continue
        fz = tri[flag][:, :, 2]
        fa = area[flag]
        centers = tri[flag].mean(1)
        ctr = (centers * fa[:, None]).sum(0) / fa.sum()
        entry = {
            "area": round(float(fa.sum()), 2),
            "max_angle": round(float(ang[flag].max()), 1),
            "z": [round(float(fz.min()), 2), round(float(fz.max()), 2)],
            "center": [round(float(x), 2) for x in ctr],
            "kind": face.geom_type.name.lower(),
        }
        if ang[flag].min() > 89 and face.geom_type.name == "PLANE":
            edge_faces = edge_faces if edge_faces is not None else _edge_faces(part)
            inside = inside or Inside(part)
            entry.update(bridge_span(face, part, edge_faces=edge_faces, inside=inside))  # kind "bridge" or "cantilever"
        elif face.geom_type.name == "CYLINDER":
            if hole_faces is None:
                hole_faces = {hash(f) for h in holes(part) if not h["vertical"] for f in h["faces"]}
            if hash(face) in hole_faces:
                entry["kind"] = "hole"
        found.append(entry)
    found.sort(key=lambda f: -f["area"])
    return {
        "faces": found,
        "area": round(sum(f["area"] for f in found), 2),
        "max_angle": max((f["max_angle"] for f in found), default=0.0),
    }


def round_topped_holes(part: Part, max_angle: float = 45.0, min_d: float = 0.0, min_area: float = 0.2,
                       angle_tol: float = 0.5) -> list[dict]:
    """Holes whose axis is not vertical and whose top is round: some of the hole wall faces down
    steeper than max_angle, so it sags. A teardrop (pointed 45 deg roof) or a flat bridged roof
    does not; neither does a vertical hole."""
    out = []
    for h in holes(part):
        if h["vertical"] or h["d"] < min_d:
            continue
        steep = 0.0
        for f in h["faces"]:
            t = _down_tris(f)
            if t is not None:
                tri, n, area, ang = t
                steep += float(area[(n[:, 2] < 0) & (ang > max_angle + angle_tol)].sum())
        if steep >= min_area:
            out.append({**h, "steep_area": round(steep, 2)})
    return out


def bed_fillets(part: Part, max_angle: float = 45.0, bed_tol: float = 0.05, min_area: float = 0.2,
                angle_tol: float = 0.5) -> list[dict]:
    """Curved faces that start on the bed and face down steeper than max_angle: a fillet (or any
    rounding) on a bed edge. Its lowest band is a near-flat overhang that flares and lifts."""
    zmin = part.bounding_box().min.Z
    out = []
    for f in part.faces():
        if f.geom_type.name == "PLANE" or f.bounding_box().min.Z > zmin + bed_tol:
            continue
        t = _down_tris(f)
        if t is None:
            continue
        tri, n, area, ang = t
        flag = (n[:, 2] < 0) & (ang > max_angle + angle_tol) & (tri[:, :, 2].min(1) < zmin + 0.5 * f.bounding_box().size.Z + bed_tol)
        if area[flag].sum() < min_area:
            continue
        c = f.center()
        out.append({"kind": f.geom_type.name.lower(), "area": round(float(area[flag].sum()), 2),
                    "max_angle": round(float(ang[flag].max()), 1), "height": round(f.bounding_box().size.Z, 2),
                    "center": [round(c.X, 2), round(c.Y, 2), round(c.Z, 2)]})
    return out


# ---------------------------------------------------------------------------------------------
# Tip-over: how well the first layer holds a tall part


# BP-B6. OrcaSlicer's (and Bambu Studio's) Auto brim, src/libslic3r/Brim.cpp: brim width =
# speed x H^2 x W / (1920 I), with I the first layer's second moment of area and W its width
# across that axis; under 5 mm it makes no brim. The same file adds 5 mm of brim to a part over
# 10 mm tall whose footprint islands have area / perimeter under 1.1 mm.
TIP_BRIM = 5.0  # mm: the auto-brim estimate from which a part counts as tippy
TIP_HEIGHT = 10.0  # mm: lower parts are not checked
TIP_STRIP = 1.1  # mm: area / perimeter of a footprint island under which its contact is a thin strip


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull of 2D points, counter-clockwise (monotone chain)."""
    p = np.unique(np.round(pts, 6), axis=0)
    if len(p) < 3:
        return p

    def half(seq):
        out: list = []
        for q in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (q[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(q)
        return out[:-1]

    return np.array(half(p) + half(p[::-1]))


def footprint(faces: list, height: float, speed: float = 200.0, com=None) -> dict:
    """The first layer of a part (faces: a MeshSlicer section near the bed, [outer, holes...] per
    island) and what it says about a part `height` tall: contact area, narrowest width of its
    convex hull, height / that width, the auto-brim estimate (TIP_BRIM; about the footprint's
    weaker principal axis, so it does not depend on how the part is turned on the bed), the thinnest island
    (area / perimeter, TIP_STRIP) and whether the centre of mass `com` (x, y) is over the hull."""
    loops = [lp for f in faces for lp in f]
    out = {"area": 0.0, "height": round(height, 2), "width": 0.0, "length": 0.0, "ratio": float("inf"), "brim": float("inf"),
           "islands": len(faces), "strip": 0.0, "com_inside": None}
    if not loops:
        return out
    ref = np.concatenate(loops).mean(0)
    A = cx = cy = Sxx = Syy = Sxy = 0.0
    for lp in loops:  # outer loops CCW, holes CW: signed sums subtract the holes
        x, y = (lp - ref).T
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        c = x * y1 - x1 * y
        A += c.sum() / 2
        cx += ((x + x1) * c).sum() / 6
        cy += ((y + y1) * c).sum() / 6
        Sxx += ((x * x + x * x1 + x1 * x1) * c).sum() / 12  # integral of x^2
        Syy += ((y * y + y * y1 + y1 * y1) * c).sum() / 12
        Sxy += ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * c).sum() / 24
    if A <= 1e-9:
        return out
    cx, cy = cx / A, cy / A
    Ixx, Iyy, Ixy = Sxx - A * cx * cx, Syy - A * cy * cy, Sxy - A * cx * cy  # about the centroid
    hull = _hull(np.concatenate([f[0] for f in faces]) - ref)
    th = np.radians(np.arange(0, 180, 2.0))
    if len(hull) >= 3:
        e = np.roll(hull, -1, 0) - hull
        th = np.concatenate([th, np.arctan2(e[:, 0], -e[:, 1])])  # the hull's edge normals: the exact narrowest width
    n = np.c_[np.cos(th), np.sin(th)]
    proj = hull @ n.T
    w = proj.max(0) - proj.min(0)
    # OrcaSlicer measures along X and Y; here along the footprint's principal axes (the narrowest
    # width and across it when they are not distinct), so turning the part on the bed changes nothing
    J = np.array([[Ixx, Ixy], [Ixy, Iyy]])
    ev, vec = np.linalg.eigh(J)
    axes = vec.T if ev[1] > 1.05 * ev[0] else [n[int(np.argmin(w))], n[int(np.argmin(w))] @ [[0, 1], [-1, 0]]]
    k = []
    for u in axes:
        pr = hull @ u
        inertia = float(u @ J @ u)  # about the axis across u
        k.append((pr.max() - pr.min()) / inertia if inertia > 1e-12 else np.inf)
    k = np.array(k)
    strips = []
    for f in faces:
        lp = f[0]
        a = 0.5 * abs(float(np.sum(lp[:, 0] * np.roll(lp[:, 1], -1) - np.roll(lp[:, 0], -1) * lp[:, 1])))
        per = float(np.linalg.norm(np.roll(lp, -1, 0) - lp, axis=1).sum())
        strips.append(a / per if per else 0.0)
    width = float(w.min())
    out.update(area=round(A, 2), width=round(width, 2), length=round(float(w.max()), 2),
               ratio=round(height / width, 2) if width > 1e-6 else float("inf"),
               brim=round(float(speed * height ** 2 * k.max() / 1920), 2), strip=round(min(strips), 2),
               centroid=[round(float(cx + ref[0]), 2), round(float(cy + ref[1]), 2)])
    if com is not None and len(hull) >= 3:
        from matplotlib.path import Path as MPath

        out["com_inside"] = bool(MPath(hull).contains_point((com[0] - ref[0], com[1] - ref[1]), radius=1e-6))
    return out


def bed_footprint(part: Part, speed: float = 200.0, layer: float = 0.2, slicer=None) -> dict:
    """footprint() of `part` as it sits (bed at its lowest point): the section half a layer up."""
    from build123d import CenterOf

    bb = part.bounding_box()
    sl = slicer or MeshSlicer(part)
    c = part.center(CenterOf.MASS)
    return footprint(sl.section("XY", bb.min.Z + layer / 2, 1e9), bb.size.Z, speed, (c.X, c.Y))


def tip_risk(fp: dict, brim: float = TIP_BRIM, min_height: float = TIP_HEIGHT) -> list[str]:
    """Why a footprint() is at risk of being knocked over or wobbling (empty: it is not)."""
    if fp["height"] < min_height:
        return []
    why = []
    if not fp["area"]:
        return ["nothing on the bed (it rests on an edge or a point)"]
    if fp["com_inside"] is False:
        why.append("its centre of mass is outside the footprint")
    if fp["brim"] >= brim:
        why.append(f"auto-brim estimate {fp['brim']:.3g} mm (>= {brim:g})")
    if fp["strip"] < TIP_STRIP:
        why.append(f"it stands on a strip {2 * fp['strip']:.2g} mm wide")
    return why


def _vec(c):
    from build123d import Vector

    return Vector(*map(float, c))


# ---------------------------------------------------------------------------------------------
# Thin features


def line_width(settings) -> float:
    """Extrusion line width: the printer profile's, else 0.45 (a 0.4 mm nozzle)."""
    if getattr(settings, "printer", ""):
        from .profiles import load_printer

        return load_printer(settings.printer).line_width
    return 0.45


def flat_faces(part: Part) -> list[tuple]:
    """(normal, center) of each flat face, for section_levels."""
    out = []
    for f in part.faces():
        if f.geom_type.name == "PLANE":
            c = f.center()
            n = f.normal_at(c)
            out.append(((n.X, n.Y, n.Z), (c.X, c.Y, c.Z)))
    return out


def section_levels(part: Part, plane: str, step: float = 2.0, cap: int = 80, flats=None) -> list[float]:
    """Where to cut sections on `plane` so every feature is seen: the midpoint between each pair of
    neighbouring flat faces parallel to the plane (a 0.6 mm tall label gets its own cut), plus
    cuts every `step` mm in between (curved and sloped parts); at most `cap` cuts. flats: the
    part's flat_faces, when already known."""
    axis = AXES[plane]
    bb = part.bounding_box()
    lo, hi = (bb.min.X, bb.min.Y, bb.min.Z)[axis], (bb.max.X, bb.max.Y, bb.max.Z)[axis]
    stops = {round(lo, 4), round(hi, 4)}
    for n, c in flat_faces(part) if flats is None else flats:
        if abs(n[axis]) > 0.999:
            stops.add(round(c[axis], 4))
    stops = sorted(stops)
    while True:
        out = []
        for a, b in zip(stops, stops[1:]):
            if b - a < 1e-3:
                continue
            k = max(1, int(np.ceil((b - a) / step)))
            out += [a + (b - a) * (i + 0.5) / k for i in range(k)]
        if len(out) <= cap or step > hi - lo:
            return [round(x, 4) for x in out]
        step *= 2


def _boxes_2d(boxes, plane: str, at: float) -> list[tuple]:
    """3D boxes ((cx, cy, cz), (sx, sy, sz)) cut by the section plane, as 2D (u0, v0, u1, v1)."""
    axis = AXES[plane]
    keep = [i for i in range(3) if i != axis]
    out = []
    for c, s in boxes:
        if abs(at - c[axis]) <= s[axis] / 2:
            out.append((c[keep[0]] - s[keep[0]] / 2, c[keep[1]] - s[keep[1]] / 2,
                        c[keep[0]] + s[keep[0]] / 2, c[keep[1]] + s[keep[1]] / 2))
    return out


def _to_3d(plane: str, at: float, uv) -> list[float]:
    axis = AXES[plane]
    p = list(uv)
    p.insert(axis, at)
    return [round(float(x), 2) for x in p]


def thin_features(part: Part, limit: float, planes=("XY", "XZ", "YZ"), step: float = 2.0, ignore=(),
                  sample: float = 0.25) -> list[dict]:
    """Every spot thinner than `limit` in sections across the part (see section_levels), thinnest
    first, at most one per 2 mm. Each: {"min", "at": [x, y, z], "plane", "section_at"}."""
    spots = []
    slicer = MeshSlicer(part) if meshy(part) else None
    flats = flat_faces(part)
    for plane in planes:
        plane = plane.upper()
        for at in section_levels(part, plane, step, flats=flats):
            r = wall_thickness(part, plane, at, step=sample, limit=limit, exclude=_boxes_2d(ignore, plane, at), slicer=slicer)
            if r is not None and np.isfinite(r["min"]) and r["min"] < limit:
                spots.append({"min": r["min"], "at": _to_3d(plane, at, r["at"]), "plane": plane, "section_at": at,
                              "taper": bool(r.get("taper", False))})
    spots.sort(key=lambda s: s["min"])
    kept = []
    for s in spots:
        if all(np.linalg.norm(np.subtract(s["at"], k["at"])) > 2.0 for k in kept):
            kept.append(s)
    # A section can cut close to a corner or a knife edge so that its two faces look like a thin
    # wall (a notch through a lip leaves a wedge-shaped end). A real thin wall, pin or plate is
    # thin in at least two of the three planes through the spot; otherwise, or when another plane
    # shows it tapering, it is an edge.
    for s in kept:
        if s["taper"]:
            continue
        confirmed = False
        for other in ("XY", "XZ", "YZ"):
            if other == s["plane"]:
                continue
            ax = AXES[other]
            uv = [s["at"][i] for i in range(3) if i != ax]
            r = wall_thickness(part, other, s["at"][ax], near=uv, radius=1.0, step=sample / 2, limit=limit, slicer=slicer)
            if r is not None and np.isfinite(r["min"]) and r["min"] < limit:
                if r.get("taper"):
                    confirmed = False
                    break
                confirmed = True
        s["taper"] = not confirmed
    return kept


# ---------------------------------------------------------------------------------------------
# Gaps


def gap(a: Part, b: Part) -> float:
    """Smallest distance between two shapes (0 when they touch or overlap)."""
    return float(a.distance_to(b))


# ---------------------------------------------------------------------------------------------
# Wall thickness


def wire_edges(w) -> list:
    """The edges of a wire in order along it. OCC's wire explorer walks them in a linear pass;
    Wire.order_edges sorts by projecting every edge onto the wire, which takes seconds on the
    thousand-edge outlines of sections through mesh-derived solids."""
    from build123d import Edge
    from OCP.BRepTools import BRepTools_WireExplorer

    edges = w.edges()
    ex, out = BRepTools_WireExplorer(w.wrapped), []
    while ex.More():
        out.append(Edge(ex.Current()))
        ex.Next()
    if len(out) == len(edges):
        return out
    try:  # the explorer skips edges of a wire that is not a simple chain
        return w.order_edges()
    except IndexError:  # a degenerate wire in a section (seen on tiny text slivers)
        return edges


def edge_points(e, step: float) -> np.ndarray:
    """Points along an edge at most `step` apart, evenly spaced by arc length, in the edge's own
    direction: (n, 3). Straight edges (every edge of a section through a mesh-derived solid) are
    interpolated directly: Edge.length and Edge.positions integrate the curve for every point,
    half a second on a thousand-edge section."""
    if e.geom_type.name == "LINE":
        p0, p1 = e.start_point(), e.end_point()
        a, b = np.array([p0.X, p0.Y, p0.Z]), np.array([p1.X, p1.Y, p1.Z])
        n = max(2, int(np.ceil(float(np.linalg.norm(b - a)) / step)) + 1)
        return a + (b - a) * np.linspace(0, 1, n)[:, None]
    n = max(2, int(np.ceil(e.length / step)) + 1)
    return np.array([(p.X, p.Y, p.Z) for p in e.positions(list(np.linspace(0, 1, n)))])


def _loops(face, plane: str, step: float) -> list[np.ndarray]:
    """Face boundary loops as 2D polylines with material on the LEFT of each segment."""
    axis = AXES[plane]
    keep = [i for i in range(3) if i != axis]
    loops = []
    wires = [face.outer_wire(), *face.inner_wires()]
    for wi, w in enumerate(wires):
        pts = []
        for e in wire_edges(w):
            xy = [(p[keep[0]], p[keep[1]]) for p in edge_points(e, step).tolist()]
            if pts and np.hypot(xy[0][0] - pts[-1][0], xy[0][1] - pts[-1][1]) > np.hypot(xy[-1][0] - pts[-1][0], xy[-1][1] - pts[-1][1]):
                xy.reverse()  # edge stored against the wire direction
            pts.extend(xy if not pts else xy[1:])
        p = np.array(pts)
        if len(p) < 3:
            continue
        x, y = p[:, 0], p[:, 1]
        signed = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
        outer = wi == 0
        if (signed < 0) == outer:  # outer must be CCW, holes CW -> material on the left
            p = p[::-1]
        loops.append(p)
    return loops


def wall_thickness(part: Part, plane: str, at: float, near=None, radius: float | None = None, step: float = 0.1,
                   limit: float | None = None, exclude=(), slicer=None, loops=None) -> dict | None:
    """Thinnest material in the cross-section of `part` on `plane` at `at`.

    near: (u, v) in the section's own 2D axes (XY -> (x, y), XZ -> (x, z), YZ -> (y, z)); with
    radius, only material within that distance of `near` is measured (e.g. around one hole).
    Thickness at each boundary point is the distance along the inward normal to the next
    boundary; also the closest approach between different boundary loops (hole to outside).
    limit: only walls thinner than this matter (much faster on big sections); with nothing
    thinner the result's "min" is inf. exclude: 2D boxes (u0, v0, u1, v1) left out. slicer: a
    MeshSlicer of the part, to cut its triangulation instead of the B-rep (many-faced solids).
    loops: the section already cut, as _loops of each section face (Wall cuts it once for both
    its facts and the measurement).
    Returns {"min": mm, "at": [u, v], "plane":..., ...} or None when the plane misses the region."""
    plane = plane.upper()
    best = None
    if loops is not None:
        faces = loops
    elif slicer is not None:
        faces = slicer.section(plane, at, step)
    else:
        faces = (_loops(f, plane, step) for f in section_faces(part, plane, at))
    for loops in faces:
        cand = _face_thinnest(loops, near, radius, limit, exclude)
        if cand is not None and (best is None or cand["min"] < best["min"]):
            best = cand
    if best is None or (limit is None and not np.isfinite(best["min"])):
        return None
    if np.isfinite(best["min"]):
        best["min"] = round(best["min"], 3)
    best["at"] = [round(x, 2) for x in best["at"]]
    best["plane"] = plane
    best["section_at"] = at
    return best


MESHY_FACES = 1500  # solids with more faces (most come from meshes: import_model) are sliced as triangles
FACETED_FACES, FACETED_SHARE = 400, 0.95  # ... and so are solids this many faces, nearly all flat (a mesh's facets)


def meshy(part: Part) -> bool:
    """Cut sections of `part` from its triangulation (MeshSlicer) rather than the B-rep: thousands
    of faces, or hundreds that are nearly all flat, as a solid from import_model is. Flat faces
    triangulate exactly, so the outline is the same; an OCC section of a 1200-face solid takes
    ~0.1 s, and ThinFeature cuts a hundred of them."""
    faces = part.faces()
    if len(faces) > MESHY_FACES:
        return True
    return len(faces) >= FACETED_FACES and sum(f.geom_type.name == "PLANE" for f in faces) >= FACETED_SHARE * len(faces)


class MeshSlicer:
    """Cross-sections of a solid cut from its triangulation, for solids with thousands of faces
    (one OCC section of a 10k-face solid takes ~0.4 s; this takes milliseconds). section() gives
    what _loops gives per section face: 2D loops, outer CCW then its holes CW (material on the left)."""

    def __init__(self, part: Part, tol: float = 0.01):
        v, t = tessellate(part, tol, 0.1)
        from .remix import _weld

        v, t = _weld(v, t, 1e-4)  # each face has its own copy of the nodes on its edges
        self.v, self.t = v, t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]

    def section(self, plane: str, at: float, step: float) -> list[list[np.ndarray]]:
        from matplotlib.path import Path as MPath

        ax = AXES[plane.upper()]
        keep = [i for i in range(3) if i != ax]
        d = self.v[:, ax] - at
        d = np.where(np.abs(d) < 1e-9, 1e-9, d)  # nothing exactly on the plane
        s = d[self.t] > 0
        cross = s.any(1) & ~s.all(1)
        if not cross.any():
            return []
        tri = self.t[cross]
        nv = len(self.v)
        segs = []
        for a, b, c in tri.tolist():
            hit = [(p, q) for p, q in ((a, b), (b, c), (c, a)) if (d[p] > 0) != (d[q] > 0)]
            segs.append((min(hit[0]) * nv + max(hit[0]), min(hit[1]) * nv + max(hit[1])))  # oriented below
        pt = {}

        def point(k):
            p = pt.get(k)
            if p is None:
                i, j = divmod(k, nv)
                w = d[i] / (d[i] - d[j])
                p = pt[k] = (self.v[i] + w * (self.v[j] - self.v[i]))[keep]
            return p

        # chain: each crossing edge is shared by two crossing triangles -> undirected adjacency
        adj: dict = {}
        for k0, k1 in segs:
            adj.setdefault(k0, []).append(k1)
            adj.setdefault(k1, []).append(k0)
        loops, seen = [], set()
        for start in adj:
            if start in seen:
                continue
            lp, prev, cur = [], None, start
            while cur not in seen:
                seen.add(cur)
                lp.append(point(cur))
                nb = [x for x in adj[cur] if x != prev and x not in seen]
                if not nb:
                    break
                prev, cur = cur, nb[0]
            if len(lp) >= 3 and start in adj[cur] and all(len(adj[k]) == 2 for k in (start, cur)):
                loops.append(_resample(np.array(lp), step))
        # nesting: even depth = outer (CCW), odd = hole (CW) of the smallest outer around it
        paths = [MPath(lp) for lp in loops]
        depth = [sum(paths[j].contains_point(loops[i][0]) for j in range(len(loops)) if j != i) for i in range(len(loops))]
        area = [0.5 * float(np.sum(lp[:, 0] * np.roll(lp[:, 1], -1) - np.roll(lp[:, 0], -1) * lp[:, 1])) for lp in loops]
        faces: dict[int, list] = {}
        for i, lp in enumerate(loops):
            outer = depth[i] % 2 == 0
            if (area[i] < 0) == outer:
                loops[i] = lp[::-1]
        for i in range(len(loops)):
            if depth[i] % 2 == 0:
                faces[i] = [loops[i]]
        for i in range(len(loops)):
            if depth[i] % 2 == 1:
                hosts = [j for j in faces if depth[j] == depth[i] - 1 and paths[j].contains_point(loops[i][0])]
                if hosts:
                    faces[min(hosts, key=lambda j: abs(area[j]))].append(loops[i])
        return list(faces.values())


def _resample(p: np.ndarray, step: float) -> np.ndarray:
    """A closed polyline with points at most `step` apart."""
    q = np.roll(p, -1, axis=0)
    n = np.maximum(1, np.ceil(np.linalg.norm(q - p, axis=1) / step).astype(int))
    if n.max() == 1:
        return p
    return np.concatenate([p[i] + (q[i] - p[i]) * (np.arange(n[i])[:, None] / n[i]) for i in range(len(p))])


def _inside(p: np.ndarray, boxes) -> np.ndarray:
    out = np.zeros(len(p), bool)
    for u0, v0, u1, v1 in boxes:
        out |= (p[:, 0] >= u0) & (p[:, 0] <= u1) & (p[:, 1] >= v0) & (p[:, 1] <= v1)
    return out


def _face_thinnest(loops, near, radius, limit, exclude) -> dict | None:
    if not loops:
        return None
    lim = np.inf if limit is None else float(limit)
    segs, loop_id, arc, perim = [], [], [], []
    for li, lp in enumerate(loops):
        sg = np.stack([lp, np.roll(lp, -1, axis=0)], 1)
        ln = np.linalg.norm(sg[:, 1] - sg[:, 0], axis=1)
        segs.append(sg)
        loop_id.append(np.full(len(sg), li))
        arc.append(np.cumsum(ln) - ln / 2)  # arc length at each segment's midpoint
        perim.append(np.full(len(sg), ln.sum()))
    segs, loop_id, arc, perim = (np.concatenate(x) for x in (segs, loop_id, arc, perim))
    a, b = segs[:, 0], segs[:, 1]
    d = b - a
    length = np.linalg.norm(d, axis=1)
    ok = length > 1e-9
    a, b, d, length, loop_id, arc, perim = a[ok], b[ok], d[ok], length[ok], loop_id[ok], arc[ok], perim[ok]
    mid = (a + b) / 2
    normal = np.c_[-d[:, 1], d[:, 0]] / length[:, None]  # left = into the material
    sel = np.ones(len(mid), bool)
    if near is not None and radius is not None:
        sel = np.hypot(mid[:, 0] - near[0], mid[:, 1] - near[1]) <= radius
    if exclude:
        sel &= ~_inside(mid, exclude)
    if not sel.any():
        return None
    o, r = mid[sel], normal[sel]
    o_loop, o_arc = loop_id[sel], arc[sel]
    seg_lo, seg_hi = np.minimum(a, b), np.maximum(a, b)
    # Ray (o + t r) vs segment (a + s d), in chunks. A hit a short way along the same boundary
    # (< CORNER * t) on a face that does not face back at the ray (normals > 30 deg from
    # opposite) is the other side of a corner, not of a wall: ignore it. Otherwise every
    # 60 deg corner would read as a 0.0x mm wall right at its tip.
    # Rays are cast in rounds of growing reach, each against only the segments within reach of
    # the chunk: a ray whose nearest hit is within reach has found it, the others go on to the
    # next round. The last round (reach >= limit, or every segment) is the plain cast, chunk by
    # chunk as before, so the result is the same; on a section with thousands of segments (a
    # mesh-derived solid) most rays end in the first round against a few dozen segments.
    tmin = np.full(len(o), np.inf)
    tdot = np.zeros(len(o))  # ray direction . normal of the boundary it hits: -1 = parallel walls
    traw = 0.0
    span = float(np.max(seg_hi.max(0) - seg_lo.min(0))) if len(a) else 0.0
    reach = min(REACH, lim)
    pending = np.ones(len(o), bool)
    while pending.any():
        last = reach >= lim or reach >= span
        margin = lim if last else reach
        for i in range(0, len(o), CHUNK):
            idx = i + np.nonzero(pending[i : i + CHUNK])[0]
            if not len(idx):
                continue
            box = o[i : i + CHUNK] if last else o[idx]  # last round: the whole chunk, as a plain cast
            if np.isfinite(margin):  # only segments that can be within reach of this chunk
                k = np.nonzero(np.all(seg_hi >= box.min(0) - margin, 1) & np.all(seg_lo <= box.max(0) + margin, 1))[0]
            else:
                k = slice(None)
            sa, sd, sn, sl, sarc, sper = a[k], d[k], normal[k], loop_id[k], arc[k], perim[k]
            oo, rr = o[idx][:, None, :], r[idx][:, None, :]
            denom = rr[..., 0] * sd[None, :, 1] - rr[..., 1] * sd[None, :, 0]
            w = sa[None] - oo
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (w[..., 0] * sd[None, :, 1] - w[..., 1] * sd[None, :, 0]) / denom
                s = (w[..., 0] * rr[..., 1] - w[..., 1] * rr[..., 0]) / denom
            hit = (np.abs(denom) > 1e-12) & (t > 1e-6) & (s >= -1e-9) & (s <= 1 + 1e-9)
            along = np.abs(o_arc[idx, None] - sarc[None, :])
            along = np.minimum(along, sper[None, :] - along)
            facing = (rr[..., 0] * sn[None, :, 0] + rr[..., 1] * sn[None, :, 1]) < -0.866
            corner = (o_loop[idx, None] == sl[None, :]) & (along < CORNER * t) & ~facing
            traw = max(traw, float(np.where(hit, t, 0).max(initial=0)))
            t = np.where(hit & ~corner & (t <= lim), t, np.inf)
            tm = t.min(1, initial=np.inf)
            done = last | (tm <= reach)
            tmin[idx[done]] = tm[done]
            pending[idx[done]] = False
            if t.shape[1]:
                j = t.argmin(1)
                tdot[idx] = (rr[:, 0, 0] * sn[j, 0] + rr[:, 0, 1] * sn[j, 1])
        reach = min(reach * 4, lim)
    k = int(np.argmin(tmin))
    if np.isfinite(tmin[k]):
        taper = bool(tdot[k] > -PARALLEL)
        cand = {"min": float(tmin[k]), "at": o[k].tolist(), "how": "tapers to an edge" if taper else "across the wall",
                "taper": taper}
    elif traw > 0 and traw <= lim:  # only corner hits: a compact blob with no walls, as thick as it is wide
        cand = {"min": traw, "at": o[k].tolist(), "how": "no thin walls (compact section)"}
    else:
        cand = {"min": np.inf, "at": o[k].tolist(), "how": f"nothing thinner than {lim:g}"}
    # closest approach between different loops (a hole close to the outside or another hole)
    if len(loops) > 1:
        for (i, p), (j, q) in combinations(enumerate(loops), 2):
            if near is not None and radius is not None:
                p = p[np.hypot(p[:, 0] - near[0], p[:, 1] - near[1]) <= radius]
                q = q[np.hypot(q[:, 0] - near[0], q[:, 1] - near[1]) <= radius]
            if exclude:
                p, q = p[~_inside(p, exclude)], q[~_inside(q, exclude)]
            if not len(p) or not len(q):
                continue
            if np.any(p.min(0) - q.max(0) > min(lim, cand["min"])) or np.any(q.min(0) - p.max(0) > min(lim, cand["min"])):
                continue
            for c0 in range(0, len(p), 1024):
                pc = p[c0 : c0 + 1024]
                qc = q
                m = min(lim, cand["min"])  # points farther than this cannot be the new closest
                if np.isfinite(m):
                    qc = q[np.all((q >= pc.min(0) - m) & (q <= pc.max(0) + m), 1)]
                    if not len(qc):
                        continue
                dd = np.hypot(pc[:, None, 0] - qc[None, :, 0], pc[:, None, 1] - qc[None, :, 1])
                m = np.unravel_index(np.argmin(dd), dd.shape)
                if dd[m] < cand["min"] and dd[m] <= lim:
                    cand = {"min": float(dd[m]), "at": ((pc[m[0]] + qc[m[1]]) / 2).tolist(), "how": "between two boundaries"}
    return cand


# ---------------------------------------------------------------------------------------------
# Specs declared by part scripts


def _get(parts: dict, name):
    """Part by name (a single unnamed part is "part" or ""), or a Part passed directly."""
    if isinstance(name, Part):
        return name
    key = name or "part"
    if key not in parts:
        raise KeyError(f"no part named {name!r}; parts: {sorted(parts)}")
    return parts[key]


@dataclass
class Overlap:
    """Fail if any two assembly parts intersect by more than `tol` mm^3."""

    ignore: tuple = ()  # label pairs allowed to overlap
    tol: float = 0.01

    def run(self, parts, assembly, settings) -> list[Finding]:
        if not assembly:
            return []
        return overlap([(p, label) for p, _, label in assembly], self.tol, self.ignore)


@dataclass
class Overhang:
    """Report downward faces steeper than max_angle (default from settings, 45 deg). BP-O1, BP-O3, BP-O4.
    Flat ceilings are told apart: a bridge rests on walls on two opposite sides (listed, warns when
    its span is over max_bridge, never fails), a cantilever hangs off one side (an overhang like
    any other). fail=True turns the report into a failure: use it for parts meant to print
    without supports.
    accept: the part's reason when its PRINT intent says supports "none" (set automatically from
    PRINT): the overhangs and long bridges are still reported, as accepted (OK) instead of a WARN;
    a FAIL (fail=True on a hard overhang) stays a FAIL."""

    part: str
    max_angle: float | None = None
    fail: bool = False
    min_area: float = 1.0  # mm^2; smaller flagged areas are reported but not counted
    ignore_below: float = 0.0  # mm above the bed; e.g. 1.0 to accept a small fillet on a bed edge
    bridges_ok: bool = True  # bridges (flat ceilings held on two opposite sides) never fail
    max_bridge: float | None = None  # mm; longer bridges warn (default: the max_bridge setting)
    accept: str = ""  # PRINT supports "none": its why; the findings are accepted, never a FAIL turned to a pass

    def run(self, parts, assembly, settings) -> list[Finding]:
        lim = self.max_angle if self.max_angle is not None else settings.max_overhang
        span_lim = self.max_bridge if self.max_bridge is not None else settings.max_bridge
        r = overhang_faces(_get(parts, self.part), lim, ignore_below=self.ignore_below)
        big = [f for f in r["faces"] if f["area"] >= self.min_area]
        if not big:
            small = f" ({len(r['faces'])} tiny face(s), {r['area']} mm^2, ignored)" if r["faces"] else ""
            return [Finding(OK, "overhang", self.part or "part", f"nothing steeper than {lim:g} deg{small}", r)]
        area = sum(f["area"] for f in big)
        hard = [f for f in big if not (self.bridges_ok and f["kind"] == "bridge")]
        long = [f for f in big if f["kind"] == "bridge" and f["span"] > span_lim]

        def kind(f):
            if f["kind"] == "bridge":
                return f"bridge {f['span']:g} mm"
            if f["kind"] == "cantilever":
                return "cantilever, " + ("no wall under it" if f["hanging"] == float("inf") else f"hangs {f['hanging']:g} mm")
            return f["kind"]

        groups: dict = {}
        for f in big:
            k = (round(f["area"]), f["max_angle"], tuple(f["z"]), kind(f))
            groups[k] = groups.get(k, 0) + 1
        items = sorted(groups.items(), key=lambda kv: -kv[0][0] * kv[1])
        top = "; ".join(
            f"{'%d x ' % n if n > 1 else ''}{a} mm^2 at {ang:.0f} deg, z {z[0]:g}..{z[1]:g} ({kd})"
            for (a, ang, z, kd), n in items[:4]
        )
        more = f" (+{len(items) - 4} more groups)" if len(items) > 4 else ""
        failed = self.fail and hard
        accepted = f"accepted, the part prints without supports (PRINT): {self.accept}. " if self.accept else ""
        out = [
            Finding(
                FAIL if failed else OK if accepted else WARN,
                "overhang",
                self.part or "part",
                f"{'' if failed else accepted}{len(big)} face(s), {area:.0f} mm^2 steeper than {lim:g} deg: {top}{more}",
                {**r, "accepted": self.accept} if accepted and not failed else r,
            )
        ]
        if long:
            spans = ", ".join(f"{f['span']:g} mm at {f['center']}" for f in long[:4])
            out.append(Finding(OK if accepted else WARN, "bridge", self.part or "part",
                               f"{accepted}{len(long)} bridge(s) longer than max_bridge {span_lim:g} mm: {spans}; they sag"
                               + ("" if accepted else ". Add a wall or rib under them, split the part, or print the coupon "
                                  "to measure your printer"),
                               {"bridges": long, **({"accepted": self.accept} if accepted else {})}))
        return out


@dataclass
class ThinFeature:
    """Material thinner than one line width does not print as modeled (fail); thinner than
    min_wall is weak (warn). BP-W1, BP-W2, BP-X2. Added automatically for every part: sections on
    XY, XZ and YZ at every flat-face level and every `step` mm. List it in checks(d) to change
    its limits or to ignore a region where thin is intended (a living hinge)."""

    part: str
    min: float | None = None  # warn below, mm (default: the min_wall setting)
    fail_below: float | None = None  # mm (default: one line width; 0.45 in generic mode)
    ignore: tuple = ()  # boxes ((cx, cy, cz), (sx, sy, sz)) where thin is intended
    step: float = 2.0  # mm between extra sections
    planes: tuple = ("XY", "XZ", "YZ")  # () turns the check off

    def limit(self, settings) -> float:
        warn = self.min if self.min is not None else settings.min_wall
        return max(warn, self.fail_below if self.fail_below is not None else line_width(settings))

    def thin_at(self, part: Part, spot: dict, settings, slicer=None) -> bool:
        """Is `part` thinner than this check's limit within 1 mm of a spot another part reported
        ({"at", "plane", "section_at"})? A remix's thin spot is the original's when the original
        is thin there too; matching the two spot lists is not enough, because each section
        reports only its single thinnest point and equal features (four identical clips) tie."""
        plane = spot["plane"]
        ax = AXES[plane]
        uv = [spot["at"][i] for i in range(3) if i != ax]
        r = wall_thickness(part, plane, spot["section_at"], near=uv, radius=1.0, step=0.125, limit=self.limit(settings),
                           exclude=_boxes_2d(self.ignore, plane, spot["section_at"]), slicer=slicer)
        return r is not None and bool(np.isfinite(r["min"]))

    def run(self, parts, assembly, settings) -> list[Finding]:
        lw = line_width(settings)
        warn = self.min if self.min is not None else settings.min_wall
        fail = self.fail_below if self.fail_below is not None else lw
        name = self.part or "part"
        spots = thin_features(_get(parts, self.part), max(warn, fail), self.planes, self.step, self.ignore)
        data = {"spots": spots[:8], "line_width": lw, "warn_below": warn, "fail_below": fail,
                "located": {"wall": [x["at"] for x in spots if not x["taper"]], "edge": [x["at"] for x in spots if x["taper"]]}}
        if not spots:
            return [Finding(OK, "thin", name, f"nothing thinner than {warn:g} mm ({warn / lw:.1f} lines)", data)]
        out = []
        walls = [s for s in spots if not s["taper"]]
        edges = [s for s in spots if s["taper"]]
        if walls:
            m = walls[0]
            where = "; ".join(f"{s['min']:.2f} at {tuple(s['at'])}" for s in walls[:4])
            more = f" (+{len(walls) - 4} more)" if len(walls) > 4 else ""
            out.append(Finding(FAIL if m["min"] < fail else WARN, "thin", name,
                               f"thinnest wall {m['min']:.2f} mm ({m['min'] / lw:.1f} lines of {lw:g}): {where}{more}; "
                               f"fails below {fail:g} (does not print as modeled), warns below {warn:g}", data))
        if edges:
            where = "; ".join(f"{s['min']:.2f} at {tuple(s['at'])}" for s in edges[:4])
            more = f" (+{len(edges) - 4} more)" if len(edges) > 4 else ""
            out.append(Finding(WARN, "thin", name,
                               f"{len(edges)} knife edge(s), material tapering below {warn:g} mm: {where}{more}; "
                               "the tip does not print as modeled (BP-R3). Fine on a cosmetic edge; blunt it where it matters",
                               data))
        return out


@dataclass
class Holes:
    """Lists round holes; warns on horizontal holes with a round top (BP-H3: the top sags and
    prints small; use a teardrop or a flat bridged roof, or turn the part) and on holes below
    min_diameter (BP-H5). Added automatically for every part."""

    part: str
    min_diameter: float = 1.0  # mm; smaller holes warn
    round_top_from: float = 2.0  # mm; horizontal holes this size and up need a teardrop or flat roof

    def run(self, parts, assembly, settings) -> list[Finding]:
        part = _get(parts, self.part)
        name = self.part or "part"
        found = holes(part)
        brief = [{k: v for k, v in h.items() if k != "faces"} for h in found]
        if not found:
            return [Finding(OK, "holes", name, "no round holes", {"holes": []})]
        out = []
        sag = round_topped_holes(part, settings.max_overhang, self.round_top_from)
        if sag:
            where = ", ".join(f"d {h['d']:g} at {tuple(h['center'])}" for h in sag[:4])
            more = f" (+{len(sag) - 4} more)" if len(sag) > 4 else ""
            out.append(Finding(WARN, "holes", name,
                               f"{len(sag)} horizontal hole(s) with a round top: {where}{more}. The top sags and prints "
                               "small; give it a teardrop or flat roof, or turn the part so the hole is vertical",
                               {"round_top": [{k: v for k, v in h.items() if k != "faces"} for h in sag]}))
        small = [h for h in brief if h["d"] < self.min_diameter]
        if small:
            where = ", ".join(f"d {h['d']:g} at {tuple(h['center'])}" for h in small[:4])
            out.append(Finding(WARN, "holes", name,
                               f"{len(small)} hole(s) under {self.min_diameter:g} mm: {where}; too small to print round. "
                               "Drill them, or make them bigger", {"small": small}))
        if not out:
            nv = sum(h["vertical"] for h in brief)
            out.append(Finding(OK, "holes", name, f"{len(brief)} round hole(s), {nv} vertical; no round-topped "
                               "horizontal holes", {"holes": brief}))
        else:
            out[0].data["holes"] = brief
        return out


@dataclass
class BedEdge:
    """Warns on curved faces (fillets, roundings) that start on the bed and face down steeper than
    max_overhang: their lowest band flares and lifts. Use a chamfer on bed edges. BP-O2. Added
    automatically for every part."""

    part: str
    min_area: float = 0.2  # mm^2 of steep surface before a face counts

    def run(self, parts, assembly, settings) -> list[Finding]:
        name = self.part or "part"
        found = bed_fillets(_get(parts, self.part), settings.max_overhang, min_area=self.min_area)
        if not found:
            return [Finding(OK, "bed edge", name, "no fillets on the bed edges")]
        where = "; ".join(f"{f['kind']} {f['height']:g} mm tall at {tuple(f['center'])}" for f in found[:4])
        more = f" (+{len(found) - 4} more)" if len(found) > 4 else ""
        return [Finding(WARN, "bed edge", name,
                        f"{len(found)} rounded bed edge(s): {where}{more}; the start of a fillet on the bed is a "
                        "flat overhang that flares. Use a chamfer on bed edges", {"faces": found})]


@dataclass
class TipOver:
    """Warns when a part is tall on a small first layer: the nozzle can knock it off the bed, or
    it wobbles and its top prints badly. BP-B6. The measure is OrcaSlicer's Auto brim (height,
    and the footprint's width and second moment of area about its weakest axis, at the `tip_speed`
    setting); also a footprint that is a thin strip, or a centre of mass outside it. Never
    fails. Added automatically for every part; tip_speed = 0 turns it off."""

    part: str
    brim: float = TIP_BRIM  # mm: warn when the auto-brim estimate reaches this
    min_height: float = TIP_HEIGHT  # mm: lower parts are not checked
    speed: float | None = None  # mm/s: the slicer's fastest print speed (default: the tip_speed setting)

    def run(self, parts, assembly, settings) -> list[Finding]:
        name = self.part or "part"
        speed = self.speed if self.speed is not None else settings.tip_speed
        if not speed:
            return []
        fp = bed_footprint(_get(parts, self.part), speed)
        why = tip_risk(fp, self.brim, self.min_height)
        size = f"{fp['height']:g} mm tall on a {fp['width']:g} x {fp['length']:g} mm footprint ({fp['area']:g} mm^2"
        size += f", height {fp['ratio']:.3g} x its narrowest width)" if fp["width"] else ")"
        if not why:
            low = f"under {self.min_height:g} mm tall" if fp["height"] < self.min_height else f"auto-brim estimate {fp['brim']:.3g} mm"
            return [Finding(OK, "tip-over", name, f"stable: {size}; {low}", fp)]
        return [Finding(WARN, "tip-over", name,
                        f"{size}: {'; '.join(why)}. The nozzle can knock it over, or it wobbles. Use a brim "
                        "(5-10 mm) or mouse ears, lay it down (suggest_orientation ranks the ways to put it on the bed), "
                        "or print several together joined by a thin tie", fp)]


@dataclass
class Gap:
    """Smallest gap between two parts (`part` and `other`: names from build() or labels from
    assembly(d), assembled position preferred), or, with other=None, between the separate solids
    of one printable part (parts printed in place, which fuse when too close). BP-F1, BP-F3.
    Fails below `min` (default: pip_clearance for solids of one part, clearance for two parts) or
    above `max`. Added automatically for every part made of several solids."""

    part: object
    other: object = None
    min: float | None = None  # mm
    max: float | None = None  # mm
    within: tuple | None = None  # box ((cx, cy, cz), (sx, sy, sz)): only measure inside it
    label: str = ""

    def _shape(self, x, parts, assembly):
        if isinstance(x, Part):
            return x
        for p, _, lbl in assembly or []:
            if lbl == x:
                return p
        return _get(parts, x)

    def run(self, parts, assembly, settings) -> list[Finding]:
        from build123d import Box, Pos

        box = Pos(*self.within[0]) * Box(*self.within[1]) if self.within else None

        def clip(s):
            return s & box if box is not None else s

        tname = self.part if isinstance(self.part, str) else "part"
        if self.other is None:
            solids = list(_get(parts, self.part).solids())
            if len(solids) < 2:
                return []
            lim = self.min if self.min is not None else settings.pip_clearance
            pairs = [(clip(a), clip(b), f"solids {i + 1} / {j + 1}") for (i, a), (j, b) in combinations(enumerate(solids), 2)]
            tgt = tname
        else:
            lim = self.min if self.min is not None else settings.clearance
            oname = self.other if isinstance(self.other, str) else "other"
            pairs = [(clip(self._shape(self.part, parts, assembly)), clip(self._shape(self.other, parts, assembly)),
                      f"{tname} / {oname}")]
            tgt = f"{tname} / {oname}"
        tgt = f"{tgt} ({self.label})" if self.label else tgt
        best = None
        for a, b, what in pairs:
            if a.volume <= 0 or b.volume <= 0:
                continue
            if self.max is None and _bbox_gap(a, b) > lim:
                g = _bbox_gap(a, b)  # far apart: the box gap is a lower bound and already passes
            else:
                g = gap(a, b)
            if best is None or g < best[0]:
                best = (g, what)
        if best is None:
            return [Finding(FAIL, "gap", tgt, "nothing to measure (check `within`)")]
        g, what = best
        bad = g < lim - 1e-3 or (self.max is not None and g > self.max + 1e-3)
        rng = f"min {lim:g}" + (f", max {self.max:g}" if self.max is not None else "")
        msg = f"smallest gap {g:.3f} mm ({what}; {rng})"
        if bad and self.other is None and g < lim:
            msg += ": parts printed this close fuse"
        return [Finding(FAIL if bad else OK, "gap", tgt, msg, {"gap": round(g, 4), "between": what})]


def _bbox_gap(a, b) -> float:
    ba, bb = a.bounding_box(), b.bounding_box()
    d = [max(0.0, bmin - amax, amin - bmax) for amin, amax, bmin, bmax in
         zip((ba.min.X, ba.min.Y, ba.min.Z), (ba.max.X, ba.max.Y, ba.max.Z), (bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z))]
    return float(np.linalg.norm(d))


FRAMES = ("print", "assembly")


def _framed(spec, parts, assembly):
    """The shape a Wall or Probe measures: the printable part (frame="print", the default) or
    the part as it sits in assembly(d), found by its label (frame="assembly")."""
    if not isinstance(spec.part, str):
        return spec.part
    if spec.frame not in FRAMES:
        raise ValueError(f"frame must be one of {FRAMES}, not {spec.frame!r}")
    if spec.frame == "print":
        return _get(parts, spec.part)
    if not assembly:
        raise KeyError(f'frame="assembly" but the script has no assembly(d) (part {spec.part!r})')
    for p, _, lbl in assembly:
        if lbl == spec.part:
            return p
    raise KeyError(f"no assembly part labeled {spec.part!r}; labels: {[lbl for _, _, lbl in assembly]}")


def _fmt(v) -> str:
    return "(" + ", ".join(f"{x:.4g}" for x in v) + ")"


def _section_facts(part: Part, plane: str, at: float, near=None, radius=None, step: float = 0.1,
                   faces=None, face_loops=None) -> dict | None:
    """What a section holds: its area and 2D bbox, how far `near` is from material (0 = inside
    it) and the bbox of the boundary within `radius` of `near` (the region a Wall measures).
    None when the plane misses the part. faces, face_loops: the section already cut (its faces
    and their _loops)."""
    from matplotlib.path import Path as MPath

    if faces is None:
        faces = section_faces(part, plane.upper(), at)
    if not faces:
        return None
    if face_loops is None:
        face_loops = [_loops(f, plane.upper(), step) for f in faces]
    pts, dist = [], np.inf
    for loops in face_loops:
        if not loops:
            continue
        pts += list(loops)
        if near is not None:
            inside = MPath(loops[0]).contains_point(near) and not any(MPath(lp).contains_point(near) for lp in loops[1:])
            d = 0.0 if inside else min(float(np.hypot(*(lp - near).T).min()) for lp in loops)
            dist = min(dist, d)
    allp = np.concatenate(pts) if pts else np.zeros((0, 2))
    out = {"area": round(sum(f.area for f in faces), 2),
           "bbox": [[round(float(x), 2) for x in allp.min(0)], [round(float(x), 2) for x in allp.max(0)]] if len(allp) else None}
    if near is not None:
        out["near_dist"] = round(dist, 3)
        if radius is not None and len(allp):
            sel = allp[np.hypot(*(allp - near).T) <= radius]
            out["region"] = [[round(float(x), 2) for x in sel.min(0)], [round(float(x), 2) for x in sel.max(0)]] if len(sel) else None
    return out


@dataclass
class Wall:
    """Thinnest wall in a section (around `near` within `radius`); fail below `min`. BP-T4: the
    wall around a heat-set insert or screw boss. The result says what it measured (section area,
    how far `near` is from material, the region measured) and fails when nothing lies within
    `radius` of `near`. frame="assembly" measures the part where it sits in assembly(d), so
    turning the part over for printing cannot move the check onto another feature."""

    part: str
    plane: str
    at: float
    near: tuple | None = None
    radius: float | None = None
    min: float | None = None  # default: settings.min_wall
    label: str = ""
    frame: str = "print"  # "print": build() coordinates; "assembly": the part as placed in assembly(d)

    def run(self, parts, assembly, settings) -> list[Finding]:
        lim = self.min if self.min is not None else settings.min_wall
        where = f"{self.plane} @ {self.at:g}" + (f" near {tuple(round(x, 2) for x in self.near)}" if self.near else "")
        where += f" ({self.frame} frame)" if self.frame != "print" else ""
        name = self.part if isinstance(self.part, str) and self.part else "part"
        tgt = f"{name} ({self.label})" if self.label else name
        shape = _framed(self, parts, assembly)
        near = None if self.near is None else np.asarray(self.near, float)
        faces = section_faces(shape, self.plane.upper(), self.at)  # cut once, for the facts and the measurement
        face_loops = [_loops(f, self.plane.upper(), 0.1) for f in faces]
        facts = _section_facts(shape, self.plane, self.at, near, self.radius, faces=faces, face_loops=face_loops)
        if facts is None:
            bb = shape.bounding_box()
            ax = AXES[self.plane.upper()]
            lo, hi = (bb.min.X, bb.min.Y, bb.min.Z)[ax], (bb.max.X, bb.max.Y, bb.max.Z)[ax]
            return [Finding(FAIL, "wall", tgt, f"section {where} misses the part, which spans {'XYZ'[ax]} "
                            f"{lo:.4g}..{hi:.4g} (check the position and the frame)")]
        seen = f"section area {facts['area']:.4g} mm^2"
        if near is not None:
            d = facts["near_dist"]
            seen += ", near point inside material" if d == 0 else f", near point {d:.2f} mm from material"
            if self.radius is not None and facts.get("region"):
                seen += f", measured region {_fmt(facts['region'][0])}..{_fmt(facts['region'][1])}"
        if near is not None and self.radius is not None and facts["near_dist"] > self.radius:
            return [Finding(FAIL, "wall", tgt, f"nothing within radius {self.radius:g} of the near point: {seen}, "
                            f"section bbox {_fmt(facts['bbox'][0])}..{_fmt(facts['bbox'][1])}, {where}. The check "
                            "measures nothing there: did the part move or turn over? (frame=\"assembly\" pins it)", facts)]
        r = wall_thickness(shape, self.plane, self.at, self.near, self.radius, loops=face_loops)
        if r is None:
            return [Finding(FAIL, "wall", tgt, f"no wall boundary within radius {self.radius:g} of the near point "
                            f"(it is inside solid material): {seen}, {where}. Move it next to the cut, or widen radius",
                            facts)]
        level = FAIL if r["min"] < lim else OK
        return [Finding(level, "wall", tgt, f"min wall {r['min']:.2f} mm (limit {lim:g}) at {r['at']}, {where}; "
                        f"measured: {seen}", {**r, "measured": facts})]


@dataclass
class Probe:
    """Material must be present (expect="solid") or absent (expect="empty") in a small box.
    For design intent the other checks cannot see: "the roof is closed over the sensor",
    "nothing blocks the cable channel". part: a name from build() (frame="print"), a label from
    assembly(d) (frame="assembly"), or a Part. The result shows the box against the part's
    bounding box; a box entirely outside it fails (solid) or warns (empty: it proves nothing
    about the part unless the point is that nothing reaches there)."""

    part: object
    center: tuple
    size: tuple
    expect: str = "solid"
    fill: float = 0.98  # fraction of the box that counts as solid / at most this much counts as empty
    label: str = ""
    frame: str = "print"  # "print": build() coordinates; "assembly": the part as placed in assembly(d)

    def run(self, parts, assembly, settings) -> list[Finding]:
        from build123d import Box, Pos

        shape = _framed(self, parts, assembly)
        box = Pos(*self.center) * Box(*self.size)
        frac = (shape & box).volume / box.volume
        tgt = self.label or (self.part if isinstance(self.part, str) else "part")
        good = frac >= self.fill if self.expect == "solid" else frac <= 1 - self.fill
        bb = shape.bounding_box()
        pmin, pmax = (bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)
        bmin = [c - s / 2 for c, s in zip(self.center, self.size)]
        bmax = [c + s / 2 for c, s in zip(self.center, self.size)]
        outside = any(bmin[i] > pmax[i] or bmax[i] < pmin[i] for i in range(3))
        frame = f", {self.frame} frame" if self.frame != "print" else ""
        msg = (f"{frac:.0%} solid at {tuple(round(c, 2) for c in self.center)} (expected {self.expect}{frame}); "
               f"box {_fmt(bmin)}..{_fmt(bmax)}, part bbox {_fmt(pmin)}..{_fmt(pmax)}")
        data = {"fraction": round(frac, 4), "box": [bmin, bmax], "part_bbox": [list(pmin), list(pmax)], "outside": outside}
        if outside:
            msg += ": the box is entirely outside the part. Check the coordinates and the frame"
            return [Finding(FAIL if self.expect == "solid" else WARN, "probe", tgt, msg, data)]
        return [Finding(OK if good else FAIL, "probe", tgt, msg, data)]


@dataclass
class Fit:
    """The part must fit the active printer's build volume in print orientation (added
    automatically when a printer profile is set; nothing to check in generic mode)."""

    part: str
    margin: float = 0.0  # mm kept free at each bed edge

    def run(self, parts, assembly, settings) -> list[Finding]:
        if not settings.printer:
            return []
        from .profiles import fits, load_printer

        pr = load_printer(settings.printer)
        size = _get(parts, self.part).bounding_box().size
        ok, why = fits(pr, (size.X, size.Y, size.Z), self.margin)
        level = OK if ok else FAIL
        if ok and "turned" in why:
            level = WARN
        return [Finding(level, "fit", self.part or "part", f"{pr.label or pr.name}: {why}")]
