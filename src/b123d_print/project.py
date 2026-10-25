"""Part-script convention and the runner behind `b123d-print build` / `b123d-print check` / the MCP tools.

A part script lives at <parts_dir>/<name>/<name>.py and defines:

    @dataclass(frozen=True)
    class Dims: ...                  # UPPER_CASE fields in mm; derived values as properties
    VARIANTS = {"": {}, "big": dict(WIDTH=80.0)}   # overrides only; "" is the standard part
    def build(d) -> Part | dict[str, Part]          # printable parts, in PRINT orientation; a dict's
                                                    # values may be zero-argument callables (lazy
                                                    # pieces: built only when that piece is needed)

and optionally:

    def assembly(d) -> list[(Part, color, label)]   # assembled position, incl. stand-ins for
                                                    # the things it mates with -> overlap check
    def views(d) -> list[View]                      # section views saved on export
    def checks(d) -> list[Wall | Overhang | Gap | ...]  # automatic per part: Overhang, ThinFeature,
                                                    # Holes, BedEdge, TipOver, Gap, Fit
    def original(d) -> Part                         # remixes: the original as placed in the remix
                                                    # (default: what build() loaded with import_model)
    def templates(d) -> list[Template]              # fit-test templates exported with every variant
    def hardware(d) -> list[Hardware]              # declared bought parts for the whole assembly

    if __name__ == "__main__":
        from b123d_print import run
        run(__file__)

Scripts with only a module-level `part = ...` (no Dims) also work.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, is_dataclass, replace
from pathlib import Path
from types import ModuleType

from build123d import Part

from . import checks as ck
from . import intent
from .config import Settings, hole_comp_source, load_settings, parse_formats, safe_console
from .motion import _Swept
from .motion import image_path as motion_image
from .partfiles import find_parts, resolve_part, timing_lines  # noqa: F401  (light: the MCP server imports them from there)
from . import outdir
from .render import export_files, render, report, section_view


@dataclass
class View:
    """A cross-section saved with the exports. plane 'XY' (at=Z), 'XZ' (at=Y) or 'YZ' (at=X).
    parts: names from build() to include; default the assembly if there is one, else all parts."""

    plane: str
    at: float
    title: str = ""
    parts: tuple | None = None


def load(path: str | Path) -> ModuleType:
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))  # sibling helper modules
    name = f"b123d_print_part_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def variants(mod: ModuleType) -> dict[str, dict]:
    return dict(getattr(mod, "VARIANTS", None) or {"": {}})


def variant_key(name: str | None) -> str | None:
    return None if name is None else ("" if name in ("", "standard") else name)


def dims(mod: ModuleType, key: str):
    D = getattr(mod, "Dims", None)
    if D is None:
        return None
    overrides = variants(mod)[key]
    return replace(D(), **overrides) if is_dataclass(D) else D(**overrides)


def printables(mod: ModuleType, d) -> dict[str, Part]:
    """Every printable piece of build(d), lazy ones built too ({"": part} for a single part)."""
    return Pieces(mod, d).parts()


HEAVY_FACES = 1500  # a piece with more faces than this, or ...
HEAVY_SECONDS = 10.0  # ... taking longer than this to build, gets HEAVY_HINT in the timing report
HEAVY_HINT = "dense polyline or many stacked offsets: fewer curve points, a spline, or build once and mirror/copy the result"


class Pieces:
    """The printable pieces of one variant, built when first asked for. build(d) may return a dict
    whose values are zero-argument callables (lazy pieces): each is called only when its piece is
    needed, so `parts=` / `--only` builds just those. Plain shapes work as always (build(d) builds
    them all at once). With a BuildCache, a piece built before from the same inputs is read back
    instead of built. `stats` holds what each piece cost: faces, seconds (None for a piece of an
    eager dict: build(d) built them all, in `build_seconds`) and whether it came from the cache."""

    progress = None  # a callable the worker sets: told what is being built (diagnose.PROGRESS lines, for timeouts)

    def __init__(self, mod: ModuleType, d, cache: BuildCache | None = None):
        self.mod, self.d, self.cache = mod, d, cache
        self.stats: dict[str, dict] = {}
        self.build_seconds: float | None = None  # how long build(d) itself took, when it ran
        self.imports: list = []  # what import_model loaded while building (remix.IMPORTED entries)
        self._raw: dict | None = None
        self._names: list[str] | None = None
        self._done: dict[str, Part] = {}
        self._asm = None
        self._asm_done = False
        self._imported = False  # build(d) itself loaded a model: nothing it made is cached

    def names(self) -> list[str]:
        """The pieces' names in build order ("" for a single part); calls build(d) unless cached."""
        if self._names is None:
            got = self.cache.names() if self.cache is not None else None
            self._names = got if got is not None else list(self._build())
        return self._names

    def _build(self) -> dict:
        if self._raw is None:
            t = time.perf_counter()
            self._say("building build(d)")
            with self._recording() as rec:
                if hasattr(self.mod, "build"):
                    r = self.mod.build(self.d) if self.d is not None else self.mod.build()
                elif hasattr(self.mod, "part"):
                    r = self.mod.part
                else:
                    raise AttributeError("script defines neither build(d) nor a module-level `part`")
            self.build_seconds = time.perf_counter() - t
            self._say(f"built build(d) in {self.build_seconds:.2f} s")
            self._raw = dict(r) if isinstance(r, dict) else {"": r}
            self._imported = bool(rec)
            if self.cache is not None and not self._imported:
                self.cache.save_names(list(self._raw))
        return self._raw

    def _say(self, msg: str) -> None:
        if Pieces.progress is not None:
            Pieces.progress(msg)

    @contextmanager
    def _recording(self):
        """Collects what import_model loads inside it (into self.imports too)."""
        from . import remix

        n0, got = len(remix.IMPORTED), []
        try:
            yield got
        finally:
            got.extend(remix.IMPORTED[n0:])
            self.imports.extend(got)

    def part(self, name: str) -> Part:
        """One piece by its build() name ("" or "part" for a single part)."""
        if name == "part" and "part" not in self.names() and "" in self.names():
            name = ""
        if name in self._done:
            return self._done[name]
        raw = self._raw
        eager = raw is not None and name in raw and not _lazy(raw[name])
        shape = None
        if self.cache is not None and not eager:
            got = self.cache.load(name)
            if got is not None:
                shape, self.stats[name] = got[0], {**got[1], "cached": True}
        if shape is None:
            raw = self._build()
            if name not in raw:
                raise KeyError(f"no part {name or 'part'!r}; parts: {sorted(k or 'part' for k in raw)}")
            v = raw[name]
            t = time.perf_counter()
            self._say(f"building piece {name or 'part'}")
            with self._recording() as rec:
                shape = v() if _lazy(v) else v
            secs = round(time.perf_counter() - t, 2) if _lazy(v) else None
            self.stats[name] = {"faces": _faces(shape), "seconds": secs, "cached": False}
            self._say(f"built piece {name or 'part'}: {self.stats[name]['faces']} faces, {secs or 0:.2f} s")
            if self.cache is not None and not (self._imported or rec):
                self.cache.save(name, shape, self.stats[name])
        self._done[name] = shape
        return shape

    def parts(self, only=None) -> dict[str, Part]:
        """{name: piece} in build order: every piece, or the ones named in `only` (a list or a
        comma-separated string; "part" names a single part)."""
        names = self.names()
        if only:
            want = [w.strip() for w in only.split(",")] if isinstance(only, str) else list(only)
            known = {(n or "part"): n for n in names}
            missing = [w for w in want if w and w not in known]
            if missing:
                raise KeyError(f"no part(s) {missing}; parts: {sorted(known)}")
            names = [known[w] for w in dict.fromkeys(want) if w]
        return {n: self.part(n) for n in names}

    def assembly(self) -> list | None:
        """assembly(d), read back from the cache when it was saved before (None: no assembly)."""
        if not self._asm_done:
            f = getattr(self.mod, "assembly", None)
            got = self.cache.load_assembly() if f is not None and self.cache is not None else None
            if got is not None:
                self._asm = got
            elif f is not None:
                t = time.perf_counter()
                with self._recording() as rec:
                    self._asm = f(self.d)
                if self.cache is not None and not rec and self._asm:
                    self.cache.save_assembly(self._asm, round(time.perf_counter() - t, 2))
            self._asm_done = True
        return self._asm

    def timing(self) -> dict:
        """The timing report: per built piece its faces, seconds and whether it was cached; the
        build(d) call's seconds when it ran; and HEAVY_HINT for the pieces that need it."""
        pieces = {(n or "part"): st for n, st in self.stats.items()}
        hints = [f"{n}: {st['faces']} faces" + (f", {st['seconds']:g} s" if st.get("seconds") is not None else "")
                 + f": {HEAVY_HINT}" for n, st in pieces.items()
                 if st["faces"] > HEAVY_FACES or (st.get("seconds") or 0) > HEAVY_SECONDS]
        eager = [n for n, st in pieces.items() if st.get("seconds") is None and not st.get("cached")]
        if self.build_seconds is not None and self.build_seconds > HEAVY_SECONDS and len(eager) > 1:
            hints.append(f"build(d) took {self.build_seconds:.1f} s for {len(eager)} pieces at once: return lazy pieces "
                         "({'name': lambda: make_name(d)}) to see each piece's time and build one at a time")
        out = {"pieces": pieces, "hints": hints}
        if self.build_seconds is not None:
            out["build_seconds"] = round(self.build_seconds, 2)
        if self.cache is not None:
            why = ("not cached: the build loaded a model with import_model (its conversion has its own cache)"
                   if self.imports else self.cache.skipped)
            out["cache"] = why or ("off for this call (fresh): rebuilt and saved again" if self.cache.cfg.fresh else "on")
        return out


