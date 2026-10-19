"""Fit between pieces: how the pieces of an assembly meet.

Two checks on the parts of `assembly(d)` as placed (printed pieces and stand-ins alike):

- interference: pairs that overlap (FAIL, with the overlap volume and where), and pairs closer
  than the clearance without touching (WARN: a sliding fit that will bind). Faces resting on
  each other (gap 0, no overlap) are contact, not interference. Two stand-ins are never paired.
  A male/female joint pair (see `joint_pairs`) is an intentional fit: its gap must be at least
  the joint's clearance (FAIL below it).
- hole alignment: round holes (checks.holes) of two pieces on parallel axes that meet across
  the pieces' faces are partners. Partners off-axis by more than `hole_tol` fail; partner
  diameters are read as screw holes (clearance, pilot/tap, heat-set insert; the configured
  hole_comp taken off first) and a pair no single screw size explains warns. A hole whose axis
  runs into solid material of the next printed piece, with no hole there, has no partner (WARN;
  not against stand-ins, which are simplified and usually have no holes).

Pairs are pre-filtered on bounding boxes and capped (`max_pairs`, nearest first), so the check
stays fast on big assemblies. Used by the `Mates` check spec and the `check_fit` tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from build123d import Part, Vector

from .checks import FAIL, OK, WARN, Finding, Overlap, _bbox_gap, holes

STANDIN_RE = re.compile(r"stand[- ]?in|dummy|\(ref\)", re.I)
CONTACT = 1e-3  # mm: closer than this is touching
REACH = 2.0  # mm: how far past a hole's end its partner (or the next piece's material) is looked for

# Metric screw holes (mm, printed size): pilot for thread-forming screws (BP-T6, M3 2.6-2.9),
# clearance (ISO 273 fine..medium, plus print slack), heat-set insert holes (CNC Kitchen's
# insert table, BP-T2: M3 4.0). Ranges are inclusive; a hole may read as more than one kind.
SCREWS = {
    "M2": {"pilot": (1.5, 1.85), "clearance": (2.2, 2.6), "insert": (3.1, 3.3)},
    "M2.5": {"pilot": (2.0, 2.35), "clearance": (2.7, 3.1), "insert": (3.5, 3.7)},
    "M3": {"pilot": (2.5, 2.95), "clearance": (3.2, 3.7), "insert": (3.9, 4.3)},
    "M4": {"pilot": (3.3, 3.75), "clearance": (4.3, 4.9), "insert": (5.5, 5.8)},
    "M5": {"pilot": (4.2, 4.65), "clearance": (5.3, 5.9), "insert": (6.3, 6.6)},
    "M6": {"pilot": (5.0, 5.45), "clearance": (6.4, 7.0), "insert": (7.9, 8.2)},
}


def hole_kinds(d: float) -> list[tuple[str, str]]:
    """[(size, kind)] a printed hole diameter fits: [('M3', 'clearance'), ('M2.5', 'insert')]."""
    return [(m, k) for m, kinds in SCREWS.items() for k, (lo, hi) in kinds.items() if lo - 1e-6 <= d <= hi + 1e-6]


def _kinds_text(d: float) -> str:
    k = hole_kinds(d)
    return " or ".join(f"{m} {kind}" for m, kind in k) if k else "no standard screw hole"


def screw_pair(d1: float, d2: float) -> str | None:
    """How two partner holes take one screw, or None: one must let the screw through (clearance);
    the other holds it (pilot, insert) or is a clearance hole too (a bolt and nut)."""
    a, b = hole_kinds(d1), hole_kinds(d2)
    best = None
    for m, ka in a:
        for m2, kb in b:
            if m != m2 or "clearance" not in (ka, kb):
                continue
            other = kb if ka == "clearance" else ka
            how = {"pilot": "screwed into the pilot hole", "insert": "into a heat-set insert",
                   "clearance": "through both (bolt and nut)"}[other]
            text = f"{m}: clearance + {other}, {how}"
            if best is None or other != "clearance":  # a fastening pair beats a through pair
                best = text
    return best


def is_standin(label: str, printed: set[str]) -> bool:
    """A stand-in: labeled so ('board (stand-in)', 'dummy'), or matching no printed piece."""
    if STANDIN_RE.search(label or ""):
        return True
    return bool(printed) and _norm(label) not in printed


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", (s or "").lower())


def joint_pairs(specs) -> dict[frozenset, dict]:
    """Male/female joint pairs as {frozenset(labels): {"male", "female", "clearance"}}. Each item:
    a tuple (male, female) or (male, female, clearance), a dict with those keys, or an object
    with `male`/`female` (or `a`/`b`) attributes and an optional `clearance` (per side): the
    joints module's pairs are read the same way."""
    out = {}
    for j in specs or ():
        if isinstance(j, (tuple, list)):
            m, f, c = (list(j) + [None])[:3]
        elif isinstance(j, dict):
            m, f, c = j.get("male", j.get("a")), j.get("female", j.get("b")), j.get("clearance")
        else:
            m = getattr(j, "male", getattr(j, "a", None))
            f = getattr(j, "female", getattr(j, "b", None))
            c = getattr(j, "clearance", None)
        if m is None or f is None:
            raise ValueError(f"joint {j!r}: needs a male and a female label")
        out[frozenset((str(m), str(f)))] = {"male": str(m), "female": str(f), "clearance": c}
    return out


