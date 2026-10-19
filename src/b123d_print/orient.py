"""Print orientation: rank the ways to put a part on the bed (`suggest_orientation`, `b123d-print orient`).

Candidates: the six axis-aligned orientations, plus each large flat face of the part's convex
hull put down on the bed (every flat face the part can rest on, its own flat faces included);
the same side down twice counts once, and at most MAX_CANDIDATES are scored. Each candidate is
scored with what the checks and the design metrics already measure, nothing new:

- supports: metrics.supports (overhangs steeper than max_overhang that are not bridges within
  max_bridge; area and the support volume under them) and the bridges it found;
- print time: metrics.print_time, supports included (so also height: layers cost time);
- bed contact and tip-over: checks.bed_footprint (the first layer, OrcaSlicer's auto-brim measure);
- the load (DS-T1): with `load` given, or the structural style, how much of it runs across the
  layers (along Z).

Rough estimates, for ranking orientations against each other. Nothing here changes the script:
the result says how to apply the rotation in build(d).
"""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field

import numpy as np
from build123d import CenterOf, Part, Pos, Rot

from . import checks as ck
from . import metrics as M

MAX_CANDIDATES = 12  # orientations scored (six axis-aligned + the largest hull faces); keeps a call to a few seconds
SUPPORT_POINTS = 400  # support columns measured per orientation (metrics.supports max_points)
BRIDGE_MIN_AREA = 5.0  # mm^2: smaller flat ceilings count as supported, unmeasured (their bridge check is slow)
MIN_FACE_SHARE = 0.03  # a hull face smaller than this share of the hull's area is not a candidate
SAME_DIR = math.cos(math.radians(2))  # two down directions within 2 deg are the same orientation

# score weights: lower is better (see docs/using/tools.md "suggest_orientation")
W_TIME = 1.0  # per extra print time, as a share of the fastest candidate's
W_SUPPORT = 4.0  # per share of the part's surface that rests on supports (rough, slow to clean)
W_CONTACT = 0.5  # 1 - contact / the best candidate's contact
W_TIP = 1.0  # per auto-brim estimate / TIP_BRIM, up to 3
W_FALL = 3.0  # nothing on the bed, or the centre of mass outside the footprint
W_STRIP = 1.0  # standing on a thin strip
W_BRIDGE = 0.3  # per bridge longer than max_bridge
W_LOAD = 3.0  # x |cos| of the angle between the load and Z (DS-T1), with a given load
W_LOAD_ASSUMED = 1.5  # the same for the structural style without a load: bending along the long axis assumed

_AXES = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
_SIDES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