def _lazy(v) -> bool:
    from build123d import Shape

    return callable(v) and not isinstance(v, Shape)


def _faces(shape) -> int:
    try:
        return len(shape.faces())
    except Exception:  # noqa: BLE001 - not a shape: report() says what is wrong with it
        return 0


def built(mod: ModuleType, d, pieces: Pieces | None = None, only=None) -> tuple[dict[str, Part], Part | None, list]:
    """printables() plus the remix's original: what `original(d)` returns, else what build() loaded
    with import_model (None for a part that is not a remix), and the import records.
    pieces: build through these (lazy, cached) instead of calling build(d) here; only: just these
    pieces (Pieces.parts)."""
    from . import remix

    remix.reset_imports()
    pieces = pieces if pieces is not None else Pieces(mod, d)
    parts = pieces.parts(only)
    imports = list(pieces.imports)
    f = getattr(mod, "original", None)
    if f is not None:
        n0 = len(remix.IMPORTED)
        orig = f(d) if d is not None else f()
        imports += remix.IMPORTED[n0:]
    elif imports:
        from build123d import Compound

        orig = imports[0][0] if len(imports) == 1 else Part(Compound([s for p, _ in imports for s in p.solids()]).wrapped)
    else:
        orig = None
    remix.reset_imports()
    return parts, orig, [info for _, info in imports]


def assembly(mod: ModuleType, d) -> list[tuple[Part, str, str]] | None:
    f = getattr(mod, "assembly", None)
    return f(d) if f else None


def out_name(stem: str, key: str, part: str) -> str:
    return "_".join(x for x in (stem, key, part) if x)


def check_specs(mod: ModuleType, d, parts: dict, asm) -> list:
    f = getattr(mod, "checks", None)
    specs = list(f(d) if f else [])
    covered = {s.part or "part" for s in specs if isinstance(s, ck.Overhang)}
    specs += [ck.Overhang(p) for p in parts if p not in covered]  # always report overhangs
    why = intent.no_supports_why(mod, d)  # PRINT supports "none": overhangs reported as accepted, FAILs kept
    if why:
        specs = [replace(s, accept=why) if isinstance(s, ck.Overhang) and not s.accept else s for s in specs]
    if asm and not any(isinstance(s, ck.Overlap) for s in specs):
        specs.append(ck.Overlap())
    fitted = {s.part or "part" for s in specs if isinstance(s, ck.Fit)}
    specs += [ck.Fit(p) for p in parts if p not in fitted]  # no-op without a printer profile
    # automatic per-part checks; a script lists one itself to change its arguments
    for cls in (ck.ThinFeature, ck.Holes, ck.BedEdge, ck.TipOver):
        listed = {s.part or "part" for s in specs if isinstance(s, cls)}
        specs += [cls(p) for p in parts if p not in listed]
    gapped = {s.part or "part" for s in specs if isinstance(s, ck.Gap) and s.other is None}
    specs += [ck.Gap(p) for p in parts if p not in gapped]  # no-op for a single solid
    return specs


def run_checks(mod: ModuleType, key: str, settings: Settings, nudge: bool = True,
               deadline: float | None = None, cache: CacheConfig | None = None) -> list[ck.Finding]:
    """Build one variant and run every check. Never raises: errors become findings.
    nudge: also add the setup reminders (hole_comp never measured); callers pass it for the
    first variant only, so a check run says it once.
    deadline: a time.time() by which to stop (the worker's soft limit, below the hard timeout
    that kills it). A check still running then is interrupted; the result is every finding
    finished so far plus a "timeout" FAIL naming the check that was running and those not run.
    The MCP server runs the same checks split over several workers (check_share, merge_shares).
    cache: build through the build cache (the worker)."""
    return merge_shares([check_share(mod, key, settings, deadline=deadline, cache=cache)], nudge)


# A check run is a list of items: each check spec on the printable parts ("<i>:part") and, for a
# remix, the automatic ones again on the original ("<i>:original"). check_share runs the items of
# one share; merge_shares puts the shares' findings back in spec order and labels inherited ones.
# Shares are what the MCP server runs in parallel workers: every worker builds the part (from
# import_model's cache) and computes the same partition, so no worker needs another's result.

COST_MIN_SPLIT = 4.0  # estimated seconds: a smaller check run is not worth splitting (a worker takes ~3 s to start)


def check_share(mod: ModuleType, key: str, settings: Settings, share: tuple[int, int] = (0, 1),
                deadline: float | None = None, started: float | None = None, cache: CacheConfig | None = None) -> dict:
    """Run share `share` = (index, count) of one variant's check items (see partition). started:
    when the check run began; an original's findings cached before then count as free (cached
    later: not, so every share sees the same and computes the same partition). Returns a
    JSON-able dict: "pre" (import and validity findings), "labels" and "inherit" per spec,
    "results" {item: [finding dicts]}, "assigned" items, "stopped" (what was running and not run
    when the deadline passed) or "error" (the build failed), "hole_comp_set", "costs"."""
    tag = key or "standard"
    res: dict = {"tag": tag, "pre": [], "labels": [], "inherit": [], "results": {}, "assigned": [], "stopped": None,
                 "error": None, "hole_comp_set": hole_comp_source(getattr(mod, "__file__", None)) is not None}
    if deadline is not None and time.time() >= deadline:
        res["stopped"] = {"running": None, "not_run": [f"variant {tag}"], "seconds": 0.0}
        return res
    current = f"building variant {tag}"
    todo: list = []
    with _Deadline(deadline) as dl:
        try:
            try:
                d = dims(mod, key)
                intent.declared(mod, d)  # a bad PRINT is a build error, said before any check runs
                pc = make_pieces(mod, key, d, settings, cache)
                parts, orig, imports = built(mod, d, pc)
                imported_before_assembly = len(pc.imports)
                asm = pc.assembly()
                # Assembly-only imports (e.g. bought hardware) need their conversion warnings,
                # but are never the remix original. Do not repeat a build's identical import.
                seen_imports = {(i.file, i.units, i.scale, i.faces_after) for i in imports}
                for _, info in pc.imports[imported_before_assembly:]:
                    identity = (info.file, info.units, info.scale, info.faces_after)
                    if identity not in seen_imports:
                        imports.append(info)
                        seen_imports.add(identity)
            except CheckTimeout:
                raise
            except Exception as e:
                res["error"] = finding_dict(ck.Finding(ck.FAIL, "error", tag, f"build failed: {e!r}",
                                                       {"traceback": traceback.format_exc(),
                                                        "diagnosis": _diagnosis(e, mod)}))
                return res
            pre = [import_finding(i) for i in imports]
            for name, p in parts.items() if share[0] == 0 else ():  # once per run: share 0 reports them
                current = f"validity of {name or 'part'}"
                valid = bool(p.is_valid) and p.volume > 0
                pre.append(ck.Finding(ck.OK if valid else ck.FAIL, "valid", name or "part",
                                      "valid solid" if valid else f"is_valid={p.is_valid}, volume={p.volume:.3f}", report(p)))
            res["pre"] = [finding_dict(f) for f in pre] if share[0] == 0 else []
            res["share"] = list(share)
            named = {(k or "part"): v for k, v in parts.items()}
            lookup = dict(named)
            if list(parts) == [""]:  # a bare Part from build(): also findable by the script's own name
                lookup.setdefault(Path(getattr(mod, "__file__", "part")).stem, named["part"])
            current = "checks(d)"
            specs = check_specs(mod, d, named, asm)
            res["labels"] = [spec_label(sp) for sp in specs]
            res["inherit"] = [orig is not None and isinstance(sp, INHERITABLE) and getattr(sp, "other", None) is None
                              for sp in specs]
            items = [(i, side) for i in range(len(specs)) for side in ("part", "original")
                     if side == "part" or res["inherit"][i]]
            originals = OriginalFindings(mod, orig, settings) if orig is not None else None
            found_cache = CheckCache(pc.cache, key, lookup, settings, specs) if pc.cache is not None and orig is None else None
            costs = [0.01 if started is not None and (
                         originals.cached_before(replace(specs[i], part=ORIGINAL), started) if side == "original"
                         else found_cache is not None and found_cache.cached_before(specs[i], started))
                     else item_cost(specs[i], lookup, asm, orig if side == "original" else None) for i, side in items]
            mine = partition(costs, share[1], first=0.0003 * sum(len(p.faces()) for p in parts.values()))
            todo = [it for it, j in zip(items, mine) if j == share[0]]
            res["assigned"] = [f"{i}:{side}" for i, side in todo]
            res["costs"] = round(sum(costs), 2)
            while todo:
                i, side = todo[0]
                spec = specs[i]
                current = res["labels"][i] + (" on the original" if side == "original" else "")
                try:
                    if side == "original":
                        found = originals.get(replace(spec, part=ORIGINAL))
                    else:
                        if isinstance(spec, _Swept) and spec.image is None and getattr(mod, "__file__", None):
                            script = Path(mod.__file__)  # a motion draws its worst pose next to the exports
                            spec = replace(spec, image=str(motion_image(script.parent / "out" / outdir.IMAGES, out_name(script.stem, key, ""), spec)))
                        found = found_cache.get(spec) if found_cache is not None else None
                        if found is None:
                            found = spec.run(lookup, asm, settings)
                            if found_cache is not None:
                                found_cache.put(spec, found)
                        if isinstance(spec, ck.ThinFeature) and res["inherit"][i]:
                            probe = originals.probe(spec)  # is the original thin at each listed spot? (merge_shares)
                            for f in found:
                                for spot in f.data.get("spots", []) if f.level != ck.OK else []:
                                    spot["original_thin"] = bool(probe(spot))
                except CheckTimeout:
                    raise
                except Exception as e:
                    found = [ck.Finding(ck.FAIL, "error", getattr(spec, "part", type(spec).__name__), repr(e),
                                        {"traceback": traceback.format_exc()})]
                res["results"][f"{i}:{side}"] = [finding_dict(f) for f in found]
                todo.pop(0)
        except CheckTimeout:
            not_run = [res["labels"][i] + (" on the original" if side == "original" else "") for i, side in todo[1:]]
            res["stopped"] = {"running": current, "not_run": not_run, "seconds": round(time.time() - dl.started, 1)}
    return res


