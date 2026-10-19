"""Part-script convention and the runner behind `b123d-print build` / `b123d-print check` / the MCP tools.

A part script lives at <parts_dir>/<name>/<name>.py and defines:

    @dataclass(frozen=True)
    class Dims: ...                  # UPPER_CASE fields in mm; derived values as properties
    VARIANTS = {"": {}, "big": dict(WIDTH=80.0)}   # overrides only; "" is the standard part
    def build(d) -> Part | dict[str, Part]          # printable parts, in PRINT orientation

and optionally:

    def assembly(d) -> list[(Part, color, label)]   # assembled position, incl. stand-ins for
                                                    # the things it mates with -> overlap check
    def views(d) -> list[View]                      # section views saved on export
    def checks(d) -> list[Wall | Overhang | Gap | ...]  # automatic per part: Overhang, ThinFeature,
                                                    # Holes, BedEdge, Gap, Fit
    def original(d) -> Part                         # remixes: the original as placed in the remix
                                                    # (default: what build() loaded with import_model)
    def templates(d) -> list[Template]              # fit-test templates exported with every variant

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
from dataclasses import dataclass, is_dataclass, replace
from pathlib import Path
from types import ModuleType

from build123d import Part

from . import checks as ck
from .config import Settings, hole_comp_source, load_settings, parse_formats, safe_console
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
    if hasattr(mod, "build"):
        r = mod.build(d) if d is not None else mod.build()
    elif hasattr(mod, "part"):
        r = mod.part
    else:
        raise AttributeError("script defines neither build(d) nor a module-level `part`")
    return dict(r) if isinstance(r, dict) else {"": r}


def built(mod: ModuleType, d) -> tuple[dict[str, Part], Part | None, list]:
    """printables() plus the remix's original: what `original(d)` returns, else what build() loaded
    with import_model (None for a part that is not a remix), and the import records."""
    from . import remix

    remix.reset_imports()
    parts = printables(mod, d)
    imports = list(remix.IMPORTED)
    f = getattr(mod, "original", None)
    if f is not None:
        orig = f(d) if d is not None else f()
        imports += remix.IMPORTED[len(imports):]
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
    if asm and not any(isinstance(s, ck.Overlap) for s in specs):
        specs.append(ck.Overlap())
    fitted = {s.part or "part" for s in specs if isinstance(s, ck.Fit)}
    specs += [ck.Fit(p) for p in parts if p not in fitted]  # no-op without a printer profile
    # automatic per-part checks; a script lists one itself to change its arguments
    for cls in (ck.ThinFeature, ck.Holes, ck.BedEdge):
        listed = {s.part or "part" for s in specs if isinstance(s, cls)}
        specs += [cls(p) for p in parts if p not in listed]
    gapped = {s.part or "part" for s in specs if isinstance(s, ck.Gap) and s.other is None}
    specs += [ck.Gap(p) for p in parts if p not in gapped]  # no-op for a single solid
    return specs


def run_checks(mod: ModuleType, key: str, settings: Settings, nudge: bool = True,
               deadline: float | None = None) -> list[ck.Finding]:
    """Build one variant and run every check. Never raises: errors become findings.
    nudge: also add the setup reminders (hole_comp never measured); callers pass it for the
    first variant only, so a check run says it once.
    deadline: a time.time() by which to stop (the worker's soft limit, below the hard timeout
    that kills it). A check still running then is interrupted; the result is every finding
    finished so far plus a "timeout" FAIL naming the check that was running and those not run.
    The MCP server runs the same checks split over several workers (check_share, merge_shares)."""
    return merge_shares([check_share(mod, key, settings, deadline=deadline)], nudge)


# A check run is a list of items: each check spec on the printable parts ("<i>:part") and, for a
# remix, the automatic ones again on the original ("<i>:original"). check_share runs the items of
# one share; merge_shares puts the shares' findings back in spec order and labels inherited ones.
# Shares are what the MCP server runs in parallel workers: every worker builds the part (from
# import_model's cache) and computes the same partition, so no worker needs another's result.

COST_MIN_SPLIT = 4.0  # estimated seconds: a smaller check run is not worth splitting (a worker takes ~3 s to start)


def check_share(mod: ModuleType, key: str, settings: Settings, share: tuple[int, int] = (0, 1),
                deadline: float | None = None, started: float | None = None) -> dict:
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
                parts, orig, imports = built(mod, d)
                asm = assembly(mod, d)
            except CheckTimeout:
                raise
            except Exception as e:
                res["error"] = finding_dict(ck.Finding(ck.FAIL, "error", tag, f"build failed: {e!r}",
                                                       {"traceback": traceback.format_exc()}))
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
            costs = [0.01 if side == "original" and started is not None
                     and originals.cached_before(replace(specs[i], part=ORIGINAL), started)
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
                        found = spec.run(lookup, asm, settings)
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


def shape_fingerprint(shape) -> str:
    """A hash of a solid's geometry that survives a BREP round trip (unlike the BREP text)."""
    import hashlib

    import numpy as np

    pts = [(v.X, v.Y, v.Z) for v in shape.vertices()]
    a = np.round(np.array(pts, float).reshape(-1, 3), 4) + 0.0  # + 0.0: no -0.0
    a = a[np.lexsort(a.T[::-1])] if len(a) else a
    h = hashlib.sha256(a.tobytes())
    h.update(f"|{len(shape.faces())}|{len(shape.edges())}|{shape.volume:.3f}".encode())
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


