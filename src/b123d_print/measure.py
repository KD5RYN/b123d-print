"""Precise measurements on a built part, for checking fits instead of guessing them from pictures.

- distance(a, b): the smallest gap between two shapes and the two points where it is; when they
  overlap, the interference instead (its volume, box and center).
- wall(part, at, direction): the material along a line through `at` (default: into the part,
  along the normal of the nearest face): the wall the point is on, and the walls and gaps beyond.
- faces(part, id1, id2): two flat faces (ids from list_faces): the distance between their planes
  when parallel (a wall's thickness, a slot's width), else the angle; and their closest points.
- hole(part, face, at): the round holes in a flat face (or the hole nearest a point): modeled
  diameter, center, axis, depth or through, and what it prints at after hole compensation.

Every number is in mm, rounded to 0.001 mm; points are [x, y, z] in the frame named in the
result: "print" (the part as build() returns it) or "assembly" (as assembly(d) places it).
`run` resolves names to shapes from a project.Pieces and draws the optional highlight picture.
"""

from __future__ import annotations

import math

import numpy as np

from build123d import Compound, Face, Part, Shape, Vector

KINDS = ("distance", "wall", "faces", "hole")
TOUCH = 1e-4  # mm: closer than this is touching
OVERLAP_VOLUME = 1e-6  # mm^3: a common volume above this is interference


class MeasureError(ValueError):
    pass


def _p(v) -> list[float]:
    v = v if isinstance(v, (list, tuple, np.ndarray)) else (v.X, v.Y, v.Z)
    return [round(float(x), 3) + 0.0 for x in v]


def _r(v: float, nd: int = 3) -> float:
    return round(float(v), nd) + 0.0


def _vec(v) -> np.ndarray:
    return np.array([v.X, v.Y, v.Z], dtype=float) if hasattr(v, "X") else np.array(v, dtype=float).reshape(3)


def _bbox(s) -> dict:
    bb = s.bounding_box()
    return {"min": _p(bb.min), "max": _p(bb.max), "size": _p(bb.size)}


def _boxes_touch(a, b, tol: float = 1e-6) -> bool:
    ba, bb = a.bounding_box(), b.bounding_box()
    return all(lo1 <= hi2 + tol and lo2 <= hi1 + tol for lo1, hi1, lo2, hi2 in
               zip(_vec(ba.min), _vec(ba.max), _vec(bb.min), _vec(bb.max)))


def distance(a: Shape, b: Shape) -> dict:
    """The smallest gap between `a` and `b` with the closest points, or their interference."""
    if _boxes_touch(a, b):
        common = a & b
        vol = float(common.volume) if common is not None else 0.0
        if vol > OVERLAP_VOLUME:
            box = _bbox(common)
            return {"overlap": True, "distance": 0.0, "interference_volume": _r(vol, 4), "interference_box": box,
                    "interference_center": _p(common.center()), "depth": _r(min(box["size"])),
                    "_shape": common}
    d, pa, pb = a.distance_to_with_closest_points(b)
    return {"overlap": False, "distance": _r(d, 4), "touching": d < TOUCH, "points": [_p(pa), _p(pb)]}