def _diagnosis(e: BaseException, mod: ModuleType) -> dict | None:
    """diagnose.from_exception, never raising: a broken diagnosis must not hide the error itself."""
    from . import diagnose

    try:
        return diagnose.from_exception(e, getattr(mod, "__file__", None))
    except Exception:  # noqa: BLE001
        return None


def merge_shares(shares: list[dict], nudge: bool = True, failed: list[str] = ()) -> list[ck.Finding]:
    """The findings of one variant from its shares (check_share), in spec order: import and
    validity, then each check's findings, labeled "inherited" against the original's; a timeout
    FAIL if any share stopped at the deadline, an error per share that failed (`failed`)."""
    from .remix import mark_inherited

    tag = next((s["tag"] for s in shares), "standard")
    err = next((s["error"] for s in shares if s.get("error")), None)
    if err:
        return [ck.Finding(**err)]
    base = next((s for s in shares if s["labels"]), shares[0] if shares else None)
    first = next((s for s in shares if s.get("share", [0])[0] == 0), base)  # share 0 has the validity findings
    out = [ck.Finding(**f) for f in first["pre"]] if first else []
    results = {k: [ck.Finding(**f) for f in v] for s in shares for k, v in s["results"].items()}
    labels, inherit = (base["labels"], base["inherit"]) if base else ([], [])
    for i, label in enumerate(labels):
        found = results.get(f"{i}:part")
        if found is None:
            continue
        theirs = results.get(f"{i}:original")
        if inherit[i] and theirs is not None:
            found = mark_inherited(found, theirs, lambda spot: spot.get("original_thin", False))
        for f in found:
            for spot in f.data.get("spots", []):
                spot.pop("original_thin", None)
        out.extend(found)
    stopped = [s["stopped"] for s in shares if s.get("stopped")]
    if stopped:
        running = [x["running"] for x in stopped if x["running"]]
        not_run = [n for x in stopped for n in x["not_run"]]
        spent = max(x["seconds"] for x in stopped)
        if not running and not labels:
            out.append(ck.Finding(ck.FAIL, "timeout", tag, "not checked: the time limit was reached on an earlier variant"))
        else:
            what = " and ".join(running) if running else "the checks"
            rest = f"; not run: {', '.join(not_run)}" if not_run else ""
            out.append(ck.Finding(ck.FAIL, "timeout", tag,
                                  f"time limit reached while running {what} (after {spent:.0f} s of checks on this variant): "
                                  f"stopped{rest}. The findings above are complete. Raise the check time limit "
                                  "(B123D_PRINT_CHECK_TIMEOUT on the server, default 300 s) or run fewer checks",
                                  {"running": running[0] if len(running) == 1 else running, "not_run": not_run,
                                   "seconds": spent}))
    done = {a for s in shares for a in s["assigned"]}
    missing = [labels[i] + (" on the original" if side == "original" else "")
               for i in range(len(labels)) for side in ("part", "original")
               if (side == "part" or inherit[i]) and f"{i}:{side}" not in done]
    if missing and not failed and not stopped:  # the shares disagreed on the partition: never silently
        failed = ["some checks were assigned to no check worker"]
    if failed:
        for msg in failed:
            out.append(ck.Finding(ck.FAIL, "error", tag, msg + (f" (not run: {', '.join(missing)})" if missing else ""),
                                  {"not_run": missing}))
    if nudge and base is not None:
        out.extend(setup_findings_for(out, base["hole_comp_set"]))
    return out


def finding_dict(f: ck.Finding) -> dict:
    """A finding as plain JSON values (numpy numbers become Python numbers)."""
    import json

    return json.loads(json.dumps(f.__dict__, default=_plain))


def _plain(x):
    import numpy as np

    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)


def item_cost(spec, lookup: dict, asm, orig) -> float:
    """A rough estimate, in seconds on a fast CPU, of one check item: enough to balance shares.
    The same in every worker, so they all compute the same partition. A check object of your own
    may give its own estimate as a `cost` attribute (seconds)."""
    if isinstance(getattr(spec, "cost", None), (int, float)):
        return float(spec.cost)
    try:
        if orig is not None:
            part = orig
        elif isinstance(spec, ck.Overlap):
            return 0.2 + 0.002 * sum(len(p.faces()) for p, _, _ in asm or [])
        elif isinstance(getattr(spec, "part", None), Part):
            part = spec.part
        elif getattr(spec, "frame", "print") == "assembly":
            part = next(p for p, _, lbl in asm or [] if lbl == spec.part)
        else:
            part = ck._get(lookup, spec.part)
        n = len(part.faces())
        flat = ck.meshy(part)
    except Exception:  # noqa: BLE001 - an estimate only; the check itself reports the problem
        return 0.5
    if isinstance(spec, ck.ThinFeature):
        return 0.2 + n * (0.0006 if flat else 0.02)
    if isinstance(spec, ck.Overhang):
        return 0.05 + n * 0.0003
    if isinstance(spec, ck.Wall):
        return 0.2 + n * 0.0002
    if isinstance(spec, (ck.Gap, ck.Probe)):
        return 0.1 + n * 0.0005
    return 0.02 + n * 0.00002


def partition(costs: list[float], count: int, first: float = 0.0) -> list[int]:
    """Which share runs each item: longest first, each to the share with the least so far (ties:
    the lowest share). Everything in share 0 when the total is under COST_MIN_SPLIT. first: what
    share 0 does besides (the validity findings)."""
    if count <= 1 or sum(costs) < COST_MIN_SPLIT:
        return [0] * len(costs)
    load = [first] + [0.0] * (count - 1)
    out = [0] * len(costs)
    for k in sorted(range(len(costs)), key=lambda k: (-costs[k], k)):
        j = min(range(count), key=lambda j: (load[j], j))
        out[k] = j
        load[j] += costs[k]
    return out


def spec_label(spec) -> str:
    """How a check is named in a timeout finding: Wall(part, label), ThinFeature(cover)."""
    part = getattr(spec, "part", None)
    bits = [part if isinstance(part, str) and part else ("part" if hasattr(spec, "part") else "")]
    if getattr(spec, "label", ""):
        bits.append(spec.label)
    return f"{type(spec).__name__}({', '.join(b for b in bits if b)})"


