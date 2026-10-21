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
import warnings
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
from b123d_print import diagnose  # noqa: E402
from b123d_print.config import load_settings, parse_formats  # noqa: E402
from b123d_print.project import (  # noqa: E402
    CacheConfig,
    ReadLog,
    before_after,
    built,
    check_share,
    dims,
    export_variant,
    load,
    make_pieces,
    run_checks,
    variants,
    write_template,
)
from b123d_print import remix  # noqa: E402
import scipy.sparse.csgraph  # noqa: E402,F401  (import_model's mesh repair, loaded before the guard)
from b123d_print.render import render, report, section_view, side_by_side  # noqa: E402
from b123d_print import compare as cmp  # noqa: E402  (scipy's k-d tree, loaded before the guard)
from b123d_print import metrics  # noqa: E402
from b123d_print import templates  # noqa: E402,F401  (fit-test templates)
from b123d_print import joints  # noqa: E402,F401  (split parts, joint helpers)
from b123d_print import viewer  # noqa: E402  (the 3D view's GLB)
from b123d_print import measure  # noqa: E402  (measure)
from b123d_print import outdir  # noqa: E402  (out/'s folders)
from b123d_print.project import Pieces  # noqa: E402
import scipy.ndimage  # noqa: E402,F401  (design_metrics' water-trap labelling, loaded before the guard)
from b123d_print import fit  # noqa: E402  (fit between pieces)
from b123d_print import hardware  # noqa: E402  (hardware_list: the declared bought parts)
from b123d_print import trace as tr  # noqa: E402  (outline tracing)
import scipy.interpolate  # noqa: E402,F401  (trace's spline fit, loaded before the guard)
import contourpy  # noqa: E402,F401  (trace's contours)
import PIL.Image  # noqa: E402,F401  (trace reads the image)

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
    # introspection that could walk to the guard's own settings and change them: refuse it in a
    # part script (the libraries are all imported before the guard goes in, so nothing here fires
    # during a normal build)
    "gc.get_objects",
    "gc.get_referrers",
    "gc.get_referents",
)
BLOCKED_IMPORTS = {"_posixsubprocess", "socket", "_socket", "ssl", "_ssl", "subprocess"}
# write-ish events whose one path argument (args[0]) must be in a writable folder
WRITE_ONE = {"os.remove", "os.unlink", "os.rmdir", "os.mkdir", "os.makedirs", "shutil.rmtree",
             "os.truncate", "os.chmod", "os.chown", "os.chflags", "os.utime", "os.removexattr", "os.setxattr"}
# events with two path arguments (args[0] and args[1]); both must be writable
WRITE_TWO = {"os.rename", "os.link"}  # os.replace also raises os.rename
WRITE_EVENTS = WRITE_ONE | WRITE_TWO | {"os.symlink"}  # kept as the public name of the set


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
READS = ReadLog()  # what the part script reads, for the build cache (main installs it)