def _line_hits(shape: Shape, origin: np.ndarray, direction: np.ndarray) -> list[float]:
    """Parameters t (mm along the unit `direction`) where the line through `origin` crosses the
    shape's faces, sorted and without near duplicates."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape.wrapped, 1e-7)
    inter.Perform(gp_Lin(gp_Pnt(*origin), gp_Dir(*direction)), -1e7, 1e7)
    ts = sorted(inter.WParameter(i) for i in range(1, inter.NbPnt() + 1))
    out: list[float] = []
    for t in ts:
        if not out or t - out[-1] > 1e-6:
            out.append(t)
    return out


def _inside(shape: Shape, p: np.ndarray) -> bool:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    for s in shape.solids():
        if BRepClass3d_SolidClassifier(s.wrapped, gp_Pnt(*p), 1e-7).State() == TopAbs_IN:
            return True
    return False


def segments(shape: Shape, origin, direction) -> list[tuple[float, float, bool]]:
    """The line through `origin` along `direction` cut at the shape's faces: (t0, t1, solid) for
    each piece between two crossings, t in mm from `origin`."""
    o, d = _vec(origin), _vec(direction)
    d = d / np.linalg.norm(d)
    ts = _line_hits(shape, o, d)
    return [(t0, t1, _inside(shape, o + d * (t0 + t1) / 2)) for t0, t1 in zip(ts, ts[1:])]


def _nearest_face(shape: Shape, p: np.ndarray):
    """(distance, face, closest point on it) for the face of `shape` nearest the point `p`."""
    from build123d import Vertex

    v = Vertex(*p)
    best = None
    for f in shape.faces():
        try:
            dist, q, _ = f.distance_to_with_closest_points(v)
        except Exception:  # noqa: BLE001 - a degenerate face: skip it
            continue
        if best is None or dist < best[0]:
            best = (dist, f, _vec(q))
    if best is None:
        raise MeasureError("the part has no faces")
    return best


def wall(shape: Shape, at, direction=None) -> dict:
    """The material along a line through `at`. With a direction: the line along it (both ways
    when `at` is inside the material). Without one: from the nearest surface point into the part,
    along that face's normal: the thickness of the wall `at` is on."""
    p = _vec(at)
    inside = _inside(shape, p)
    if direction is None:
        dist, face, q = _nearest_face(shape, p)
        try:
            n = _vec(face.normal_at(Vector(*q)))
        except Exception:  # noqa: BLE001 - a degenerate point: the face's own normal
            n = _vec(face.normal_at(face.center()))
        n = n / np.linalg.norm(n)
        d = -n if _inside(shape, q - n * 1e-3) else n  # into the material
        origin, how = q, "into the part along the normal of the nearest face"
    else:
        d = _vec(direction)
        if not np.linalg.norm(d):
            raise MeasureError("direction must not be zero")
        d = d / np.linalg.norm(d)
        origin, how, dist = p, "along the given direction", None
    segs = segments(shape, origin, d)
    if inside or direction is None:
        here = next((s for s in segs if s[2] and s[0] - 1e-4 <= 0.0 <= s[1] + 1e-4), None)
        if here is None and direction is None:
            here = next((s for s in segs if s[2] and s[1] > 1e-4), None)
    else:
        here = next((s for s in segs if s[2] and s[1] > 0), None)
    if here is None:
        raise MeasureError(f"no material along the line from {_p(origin)} {how}")
    t0, t1, _ = here
    beyond = [{"kind": "material" if solid else "gap", "length": _r(b - a), "from": _p(origin + d * a),
               "to": _p(origin + d * b)} for a, b, solid in segs if a >= t1 - 1e-6][:6]
    out = {"thickness": _r(t1 - t0), "from": _p(origin + d * t0), "to": _p(origin + d * t1), "direction": _p(d),
           "how": how, "point_inside": inside}
    if dist is not None and not inside:
        out["point_to_surface"] = _r(dist)
    if beyond:
        out["beyond"] = beyond
    return out


def faces(shape: Shape, f1, f2) -> dict:
    """Two flat faces (ids or sides, see templates.find_face): distance between their planes when
    parallel, else the angle between them; the closest points of the faces themselves."""
    from .templates import find_face

    a, ia = find_face(shape, f1)
    b, ib = find_face(shape, f2)
    na, nb = _vec(a.normal_at(a.center())), _vec(b.normal_at(b.center()))
    ca, cb = _vec(a.center()), _vec(b.center())
    d, pa, pb = a.distance_to_with_closest_points(b)
    out: dict = {"faces": [ia, ib], "normals": [_p(na), _p(nb)], "centers": [_p(ca), _p(cb)],
                 "closest": _r(d, 4), "points": [_p(pa), _p(pb)]}
    dot = float(np.dot(na, nb))
    if abs(dot) > 0.9999:
        sep = float(np.dot(cb - ca, na))
        out["parallel"] = True
        out["distance"] = _r(abs(sep))
        if dot < 0:  # opposite normals: material between them (a wall) or space between them (a slot)
            out["between"] = "the part (they face away from each other)" if sep < 0 else "space (they face each other: a slot or gap)"
        else:
            out["between"] = "a step (both face the same way)"
    else:
        out["parallel"] = False
        out["angle"] = _r(math.degrees(math.acos(max(-1.0, min(1.0, dot)))), 2)
    out["_shapes"] = [a, b]
    return out


