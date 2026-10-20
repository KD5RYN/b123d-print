"""Scorers for the benchmark tasks (benchmarks.toml): pass/fail checks on a part script's pieces,
shared by every task so none re-implements them.

A script is built once into a `Candidate`: its printable pieces in print orientation (exported
as STEP and read back) and, when a check needs it, the fit report of its assembly(d). An agent's
script runs only inside the b123d-print sandbox (`sandboxed`); the repository's own reference
scripts may run in this process (`in_process`, what the offline self-tests use). The checks then
read geometry only:

    pieces       the printable pieces are exactly these names
    on_bed       every piece rests on Z=0
    size         a piece's bounding box (any axis order unless any_order = false)
    origin       where the part's origin is, as the bounding-box centre in XY
    holes        vertical round holes at X/Y from a datum (the bounding-box corner), with diameters
    orientation  suggest_orientation ranks the piece as built at the top, or close to it
    supports     support area under the piece as built (suggest_orientation's estimate)
    tip_over     the tip-over check's footprint test
    compare      b123d_print.compare against the reference script's piece
    mirror_of    one piece is the mirror image of another, not a copy
    fit          check_fit on assembly(d): no failure, holes line up, stand-ins present

Each check returns a `Result`; a task passes when every one passes.
"""

from __future__ import annotations

import math
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from b123d_print import checks as ck
from b123d_print.config import Settings

DATUMS = ("min", "origin")  # hole positions from the bounding box's -X -Y corner, or from the part origin


@dataclass
class Result:
    check: str
    ok: bool
    detail: str
    piece: str = ""
    value: object = None
    limit: object = None

    def as_dict(self) -> dict:
        return {"check": self.check, "piece": self.piece, "ok": self.ok, "detail": self.detail,
                "value": self.value, "limit": self.limit}

    def line(self) -> str:
        where = f" [{self.piece}]" if self.piece else ""
        return f"[{'ok' if self.ok else 'FAIL':4}] {self.check}{where}: {self.detail}"


@dataclass
class Candidate:
    """A part script, built: its pieces in print orientation and (if asked) its fit report."""

    script: Path
    pieces: dict = field(default_factory=dict)  # name -> build123d Part ("part" for a single one)
    fit: dict | None = None  # the worker's "fit" result for the first variant
    error: str = ""
    _orient: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------------------------
# building a script: in the sandbox (agent output) or in this process (trusted references)

JobRunner = Callable[[dict, Path, Path], dict]  # (job, workspace, out_dir) -> the worker's result


def sandboxed(timeout: float = 240.0) -> JobRunner:
    """Run jobs the way the MCP server does: b123d_print.sandbox (restricted process, timeout)."""
    from b123d_print import sandbox

    return lambda job, ws, out: sandbox.run_job(job, ws, out, timeout)


def in_process(job: dict, ws: Path, out: Path) -> dict:
    """Run a job in this process. Only for scripts in this repository (the references)."""
    from b123d_print import worker

    out.mkdir(parents=True, exist_ok=True)
    try:
        return {"ok": True, **worker.do({**job, "out_dir": str(out)})}
    except Exception as e:  # noqa: BLE001 - a broken script is a result, like in the worker
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(limit=3)}


def build(script: Path, out: Path, run: JobRunner = in_process, workspace: Path | None = None,
          fit: bool = False) -> Candidate:
    """Export the script's pieces (first variant) as STEP into `out` and read them back; with
    fit=True also run the fit check on its assembly(d)."""
    from build123d import import_step

    script = Path(script).resolve()
    ws = Path(workspace).resolve() if workspace else script.parent
    cand = Candidate(script)
    res = run({"op": "export", "script": str(script), "formats": "step", "variant": _first_variant(script)}, ws, out)
    if not res.get("ok"):
        cand.error = f"export failed: {res.get('error', '?')}"
        return cand
    v = res["variants"][0]
    names = list(v["parts"])
    steps = [Path(f) for f in v["files"] if f.endswith(".step")][:len(names)]
    for n, f in zip(names, steps):
        cand.pieces[n] = import_step(out / f.name if not f.is_absolute() else f)
    if fit:
        r = run({"op": "fit", "script": str(script), "variant": _first_variant(script)}, ws, out)
        cand.fit = r["variants"][0] if r.get("ok") else {"error": r.get("error", "?")}
    return cand