class CheckTimeout(BaseException):
    """Raised in the main thread when run_checks' deadline passes (a BaseException, so a check's
    own `except Exception` cannot swallow it)."""


class _Deadline:
    """Interrupts the main thread at `deadline` (time.time()): a timer thread raises SIGINT there
    (_thread.interrupt_main, on every OS), and the handler installed meanwhile turns it into
    CheckTimeout. Python checks for it between bytecodes, so a long OCC call finishes first
    (seconds at most). A real Ctrl-C still raises KeyboardInterrupt. Without a deadline, or
    outside the main thread, it does nothing."""

    def __init__(self, deadline: float | None):
        import threading

        self.deadline, self.timer, self.prev = deadline, None, None
        self.armed = self.fired = False
        self.lock = threading.Lock()
        self.started = time.time()

    def __enter__(self):
        import signal
        import threading

        if self.deadline is None or threading.current_thread() is not threading.main_thread():
            self.deadline = None
            return self
        self.prev = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._handler)
        self.armed = True
        self.timer = threading.Timer(max(0.0, self.deadline - time.time()), self._fire)
        self.timer.daemon = True
        self.timer.start()
        return self

    def _fire(self):
        import _thread

        with self.lock:  # never after __exit__ disarmed it
            if self.armed:
                self.fired = True
                _thread.interrupt_main()

    def _handler(self, signum, frame):
        if self.fired:
            self.fired = False  # once: a second SIGINT is a real Ctrl-C
            if self.armed:
                raise CheckTimeout()
            return  # fired just as the checks ended: nothing left to stop
        raise KeyboardInterrupt

    def __exit__(self, *exc):
        import signal

        if self.deadline is None:
            return False
        with self.lock:
            self.armed = False
        self.timer.cancel()
        signal.signal(signal.SIGINT, self.prev if self.prev is not None else signal.default_int_handler)
        return False


CACHE_VERSION = 1  # bump when what is cached changes


class OriginalFindings:
    """The checks run on a remix's original, cached in the script's out/.cache/ (next to
    import_model's conversions): the original does not change while the remix is worked on, so
    every check after the first pays only for the remix. Keyed by the original's geometry
    (rounded vertices, face count, volume: the same whether import_model converted the file or
    read its cached conversion), the check's arguments, the settings and the b123d-print code."""

    def __init__(self, mod: ModuleType, orig: Part, settings: Settings):
        self.orig, self.settings = orig, settings
        f = getattr(mod, "__file__", None)
        self.dir = Path(f).resolve().parent / "out" / ".cache" if f else None
        self.mem: dict = {}
        self._base: str | None = None

    def _key(self, twin) -> str:
        import hashlib
        import json

        if self._base is None:
            from dataclasses import asdict

            s = {k: v for k, v in asdict(self.settings).items() if k != "root"}
            self._base = json.dumps([CACHE_VERSION, shape_fingerprint(self.orig), repr(sorted(s.items())),
                                     ck.line_width(self.settings), code_version()])
        return hashlib.sha256(f"{self._base}|{twin!r}".encode()).hexdigest()[:32]

    def probe(self, spec):
        """spot -> whether the original is thin there too (ThinFeature.thin_at); not cached:
        a few local sections, milliseconds on a mesh-derived original."""
        if not hasattr(self, "_slicer"):
            self._slicer = ck.MeshSlicer(self.orig) if ck.meshy(self.orig) else None
        return lambda spot: spec.thin_at(self.orig, spot, self.settings, self._slicer)

    def cached_before(self, twin, when: float) -> bool:
        """Were the findings of `twin` cached before `when` (time.time())?"""
        if self.dir is None:
            return False
        try:
            return (self.dir / f"original-{self._key(twin)}.json").stat().st_mtime < when
        except OSError:
            return False

    def get(self, twin) -> list[ck.Finding]:
        k = repr(twin)
        if k in self.mem:
            return self.mem[k]
        path = self.dir / f"original-{self._key(twin)}.json" if self.dir is not None else None
        found = _read_findings(path) if path is not None else None
        if found is None:
            found = twin.run({ORIGINAL: self.orig}, None, self.settings)
            if path is not None:
                _write_findings(path, found)
        self.mem[k] = found
        return found


# the per-piece checks whose findings CheckCache keeps: each reads one printable piece (by name,
# in print coordinates), its own arguments and the settings, nothing else. Exact types: a
# subclass may read more. Fit reads the printer profile's file, the assembly checks other pieces.
PIECE_CHECKS = (ck.ThinFeature, ck.Overhang, ck.Holes, ck.BedEdge, ck.TipOver, ck.Gap, ck.Wall, ck.Probe)


class CheckCache:
    """The findings of the per-piece checks (PIECE_CHECKS), saved in out/.cache/ next to the build
    cache (BuildCache: only the sandboxed worker uses it, never through a link, and fresh reads
    none of it) and read back while nothing they depend on changed. The key: the piece's geometry
    (shape_fingerprint, so a piece rebuilt the same is a hit and a changed one a miss), the check's
    arguments (its repr), the settings, the line width, the variant and the code (b123d-print's
    version, the checks' and this module's source). A missing, broken or mismatched entry is a
    miss: the check runs and saves its findings again. Assembly-level checks (Overlap, Mates, a Gap
    between two parts, a Wall or Probe in the assembly frame, Motion and Slide) are never cached:
    they run every time. Writing a check's new findings removes the older entries of its slot (the
    variant, the check's type and piece, and which of those it is in checks(d))."""

    def __init__(self, build: BuildCache, key: str, lookup: dict, settings: Settings, specs: list):
        self.build, self.variant, self.lookup, self.settings = build, key, lookup, settings
        self._fps: dict[int, str] = {}
        self._base: str | None = None
        self._slots: dict[int, list] = {}
        seen: dict = {}
        for sp in specs:
            kind = (type(sp).__name__, repr(getattr(sp, "part", None)))
            self._slots[id(sp)] = [key, *kind, seen.setdefault(kind, 0)]
            seen[kind] += 1

    def _piece(self, spec):
        """The piece `spec` reads, or None when its findings are not cached."""
        if type(spec) not in PIECE_CHECKS or not isinstance(getattr(spec, "part", None), str):
            return None
        if getattr(spec, "frame", "print") != "print" or (isinstance(spec, ck.Gap) and spec.other is not None):
            return None
        try:
            return ck._get(self.lookup, spec.part)
        except KeyError:
            return None

    def _paths(self, spec) -> tuple[Path, str] | None:
        """(the entry's path, its key) or None (not cached)."""
        import hashlib
        import json

        part = self._piece(spec)
        args = repr(spec)
        if part is None or " at 0x" in args:  # an argument without a stable repr: not cached
            return None
        if id(part) not in self._fps:
            self._fps[id(part)] = shape_fingerprint(part)
        if self._base is None:
            from dataclasses import asdict

            s = {k: v for k, v in asdict(self.settings).items() if k != "root"}
            self._base = json.dumps([CACHE_VERSION, "check", repr(sorted(s.items())), ck.line_width(self.settings),
                                     code_version(), _file_hash(Path(__file__))])
        slot = self._slots.get(id(spec), [self.variant, args])
        prefix = hashlib.sha256(json.dumps(slot).encode()).hexdigest()[:12]
        k = hashlib.sha256(f"{self._base}|{self.variant}|{args}|{self._fps[id(part)]}".encode()).hexdigest()[:32]
        return self.build.root / f"check-{prefix}-{k}.json", k

    def cached_before(self, spec, when: float) -> bool:
        """Were the findings of `spec` saved before `when` (time.time())? (check_share: every share
        sees the same, so they all compute the same partition)"""
        got = None if self.build.cfg.fresh else self._paths(spec)
        if got is None:
            return False
        try:
            return got[0].stat().st_mtime < when
        except OSError:
            return False

    def get(self, spec) -> list[ck.Finding] | None:
        """The saved findings of `spec`, or None (a miss)."""
        import json

        got = self._paths(spec)
        if got is None or not self.build._usable(got[0]):
            return None
        try:
            raw = json.loads(got[0].read_text(encoding="utf-8"))
            if raw["key"] != got[1]:
                return None
            return [ck.Finding(**f) for f in raw["findings"]]
        except (OSError, ValueError, KeyError, TypeError):  # missing or broken: run the check again
            return None

    def put(self, spec, findings: list[ck.Finding]) -> None:
        import os

        got = self._paths(spec)
        if got is None or not self.build.ok or os.path.islink(self.build.root):
            return
        path, k = got
        try:
            self.build.root.mkdir(parents=True, exist_ok=True)
            when = path.stat().st_mtime if path.is_file() else None  # an entry replaced keeps its time (cached_before)
        except OSError:
            return
        _write_json(path, {"key": k, "findings": [finding_dict(f) for f in findings]})
        try:
            if when is not None:
                os.utime(path, (when, when))
            for p in self.build.root.glob(f"{path.name[:len('check-') + 12]}-*.json"):
                if p.name != path.name and not p.is_symlink():
                    p.unlink()
        except OSError:
            pass


