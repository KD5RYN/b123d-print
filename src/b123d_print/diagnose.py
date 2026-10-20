"""Build failures turned into a likely cause and concrete fixes.

A failed build_part / render_preview / section / check / export result carries a `diagnosis`:
what went wrong in words, where in the script (file, line, function, the code, and the piece of
build() that was being built), the evidence (the fillet radius and how wide the faces next to
the edges are, the offset distance against the size of the outline, the loft's sections ...)
and fixes to try, specific to the numbers ("fillet r 3 on edges between faces 4 mm wide: try
r <= 1.9"). The worker makes it from the live exception: the traceback's frames, and the locals
of the build123d call that failed (the edges a fillet was given, the wire an offset was asked
of). The server makes it for what the worker could not report: a timeout (from the progress
lines the worker prints while it builds pieces) or a worker that was killed.

`shape_problems` does the same for a build that ran but made something unprintable: an invalid
solid, zero volume, a 2D shape, a part not on the bed. `analyze_shape` is the deeper look
(diagnose_failure): which faces and edges of an invalid solid are bad, tiny edges and sliver
faces from booleans, and whether `fix()` repairs it.

This module imports nothing heavy at the top: the MCP server uses it outside the worker.
"""

from __future__ import annotations

import difflib
import math
import re
from pathlib import Path

PROGRESS = "[b123d-print progress] "  # lines the worker prints while it builds (see project.Pieces)
LIST_EDGES = ("list_edges (CLI: b123d-print edges) on the part built without this step lists the edges with ids, "
              "convexity and faces; highlight=<ids> of the ones meant shows them and gives a verified selector")
TINY_EDGE = 0.01  # mm: edges shorter than this come from booleans on nearly coincident faces
SLIVER_AREA = 0.01  # mm^2: faces smaller than this, likewise
BED_TOL = 1e-3  # mm: a part whose bottom is further from Z=0 than this is not on the bed

GEOMETRY_TYPES = ("Part", "Solid", "Compound")
BUILDERS = ("BuildPart", "BuildSketch", "BuildLine")
FLAT_TYPES = ("Sketch", "Face", "Shell", "Wire", "Edge", "Curve", "Vertex")


# ---------------------------------------------------------------------------------------------
# where in the script


def _in_folder(filename: str, folder: Path | None) -> bool:
    if folder is None or not filename or filename.startswith("<"):
        return False
    try:
        return Path(filename).resolve().is_relative_to(folder)
    except (OSError, ValueError):
        return False


def _rel(filename: str, folder: Path | None) -> str:
    """The file as the user knows it: parts/<name>/<file> when it is in the part's folder."""
    try:
        p = Path(filename).resolve()
        if folder is not None and p.is_relative_to(folder):
            return (Path(folder.parent.name) / folder.name / p.relative_to(folder)).as_posix()
    except (OSError, ValueError):
        pass
    return Path(filename).name


def where(frames: list, script: str | Path | None) -> dict | None:
    """The innermost frame in the part's folder (the script or a helper module next to it):
    {"file", "line", "function", "code", "chain"}, chain = the script functions on the way there."""
    folder = Path(script).resolve().parent if script else None
    mine = [f for f in frames if _in_folder(f[0], folder)]
    if not mine:
        return None
    fn, line, func, code = mine[-1]
    chain = [f[2] for f in mine if f[2] != "<module>"]
    out = {"file": _rel(fn, folder), "line": line, "function": func, "code": (code or "").strip()}
    if len(chain) > 1:
        out["chain"] = " -> ".join(chain)
    return out


TB_LINE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)\s*$')


def frames_from_text(tb: str) -> list[tuple]:
    """(file, line, function, code) for each frame of a formatted traceback."""
    out, lines = [], (tb or "").splitlines()
    for i, s in enumerate(lines):
        m = TB_LINE.match(s)
        if m:
            code = lines[i + 1].strip() if i + 1 < len(lines) and not TB_LINE.match(lines[i + 1]) else ""
            out.append((m["file"], int(m["line"]), m["func"], code))
    return out


def _piece_from_tb(tb) -> str | None:
    """The piece being built when the exception was raised: the name in project.Pieces.part's
    frame, or what else of the build was running (build(d), assembly(d), the Dims)."""
    import traceback

    found = None
    for frame, _ in traceback.walk_tb(tb):
        code = frame.f_code
        if not code.co_filename.endswith("project.py"):
            continue
        if code.co_name == "part" and isinstance(frame.f_locals.get("name"), str):
            n = frame.f_locals["name"]
            found = f"piece {n or 'part'!r}"
        elif code.co_name == "_build" and found is None:
            found = "build(d)"
        elif code.co_name == "assembly":
            found = "assembly(d)"
        elif code.co_name == "dims":
            found = "Dims / VARIANTS"
    return found


def _dims_used(tb, folder: Path | None) -> dict:
    """{field: value} of the Dims fields (d.FIELD) on the failing line of the script, read from
    the frame's own `d`, so a fix can name the field to change."""
    import traceback

    last = None
    for frame, line in traceback.walk_tb(tb):
        if _in_folder(frame.f_code.co_filename, folder):
            last = (frame, line)
    if last is None:
        return {}
    import linecache

    frame, line = last
    text = linecache.getline(frame.f_code.co_filename, line)
    out = {}
    for var, name in re.findall(r"\b(\w+)\.([A-Z][A-Z0-9_]*)\b", text):
        obj = frame.f_locals.get(var, frame.f_globals.get(var))
        if obj is not None and type(obj).__name__ == "Dims":
            v = getattr(obj, name, None)
            if isinstance(v, (int, float, str, bool)):
                out[name] = v
    return out


# ---------------------------------------------------------------------------------------------
# what the failing build123d call was doing (its locals)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _r(v: float, nd: int = 3) -> float:
    return round(float(v), nd) + 0.0