def _first_variant(script: Path) -> str:
    """The variant to score: the standard one. The tasks ask for one part with no extra variants;
    a script without a "" variant still builds its first one (the worker picks it with None)."""
    import ast

    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "VARIANTS" for t in node.targets):
                keys = [k.value for k in getattr(node.value, "keys", []) if isinstance(k, ast.Constant)]
                if keys and "" not in keys:
                    return keys[0]
    except (OSError, SyntaxError):
        pass
    return "standard"


# ---------------------------------------------------------------------------------------------
# the checks: fn(cand, ref, **params) -> Result | list[Result]


def _bbox(part):
    bb = part.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _piece(cand: Candidate, piece: str | None):
    name = piece or (next(iter(cand.pieces)) if len(cand.pieces) == 1 else "part")
    if name not in cand.pieces:
        raise KeyError(f"no piece {name!r} (pieces: {sorted(cand.pieces)})")
    return name, cand.pieces[name]


def _r(x, n: int = 3):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [round(float(v), n) for v in x]
    return round(float(x), n)


def check_pieces(cand, ref, names: list[str]) -> Result:
    have = sorted(cand.pieces)
    ok = have == sorted(names)
    return Result("pieces", ok, f"pieces {have}" + ("" if ok else f", expected {sorted(names)}"), value=have, limit=sorted(names))


def check_on_bed(cand, ref, tol: float = 0.05) -> list[Result]:
    out = []
    for n, p in cand.pieces.items():
        z = float(_bbox(p)[0][2])
        out.append(Result("on_bed", abs(z) <= tol, f"lowest point at Z={z:.3f} (bed at 0 +- {tol:g})", n, _r(z), tol))
    return out


def check_size(cand, ref, mm: list[float], piece: str | None = None, tol: float = 0.2, any_order: bool = True) -> Result:
    name, p = _piece(cand, piece)
    lo, hi = _bbox(p)
    got, want = hi - lo, np.asarray(mm, float)
    a, b = (np.sort(got), np.sort(want)) if any_order else (got, want)
    err = float(np.max(np.abs(a - b)))
    return Result("size", err <= tol, f"{' x '.join(f'{x:.2f}' for x in got)} mm, expected {' x '.join(f'{x:g}' for x in want)}"
                  f"{' (any axis order)' if any_order else ''}, off by {err:.2f} (tol {tol:g})", name, _r(got), _r(want))


def check_origin(cand, ref, xy: list[float] = (0.0, 0.0), piece: str | None = None, tol: float = 0.5) -> Result:
    name, p = _piece(cand, piece)
    lo, hi = _bbox(p)
    c = (lo + hi)[:2] / 2
    err = float(np.linalg.norm(c - np.asarray(xy, float)))
    return Result("origin", err <= tol, f"bounding-box centre at XY ({c[0]:.2f}, {c[1]:.2f}), expected ({xy[0]:g}, {xy[1]:g}) "
                  f"+- {tol:g}", name, _r(c), list(xy))


def vertical_holes(part) -> list[dict]:
    """Round through or blind holes with a vertical axis (fit.bores: a counterbore and its hole
    are one), as {"x", "y", "d"} in the part's frame."""
    from b123d_print.fit import bores

    return [{"x": b["center"][0], "y": b["center"][1], "d": b["d"]} for b in bores(part) if abs(b["axis"][2]) > 0.98]


