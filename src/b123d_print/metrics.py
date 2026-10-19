"""Design metrics: objective numbers for the design review (docs/DESIGN_GUIDE.md, rules `DS-*`).

M1 size and proportions, M2 filament mass (and M4 cost), M3 print time, M5 supports, M6
stair-stepping, M7 edge treatment, M8 mirror symmetry, M9 economy (parts, fastener sizes),
M10 seam corners, M11 water traps, and for load-bearing parts M12 inside corners, M13 walls,
M14 hole edge distance, M15 slenderness across the layers. Then the style findings: the
thresholds of the chosen style turned into "suggest" and "note" lines that cite their rule.
Nothing here fails a build.

Filament (M2), time (M3) and supports (M5) are simple estimates from the solid alone (no slicer):
filament roughly +-20 %, time and supports rough. Good for comparing two versions of a part, not
for a quote.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from build123d import Part

from . import checks as ck
from .render import tessellate
from .styles import EDGE_PREFS, THRESHOLDS, Style, load_style, normalize

# DS-C1 / DS-C3: the slicers' defaults (OrcaSlicer, PrusaSlicer and Cura profiles)
WALLS, TOP_LAYERS, BOTTOM_LAYERS, INFILL = 2, 5, 3, 0.15
FLOW = 10.0  # mm^3/s a standard hotend sustains (Prusa: 8-12); the `print_flow` setting changes it
LAYER_S = 3.0  # s per layer: layer change, travel, seam (ours; slicers' minimum layer time is 3-20 s)
SUPPORT_FILL = 0.2  # supports are roughly a fifth solid
DEFAULT_DENSITY = 1.24  # PLA datasheets (Prusament, Bambu); used when no material is set


@dataclass
class Params:
    """Assumptions for the estimates: slicer defaults, the printer's nozzle and layer height, the
    material's density, and the `print_flow` and `filament_price` settings."""

    nozzle: float = 0.4
    layer: float = 0.2
    walls: int = WALLS
    top_layers: int = TOP_LAYERS
    bottom_layers: int = BOTTOM_LAYERS
    infill: float = INFILL
    density: float = DEFAULT_DENSITY
    density_assumed: bool = True
    price: float | None = None  # per kg
    flow: float = FLOW
    max_overhang: float = 45.0
    max_bridge: float = 10.0
    material: str = ""
    line_width: float = 0.45  # the printer profile's, else a 0.4 mm nozzle's (checks.line_width)
    wall_lines: float | None = None  # M13 looks for walls under this many lines: the style's min_wall_lines
    hole_comp: float = 0.0
    hole_comp_h: float = 0.0

    @classmethod
    def from_settings(cls, s) -> "Params":
        p = cls(price=s.filament_price, flow=s.print_flow or FLOW, max_overhang=s.max_overhang,
                max_bridge=s.max_bridge, material=s.material, hole_comp=s.hole_comp,
                hole_comp_h=s.hole_comp if s.hole_comp_h is None else s.hole_comp_h)
        if s.printer:
            from .profiles import load_printer

            pr = load_printer(s.printer)
            p.nozzle, p.layer, p.line_width = pr.nozzle, pr.layer_height, pr.line_width
        if s.material:
            from .profiles import load_material

            m = load_material(s.material)
            if m.density:
                p.density, p.density_assumed = m.density, False
        return p

    @property
    def t_wall(self) -> float:
        return self.walls * 1.1 * self.nozzle  # ~0.44 mm per line at 0.4


# ---------------------------------------------------------------------------------------------
# mesh helpers


class Mesh:
    """The part's triangulation: unit normals pointing out, areas, centroids."""

    def __init__(self, part: Part, tol: float = 0.02):
        v, t = tessellate(part, tol, 0.1)
        tri = v[t]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        a = np.linalg.norm(n, axis=1) / 2
        keep = a > 1e-12
        self.tri, self.area = tri[keep], a[keep]
        self.n = n[keep] / (2 * self.area[:, None])
        self.c = self.tri.mean(1)


def _sections(part: Part, step: float, cap: int = 100) -> list:
    """MeshSlicer sections at up to `cap` evenly spaced heights: per height, a list of
    [outer, holes...] loops per face."""
    bb = part.bounding_box()
    z0, z1 = bb.min.Z, bb.max.Z
    n = max(1, min(cap, int(round((z1 - z0) / step))))
    sl = ck.MeshSlicer(part)
    return [sl.section("XY", float(z0 + (i + 0.5) * (z1 - z0) / n), 1e9) for i in range(n)]


# ---------------------------------------------------------------------------------------------
# M1 size, M2 mass, M3 time, M5 supports


def size(part: Part) -> dict:
    """M1: bounding box, volume, area, sorted aspect ratios. Reported only: no proportion rule (DS-G9)."""
    bb = part.bounding_box()
    dims = [bb.size.X, bb.size.Y, bb.size.Z]
    s = sorted(dims, reverse=True)
    return {"x": round(dims[0], 2), "y": round(dims[1], 2), "z": round(dims[2], 2),
            "volume": round(part.volume, 1), "area": round(part.area, 1),
            "ratios": [round(x / s[-1], 2) if s[-1] > 0 else None for x in s]}


def shell_volume(mesh: Mesh, volume: float, p: Params) -> float:
    """DS-C1: per triangle, t = max(cap thickness x |n_z|, wall thickness x sqrt(1 - n_z^2))."""
    nz = np.clip(mesh.n[:, 2], -1, 1)
    cap = np.where(nz > 0, p.top_layers * p.layer, p.bottom_layers * p.layer) * np.abs(nz)
    side = p.t_wall * np.sqrt(1 - nz * nz)
    return float(min(volume, np.sum(mesh.area * np.maximum(cap, side))))


def mass(part: Part, mesh: Mesh, p: Params) -> dict:
    """M2 (+ M4 cost): extruded = shell + infill x (V - shell); mass = extruded x density."""
    V = part.volume
    sh = shell_volume(mesh, V, p)
    ext = sh + p.infill * (V - sh)
    g = ext * p.density / 1000
    out = {"grams": round(g, 1), "extruded_mm3": round(ext), "shell_share": round(sh / ext, 3) if ext else 0.0,
           "infill_share": round(1 - sh / ext, 3) if ext else 0.0, "density": p.density,
           "accuracy": "simple estimate, roughly ±20 %"}
    if p.price:
        out["cost"] = round(g * p.price / 1000, 2)
    return out


def print_time(part: Part, extruded: float, p: Params) -> dict:
    """M3 (DS-C3, DS-C7), one rule: extruded volume / print_flow + layers x 3 s. A rough estimate."""
    layers = max(1, int(round(part.bounding_box().size.Z / p.layer)))
    total = extruded / p.flow + layers * LAYER_S
    return {"minutes": round(total / 60, 1), "layers": layers,
            "layer_share": round(layers * LAYER_S / total, 3) if total else 0.0,
            "rule": f"extruded / {p.flow:g} mm3/s + {layers} layers x {LAYER_S:g} s",
            "accuracy": "rough estimate"}