def _face_width(edge, face) -> float | None:
    """How wide `face` is across `edge`: the distance from the edge to the nearest edge of the
    face that does not touch it (the opposite side of a rectangle; the narrow part of an L)."""
    import numpy as np

    ends = [np.array(tuple(v)) for v in (edge.start_point(), edge.end_point())]
    best = None
    for e in face.edges():
        pts = [np.array(tuple(v)) for v in (e.start_point(), e.end_point())]
        if any(np.linalg.norm(a - b) < 1e-6 for a in ends for b in pts):
            continue  # the edge itself, or one that meets it
        try:
            d = edge.distance_to(e)
        except Exception:  # noqa: BLE001 - a degenerate edge: skip it
            continue
        if d > 1e-6 and (best is None or d < best):
            best = d
    return best


def _fillet_context(shape, edges, value, deep: bool, what: str) -> dict:
    ctx: dict = {"op": what, "radius" if what == "fillet" else "length": _num(value)}
    edges = list(edges or [])
    ctx["edges"] = len(edges)
    if shape is None or not edges:
        return ctx
    try:
        from build123d import Edge

        widths = []
        for e in edges[:50]:
            for f in shape.faces():
                if any(e.wrapped.IsSame(fe.wrapped) for fe in f.edges()):
                    w = _face_width(Edge(e.wrapped), f)
                    if w is not None:
                        widths.append(w)
        if widths:
            ctx["narrowest_face"] = _r(min(widths))
        if deep and what == "fillet" and hasattr(shape, "max_fillet"):
            try:
                ctx["max_fillet"] = _r(shape.max_fillet(edges, tolerance=0.02, max_iterations=14))
            except Exception:  # noqa: BLE001 - no radius works at all: say nothing
                ctx["max_fillet"] = 0.0
    except Exception:  # noqa: BLE001 - evidence is a bonus, never a second error
        pass
    return ctx


def _wire_context(wire, distance) -> dict:
    ctx: dict = {"op": "offset2d", "distance": _num(distance)}
    try:
        edges = wire.edges()
        kinds: dict[str, int] = {}
        for e in edges:
            k = e.geom_type.name.lower()
            kinds[k] = kinds.get(k, 0) + 1
        bb = wire.bounding_box()
        size = sorted([bb.size.X, bb.size.Y, bb.size.Z], reverse=True)[:2]
        ctx.update(edges=len(edges), curves=kinds, size=[_r(s, 2) for s in size])
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _sections_context(objs) -> dict:
    ctx: dict = {"op": "loft"}
    try:
        secs = list(objs or [])
        ctx["sections"] = len(secs)
        ctx["edges_per_section"] = [len(s.edges()) for s in secs]
        ctx["wires_per_section"] = [len(s.wires()) if hasattr(s, "wires") else 1 for s in secs]
        areas = []
        for s in secs:
            try:
                areas.append(_r(s.area, 2))
            except Exception:  # noqa: BLE001 - a wire or vertex: no area
                areas.append(None)
        ctx["areas"] = areas
    except Exception:  # noqa: BLE001
        pass
    return ctx


def _context(tb, deep: bool = False) -> dict:
    """What the deepest known build123d call in the traceback was doing, from its locals."""
    import traceback

    found: dict = {}
    for frame, _ in traceback.walk_tb(tb):
        fn = frame.f_code.co_filename.replace("\\", "/")
        if "/build123d/" not in fn:
            continue
        name, loc = frame.f_code.co_name, frame.f_locals
        try:
            if name == "fillet" and "edge_list" in loc:
                found = _fillet_context(loc.get("self"), loc.get("edge_list"), loc.get("radius"), deep, "fillet")
            elif name == "chamfer" and "edge_list" in loc:
                found = _fillet_context(loc.get("self"), loc.get("edge_list"), loc.get("length"), False, "chamfer")
            elif name in ("fillet", "chamfer") and not found:
                objs = loc.get("object_list") or loc.get("objects")
                found = {"op": name, "edges": len(list(objs)) if isinstance(objs, (list, tuple)) else None,
                         ("radius" if name == "fillet" else "length"): _num(loc.get("radius", loc.get("length")))}
            elif name == "offset_2d":
                found = _wire_context(loc.get("line") or loc.get("self"), loc.get("distance"))
            elif name in ("offset_3d", "hollow"):
                found = {"op": "offset3d", "thickness": _num(loc.get("thickness"))}
                s = loc.get("self")
                if s is not None:
                    bb = s.bounding_box()
                    found["size"] = [_r(bb.size.X, 2), _r(bb.size.Y, 2), _r(bb.size.Z, 2)]
            elif name == "offset" and not found:
                found = {"op": "offset", "amount": _num(loc.get("amount"))}
            elif name in ("loft", "make_loft", "_make_loft"):
                objs = loc.get("objs") if name != "loft" else loc.get("loft_wires") or loc.get("section_list")
                if objs is not None or not found:
                    found = _sections_context(objs) if objs is not None else {"op": "loft"}
            elif name in ("sweep", "sweep_multi"):
                found = {"op": "sweep", "is_frenet": loc.get("is_frenet"),
                         "transition": str(loc.get("transition")).split(".")[-1] if loc.get("transition") is not None else None}
            elif name == "_bool_op":
                op = type(loc.get("operation")).__name__
                found = {"op": "boolean", "operation": {"BRepAlgoAPI_Cut": "cut", "BRepAlgoAPI_Fuse": "fuse",
                                                        "BRepAlgoAPI_Common": "intersect"}.get(op, op)}
            elif name == "extrude" and "amount" in loc and not found:
                found = {"op": "extrude", "amount": _num(loc.get("amount"))}
            elif name == "revolve" and not found:
                found = {"op": "revolve"}
        except Exception:  # noqa: BLE001 - never let the evidence break the diagnosis
            continue
    return {k: v for k, v in found.items() if v is not None}


# ---------------------------------------------------------------------------------------------
# the patterns


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _floor(v: float, step: float = 0.1) -> float:
    return math.floor(v / step + 1e-9) * step