def parse_load(value) -> np.ndarray | None:
    """'X', '-y', 'along X', 'x axis', 'XZ' (a diagonal), '1,0,1' or (1, 0, 1) -> a unit vector
    in the part's frame as build(d) returns it; None for nothing. The sign does not matter."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        s = value.strip().lower()
        nums = re.findall(r"-?\d+(?:\.\d+)?", s)
        if len(nums) == 3:
            v = np.array([float(x) for x in nums])
        else:
            s = re.sub(r"\b(along|the|axis|direction|in|load|bending|tension|pull|is)\b", " ", s)
            letters = re.sub(r"[\s+\-_,()]", "", s)
            if not letters or set(letters) - set("xyz"):
                raise ValueError(f"load {value!r}: give a direction like 'X', 'along Y', 'XZ' or '1,0,1'")
            v = np.sum([_AXES[c.upper()] for c in letters], axis=0).astype(float)
    else:
        v = np.asarray(value, float)
    n = float(np.linalg.norm(v))
    if v.shape != (3,) or n < 1e-9:
        raise ValueError(f"load {value!r}: not a direction")
    return v / n


def _rotation_to_down(d: np.ndarray):
    """A rotation (scipy) that turns direction d (part frame) to -Z, so that side goes on the bed.
    Of Rot(x, y, 0) (about Y first, bringing d into the YZ plane, then about X) and Rot(x, 0, z)
    (about Z first), the one with the smallest angles; any turn about Z after it prints the same."""
    from scipy.spatial.transform import Rotation

    d = d / np.linalg.norm(d)
    best = None
    for b in (math.atan2(-d[0], d[2]), math.atan2(d[0], -d[2])):  # Rot(x, y, 0): Ry(b) zeroes d_x
        dz = -math.sin(b) * d[0] + math.cos(b) * d[2]  # Ry(b) d = (0, d_y, dz)
        a = math.atan2(d[1], dz) + math.pi  # then Rx(a) takes (0, d_y, dz) to (0, 0, -1)
        best = _simpler(best, (a, b, 0.0))
    for c in (math.atan2(d[0], d[1]), math.atan2(-d[0], -d[1])):  # Rot(x, 0, z): Rz(c) zeroes d_x
        dy = math.sin(c) * d[0] + math.cos(c) * d[1]
        best = _simpler(best, (math.atan2(dy, d[2]) + math.pi, 0.0, c))
    return Rotation.from_euler("XYZ", best, degrees=True)


def _simpler(best, rad):
    deg = [(math.degrees(x) + 180) % 360 - 180 for x in rad]
    deg = [180.0 if abs(x + 180) < 1e-6 else (0.0 if abs(x) < 1e-6 else x) for x in deg]
    return deg if best is None or sum(map(abs, deg)) < sum(map(abs, best)) - 1e-6 else best


def rot_angles(r) -> tuple[float, float, float]:
    """build123d's Rot(x, y, z) for a scipy rotation (intrinsic XYZ, which is what Rot applies)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # gimbal lock at y = +-90: the angles are still exact
        a = r.as_euler("XYZ", degrees=True)
    a = [0.0 if abs(x) < 5e-3 else round(float(x), 2) + 0.0 for x in a]
    if abs(a[2]) == 180 and abs(a[0]) == 180:  # (180, y, 180) is (0, 180 - y, 0)
        a = [0.0, round((180 - a[1] + 180) % 360 - 180, 2) + 0.0, 0.0]
    return tuple(a)


def _side_name(d: np.ndarray) -> str:
    for k, v in _SIDES.items():
        if float(np.dot(d, v)) > SAME_DIR:
            return k
    return "(" + ", ".join(f"{x:.2g}" for x in np.round(d, 2) + 0.0) + ")"


def hull_faces(points: np.ndarray, min_share: float = MIN_FACE_SHARE) -> list[tuple[np.ndarray, float]]:
    """Flat faces of the convex hull of `points`, as (outward unit normal, area), largest first:
    the hull's triangles grouped by plane (their equations to 0.001), small ones (curves) dropped."""
    from scipy.spatial import ConvexHull

    try:
        h = ConvexHull(np.unique(np.round(points, 4), axis=0))
    except Exception:  # noqa: BLE001 - flat or degenerate: no hull faces, the axis candidates remain
        return []
    tri = h.points[h.simplices]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    eq = h.equations  # outward unit normal, offset
    _, group = np.unique(np.round(eq / [1, 1, 1, max(1.0, float(np.abs(eq[:, 3]).max()))], 3), axis=0, return_inverse=True)
    group = group.ravel()
    sums = np.bincount(group, weights=area)
    total = float(area.sum())
    out: list = []
    for g in np.argsort(-sums):
        if sums[g] < min_share * total:
            break
        n = eq[group == g][0, :3]
        for o in out:  # planes split by rounding, or nearly parallel: one candidate
            if float(o[0] @ n) > math.cos(math.radians(0.5)):
                o[1] += float(sums[g])
                break
        else:
            out.append([n, float(sums[g])])
    return [(n / np.linalg.norm(n), a) for n, a in out]