def _p(v) -> list[float]:
    return [round(float(x), 2) for x in (v.X, v.Y, v.Z)] if isinstance(v, Vector) else [round(float(x), 2) for x in v]


def _closest(a: Part, b: Part):
    """(distance, midpoint of the closest points)."""
    try:
        dist, pa, pb = a.distance_to_with_closest_points(b)
        return float(dist), _p((pa + pb) / 2)
    except Exception:  # noqa: BLE001 - a shape OCC cannot measure: the distance alone
        return float(a.distance_to(b)), None


def interference(items: list[tuple[Part, str, bool]], clearance: float, joints: dict, tol: float = 0.01,
                 ignore=(), max_pairs: int = 60) -> list[Finding]:
    """items: [(part, label, standin)]. One finding per pair that is close (see module doc)."""
    skip = {frozenset(p) for p in ignore}
    cands = []
    for (a, an, sa), (b, bn, sb) in combinations(items, 2):
        if (sa and sb) or frozenset((an, bn)) in skip:
            continue
        j = joints.get(frozenset((an, bn)))
        need = (j["clearance"] if j and j["clearance"] is not None else clearance)
        g = _bbox_gap(a, b)
        if g <= need + CONTACT:
            cands.append((g, a, an, b, bn, j, need))
    cands.sort(key=lambda c: c[0])
    out = []
    if len(cands) > max_pairs:
        out.append(Finding(WARN, "mate", "assembly", f"{len(cands)} close pairs; checked the {max_pairs} nearest "
                           "(raise max_pairs to check them all)"))
    for _, a, an, b, bn, j, need in cands[:max_pairs]:
        tgt = f"{an} / {bn}" + (" (joint)" if j else "")
        common = a & b
        v = float(common.volume) if common is not None else 0.0
        if v > tol:
            bb = common.bounding_box()
            where = _p(bb.center())
            size = _p(bb.size)
            out.append(Finding(FAIL, "mate", tgt, f"overlap {v:.3f} mm^3 around {tuple(where)} (extent "
                               f"{size[0]:g} x {size[1]:g} x {size[2]:g} mm)",
                               {"volume": round(v, 4), "where": where, "extent": size, "pair": [an, bn]}))
            continue
        g, where = _closest(a, b)
        at = f" at {tuple(where)}" if where else ""
        data = {"gap": round(g, 4), "where": where, "pair": [an, bn], "clearance": need}
        if j:
            if g < CONTACT:
                out.append(Finding(OK, "mate", tgt, f"joint shoulders touch{at}; the joint's own gap is not measured "
                                   "where faces rest on each other", data))
            elif g < need - 0.01:
                out.append(Finding(FAIL, "mate", tgt, f"joint gap {g:.3f} mm{at} is under its clearance {need:g} "
                                   "(per side): it will not go together", data))
            else:
                out.append(Finding(OK, "mate", tgt, f"joint gap {g:.3f} mm{at} (clearance {need:g} per side)", data))
        elif g < CONTACT:
            out.append(Finding(OK, "mate", tgt, f"touch{at} (faces resting on each other, no overlap)", data))
        elif g < need - 0.01:
            out.append(Finding(WARN, "mate", tgt, f"gap {g:.3f} mm{at} is under the clearance {need:g} mm per side: "
                               "a sliding fit binds there, a fixed one is fine", data))
        else:
            out.append(Finding(OK, "mate", tgt, f"gap {g:.3f} mm{at}", data))
    return out