INHERITABLE = (ck.Overhang, ck.ThinFeature, ck.Holes, ck.BedEdge, ck.Gap)  # automatic checks also run on the original
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
    """Reminders about settings the part depends on but nobody has set: hole_comp is 0 until it
    is measured, so a part with holes gets them at nominal size, which prints small (BP-H1)."""
    return setup_findings_for(findings, hole_comp_source(getattr(mod, "__file__", None)) is not None)


def setup_findings_for(findings: list[ck.Finding], hole_comp_set: bool) -> list[ck.Finding]:
    n = sum(len(f.data.get("holes", [])) for f in findings if f.check == "holes")
    if not n or hole_comp_set:
        return []
    return [ck.Finding(ck.WARN, "hole_comp", "settings",
                       f"this part has {n} round hole(s) and hole_comp has never been set (user config, workspace, "
                       "calibration or environment), so they are cut at nominal size and print small. Print the "
                       "hole_coupon example (`b123d-print new coupon --from hole_coupon`), then store the result with "
                       "`b123d-print printer hole-comp <value>` or `hole_comp = <value>` in your user config",
                       {"holes": n})]


def export_variant(mod: ModuleType, script: Path, key: str, out: Path | None = None, formats=None) -> dict:
    """Export every printable part in `formats` (default: the `formats` setting), plus the
    assembly render and section views when png is among them. Returns a summary."""
    formats = formats or load_settings(script).formats
    out = out or script.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    d = dims(mod, key)
    parts, orig, _ = built(mod, d)
    asm = assembly(mod, d)
    summary = {"variant": key or "standard", "parts": {}, "files": []}
    for pname, p in parts.items():
        name = out_name(script.stem, key, pname)
        files = export_files(p, out, name, formats)
        summary["parts"][pname or "part"] = report(p)
        summary["files"] += [str(f) for f in files]
    tf = getattr(mod, "templates", None)
    for spec in tf(d) if tf else []:
        r = write_template(script, key, parts, spec, out, formats)
        summary.setdefault("templates", {})[r["name"]] = r["report"]
        summary["files"] += r["files"]
    if "png" not in formats:
        return summary
    if asm:
        f = render(asm, out / f"{out_name(script.stem, key, 'assembly')}.png", f"{out_name(script.stem, key, '')} assembly")
        summary["files"].append(str(f))
    if orig is not None:
        r = before_after(orig, parts, out, out_name(script.stem, key, ""))
        summary["files"] += r["files"]
        summary["original"] = {"score": r["score"], "text": r["text"]}
    vf = getattr(mod, "views", None)
    for i, v in enumerate(vf(d) if vf else []):
        if v.parts:
            sel = [(parts[n], None, n or "part") for n in v.parts]
        else:
            sel = asm or [(p, None, n or "part") for n, p in parts.items()]
        title = out_name(script.stem, key, "")
        f = section_view(sel, v.plane, v.at, out / f"{title}_{v.plane.lower()}{round(v.at, 3):g}.png",
                         f"{title}{', ' + v.title if v.title else ''}")
        summary["files"].append(str(f))
    return summary