def install_guard(writable: list[str], hidden: list[str] = (), secrets: list[str] = (),
                  readable: list[str] = ()) -> None:
    """Install the audit hook. Its configuration (the allowed and denied folders, the event
    lists) is captured as frozen copies in this closure, and the functions it calls on the hot
    path — realpath/normcase/fsdecode and the builtins any/isinstance/len — are captured as
    closure locals too, so the hook does not go through names a part script could rebind
    (os.path.*, builtins.*) or a module global or list it could reach. The stdlib internals those
    functions use (posixpath's own globals) are not frozen, so this is best-effort: the hook is
    defense in depth, and the OS sandbox or the container is the isolation boundary — see
    sandbox.describe()."""
    sep = os.sep
    realpath, normcase, fsdecode = os.path.realpath, os.path.normcase, os.fsdecode
    _any, _isinstance, _len, _getattr = any, isinstance, len, getattr
    violation = SandboxViolation

    def norm(path) -> str:
        return normcase(realpath(fsdecode(path)))

    roots = tuple(norm(p) for p in writable)
    # folders a job may read: its own workspace, the Python installation, its config. A read under
    # one of these is always allowed, even where it sits inside a hidden folder (the job's own
    # workspace is under the hidden workspaces/ parent).
    allow_read = tuple(norm(p) for p in list(readable) + list(writable))
    # reads refused even where the OS does not hide them (Windows, SANDBOX=none in the container):
    # other workspaces, and the secret files (tokens, link secret), wherever they are
    deny_dirs = tuple(norm(p) for p in hidden)
    deny_files = frozenset(norm(p) for p in secrets)
    blocked_events = tuple(BLOCKED_EVENTS)
    blocked_imports = frozenset(BLOCKED_IMPORTS)
    write_one = frozenset(WRITE_ONE)
    write_two = frozenset(WRITE_TWO)
    allowed_native = tuple(ALLOWED_NATIVE)
    read_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT

    def can_write(path) -> bool:
        if _isinstance(path, int):
            return True  # an already-open fd
        p = norm(path)
        return _any(p == r or p.startswith(r + sep) for r in roots)

    def longest(p, dirs) -> int:
        """Length of the longest folder in `dirs` that contains `p` (-1 for none)."""
        best = -1
        for d in dirs:
            if (p == d or p.startswith(d + sep)) and _len(d) > best:
                best = _len(d)
        return best

    def denied_read(path) -> bool:
        if _isinstance(path, int) or path is None:
            return False
        p = norm(path)
        if p in deny_files:  # the secret files are off limits wherever they are
            return True
        # the server's own environment (where a single-container HTTP setup keeps its token) is not
        # the script's to read; a normal build never looks here
        if p.startswith("/proc/") and p.endswith("/environ"):
            return True
        # the most specific folder wins: a job's own workspace (readable) sits inside the hidden
        # workspaces/ parent, so it stays readable, while a sibling workspace under that parent does not
        return longest(p, deny_dirs) > longest(p, allow_read)

    def ctypes_guard(event: str, args) -> None:
        if event == "ctypes.dlopen":
            name = args[0] if args else None
            p = norm(name) if name else ""
            if not _any(p.startswith(d + sep) for d in allowed_native):
                raise violation(f"blocked in part scripts: loading native library {name!r}")
        elif event == "ctypes.dlsym":
            name = _getattr(args[0], "_name", None) if args else None
            p = norm(name) if _isinstance(name, (str, bytes)) else ""
            if not _any(p.startswith(d + sep) for d in allowed_native):
                raise violation(f"blocked in part scripts: symbol lookup in {name!r}")
        elif event in ("ctypes.cdata", "ctypes.dlsym/handle", "ctypes.set_errno", "ctypes.seh_exception"):
            raise violation(f"blocked in part scripts: {event}")

    def hook(event: str, args) -> None:
        if event.startswith("ctypes."):
            ctypes_guard(event, args)
            return
        if event.startswith(blocked_events):
            raise violation(f"blocked in part scripts: {event}")
        if event == "import" and args and args[0] in blocked_imports:
            raise violation(f"blocked in part scripts: import {args[0]}")
        if event == "open" and args:
            path = args[0]
            mode = args[1] if _len(args) > 1 else None
            flags = args[2] if _len(args) > 2 else 0
            writing = (_isinstance(mode, str) and _any(c in mode for c in "wax+")) or (
                _isinstance(flags, int) and flags & read_flags
            )
            if writing and path is not None and not can_write(path):
                raise violation(f"blocked in part scripts: writing {path}")
            if not writing and denied_read(path):
                raise violation(f"blocked in part scripts: reading {path}")
            return
        if event in ("os.scandir", "os.listdir") and args and denied_read(args[0]):
            raise violation(f"blocked in part scripts: listing {args[0]}")
        if event in write_one and args and not can_write(args[0]):
            raise violation(f"blocked in part scripts: {event} {args[0]}")
        if event in write_two and args:  # rename/replace/link: the source and the destination
            for p in args[:2]:
                if p is not None and not can_write(p):
                    raise violation(f"blocked in part scripts: {event} {p}")
        if event == "os.symlink" and _len(args) >= 2 and not can_write(args[1]):
            # the link is created at args[1]; a link pointing outside is harmless because any read
            # or write through it resolves to its real target, which is checked in turn
            raise violation(f"blocked in part scripts: os.symlink at {args[1]}")

    sys.addaudithook(hook)