class _Facts:
    """Everything a pattern may look at."""

    def __init__(self, error: str, ctx: dict, where: dict | None, warnings: list, fields: list, part: str,
                 dims_used: dict, frames: list):
        self.error, self.ctx, self.where, self.warnings = error, ctx, where or {}, warnings
        self.fields, self.part, self.dims_used, self.frames = fields, part, dims_used, frames
        self.low = error.lower()
        self.code = self.where.get("code", "")

    def dim_for(self, value) -> str:
        """' (FIELD in Dims: set_params(...))' when a Dims field on the failing line has this value."""
        if value is None:
            return ""
        for k, v in self.dims_used.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(float(v) - float(value)) < 1e-9:
                return f" ({k} in Dims: set_params('{self.part}', {{'{k}': <new value>}}))"
        return ""

    def lib(self, *names: str) -> bool:
        """Did a frame with one of these function names run (in the traceback)?"""
        return any(f[2] in names for f in self.frames)


def _fillet(f: _Facts) -> dict | None:
    op = f.ctx.get("op")
    if not (op in ("fillet", "chamfer") or "failed creating a fillet" in f.low or "failed creating a chamfer" in f.low
            or "nothing to fillet" in f.low or "nothing to chamfer" in f.low):
        return None
    what = op or ("chamfer" if "chamfer" in f.low else "fillet")
    size_key = "radius" if what == "fillet" else "length"
    if "nothing to" in f.low or f.ctx.get("edges") == 0:
        return {"kind": f"{what}-selection",
                "cause": f"the {what} was given no edges: the edge selection is empty (the selector matched nothing, "
                         "or the faces it looks at changed)",
                "fixes": [f"print len(...) of the selection before the {what}; select from the part as it is at that "
                          "point (an earlier cut or fillet changes its edges)",
                          "select with fewer filters, e.g. part.edges().filter_by(Axis.Z) or .group_by(Axis.Z)[-1] "
                          "for the top edges",
                          LIST_EDGES]}
    r = f.ctx.get(size_key)
    m = re.search(r"radius of ([\d.]+)", f.error)
    if r is None and m:
        r = float(m.group(1))
    n, w, mx = f.ctx.get("edges"), f.ctx.get("narrowest_face"), f.ctx.get("max_fillet")
    evidence = []
    if r is not None:
        evidence.append(f"{what} {size_key} {_fmt(r)} mm" + (f" on {n} edge(s)" if n else ""))
    if w is not None:
        evidence.append(f"narrowest face next to those edges: {_fmt(w)} mm wide")
    if mx is not None:
        evidence.append(f"largest {what} radius that works on these edges (max_fillet): {_fmt(mx)} mm")
    fixes = []
    lim = None
    if mx:
        lim = _floor(mx * 0.98)
    elif w is not None:
        lim = _floor(w / 2 * 0.95)
    if r is not None and lim is not None and lim > 0:
        what_r = "r" if what == "fillet" else "length"
        fixes.append(f"{what} {what_r} {_fmt(r)} on edges between faces {_fmt(w if w is not None else 2 * lim)} mm wide: "
                     f"try {what_r} <= {_fmt(lim)}" + f.dim_for(r))
    elif r is not None:
        fixes.append(f"try a smaller {size_key} than {_fmt(r)} mm (halve it to find the limit)" + f.dim_for(r))
    fixes += [f"{what} before the cut or boolean that makes the narrow face, so it rounds simpler geometry",
              f"check the edge selection ({n} edge(s)): an edge next to a curved, tangent or very short face needs a smaller "
              f"{size_key}; {what} fewer edges, or the big ones and the small ones in separate calls"
              if n else f"check the edge selection: {what} fewer edges, or in separate calls"]
    if what == "fillet" and mx is None:
        fixes.append("diagnose_failure finds the largest radius that works on these edges (max_fillet)")
    fixes.append(LIST_EDGES)
    return {"kind": what,
            "cause": f"the {what} {size_key} is too big for a face next to the edges, or the edges selected are not the "
                     "ones meant (OpenCascade cannot fit the rounding)",
            "evidence": evidence, "fixes": fixes}


def _offset2d(f: _Facts) -> dict | None:
    if not (f.ctx.get("op") == "offset2d" or "2d offset failed" in f.low
            or ("unexpected result type" in f.low and f.lib("offset_2d"))):
        return None
    d = f.ctx.get("distance")
    m = re.search(r"distance (-?[\d.]+)", f.error)
    if d is None and m:
        d = float(m.group(1))
    size, curves = f.ctx.get("size"), f.ctx.get("curves") or {}
    splines = sum(v for k, v in curves.items() if k in ("bspline", "bezier", "offset", "other"))
    evidence = []
    if d is not None:
        evidence.append(f"offset distance {_fmt(d)} mm")
    if size:
        evidence.append(f"outline {_fmt(size[0])} x {_fmt(size[1])} mm, {f.ctx.get('edges')} edges "
                        f"({', '.join(f'{v} {k}' for k, v in curves.items())})")
    fixes = []
    if d is not None and size and abs(d) >= min(size) / 2:
        fixes.append(f"the offset ({_fmt(abs(d))} mm) is at least half the outline's narrowest width ({_fmt(min(size))} mm): "
                     f"an inward offset that big makes nothing; use less than {_fmt(min(size) / 2)} mm" + f.dim_for(d))
    if "unexpected result type" in f.low:
        fixes.append("the offset split the outline into several pieces (a narrow neck closed up): use a smaller distance "
                     "or widen the neck")
    if splines or not curves:
        fixes.append("offsets of splines often fail: build the outline as a polyline through points on the spline "
                     "(Polyline(*spline.positions([i / 40 for i in range(41)]))) and offset that; the polygon version of "
                     "a spline outline offsets reliably")
    fixes += ["a tight curve (radius smaller than the offset) folds over itself: smaller distance, or round that corner more",
              "try kind=Kind.INTERSECTION (sharp corners) instead of the default Kind.ARC, or the reverse",
              "build the offset outline directly from the Dims (a smaller Rectangle / RectangleRounded / Polyline) instead "
              "of offsetting"]
    return {"kind": "offset2d",
            "cause": "the 2D offset cannot be made: too big for the outline (an inward offset past half its width), a tight "
                     "curve that folds over itself, or a spline OpenCascade cannot offset",
            "evidence": evidence, "fixes": fixes}


