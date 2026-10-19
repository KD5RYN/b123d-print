"""Edge listing and selection by id, for fillets and chamfers (like list_faces for templates).

list_edges(part) lists every edge with a stable id (the same geometry always gets the same ids),
its type, length, end points or center, whether it is convex (an outside edge), concave (an inside
corner), tangent (a smooth joint, e.g. the side of a fillet) or a seam, and the two faces it joins
(flat faces by their list_faces id, curved ones by type). Filters narrow the list: by face, type,
convexity, or near a point.

Ids change when the model changes, so a script never selects by id. selector(part, ids) turns
chosen ids into a build123d selector expression (filter_by / group_by / sort_by on part.edges(),
or on the edges of one face) that selects exactly those edges, verified by evaluating it on the
part; when no such chain exists it falls back to a selection by position, and says so.

    res = list_edges(part, convexity="convex", face="top")
    sel = selector(part, [3, 4, 7, 8])   # {"expr": "part.edges().filter_by(GeomType.LINE)...", ...}
    part = fillet(eval(sel["expr"]), radius=1)   # in the script: paste the expression itself
"""

from __future__ import annotations

import math
import time

import numpy as np
from build123d import Axis, Edge, GeomType, Part, ShapeList, SortBy, Vector

from . import checks as ck
from . import metrics as mx
from . import templates as tp

KINDS = ("line", "circle", "arc", "ellipse", "spline")  # the kind filter: "circle" takes arcs too
CONVEXITY = ("convex", "concave", "tangent", "seam", "open")
TANGENT_DEG = 5.0  # faces meeting at less than this turn are a smooth (tangent) joint, as in metrics M7/M12
LIMIT = 200  # edges listed at most (the counts cover all of them)
SEARCH_S = 30.0  # s: the selector search gives up after this (then it selects by position)


class EdgeError(tp.TemplateError):
    pass


def _r(v: float, n: int = 3) -> float:
    return round(float(v), n) + 0.0


def _pt(v) -> list[float]:
    return [_r(x) for x in (v.X, v.Y, v.Z)]