def _ends(h) -> tuple[np.ndarray, np.ndarray]:
    ax = np.asarray(h["axis"], float)
    c = np.asarray(h["center"], float)
    return c - ax * h["length"] / 2, c + ax * h["length"] / 2


def _axis_offset(h1, h2) -> float:
    """Distance between two parallel hole axes."""
    ax = np.asarray(h1["axis"], float)
    dv = np.asarray(h2["center"], float) - np.asarray(h1["center"], float)
    return float(np.linalg.norm(dv - np.dot(dv, ax) * ax))


def _axial_gap(h1, h2) -> float:
    """How far apart two holes on (near) the same axis are along it (0 when they overlap)."""
    ax = np.asarray(h1["axis"], float)
    t1 = sorted(float(np.dot(p, ax)) for p in _ends(h1))
    t2 = sorted(float(np.dot(p, ax)) for p in _ends(h2))
    return max(0.0, t2[0] - t1[1], t1[0] - t2[1])


def _solid_beyond(h, other: Part, reach: float = REACH) -> list | None:
    """A point just past either end of hole h, on its axis, inside `other`; else None."""
    ax = np.asarray(h["axis"], float)
    lo, hi = _ends(h)
    for end, sign in ((lo, -1), (hi, 1)):
        for t in (0.3, 0.8, reach):
            p = end + sign * ax * t
            try:
                if other.is_inside(Vector(*p)):
                    return [round(float(x), 2) for x in p]
            except Exception:  # noqa: BLE001
                return None
    return None


def bores(part: Part) -> list[dict]:
    """Round holes (checks.holes) with coaxial ones merged into one bore: a counterbore over its
    clearance hole is one screw hole, whose size is the smallest diameter (what the screw passes)
    and whose extent spans them all. "ds" lists every diameter along it."""
    out: list[dict] = []
    for h in holes(part):
        ax = np.asarray(h["axis"], float)
        for b in out:
            if abs(float(np.dot(ax, b["axis"]))) > 0.999 and _axis_offset(b, h) < 0.02 and _axial_gap(b, h) < 0.05:
                lo = sorted([float(np.dot(p, b["axis"])) for p in (*_ends(b), *_ends(h))])
                c0 = np.asarray(b["center"], float)
                c0 = c0 - np.dot(c0, b["axis"]) * np.asarray(b["axis"], float)
                mid = (lo[0] + lo[-1]) / 2
                b["center"] = [round(float(x), 2) for x in c0 + mid * np.asarray(b["axis"], float)]
                b["length"] = round(lo[-1] - lo[0], 2)
                b["ds"].append(h["d"])
                b["d"] = min(b["d"], h["d"])
                break
        else:
            out.append({"d": h["d"], "ds": [h["d"]], "axis": [float(x) for x in ax], "center": list(h["center"]),
                        "length": h["length"]})
    return out