def _parts_for(pc, which: str | None):
    """[(part, None, name)] for `which` (every piece, 'assembly' or comma-separated names); only
    the named pieces are built (lazy pieces) or read from the build cache."""
    if which in (None, "", "all"):
        return [(p, None, n or "part") for n, p in pc.parts().items()]
    if which == "assembly":
        asm = pc.assembly()
        if not asm:
            raise ValueError("this script has no assembly(d)")
        return asm
    try:
        named = pc.parts(which)
    except KeyError as e:
        raise KeyError(e.args[0] + (" (or 'assembly')" if hasattr(pc.mod, "assembly") else "")) from None
    return [(p, None, n or "part") for n, p in named.items()]


def _preview_parts(pc, which: str | None):
    """What render_preview draws: the assembly when the script has one (printable parts all sit at
    the origin in print orientation, so drawn together they overlap), else the printable parts
    side by side on the bed. Returns (items, layout)."""
    if which in (None, "", "all"):
        asm = pc.assembly()
        if asm:
            return asm, "assembly"
        sel = _parts_for(pc, None)
    elif which == "assembly":
        return _parts_for(pc, which), "assembly"
    else:
        sel = _parts_for(pc, which)
    if len(sel) > 1:
        return side_by_side([(p, lbl) for p, _, lbl in sel]), "side by side"
    return sel, "single"


def _for_pick(pc, name: str | None) -> dict:
    """The pieces for templates.pick_part: only the named one when it exists (pick_part reports a
    wrong name, with the list)."""
    return pc.parts(name) if name and name in {n or "part" for n in pc.names()} else pc.parts()


def do_compare(job: dict) -> dict:
    """Compare two mesh files (agent-exported files are untrusted input to the parsers)."""
    crit = cmp.Criteria(**job.get("criteria", {}))
    r = cmp.compare(job["reference"], job["candidate"], criteria=crit)
    res = {"text": r.text(), **{k: v for k, v in r.as_dict().items() if k in ("metrics", "checks", "alignment", "score", "passed")}}
    if job.get("image"):
        res["image"] = str(cmp.render_comparison(job["reference"], job["candidate"], r, _image(job["out_dir"], job["image"]),
                                                 size=job.get("size", "normal")))
    return res


def _image(out_dir: str, name: str) -> Path:
    """Where a picture goes: images/ when out_dir is a part's out/ folder, else out_dir itself."""
    return outdir.path(out_dir, name) if Path(out_dir).name == "out" else Path(out_dir) / name


def do_describe(job: dict) -> dict:
    """Describe a reference model (an untrusted file for the parsers) and render it."""
    summary, part = remix.describe(job["file"], job.get("scale", 1.0))
    res = {"summary": summary}
    if job.get("image"):
        out = Path(job["out_dir"])
        stem = Path(job["file"]).stem
        res["image"] = str(render(part, outdir.path(out, f"{stem}_original{'_small' if job.get('size') == 'small' else ''}.png"),
                                  f"original: {Path(job['file']).name}", size=job.get("size", "normal")))
    return res


def _usage_error(e: BaseException) -> bool:
    """An error in what the tool was asked (a wrong piece, variant, face or measurement)."""
    msg = str(e)
    return (isinstance(e, (measure.MeasureError, templates.TemplateError))
            or (isinstance(e, KeyError) and (msg.startswith(("'no part", "'no variant", '"no part', '"no variant'))
                                              or "no part(s)" in msg or "no variant" in msg)))