def _bb_center(e: Edge) -> np.ndarray:
    bb = e.bounding_box()
    return np.array([(bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2])


def ordered(part: Part) -> list[Edge]:
    """The edges in id order: longest first, then by the center of their box (bottom first, then
    front, left) and type, rounded so the same geometry rebuilt gets the same order."""
    def key(e):
        c = np.round(_bb_center(e), 2) + 0.0
        return (-round(e.length, 2), *c[[2, 1, 0]], e.geom_type.name)

    return sorted(part.edges(), key=key)


def _face_names(part: Part) -> dict[int, object]:
    """hash(face) -> its list_faces id (flat faces) or its type, e.g. "cylinder r2.5" (curved)."""
    out: dict[int, object] = {hash(f): i for i, f in enumerate(tp._planar(part), 1)}
    for f in part.faces():
        if hash(f) not in out:
            r = mx._blend_radius(f)
            out[hash(f)] = f.geom_type.name.lower() + (f" r{_r(r, 2):g}" if r else "")
    return out


def _convexity(e: Edge, faces: list, inside) -> tuple[str, float | None]:
    """(convex | concave | tangent | seam | open, the turn between the two faces' normals in deg)."""
    if len(faces) == 1 or (len(faces) == 2 and faces[0].wrapped.IsSame(faces[1].wrapped)):
        return "seam", None  # one face meets itself (the seam line of a cylinder)
    if len(faces) != 2:
        return "open", None
    pm = e.position_at(0.5)
    try:
        n1, n2 = mx._vec3(faces[0].normal_at(pm)), mx._vec3(faces[1].normal_at(pm))
    except Exception:  # noqa: BLE001 - a degenerate face
        return "open", None
    turn = math.degrees(math.acos(max(-1.0, min(1.0, float(n1 @ n2)))))
    if turn < TANGENT_DEG:
        return "tangent", turn
    # M7's probe: n1 - n2 leaves the solid at a convex edge and stays in it at a concave one
    return ("convex" if mx._probe_convex(inside, mx._vec3(pm), n1, n2) else "concave"), turn


def _kind(e: Edge) -> str:
    g = e.geom_type.name
    if g == "CIRCLE":
        return "circle" if e.is_closed else "arc"
    if g in ("LINE", "ELLIPSE"):
        return g.lower()
    return "spline" if g in ("BSPLINE", "BEZIER") else g.lower()


def describe(part: Part) -> list[dict]:
    """Every edge of `part` as a dict, in id order (see the module docstring)."""
    ef = ck._edge_faces(part)
    names = _face_names(part)
    inside = mx._Inside(part)
    out = []
    for i, e in enumerate(ordered(part), 1):
        fl = ef.get(hash(e), [])
        conv, turn = _convexity(e, fl, inside)
        row = {"id": i, "type": _kind(e), "length": _r(e.length), "convexity": conv}
        if turn is not None:
            row["turn"] = _r(turn, 1)
        if e.geom_type.name == "CIRCLE":
            row.update(radius=_r(e.radius), center=_pt(e.arc_center))
        if not e.is_closed:
            row.update(start=_pt(e.position_at(0)), end=_pt(e.position_at(1)))
        else:
            row["mid"] = _pt(e.position_at(0.5))
        uniq = []
        for f in fl:
            if not any(f.wrapped.IsSame(g.wrapped) for g in uniq):
                uniq.append(f)
        fs = [names.get(hash(f), f.geom_type.name.lower()) for f in uniq]
        row["faces"] = sorted(fs, key=lambda f: (isinstance(f, str), f if isinstance(f, str) else f"{f:09d}"))
        out.append(row)
    return out


def list_edges(part: Part, face=None, kind: str | None = None, convexity: str | None = None, near=None,
               radius: float = 1.0, limit: int = LIMIT) -> dict:
    """The part's edges with stable ids (1 = the longest), each with its type, length, end points
    (or center and radius), convexity and the two faces it joins. Filters: face (an id, side or
    point, as list_faces), kind (line, circle (with arcs), arc, ellipse, spline), convexity (convex, concave,
    tangent, seam), near (x, y, z: edges within `radius` mm, nearest first). The ids are the same
    with or without filters; `limit` caps the list, `total` and `counts` cover the whole part."""
    rows = describe(part)
    edges = ordered(part)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["convexity"]] = counts.get(r["convexity"], 0) + 1
    keep = list(range(len(rows)))
    if face is not None:
        f, fid = tp.find_face(part, face)
        hs = {hash(e) for e in f.edges()}
        keep = [i for i in keep if hash(edges[i]) in hs]
    if kind:
        k = kind.strip().lower()
        if k not in KINDS:
            raise EdgeError(f"edge type {kind!r}: one of {', '.join(KINDS)}")
        want = {"circle", "arc"} if k == "circle" else {k}
        keep = [i for i in keep if rows[i]["type"] in want]
    if convexity:
        c = convexity.strip().lower()
        if c not in CONVEXITY:
            raise EdgeError(f"convexity {convexity!r}: one of {', '.join(CONVEXITY)}")
        keep = [i for i in keep if rows[i]["convexity"] == c]
    if near is not None:
        p = Vector(*np.array(near, float).reshape(3))
        dist = {i: edges[i].distance_to(p) for i in keep}
        keep = sorted((i for i in keep if dist[i] <= radius), key=lambda i: (dist[i], i))
        for i in keep:
            rows[i] = {**rows[i], "distance": _r(dist[i])}
    shown = [rows[i] for i in keep[:limit]]
    res = {"edges": shown, "matched": len(keep), "total": len(rows), "counts": counts}
    if face is not None:
        res["face"] = fid
    if len(keep) > limit:
        res["note"] = f"{len(keep) - limit} more not listed: narrow with face, kind, convexity or near"
    return res


def parse_ids(ids, n: int) -> list[int]:
    """Edge ids from an int, a list or a string "3,4,7" (or "3-6"), checked against 1..n."""
    if isinstance(ids, (int, np.integer)) and not isinstance(ids, bool):
        vals = [int(ids)]
    elif isinstance(ids, str):
        vals = []
        for part in ids.replace(";", ",").split(","):
            a, sep, b = part.strip().partition("-")
            if not a.strip().isdigit() or (sep and not b.strip().isdigit()):
                raise EdgeError(f"edge ids {ids!r}: numbers from list_edges, e.g. 3,4,7 or 3-6")
            vals += list(range(int(a), int(b) + 1)) if sep else [int(a)]
    else:
        vals = [int(v) for v in ids]
    if not vals:
        raise EdgeError("no edge ids given")
    bad = [v for v in vals if not 1 <= v <= n]
    if bad:
        raise EdgeError(f"no edge {bad[0]}: ids are 1 to {n} (list_edges)")
    return sorted(set(vals))


def find_edges(part: Part, ids) -> tuple[list[Edge], list[int]]:
    edges = ordered(part)
    got = parse_ids(ids, len(edges))
    return [edges[i - 1] for i in got], got


# ---------------------------------------------------------------------------------------------
# selectors


AXES = {"X": Axis.X, "Y": Axis.Y, "Z": Axis.Z}
GEOM = ("LINE", "CIRCLE", "ELLIPSE", "BSPLINE", "BEZIER")