def supports(part: Part, mesh: Mesh, p: Params, faces: list | None = None) -> dict:
    """M5: downward faces steeper than max_overhang that are not bridges within max_bridge;
    column = area x |n_z| x height above whatever is below (ray down); supports ~20 % solid (DS-C4)."""
    zmin = part.bounding_box().min.Z
    edge_faces = None
    rows, pts, wts = [], [], []
    for f in faces if faces is not None else part.faces():
        t = ck._down_tris(f, 0.05)
        if t is None:
            continue
        tri, n, area, ang = t
        flag = (n[:, 2] < 0) & (ang > p.max_overhang + 0.5) & (tri[:, :, 2].max(1) > zmin + 0.05)
        if not flag.any():
            continue
        if ang[flag].min() > 89 and f.geom_type.name == "PLANE":
            edge_faces = edge_faces if edge_faces is not None else ck._edge_faces(part)
            b = ck.bridge_span(f, part, edge_faces=edge_faces)
            if b.get("kind") == "bridge" and b.get("span", 1e9) <= p.max_bridge:
                continue
        c = tri[flag].mean(1)
        w = area[flag] * np.abs(n[flag][:, 2])
        pts.append(c)
        wts.append(w)
        cc = (c * w[:, None]).sum(0) / w.sum()
        rows.append({"kind": f.geom_type.name.lower(), "area": round(float(area[flag].sum()), 1),
                     "center": [round(float(x), 1) for x in cc]})
    if not rows:
        return {"area": 0.0, "column_mm3": 0.0, "grams": 0.0, "faces": []}
    P, W = np.concatenate(pts), np.concatenate(wts)
    floor = _floor_below(mesh, P, zmin)
    col = float(np.sum(W * np.maximum(P[:, 2] - floor, 0)))
    vol = SUPPORT_FILL * col
    return {"area": round(float(sum(r["area"] for r in rows)), 1), "column_mm3": round(col),
            "volume_mm3": round(vol), "grams": round(vol * p.density / 1000, 1), "faces": rows,
            "accuracy": "rough estimate"}


def _floor_below(mesh: Mesh, P: np.ndarray, zmin: float) -> np.ndarray:
    """Height of the highest up-facing surface under each point (the bed if none)."""
    up = mesh.n[:, 2] > 1e-6
    T = mesh.tri[up]
    out = np.full(len(P), zmin)
    if not len(T):
        return out
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    v0, v1 = c[:, :2] - a[:, :2], b[:, :2] - a[:, :2]
    d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    ok = np.abs(den) > 1e-12
    for i0 in range(0, len(P), 256):
        q = P[i0:i0 + 256]
        v2 = q[:, None, :2] - a[None, :, :2]
        d02, d12 = (v2 * v0[None]).sum(2), (v2 * v1[None]).sum(2)
        with np.errstate(divide="ignore", invalid="ignore"):
            u = (d11 * d02 - d01 * d12) / den
            v = (d00 * d12 - d01 * d02) / den
        inside = ok[None] & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        z = a[None, :, 2] + u * (c[None, :, 2] - a[None, :, 2]) + v * (b[None, :, 2] - a[None, :, 2])
        z = np.where(inside & (z < q[:, None, 2] - 1e-3), z, -np.inf)
        out[i0:i0 + 256] = np.maximum(out[i0:i0 + 256], z.max(1))
    return out


# ---------------------------------------------------------------------------------------------
# M6 stepping


_DIRS = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


def parse_dirs(value) -> list[str]:
    items = [value] if isinstance(value, str) else list(value or [])
    out = []
    for x in items:
        for d in str(x).replace(",", " ").split():
            d = d.upper() if d[0] in "+-" else "+" + d.upper()
            if d not in _DIRS:
                raise ValueError(f"direction {x!r}: use +X, -X, +Y, -Y, +Z or -Z")
            out.append(d)
    return out


def _show_mask(mesh: Mesh, show: list[str]) -> np.ndarray:
    """Triangles facing one of the visible directions (within 60 deg)."""
    if not show:
        return np.ones(len(mesh.area), bool)
    m = np.zeros(len(mesh.area), bool)
    for d in show:
        m |= mesh.n @ np.array(_DIRS[d], float) > 0.5
    return m


def stepping(mesh: Mesh, p: Params, show: list[str] | None = None) -> dict:
    """M6 (DS-S1): cusp height h = layer x |n_z|; the stepping band is the area tilted 1-30 deg from
    flat (shallow slopes, not flat faces), up-facing and down-facing."""
    nz = np.clip(mesh.n[:, 2], -1, 1)
    tilt = np.degrees(np.arccos(np.abs(nz)))
    band = (tilt > 1) & (tilt < 30)
    up = nz > math.sin(math.radians(1))
    vis = _show_mask(mesh, show or [])
    up_area = float(mesh.area[up & vis].sum())
    band_up = float(mesh.area[band & up & vis].sum())
    band_down = float(mesh.area[band & (nz < 0) & vis].sum())
    cusp = float(np.sum(mesh.area * p.layer * np.abs(nz)) / mesh.area.sum()) if len(mesh.area) else 0.0
    return {"band_up_cm2": round(band_up / 100, 2), "band_up_share": round(band_up / up_area, 3) if up_area else 0.0,
            "band_down_cm2": round(band_down / 100, 2), "mean_cusp_mm": round(cusp, 3),
            "scope": "visible faces " + ",".join(show) if show else "all faces"}


# ---------------------------------------------------------------------------------------------
# M7 edges


class _Inside:
    """Point-in-solid with one OCC classifier for the whole part (Shape.is_inside builds a new one
    per call, which made M7 take half a minute on a 600-face coupon)."""

    def __init__(self, part: Part):
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier

        self.c = BRepClass3d_SolidClassifier(part.wrapped)

    def __call__(self, p) -> bool:
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN

        self.c.Perform(gp_Pnt(*map(float, p)), 1e-6)
        return self.c.State() == TopAbs_IN


def _probe_convex(inside: _Inside, p, n1, n2) -> bool:
    """Seen across the edge, the solid fills less than half a turn at a convex edge and more at a
    concave one; the direction n1 - n2 is a quarter turn from the middle of the solid's side, so
    it leaves the solid at a convex edge and stays in it at a concave one."""
    d = n1 - n2
    L = float(np.linalg.norm(d))
    return L > 1e-9 and not inside(p + d / L * 0.01)


def _vec3(v) -> np.ndarray:
    return np.array([v.X, v.Y, v.Z], float)


def _blend_radius(f) -> float | None:
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    s = BRepAdaptor_Surface(f.wrapped)
    if f.geom_type.name == "CYLINDER":
        return s.Cylinder().Radius()
    if f.geom_type.name == "TORUS":
        return s.Torus().MinorRadius()
    return None