def shape_fingerprint(shape) -> str:
    """A hash of a solid's geometry that survives a BREP round trip (unlike the BREP text)."""
    import hashlib

    import numpy as np

    pts = [(v.X, v.Y, v.Z) for v in shape.vertices()]
    a = np.round(np.array(pts, float).reshape(-1, 3), 4) + 0.0  # + 0.0: no -0.0
    a = a[np.lexsort(a.T[::-1])] if len(a) else a
    h = hashlib.sha256(a.tobytes())
    h.update(f"|{len(shape.faces())}|{len(shape.edges())}|{shape.volume:.3f}|{shape.area:.3f}".encode())
    return h.hexdigest()[:32]


def code_version() -> str:
    """b123d-print's version plus a hash of the checks' code, so an edited checkout does not
    reuse findings computed by older code."""
    import hashlib
    from importlib.metadata import PackageNotFoundError, version

    from . import remix

    try:
        v = version("b123d-print")
    except PackageNotFoundError:
        v = "unknown"
    h = hashlib.sha256()
    for f in (ck.__file__, remix.__file__):
        h.update(Path(f).read_bytes())
    return f"{v}+{h.hexdigest()[:12]}"


def _read_findings(path: Path) -> list[ck.Finding] | None:
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [ck.Finding(**f) for f in raw["findings"]]
    except (OSError, ValueError, KeyError, TypeError):  # missing or broken: run the checks again
        return None


def _write_findings(path: Path, findings: list[ck.Finding]) -> None:
    import json
    import os

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"findings": [f.__dict__ for f in findings]}, default=_plain), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:  # a read-only folder: no cache
        pass


NO_CACHE_ENV = "B123D_PRINT_NO_CACHE"  # set (to anything but "" or 0): the worker neither reads nor writes the build cache
SHAPE_TYPES = ("Part", "Compound", "Solid")  # what the build cache restores (a Box as a Part); others are built every time
NOT_GEOMETRY = ("root", "formats", "style", "filament_price", "print_flow", "tip_speed")  # settings no build reads


def no_cache_env() -> bool:
    import os

    return os.environ.get(NO_CACHE_ENV, "").strip() not in ("", "0")


class ReadLog:
    """The paths opened or listed in this process, recorded by an audit hook. The worker installs it
    before it loads the part script (and before its own guard, which refuses later hooks), so the
    build cache knows which files a build read besides the script: a reference model in ref/, a
    table the script parses. Recording only: it refuses nothing."""

    def __init__(self):
        self.paths: list[str] = []
        self.installed = False

    def install(self) -> None:
        import os

        paths = self.paths
        self.installed = True

        def hook(event: str, args) -> None:
            if event in ("open", "os.listdir", "os.scandir") and args and args[0] is not None and not isinstance(args[0], int):
                try:
                    paths.append(os.path.abspath(os.fsdecode(args[0])))
                except Exception:  # noqa: BLE001 - never break the open itself
                    pass

        sys.addaudithook(hook)


@dataclass
class CacheConfig:
    """How the worker caches builds (BuildCache). workspace: reading a file in it outside the
    part's own folder makes a build uncacheable (nothing could tell when that file changed);
    reads: the ReadLog; fresh: build again and overwrite what is cached, reading none of it."""

    workspace: Path
    reads: ReadLog
    fresh: bool = False


class BuildCache:
    """The pieces of one variant (and its assembly), saved after they are built and read back
    instead of building them again: out/.cache/build-<variant hash>-<key>/, one BREP file and one
    JSON note per piece. Only the sandboxed worker uses it, and it reads and writes nothing but
    that folder and the part's own sources.

    The key: every .py file in the part's folder (the script and its helpers), the variant and its
    Dims, the settings a build can read (hole_comp, clearances, printer, ...), and the versions of
    b123d-print, build123d and OCP. Each note also lists the other files the build read in the
    part's folder (ref/ models, data files) with their hashes; a change there is a miss too. A
    build that read a file elsewhere in the workspace, or loaded a model with import_model (a
    remix: its conversion has its own cache, and the checks need the original it loaded), is not
    saved. A missing, changed or broken entry (BREP hash, face count or volume differ) is a miss:
    the piece is built again. Building a new key removes the variant's older entries."""

    def __init__(self, mod: ModuleType, key: str, d, settings: Settings, cfg: CacheConfig):
        import hashlib
        import os

        self.cfg = cfg
        self.folder = Path(os.path.realpath(Path(mod.__file__).parent))
        self.out = self.folder / "out"
        self.root = self.out / ".cache"
        # never through a link: out/ and out/.cache/ must be what they look like
        self.ok = (os.path.normcase(os.path.realpath(self.out)) == os.path.normcase(str(self.out))
                   and not os.path.islink(self.root))
        self.prefix = f"build-{hashlib.sha256(key.encode()).hexdigest()[:8]}-"
        self.dir = self.root / (self.prefix + self._key(key, d, settings))
        self.skipped: str | None = None  # why the last piece was not saved
        self._pruned = False
        self._skip = (os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix), os.path.realpath(sys.exec_prefix),
                      os.path.realpath(Path(__file__).parent), str(self.out))
        self._import_dirs = {os.path.normcase(os.path.realpath(p)) for p in sys.path if p}  # listed by imports
        self._fps: dict[str, str | None] = {}  # fingerprints, once per file in this worker

    def _key(self, key: str, d, settings: Settings) -> str:
        import hashlib
        import json
        import os
        from dataclasses import asdict

        import build123d
        import OCP

        src = []
        for top, dirs, names in os.walk(self.folder):
            dirs[:] = sorted(x for x in dirs if not (top == str(self.folder) and x == "out") and x != "__pycache__")
            for n in sorted(names):
                f = Path(top) / n
                if n.endswith(".py"):
                    rel = f.relative_to(self.folder).as_posix()
                    src.append([rel, "link:" + os.readlink(f) if f.is_symlink() else _file_hash(f)])
        s = {k: v for k, v in asdict(settings).items() if k not in NOT_GEOMETRY}
        return hashlib.sha256(json.dumps([CACHE_VERSION, "build", src, key, repr(d), repr(sorted(s.items())),
                                          code_version(), _file_hash(Path(__file__)), build123d.__version__,
                                          getattr(OCP, "__version__", "?")]).encode()).hexdigest()[:32]

    # --- reading ---

    def _usable(self, path: Path) -> bool:
        import os

        return self.ok and not self.cfg.fresh and not os.path.islink(self.dir) and not os.path.islink(path)

    def _note(self, stem: str) -> dict | None:
        import json

        path = self.dir / f"{stem}.json"
        if not self._usable(path):
            return None
        try:
            note = json.loads(path.read_text(encoding="utf-8"))
            return note if isinstance(note, dict) and self._inputs_ok(note["inputs"]) else None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):  # missing or broken: a miss
            return None

    def _inputs_ok(self, inputs: dict) -> bool:
        import os

        for rel, h in inputs.items():
            real = os.path.realpath(self.folder / rel)
            if not _within(real, str(self.folder)) or _within(real, str(self.out)) or self._fp(real) != h:
                return False
        return True

    def _fp(self, real: str) -> str | None:
        if real not in self._fps:
            self._fps[real] = _fingerprint(real)
        return self._fps[real]

    def _shape(self, stem: str, note: dict):
        """The piece saved as <stem>.brep, if its hash, faces and volume match the note."""
        import build123d
        from build123d import import_brep

        path = self.dir / f"{stem}.brep"
        if not self._usable(path) or note.get("type") not in SHAPE_TYPES:
            return None
        try:
            if _file_hash(path) != note["sha256"]:
                return None
            shape = getattr(build123d, note["type"])(import_brep(path).wrapped)
            if len(shape.faces()) != note["faces"] or abs(shape.volume - note["volume"]) > 1e-6 * max(1.0, abs(note["volume"])):
                return None
            if note.get("label"):
                shape.label = str(note["label"])
            if note.get("color"):
                shape.color = build123d.Color(*note["color"])
        except Exception:  # noqa: BLE001 - an unreadable BREP or a broken note is a miss, never an error
            return None
        return shape

    def names(self) -> list[str] | None:
        note = self._note("names")
        names = note.get("names") if note else None
        return list(names) if isinstance(names, list) and all(isinstance(n, str) for n in names) else None

    def load(self, name: str) -> tuple | None:
        """(piece, {"faces", "seconds"}) or None."""
        stem = _stem("piece", name)
        note = self._note(stem)
        if note is None or note.get("name") != name:
            return None
        shape = self._shape(stem, note)
        secs = note.get("seconds")
        return None if shape is None else (shape, {"faces": note["faces"], "seconds": secs if isinstance(secs, (int, float)) else None})

    def load_assembly(self) -> list | None:
        note = self._note("assembly")
        if note is None:
            return None
        out = []
        try:
            for i, it in enumerate(note["items"]):
                shape = self._shape(f"assembly-{i}", it)
                if shape is None:
                    return None
                out.append(shape if it.get("bare") else (shape, *[tuple(c) if isinstance(c, list) else c for c in it["rest"]]))
        except (KeyError, TypeError, AttributeError):  # a broken note: a miss
            return None
        return out

    # --- writing ---

    def _inputs(self) -> dict | None:
        """{path in the part's folder: fingerprint} for the files read so far, or None (and why, in
        `skipped`) when one of them is elsewhere in the workspace."""
        import os

        ws = os.path.realpath(self.cfg.workspace)
        out = {}
        for raw in dict.fromkeys(self.cfg.reads.paths):
            real = os.path.realpath(raw)
            if (any(_within(real, s) for s in self._skip) or os.path.basename(real) == "b123d-print.toml"
                    or os.path.normcase(real) in self._import_dirs):
                continue  # Python and the libraries, this build's output, settings: all in the key
            if _within(real, str(self.folder)):
                if not real.endswith((".py", ".pyc")):  # the sources are in the key
                    out[Path(os.path.relpath(real, self.folder)).as_posix()] = self._fp(real)
            elif _within(real, ws):
                f = Path(real)
                if f.parent.name == "__pycache__":  # an import looks for the compiled module first: name the source
                    f = f.parent.parent / (f.name.split(".")[0] + ".py")
                self.skipped = f"not cached: the build read {Path(os.path.relpath(f, ws)).as_posix()}, outside the part's folder"
                return None
        return out

    def _ready(self) -> bool:
        """May this build write now? Makes the folder and, once, removes the variant's older entries."""
        import os
        import shutil

        if not self.ok:
            return False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            if os.path.islink(self.dir):
                return False
            if not self._pruned:
                self._pruned = True
                for p in self.root.iterdir():
                    if p.name.startswith(self.prefix) and p.name != self.dir.name and p.is_dir() and not p.is_symlink():
                        shutil.rmtree(p, ignore_errors=True)
            return True
        except OSError:
            return False

    def _put(self, stem: str, shape) -> dict | None:
        """Write the BREP; the note's shape fields, or None when it cannot be cached."""
        import os

        from build123d import export_brep

        import build123d

        kind = next((t for t in SHAPE_TYPES if isinstance(shape, getattr(build123d, t))), None)
        if kind is None or not self._ready():
            return None
        path = self.dir / f"{stem}.brep"
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            if not export_brep(shape, tmp):
                return None
            h = _file_hash(tmp)
            os.replace(tmp, path)
            color = tuple(shape.color) if getattr(shape, "color", None) is not None else None
            return {"type": kind, "sha256": h, "faces": len(shape.faces()), "volume": shape.volume,
                    "label": getattr(shape, "label", "") or "", "color": color}
        except Exception:  # noqa: BLE001 - a cache that cannot be written is no cache, not an error
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None

    def save_names(self, names: list) -> None:
        inputs = self._inputs()
        if inputs is not None and all(isinstance(n, str) for n in names) and self._ready():
            _write_json(self.dir / "names.json", {"names": names, "inputs": inputs})

    def save(self, name: str, shape, stats: dict) -> None:
        inputs = self._inputs()
        if inputs is None or not isinstance(name, str):
            return
        stem = _stem("piece", name)
        fields = self._put(stem, shape)
        if fields is not None:
            _write_json(self.dir / f"{stem}.json", {"name": name, **fields, "seconds": stats.get("seconds"), "inputs": inputs})

    def save_assembly(self, items: list, seconds: float) -> None:
        from build123d import Shape

        inputs = self._inputs()
        if inputs is None:
            return
        notes = []
        for i, it in enumerate(items):
            bare = isinstance(it, Shape)
            shape, rest = (it, []) if bare else (it[0], list(it[1:]) if isinstance(it, (list, tuple)) else None)
            if rest is None or not all(r is None or isinstance(r, str) or _rgb(r) for r in rest):
                return  # a color or label the JSON note cannot hold: not cached
            fields = self._put(f"assembly-{i}", shape)
            if fields is None:
                return
            notes.append({**fields, "bare": bare, "rest": [list(r) if isinstance(r, tuple) else r for r in rest]})
        _write_json(self.dir / "assembly.json", {"items": notes, "seconds": seconds, "inputs": inputs})