def _offset3d(f: _Facts) -> dict | None:
    if not (f.ctx.get("op") in ("offset3d", "offset") or f.lib("offset_3d", "hollow", "shell")):
        return None
    t = f.ctx.get("thickness", f.ctx.get("amount"))
    size = f.ctx.get("size")
    fixes = []
    if t is not None and size and abs(t) >= min(size) / 2:
        fixes.append(f"the offset ({_fmt(abs(t))} mm) is at least half the part's smallest size ({_fmt(min(size))} mm): "
                     "an inward offset that big leaves nothing" + f.dim_for(t))
    fixes += ["inward offsets (shell, hollow) fail on fillets with a radius smaller than the thickness: make those "
              "fillets bigger than the wall, or fillet after shelling",
              "shell the simple body first, then add the small features (bosses, holes, text)",
              "or build the inside as its own solid from the Dims and subtract it"]
    return {"kind": "offset3d",
            "cause": "the 3D offset (shell / hollow / offset of a solid) failed: the wall is thicker than the part allows "
                     "somewhere, or a small fillet or feature collapses",
            "evidence": [f"offset {_fmt(t)} mm"] if t is not None else [], "fixes": fixes}


def _loft(f: _Facts) -> dict | None:
    if not (f.ctx.get("op") == "loft" or "loft" in f.low or "same number of inner wires" in f.low
            or f.lib("loft", "make_loft", "_make_loft")):
        return None
    evidence, fixes = [], []
    n, edges, areas = f.ctx.get("sections"), f.ctx.get("edges_per_section"), f.ctx.get("areas")
    if n:
        evidence.append(f"{n} sections; edges per section {edges}")
    if edges and len(set(edges)) > 1:
        fixes.append(f"the sections have different edge counts ({edges}): give every section the same number of "
                     "edges (split a circle into arcs to match a rectangle's 4 sides) or use ruled=True")
    if areas and any(a is not None and a <= 1e-9 for a in areas):
        fixes.append("a section has zero area: end the loft on a Vertex (a point) instead of a zero-size shape")
    if "inner wires" in f.low or (f.ctx.get("wires_per_section") and len(set(f.ctx["wires_per_section"])) > 1):
        fixes.append("every section must have the same number of holes (inner wires); loft the outer shapes and cut "
                     "the holes afterwards")
    fixes += ["sections must be in order along the loft and must not cross or touch each other",
              "start each section at the same corner and draw them in the same direction (a twist folds the surface)",
              "try ruled=True (straight between sections) to see whether the smooth version is the problem"]
    return {"kind": "loft", "cause": "the loft cannot join these sections into a solid", "evidence": evidence,
            "fixes": fixes}


def _sweep(f: _Facts) -> dict | None:
    if not (f.ctx.get("op") == "sweep" or f.lib("sweep", "sweep_multi")):
        return None
    return {"kind": "sweep",
            "cause": "the sweep cannot move the profile along the path: a sharp corner in the path, a profile bigger "
                     "than the path's bend radius, or a profile that does not sit at the start of the path",
            "evidence": [f"transition {f.ctx['transition']}"] if f.ctx.get("transition") else [],
            "fixes": ["round the path's corners (fillet the path, or a Spline through its points), or pass "
                      "transition=Transition.ROUND / Transition.RIGHT for a polyline path",
                      "make the path's bend radius bigger than the profile's half width",
                      "put the profile at the start of the path, perpendicular to it (Plane(path @ 0, z_dir=path % 0))",
                      "is_frenet=True for helices and other 3D paths"]}


def _boolean(f: _Facts) -> dict | None:
    unclean = [w for w in f.warnings if "unable to clean" in w.lower()]
    if not (f.ctx.get("op") == "boolean" or unclean or "null topods_shape" in f.low
            or "brep_api: command not done" in f.low or "nothing to intersect" in f.low):
        return None
    op = f.ctx.get("operation")
    return {"kind": "boolean",
            "cause": f"the boolean{(' ' + op) if op else ''} failed or made a broken result: usually faces that "
                     "coincide exactly (coplanar), shapes that only just touch (tangent contact), or a sliver thinner "
                     "than the tolerance",
            "evidence": [f"warning: {w}" for w in unclean[:3]],
            "fixes": ["make every cutting tool reach past the faces it shares with the part: a hole through a 3 mm "
                      "wall as Cylinder(r, 3 + 1) centered on it, a pocket 0.01-1 mm deeper than the face it opens to",
                      "avoid exactly tangent contact (a cylinder touching a flat face along a line): overlap by 0.1 mm "
                      "or leave a gap",
                      "pieces to fuse must overlap a little, not only share a face",
                      "a cut that leaves a skin under 0.01 mm: move it or make it go through",
                      "split the operation (cut the tools one at a time) to find the one that fails"]}


def _extrude(f: _Facts) -> dict | None:
    if not (f.ctx.get("op") == "extrude" or "brepsweep_translation" in f.low):
        return None
    a = f.ctx.get("amount")
    return {"kind": "extrude",
            "cause": "the extrusion has zero length, or goes along the sketch's own plane",
            "evidence": [f"amount {_fmt(a)} mm"] if a is not None else [],
            "fixes": ["give a non-zero amount" + f.dim_for(a) if a is not None else "give a non-zero amount",
                      "extrude along the sketch's normal: a sketch on Plane.XZ extrudes along Y"]}