@dataclass
class Candidate:
    rotation: object  # scipy Rotation, part frame -> print frame
    down: np.ndarray  # the side of the part (as modeled) that goes on the bed
    source: str  # "as modeled", "axis" or "hull face"
    rot: tuple = ()
    part: Part | None = None
    stats: dict = field(default_factory=dict)
    score: float = 0.0
    terms: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def candidates(part: Part, mesh_points: np.ndarray, limit: int = MAX_CANDIDATES) -> list[Candidate]:
    """As modeled first, the other five axis-aligned orientations, then the largest hull faces;
    the same side down only once, at most `limit`."""
    out: list[Candidate] = []

    def add(d, source):
        d = np.asarray(d, float)
        d = d / np.linalg.norm(d)
        if any(float(c.down @ d) > SAME_DIR for c in out) or len(out) >= limit:
            return
        r = _rotation_to_down(d)
        out.append(Candidate(r, d, source, rot_angles(r)))

    for k in ("-Z", "+Z", "-Y", "+Y", "-X", "+X"):
        add(_SIDES[k], "as modeled" if k == "-Z" else "axis")
    for n, _ in hull_faces(mesh_points):
        add(n, "hull face")
    return out


class _Turned:
    """The part's triangulation (metrics.Mesh) and its slicer (checks.MeshSlicer), made once and
    turned with each candidate: no new tessellation per orientation."""

    def __init__(self, part: Part):
        from .render import tessellate

        self.mesh = M.Mesh(part, tol=0.05)
        self.slicer = ck.MeshSlicer(part, tol=0.05)
        c = part.center(CenterOf.MASS)
        self.com = np.array([c.X, c.Y, c.Z])
        self.normals = []  # per face, its triangles' normals: which faces can face down in a turn
        for f in part.faces():
            v, t = tessellate(f, 0.05)
            n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]) if len(t) else np.zeros((0, 3))
            ln = np.linalg.norm(n, axis=1)
            self.normals.append(n[ln > 1e-12] / ln[ln > 1e-12, None])

    def steep(self, R: np.ndarray, max_overhang: float) -> list[int]:
        """The faces with a triangle facing down past max_overhang (less a degree) once turned by R:
        the only ones metrics.supports needs to look at."""
        lim = -math.sin(math.radians(max_overhang - 1))
        return [i for i, n in enumerate(self.normals) if len(n) and float((n @ R[2]).min()) < lim]

    def turn(self, rot: tuple) -> tuple[np.ndarray, np.ndarray, M.Mesh, ck.MeshSlicer]:
        """(the rotation matrix, the shift that puts the turned part centred on the bed, the turned
        mesh and slicer)."""
        import copy

        from scipy.spatial.transform import Rotation

        R = Rotation.from_euler("XYZ", rot, degrees=True).as_matrix()
        v = self.slicer.v @ R.T
        lo, hi = v.min(0), v.max(0)
        t = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        sl = copy.copy(self.slicer)
        sl.v = v + t
        m = copy.copy(self.mesh)
        m.tri = self.mesh.tri @ R.T + t
        m.n = self.mesh.n @ R.T
        m.c = m.tri.mean(1)
        return R, t, m, sl


def evaluate(c: Candidate, part: Part, p: M.Params, tip_speed: float, turned: _Turned) -> None:
    """Fill c.part (turned and on the bed) and c.stats from the existing measurements."""
    R, t, mesh, sl = turned.turn(c.rot)
    rp = Pos(*t) * (Rot(*c.rot) * part)
    c.part = rp
    faces = rp.faces()
    sup = M.supports(rp, mesh, p, faces=[faces[i] for i in turned.steep(R, p.max_overhang)], max_points=SUPPORT_POINTS,
                     bridge_min_area=BRIDGE_MIN_AREA)
    ms = M.mass(rp, mesh, p)
    height = float(sl.v[:, 2].max())
    time_ = M.print_time(rp, ms["extruded_mm3"] + sup.get("volume_mm3", 0), p)
    com = R @ turned.com + t
    fp = ck.footprint(sl.section("XY", p.layer / 2, 1e9), height, tip_speed or 200.0, (com[0], com[1]))
    c.stats = {"supports_mm2": sup["area"], "supports_g": sup["grams"], "support_mm3": sup.get("volume_mm3", 0),
               "bridges": sup.get("bridges", []), "long_bridges": [s for s in sup.get("bridges", []) if s > p.max_bridge],
               "contact_mm2": fp["area"], "height": round(height, 2), "minutes": time_["minutes"],
               "footprint": fp, "tip": ck.tip_risk(fp) if tip_speed else []}


