"""Sketch first: the 2D shapes a part is made from, drawn and checked before any 3D.

A part script may define

    def sketches(d) -> dict[str, Sketch | Face | callable]

returning named 2D shapes (an outline made with FilletPolyline + make_face, slots, circles, a
revolve profile, a sweep section). Like lazy pieces, a value may be a zero-argument function:
only the sketch asked for is made. `render_sketch` (CLI `b123d-print sketch`) draws one on a mm
grid with its dimensions (overall size, holes, slots, inside corner radii) and runs the sketch
checks: one closed region, the narrowest neck against min_wall, sharp or tight inside corners
(BP-R1), holes under 1 mm (BP-H5), and the outline against the bed. build(d) then extrudes,
revolves or sweeps the same shape, so the part is what the user confirmed.

Sketches are 2D and quick to make, so they are not cached; nothing here builds the part.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import numpy as np

from . import checks as ck
from .bodies import valid_name  # a sketch's name goes into its picture's file name: the body-name rule
from .checks import FAIL, OK, WARN, Finding

STEP = 0.05  # mm between outline points: an arc of radius r turns STEP / r rad per point
SHARP_DEG = 25.0  # a turn this sharp at one outline point is a corner with no radius (r < ~0.1 mm)
INSIDE_R = 0.5  # mm: inside corners under this radius warn (BP-R1)
MIN_HOLE = 1.0  # mm: holes under this warn (BP-H5)
MAX_ORDINATES = 14  # more distinct hole/slot centres than this along one edge: listed, not drawn
FILL, EDGE, MARK = "#4c8cd9", "#1d3f6e", "#cc2222"


# ---------------------------------------------------------------------------------------------
# The hook


class SketchError(LookupError):
    """No sketches(d), or no sketch of that name: a wrong request, nothing to diagnose."""


class Sketches:
    """The sketches of one variant, each made when first asked for."""

    def __init__(self, mod: ModuleType, d):
        f = getattr(mod, "sketches", None)
        if f is None:
            raise SketchError("this script has no sketches(d): sketch first is optional; add "
                              "def sketches(d): return {'outline': ...} (new_part(..., sketch_first=True) scaffolds one)")
        raw = f(d) if d is not None else f()
        if not isinstance(raw, dict):
            raw = {"sketch": raw}
        bad = [k for k in raw if not valid_name(k)]
        if bad:
            raise SketchError(f"sketches(d): bad sketch name(s) {bad}: a name is 1-40 letters, digits, '_' or '-', "
                              "starting with a letter or digit (it becomes part of the picture's file name)")
        self._raw, self._done = raw, {}

    def names(self) -> list[str]:
        return list(self._raw)

    def get(self, name: str | None = None):
        """One sketch by name (default: the first)."""
        if not self._raw:
            raise SketchError("sketches(d) returned no sketches")
        name = name or next(iter(self._raw))
        if name not in self._raw:
            raise SketchError(f"no sketch {name!r}; sketches: {self.names()}")
        if name not in self._done:
            from build123d import Shape

            v = self._raw[name]
            self._done[name] = v() if callable(v) and not isinstance(v, Shape) else v
        return self._done[name]


# ---------------------------------------------------------------------------------------------
# Flattening and features


def flatten(shape) -> tuple[list, str]:
    """The faces of a 2D shape laid in XY, and the names of the axes it was drawn in ("XY" for a
    sketch on Plane.XY, "XZ" for one on Plane.XZ, ...). A sketch on XY keeps the script's own
    coordinates; one on another plane is read in that plane's own (x, y)."""
    from build123d import Plane, Vector

    faces = list(shape.faces()) if hasattr(shape, "faces") else []
    if not faces:
        return [], "XY"
    n = faces[0].normal_at()
    for name, plane in (("XY", Plane.XY), ("XZ", Plane.XZ), ("YZ", Plane.YZ)):
        if abs(abs(n.dot(plane.z_dir)) - 1) < 1e-6:
            break
    else:
        name, plane = "XY", Plane(faces[0].center(), z_dir=n)
    if name == "XY":
        z = faces[0].center().Z
        flat = [f.translate(Vector(0, 0, -z)) if abs(z) > 1e-9 else f for f in faces]
    else:
        flat = [plane.to_local_coords(f) for f in faces]
    return flat, name