def _dims(f: _Facts) -> dict | None:
    m = re.search(r"'Dims' object has no attribute '(\w+)'", f.error)
    names = [x["name"] for x in f.fields]
    if m:
        name = m.group(1)
        close = difflib.get_close_matches(name, names, n=3, cutoff=0.6)
        fixes = [f"add the field to Dims with a comment saying where the value comes from: "
                 f"`{name}: float = <value>  # measured / typed / estimate`"]
        if close:
            fixes.insert(0, f"did you mean {' or '.join(close)}? (Dims has {', '.join(names)})")
        return {"kind": "missing-dim", "cause": f"the script uses {name} but Dims has no field {name}",
                "evidence": [f"Dims fields: {', '.join(names) or 'none'}"], "fixes": fixes}
    m = re.search(r"__init__\(\) got an unexpected keyword argument '(\w+)'", f.error)
    if m and ("Dims" in f.error or "variants" in f.low or f.where.get("function") in (None, "<module>")):
        name = m.group(1)
        close = difflib.get_close_matches(name, names, n=3, cutoff=0.6)
        return {"kind": "variant-field", "cause": f"VARIANTS overrides {name}, which is not a Dims field",
                "fixes": [(f"did you mean {' or '.join(close)}? " if close else "")
                          + f"fix the name in VARIANTS, or add {name} to Dims"]}
    if "cannot assign to field" in f.low:
        return {"kind": "frozen-dims", "cause": "the script assigns to a Dims field, but Dims is frozen (read-only)",
                "fixes": ["compute the value in a local variable, or as a @property of Dims for a derived value",
                          "a different value for a variant goes into VARIANTS, not into d"]}
    if re.search(r"missing \d+ required positional argument", f.error) and "Dims" in f.error:
        return {"kind": "dims-default", "cause": "a Dims field has no default value",
                "fixes": ["give every Dims field a default (`WIDTH: float = 40.0  # source`)"]}
    return None


def _wrong_type(f: _Facts) -> dict | None:
    m = re.search(r"'(\w+)'(?: object)? has no attribute '(\w+)'", f.error)
    if "neither build(d) nor a module-level" in f.low:
        return {"kind": "no-build", "cause": "the script defines no build(d) function",
                "fixes": ["define build(d) returning the printable part (or {'name': part} for several)"]}
    if not m or m.group(1) == "Dims":
        return None
    t, attr = m.groups()
    in_runner = not f.where or f.where.get("function") in ("<module>",) or attr in (
        "bounding_box", "is_valid", "volume", "solids", "faces", "wrapped")
    if not in_runner:
        return None
    if t == "NoneType":
        cause, fix = ("build(d) (or a piece's function) returned None", "end the function with `return part` "
                      "(a function without return gives None)")
    elif t in BUILDERS:
        cause, fix = (f"build(d) returned the {t} builder, not its shape",
                      f"return the builder's shape: `return bp.{'part' if t == 'BuildPart' else 'sketch' if t == 'BuildSketch' else 'line'}`")
    elif t in ("list", "tuple", "ShapeList"):
        cause, fix = (f"build(d) returned a {t}", "return one Part (fuse them: `Part() + [a, b]`, or a Compound), or a "
                      "dict {'name': part} for separate pieces")
    elif t in ("dict",):
        cause, fix = ("a piece of build(d) is a dict", "return {'name': part} with one shape (or a function) per name")
    elif t in ("int", "float", "str"):
        cause, fix = (f"build(d) returned a {t}", "return the Part you built")
    else:
        return None
    return {"kind": "wrong-type", "cause": cause,
            "fixes": [fix, "build(d) returns a Part in print orientation, or {'name': Part or lambda: Part} for several"]}


def _selection(f: _Facts) -> dict | None:
    if not f.error.startswith("IndexError"):
        return None
    if not re.search(r"\.(edges|faces|vertices|wires|solids|group_by|sort_by|filter_by)\(", f.code):
        return None
    return {"kind": "selection",
            "cause": "a selector returned fewer items than the index asks for (an empty or shorter selection)",
            "fixes": ["print len(...) of the selection: the faces or edges at that point are not the ones expected "
                      "(an earlier cut, fillet or a changed dimension changes them)",
                      "select by position or direction (sort_by(Axis.Z)[-1], filter_by(Axis.Z), group_by(...)) "
                      "instead of a fixed index into a list"]}


def _name(f: _Facts) -> dict | None:
    m = re.match(r"NameError: name '(\w+)' is not defined", f.error)
    if not m:
        return None
    n = m.group(1)
    fixes = []
    import sys

    for mod in ("build123d", "b123d_print"):
        lib = sys.modules.get(mod)
        if lib is not None and hasattr(lib, n):
            fixes.append(f"add `from {mod} import {n}`")
    if n == "d":
        fixes.append("pass d into the function that uses it (def piece(d): ...)")
    fixes.append("check the spelling, and that it is defined before it is used")
    return {"kind": "name", "cause": f"{n} is not defined in the script", "fixes": fixes}


def _sandbox(f: _Facts) -> dict | None:
    if "blocked in part scripts" not in f.low:
        return None
    return {"kind": "sandbox", "cause": "the script did something part scripts may not: network, starting programs, "
                                        "native libraries, or writing outside the part's out/ folder",
            "fixes": ["remove it: a part script only builds geometry (files it needs go next to it, read-only)"]}


PATTERNS = (_dims, _wrong_type, _fillet, _offset2d, _offset3d, _loft, _sweep, _extrude, _boolean, _selection, _name,
            _sandbox)


def classify(error: str, ctx: dict | None = None, where_: dict | None = None, warnings=(), fields=(), part: str = "<part>",
             dims_used: dict | None = None, frames=()) -> dict:
    """The diagnosis of one error: {"kind", "cause", "evidence", "fixes", "where", "error"}."""
    f = _Facts(error or "", ctx or {}, where_, list(warnings), list(fields), part, dims_used or {}, list(frames))
    found = None
    for p in PATTERNS:
        found = p(f)
        if found:
            break
    if found is None:
        found = {"kind": "other", "cause": "an error in the script" + (" (see where)" if where_ else ""),
                 "fixes": [f"diagnose_failure('{part}') builds each piece on its own and looks deeper",
                           "section through the region near the failing feature to see the geometry at that point"]}
    out = {"kind": found["kind"], "cause": found["cause"], "error": (error or "").splitlines()[0][:300]}
    if where_:
        out["where"] = where_
    if dims_used:
        out["dims_on_line"] = dims_used
    if ctx:
        out["context"] = ctx
    if found.get("evidence"):
        out["evidence"] = found["evidence"]
    out["fixes"] = found["fixes"]
    other = [w for w in warnings if w not in "".join(out.get("evidence", []))]
    if other:
        out["warnings"] = other[:5]
    return out