def alignment(items: list[tuple[Part, str, bool]], hole_tol: float, hole_comp: float = 0.0,
              max_pairs: int = 60) -> list[Finding]:
    """Hole partners across pieces that meet (bounding boxes within REACH); see module doc."""
    found = {lbl: bores(p) for p, lbl, _ in items}
    out = []
    pairs = [(x, y) for x, y in combinations(items, 2) if not (x[2] and y[2]) and _bbox_gap(x[0], y[0]) <= REACH]
    pairs = sorted(pairs, key=lambda xy: _bbox_gap(xy[0][0], xy[1][0]))[:max_pairs]
    for (a, an, sa), (b, bn, sb) in pairs:
        partnered_a, partnered_b = set(), set()
        for i, h1 in enumerate(found[an]):
            ax = np.asarray(h1["axis"], float)
            for k, h2 in enumerate(found[bn]):
                if abs(float(np.dot(ax, h2["axis"]))) < 0.99:
                    continue
                off = _axis_offset(h1, h2)
                if off > max(h1["d"], h2["d"]) / 2 or _axial_gap(h1, h2) > REACH:
                    continue
                partnered_a.add(i)
                partnered_b.add(k)
                d1, d2 = h1["d"] - hole_comp, h2["d"] - hole_comp
                where = [round((x + y) / 2, 2) for x, y in zip(h1["center"], h2["center"])]
                tgt = f"{an} / {bn}"
                desc = f"{an} {d1:.2f} ({_kinds_text(d1)}) over {bn} {d2:.2f} ({_kinds_text(d2)})"
                data = {"offset": round(off, 3), "d": [round(d1, 3), round(d2, 3)], "where": where,
                        "centers": [h1["center"], h2["center"]], "pair": [an, bn]}
                if off > hole_tol:
                    out.append(Finding(FAIL, "align", tgt, f"holes at {tuple(where)} are {off:.2f} mm off-axis "
                                       f"(tolerance {hole_tol:g}): {desc}", data))
                    continue
                how = screw_pair(d1, d2)
                if how or abs(d1 - d2) < 0.05:
                    note = how or "same diameter (a pin or dowel through both)"
                    out.append(Finding(OK, "align", tgt, f"holes at {tuple(where)} line up ({off:.2f} mm): {note}", data))
                else:
                    out.append(Finding(WARN, "align", tgt, f"holes at {tuple(where)} line up ({off:.2f} mm) but "
                                       f"their sizes match no one screw: {desc}. One needs clearance for the screw, "
                                       "the other a pilot, an insert hole or clearance for a nut", data))
        if sa or sb:  # stand-ins are simplified (a board without its holes): no "no partner" on them
            continue
        for lbl, other, olbl, hs, done in ((an, b, bn, found[an], partnered_a), (bn, a, an, found[bn], partnered_b)):
            for i, h in enumerate(hs):
                if i in done:
                    continue
                hit = _solid_beyond(h, other)
                if hit:
                    d = h["d"] - hole_comp
                    out.append(Finding(WARN, "align", f"{lbl} / {olbl}", f"{lbl} hole {d:.2f} mm at {tuple(h['center'])} "
                                       f"has no partner: its axis runs into solid {olbl} at {tuple(hit)}",
                                       {"hole": h["center"], "d": round(d, 3), "solid_at": hit, "pair": [lbl, olbl]}))
    return out