def _ops(sel: ShapeList, target: set[int], middle: bool):
    """The next steps from a selection: (text, the selection after it) for each filter, and the
    group or end of a sort that still holds all the target edges (only the first or last group
    unless `middle`: a middle group's index changes when edges are added along that axis)."""
    types = {e.geom_type.name for e in sel}
    if len(types) > 1:
        for g in GEOM:
            if g in types:
                yield f".filter_by(GeomType.{g})", sel.filter_by(getattr(GeomType, g))
    for a, ax in AXES.items():
        yield f".filter_by(Axis.{a})", sel.filter_by(ax)
    for a, ax in [*AXES.items(), ("SortBy.LENGTH", SortBy.LENGTH), ("SortBy.RADIUS", SortBy.RADIUS)]:
        name = f"Axis.{a}" if a in AXES else a
        if a == "SortBy.RADIUS" and types != {"CIRCLE"}:
            continue
        try:
            groups = sel.group_by(ax)
        except Exception:  # noqa: BLE001 - e.g. no radius on this kind of edge
            continue
        if len(groups) < 2:
            continue
        for i, g in enumerate(groups):
            hs = {hash(e) for e in g}
            if target <= hs:
                idx = i if i <= len(groups) - 1 - i else i - len(groups)
                if idx not in (0, -1) and not middle:
                    break
                yield f".group_by({name})[{idx}]", ShapeList(g)
                break
    if len(target) == 1 and len(sel) > 1:
        for a, ax in AXES.items():
            s = sel.sort_by(ax)
            for idx in (0, -1):
                if hash(s[idx]) in target:
                    yield f".sort_by(Axis.{a})[{idx}]", ShapeList([s[idx]])


def _by_convexity(part: Part, which: str) -> ShapeList:
    ef = ck._edge_faces(part)
    inside = mx._Inside(part)
    return ShapeList(e for e in part.edges() if _convexity(e, ef.get(hash(e), []), inside)[0] == which)


def convex_edges(part: Part) -> ShapeList:
    """The part's convex (outside) edges, for a selector: convex_edges(part).group_by(Axis.Z)[-1]."""
    return _by_convexity(part, "convex")


def concave_edges(part: Part) -> ShapeList:
    """The part's concave edges (inside corners), for a selector: concave_edges(part).filter_by(Axis.Y)."""
    return _by_convexity(part, "concave")


def _starts(part: Part):
    """Where a selection begins: all the part's edges, the edges of its outermost face on a side,
    or its convex or concave edges (b123d_print.edges.convex_edges / concave_edges)."""
    yield "part.edges()", part.edges()
    for a, ax in AXES.items():
        faces = part.faces().sort_by(ax)
        for idx in (0, -1):
            yield f"part.faces().sort_by(Axis.{a})[{idx}].edges()", faces[idx].edges()
    yield "concave_edges(part)", concave_edges(part)
    yield "convex_edges(part)", convex_edges(part)


def _search(starts: list, target: set[int], depth: int = 3, middle: bool = False, until: float = math.inf) -> str | None:
    """The shortest chain of steps (fewest, then shortest text) from a start that selects exactly
    `target`; breadth first, keeping only selections that still hold every target edge."""
    level = []
    seen: set[frozenset] = set()
    for text, sel in starts:
        hs = frozenset(hash(e) for e in sel)
        if target <= hs and hs not in seen:
            seen.add(hs)
            level.append((text, sel))
    for _ in range(depth + 1):
        done = sorted((t for t, s in level if {hash(e) for e in s} == target and len(s) == len(target)), key=len)
        if done:
            return done[0]
        nxt = []
        for text, sel in level:
            if time.monotonic() > until:
                return None
            for step, s in _ops(sel, target, middle):
                hs = frozenset(hash(e) for e in s)
                if target <= hs and hs not in seen:
                    seen.add(hs)
                    nxt.append((text + step, s))
        level = nxt
    return None


def _union(starts: list, chosen: list[Edge], most: int = 4, middle: bool = False, until: float = math.inf) -> str | None:
    """Several chains joined with +, when no one chain selects the edges: one per edge type, or
    one per edge for up to `most` edges."""
    by_type: dict[str, list[Edge]] = {}
    for e in chosen:
        by_type.setdefault(e.geom_type.name, []).append(e)
    for groups in ([v for v in by_type.values()], [[e] for e in chosen] if len(chosen) <= most else []):
        if len(groups) < 2:
            continue
        exprs = [_search(starts, {hash(e) for e in g}, middle=middle, until=until) for g in groups]
        if all(exprs):
            return " + ".join(f"({x})" if " + " in x else x for x in exprs)
    return None


def evaluate(expr: str, part: Part) -> ShapeList:
    """Evaluate a selector expression on `part` (the name `part` in it), with build123d's names."""
    import build123d

    env = {k: getattr(build123d, k) for k in dir(build123d) if not k.startswith("_")}
    env.update(part=part, convex_edges=convex_edges, concave_edges=concave_edges)
    res = eval(expr, env)  # noqa: S307 - our own generated expression, on the caller's part
    return ShapeList(res) if not isinstance(res, ShapeList) else res