def check_holes(cand, ref, holes: list[list[float]], piece: str | None = None, datum: str = "min", tol: float = 0.2,
                d_tol: float = 0.35, exact: bool = True) -> Result:
    """holes: [[x, y, d], ...] from the datum. A hole's diameter may be up to d_tol larger than
    given (hole compensation), or slightly smaller."""
    if datum not in DATUMS:
        raise ValueError(f"datum {datum!r}: use one of {DATUMS}")
    name, p = _piece(cand, piece)
    o = _bbox(p)[0][:2] if datum == "min" else np.zeros(2)
    found = [{**h, "x": h["x"] - o[0], "y": h["y"] - o[1]} for h in vertical_holes(p)]
    misses, worst, used = [], 0.0, set()
    for x, y, d in holes:
        best = None
        for i, h in enumerate(found):
            if i in used or not (-0.05 <= h["d"] - d <= d_tol):
                continue
            off = math.hypot(h["x"] - x, h["y"] - y)
            if best is None or off < best[0]:
                best = (off, i)
        if best is None or best[0] > tol:
            near = f", nearest {best[0]:.2f} mm away" if best else ""
            misses.append(f"d {d:g} at ({x:g}, {y:g}){near}")
        else:
            used.add(best[1])
            worst = max(worst, best[0])
    extra = len(found) - len(used)
    ok = not misses and (extra == 0 or not exact)
    got = "; ".join(f"d {h['d']:.2f} at ({h['x']:.2f}, {h['y']:.2f})" for h in found) or "none"
    detail = (f"{len(holes) - len(misses)}/{len(holes)} holes within {tol:g} mm of their place from the "
              f"{'bounding-box -X -Y corner' if datum == 'min' else 'origin'} (worst {worst:.3f})")
    if misses:
        detail += "; missing " + ", ".join(misses)
    if extra and exact:
        detail += f"; {extra} extra hole(s)"
    if not ok:
        detail += f"; found {got}"
    return Result("holes", ok, detail, name, [[_r(h["x"], 2), _r(h["y"], 2), _r(h["d"], 2)] for h in found], holes)


def _orientation(cand: Candidate, name: str, part) -> dict:
    if name not in cand._orient:
        from b123d_print import orient

        res, _ = orient.suggest(part, Settings())
        rows = res["candidates"]
        mine = next(r for r in rows if r["source"] == "as modeled")
        cand._orient[name] = {"top": rows[0], "mine": mine}
    return cand._orient[name]


def check_orientation(cand, ref, piece: str | None = None, max_gap: float = 0.5, max_rank: int = 1) -> Result:
    """suggest_orientation's ranking of the piece as built: it passes as the top choice (rank <=
    max_rank) or within max_gap of the top choice's score (lower is better)."""
    name, p = _piece(cand, piece)
    o = _orientation(cand, name, p)
    mine, top = o["mine"], o["top"]
    gap = mine["score"] - top["score"]
    ok = mine["rank"] <= max_rank or gap <= max_gap
    return Result("orientation", ok, f"as built ranks #{mine['rank']} (score {mine['score']:g}, top {top['score']:g} "
                  f"with {top['down']} side down, gap {gap:.2f}, limit {max_gap:g}); {'; '.join(mine['notes'])}",
                  name, round(gap, 3), max_gap)


def check_supports(cand, ref, piece: str | None = None, max_mm2: float = 200.0) -> Result:
    name, p = _piece(cand, piece)
    a = _orientation(cand, name, p)["mine"]["supports_mm2"]
    return Result("supports", a <= max_mm2, f"supports under {a:g} mm^2 as built (limit {max_mm2:g})", name, a, max_mm2)


def check_tip_over(cand, ref, piece: str | None = None) -> Result:
    name, p = _piece(cand, piece)
    fp = ck.bed_footprint(p, Settings().tip_speed)
    why = ck.tip_risk(fp)
    return Result("tip_over", not why, "; ".join(why) or f"stable: {fp['height']:g} mm tall on {fp['area']:g} mm^2",
                  name, fp.get("brim"), ck.TIP_BRIM)


def check_compare(cand, ref, piece: str | None = None, ref_piece: str | None = None, thresholds: dict | None = None) -> Result:
    """b123d_print.compare of the piece against the reference script's piece (any placement; a
    mirror image fails unless thresholds allow_mirrored)."""
    from b123d_print.compare import Criteria, compare

    if ref is None:
        raise ValueError("compare needs the task's reference script")
    name, p = _piece(cand, piece)
    _, rp = _piece(ref, ref_piece or piece)
    crit = Criteria.from_pairs([f"{k}={v}" for k, v in (thresholds or {}).items()])
    c = compare(rp, p, criteria=crit)
    m = c.metrics
    fails = c.failures()
    return Result("compare", c.passed, f"score {c.score:.1f}, Hausdorff {m['hausdorff_mm']:.2f} mm, volume {m['volume_rel']:+.1%}"
                  f"{', MIRRORED' if c.alignment['mirrored'] else ''}" + (f"; failed {', '.join(fails)}" if fails else ""),
                  name, c.score, None)