def _fields(script) -> list:
    if not script:
        return []
    try:
        from .params import read

        return read(Path(script).read_text(encoding="utf-8"))["fields"]
    except Exception:  # noqa: BLE001 - no Dims, or a script that does not parse
        return []


def from_exception(exc: BaseException, script=None, warnings=(), deep: bool = False) -> dict:
    """The diagnosis of an exception the worker caught (live traceback: frame locals are read)."""
    import traceback

    tb = exc.__traceback__
    frames = [(f.filename, f.lineno, f.name, f.line) for f in traceback.extract_tb(tb)]
    folder = Path(script).resolve().parent if script else None
    w = where(frames, script)
    piece = _piece_from_tb(tb)
    if piece:
        w = {**(w or {}), "piece": piece}
    try:
        ctx = _context(tb, deep)
    except Exception:  # noqa: BLE001
        ctx = {}
    try:
        used = _dims_used(tb, folder)
    except Exception:  # noqa: BLE001
        used = {}
    error = f"{type(exc).__name__}: {exc}"
    return classify(error, ctx, w, warnings, _fields(script), Path(script).stem if script else "<part>", used, frames)


def progress(log: str) -> dict:
    """What the progress lines in a worker's output say: pieces built (with faces and seconds) and
    the one it was building last."""
    done, running = {}, None
    for line in (log or "").splitlines():
        if not line.startswith(PROGRESS):
            continue
        msg = line[len(PROGRESS):]
        m = re.match(r"built piece (.+): (\d+) faces, ([\d.]+) s$", msg)
        if m:
            done[m.group(1)] = {"faces": int(m.group(2)), "seconds": float(m.group(3))}
            if running == m.group(1):
                running = None
            continue
        if msg.startswith("built build(d)"):
            running = None if running == "build(d)" else running
            continue
        m = re.match(r"building (?:piece )?(.+)$", msg)
        if m:
            running = m.group(1)
    return {"done": done, "running": running}


def slow_piece(label: str, seconds: float) -> dict:
    """A piece that ran out of the time left for diagnose_failure."""
    return {"kind": "timeout", "cause": f"{label} was still building after {seconds:.0f} s, when the time ran out",
            "where": {"piece": f"piece {label!r}"},
            "fixes": [f"work on {label} alone (parts='{label}') and make it cheaper: fewer curve points, a spline "
                      "instead of a dense polyline, fewer stacked offsets",
                      "build each distinct piece once (@functools.cache) and mirror or copy it"]}


def from_result(res: dict, script=None) -> dict | None:
    """The diagnosis of a failed result the worker did not diagnose: a timeout, a killed worker,
    or an error reported without one (the traceback's text is parsed instead)."""
    if res.get("ok") or res.get("diagnosis"):
        return res.get("diagnosis")
    error, part = str(res.get("error") or ""), Path(script).stem if script else "<part>"
    if error.startswith("timed out"):
        pr = progress(res.get("log", ""))
        ev = [f"{n}: {st['faces']} faces, {st['seconds']:g} s" for n, st in pr["done"].items()]
        fixes = []
        running = pr["running"] if pr["running"] in (None, "build(d)") else f"piece {pr['running']!r}"
        if pr["running"] and pr["running"] != "build(d)":
            fixes.append(f"work on {pr['running']} alone (parts='{pr['running']}' on build_part, render_preview, "
                         "section, export) and make it cheaper: fewer curve points, a spline instead of a dense polyline, "
                         "fewer stacked offsets")
        elif pr["running"] == "build(d)":
            fixes.append("build(d) itself was running: return lazy pieces ({'name': lambda: make_name(d)}) so each "
                         "piece builds, times and caches on its own, then work on the slow one with parts=")
        else:
            fixes.append("return lazy pieces from build(d) and build one at a time with parts= to find the slow one")
        fixes += ["build each distinct piece once (@functools.cache on its function) and mirror or copy it, instead "
                  "of building it again",
                  "a piece over ~1,500 faces is slow everywhere: halve the points of curves and polylines"]
        if pr["done"]:
            fixes.append("pieces that finished are cached: the next call builds only the rest")
        return {"kind": "timeout",
                "cause": "the build ran out of time" + (f" while building {running}" if running else ""),
                "error": error, **({"where": {"piece": running}} if running else {}),
                **({"evidence": ["finished: " + "; ".join(ev)]} if ev else {}), "fixes": fixes}
    if error.startswith("worker was killed") or error.startswith("worker exited"):
        pr = progress(res.get("log", ""))
        return {"kind": "killed", "cause": "the build process died: most often out of memory (a huge face count, a "
                                           "very fine mesh or polyline)", "error": error,
                **({"where": {"piece": pr["running"]}} if pr["running"] else {}),
                "fixes": ["build one piece at a time with parts= to find the one", "fewer points in curves and polylines"]}
    if error.startswith("cancelled"):
        return None
    frames = frames_from_text(res.get("traceback", ""))
    return classify(error, {}, where(frames, script), [], _fields(script), part, {}, frames)


def text(diag: dict | None, name: str | None = None) -> str:
    """The diagnosis as text lines for a tool result."""
    if not diag:
        return ""
    lines = [f"DIAGNOSIS ({diag['kind']}): {diag['cause']}"]
    w = diag.get("where") or {}
    if w:
        at = f"{w['file']} line {w['line']} in {w['function']}" if w.get("file") else ""
        piece = w.get("piece")
        lines.append("  where: " + ", ".join(x for x in (at, f"while building {piece}" if piece else "") if x)
                     + (f": {w['code']}" if w.get("code") else ""))
        if w.get("chain"):
            lines.append(f"  called as: {w['chain']}")
    if diag.get("dims_on_line"):
        lines.append("  Dims on that line: " + ", ".join(f"{k}={v}" for k, v in diag["dims_on_line"].items()))
    for e in diag.get("evidence", []):
        lines.append(f"  evidence: {e}")
    for w_ in diag.get("warnings", []):
        lines.append(f"  warning: {w_}")
    lines.append("  try:")
    lines += [f"    - {x}" for x in diag.get("fixes", [])]
    if name and diag["kind"] not in ("sandbox",):
        lines.append(f"  deeper look: diagnose_failure('{name}')")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# a build that ran, but made something unprintable