def _within(path: str, root: str) -> bool:
    import os

    p, r = os.path.normcase(path), os.path.normcase(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _file_hash(path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fingerprint(real: str) -> str | None:
    """A file's hash, a folder's sorted entry names (hashed), or None when it does not exist."""
    import hashlib
    import os

    try:
        if os.path.isdir(real):
            return "dir:" + hashlib.sha256("\n".join(sorted(os.listdir(real))).encode()).hexdigest()
        return _file_hash(real) if os.path.exists(real) else None
    except OSError:
        return "unreadable"


def _stem(kind: str, name: str) -> str:
    import hashlib

    return f"{kind}-{hashlib.sha256(name.encode()).hexdigest()[:16]}"  # no piece name ever becomes a path


def _rgb(c) -> bool:
    return isinstance(c, (list, tuple)) and 3 <= len(c) <= 4 and all(isinstance(x, (int, float)) for x in c)


def _write_json(path: Path, data: dict) -> None:
    import json
    import os

    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, default=_plain), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:  # a read-only folder: no cache
        pass


class Outputs:
    """What export wrote, kept next to the build cache so an export of unchanged pieces writes
    nothing again (#75): out/.cache/out-<file>.json per output file, with the key of what it was
    made from and the file's size and time as written. A file is current when its stamp has the
    same key and the file is still the one written (same size and time: one edited, replaced or
    removed is written again). Keys: `key()` over the shapes' geometry (shape_fingerprint), their
    names, colors and labels, the file's own arguments, and the code that writes (b123d-print's
    version and these modules' source, build123d, OCP, matplotlib). fresh writes everything."""

    def __init__(self, build: BuildCache):
        self.build = build
        self._fps: dict[int, str] = {}
        self._base: str | None = None

    def fingerprint(self, shape) -> str:
        if id(shape) not in self._fps:
            self._fps[id(shape)] = shape_fingerprint(shape)
        return self._fps[id(shape)]

    def key(self, *what) -> str:
        """A key over `what`: shapes by their geometry, color and label; anything else by repr."""
        import hashlib
        import json

        from build123d import Shape

        if self._base is None:
            import build123d
            import matplotlib
            import OCP

            from importlib import import_module

            mods = [import_module(f"{__package__}.{m}") for m in ("project", "render", "templates", "viewer")]  # never b123d_print.render, the function
            here = [_file_hash(Path(m.__file__)) for m in mods]
            self._base = json.dumps([CACHE_VERSION, "output", here, code_version(), build123d.__version__,
                                     getattr(OCP, "__version__", "?"), matplotlib.__version__])

        def one(x):
            if isinstance(x, Shape):
                color = getattr(x, "color", None)
                return ["shape", self.fingerprint(x), repr(getattr(x, "label", "")), repr(tuple(color) if color is not None else None)]
            if isinstance(x, (list, tuple)):
                return [one(v) for v in x]
            return repr(x)

        return hashlib.sha256(json.dumps([self._base, one(list(what))]).encode()).hexdigest()[:32]

    def _stamp(self, f: Path) -> Path:
        import hashlib
        import os

        return self.build.root / f"out-{hashlib.sha256(os.path.abspath(f).encode()).hexdigest()[:20]}.json"

    def current(self, f: Path, key: str) -> bool:
        """Is `f` there, as written for `key`?"""
        import json
        import os

        stamp = self._stamp(f)
        if self.build.cfg.fresh or not self.build.ok or os.path.islink(stamp) or os.path.islink(f):
            return False
        try:
            st, note = f.stat(), json.loads(stamp.read_text(encoding="utf-8"))
            return note["key"] == key and note["size"] == st.st_size and note["mtime"] == st.st_mtime_ns
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def wrote(self, f: Path, key: str) -> None:
        import os

        if not self.build.ok or os.path.islink(self.build.root):
            return
        try:
            st = Path(f).stat()
            self.build.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        _write_json(self._stamp(Path(f)), {"key": key, "size": st.st_size, "mtime": st.st_mtime_ns})

    def write(self, f: Path, key: str, make) -> Path:
        """`f`, written by make() unless it is current; stamped."""
        if self.current(f, key):
            return f
        made = Path(make())
        self.wrote(made, key)
        return made


EXPORT_ORDER = ("step", "stl", "3mf", "png", "glb")  # export_files' order


def export_part(p, out: Path, name: str, formats, outputs: Outputs | None, template: bool = False) -> list[Path]:
    """export_files into out/'s folders (outdir.folder: print/, cad/, images/; a template's print
    files in print/templates/), skipping the files `outputs` says are current (each format on its own)."""
    files = []
    for fmt in (f for f in EXPORT_ORDER if f in formats):
        f = outdir.path(out, f"{name}.{fmt}", template)

        def write(fmt=fmt, f=f):
            return export_files(p, f.parent, name, [fmt])[0]

        files.append(outputs.write(f, outputs.key("part", name, fmt, p), write) if outputs is not None else write())
    return files


TEMPLATE_TYPES = ("Part", "Compound", "Solid", "Face")  # what a template's shapes are saved as


class TemplateCache:
    """Fit-test templates (templates.make) saved in out/.cache/template-<slot>-<key>/ and read back
    instead of made again: a template is a function of the piece it is cut from (its geometry), the
    Template spec, the label text and the code. A broken or mismatched entry is a miss."""

    def __init__(self, build: BuildCache, outputs: Outputs):
        self.build, self.outputs = build, outputs

    def _dir(self, variant: str, pname: str, spec, part, label_name: str) -> Path:
        import hashlib
        import json

        slot = hashlib.sha256(json.dumps([variant, pname, spec.ident()]).encode()).hexdigest()[:12]
        return self.build.root / f"template-{slot}-{self.outputs.key('template', spec, label_name, part)}"

    def get(self, d: Path):
        import json
        import os

        import build123d
        from build123d import import_brep

        from . import templates as tp

        if self.build.cfg.fresh or not self.build.ok or os.path.islink(d):
            return None
        try:
            note = json.loads((d / "note.json").read_text(encoding="utf-8"))
            shapes = {}
            for k in ("part", "where"):
                n = note[k]
                path = d / f"{k}.brep"
                if n["type"] not in TEMPLATE_TYPES or os.path.islink(path) or _file_hash(path) != n["sha256"]:
                    return None
                got = import_brep(path)
                shapes[k] = got if type(got).__name__ == n["type"] else getattr(build123d, n["type"])(got.wrapped)
            return note["id"], tp.Made(shapes["part"], shapes["where"], note["info"], [_tuples(b) for b in note["ignore"]])
        except Exception:  # noqa: BLE001 - a broken entry is a miss, never an error
            return None

    def save(self, d: Path, tid: str, made) -> None:
        import json
        import os
        import shutil

        from build123d import export_brep

        if not self.build.ok or os.path.islink(self.build.root):
            return
        try:
            note = json.loads(json.dumps({"id": tid, "info": made.info, "ignore": made.ignore}))
        except (TypeError, ValueError):  # info that JSON cannot hold: not cached
            return
        try:
            d.mkdir(parents=True, exist_ok=True)
            for k in ("part", "where"):
                shape = getattr(made, k)
                kind = type(shape).__name__
                path = d / f"{k}.brep"
                if kind not in TEMPLATE_TYPES or not export_brep(shape, path):
                    return
                note[k] = {"type": kind, "sha256": _file_hash(path)}
            _write_json(d / "note.json", note)
            for p in self.build.root.glob(d.name[:len("template-") + 12] + "-*"):
                if p.name != d.name and p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p, ignore_errors=True)
        except Exception:  # noqa: BLE001 - a cache that cannot be written is no cache, not an error
            return