def do_trace(job: dict) -> dict:
    """Trace the outline of a flat object in a reference image (an untrusted file for the parsers)."""
    a = job.get("args", {})
    scale = tr.Scale(**job.get("scale", {}))
    res = tr.trace(job["file"], scale, tolerance=a.get("tolerance", 0.2), smooth=bool(a.get("smooth")),
                   threshold=a.get("threshold"), invert=a.get("invert"), clean=a.get("clean"),
                   min_hole=a.get("min_hole", 1.0), pick=a.get("pick"))
    stem = Path(job["file"]).stem
    tr.write(res, job["out_dir"], stem, title=Path(job["file"]).name, sort=True)
    return {"text": tr.text(res), "trace": res.as_dict(), "snippet": tr.snippet(res)}


def do(job: dict, warned: list | None = None) -> dict:
    if job["op"] == "compare":
        return do_compare(job)
    if job["op"] == "describe":
        return do_describe(job)
    if job["op"] == "diagnose":  # loads the script itself, so a script that fails to load is diagnosed too
        want = job.get("variant")
        return diagnose.deep(Path(job["script"]), None if want is None else ("" if want in ("", "standard") else want),
                             job.get("parts"), job.get("deadline"), warned if warned is not None else [])
    if job["op"] == "trace":
        return do_trace(job)
    script = Path(job["script"])
    mod = load(script)
    keys = list(variants(mod))
    want = job.get("variant")
    key = None if want is None else ("" if want in ("", "standard") else want)
    if key is not None and key not in keys:
        raise KeyError(f"no variant {want!r}; variants: {[k or 'standard' for k in keys]}")
    op = job["op"]
    if op == "hardware":  # the declared bought parts (hardware_list): hardware(d) only, nothing is built
        k = key if key is not None else keys[0]
        items = hardware.declared(mod, dims(mod, k))
        return {"variant": k or "standard", "variants": [kk or "standard" for kk in keys], "declared": items is not None,
                "items": [item.record() for item in items or []]}
    out = Path(job["out_dir"])
    settings = load_settings(script)
    # the build cache: only in a worker that records what the script reads (main), and only in
    # the part's own out/ folder, which is the one folder of the part it may write
    cache = None
    if READS.installed and job.get("workspace") and _norm(out) == _norm(script.parent / "out"):
        cache = CacheConfig(Path(job["workspace"]), READS, fresh=bool(job.get("fresh")))
    if _norm(out) == _norm(script.parent / "out"):
        outdir.tidy(out)  # files of the flat layout before 0.3.11 into their folders: never both layouts
    only = job.get("parts") or None

    if op == "build":
        res = {"variants": {}}
        for k in keys if key is None else [key]:
            d = dims(mod, k)
            pc = make_pieces(mod, k, d, settings, cache)
            parts = pc.parts(only)
            v = res["variants"][k or "standard"] = {
                "parts": {(n or "part"): report(p) for n, p in parts.items()},
                "dims": {f: getattr(d, f) for f in d.__dataclass_fields__} if d is not None else None,
            }
            problems = {(n or "part"): pr for n, p in parts.items()
                        if (pr := diagnose.shape_problems(n or "part", p, v["parts"][n or "part"]))}
            if problems:  # it built, but not into something printable: say what and how to fix it
                v["problems"] = problems
            if not only:  # the assembly needs every piece
                v["assembly"] = [lbl for _, _, lbl in (pc.assembly() or [])]
            v["timing"] = pc.timing()
        return res

    k = key if key is not None else keys[0]
    d = dims(mod, k)
    pc = make_pieces(mod, k, d, settings, cache)
    tag = "_".join(x for x in (script.stem, k) if x)
    size = job.get("size", "normal")
    small = "_small" if size == "small" else ""
    if op == "render":
        which = job.get("parts")
        sel, layout = _preview_parts(pc, which)
        name = f"{tag}_{(which or 'all').replace(',', '+')}_preview{small}.png"
        title = tag + (f" ({which})" if which else "") + (f", {layout}" if layout != "single" else "")
        f = render(sel if len(sel) > 1 else sel[0][0], outdir.path(out, name), title, size=size)
        # report the printable parts as built (print orientation), not moved copies or stand-ins
        reports = {lbl: report(p) for p, _, lbl in _parts_for(pc, None if layout == "assembly" else which)}
        return {"image": str(f), "variant": k or "standard", "parts": reports, "layout": layout,
                "drawn": [lbl for _, _, lbl in sel], "timing": pc.timing()}
    if op == "section":
        sel = _parts_for(pc, job.get("parts") or ("assembly" if hasattr(mod, "assembly") else None))
        plane, at = job["plane"].upper(), float(job["at"])
        f = section_view(sel, plane, at, outdir.path(out, f"{tag}_{plane.lower()}{round(at, 3):g}{small}.png"), tag, size=size)
        return {"image": str(f), "variant": k or "standard", "plane": plane, "at": at, "timing": pc.timing()}
    if op == "check" and job.get("share"):  # one of several workers sharing a check run (mcp_server.check)
        share = tuple(job["share"])
        return {"shares": {kk or "standard": check_share(mod, kk, settings, share, deadline=job.get("deadline"),
                                                       started=job.get("started"), cache=cache)
                           for kk in (keys if key is None else [key])}}
    if op == "check":
        res = {}
        for i, kk in enumerate(keys if key is None else [key]):
            res[kk or "standard"] = [f.__dict__ for f in run_checks(mod, kk, settings, nudge=i == 0, deadline=job.get("deadline"),
                                                                    cache=cache)]
        failed = any(f["level"] == ck.FAIL for v in res.values() for f in v)
        return {"passed": not failed, "variants": res}
    if op == "fit":
        out = []
        for kk in keys if key is None else [key]:
            r = fit.run_fit(mod, kk, settings, cache, job.get("hole_tol"))
            out.append({"text": fit.text(r, script.stem, bool(job.get("verbose"))),
                        "passed": not any(f.level == ck.FAIL for f in r["findings"]),
                        "findings": [f.__dict__ for f in r["findings"]], "variant": r["variant"]})
        return {"variants": out, "passed": all(v["passed"] for v in out)}
    if op == "metrics":
        res = metrics.design_metrics(mod, d, pc.parts(), settings, style=job.get("style") or None,
                                     up=job.get("up") or None)
        return {"variant": k or "standard", "metrics": res, "text": metrics.text(res)}
    if op == "orient":
        from b123d_print import orient

        piece = job.get("piece")
        ranked, best = orient.for_script(mod, d, pc.parts(piece) if piece else pc.parts(), settings, piece, job.get("load"))
        res = {"variant": k or "standard", "parts": ranked,
               "text": "\n\n".join(orient.text(n if len(ranked) > 1 else tag, r) for n, r in ranked.items())}
        if job.get("image"):
            n, top = next(iter(best.items()))
            rows = ranked[n]["candidates"]
            title = f"{tag}{'_' + n if n != 'part' else ''}: {orient._fmt_rot(rows[0]['rot'])}, {rows[0]['down']} side on the bed"
            res["image"] = str(render(top, outdir.path(out, f"{tag}{'_' + n if n != 'part' else ''}_orient{small}.png"), title, size=size))
        return res
    if op == "before_after":
        parts, orig, _ = built(mod, d, pc)
        if orig is None:
            raise ValueError("this part is not a remix: build() loads nothing with import_model and the script has no original(d)")
        r = before_after(orig, {(n or "part"): p for n, p in parts.items()}, out, tag, size)
        return {"variant": k or "standard", **r}
    if op == "faces":
        from b123d_print import templates as tp

        pname, part = tp.pick_part(_for_pick(pc, job.get("part")), job.get("part"))
        res = {"variant": k or "standard", "part": pname, **tp.list_faces(part)}
        if job.get("highlight") is not None:
            face, fid = tp.find_face(part, job["highlight"])
            img = outdir.path(out, f"{tag}{'_' + pname if pname != 'part' else ''}_face{fid}{small}.png")
            res["image"] = str(tp.highlight(part, [face], img, f"{tag}: face {fid} (red)", size=size))
            res["highlight"] = fid
        return res
    if op == "edges":
        from b123d_print import edges as ed, templates as tp

        pname, part = tp.pick_part(_for_pick(pc, job.get("part")), job.get("part"))
        res = {"variant": k or "standard", "part": pname,
               **ed.list_edges(part, job.get("face"), job.get("kind"), job.get("convexity"), job.get("near"),
                               job.get("radius", 1.0), job.get("limit", ed.LIMIT))}
        if job.get("highlight") is not None:
            chosen, ids = ed.find_edges(part, job["highlight"])
            img = outdir.path(out, f"{tag}{'_' + pname if pname != 'part' else ''}_edges{'-'.join(map(str, ids[:6]))}{small}.png")
            res["image"] = str(ed.highlight(part, chosen, img, f"{tag}: edges {ed.id_text(ids)} (red)", size=size))
            res["selector"] = ed.selector(part, ids)
        return res
    if op == "template":
        from b123d_print import templates as tp

        spec = tp.Template(**{f: v for f, v in job["spec"].items() if v is not None})
        fmts = parse_formats(job["formats"]) if job.get("formats") else settings.formats
        return write_template(script, k, _for_pick(pc, spec.part), spec, out, fmts, settings)
    if op == "measure":
        q = dict(job["query"])
        return {"variant": k or "standard", **measure.run(pc, q, settings, out, tag, size)}
    if op == "export":
        fmts = parse_formats(job["formats"]) if job.get("formats") else None
        res = {"variants": [export_variant(mod, script, kk, out, fmts, only=only, cache=cache)
                            for kk in (keys if key is None else [key])]}
        if job.get("view"):  # the 3D view of each variant (export's view=), from the same (cached) pieces
            for kk, v in zip(keys if key is None else [key], res["variants"]):
                tag = "_".join(x for x in (script.stem, kk) if x)
                try:
                    pc = make_pieces(mod, kk, dims(mod, kk), settings, cache)
                    v["view"] = str(viewer.write_view(pc, tag, out, job["view"], only))
                except (KeyError, ValueError) as e:  # e.g. view='assembly' without assembly(d): the export still stands
                    v["view_error"] = str(e).strip('"')
        return res
    raise ValueError(f"unknown op {op!r}")


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result_path = Path(job["result"])
    os.chdir(job["out_dir"])
    READS.install()  # before the guard, which refuses any later audit hook
    if job.get("guard", True):
        install_guard(job["writable"], job.get("hidden", []), job.get("secrets", []), job.get("readable", []))
    # what is being built, for a timeout's diagnosis (the server reads these lines when the worker is killed)
    Pieces.progress = lambda msg: print(diagnose.PROGRESS + msg, file=sys.stderr, flush=True)
    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        try:
            res = {"ok": True, **do(job, warned)}
            if diagnose.warning_texts(warned):
                res["warnings"] = diagnose.warning_texts(warned)
        except BaseException as e:  # noqa: BLE001 - report everything, including SystemExit from scripts
            tb = traceback.format_exc()
            # keep the frames from the part script (and below), drop the b123d-print plumbing above it
            lines = tb.splitlines()
            res = {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": "\n".join(lines[-40:])}
            if _usage_error(e):  # the tool's arguments, not the script: nothing to diagnose
                res["usage_error"] = True
            elif job.get("script"):
                try:
                    res["diagnosis"] = diagnose.from_exception(e, job["script"], diagnose.warning_texts(warned))
                except Exception:  # noqa: BLE001 - the error itself is what matters
                    pass
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(res, f, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