def shape_problems(name: str, shape, rep: dict | None = None) -> list[dict]:
    """What is wrong with a built piece: not a 3D shape, zero volume, invalid, not on the bed.
    Each problem is a diagnosis ({"kind", "cause", "fixes"})."""
    t = type(shape).__name__
    out = []
    if t in FLAT_TYPES:
        return [{"kind": "flat", "cause": f"{name} is a {t} (2D), not a solid",
                 "fixes": ["extrude the sketch (extrude(sketch, amount=...)) or revolve it before returning it"]}]
    try:
        vol = float(shape.volume)
        valid = bool(shape.is_valid)
        bb = shape.bounding_box()
        zmin = float(bb.min.Z)
    except Exception as e:  # noqa: BLE001
        return [{"kind": "wrong-type", "cause": f"{name} is a {t}, not a shape ({e})",
                 "fixes": ["return a Part (or {'name': Part})"]}]
    if vol <= 1e-9:
        out.append({"kind": "empty", "cause": f"{name} has zero volume: a boolean removed everything (the cutting tool "
                                              "covers the part), an intersect of shapes that do not overlap, or only "
                                              "faces were returned",
                    "fixes": ["render_preview / section the inputs of the last boolean to see where they are",
                              "check the signs and alignment of the tools (Align.MIN vs CENTER puts them elsewhere)"]})
    if not valid:
        out.append({"kind": "invalid", "cause": f"{name} is not a valid solid (is_valid=False): usually from a boolean "
                                                "on coplanar faces, tangent contact or a sliver",
                    "fixes": ["let cutting tools reach past the faces they share with the part (0.01-1 mm)",
                              "avoid exactly tangent or coincident contact: overlap by 0.1 mm or leave a gap",
                              "diagnose_failure shows which faces and edges are bad, tiny edges and sliver faces, "
                              "and whether part.fix() repairs it"]})
    if vol > 1e-9 and abs(zmin) > BED_TOL:
        where_ = "below the bed" if zmin < 0 else "above the bed"
        out.append({"kind": "bed", "cause": f"{name}'s bottom is at Z={_fmt(zmin)} ({where_}): parts are built in print "
                                            "orientation with the bottom face on Z=0",
                    "fixes": [f"move it: `part = Pos(0, 0, {_fmt(-zmin)}) * part` (or align=(Align.CENTER, Align.CENTER, "
                              "Align.MIN) on the first shape)",
                              "if it is meant to print in another orientation, turn it first, then put it on the bed"]})
    return out


def analyze_shape(shape, limit: int = 8) -> dict:
    """The deeper look at a built piece: bad faces and edges (BRepCheck), tiny edges, sliver
    faces, and whether `fix()` makes it valid. Locations are centers in mm."""
    from OCP.BRepCheck import BRepCheck_Analyzer

    def c(s):
        p = s.center()
        return [_r(p.X, 2), _r(p.Y, 2), _r(p.Z, 2)]

    out: dict = {"valid": bool(shape.is_valid), "faces": len(shape.faces()), "edges": len(shape.edges()),
                 "solids": len(shape.solids()), "volume": _r(shape.volume, 3)}
    bad_f = [f for f in shape.faces() if not BRepCheck_Analyzer(f.wrapped).IsValid()]
    bad_e = [e for e in shape.edges() if not BRepCheck_Analyzer(e.wrapped).IsValid()]
    tiny = [e for e in shape.edges() if e.length < TINY_EDGE]
    slivers = [f for f in shape.faces() if f.area < SLIVER_AREA]
    if bad_f:
        out["bad_faces"] = [{"type": f.geom_type.name.lower(), "center": c(f), "area": _r(f.area, 4)} for f in bad_f[:limit]]
    if bad_e:
        out["bad_edges"] = [{"center": c(e), "length": _r(e.length, 4)} for e in bad_e[:limit]]
    if tiny:
        out["tiny_edges"] = [{"center": c(e), "length": _r(e.length, 5)} for e in tiny[:limit]]
    if slivers:
        out["sliver_faces"] = [{"center": c(f), "area": _r(f.area, 5)} for f in slivers[:limit]]
    for k, lst in (("bad_faces", bad_f), ("bad_edges", bad_e), ("tiny_edges", tiny), ("sliver_faces", slivers)):
        if len(lst) > limit:
            out[k + "_more"] = len(lst) - limit
    if not out["valid"]:
        try:
            fixed = shape.fix()
            out["fix_repairs_it"] = bool(fixed.is_valid) and abs(fixed.volume - shape.volume) < 0.01 * max(1.0, abs(shape.volume))
        except Exception:  # noqa: BLE001
            out["fix_repairs_it"] = False
    notes = []
    if tiny or slivers:
        notes.append("tiny edges / sliver faces near the listed centers: a cut or fuse there meets a face almost exactly "
                     "(coplanar or tangent); move that tool 0.01-1 mm so it clearly overlaps or clearly misses")
    if out.get("fix_repairs_it"):
        notes.append("part.fix() makes it valid with the same volume: call it on the result as a stopgap, and fix the "
                     "boolean that made it")
    if notes:
        out["notes"] = notes
    return out


# ---------------------------------------------------------------------------------------------
# the deeper look: diagnose_failure


def warning_texts(caught: list) -> list[str]:
    """The warnings worth showing (build123d's "Unable to clean", ...), once each, at most ten."""
    out = []
    for w in caught:
        if issubclass(w.category, (DeprecationWarning, PendingDeprecationWarning, ImportWarning)):
            continue
        msg = str(w.message)[:300]
        if msg not in out:
            out.append(msg)
    return out[:10]