def _edge_info(part: Part) -> list[tuple]:
    """(edge, face_a, face_b, turn deg, convex) for every edge shared by two faces."""
    ef = ck._edge_faces(part)
    edges = {hash(e): e for f in part.faces() for e in f.edges()}
    inside = _Inside(part)
    out = []
    for h, fl in ef.items():
        if len(fl) != 2:
            continue
        e = edges[h]
        pm = e.position_at(0.5)
        try:
            n1, n2 = _vec3(fl[0].normal_at(pm)), _vec3(fl[1].normal_at(pm))
        except Exception:  # noqa: BLE001 - a degenerate face: skip the edge
            continue
        turn = math.degrees(math.acos(max(-1.0, min(1.0, float(n1 @ n2)))))
        convex = turn >= 5 and _probe_convex(inside, _vec3(pm), n1, n2)
        out.append((e, fl[0], fl[1], turn, convex))
    return out


def edges(part: Part, max_overhang: float = 45.0, info: list | None = None) -> dict:
    """M7 (DS-G1, DS-S4): outside (convex) edges by length: filleted (convex cylinder/torus blend
    faces, by spine length), chamfered (narrow planar faces between two 20-70 deg convex turns),
    sharp (other convex edges turning > 20 deg). Bed edges (on the lowest Z) are counted apart;
    holes, their rims and full bosses are not counted."""
    from OCP.BRepTools import BRepTools

    zmin = part.bounding_box().min.Z
    info = _edge_info(part) if info is None else info
    by_face: dict = {}
    for row in info:
        for f in (row[1], row[2]):
            by_face.setdefault(hash(f), []).append(row)
    hole_faces = {hash(f) for h in ck.holes(part) for f in h["faces"]}

    def on_bed(e) -> bool:
        return all(e.position_at(t).Z < zmin + 0.05 for t in (0.0, 0.5, 1.0))

    fillets, inside_fillets, chamfers, chamfer_faces, down = [], [], [], set(), 0
    for f in part.faces():
        rows = by_face.get(hash(f), [])
        r = _blend_radius(f)
        if r is not None and hash(f) not in hole_faces:
            tangent = [x for x in rows if x[3] < 5]
            if not tangent:
                continue
            u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
            span = (u1 - u0) if f.geom_type.name == "CYLINDER" else (v1 - v0)
            if span >= math.radians(180):
                continue  # a boss or a round end, not an edge blend
            spine = f.area / (r * span) if span > 0 else 0.0
            convex = _blend_convex(f)
            entry = {"r": round(r, 2), "length": spine, "bed": f.bounding_box().min.Z < zmin + 0.05 and
                     f.bounding_box().max.Z < zmin + r + 0.1}
            if convex:
                fillets.append(entry)
                t = ck._down_tris(f)
                if t is not None and (t[3][t[1][:, 2] < 0] > max_overhang + 0.5).any() and not entry["bed"]:
                    down += 1
            else:
                inside_fillets.append(entry)
        elif f.geom_type.name == "PLANE" and rows:
            long = sorted(rows, key=lambda x: -x[0].length)[:2]
            if len(long) < 2:
                continue
            L = long[0][0].length
            width = 2 * f.area / (L + long[1][0].length) if L > 0 else 1e9  # a trapezoid: mitred ends
            if width > 3.0 or not all(x[4] and 20 <= x[3] <= 70 for x in long):
                continue
            leg = width * math.cos(math.radians(long[0][3]))
            chamfers.append({"size": round(leg, 2), "width": round(width, 2), "length": L,
                             "bed": on_bed(long[0][0]) or on_bed(long[1][0])})
            chamfer_faces.add(hash(f))
    sharp = sharp_bed = 0.0
    for e, a, b, turn, convex in info:
        if not convex or turn <= 20 or {hash(a), hash(b)} & (chamfer_faces | hole_faces):
            continue
        if on_bed(e):
            sharp_bed += e.length
        else:
            sharp += e.length
    fil = sum(x["length"] for x in fillets if not x["bed"])
    cha = sum(x["length"] for x in chamfers if not x["bed"])
    total = sharp + fil + cha
    radii = sorted({x["r"] for x in fillets})
    sizes = sorted({x["size"] for x in chamfers if not x["bed"]})
    return {
        "outside_mm": round(total, 1),
        "sharp_share": round(sharp / total, 3) if total else 0.0,
        "fillet_share": round(fil / total, 3) if total else 0.0,
        "chamfer_share": round(cha / total, 3) if total else 0.0,
        "radii": _cluster(radii),
        "radius_families": _families(_cluster(radii)),
        "chamfer_sizes": _cluster(sizes),
        "inside_radii": _cluster(sorted({x["r"] for x in inside_fillets})),
        "bed_edges": {"chamfered_mm": round(sum(x["length"] for x in chamfers if x["bed"]), 1),
                      "filleted_mm": round(sum(x["length"] for x in fillets if x["bed"]), 1),
                      "sharp_mm": round(sharp_bed, 1)},
        "downward_fillets": down,
    }