def _wire_kind(w) -> tuple[str, dict]:
    """("hole", {d, center}) for one full circle, ("slot", {...}) for two parallel lines with two
    half circles, else ("cutout", {})."""
    edges = w.edges()
    kinds = [e.geom_type.name for e in edges]
    if kinds == ["CIRCLE"]:
        c = edges[0].arc_center
        return "hole", {"d": round(2 * edges[0].radius, 3), "center": [round(c.X, 3), round(c.Y, 3)]}
    if sorted(kinds) == ["CIRCLE", "CIRCLE", "LINE", "LINE"]:
        arcs = [e for e in edges if e.geom_type.name == "CIRCLE"]
        lines = [e for e in edges if e.geom_type.name == "LINE"]
        if abs(arcs[0].radius - arcs[1].radius) < 1e-6 and abs(lines[0].length - lines[1].length) < 1e-6:
            a, b = arcs[0].arc_center, arcs[1].arc_center
            if abs((a - b).length - lines[0].length) < 1e-4:
                return "slot", {"width": round(2 * arcs[0].radius, 3), "length": round((a - b).length, 3),
                                "centers": [[round(a.X, 3), round(a.Y, 3)], [round(b.X, 3), round(b.Y, 3)]]}
    return "cutout", {}


def _arcs(face, wires) -> list[dict]:
    """The arcs on these wires that are corners, each {r, at, center, inside}: inside when the
    arc's centre is on the empty side (a concave, inside corner), else an outside rounding."""
    from build123d import Vector

    out = []
    for w in wires:
        for e in w.edges():
            if e.geom_type.name != "CIRCLE" or e.is_closed:
                continue
            r, c, m = e.radius, e.arc_center, e.position_at(0.5)
            towards = (c - m).normalized() * min(0.05, r / 2)
            inside = not face.is_inside(Vector(m.X + towards.X, m.Y + towards.Y, 0))
            out.append({"r": round(r, 3), "at": [round(m.X, 3), round(m.Y, 3)], "center": [round(c.X, 3), round(c.Y, 3)],
                        "inside": inside})
    return out


def _sharp_inside(loops) -> list[list[float]]:
    """Points where an outline turns into the material by more than SHARP_DEG at once: inside
    corners with no radius. Loops have the material on the left, so an inside corner turns right."""
    out = []
    for p in loops:
        q = p[np.r_[True, np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-6]]
        if len(q) < 3:
            continue
        din = q - np.roll(q, 1, axis=0)
        dout = np.roll(q, -1, axis=0) - q
        cross = din[:, 0] * dout[:, 1] - din[:, 1] * dout[:, 0]
        dot = (din * dout).sum(1)
        turn = np.degrees(np.arctan2(cross, dot))
        for i in np.nonzero(turn < -SHARP_DEG)[0]:
            out.append([round(float(q[i, 0]), 3), round(float(q[i, 1]), 3)])
    return out


def features(shape) -> dict:
    """What the sketch is made of, in its own 2D coordinates (see flatten): overall size and
    lower-left corner, faces, holes, slots, other cutouts, corner arcs and sharp inside corners."""
    faces, axes = flatten(shape)
    res = {"axes": axes, "faces": len(faces), "holes": [], "slots": [], "cutouts": 0, "arcs": [], "sharp_inside": [],
           "loops": []}
    if not faces:
        return res
    from build123d import Compound

    bb = Compound(faces).bounding_box()
    res.update(size=[round(bb.size.X, 3), round(bb.size.Y, 3)], min=[round(bb.min.X, 3), round(bb.min.Y, 3)],
               max=[round(bb.max.X, 3), round(bb.max.Y, 3)], area=round(sum(f.area for f in faces), 2))
    for f in faces:
        loops = ck._loops(f, "XY", STEP)
        res["loops"].append(loops)
        corner_wires = [f.outer_wire()]
        for w in f.inner_wires():
            kind, info = _wire_kind(w)
            if kind == "hole":
                res["holes"].append(info)
            elif kind == "slot":
                res["slots"].append(info)
            else:
                res["cutouts"] += 1
                corner_wires.append(w)
        res["arcs"] += _arcs(f, corner_wires)
        res["sharp_inside"] += _sharp_inside(loops)
    return res