def deep(script: Path, key: str | None, parts: str | None = None, deadline: float | None = None,
         warned: list | None = None) -> dict:
    """Build one variant piece by piece, each on its own and without the build cache, and say
    what is wrong with each: the error and its diagnosis (with max_fillet for a fillet), or for a
    piece that built, what makes it unprintable and, when it is invalid, which faces and edges are
    bad. Stops before `deadline` (time.time()) and names the pieces it did not get to. `warned`:
    the list a warnings.catch_warnings(record=True) is filling."""
    import time

    from .config import load_settings
    from .project import CheckTimeout, _Deadline, dims, load, make_pieces, variants
    from .render import report

    warned = warned if warned is not None else []
    res: dict = {}

    def failed(e: BaseException, stage: str) -> dict:
        return {**res, "stage": stage, "error": f"{type(e).__name__}: {e}",
                "diagnosis": from_exception(e, script, warning_texts(warned), deep=True)}

    try:
        mod = load(script)
    except Exception as e:  # noqa: BLE001
        return failed(e, "loading the script")
    keys = list(variants(mod))
    if key is not None and key not in keys:
        raise KeyError(f"no variant {key or 'standard'!r}; variants: {[k or 'standard' for k in keys]}")
    k = key if key is not None else keys[0]
    res["variant"] = k or "standard"
    try:
        d = dims(mod, k)
    except Exception as e:  # noqa: BLE001
        return failed(e, "making the Dims (VARIANTS)")
    pc = make_pieces(mod, k, d, load_settings(script), None)  # no cache: the errors and times as they are
    try:
        names = pc.names()
    except Exception as e:  # noqa: BLE001
        return failed(e, "running build(d)")
    if parts:
        want = [w.strip() for w in parts.split(",") if w.strip()]
        known = {(n or "part"): n for n in names}
        missing = [w for w in want if w not in known]
        if missing:
            raise KeyError(f"no part(s) {missing}; parts: {sorted(known)}")
        names = [known[w] for w in want]
    pieces: dict = {}
    skipped: list[str] = []
    for i, n in enumerate(names):
        label = n or "part"
        if deadline is not None and time.time() > deadline - 2:
            skipped += [x or "part" for x in names[i:]]
            break
        n0, t = len(warned), time.perf_counter()
        try:
            with _Deadline(deadline):
                shape = pc.part(n)
        except CheckTimeout:
            pieces[label] = {"ok": False, "error": "out of time", "diagnosis": slow_piece(label, time.perf_counter() - t)}
            skipped += [x or "part" for x in names[i + 1:]]
            break
        except Exception as e:  # noqa: BLE001
            pieces[label] = {"ok": False, "seconds": round(time.perf_counter() - t, 2), "error": f"{type(e).__name__}: {e}",
                             "diagnosis": from_exception(e, script, warning_texts(warned[n0:]), deep=True)}
            continue
        entry: dict = {"ok": True, "seconds": round(time.perf_counter() - t, 2)}
        try:
            entry["report"] = report(shape)
            entry["problems"] = shape_problems(label, shape, entry["report"])
            if not entry["report"]["valid"] or entry["report"]["volume"] <= 0:
                entry["analysis"] = analyze_shape(shape)
        except Exception as e:  # noqa: BLE001 - not a shape at all
            entry.update(ok=False, error=f"{type(e).__name__}: {e}", diagnosis=from_exception(e, script, deep=True))
        if warned[n0:]:
            entry["warnings"] = warning_texts(warned[n0:])
        pieces[label] = entry
    res["pieces"] = pieces
    if skipped:
        res["not_built"] = skipped
    if hasattr(mod, "assembly") and not parts and not skipped and all(p["ok"] for p in pieces.values()):
        try:
            res["assembly"] = [it[2] if isinstance(it, (list, tuple)) and len(it) > 2 else "?" for it in pc.assembly() or []]
        except Exception as e:  # noqa: BLE001
            res["assembly_error"] = {"error": f"{type(e).__name__}: {e}", "diagnosis": from_exception(e, script, deep=True)}
    return res


def deep_text(res: dict, name: str) -> str:
    """deep()'s result as the text diagnose_failure and `b123d-print diagnose` show."""
    import json

    lines = [f"diagnose_failure {name} [{res.get('variant', '?')}]"]
    if res.get("error"):  # the script failed before any piece: loading, Dims or build(d)
        lines.append(f"FAILED while {res['stage']}: {res['error']}")
        lines.append(text(res.get("diagnosis")))
        return "\n".join(lines)
    for pname, p in res.get("pieces", {}).items():
        if not p["ok"]:
            lines.append(f"\npiece {pname}: FAILED" + (f" after {p['seconds']:g} s" if p.get("seconds") is not None else "")
                         + f": {p['error']}")
            lines += ["  " + x for x in text(p.get("diagnosis")).splitlines()]
            continue
        r = p["report"]
        lines.append(f"\npiece {pname}: built in {p['seconds']:g} s, {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, "
                     f"volume {r['volume']:.1f} mm^3, {r['solids']} solid(s), valid={r['valid']}")
        for pr in p.get("problems", []):
            lines.append(f"  PROBLEM ({pr['kind']}): {pr['cause']}")
            lines += [f"    - {f}" for f in pr["fixes"]]
        for w in p.get("warnings", []):
            lines.append(f"  warning: {w}")
        if p.get("analysis"):
            lines.append("  analysis: " + json.dumps(p["analysis"]))
        if not p.get("problems") and not p.get("warnings"):
            lines.append("  OK")
    if res.get("not_built"):
        lines.append(f"\nnot built (out of time): {', '.join(res['not_built'])}; ask for them with parts=")
    if res.get("assembly") is not None:
        lines.append(f"\nassembly(d): OK ({len(res['assembly'])} items)")
    if res.get("assembly_error"):
        lines.append(f"\nassembly(d) FAILED: {res['assembly_error']['error']}")
        lines.append(text(res["assembly_error"].get("diagnosis")))
    return "\n".join(lines)
