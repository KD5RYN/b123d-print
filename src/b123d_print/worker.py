"""Worker process: runs ONE operation on a part script (or compares two mesh files, or describes a
reference model) and writes a JSON result.

Started by b123d_print.sandbox inside an OS sandbox where one is available. Part scripts are
model-written code, so before the script is imported this process installs an audit hook that
refuses network access, starting processes, ctypes and file writes outside the allowed folders.
The hook is defense in depth, not a security boundary on its own: the OS sandbox (or Docker)
is what enforces the limits.

    python -m b123d_print.worker <job.json>
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# Import everything heavy before the hook goes in, so library start-up (which may legitimately
# use ctypes or subprocess) is not affected.
import matplotlib  # noqa: F401

matplotlib.use("Agg")
import matplotlib.pyplot  # noqa: E402,F401
import numpy  # noqa: E402,F401
import build123d  # noqa: E402,F401
import ctypes  # noqa: E402,F401  (opens the process handle at import; must happen before the guard)
import lib3mf  # noqa: E402,F401  (3MF export)

from b123d_print import checks as ck  # noqa: E402
from b123d_print.config import load_settings, parse_formats  # noqa: E402
from b123d_print.project import (  # noqa: E402
    assembly,
    before_after,
    built,
    check_share,
    dims,
    export_variant,
    load,
    printables,
    run_checks,
    variants,
)
from b123d_print import remix  # noqa: E402
import scipy.sparse.csgraph  # noqa: E402,F401  (import_model's mesh repair, loaded before the guard)
from b123d_print.render import render, report, section_view, side_by_side  # noqa: E402
from b123d_print import compare as cmp  # noqa: E402  (scipy's k-d tree, loaded before the guard)
from b123d_print import metrics  # noqa: E402
import scipy.ndimage  # noqa: E402,F401  (design_metrics' water-trap labelling, loaded before the guard)

BLOCKED_EVENTS = (
    "socket.",  # connect, bind, getaddrinfo, ...
    "subprocess.",
    "os.system",
    "os.exec",
    "os.fork",
    "os.forkpty",
    "os.posix_spawn",
    "os.spawn",
    "os.startfile",
    "pty.",
    "webbrowser.",
    "urllib.",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "telnetlib.",
    "sys.addaudithook",  # no hook that could swallow ours
    # Windows: starting processes below subprocess, and registry writes
    "_winapi.CreateProcess",
    "winreg.ConnectRegistry",
    "winreg.CreateKey",
    "winreg.DeleteKey",
    "winreg.DeleteValue",
    "winreg.LoadKey",
    "winreg.SaveKey",
    "winreg.SetValue",
)
BLOCKED_IMPORTS = {"_posixsubprocess", "socket", "_socket", "ssl", "_ssl", "subprocess"}
WRITE_EVENTS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.truncate", "os.chmod", "os.symlink", "os.link"}


class SandboxViolation(PermissionError):
    pass


# ctypes is allowed only for the native libraries of known dependencies (lib3mf for 3MF export,
# loaded lazily by build123d's Mesher). Loading anything else, or looking up symbols in the
# Python runtime / the process itself (pythonapi, CDLL(None)), is refused.
def _allowed_native_dirs() -> list[str]:
    import importlib.util

    out = []
    for mod in ("lib3mf",):
        spec = importlib.util.find_spec(mod)
        if spec and spec.origin:
            out.append(_norm(os.path.dirname(spec.origin)))
    return out


def _norm(path) -> str:
    """Real path, case-folded on Windows (where C:\\Users and c:\\users are the same folder)."""
    return os.path.normcase(os.path.realpath(os.fsdecode(path)))


ALLOWED_NATIVE = _allowed_native_dirs()


def ctypes_guard(event: str, args) -> None:
    if event == "ctypes.dlopen":
        name = args[0] if args else None
        p = _norm(name) if name else ""
        if not any(p.startswith(d + os.sep) for d in ALLOWED_NATIVE):
            raise SandboxViolation(f"blocked in part scripts: loading native library {name!r}")
    elif event == "ctypes.dlsym":
        name = getattr(args[0], "_name", None) if args else None
        p = _norm(name) if isinstance(name, (str, bytes)) else ""
        if not any(p.startswith(d + os.sep) for d in ALLOWED_NATIVE):
            raise SandboxViolation(f"blocked in part scripts: symbol lookup in {name!r}")
    elif event in ("ctypes.cdata", "ctypes.dlsym/handle", "ctypes.set_errno", "ctypes.seh_exception"):
        raise SandboxViolation(f"blocked in part scripts: {event}")


def install_guard(writable: list[str]) -> None:
    roots = [_norm(p) for p in writable]

    def can_write(path) -> bool:
        if isinstance(path, int):
            return True  # an already-open fd
        p = _norm(path)
        return any(p == r or p.startswith(r + os.sep) for r in roots)

    def hook(event: str, args) -> None:
        if event.startswith("ctypes."):
            ctypes_guard(event, args)
            return
        if event.startswith(BLOCKED_EVENTS):
            raise SandboxViolation(f"blocked in part scripts: {event}")
        if event == "import" and args and args[0] in BLOCKED_IMPORTS:
            raise SandboxViolation(f"blocked in part scripts: import {args[0]}")
        if event == "open" and len(args) >= 2:
            path, mode = args[0], args[1]
            flags = args[2] if len(args) > 2 else 0
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
            )
            if writing and path is not None and not can_write(path):
                raise SandboxViolation(f"blocked in part scripts: writing {path}")
        if event in WRITE_EVENTS and args and not can_write(args[0]):
            raise SandboxViolation(f"blocked in part scripts: {event} {args[0]}")

    sys.addaudithook(hook)


def _parts_for(mod, d, which: str | None):
    parts = printables(mod, d)
    named = {(k or "part"): v for k, v in parts.items()}
    if which in (None, "", "all"):
        return [(p, None, n) for n, p in named.items()]
    if which == "assembly":
        asm = assembly(mod, d)
        if not asm:
            raise ValueError("this script has no assembly(d)")
        return asm
    names = [w.strip() for w in which.split(",")]
    missing = [n for n in names if n not in named]
    if missing:
        raise KeyError(f"no part(s) {missing}; parts: {sorted(named)}" + (" (or 'assembly')" if hasattr(mod, "assembly") else ""))
    return [(named[n], None, n) for n in names]


def _preview_parts(mod, d, which: str | None):
    """What render_preview draws: the assembly when the script has one (printable parts all sit at
    the origin in print orientation, so drawn together they overlap), else the printable parts
    side by side on the bed. Returns (items, layout)."""
    if which in (None, "", "all"):
        asm = assembly(mod, d)
        if asm:
            return asm, "assembly"
        sel = _parts_for(mod, d, None)
    elif which == "assembly":
        return _parts_for(mod, d, which), "assembly"
    else:
        sel = _parts_for(mod, d, which)
    if len(sel) > 1:
        return side_by_side([(p, lbl) for p, _, lbl in sel]), "side by side"
    return sel, "single"


class _OnlyParts:
    """The part script, but build() returns only the named printable parts (export parts=)."""

    def __init__(self, mod, names: list[str]):
        self._mod, self._names = mod, names

    def __getattr__(self, attr):
        if attr in ("assembly", "part"):  # the assembly shows every part: not part of a filtered export
            raise AttributeError(attr)
        if attr == "views":
            views = getattr(self._mod, "views", None)
            if views is None:
                raise AttributeError(attr)
            return lambda d: [v for v in views(d) if v.parts and set(v.parts) <= set(self._names)]
        return getattr(self._mod, attr)

    def build(self, d=None):
        named = {(k or "part"): (k, v) for k, v in printables(self._mod, d).items()}
        missing = [n for n in self._names if n not in named]
        if missing:
            raise KeyError(f"no part(s) {missing}; parts: {sorted(named)}")
        return dict(named[n] for n in self._names)


def do_compare(job: dict) -> dict:
    """Compare two mesh files (agent-exported files are untrusted input to the parsers)."""
    crit = cmp.Criteria(**job.get("criteria", {}))
    r = cmp.compare(job["reference"], job["candidate"], criteria=crit)
    res = {"text": r.text(), **{k: v for k, v in r.as_dict().items() if k in ("metrics", "checks", "alignment", "score", "passed")}}
    if job.get("image"):
        res["image"] = str(cmp.render_comparison(job["reference"], job["candidate"], r, Path(job["out_dir"]) / job["image"],
                                                 size=job.get("size", "normal")))
    return res


def do_describe(job: dict) -> dict:
    """Describe a reference model (an untrusted file for the parsers) and render it."""
    summary, part = remix.describe(job["file"], job.get("scale", 1.0))
    res = {"summary": summary}
    if job.get("image"):
        out = Path(job["out_dir"])
        stem = Path(job["file"]).stem
        res["image"] = str(render(part, out / f"{stem}_original{'_small' if job.get('size') == 'small' else ''}.png",
                                  f"original: {Path(job['file']).name}", size=job.get("size", "normal")))
    return res


def do(job: dict) -> dict:
    if job["op"] == "compare":
        return do_compare(job)
    if job["op"] == "describe":
        return do_describe(job)
    script = Path(job["script"])
    mod = load(script)
    keys = list(variants(mod))
    want = job.get("variant")
    key = None if want is None else ("" if want in ("", "standard") else want)
    if key is not None and key not in keys:
        raise KeyError(f"no variant {want!r}; variants: {[k or 'standard' for k in keys]}")
    op = job["op"]
    out = Path(job["out_dir"])
    settings = load_settings(script)

    if op == "build":
        res = {"variants": {}}
        for k in keys if key is None else [key]:
            d = dims(mod, k)
            parts = printables(mod, d)
            res["variants"][k or "standard"] = {
                "parts": {(n or "part"): report(p) for n, p in parts.items()},
                "dims": {f: getattr(d, f) for f in d.__dataclass_fields__} if d is not None else None,
                "assembly": [lbl for _, _, lbl in (assembly(mod, d) or [])],
            }
        return res

    k = key if key is not None else keys[0]
    d = dims(mod, k)
    tag = "_".join(x for x in (script.stem, k) if x)
    size = job.get("size", "normal")
    small = "_small" if size == "small" else ""
    if op == "render":
        which = job.get("parts")
        sel, layout = _preview_parts(mod, d, which)
        name = f"{tag}_{(which or 'all').replace(',', '+')}_preview{small}.png"
        title = tag + (f" ({which})" if which else "") + (f", {layout}" if layout != "single" else "")
        f = render(sel if len(sel) > 1 else sel[0][0], out / name, title, size=size)
        # report the printable parts as built (print orientation), not moved copies or stand-ins
        reports = {lbl: report(p) for p, _, lbl in _parts_for(mod, d, None if layout == "assembly" else which)}
        return {"image": str(f), "variant": k or "standard", "parts": reports, "layout": layout,
                "drawn": [lbl for _, _, lbl in sel]}
    if op == "section":
        sel = _parts_for(mod, d, job.get("parts") or ("assembly" if hasattr(mod, "assembly") else None))
        plane, at = job["plane"].upper(), float(job["at"])
        f = section_view(sel, plane, at, out / f"{tag}_{plane.lower()}{round(at, 3):g}{small}.png", tag, size=size)
        return {"image": str(f), "variant": k or "standard", "plane": plane, "at": at}
    if op == "check" and job.get("share"):  # one of several workers sharing a check run (mcp_server.check)
        share = tuple(job["share"])
        return {"shares": {kk or "standard": check_share(mod, kk, settings, share, deadline=job.get("deadline"),
                                                       started=job.get("started"))
                           for kk in (keys if key is None else [key])}}
    if op == "check":
        res = {}
        for i, kk in enumerate(keys if key is None else [key]):
            res[kk or "standard"] = [f.__dict__ for f in run_checks(mod, kk, settings, nudge=i == 0, deadline=job.get("deadline"))]
        failed = any(f["level"] == ck.FAIL for v in res.values() for f in v)
        return {"passed": not failed, "variants": res}
    if op == "metrics":
        res = metrics.design_metrics(mod, d, printables(mod, d), settings, style=job.get("style") or None,
                                     up=job.get("up") or None)
        return {"variant": k or "standard", "metrics": res, "text": metrics.text(res)}
    if op == "before_after":
        parts, orig, _ = built(mod, d)
        if orig is None:
            raise ValueError("this part is not a remix: build() loads nothing with import_model and the script has no original(d)")
        r = before_after(orig, {(n or "part"): p for n, p in parts.items()}, out, tag, size)
        return {"variant": k or "standard", **r}
    if op == "export":
        fmts = parse_formats(job["formats"]) if job.get("formats") else None
        src = _OnlyParts(mod, [n.strip() for n in job["parts"].split(",") if n.strip()]) if job.get("parts") else mod
        return {"variants": [export_variant(src, script, kk, out, fmts) for kk in (keys if key is None else [key])]}
    raise ValueError(f"unknown op {op!r}")


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_path = Path(job["result"])
    os.chdir(job["out_dir"])
    if job.get("guard", True):
        install_guard(job["writable"])
    try:
        res = {"ok": True, **do(job)}
    except BaseException as e:  # noqa: BLE001 - report everything, including SystemExit from scripts
        tb = traceback.format_exc()
        # keep the frames from the part script (and below), drop the b123d-print plumbing above it
        lines = tb.splitlines()
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": "\n".join(lines[-40:])}
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(res, f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