# ---------------------------------------------------------------------------------------------
# Checks


def check(shape, settings, name: str = "sketch", feats: dict | None = None) -> list[Finding]:
    """The sketch checks: one closed region, the narrowest neck, inside corners, small holes, the bed."""
    from build123d import Wire

    if not hasattr(shape, "faces") or not shape.faces():
        wires = shape.wires() if hasattr(shape, "wires") else []
        if wires and not all(w.is_closed for w in wires):
            w = next(w for w in wires if not w.is_closed)
            a, b = w.start_point(), w.end_point()
            why = (f"the outline is open: its ends ({a.X:g}, {a.Y:g}) and ({b.X:g}, {b.Y:g}) are {(a - b).length:.3g} mm "
                   "apart. Close it (FilletPolyline(..., close=True), or end on the first point), then make_face it")
        elif wires or isinstance(shape, Wire):
            why = "a closed wire, not a face: make_face(wire) turns it into the region to extrude"
        else:
            why = "no face: return the outline as a face (make_face(FilletPolyline(..., close=True)))"
        return [Finding(FAIL, "region", name, why)]
    f = feats or features(shape)
    out = []
    if f["faces"] != 1:
        out.append(Finding(FAIL, "region", name, f"{f['faces']} separate regions: a sketch is one closed region. "
                           "Join them (a bridge of material), or return each as its own sketch"))
    else:
        out.append(Finding(OK, "region", name, f"one closed region, {f['size'][0]:g} x {f['size'][1]:g} mm, "
                           f"{f['area']:g} mm^2"))
    lw = ck.line_width(settings)
    neck = None
    for loops in f["loops"]:
        cand = ck._face_thinnest(loops, None, None, None, ())
        if cand is not None and np.isfinite(cand["min"]) and (neck is None or cand["min"] < neck["min"]):
            neck = cand
    if neck is not None:
        w, at = round(neck["min"], 2), [round(x, 2) for x in neck["at"]]
        data = {"min": w, "at": at, "how": neck["how"]}
        if neck.get("taper") and w < settings.min_wall:
            out.append(Finding(WARN, "neck", name, f"tapers to a point at {tuple(at)} ({w:g} mm where it ends): the tip "
                               "does not print as modeled (BP-R3); blunt it or round it where it matters", data))
        elif w < settings.min_wall:
            out.append(Finding(FAIL if w < lw else WARN, "neck", name,
                               f"narrowest neck {w:g} mm at {tuple(at)} ({neck['how']}), under min_wall {settings.min_wall:g}"
                               + (f" and one line width {lw:g}: it does not print as drawn" if w < lw else ": weak there"), data))
        else:
            out.append(Finding(OK, "neck", name, f"narrowest neck {w:g} mm at {tuple(at)} ({neck['how']}); "
                               f"min_wall {settings.min_wall:g}", data))
    tight = [a for a in f["arcs"] if a["inside"] and a["r"] < INSIDE_R]
    sharp = f["sharp_inside"]
    if tight or sharp:
        where = [f"sharp at {tuple(p)}" for p in sharp[:4]] + [f"R{a['r']:g} at {tuple(a['at'])}" for a in tight[:4]]
        n = len(tight) + len(sharp)
        out.append(Finding(WARN, "corners", name, f"{n} inside corner(s) under R{INSIDE_R:g}: {'; '.join(where)}"
                           f"{f' (+{n - len(where)} more)' if n > len(where) else ''}. Give inside corners a radius "
                           f"of at least {INSIDE_R:g} mm (more where loaded, BP-R1): a radius per corner in FilletPolyline",
                           {"sharp": sharp, "tight": tight}))
    else:
        ins = [a["r"] for a in f["arcs"] if a["inside"]]
        out.append(Finding(OK, "corners", name, f"inside corners R{min(ins):g} and up" if ins else "no inside corners"))
    small = [h for h in f["holes"] if h["d"] < MIN_HOLE]
    if small:
        where = ", ".join(f"d {h['d']:g} at {tuple(h['center'])}" for h in small[:4])
        out.append(Finding(WARN, "holes", name, f"{len(small)} hole(s) under {MIN_HOLE:g} mm: {where}; too small to "
                           "print round (BP-H5). Drill them, or make them bigger", {"small": small}))
    if settings.printer:
        from .profiles import fits, load_printer

        pr = load_printer(settings.printer)
        ok, why = fits(pr, (f["size"][0], f["size"][1], 0.0))
        out.append(Finding(OK if ok and "turned" not in why else WARN, "bed", name,
                           f"{pr.label or pr.name}, laid flat: {why}"
                           + ("" if ok else ". Split it, or stand it up if it is extruded tall")))
    return out