def _blend_convex(f) -> bool:
    """A blend face is convex (an outside rounding) when its outward normal points away from its
    centre of curvature (the cylinder's axis, the torus's tube centre); an inside fillet's normal
    points towards it."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    p = _vec3(f.position_at(0.5, 0.5))
    n = _vec3(f.normal_at(f.position_at(0.5, 0.5)))
    s = BRepAdaptor_Surface(f.wrapped)
    if f.geom_type.name == "CYLINDER":
        ax = s.Cylinder().Axis()
        loc = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        d = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        q = loc + ((p - loc) @ d) * d
    else:
        t = s.Torus()
        ax = t.Axis()
        C = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
        D = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
        w = (p - C) - ((p - C) @ D) * D
        q = C + t.MajorRadius() * w / max(np.linalg.norm(w), 1e-12)
    return float((p - q) @ n) > 0


def _cluster(vals: list[float], tol: float = 0.05) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _families(radii: list[float]) -> dict:
    """DS-S9 (1 src): edge breaks (<= 1 mm) read as crisp edges, larger radii as styling."""
    return {"edge_break": [r for r in radii if r <= 1.0], "styling": [r for r in radii if r > 1.0]}


# ---------------------------------------------------------------------------------------------
# M12 inside corners, M13 walls, M14 hole edge distance, M15 slenderness (load-bearing parts)


def _ray_depth(inside: _Inside, part: Part, p, d) -> float | None:
    """How far a ray from just inside the surface at p, along d (into the solid), travels before
    it leaves the solid; None when it does not start inside."""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

    d = d / np.linalg.norm(d)
    q = p + d * 0.02
    if not inside(q):
        return None
    it = BRepIntCurveSurface_Inter()
    it.Init(part.wrapped, gp_Lin(gp_Pnt(*map(float, q)), gp_Dir(*map(float, d))), 1e-6)
    hits = []
    while it.More():
        if it.W() > 1e-6:
            hits.append(it.W())
        it.Next()
    return min(hits) + 0.02 if hits else None


def _near_hole(pt, hole_list: list) -> bool:
    """On a hole's wall or roof: within 1.5 radii of its axis (a teardrop's tip is at 1.41) and
    along its length."""
    for h in hole_list:
        ax, c = np.array(h["axis"], float), np.array(h["center"], float)
        v = np.asarray(pt, float) - c
        along = float(v @ ax)
        if abs(along) <= h["length"] / 2 + 0.1 and np.linalg.norm(v - along * ax) <= 0.75 * h["d"] + 0.05:
            return True
    return False


def inside_corners(part: Part, info: list | None = None, hole_list: list | None = None) -> dict:
    """M12 (DS-T3): inside (concave) edges by length: filleted (concave cylinder/torus blend faces,
    by spine length), chamfered (narrow planar faces between two 20-70 deg concave turns), sharp
    (other concave edges turning > 20 deg). Holes, their rims and teardrop roofs are not counted.
    Per inside fillet: radius / the thinner of the two walls it joins, each measured by a ray
    from the fillet's tangent edge straight through that wall."""
    from OCP.BRepTools import BRepTools

    info = _edge_info(part) if info is None else info
    hole_list = ck.holes(part) if hole_list is None else hole_list
    hole_faces = {hash(f) for h in hole_list for f in h["faces"]}
    by_face: dict = {}
    for row in info:
        for f in (row[1], row[2]):
            by_face.setdefault(hash(f), []).append(row)
    inside = _Inside(part)
    fil = cha = 0.0
    radii, ratios, chamfer_faces = [], [], set()
    for f in part.faces():
        rows = by_face.get(hash(f), [])
        r = _blend_radius(f)
        if r is not None and hash(f) not in hole_faces:
            tangent = [x for x in rows if x[3] < 5]
            if not tangent or _blend_convex(f):
                continue
            u0, u1, v0, v1 = BRepTools.UVBounds_s(f.wrapped)
            span = (u1 - u0) if f.geom_type.name == "CYLINDER" else (v1 - v0)
            if span >= math.radians(180) or _near_hole(_vec3(f.center()), hole_list):
                continue
            fil += f.area / (r * span) if span > 0 else 0.0
            radii.append(round(r, 2))
            walls = []
            for e, a, b, _, _ in tangent:
                other = b if hash(a) == hash(f) else a
                pm = e.position_at(0.5)
                try:
                    n = _vec3(other.normal_at(pm))
                except Exception:  # noqa: BLE001 - a degenerate face: skip it
                    continue
                t = _ray_depth(inside, part, _vec3(pm), -n)
                if t is not None:
                    walls.append(t)
            if walls:
                c = f.center()
                ratios.append({"r": round(r, 2), "wall": round(min(walls), 2), "ratio": round(r / min(walls), 2),
                               "at": [round(c.X, 1), round(c.Y, 1), round(c.Z, 1)]})
        elif f.geom_type.name == "PLANE" and rows:
            long = sorted(rows, key=lambda x: -x[0].length)[:2]
            if len(long) < 2:
                continue
            L = long[0][0].length
            width = 2 * f.area / (L + long[1][0].length) if L > 0 else 1e9
            if width <= 3.0 and all(not x[4] and 20 <= x[3] <= 70 for x in long):
                cha += L
                chamfer_faces.add(hash(f))
    sharp = []
    for e, a, b, turn, convex in info:
        if convex or turn <= 20 or {hash(a), hash(b)} & (chamfer_faces | hole_faces):
            continue
        pm = e.position_at(0.5)
        if _near_hole(_vec3(pm), hole_list):
            continue
        sharp.append({"length": round(e.length, 1), "at": [round(pm.X, 1), round(pm.Y, 1), round(pm.Z, 1)],
                      "turn": round(turn)})
    total = sum(x["length"] for x in sharp) + fil + cha
    sharp.sort(key=lambda x: -x["length"])
    ratios.sort(key=lambda x: x["ratio"])
    return {
        "inside_mm": round(total, 1),
        "sharp_share": round(sum(x["length"] for x in sharp) / total, 3) if total else 0.0,
        "fillet_share": round(fil / total, 3) if total else 0.0,
        "chamfer_share": round(cha / total, 3) if total else 0.0,
        "sharp": sharp[:5],
        "radii": _cluster(sorted(set(radii))),
        "worst_ratio": ratios[0] if ratios else None,
    }


def walls(part: Part, p: Params) -> dict:
    """M13 (DS-T4): the thinnest walls under p.wall_lines line widths, from the thin-feature
    sections the ThinFeature check uses (knife edges and tapers apart: they are edges, not walls).
    Those take seconds, so only for a style that sets min_wall_lines."""
    if not p.wall_lines:
        return {"below_mm": None, "line_width": p.line_width, "count": 0, "skipped": "the style sets no min_wall_lines"}
    limit = p.wall_lines * p.line_width
    spots = [s for s in ck.thin_features(part, limit) if not s["taper"]]
    out = {"below_mm": round(limit, 2), "line_width": p.line_width, "count": len(spots)}
    if spots:
        out.update(thinnest_mm=round(spots[0]["min"], 2), lines=round(spots[0]["min"] / p.line_width, 1),
                   at=spots[0]["at"], spots=[{"mm": round(s["min"], 2), "at": s["at"]} for s in spots[:4]])
    return out


def _seg_dist(c: np.ndarray, lp: np.ndarray) -> float:
    """Distance from a point to a closed polyline."""
    a, b = lp, np.roll(lp, -1, 0)
    ab = b - a
    t = np.clip(np.sum((c - a) * ab, 1) / np.maximum(np.sum(ab * ab, 1), 1e-12), 0, 1)
    return float(np.min(np.linalg.norm(a + t[:, None] * ab - c, axis=1)))


def _round_about(lp: np.ndarray, c: np.ndarray, tol: float = 0.05) -> bool:
    """Is the loop a circle (within tol of its mean radius) about c?"""
    r = np.linalg.norm(lp - c, axis=1)
    return bool(r.mean() > 0 and r.std() / r.mean() < tol)