def _score(cands: list[Candidate], area: float, load: np.ndarray | None, assumed: np.ndarray | None) -> None:
    t_min = min(c.stats["minutes"] for c in cands) or 1e-9
    best_contact = max(c.stats["contact_mm2"] for c in cands) or 1e-9
    for c in cands:
        s, fp = c.stats, c.stats["footprint"]
        tip = 0.0 if not s["tip"] and fp["height"] < ck.TIP_HEIGHT else min(fp["brim"] / ck.TIP_BRIM, 3.0)
        terms = {
            "time": W_TIME * (s["minutes"] / t_min - 1),
            "supports": W_SUPPORT * s["supports_mm2"] / area if area else 0.0,
            "contact": W_CONTACT * (1 - s["contact_mm2"] / best_contact),
            "tip": W_TIP * tip,
            "fall": W_FALL * (not fp["area"] or fp["com_inside"] is False),
            "strip": W_STRIP * (bool(fp["area"]) and fp["strip"] < ck.TIP_STRIP and fp["height"] >= ck.TIP_HEIGHT),
            "bridges": W_BRIDGE * len(s["long_bridges"]),
        }
        notes = []
        for vec, w, what in ((load, W_LOAD, "load"), (assumed, W_LOAD_ASSUMED, "long axis (assumed load)")):
            if vec is None:
                continue
            z = abs(float(c.rotation.apply(vec)[2]))
            terms["load"] = w * z
            deg = math.degrees(math.asin(min(1.0, z)))
            notes.append(f"{what} {deg:.0f} deg out of the layers" if deg > 1 else f"{what} along the layers")
        c.terms = {k: round(float(v), 3) for k, v in terms.items()}
        c.score = round(float(sum(terms.values())), 3)
        if s["supports_mm2"] >= 1:
            notes.append(f"supports under {s['supports_mm2']:g} mm^2")
        if s["long_bridges"]:
            notes.append(f"{len(s['long_bridges'])} bridge(s) over max_bridge, longest {max(s['long_bridges']):g} mm")
        elif s["bridges"]:
            notes.append(f"{len(s['bridges'])} bridge(s), longest {max(s['bridges']):g} mm")
        if s["tip"]:
            notes.append(f"tip-over ({'; '.join(s['tip'])})")
        if c.source == "as modeled":
            notes.append("as modeled now")
        c.notes = notes


