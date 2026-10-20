"""Motion clearance: a piece of assembly(d) swept through its motion against the others.

Hinges, flip lids, latches and sliders can collide part-way through their motion even when the
closed and open positions are clear. `Motion` turns a piece about an axis between two angles,
`Slide` moves it along a direction; both are declared in `checks(d)` and run with `check`.

The sweep, per motion:

1. coarse: `samples` steps over the range, each pose measured against every `against` piece
   with measure.distance (the gap and closest points, or the interference volume). Pairs whose
   bounding boxes are further apart than anything that matters skip the exact measurement
   (the box gap is a lower bound);
2. refine where a collision could hide: an interval whose two ends are clear but closer than
   the farthest point of the piece travels in it is split (most suspicious first);
3. bisect the first contact (the angle or position where the interference starts), or, with no
   collision, close in on the smallest clearance.

Evaluations are capped (`max_evals`), so a motion costs about max_evals x one distance call.
The result: the smallest clearance and where (angle or position, the pair, the point), the first
contact and the interference volume at the worst pose, and, when run by `check`, a picture of
the worst pose (render and section, out/<script>[_<variant>]_motion_<piece>.png).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from build123d import Axis, Pos

from .checks import FAIL, OK, Finding, _bbox_gap
from .fit import CONTACT
from .measure import distance

COLORS = {"moving": "#3a6ea5", "fixed": "#9aa0a6", "start": "#3a6ea540", "hit": "#d62728"}


def _vec(v) -> np.ndarray:
    return np.array([v.X, v.Y, v.Z], float) if hasattr(v, "X") else np.asarray(v, float).reshape(3)


def _corners(shape) -> np.ndarray:
    bb = shape.bounding_box()
    lo, hi = _vec(bb.min), _vec(bb.max)
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])


def _pieces(spec, assembly) -> tuple[list, list]:
    """([(shape, label)] moving, [(shape, label)] fixed) from assembly(d) by label."""
    if not assembly:
        raise KeyError(f"{type(spec).__name__} needs assembly(d): it moves the pieces as placed there")
    labels = [lbl for _, _, lbl in assembly]
    names = [spec.part] if isinstance(spec.part, str) else list(spec.part)
    missing = [n for n in names + list(spec.against) if n not in labels]
    if missing:
        raise KeyError(f"no assembly piece labeled {missing}; labels: {labels}")
    moving = [(p, lbl) for p, _, lbl in assembly if lbl in names]
    fixed = [(p, lbl) for p, _, lbl in assembly if lbl not in names and (not spec.against or lbl in spec.against)]
    return moving, fixed


class _Sweep:
    """Poses t in [t0, t1] of `moving`, measured against `fixed` (see the module doc)."""

    def __init__(self, moving, fixed, pose, travel: float, tol: float, need: float):
        self.moving, self.fixed, self.pose = moving, fixed, pose
        self.travel, self.tol, self.need = travel, tol, need  # travel: mm the farthest point moves per unit of t
        self.done: dict[float, dict] = {}
        self.best = math.inf  # smallest exact clearance so far

    def at(self, t: float) -> dict:
        t = round(float(t), 6)
        if t in self.done:
            return self.done[t]
        r = {"t": t, "clearance": math.inf, "volume": 0.0, "pair": None, "where": None, "exact": True}
        cutoff = max(self.best, self.need)
        for shape, name in self.moving:
            m = self.pose(shape, t)
            for other, oname in self.fixed:
                g = _bbox_gap(m, other)
                if g > cutoff:  # a lower bound, above anything reported: no exact measurement
                    if g < r["clearance"]:
                        r.update(clearance=g, pair=[name, oname], where=None, exact=False)
                    continue
                d = distance(m, other)
                if d["overlap"]:
                    if d["interference_volume"] > self.tol:
                        if d["interference_volume"] > r["volume"]:
                            r.update(where=d["interference_center"], box=d["interference_box"], hit=[name, oname])
                        r["volume"] += d["interference_volume"]
                    g, where = 0.0, d["interference_center"]
                else:
                    g, where = d["distance"], [round((a + b) / 2, 3) for a, b in zip(*d["points"])]
                if g < r["clearance"] or (g == r["clearance"] and not r["exact"]):
                    r.update(clearance=g, pair=[name, oname], exact=True)
                    if not r["volume"]:
                        r["where"] = where
        if r["exact"] and r["volume"] <= 0:
            self.best = min(self.best, r["clearance"])
        self.done[t] = r
        return r

    def hit(self, t: float) -> bool:
        return self.at(t)["volume"] > 0

    def sorted(self) -> list[dict]:
        return [self.done[t] for t in sorted(self.done)]


def sweep(moving, fixed, pose, t0: float, t1: float, travel: float, samples: int = 24, max_evals: int = 96,
          tol: float = 0.01, need: float = 0.0, res: float = 0.01) -> dict:
    """Sample poses t0..t1 coarsely, refine (see the module doc). travel: how far (mm) the
    piece's farthest point moves per unit of t; res: stop refining below this travel (mm).
    Returns {"poses": [...], "first": pose or None, "worst": pose, "min": pose, "evals", "step"}."""
    sw = _Sweep(moving, fixed, pose, travel, tol, need)
    n = max(2, int(samples))
    for t in np.linspace(t0, t1, n + 1):
        sw.at(t)
    span = abs(t1 - t0) or 1.0

    def gaps():  # intervals that could hide a collision: both ends clear, closer than the travel between them
        out = []
        ps = sw.sorted()
        for a, b in zip(ps, ps[1:]):
            if a["volume"] or b["volume"]:
                continue
            move = travel * (b["t"] - a["t"])
            if move > res and min(a["clearance"], b["clearance"]) < move / 2:
                out.append((min(a["clearance"], b["clearance"]) / move, a["t"], b["t"]))
        return sorted(out)

    while len(sw.done) < max_evals and not any(p["volume"] for p in sw.done.values()):
        todo = gaps()
        if not todo:
            break
        for _, a, b in todo[: max(1, (max_evals - len(sw.done)) // 2)]:
            sw.at((a + b) / 2)
            if len(sw.done) >= max_evals:
                break
    first = None
    hits = [p for p in sw.sorted() if p["volume"]]
    if hits:
        ps = sw.sorted()
        i = next(k for k, p in enumerate(ps) if p["volume"])
        if i == 0:
            first = ps[0]
        else:
            lo, hi = ps[i - 1]["t"], ps[i]["t"]
            while travel * abs(hi - lo) > res and len(sw.done) < max_evals + 12:
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if sw.hit(mid) else (mid, hi)
            first = sw.at(hi)
    else:  # close in on the smallest clearance: halve the step around the best pose
        best = min(sw.done.values(), key=lambda p: p["clearance"])
        step = span / n
        while step * travel > res and len(sw.done) < max_evals + 12:
            step /= 2
            for t in (best["t"] - step, best["t"] + step):
                if min(t0, t1) <= t <= max(t0, t1):
                    sw.at(t)
            best = min(sw.done.values(), key=lambda p: p["clearance"])
    ps = sw.sorted()
    ts = [p["t"] for p in ps]
    mn = min(ps, key=lambda p: (p["clearance"], -p["volume"]))
    worst = max(ps, key=lambda p: p["volume"]) if hits else mn
    return {"poses": ps, "first": first, "worst": worst, "min": mn, "evals": len(ps),
            "step": round(max(abs(b - a) for a, b in zip(ts, ts[1:])) if len(ts) > 1 else 0.0, 4)}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower() or "piece"


class _Swept:
    """What Motion and Slide share: the sweep, the findings and the picture."""

    unit = ""
    kind = ""

    def _setup(self, moving):  # -> (pose(shape, t), t0, t1, mm the farthest point moves per unit of t)
        raise NotImplementedError

    def _fmt(self, t: float) -> str:
        return f"{t:.4g}{self.unit}"

    @property
    def cost(self) -> float:
        """Seconds, roughly, for the check runner to balance its workers (item_cost)."""
        return 0.06 * self.max_evals + (3.0 if self.image else 0.0)

    def _name(self) -> str:
        name = self.part if isinstance(self.part, str) else " + ".join(self.part)
        return f"{name} ({self.label})" if self.label else name

    def run(self, parts, assembly, settings) -> list[Finding]:
        moving, fixed = _pieces(self, assembly)
        tgt = self._name()
        if not fixed:
            return [Finding(OK, "motion", tgt, "nothing to move against (against= names no other piece)")]
        pose, t0, t1, travel = self._setup(moving)
        need = self.min_clearance if self.min_clearance is not None else 0.0
        res = sweep(moving, fixed, pose, t0, t1, travel, self.samples, self.max_evals, self.tol, need)
        rng = f"{self._fmt(t0)}..{self._fmt(t1)}"
        mn, worst, first = res["min"], res["worst"], res["first"]
        data = {"kind": self.kind, "range": [t0, t1], "unit": self.unit or "mm", "evals": res["evals"],
                "max_step": res["step"], "min_clearance": round(mn["clearance"], 4), "min_at": mn["t"],
                "min_pair": mn["pair"], "min_where": mn["where"],
                "curve": [[p["t"], round(p["clearance"], 4) if not p["volume"] else -round(p["volume"], 4)]
                          for p in res["poses"]][:200]}
        sampled = f"{res['evals']} poses, steps up to {self._fmt(res['step'])}"
        if first is not None:
            data.update(first_contact=first["t"], first_pair=first.get("hit"), volume=round(worst["volume"], 4),
                        worst_at=worst["t"], worst_where=worst["where"], interference_box=worst.get("box"))
            a, b = first.get("hit") or first["pair"]
            msg = (f"{a} hits {b} at {self._fmt(first['t'])} (moving {rng}); interference {worst['volume']:.3f} mm^3 "
                   f"at {self._fmt(worst['t'])} around {tuple(worst['where'] or ())}. Free it: more clearance there, "
                   f"a chamfer or a rounded corner on the piece, or a smaller range ({sampled})")
            found = Finding(FAIL, "motion", tgt, msg, data)
        else:
            where = f" at {tuple(mn['where'])}" if mn["where"] else ""
            pair = " / ".join(mn["pair"] or ())
            what = ("touches (no overlap)" if mn["clearance"] < CONTACT else f"smallest clearance {mn['clearance']:.3f} mm")
            msg = f"clears through {rng}: {what} at {self._fmt(mn['t'])} ({pair}{where}; {sampled})"
            if self.min_clearance is not None and mn["clearance"] < self.min_clearance - 1e-3:
                found = Finding(FAIL, "motion", tgt, msg.replace("clears through", "moves through") +
                                f": under min_clearance {self.min_clearance:g} mm, it binds or fuses there", data)
            else:
                found = Finding(OK, "motion", tgt, msg + (f" (min {self.min_clearance:g})" if self.min_clearance else ""), data)
        if self.image:
            try:
                found.data["images"] = self._pictures(moving, fixed, pose, t0, worst, first is not None)
                found.message += f"; picture: {' and '.join(Path(p).name for p in found.data['images'])}"
            except Exception as e:  # noqa: BLE001 - the numbers stand without the picture
                found.data["image_error"] = repr(e)
        return [found]

    def _pictures(self, moving, fixed, pose, t0, worst, hit) -> list[str]:
        """The worst pose rendered (the piece at its start see-through) and a section through
        the worst point, across the motion."""
        from .render import render, section_view

        t = worst["t"]
        items = [(o, COLORS["fixed"], lbl) for o, lbl in fixed]
        items += [(pose(s, t0), COLORS["start"], f"{lbl} at {self._fmt(t0)}") for s, lbl in moving if t != t0]
        items += [(pose(s, t), COLORS["moving"], f"{lbl} at {self._fmt(t)}") for s, lbl in moving]
        if hit:
            hits = [m & o for s, _ in moving for o, _ in fixed for m in [pose(s, t)]]
            items += [(h, COLORS["hit"], "interference") for h in hits if h is not None and h.volume > self.tol]
        path = Path(self.image)
        path.parent.mkdir(parents=True, exist_ok=True)
        title = f"{self._name()}: {'collides' if hit else 'closest'} at {self._fmt(t)}"
        out = [str(render(items, path, title, size="small"))]
        if worst["where"]:
            axis = int(np.argmax(np.abs(self._across())))
            plane = ("YZ", "XZ", "XY")[axis]
            out.append(str(section_view([i for i in items if not i[1].endswith("40")], plane, worst["where"][axis],
                                        path.with_name(path.stem + "_section.png"), title, size="small")))
        return out


@dataclass
class Motion(_Swept):
    """A piece of assembly(d) turned about an axis from start_deg to end_deg (right-hand rule
    about axis_dir), against the other pieces (or those named in `against`), stand-ins included.
    Fails on any interference (reports the first contact angle and the volume), and below
    min_clearance when given; else reports the smallest clearance and its angle. part: an
    assembly label, or a tuple of labels that move together."""

    part: object
    axis_point: tuple = (0.0, 0.0, 0.0)  # a point on the axis, assembly coordinates
    axis_dir: tuple = (1.0, 0.0, 0.0)
    start_deg: float = 0.0
    end_deg: float = 90.0
    against: tuple = ()  # assembly labels; empty: every other piece
    min_clearance: float | None = None  # mm; None: only interference fails
    samples: int = 24  # coarse steps over the range
    max_evals: int = 96  # cap on poses measured (each is one distance call per pair)
    tol: float = 0.01  # mm^3 of interference that counts
    label: str = ""
    image: str | None = None  # where the worst pose is drawn; `check` fills it in (out/...), "" for none

    unit = " deg"
    kind = "rotation"

    def _setup(self, moving):
        ax = Axis(tuple(self.axis_point), tuple(self.axis_dir))
        p0, u = _vec(self.axis_point), _vec(self.axis_dir) / np.linalg.norm(_vec(self.axis_dir))
        r = 0.0
        for s, _ in moving:  # the farthest bounding-box corner from the axis bounds every point's radius
            v = _corners(s) - p0
            r = max(r, float(np.max(np.linalg.norm(v - np.outer(v @ u, u), axis=1))))
        return (lambda s, t: s.rotate(ax, t)), float(self.start_deg), float(self.end_deg), r * math.pi / 180

    def _across(self):
        return _vec(self.axis_dir)


@dataclass
class Slide(_Swept):
    """A piece of assembly(d) moved `distance` mm along `direction` (from `start` mm), against
    the other pieces (or those in `against`): a drawer, a sliding lid, a latch bolt. Fails on
    any interference (reports where it jams and the volume) and below min_clearance when given."""

    part: object
    direction: tuple = (1.0, 0.0, 0.0)
    distance: float = 10.0  # mm along direction
    start: float = 0.0  # mm along direction where the motion begins
    against: tuple = ()
    min_clearance: float | None = None
    samples: int = 24
    max_evals: int = 96
    tol: float = 0.01
    label: str = ""
    image: str | None = None

    unit = " mm"
    kind = "translation"

    def _setup(self, moving):
        u = _vec(self.direction) / np.linalg.norm(_vec(self.direction))
        return (lambda s, t: Pos(*(u * t)) * s), float(self.start), float(self.start + self.distance), 1.0

    def _across(self):
        # the section plane: the one the slide direction lies in most (its normal least along it)
        u = np.abs(_vec(self.direction))
        n = np.zeros(3)
        n[int(np.argmin(u))] = 1.0
        return n


def image_path(out: Path, prefix: str, spec) -> Path:
    """out/<prefix>_motion_<piece>[_<label>].png: where `check` draws a motion's worst pose."""
    name = spec.part if isinstance(spec.part, str) else "_".join(spec.part)
    tail = _slug(name) + (f"_{_slug(spec.label)}" if spec.label else "")
    return out / f"{prefix}_motion_{tail}.png"