@dataclass
class Mates:
    """Fit between the pieces of assembly(d): interference (overlap, gaps under the clearance)
    and hole alignment across pieces (see b123d_print.fit). Opt-in in checks(d); the check_fit
    tool and `b123d-print fit` run it on any script with an assembly. clearance: per side
    (default the configured clearance); hole_tol: largest axis offset of partner holes, mm;
    joints: male/female pairs that are intentional fits (also read from the script's
    `joints(d)`); ignore: label pairs meant to overlap (a screw stand-in in its pilot hole)."""

    clearance: float | None = None
    hole_tol: float = 0.2
    joints: tuple = ()
    ignore: tuple = ()
    tol: float = 0.01  # mm^3 of overlap that counts
    max_pairs: int = 60
    align: bool = True
    part: str = "assembly"  # for the check runner's labels

    def run(self, parts, assembly, settings) -> list[Finding]:
        if not assembly:
            return [Finding(OK, "mate", "assembly", "no assembly(d): nothing to fit (pieces are only placed in assembly(d))")]
        printed = {_norm(n) for n in parts}
        items = [(p, lbl, is_standin(lbl, printed)) for p, _, lbl in assembly]
        clr = self.clearance if self.clearance is not None else settings.clearance
        out = interference(items, clr, joint_pairs(self.joints), self.tol, self.ignore, self.max_pairs)
        if self.align:
            out += alignment(items, self.hole_tol, settings.hole_comp, self.max_pairs)
        if not any(f.level != OK for f in out):
            n = sum(1 for _, _, s in items if s)
            out.insert(0, Finding(OK, "mate", "assembly", f"{len(items)} items ({n} stand-ins): no interference, "
                                  "holes line up"))
        return out


def fit_report(mod, d, parts: dict, asm, settings, hole_tol: float | None = None) -> list[Finding]:
    """The Mates check for a script: its own Mates spec from checks(d) when it has one, else the
    defaults; joints from the script's `joints(d)` and the pairs an Overlap(ignore=...) allows
    are added."""
    spec, allowed = None, ()
    f = getattr(mod, "checks", None)
    for s in (f(d) if f else []):
        if isinstance(s, Mates):
            spec = s
        elif isinstance(s, Overlap):  # pairs the script already lets overlap (a screw in its pilot hole)
            allowed += tuple(s.ignore)
    spec = spec or Mates()
    if allowed:
        spec = Mates(**{**spec.__dict__, "ignore": tuple(spec.ignore) + allowed})
    j = getattr(mod, "joints", None)
    if j is not None:
        spec = Mates(**{**spec.__dict__, "joints": tuple(spec.joints) + tuple(j(d) if d is not None else j())})
    if hole_tol is not None:
        spec.hole_tol = hole_tol
    named = {(k or "part"): v for k, v in parts.items()}
    return spec.run(named, asm, settings)



def run_fit(mod, key: str, settings, cache=None, hole_tol: float | None = None) -> dict:
    """Build one variant (through the build cache when given) and run the fit check on its
    assembly. {"variant", "findings": [Finding], "items": [(label, standin)]}."""
    from .project import built, dims, make_pieces

    d = dims(mod, key)
    pc = make_pieces(mod, key, d, settings, cache)
    parts, _, _ = built(mod, d, pc)
    asm = pc.assembly()
    printed = {_norm(n or "part") for n in parts}
    found = fit_report(mod, d, parts, asm, settings, hole_tol)
    return {"variant": key or "standard", "findings": found,
            "items": [[lbl, is_standin(lbl, printed)] for _, _, lbl in asm or []]}


def text(res: dict, name: str, verbose: bool = False) -> str:
    """The fit report as lines: failures and warnings first."""
    found = res["findings"]
    n = {lvl: sum(f.level == lvl for f in found) for lvl in (OK, WARN, FAIL)}
    items = ", ".join(f"{lbl}{' (stand-in)' if s and 'stand' not in lbl.lower() else ''}" for lbl, s in res["items"])
    lines = [f"{name} [{res['variant']}]: {n[FAIL]} fail, {n[WARN]} warn, {n[OK]} ok; assembly: {items or 'none'}"]
    order = {FAIL: 0, WARN: 1, OK: 2}
    for f in sorted(found, key=lambda f: order[f.level]):
        if verbose or f.level != OK or f.target == "assembly":
            lines.append("  " + f.line())
    return "\n".join(lines)