def _long_axis(part: Part) -> np.ndarray:
    """The part's longest principal axis of inertia (for the structural style without a load)."""
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp

    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(part.wrapped, g)
    m = g.MatrixOfInertia()
    t = np.array([[m.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])
    w, v = np.linalg.eigh(t)
    return v[:, int(np.argmin(w))]  # least inertia about it: the long axis


def suggest(part: Part, settings, load=None, style: str = "functional", up: str = "+Z",
            limit: int = MAX_CANDIDATES) -> tuple[dict, Part | None]:
    """Rank the candidate orientations of one printable part (as build(d) returns it): (the
    JSON-able ranking, the top choice turned and on the bed)."""
    p = M.Params.from_settings(settings)
    vec = parse_load(load)
    assumed = _long_axis(part) if vec is None and style == "structural" else None
    turned = _Turned(part)
    mesh = turned.mesh
    cands = candidates(part, mesh.tri.reshape(-1, 3), limit)
    for c in cands:
        evaluate(c, part, p, settings.tip_speed, turned)
    _score(cands, float(mesh.area.sum()), vec, assumed)
    cands.sort(key=lambda c: (c.score, c.stats["height"]))
    upd = np.array(_SIDES.get(up, (0, 0, 1)), float)
    rows = []
    for i, c in enumerate(cands, 1):
        s = c.stats
        rows.append({"rank": i, "rot": list(c.rot), "down": _side_name(c.down), "source": c.source, "score": c.score,
                     "terms": c.terms, "supports_mm2": s["supports_mm2"], "supports_g": s["supports_g"],
                     "contact_mm2": s["contact_mm2"], "height": s["height"], "minutes": s["minutes"],
                     "brim_estimate_mm": s["footprint"]["brim"], "notes": c.notes,
                     "up_becomes": _side_name(c.rotation.apply(upd))})
    return {"candidates": rows, "load": None if vec is None else [round(float(x), 3) for x in vec],
            "assumed_load": None if assumed is None else [round(float(x), 3) for x in assumed], "style": style,
            "up": up}, (cands[0].part if cands else None)


def _fmt_rot(rot) -> str:
    return "Rot(" + ", ".join(f"{x:g}" for x in rot) + ")"


def text(name: str, res: dict, show: int = 6) -> str:
    """The ranked table and how to apply the top choice."""
    rows = res["candidates"]
    head = f"{name}: {len(rows)} orientations ranked (lower score is better; rough estimates)"
    if res["load"]:
        head += f"; load along ({', '.join(f'{x:g}' for x in res['load'])})"
    elif res["assumed_load"]:
        head += "; structural style, no load given: bending along the long axis assumed (pass load= to say)"
    lines = [head, f"{'#':>2}  {'rotation':<20} {'on the bed':<18} {'supports':>13} {'contact':>8} {'height':>7} "
                   f"{'time':>6} {'score':>6}  notes",
             f"{'':>2}  {'':<20} {'':<18} {'mm2 / g':>13} {'mm2':>8} {'mm':>7} {'min':>6}"]
    for r in rows[:show]:
        sup = f"{r['supports_mm2']:.0f} / {r['supports_g']:g}"
        lines.append(f"{r['rank']:>2}  {_fmt_rot(r['rot']):<20} {r['down'] + ' side':<18} {sup:>13} {r['contact_mm2']:>8.0f} "
                     f"{r['height']:>7.1f} {r['minutes']:>6.1f} {r['score']:>6.2f}  {'; '.join(r['notes'])}")
    if len(rows) > show:
        lines.append(f"    (+{len(rows) - show} more)")
    best = rows[0]
    if best["rot"] == [0.0, 0.0, 0.0]:
        lines.append("\nThe part is already in the best orientation: nothing to change.")
    else:
        lines += [
            f"\nTo print it this way, turn it in build(d) and put it back on the bed (print orientation, bed at Z=0):",
            f"    p = {_fmt_rot(best['rot'])} * p",
            "    p = Pos(0, 0, -p.bounding_box().min.Z) * p",
            f"UP and SHOW are in print orientation: UP {res['up']} becomes {best['up_becomes']}, and turn the SHOW sides "
            "the same way. Re-check every frame=\"print\" Wall and Probe coordinate (frame=\"assembly\" ones stay), "
            "then build_part and check.",
        ]
    return "\n".join(lines)


def for_script(mod, d, parts: dict, settings, piece: str | None = None, load=None) -> tuple[dict, dict]:
    """suggest() for each printable part of a script variant (`parts`, as project.printables gives
    them; or only `piece`), with the script's style and UP: ({name: ranking}, {name: the top choice
    on the bed})."""
    named = {(k or "part"): v for k, v in parts.items()}
    if piece:
        if piece not in named:
            raise KeyError(f"no part {piece!r}; parts: {sorted(named)}")
        named = {piece: named[piece]}
    style, _ = M.resolve_style(mod, d, settings)
    up = M.parse_dirs(M.script_attr(mod, d, "UP", "+Z"))[0]
    out, best = {}, {}
    for n, part in named.items():
        out[n], best[n] = suggest(part, settings, load, style, up)
    return out, best