def _tuples(x):
    return tuple(_tuples(v) for v in x) if isinstance(x, list) else x


def make_pieces(mod: ModuleType, key: str, d, settings: Settings, cache: CacheConfig | None = None) -> Pieces:
    """The pieces of one variant, through the build cache when `cache` is given (the worker), the
    script builds pieces (not a module-level `part`) and B123D_PRINT_NO_CACHE is not set."""
    use = cache is not None and hasattr(mod, "build") and getattr(mod, "__file__", None) and not no_cache_env()
    return Pieces(mod, d, BuildCache(mod, key, d, settings, cache) if use else None)


INHERITABLE = (ck.Overhang, ck.ThinFeature, ck.Holes, ck.BedEdge, ck.TipOver, ck.Gap)  # automatic checks also run on the original
ORIGINAL = "original"


def import_finding(info) -> ck.Finding:
    """What import_model did with a reference file: a WARN when its units look wrong."""
    msg = info.summary()
    extra = info.repairs + info.notes + info.warnings
    if extra:
        msg += ". " + ". ".join(extra)
    return ck.Finding(ck.WARN if info.warnings else ck.OK, "import", Path(info.file).name, msg,
                      {k: v for k, v in info.__dict__.items() if k != "metadata"} | {"metadata": info.metadata})


def setup_findings(mod: ModuleType, findings: list[ck.Finding]) -> list[ck.Finding]:
    """Reminders about settings the part depends on but nobody has set: holes are modeled true to
    size and print small unless the slicer's X-Y hole compensation corrects them (BP-H1); set
    hole_comp (0 once the slicer is set, or an opt-in value) and the reminder stops."""
    return setup_findings_for(findings, hole_comp_source(getattr(mod, "__file__", None)) is not None)


def setup_findings_for(findings: list[ck.Finding], hole_comp_set: bool) -> list[ck.Finding]:
    n = sum(len(f.data.get("holes", [])) for f in findings if f.check == "holes")
    if not n or hole_comp_set:
        return []
    return [ck.Finding(ck.WARN, "hole_comp", "settings",
                       f"this part has {n} round hole(s), modeled true to size: set your slicer's X-Y hole "
                       "compensation for them (once per printer and material: print the hole_coupon example, "
                       "`b123d-print new coupon --from hole_coupon`, and enter half the diameter error). Then "
                       "`b123d-print printer calibrate hole_comp 0` (or save_setup(hole_comp=0)) records it and "
                       "this reminder stops",
                       {"holes": n})]


def export_variant(mod: ModuleType, script: Path, key: str, out: Path | None = None, formats=None,
                   only=None, cache: CacheConfig | None = None, review: list[str] | None = None) -> dict:
    """Export every printable part in `formats` (default: the `formats` setting), plus the
    assembly render and section views when png is among them, and the print sheet
    (<name>[_<variant>]_print.md, printsheet.py) when print is, and whole-assembly BOM JSON
    (<name>[_<variant>]_hardware.json) when hardware is, the shopping list as Markdown
    (<name>[_<variant>]_bom.md) and CSV (_bom.csv) when bom and bom_csv are. Returns a summary, with the timing
    report (Pieces.timing) under "timing".
    only: just these pieces (comma-separated or a list): no assembly render, and only the views
    and templates of those pieces. cache: build through the build cache (the worker). review: the
    print sheet's "Design review" lines (the MCP server's review checklist, review.py)."""
    settings = load_settings(script)
    formats = formats or settings.formats
    out = out or script.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    outdir.tidy(out)  # files of the flat layout before 0.3.11 into their folders: never both layouts
    d = dims(mod, key)
    pc = make_pieces(mod, key, d, settings, cache)
    outputs = Outputs(pc.cache) if pc.cache is not None else None
    from . import hardware

    hardware_items = hardware.declared(mod, d) if {"print", "hardware", "bom", "bom_csv"}.intersection(formats) else None
    parts, orig, _ = built(mod, d, pc, only)
    names = {n or "part" for n in parts}
    asm = None if only or "png" not in formats else pc.assembly()  # only the renders use it
    summary = {"variant": key or "standard", "parts": {}, "files": []}
    for pname, p in parts.items():
        name = out_name(script.stem, key, pname)
        files = export_part(p, out, name, formats, outputs)
        summary["parts"][pname or "part"] = report(p)
        summary["files"] += [str(f) for f in files]
    tf = getattr(mod, "templates", None)
    for spec in tf(d) if tf else []:
        if only and (spec.part or "part") not in names:
            continue
        r = write_template(script, key, parts, spec, out, formats, outputs=outputs, size="small")
        summary.setdefault("templates", {})[r["name"]] = r["report"]
        summary["files"] += r["files"]
    if "print" in formats:  # the print sheet: one per variant, every piece exported in this run
        from . import printsheet

        title = out_name(script.stem, key, "")
        text = printsheet.sheet(mod, d, parts, settings, title, hardware_items=hardware_items,
                                variant=key, hardware_resolved=True, review=review)
        f = _export_text(outdir.path(out, f"{out_name(script.stem, key, 'print')}.md"), text, outputs)
        summary["files"].append(str(f))
    if "hardware" in formats:
        text = hardware.json_text(hardware_items, key)
        f = _export_text(outdir.path(out, f"{out_name(script.stem, key, 'hardware')}.json"), text, outputs)
        summary["files"].append(str(f))
    if "bom" in formats:
        import datetime

        text = hardware.bom_file_markdown(hardware_items, script.stem, key, datetime.date.today().isoformat())
        f = _export_text(outdir.path(out, f"{out_name(script.stem, key, 'bom')}.md"), text, outputs)
        summary["files"].append(str(f))
    if "bom_csv" in formats:
        f = _export_text(outdir.path(out, f"{out_name(script.stem, key, 'bom')}.csv"), hardware.bom_file_csv(hardware_items), outputs,
                         newline="")
        summary["files"].append(str(f))
    summary["timing"] = pc.timing()
    if "png" not in formats:
        outdir.readme(out, script.stem)
        return summary
    if asm:
        f, title = outdir.path(out, f"{out_name(script.stem, key, 'assembly')}.png"), f"{out_name(script.stem, key, '')} assembly"
        f = (outputs.write(f, outputs.key("assembly", title, asm), lambda: render(asm, f, title)) if outputs is not None
             else render(asm, f, title))
        summary["files"].append(str(f))
    if orig is not None:
        r = before_after(orig, parts, out, out_name(script.stem, key, ""))
        summary["files"] += r["files"]
        summary["original"] = {"score": r["score"], "text": r["text"]}
    vf = getattr(mod, "views", None)
    for i, v in enumerate(vf(d) if vf else []):
        if only and not (v.parts and set(v.parts) <= names):
            continue
        if v.parts:
            sel = [(parts[n], None, n or "part") for n in v.parts]
        else:
            sel = asm or [(p, None, n or "part") for n, p in parts.items()]
        title = out_name(script.stem, key, "")
        f, caption = outdir.path(out, f"{title}_{v.plane.lower()}{round(v.at, 3):g}.png"), f"{title}{', ' + v.title if v.title else ''}"

        def draw(sel=sel, v=v, f=f, caption=caption):
            return section_view(sel, v.plane, v.at, f, caption)

        f = outputs.write(f, outputs.key("section", v.plane, v.at, caption, sel), draw) if outputs is not None else draw()
        summary["files"].append(str(f))
    outdir.readme(out, script.stem)
    return summary