def _wire_info(w, n: np.ndarray) -> dict:
    edges = w.edges()
    if edges and all(e.geom_type.name == "CIRCLE" for e in edges):
        rs = {round(e.radius, 4) for e in edges}
        cs = {tuple(np.round(_vec(e.arc_center), 3)) for e in edges}
        if len(rs) == 1 and len(cs) == 1:
            return {"round": True, "d": _r(2 * rs.pop()), "center": _p(cs.pop())}
    bb = w.bounding_box()
    size = [s for s, ax in zip(_vec(bb.size), np.eye(3)) if abs(np.dot(ax, n)) < 0.99]
    return {"round": False, "size": [_r(s) for s in size], "center": _p(bb.center()),
            "note": "not round (a teardrop, slot or polygon): size is its box in the face's plane"}


def _depth(shape: Shape, center: np.ndarray, n: np.ndarray, d: float | None) -> dict:
    """From a hole's opening along -n (into the part): blind (the depth to its bottom) or through."""
    segs = segments(shape, center + n * 0.01, -n)
    ahead = [s for s in segs if s[1] > 0.011]
    first = next((s for s in ahead if s[2]), None)
    if first is None:
        cyl = _bore(shape, center, n, d)
        return {"through": True, **({"length": cyl} if cyl is not None else {})}
    return {"through": False, "depth": _r(max(0.0, first[0] - 0.01))}


def _bore(shape: Shape, center: np.ndarray, n: np.ndarray, d: float | None) -> float | None:
    """The length of the cylindrical wall(s) on the hole's axis (a through hole's length)."""
    if d is None:
        return None
    lo = hi = None
    for f in shape.faces():
        if f.geom_type.name != "CYLINDER":
            continue
        try:
            r = f.radius
            ax = f.axis_of_rotation if hasattr(f, "axis_of_rotation") else None
        except Exception:  # noqa: BLE001
            continue
        if abs(2 * r - d) > 1e-3:
            continue
        if ax is not None:
            dirv, pos = _vec(ax.direction), _vec(ax.position)
            if abs(abs(np.dot(dirv, n)) - 1) > 1e-6 or np.linalg.norm(np.cross(pos - center, n)) > 1e-3:
                continue
        for v in f.vertices():
            t = float(np.dot(_vec(v) - center, -n))
            lo, hi = (t if lo is None else min(lo, t)), (t if hi is None else max(hi, t))
    return _r(hi - lo) if lo is not None else None