def _by_position(edges: list[Edge]) -> str:
    pts = ", ".join(f"({', '.join(f'{x:g}' for x in _pt(e.position_at(0.5)))})" for e in edges)
    return f"part.edges().filter_by(lambda e: min((e @ 0.5 - Vector(*p)).length for p in [{pts}]) < 0.01)"


def selector(part: Part, ids) -> dict:
    """A build123d expression that selects exactly the edges `ids` (from list_edges) of `part`:
    {"expr", "ids", "edges", "verified", "stable", "note"} and "import" when the expression uses
    convex_edges / concave_edges. A chain of filter_by / group_by /
    sort_by is stable (it follows the shape when dimensions change); the fallback selects by the
    edges' midpoints and breaks when they move."""
    chosen, got = find_edges(part, ids)
    target = {hash(e) for e in chosen}
    starts = list(_starts(part))
    until = time.monotonic() + SEARCH_S
    expr = _search(starts, target, until=until) or _union(starts, chosen, until=until)
    stable = expr is not None
    middle = None
    if expr is None:
        middle = _search(starts, target, middle=True, until=until) or _union(starts, chosen, middle=True, until=until)
    expr = expr or middle or _by_position(chosen)
    sel = evaluate(expr, part)
    verified = {hash(e) for e in sel} == target and len(sel) == len(target)
    if stable:
        note = ("re-evaluated on the part: it selects exactly these edges. Paste it where the fillet or chamfer "
                "goes, with `part` the shape at that point (it was found on the finished part; at an earlier step, "
                "check len(...) of it there)")
    elif middle:
        note = ("re-evaluated on the part: it selects exactly these edges, but through a middle group (an index "
                "other than [0] or [-1]), which changes when edges are added or removed along that axis: check "
                "len(...) of it after changing the model, or fillet in several calls with simpler selections")
    else:
        note = ("no filter_by/group_by/sort_by chain selects exactly these edges: this one selects them by their "
                "midpoints, which move when dimensions change. Write the points from Dims, or fillet in several "
                "calls with one simpler selection each")
    imports = sorted(n for n in ("concave_edges", "convex_edges") if f"{n}(" in expr)
    res = {"expr": expr, "ids": got, "edges": len(chosen), "verified": verified, "stable": stable, "note": note}
    if imports:
        res["import"] = f"from b123d_print.edges import {', '.join(imports)}"
    return res


# ---------------------------------------------------------------------------------------------
# picture


def _tube(e: Edge, r: float):
    """A thin solid along an edge (cylinders between points on it), to draw it in a render."""
    from build123d import Compound, Solid

    n = 1 if e.geom_type.name == "LINE" else max(8, min(48, int(e.length / (4 * r)) + 1))
    pts = [mx._vec3(e.position_at(t)) for t in np.linspace(0, 1, n + 1)]
    parts = []
    for a, b in zip(pts, pts[1:]):
        d = b - a
        L = float(np.linalg.norm(d))
        if L > 1e-9:
            parts.append(Solid.make_cylinder(r, L, plane=_plane(a, d / L)))
    return Compound(parts)


def _plane(o: np.ndarray, z: np.ndarray):
    from build123d import Plane

    return Plane(origin=Vector(*o), z_dir=Vector(*z))


def highlight(part: Part, edges: list[Edge], path, title: str, size: str = "normal"):
    """The part, see-through grey, with `edges` drawn as red tubes."""
    from .render import render

    bb = part.bounding_box()
    r = max(0.1, 0.006 * max(bb.size.X, bb.size.Y, bb.size.Z))
    from build123d import Compound

    tubes = Compound([t for e in edges for t in _tube(e, r).solids()])
    items = [(part, "#9aa0a640", "part"), (tubes, "#e03030", "edges" if len(edges) > 1 else "edge")]
    return render(items, path, title, size=size)


def text(res: dict) -> list[str]:
    """list_edges as lines, for the command line."""
    out = []
    for e in res["edges"]:
        where = (f"center {tuple(e['center'])} r {e['radius']:g}" if "center" in e else "") \
            + (f"  {tuple(e['start'])} -> {tuple(e['end'])}" if "start" in e else "")
        out.append(f"  {e['id']:4}  {e['type']:7} {e['convexity']:8} length {e['length']:g}  {where.strip()}  "
                   f"faces {', '.join(str(f) for f in e['faces'])}"
                   + (f"  ({e['distance']:g} mm away)" if "distance" in e else ""))
    return out


def id_text(ids: list[int]) -> str:
    """[3, 4, 5, 9] -> "3-5, 9"."""
    out, i = [], 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(f"{ids[i]}-{ids[j]}" if j > i + 1 else ", ".join(map(str, ids[i:j + 1])))
        i = j + 1
    return ", ".join(out)