def hole_edges(part: Part, p: Params, hole_list: list | None = None) -> dict:
    """M14 (DS-T7): for each fastener hole (M9's screw sizes) along X, Y or Z, the distance from its
    axis to the nearest edge of the material around it, in a section through the middle of the
    hole, over the hole's (as printed) diameter. Other round holes and bosses (an outline round
    about the hole: the Wall check measures those, BP-T4) are not edges."""
    from matplotlib.path import Path as MPath

    sl = None
    rows = []
    for h in ck.holes(part) if hole_list is None else hole_list:
        k = int(np.argmax(np.abs(h["axis"])))
        if abs(h["axis"][k]) < 0.999:
            continue
        d = h["d"] - (p.hole_comp if h["vertical"] else p.hole_comp_h)
        fc = fastener_class(d)
        if not fc:
            continue
        sl = sl or ck.MeshSlicer(part)
        plane = ("YZ", "XZ", "XY")[k]
        c = np.array([h["center"][i] for i in range(3) if i != k], float)
        best = None
        for loops in sl.section(plane, float(h["center"][k]), 1e9):
            own = [i for i, lp in enumerate(loops[1:], 1) if MPath(lp).contains_point(c)
                   and np.linalg.norm(lp - c, axis=1).max() <= 0.75 * h["d"] + 0.1]
            if not own:
                continue
            if _round_about(loops[0], c):
                break  # a boss: its wall is BP-T4's Wall check
            edges_ = [loops[0]] + [lp for i, lp in enumerate(loops[1:], 1)
                                   if i not in own and not _round_about(lp, lp.mean(0))]
            best = min(_seg_dist(c, lp) for lp in edges_)
            break
        if best is not None:
            rows.append({"size": fc[0], "d": round(d, 2), "edge_mm": round(best, 2), "ratio": round(best / d, 2),
                         "at": h["center"]})
    rows.sort(key=lambda x: x["ratio"])
    return {"holes": rows, "worst": rows[0] if rows else None}


def slenderness(part: Part, faces_per_level: list) -> dict:
    """M15 (DS-T1): a part standing tall on a small section breaks along a layer when it is pulled
    or bent. At each XY section (M10's), the run of neighbouring sections no more than 1.5 x its
    area (the post, wall or arm it belongs to), as long as the run is tall, over the square
    root of the section's area. A post of height H and diameter D scores 1.13 H / D; a tapering
    tip scores low (its run is short)."""
    bb = part.bounding_box()
    n = len(faces_per_level)
    dz = (bb.max.Z - bb.min.Z) / n if n else 0.0
    areas = []
    for faces in faces_per_level:
        area = 0.0
        for loops in faces:
            for j, lp in enumerate(loops):
                a = 0.5 * abs(float(np.sum(lp[:, 0] * np.roll(lp[:, 1], -1) - np.roll(lp[:, 0], -1) * lp[:, 1])))
                area += a if j == 0 else -a
        areas.append(area)
    best = {"value": 0.0, "z": None, "area_mm2": None, "run_mm": None}
    for i, a in enumerate(areas):
        if a <= 1e-6:
            continue
        lo = hi = i
        while lo > 0 and 0 < areas[lo - 1] <= 1.5 * a:
            lo -= 1
        while hi < n - 1 and 0 < areas[hi + 1] <= 1.5 * a:
            hi += 1
        run = (hi - lo + 1) * dz
        v = run / math.sqrt(a)
        if v > best["value"]:
            best = {"value": round(v, 2), "z": round(bb.min.Z + (i + 0.5) * dz, 2), "area_mm2": round(a, 1),
                    "run_mm": round(run, 1)}
    return best


# ---------------------------------------------------------------------------------------------
# M8 symmetry, M9 economy, M10 seams, M11 water traps


def symmetry(part: Part) -> dict:
    """M8 (DS-G7): vol(part & mirror) / vol(part) for the YZ (x), XZ (y) and XY (z) planes through
    the bounding-box centre; best of x and y (z reported, rarely meaningful)."""
    from build123d import Plane

    c = part.bounding_box().center()
    V = part.volume
    out = {}
    for k, nrm in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        try:
            m = part.mirror(Plane(origin=c, z_dir=nrm))
            out[k] = round(min(1.0, (part & m).volume / V), 3) if V > 0 else 0.0
        except Exception:  # noqa: BLE001 - a boolean that OCC cannot do: unknown
            out[k] = None
    out["best"] = max((out[k] for k in ("x", "y") if out[k] is not None), default=None)
    return out


# metric screws: clearance (normal fit), heat-set insert (CNC Kitchen), tap pilot; BP-T2, BP-T6
_SCREWS = {2: (2.4, 3.2, 1.7), 2.5: (2.9, 3.6, 2.1), 3: (3.4, 4.0, 2.6), 4: (4.5, 5.6, 3.4), 5: (5.5, 6.4, 4.3),
           6: (6.6, 8.0, 5.1), 8: (9.0, 10.0, 6.8)}


def fastener_class(d: float) -> tuple[str, str] | None:
    """(size, role) for a hole diameter (as printed, without hole_comp), or None."""
    best = None
    for m, (clr, ins, pil) in _SCREWS.items():
        for role, ref, tol in (("clearance", clr, 0.3), ("insert", ins, 0.15), ("pilot", pil, 0.2)):
            e = abs(d - ref)
            if e <= tol and (best is None or e < best[0]):
                best = (e, f"M{m:g}", role)
    return None if best is None else best[1:]


def economy(parts: dict, hole_comp: float = 0.0, hole_comp_h: float = 0.0) -> dict:
    """M9 (DS-G2, DS-G3): parts, solids, faces; holes grouped into likely screw sizes."""
    sizes: dict = {}
    other = []
    for name, p in parts.items():
        for h in ck.holes(p):
            d = h["d"] - (hole_comp if h["vertical"] else hole_comp_h)
            fc = fastener_class(d)
            if fc:
                sizes.setdefault(fc[0], {"count": 0, "roles": set()})
                sizes[fc[0]]["count"] += 1
                sizes[fc[0]]["roles"].add(fc[1])
            else:
                other.append(round(d, 2))
    return {"parts": len(parts), "solids": sum(len(p.solids()) for p in parts.values()),
            "faces": sum(len(p.faces()) for p in parts.values()),
            "screw_sizes": {k: {"count": v["count"], "roles": sorted(v["roles"])} for k, v in sorted(sizes.items())},
            "other_holes": sorted(set(other)), "note": "screw sizes are guessed from hole diameters"}


def seam_corners(faces_per_level: list, min_turn: float = 30.0) -> dict:
    """M10 (DS-S3): share of layers whose outer contour has a corner turning more than min_turn
    degrees (where a slicer can hide the seam)."""
    hit = total = 0
    for faces in faces_per_level:
        if not faces:
            continue
        total += 1
        for loops in faces:
            lp = loops[0]
            a = np.roll(lp, -1, 0) - lp
            b = np.roll(a, -1, 0)
            la, lb = np.linalg.norm(a, axis=1), np.linalg.norm(b, axis=1)
            ok = (la > 1e-6) & (lb > 1e-6)
            cosang = np.sum(a * b, 1)[ok] / (la[ok] * lb[ok])
            if (np.degrees(np.arccos(np.clip(cosang, -1, 1))) > min_turn).any():
                hit += 1
                break
    return {"share": round(hit / total, 3) if total else 0.0, "layers_sampled": total}


# rotations (axis, degrees) that turn each direction to +Z
_TO_UP = {"+X": ((0, 1, 0), -90), "-X": ((0, 1, 0), 90), "+Y": ((1, 0, 0), 90), "-Y": ((1, 0, 0), -90),
          "-Z": ((1, 0, 0), 180)}