def hole(shape: Shape, face=None, at=None, comp: float = 0.0, comp_h: float = 0.0) -> dict:
    """The holes in a flat face (an id or side from list_faces), the one nearest `at` if given;
    or, without a face, the round hole whose wall is nearest `at`."""
    from .templates import find_face

    if face is None and at is None:
        raise MeasureError("a hole needs face (an id from list_faces) or at (a point at the hole)")
    if face is not None:
        f, fid = find_face(shape, face)
        n = _vec(f.normal_at(f.center()))
        found = []
        for w in f.inner_wires():
            info = _wire_info(w, n)
            info.update(axis=_p(n))
            found.append(info)
        if not found:
            raise MeasureError(f"face {fid} has no holes (list_faces lists the holes of each face)")
        if at is not None:
            p = _vec(at)
            found.sort(key=lambda h: float(np.linalg.norm(_vec(h["center"]) - p)))
            found = found[:1]
        out_face, wires = fid, found
    else:
        p = _vec(at)
        cyl = [f for f in shape.faces() if f.geom_type.name == "CYLINDER"]
        if not cyl:
            raise MeasureError("the part has no cylindrical faces (no round holes)")
        best = min(cyl, key=lambda f: f.distance_to(Vector(*p)))
        ax = best.axis_of_rotation
        n = _vec(ax.direction)
        c = _vec(ax.position)
        ts = [float(np.dot(_vec(v) - c, n)) for v in best.vertices()] or [0.0]
        center = c + n * max(ts)
        side = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
        mid = c + n * (min(ts) + max(ts)) / 2 + side / np.linalg.norm(side) * (best.radius + 0.05)
        if not _inside(shape, mid):
            raise MeasureError(f"the round face nearest {_p(p)} (d {_r(2 * best.radius)}) is the outside of a boss or "
                               "pin, not a hole; measure it with wall or faces")
        out_face, wires = None, [{"round": True, "d": _r(2 * best.radius), "center": _p(center), "axis": _p(n)}]
    for h in wires:
        n = _vec(h["axis"])
        h.update(_depth(shape, _vec(h["center"]), n, h.get("d")))
        vertical = abs(n[2]) > 0.99
        c = comp if vertical else comp_h
        h["orientation"] = "vertical" if vertical else ("horizontal" if abs(n[2]) < 0.01 else "slanted")
        if h.get("round"):
            h["modeled_d"] = h.pop("d")
            h["prints_about"] = _r(h["modeled_d"] - c)
            h["hole_comp"] = c
    return {"face": out_face, "holes": wires}


# ---------------------------------------------------------------------------------------------
# names -> shapes, and the job the worker runs


def _resolve(pc, name: str | None, frame: str, two: bool):
    """(shape, label, frame) for a piece name or an assembly label."""
    names = {(n or "part"): n for n in pc.names()}
    if frame not in ("auto", "print", "assembly"):
        raise MeasureError("frame: 'auto', 'print' or 'assembly'")
    if name in (None, ""):
        if frame == "assembly":
            raise MeasureError("name the assembly part (its label)")
        if len(names) != 1:
            raise MeasureError(f"several pieces: name one of {sorted(names)}")
        only = next(iter(names))
        return pc.part(names[only]), only, "print"
    asm = pc.assembly() if frame == "assembly" or (frame == "auto" and (two or name not in names)) else None
    labels = {lbl: p for p, _, lbl in (asm or [])}
    if frame == "assembly" or (frame == "auto" and name in labels and (two or name not in names)):
        if name not in labels:
            raise MeasureError(f"no assembly part labeled {name!r}; labels: {sorted(labels) or 'none (no assembly(d))'}")
        return labels[name], name, "assembly"
    if name not in names:
        raise MeasureError(f"no piece {name!r}; pieces: {sorted(names)}"
                           + (f"; assembly labels: {sorted(labels)}" if labels else ""))
    return pc.part(names[name]), name, "print"


def _marker(points: list, scale: float) -> list:
    """Small spheres at `points` and a rod between the first two, for the highlight picture."""
    from build123d import Plane, Pos, Solid, Sphere

    r = max(0.2, 0.01 * scale)
    out = [Pos(*p) * Sphere(r) for p in points]
    if len(points) >= 2:
        a, b = _vec(points[0]), _vec(points[1])
        length = float(np.linalg.norm(b - a))
        if length > 1e-6:
            out.append(Solid.make_cylinder(r / 2.5, length, Plane(origin=tuple(a), z_dir=tuple((b - a) / length))))
    return out