# ---------------------------------------------------------------------------------------------
# The picture


def _grid_step(span: float) -> float:
    """A major grid step of 1, 2 or 5 x 10^n giving about 8-16 lines across `span`."""
    raw = max(span, 1e-3) / 12
    mag = 10 ** np.floor(np.log10(raw))
    return float(min((s * mag for s in (1, 2, 5, 10)), key=lambda s: abs(np.log(s / raw))))


def _fmt(v: float) -> str:
    return f"{round(v, 2):g}"


class _Labels:
    """Text placed so it overlaps no text placed before: spots around the anchor are tried,
    nearest first; if every spot touches something, the one touching the fewest wins."""

    def __init__(self, fig, ax, unit: float):
        self.fig, self.ax, self.unit, self.boxes = fig, ax, unit, []
        self.renderer = fig.canvas.get_renderer()

    def extent(self, t):
        from matplotlib.text import Annotation, Text

        if isinstance(t, Annotation):
            t.update_positions(self.renderer)  # place the text where xytext says before measuring it
        return Text.get_window_extent(t, self.renderer).padded(3)  # the text alone, not its leader

    def put(self, anchor, text, color="#222222", dist=1.0):
        step = dist * self.unit
        tries = [(dx * k * step, dy * k * step) for k in (1, 2, 3, 4)
                 for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1), (1, 0), (0, 1), (-1, 0), (0, -1))]
        best = None
        for dx, dy in tries:
            t = self.ax.annotate(text, anchor, xytext=(anchor[0] + dx, anchor[1] + dy), textcoords="data", color=color,
                                 fontsize=9, ha="left" if dx > 0 else ("right" if dx < 0 else "center"),
                                 va="bottom" if dy > 0 else ("top" if dy < 0 else "center"),
                                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, lw=0.6, alpha=0.9),
                                 arrowprops=dict(arrowstyle="-", color=color, lw=0.7))
            bb = self.extent(t)
            hits = sum(bb.overlaps(o) for o in self.boxes)
            if hits == 0:
                if best is not None:
                    best[0].remove()
                best = (t, bb, 0)
                break
            if best is None or hits < best[2]:
                if best is not None:
                    best[0].remove()
                best = (t, bb, hits)
            else:
                t.remove()
        self.boxes.append(best[1])
        return best[0]