def water_traps(part: Part, up: str = "+Z", res: float | None = None, max_cells: int = 2_000_000) -> dict:
    """M11 (DS-R3): water that stays in the part with `up` pointing up. Voxel grid (1 mm, 0.5 mm
    for parts under 30 mm) with one cell of air around; air drains when it can reach the sides or
    the bottom of the grid moving sideways or down. Air that cannot drain but is open to the top is
    a trap; sealed voids are not."""
    from build123d import Axis
    from matplotlib.path import Path as MPath
    from scipy import ndimage

    p = part
    if up != "+Z":
        ax, deg = _TO_UP[up]
        p = part.rotate(Axis((0, 0, 0), ax), deg)
    bb = p.bounding_box()
    span = max(bb.size.X, bb.size.Y, bb.size.Z)
    if res is None:
        res = 0.5 if span < 30 else 1.0
    vol = (bb.size.X / res + 2) * (bb.size.Y / res + 2) * (bb.size.Z / res + 2)
    if vol > max_cells:
        res *= (vol / max_cells) ** (1 / 3)
    nx, ny, nz = (int(math.ceil(s / res)) + 2 for s in (bb.size.X, bb.size.Y, bb.size.Z))
    x0, y0, z0 = bb.min.X - res, bb.min.Y - res, bb.min.Z - res
    xs = x0 + (np.arange(nx) + 0.5) * res
    ys = y0 + (np.arange(ny) + 0.5) * res
    zs = z0 + (np.arange(nz) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    solid = np.zeros((nx, ny, nz), bool)
    sl = ck.MeshSlicer(p)
    for k, z in enumerate(zs):
        if z <= bb.min.Z or z >= bb.max.Z:
            continue
        inside = np.zeros(len(pts), bool)
        for loops in sl.section("XY", float(z), 1e9):
            m = MPath(loops[0]).contains_points(pts)
            for hole in loops[1:]:
                m &= ~MPath(hole).contains_points(pts)
            inside |= m
        solid[:, :, k] = inside.reshape(nx, ny)
    air = ~solid
    # drain: start at air cells on the sides and bottom, spread to air at the same or a higher level
    drain = np.zeros_like(air)
    drain[0], drain[-1], drain[:, 0], drain[:, -1], drain[:, :, 0] = air[0], air[-1], air[:, 0], air[:, -1], air[:, :, 0]
    frontier = drain.copy()
    while frontier.any():
        grow = np.zeros_like(frontier)
        grow[1:] |= frontier[:-1]
        grow[:-1] |= frontier[1:]
        grow[:, 1:] |= frontier[:, :-1]
        grow[:, :-1] |= frontier[:, 1:]
        grow[:, :, 1:] |= frontier[:, :, :-1]  # up only: water reached from above drains down here
        frontier = grow & air & ~drain
        drain |= frontier
    wet = air & ~drain
    labels, n = ndimage.label(wet)
    top_open = set(np.unique(labels[:, :, -1])) - {0}
    traps = []
    for i in range(1, n + 1):
        cells = labels == i
        if i not in top_open and not _open_above(cells, air):
            continue  # sealed void
        idx = np.argwhere(cells)
        c = idx.mean(0)
        traps.append({"cm3": round(cells.sum() * res ** 3 / 1000, 2),
                      "center": [round(float(x0 + (c[0] + 0.5) * res), 1), round(float(y0 + (c[1] + 0.5) * res), 1),
                                 round(float(z0 + (c[2] + 0.5) * res), 1)],
                      "lowest_z": round(float(z0 + (idx[:, 2].min() + 0.5) * res), 1)})
    traps.sort(key=lambda t: -t["cm3"])
    return {"cm3": round(sum(t["cm3"] for t in traps), 2), "traps": traps, "up": up, "voxel_mm": round(res, 2)}


def _open_above(cells: np.ndarray, air: np.ndarray) -> bool:
    """Does this wet region touch air that drains (i.e. is it reachable from outside from above)?"""
    from scipy import ndimage

    grown = ndimage.binary_dilation(cells) & air & ~cells
    return bool(grown.any())


# ---------------------------------------------------------------------------------------------
# all of it, and the style findings


def part_metrics(part: Part, p: Params, show: list[str] | None = None, up: str = "+Z") -> dict:
    mesh = Mesh(part)
    m: dict = {"size": size(part)}
    m["mass"] = mass(part, mesh, p)
    faces = _sections(part, p.layer)
    m["supports"] = supports(part, mesh, p)
    m["time"] = print_time(part, m["mass"]["extruded_mm3"] + m["supports"].get("volume_mm3", 0), p)
    if p.price and m["supports"].get("grams"):
        m["supports"]["cost"] = round(m["supports"]["grams"] * p.price / 1000, 2)
    m["stepping"] = stepping(mesh, p, show)
    info, hole_list = _edge_info(part), ck.holes(part)
    m["edges"] = edges(part, p.max_overhang, info)
    m["symmetry"] = symmetry(part)
    m["seam_corners"] = seam_corners(faces)
    m["water"] = water_traps(part, up)
    m["inside_corners"] = inside_corners(part, info, hole_list)
    m["walls"] = walls(part, p)
    m["hole_edges"] = hole_edges(part, p, hole_list)
    m["slenderness"] = slenderness(part, faces)
    return m


def findings(style: Style, m: dict, eco: dict, p: Params, show: list[str], edges_pref: str = "") -> list[dict]:
    """The style file's thresholds (styles.THRESHOLDS) as suggest/note lines, plus a few notes for
    every style. The built-in thresholds are the project's starting values (DESIGN_GUIDE 4)."""
    out: list[dict] = []
    T = THRESHOLDS

    def add(field, msg):
        level, rule, _ = T[field]
        out.append({"level": level, "rule": rule, "message": msg})

    e, st, sup, mass_ = m["edges"], m["stepping"], m["supports"], m["mass"]
    # every style: notes
    if sup.get("grams"):
        out.append({"level": "note", "rule": "DS-C4",
                    "message": f"supports ~{sup['grams']} g under {len(sup['faces'])} face(s); supported faces come out rough"})
    if e["downward_fillets"]:
        out.append({"level": "note", "rule": "DS-S4",
                    "message": f"{e['downward_fillets']} fillet(s) face down past the overhang limit: a chamfer prints cleaner"})
    if edges_pref == "chamfer" and e["fillet_share"] > e["chamfer_share"]:
        out.append({"level": "suggest", "rule": "DS-G1", "message": f"EDGES='chamfer' but fillets are {e['fillet_share']:.0%} of "
                    f"outside edges vs chamfers {e['chamfer_share']:.0%}: use chamfers (constant printable angle, DS-S4)"})
    if edges_pref == "fillet" and e["chamfer_share"] > e["fillet_share"]:
        out.append({"level": "suggest", "rule": "DS-G1", "message": f"EDGES='fillet' but chamfers are {e['chamfer_share']:.0%} "
                    "of outside edges: use fillets (chamfer the bed edges only)"})
    if edges_pref and style.max_chamfer_sizes is None and len(e["chamfer_sizes"]) > 2:
        out.append({"level": "suggest", "rule": "DS-G1",
                    "message": f"{len(e['chamfer_sizes'])} chamfer sizes {e['chamfer_sizes']}: use one or two"})

    s = style
    if s.max_shallow_slope_share is not None and st["band_up_share"] > s.max_shallow_slope_share:
        add("max_shallow_slope_share", f"{st['band_up_share']:.0%} of the up-facing area ({st['scope']}) is a shallow slope "
            f"({st['band_up_cm2']} cm2) that shows layer steps: turn the part, make the face steeper or flat, or use "
            "variable layer height")
    if s.supports_on_visible and show and "-Z" in show and sup.get("grams"):
        add("supports_on_visible", f"supports sit under the visible -Z side ({len(sup['faces'])} face(s)): turn the part")
    if s.seam_note and m["seam_corners"]["share"] < 0.1:
        add("seam_note", "no sharp corner on the outer contour for the seam to hide in: if one side shows, add a small "
                         "vertical groove or edge on the back")
    if s.max_screw_sizes is not None and len(eco["screw_sizes"]) > s.max_screw_sizes:
        add("max_screw_sizes", f"{len(eco['screw_sizes'])} screw sizes ({', '.join(eco['screw_sizes'])}): standardize "
                               f"on {s.max_screw_sizes} or fewer")
    treated = e["fillet_share"] + e["chamfer_share"]
    if s.min_treated_edge_share is not None and e["outside_mm"] and treated < s.min_treated_edge_share:
        add("min_treated_edge_share", f"{treated:.0%} of outside edges are rounded or chamfered (target "
                                      f"{s.min_treated_edge_share:.0%}, bed edges apart)")
    fam = e["radius_families"]
    if s.max_edge_break_sizes is not None and len(fam["edge_break"]) > s.max_edge_break_sizes:
        add("max_edge_break_sizes", f"edge-break radii {fam['edge_break']}: use {s.max_edge_break_sizes}")
    if s.max_styling_radii is not None and len(fam["styling"]) > s.max_styling_radii:
        add("max_styling_radii", f"styling radii {fam['styling']}: use at most {s.max_styling_radii}")
    if s.max_chamfer_sizes is not None and len(e["chamfer_sizes"]) > s.max_chamfer_sizes:
        add("max_chamfer_sizes", f"chamfer sizes {e['chamfer_sizes']}: use at most {s.max_chamfer_sizes}")
    if s.max_sharp_edge_share is not None and e["sharp_share"] > s.max_sharp_edge_share:
        add("max_sharp_edge_share", f"{e['sharp_share']:.0%} of outside edges are sharp (target <= "
                                    f"{s.max_sharp_edge_share:.0%}): round them; where they take knocks, outside "
                                    "radius = inside radius + wall (DS-R7)")
    best = m["symmetry"]["best"]
    if s.min_symmetry is not None and best is not None and best < s.min_symmetry:
        add("min_symmetry", f"best mirror symmetry {best:.2f} (< {s.min_symmetry:g}): fine if the function needs it; ask")
    if s.hidden_screws_note and show and eco["screw_sizes"]:
        add("hidden_screws_note", "keep screw heads off the visible sides " + ",".join(show))
    g = mass_["grams"]
    if s.max_support_share is not None and sup.get("grams") and g and sup["grams"] > s.max_support_share * g:
        add("max_support_share", f"supports ~{sup['grams']} g = {sup['grams'] / g:.0%} of the part's {g} g: turn the part "
                                 "or chamfer the overhangs")
    if s.max_infill_share is not None:
        if mass_["infill_share"] > s.max_infill_share:
            add("max_infill_share", f"infill is {mass_['infill_share']:.0%} of the filament: pocket or hollow the bulk")
        elif mass_["shell_share"] > 0.7:
            out.append({"level": "note", "rule": "DS-C5",
                        "message": f"shell is {mass_['shell_share']:.0%} of the filament: hollowing saves little"})
    if s.max_layer_time_share is not None and m["time"]["layer_share"] > s.max_layer_time_share:
        add("max_layer_time_share", f"about {m['time']['layer_share']:.0%} of the time is per-layer time (a tall, small "
                                    "part): print several at once, or lay it down")
    if s.outdoor_material and p.material in ("", "pla"):
        add("outdoor_material", "material " + (p.material.upper() or "not set") + ": for sun and heat use ASA (PETG in "
                                "shade); PLA softens at ~55 C")
    w = m["water"]
    if s.max_water_cm3 is not None and w["cm3"] > s.max_water_cm3:
        t = w["traps"][0]
        add("max_water_cm3", f"holds {w['cm3']} cm3 of water with {w['up']} up (largest at {t['center']}, low point z "
                             f"{t['lowest_z']}): add a drain at the low point or slope the floor")
    if s.curved_supports_note and sup.get("grams"):
        add("curved_supports_note", "supports on curved faces: organic/tree supports scar less")
    ic = m["inside_corners"]
    if s.max_sharp_inside_share is not None and ic["inside_mm"] and ic["sharp_share"] > s.max_sharp_inside_share:
        where = "; ".join(f"{x['length']:g} mm at {tuple(x['at'])}" for x in ic["sharp"][:3])
        add("max_sharp_inside_share", f"{ic['sharp_share']:.0%} of inside corner length is sharp (target <= "
                                      f"{s.max_sharp_inside_share:.0%}), longest: {where}: fillet the loaded ones, "
                                      "radius at least half the wall")
    wr = ic["worst_ratio"]
    if s.min_inside_radius_ratio is not None and wr and wr["ratio"] < s.min_inside_radius_ratio:
        add("min_inside_radius_ratio", f"inside fillet r {wr['r']:g} on a {wr['wall']:g} mm wall at {tuple(wr['at'])}: "
                                       f"r/wall {wr['ratio']:.2f} (target >= {s.min_inside_radius_ratio:g}): "
                                       f"r {s.min_inside_radius_ratio * wr['wall']:.1f} or more")
    wl = m["walls"]
    if s.min_wall_lines is not None and wl.get("thinnest_mm") is not None and wl["lines"] < s.min_wall_lines:
        add("min_wall_lines", f"thinnest wall {wl['thinnest_mm']:g} mm = {wl['lines']:g} lines of {wl['line_width']:g} at "
                              f"{tuple(wl['at'])} (target >= {s.min_wall_lines:g} lines, "
                              f"{s.min_wall_lines * wl['line_width']:.2f} mm) where it carries load; "
                              f"{wl['count']} spot(s)")
    sl = m["slenderness"]
    if s.max_z_slenderness is not None and sl["value"] > s.max_z_slenderness:
        add("max_z_slenderness", f"{sl['run_mm']:g} mm stands on a {sl['area_mm2']:g} mm2 section (z {sl['z']:g}; "
                                 f"slenderness {sl['value']:g} > {s.max_z_slenderness:g}): if it is pulled or bent "
                                 "there, it breaks along a layer; lay it down so the load runs along the layers")
    return out


def resolve_style(mod, d, settings) -> tuple[str, str]:
    """(name, source): the script's STYLE (Dims, else module), else the workspace `style`, else functional."""
    for obj in (d, mod):
        v = getattr(obj, "STYLE", None) if obj is not None else None
        if v:
            return normalize(v), "script"
    if settings.style:
        return normalize(settings.style), "settings"
    return "functional", "default"


def script_attr(mod, d, name: str, default=None):
    for obj in (d, mod):
        if obj is not None and getattr(obj, name, None) not in (None, "", (), []):
            return getattr(obj, name)
    return default


def design_metrics(mod, d, parts: dict, settings, style: str | None = None, up: str | None = None) -> dict:
    """Every metric for every printable part, plus the style's findings."""
    p = Params.from_settings(settings)
    name, src = (normalize(style), "argument") if style else resolve_style(mod, d, settings)
    sty = load_style(name, settings.root)
    if sty.min_wall_lines is not None:
        p.wall_lines = sty.min_wall_lines
    show = parse_dirs(script_attr(mod, d, "SHOW", []))
    upd = parse_dirs(up or script_attr(mod, d, "UP", "+Z"))[0]
    edges_pref = str(script_attr(mod, d, "EDGES", "") or sty.edges or "").lower()
    if edges_pref not in EDGE_PREFS:
        raise ValueError(f"EDGES={edges_pref!r}: use 'chamfer', 'fillet' or leave it empty")
    named = {(k or "part"): v for k, v in parts.items()}
    per = {n: part_metrics(v, p, show, upd) for n, v in named.items()}
    eco = economy(named, p.hole_comp, p.hole_comp_h)
    found, seen = [], set()
    for n, m in per.items():
        for f in findings(sty, m, eco, p, show, edges_pref):
            k = (f["rule"], f["message"])
            if k not in seen:
                seen.add(k)
                found.append({**f, "part": n})
    return {
        "style": sty.name, "style_source": src, "style_file": sty.source, "style_label": sty.label,
        "style_description": sty.description, "style_review": sty.review.strip(),
        "edges": edges_pref, "show": show, "up": upd,
        "assumptions": {"walls": p.walls, "top_layers": p.top_layers, "bottom_layers": p.bottom_layers,
                        "infill": p.infill, "layer": p.layer, "nozzle": p.nozzle, "density": p.density,
                        "density_note": "material not set: PLA assumed" if p.density_assumed else p.material,
                        "print_flow": p.flow, "filament_price": p.price, "line_width": p.line_width},
        "parts": per, "economy": eco, "findings": found,
    }


def _strength_line(m: dict) -> str:
    ic, wl, he, sl = m["inside_corners"], m["walls"], m["hole_edges"], m["slenderness"]
    wr = ic["worst_ratio"]
    return (f"  inside corners: sharp {ic['sharp_share']:.0%}, filleted {ic['fillet_share']:.0%}, chamfered "
            f"{ic['chamfer_share']:.0%} of {ic['inside_mm']} mm"
            + (f", smallest r/wall {wr['ratio']:g} (r {wr['r']:g} / {wr['wall']:g})" if wr else "")
            + ("" if wl.get("skipped") else "; walls " + (
                f"{wl['thinnest_mm']:g} mm thinnest ({wl['lines']:g} lines)" if wl.get("thinnest_mm") is not None
                else f"none under {wl['below_mm']:g} mm"))
            + "; hole edge distance " + (f"{he['worst']['ratio']:g} d ({he['worst']['size']})" if he["worst"] else "-")
            + f"; slenderness {sl['value']:g}")


def text(res: dict) -> str:
    """The metrics as a short readable report."""
    a = res["assumptions"]
    lines = [f"style: {res['style']} ({res['style_source']}; {res['style_file']})" + (f", edges: {res['edges']}" if res["edges"] else "")
             + (f", visible: {','.join(res['show'])}" if res["show"] else "") + f", up: {res['up']}",
             f"assumes {a['walls']} walls, {a['infill']:.0%} infill, {a['layer']} mm layers, {a['top_layers']}/"
             f"{a['bottom_layers']} top/bottom, density {a['density']} ({a['density_note']}), print_flow {a['print_flow']:g} mm3/s"]
    for n, m in res["parts"].items():
        s, ms, t, sp = m["size"], m["mass"], m["time"], m["supports"]
        e = m["edges"]
        lines += [
            f"\n{n}: {s['x']} x {s['y']} x {s['z']} mm, {s['volume'] / 1000:.1f} cm3",
            f"  filament {ms['grams']} g" + (f" ({ms['cost']} cost)" if "cost" in ms else "")
            + f", shell {ms['shell_share']:.0%} / infill {ms['infill_share']:.0%}  [{ms['accuracy']}]",
            f"  time ~{t['minutes']:g} min  [{t['accuracy']}: {t['rule']}]",
            f"  supports {sp['grams']} g on {len(sp['faces'])} face(s)" + (f"  [{sp['accuracy']}]" if sp["faces"] else ""),
            f"  edges: sharp {e['sharp_share']:.0%}, filleted {e['fillet_share']:.0%}, chamfered {e['chamfer_share']:.0%} "
            f"of {e['outside_mm']} mm; radii {e['radii'] or '-'}, chamfers {e['chamfer_sizes'] or '-'}; bed edges "
            + (", ".join(f"{k.removesuffix('_mm')} {v:g} mm" for k, v in e["bed_edges"].items() if v) or "-"),
            f"  stepping: {m['stepping']['band_up_cm2']} cm2 up-facing shallow slopes ({m['stepping']['band_up_share']:.0%}, "
            f"{m['stepping']['scope']})",
            f"  symmetry: x {m['symmetry']['x']}, y {m['symmetry']['y']}; seam corners on "
            f"{m['seam_corners']['share']:.0%} of layers; water traps {m['water']['cm3']} cm3 ({m['water']['up']} up)",
            _strength_line(m),
        ]
    eco = res["economy"]
    lines.append(f"\neconomy: {eco['parts']} part(s), {eco['faces']} faces, screw sizes "
                 f"{ {k: v['count'] for k, v in eco['screw_sizes'].items()} or 'none'}")
    if res["findings"]:
        lines.append("\nfindings:")
        for f in res["findings"]:
            lines.append(f"  [{f['level'].upper()}] {f['rule']} {f['part']}: {f['message']}")
    else:
        lines.append("\nno findings for this style")
    if res["style_review"]:
        lines.append(f"\nstyle {res['style']} ({res['style_label'] or res['style']}): {res['style_description']}\n"
                     + res["style_review"])
    return "\n".join(lines)