def check_mirror_of(cand, ref, piece: str, of: str, thresholds: dict | None = None) -> Result:
    """`piece` is the mirror image of `of`: compare finds the best match mirrored. A copy (or a
    copy turned around) matches without a mirror and fails."""
    from b123d_print.compare import Criteria, compare

    _, a = _piece(cand, of)
    _, b = _piece(cand, piece)
    crit = Criteria.from_pairs([f"{k}={v}" for k, v in {**(thresholds or {}), "allow_mirrored": True}.items()])
    c = compare(a, b, criteria=crit)
    mirrored = bool(c.alignment["mirrored"])
    ok = c.passed and mirrored
    why = ("its mirror image" if mirrored else "a copy (it matches without mirroring)") if c.passed else \
        f"neither a copy nor a mirror image (failed {', '.join(c.failures())})"
    return Result("mirror_of", ok, f"{piece} is {why} of {of} (Hausdorff {c.metrics['hausdorff_mm']:.2f} mm)", piece, mirrored, True)


def check_fit(cand, ref, pieces: list[str] = ("box", "lid"), min_aligned: int = 4, min_standins: int = 0) -> list[Result]:
    """check_fit on assembly(d): no FAIL; at least min_aligned hole pairs between `pieces` line up
    with a screw that explains them; at least min_standins stand-ins (screws) in the assembly."""
    f = cand.fit
    if not f or f.get("error"):
        return [Result("fit", False, f"no fit report: {(f or {}).get('error', 'no assembly')}")]
    found = f["findings"]
    fails = [x["message"] for x in found if x["level"] == ck.FAIL]
    out = [Result("fit", not fails, f"{len(fails)} failure(s)" + (": " + "; ".join(fails[:3]) if fails else ""), value=len(fails), limit=0)]
    want = {str(p).lower() for p in pieces}
    aligned = [x for x in found if x["check"] == "align" and x["level"] == ck.OK
               and {str(s).lower() for s in (x.get("data") or {}).get("pair", [])} == want]
    out.append(Result("fit_holes", len(aligned) >= min_aligned, f"{len(aligned)} hole pair(s) between {' and '.join(pieces)} line up "
                      f"(need {min_aligned})", value=len(aligned), limit=min_aligned))
    if min_standins:
        n = _standins(f.get("text", ""))
        out.append(Result("standins", n >= min_standins, f"{n} stand-in(s) in assembly(d) (need {min_standins})", value=n, limit=min_standins))
    return out


def _standins(text: str) -> int:
    """Stand-ins in the fit report's first line ("...; assembly: box, lid, screw 1 (stand-in), ..."):
    fit.text marks every stand-in whose label does not already say so."""
    first = text.splitlines()[0] if text else ""
    _, _, items = first.partition("; assembly: ")
    return sum(1 for s in items.split(", ") if "stand" in s.lower() or "dummy" in s.lower() or "(ref)" in s.lower())


CHECKS: dict[str, Callable] = {
    "pieces": check_pieces, "on_bed": check_on_bed, "size": check_size, "origin": check_origin, "holes": check_holes,
    "orientation": check_orientation, "supports": check_supports, "tip_over": check_tip_over, "compare": check_compare,
    "mirror_of": check_mirror_of, "fit": check_fit,
}
NEEDS_FIT = {"fit"}


def run_checks(cand: Candidate, ref: Candidate | None, specs: list[dict]) -> list[Result]:
    """Every check of a task on a built candidate. A check that cannot run fails with the reason."""
    if cand.error:
        return [Result("build", False, cand.error)]
    out: list[Result] = []
    for spec in specs:
        params = {k: v for k, v in spec.items() if k != "check"}
        name = spec["check"]
        try:
            r = CHECKS[name](cand, ref, **params)
        except Exception as e:  # noqa: BLE001 - a missing piece, a failed compare: the check fails
            r = Result(name, False, f"could not run: {type(e).__name__}: {e}", str(params.get("piece", "")))
        out += r if isinstance(r, list) else [r]
    return out


def summary(results: list[Result]) -> dict:
    n = len(results)
    ok = sum(r.ok for r in results)
    return {"score": round(100.0 * ok / n, 1) if n else 0.0, "passed": bool(n) and ok == n,
            "failures": [r.check + (f"[{r.piece}]" if r.piece else "") for r in results if not r.ok]}