def write_template(script: Path, key: str, parts: dict, spec, out: Path, formats, settings=None) -> dict:
    """Make one fit-test template (templates.Template) from the built parts and write it as
    <name>[_<variant>]_template_<id>.<fmt>; with png also <...>_where.png, the part with the
    template's source in red. settings: also run the print checks on it ("findings")."""
    from . import templates as tp

    pname, part = tp.pick_part(parts, spec.part)
    label_name = script.stem if pname == "part" else f"{script.stem} {pname}"
    try:
        tid, made = tp.make(spec, part, label_name)
    except tp.TemplateError as e:
        raise tp.TemplateError(f"template {spec.kind} ({_spec_args(spec)}) of {pname}: {e}") from None
    name = out_name(script.stem, key, f"template_{tid}" if pname == "part" else f"{pname}_template_{tid}")
    files = [str(f) for f in export_files(made.part, out, name, [f for f in formats if f != "png"])]
    if "png" in formats:
        files.append(str(render(made.part, out / f"{name}.png", f"{name} (laid flat for printing)")))
        files.append(str(tp.highlight(part, [made.where], out / f"{name}_where.png",
                                      f"{name}: where it comes from (red) on {out_name(script.stem, key, '') or pname}")))
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
    a = render(side_by_side([(orig, "original"), (remix_part, "remix")]), out / f"{stem}_before_after{small}.png",
               f"{stem}: original (left) and remix (right)", size=size)
    r = cmp.compare(orig, remix_part)
    b = cmp.render_comparison(orig, remix_part, r, out / f"{stem}_vs_original{small}.png",
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
    ap.add_argument("--formats", help="comma-separated: step,stl,3mf,png or all (default: the formats setting)")
    args = ap.parse_args(argv)
    settings = load_settings(script)
    worst = 0
    nudged = False
    for key in variants(mod):
        if args.variant and variant_key(args.variant) != key:
            continue
        s = export_variant(mod, script, key, formats=parse_formats(args.formats) if args.formats else None)
        for pname, r in s["parts"].items():
            print(f"{out_name(script.stem, key, '' if pname == 'part' else pname)}: "
                  f"{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, volume {r['volume']:.1f} mm^3, valid={r['valid']}")
        print(f"  -> {len(s['files'])} files in {script.parent / 'out'}")
        if not args.no_check:
            for f in run_checks(mod, key, settings, nudge=not nudged):
                nudged |= f.check == "hole_comp"
                if f.level != ck.OK:
                    print("  " + f.line())
                worst = max(worst, {"ok": 0, "warn": 0, "fail": 1}[f.level])
    sys.exit(worst)


def find_parts(root: Path, parts_dir: str) -> list[Path]:
    base = root / parts_dir
    return sorted(p / f"{p.name}.py" for p in base.iterdir() if (p / f"{p.name}.py").is_file()) if base.is_dir() else []


def resolve_part(spec: str, root: Path, parts_dir: str) -> Path:
    """A part name (folder under parts_dir) or a path to a script."""
    p = Path(spec)
    if p.suffix == ".py" and p.is_file():
        return p.resolve()
    cand = root / parts_dir / spec / f"{spec}.py"
    if cand.is_file():
        return cand.resolve()
    raise FileNotFoundError(f"no part '{spec}' (looked for {cand})")