def run(pc, query: dict, settings, out_dir=None, tag: str = "part", size: str = "normal") -> dict:
    """One measurement from a query {"kind", "a", "b", "at", "direction", "face", "face2",
    "frame", "image"} on the pieces `pc` (project.Pieces). The result's "summary" says it in one
    line; "image" is the highlight picture's path when asked for."""
    kind = (query.get("kind") or "").lower()
    if kind not in KINDS:
        raise MeasureError(f"kind: one of {', '.join(KINDS)}")
    frame = (query.get("frame") or "auto").lower()
    hl: list = []
    if kind == "distance":
        if not query.get("b"):
            raise MeasureError("distance needs a and b: two piece names or assembly labels")
        sa, la, fa = _resolve(pc, query.get("a"), frame, True)
        sb, lb, fb = _resolve(pc, query.get("b"), frame if frame != "auto" else fa, True)
        if fa != fb:
            raise MeasureError(f"{la} is in the {fa} frame and {lb} in the {fb} frame: pass frame='print' or 'assembly'")
        res = distance(sa, sb)
        base = Part(Compound([sa, sb]).wrapped) if hasattr(sa, "wrapped") else sa
        if res["overlap"]:
            res["summary"] = (f"{la} and {lb} overlap: interference {res['interference_volume']:g} mm^3 in a "
                              f"{' x '.join(f'{v:g}' for v in res['interference_box']['size'])} mm box at "
                              f"{res['interference_center']} (depth {res['depth']:g} mm, its smallest side)")
            hl = [res.pop("_shape")]
        else:
            res["summary"] = (f"{'touching' if res['touching'] else 'gap'} {la} / {lb}: {res['distance']:g} mm, "
                              f"from {res['points'][0]} on {la} to {res['points'][1]} on {lb}")
            hl = _marker(res["points"], max(_bbox(base)["size"]))
        res.update(a=la, b=lb, frame=fa)
    else:
        shape, label, fr = _resolve(pc, query.get("a"), frame, False)
        base = shape
        if kind == "wall":
            if query.get("at") is None:
                raise MeasureError("wall needs at: a point x,y,z on or in the wall")
            res = wall(shape, query["at"], query.get("direction"))
            res["summary"] = (f"wall of {label}: {res['thickness']:g} mm from {res['from']} to {res['to']} "
                              f"({res['how']})")
            hl = _marker([res["from"], res["to"]], max(_bbox(shape)["size"]))
        elif kind == "faces":
            if query.get("face") is None or query.get("face2") is None:
                raise MeasureError("faces needs face and face2: two ids (or sides) from list_faces")
            res = faces(shape, query["face"], query["face2"])
            hl = res.pop("_shapes")
            if res["parallel"]:
                res["summary"] = (f"faces {res['faces'][0]} and {res['faces'][1]} of {label} are parallel, "
                                  f"{res['distance']:g} mm apart ({res['between']})")
            else:
                res["summary"] = (f"faces {res['faces'][0]} and {res['faces'][1]} of {label}: {res['angle']:g} deg "
                                  f"between their normals, {res['closest']:g} mm apart at the closest")
        else:
            res = hole(shape, query.get("face"), query.get("at"), getattr(settings, "hole_comp", 0.0) or 0.0,
                       getattr(settings, "hole_comp_h", 0.0) or 0.0)
            bits = []
            for h in res["holes"]:
                size = (f"d {h['modeled_d']:g} mm (prints about {h['prints_about']:g} with hole_comp {h['hole_comp']:g})"
                        if h.get("round") else f"{' x '.join(f'{v:g}' for v in h['size'])} mm, not round")
                depth = (f"through ({h['length']:g} mm)" if h.get("through") and h.get("length") is not None
                         else "through" if h.get("through") else f"blind, {h['depth']:g} mm deep")
                bits.append(f"{size} at {h['center']}, {h['orientation']}, {depth}")
            res["summary"] = f"hole(s) of {label}" + (f" in face {res['face']}" if res["face"] else "") + ": " + "; ".join(bits)
            hl = [f for f in shape.faces() if f.geom_type.name == "CYLINDER"
                  and any(h.get("round") and abs(2 * f.radius - h["modeled_d"]) < 1e-3
                          and f.distance_to(Vector(*h["center"])) < h["modeled_d"] for h in res["holes"])]
        res.update(a=label, frame=fr)
    res["kind"] = kind
    if query.get("image") and out_dir is not None:
        from pathlib import Path

        from . import outdir
        from .templates import highlight

        small = "_small" if size == "small" else ""
        name = f"{tag}_measure_{kind}{small}.png"
        res["image"] = str(highlight(base, [s for s in hl if isinstance(s, (Shape, Face))], outdir.path(out_dir, name),
                                     f"{tag}: {res['summary'][:90]}", size=size))
    return res