def _dim_line(ax, a, b, off, text, horizontal: bool, labels: _Labels, color="#333333"):
    """A dimension between a and b (data coords), drawn `off` mm away, with extension lines."""
    (x0, y0), (x1, y1) = a, b
    if horizontal:
        y = off
        ax.plot([x0, x0], [y0, y], color=color, lw=0.5)
        ax.plot([x1, x1], [y1, y], color=color, lw=0.5)
        ax.annotate("", (x0, y), xytext=(x1, y), arrowprops=dict(arrowstyle="<|-|>", color=color, lw=0.8, shrinkA=0, shrinkB=0))
        t = ax.text((x0 + x1) / 2, y, text, ha="center", va="center", fontsize=9, color=color,
                    bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
    else:
        x = off
        ax.plot([x0, x], [y0, y0], color=color, lw=0.5)
        ax.plot([x1, x], [y1, y1], color=color, lw=0.5)
        ax.annotate("", (x, y0), xytext=(x, y1), arrowprops=dict(arrowstyle="<|-|>", color=color, lw=0.8, shrinkA=0, shrinkB=0))
        t = ax.text(x, (y0 + y1) / 2, text, ha="center", va="center", fontsize=9, color=color, rotation=90,
                    bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
    labels.boxes.append(labels.extent(t))


def _ordinates(ax, values, base, at, horizontal: bool, labels: _Labels, color="#555555") -> int:
    """Ordinate dimensions: each distinct value measured from `base`, written at `at` along the
    edge (x values along the top when horizontal, y values along the right side otherwise), with
    a dashed line from each feature. values: [(coord, from_coord)]. A label that would touch the
    one before moves out a row. Returns how many were drawn (0 over MAX_ORDINATES: too busy,
    the result lists the centres instead)."""
    seen = []  # one per distinct value, its line from the feature nearest the edge
    for v, src in sorted(values):
        if seen and abs(v - seen[-1][0]) < 1e-3:
            seen[-1] = (seen[-1][0], max(src, seen[-1][1]))
        else:
            seen.append((v, src))
    if len(seen) > MAX_ORDINATES:
        return 0
    prev = None
    for v, src in seen:
        txt = _fmt(v - base)
        for row in range(4):
            off = at + row * labels.unit * 1.6
            if horizontal:
                t = ax.text(v, off, txt, ha="center", va="bottom", fontsize=8, color=color, rotation=90)
            else:
                t = ax.text(off, v, txt, ha="left", va="center", fontsize=8, color=color)
            bb = labels.extent(t)
            if prev is None or not bb.overlaps(prev) or row == 3:
                break
            t.remove()
        if horizontal:
            ax.plot([v, v], [src, off], color=color, lw=0.5, ls=(0, (3, 3)))
        else:
            ax.plot([src, off], [v, v], color=color, lw=0.5, ls=(0, (3, 3)))
        prev = bb
        labels.boxes.append(bb)
    return len(seen)


def render_sketch(shape, path: str | Path, title: str, findings: list[Finding] = (), size: str = "normal",
                  dims: bool = True, feats: dict | None = None) -> Path:
    """The sketch filled on a mm grid, with its automatic dimensions and the findings marked in red."""
    import matplotlib.patches
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath

    from .render import _size

    small = _size(size) == "small"
    f = feats or features(shape)
    fig, ax = plt.subplots(figsize=(8, 6.4) if small else (11, 8.6))
    if not f["faces"]:
        ax.text(0.5, 0.5, "no closed region to draw (see the region check)", transform=ax.transAxes, ha="center")
        ax.set_axis_off()
        fig.savefig(path, dpi=100)
        plt.close(fig)
        return Path(path)
    for loops in f["loops"]:
        verts = np.concatenate([np.vstack([lp, lp[:1]]) for lp in loops])
        codes = np.concatenate([[MPath.MOVETO] + [MPath.LINETO] * (len(lp) - 1) + [MPath.CLOSEPOLY] for lp in loops])
        ax.add_patch(matplotlib.patches.PathPatch(MPath(verts, codes), facecolor=FILL, alpha=0.35, edgecolor=EDGE, lw=1.2))
    (x0, y0), (x1, y1) = f["min"], f["max"]
    w, h = x1 - x0, y1 - y0
    span = max(w, h)
    pad = 0.28 * span if dims else 0.08 * span
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    major = _grid_step(span + 2 * pad)
    ax.xaxis.set_major_locator(plt.MultipleLocator(major))
    ax.yaxis.set_major_locator(plt.MultipleLocator(major))
    ax.xaxis.set_minor_locator(plt.MultipleLocator(major / (5 if major in (1, 10, 100) or major < 1 else 4)))
    ax.yaxis.set_minor_locator(plt.MultipleLocator(major / (5 if major in (1, 10, 100) or major < 1 else 4)))
    ax.grid(which="major", alpha=0.35)
    ax.grid(which="minor", alpha=0.12)
    ax.set_axisbelow(True)
    a, b = f["axes"][0], f["axes"][1]
    ax.set_xlabel(f"{a} (mm), grid {_fmt(major)} mm")
    ax.set_ylabel(f"{b} (mm)")
    fig.canvas.draw()
    labels = _Labels(fig, ax, 0.05 * span)
    if dims:
        gap = 0.1 * span
        _dim_line(ax, (x0, y0), (x1, y0), y0 - gap, _fmt(w), True, labels)
        _dim_line(ax, (x0, y0), (x0, y1), x0 - gap, _fmt(h), False, labels)
        ax.plot([x0], [y0], marker="o", ms=5, color="#333333")
        ax.annotate("datum", (x0, y0), xytext=(-4, -4), textcoords="offset points", ha="right", va="top", fontsize=7,
                    color="#333333")
        centres = [(hh["center"], hh) for hh in f["holes"]] + [(c, s) for s in f["slots"] for c in s["centers"]]
        notes = ["centres from the datum (lower-left corner)"] if centres else []
        if centres:
            nx = _ordinates(ax, [(c[0], c[1]) for c, _ in centres], x0, y1 + 0.06 * span, True, labels)
            ny = _ordinates(ax, [(c[1], c[0]) for c, _ in centres], y0, x1 + 0.06 * span, False, labels)
            if not (nx and ny):
                notes[0] = "too many centres to dimension here: they are listed in the result"
        outside = sorted({arc["r"] for arc in f["arcs"] if not arc["inside"]})
        if outside:
            n = sum(1 for arc in f["arcs"] if not arc["inside"])
            notes.append(f"outside corners: {n}× " + ", ".join(f"R{_fmt(r)}" for r in outside))
        if notes:
            ax.text(0.0, -0.08, ";  ".join(notes), transform=ax.transAxes, fontsize=8, color="#555555", va="top")
        for c, _ in centres:
            r = 0.03 * span
            ax.plot([c[0] - r, c[0] + r], [c[1], c[1]], color="#555555", lw=0.6)
            ax.plot([c[0], c[0]], [c[1] - r, c[1] + r], color="#555555", lw=0.6)
        groups: dict = {}
        for hh in f["holes"]:
            groups.setdefault(hh["d"], []).append(hh)
        for dia, hs in groups.items():
            c = hs[0]["center"]
            anchor = (c[0] + dia / 2 * 0.7071, c[1] + dia / 2 * 0.7071)
            labels.put(anchor, (f"{len(hs)}× " if len(hs) > 1 else "") + f"⌀{_fmt(dia)}")
        sgroups: dict = {}
        for s in f["slots"]:
            sgroups.setdefault((s["width"], s["length"]), []).append(s)
        for (sw, sl), ss in sgroups.items():
            c = ss[0]["centers"][0]
            labels.put((c[0], c[1] + sw / 2), (f"{len(ss)}× " if len(ss) > 1 else "") + f"slot {_fmt(sw)} wide, "
                       f"{_fmt(sl)} c-c")
        rgroups: dict = {}
        for arc in f["arcs"]:
            if arc["inside"]:
                rgroups.setdefault(arc["r"], []).append(arc)
        for r, arcs in rgroups.items():
            labels.put(tuple(arcs[0]["at"]), (f"{len(arcs)}× " if len(arcs) > 1 else "") + f"R{_fmt(r)}", dist=0.8)
    for fd in findings:
        if fd.level == OK:
            continue
        if fd.check == "neck" and "at" in fd.data:
            ax.plot(*fd.data["at"], marker="o", ms=10, mfc="none", mec=MARK, mew=1.5)
            labels.put(tuple(fd.data["at"]), f"neck {_fmt(fd.data['min'])}", color=MARK)
        if fd.check == "corners":
            for p in fd.data.get("sharp", []) + [t["at"] for t in fd.data.get("tight", [])]:
                ax.plot(*p, marker="o", ms=9, mfc="none", mec=MARK, mew=1.5)
        if fd.check == "holes":
            for hh in fd.data.get("small", []):
                ax.plot(*hh["center"], marker="o", ms=11, mfc="none", mec=MARK, mew=1.5)
    worst = "FAIL" if any(x.level == FAIL for x in findings) else ("WARN" if any(x.level == WARN for x in findings) else "OK")
    ax.set_title(f"{title}: {_fmt(w)} x {_fmt(h)} mm ({a}{b})" + (f"   checks: {worst}" if findings else ""))
    fig.savefig(path, dpi=67 if small else 100, bbox_inches="tight")
    plt.close(fig)
    return Path(path)


# ---------------------------------------------------------------------------------------------
# One call: the hook, the checks, the picture


def sketch_report(mod: ModuleType, d, name: str | None, out: Path, tag: str, settings, size: str = "normal",
                  dims: bool = True) -> dict:
    """Make sketch `name` of sketches(d), check it and draw it into out/images/. Returns
    {"sketch", "sketches", "image", "features", "findings"}."""
    from . import outdir

    sk = Sketches(mod, d)
    name = name or sk.names()[0]
    shape = sk.get(name)
    has_face = hasattr(shape, "faces") and bool(shape.faces())
    feats = features(shape) if has_face else None
    findings = check(shape, settings, name, feats)
    small = "_small" if size == "small" else ""
    img = render_sketch(shape, outdir.path(out, f"{tag}_sketch_{name}{small}.png"), f"{tag}: sketch {name}", findings,
                        size, dims, feats or {"faces": 0})
    brief = None
    if feats:
        brief = {k: v for k, v in feats.items() if k not in ("loops", "arcs")}
        brief["inside_radii"] = sorted({a["r"] for a in feats["arcs"] if a["inside"]})
        brief["outside_radii"] = sorted({a["r"] for a in feats["arcs"] if not a["inside"]})
    return {"sketch": name, "sketches": sk.names(), "image": str(img), "features": brief,
            "findings": [ck_dict(x) for x in findings]}


def ck_dict(f: Finding) -> dict:
    return {"level": f.level, "check": f.check, "target": f.target, "message": f.message}


def text(res: dict) -> str:
    """The sketch result as lines for the CLI and the MCP tool."""
    lines = [f"sketch {res['sketch']} (sketches: {', '.join(res['sketches'])}): {res['image']}"]
    ft = res.get("features")
    if ft:
        lines.append(f"  size {_fmt(ft['size'][0])} x {_fmt(ft['size'][1])} mm in {ft['axes']}, lower-left corner "
                     f"({_fmt(ft['min'][0])}, {_fmt(ft['min'][1])}), area {ft['area']:g} mm^2")
        for hh in ft["holes"]:
            lines.append(f"  hole d {hh['d']:g} at ({_fmt(hh['center'][0])}, {_fmt(hh['center'][1])})")
        for s in ft["slots"]:
            lines.append(f"  slot {s['width']:g} wide, {s['length']:g} c-c, centres {s['centers'][0]} {s['centers'][1]}")
        if ft["cutouts"]:
            lines.append(f"  {ft['cutouts']} other cutout(s)")
        if ft["inside_radii"] or ft["outside_radii"]:
            lines.append(f"  corner radii: inside {ft['inside_radii'] or '-'}, outside {ft['outside_radii'] or '-'}")
    for x in res["findings"]:
        lines.append(f"[{x['level'].upper():4}] {x['check']:8} {x['target']}: {x['message']}")
    return "\n".join(lines)


__all__ = ["SketchError", "Sketches", "check", "features", "flatten", "render_sketch", "sketch_report", "text", "OK", "WARN", "FAIL"]