def _export_text(path: Path, text: str, outputs: Outputs | None, newline: str | None = None) -> Path:
    """Cache by final text: declaration, dimensions, notes and settings cannot leave stale BOMs.
    newline="": write the line ends as they are (CSV's CRLF)."""
    def write():
        path.write_text(text, encoding="utf-8", newline=newline)
        return path

    return outputs.write(path, outputs.key("text", text), write) if outputs is not None else write()


def write_template(script: Path, key: str, parts: dict, spec, out: Path, formats, settings=None,
                   outputs: Outputs | None = None, size: str = "normal") -> dict:
    """Make one fit-test template (templates.Template) from the built parts and write it as
    <name>[_<variant>]_template_<id>.<fmt>; with png also <...>_where.png, the part with the
    template's source in red. settings: also run the print checks on it ("findings").
    outputs: read the template from the TemplateCache and skip the files that are current
    (export, in the worker); size: of the two PNGs."""
    from . import templates as tp

    pname, part = tp.pick_part(parts, spec.part)
    label_name = script.stem if pname == "part" else f"{script.stem} {pname}"
    tc = TemplateCache(outputs.build, outputs) if outputs is not None else None
    entry = tc._dir(key, pname, spec, part, label_name) if tc is not None else None
    got = tc.get(entry) if tc is not None else None
    if got is not None:
        tid, made = got
    else:
        try:
            tid, made = tp.make(spec, part, label_name)
        except tp.TemplateError as e:
            raise tp.TemplateError(f"template {spec.kind} ({_spec_args(spec)}) of {pname}: {e}") from None
        if tc is not None:
            tc.save(entry, tid, made)
    name = out_name(script.stem, key, f"template_{tid}" if pname == "part" else f"{pname}_template_{tid}")
    files = [str(f) for f in export_part(made.part, out, name, [f for f in formats if f != "png"], outputs, template=True)]
    if "png" in formats:
        shots = [(outdir.path(out, f"{name}.png"), f"{name} (laid flat for printing)",
                  lambda f, t: render(made.part, f, t, size=size), made.part),
                 (outdir.path(out, f"{name}_where.png"), f"{name}: where it comes from (red) on {out_name(script.stem, key, '') or pname}",
                  lambda f, t: tp.highlight(part, [made.where], f, t, size=size), (part, made.where))]
        for f, title, draw, shapes in shots:
            if outputs is not None:
                f = outputs.write(f, outputs.key("template png", title, size, shapes), lambda f=f, t=title, g=draw: g(f, t))
            else:
                f = draw(f, title)
            files.append(str(f))
    res = {"name": name, "id": tid, "part": pname, "variant": key or "standard", "info": made.info,
           "report": report(made.part), "files": files}
    if settings is not None:
        res["findings"] = [finding_dict(f) for f in tp.checks(made, settings)]
    return res


def _spec_args(spec) -> str:
    if spec.kind == "slice":
        return f"{spec.plane} at {spec.at:g}"
    if spec.kind == "face":
        return f"face {spec.face}"
    return f"center {tuple(spec.center)}, size {tuple(spec.size)}"


def before_after(orig: Part, parts: dict, out: Path, stem: str, size: str = "normal") -> dict:
    """A remix next to its original (<stem>_before_after.png) and the original colored by how far
    the remix is from it (<stem>_vs_original.png, compare's deviation view), with compare's score."""
    from build123d import Compound

    from . import compare as cmp
    from .render import side_by_side

    remix_part = next(iter(parts.values())) if len(parts) == 1 else Part(Compound(
        [s for p in parts.values() for s in p.solids()]).wrapped)
    small = "_small" if size == "small" else ""
    a = render(side_by_side([(orig, "original"), (remix_part, "remix")]), outdir.path(out, f"{stem}_before_after{small}.png"),
               f"{stem}: original (left) and remix (right)", size=size)
    r = cmp.compare(orig, remix_part)
    b = cmp.render_comparison(orig, remix_part, r, outdir.path(out, f"{stem}_vs_original{small}.png"),
                              f"{stem}: original, red where the remix differs (score {r.score:.1f})", size=size)
    return {"files": [str(a), str(b)], "score": r.score, "text": r.text(), "metrics": r.metrics}


def run(script_file: str, argv: list[str] | None = None) -> None:
    """`__main__` entry for part scripts: export every variant (or --variant), then run checks."""
    safe_console()
    script = Path(script_file).resolve()
    mod = sys.modules.get("__main__")
    if mod is None or Path(getattr(mod, "__file__", "")).resolve() != script:
        mod = load(script)
    ap = argparse.ArgumentParser(description=f"Build {script.stem}")
    ap.add_argument("--variant", choices=[v or "standard" for v in variants(mod)], help="default: all")
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--formats", help="comma-separated: step,stl,3mf,png,glb,print,hardware,bom,bom_csv or all (default: the formats setting)")
    ap.add_argument("--only", metavar="PIECES", help="comma-separated piece names from build(): build and export only "
                                                      "those (lazy pieces: the others are never built)")
    args = ap.parse_args(argv)
    settings = load_settings(script)
    worst = 0
    nudged = False
    for key in variants(mod):
        if args.variant and variant_key(args.variant) != key:
            continue
        s = export_variant(mod, script, key, formats=parse_formats(args.formats) if args.formats else None, only=args.only)
        for pname, r in s["parts"].items():
            print(f"{out_name(script.stem, key, '' if pname == 'part' else pname)}: "
                  f"{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, volume {r['volume']:.1f} mm^3, valid={r['valid']}")
        for line in timing_lines(s["timing"]):
            print("  " + line)
        print(f"  -> {len(s['files'])} files in {script.parent / 'out'} (slicer files in print/; see out/README.md)")
        if settings.hole_comp or settings.hole_comp_h:
            from .setup import hole_note

            print("  " + hole_note(settings))
        if args.only and not args.no_check:
            print("  checks skipped with --only: they need every piece (run without --only, or b123d-print check)")
        if not args.no_check and not args.only:
            for f in run_checks(mod, key, settings, nudge=not nudged):
                nudged |= f.check == "hole_comp"
                if f.level != ck.OK:
                    print("  " + f.line())
                worst = max(worst, {"ok": 0, "warn": 0, "fail": 1}[f.level])
    sys.exit(worst)
