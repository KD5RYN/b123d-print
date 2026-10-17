"""b123d-print MCP server: design, check and export 3D-printable build123d parts from any MCP
client. Part scripts are model-written code: every build runs in a sandboxed subprocess.

    b123d-print-mcp --workspace ~/parts            # stdio; or B123D_PRINT_WORKSPACE=~/parts; default: the cwd
    B123D_PRINT_TOKEN=... b123d-print-mcp --transport http --port 8000   # Streamable HTTP at /mcp

Over HTTP every request needs `Authorization: Bearer <token>`, and each client picks its own
workspace with `/mcp?workspace=<name>` (or the header `X-B123D-Workspace`), which is the folder
<workspace>/workspaces/<name>; without one, clients share <workspace> itself. Files the server
writes come back as signed download links (GET /files/..., no token, they expire) and as
b123d-print://files/ resources.
"""

from __future__ import annotations

import argparse
import contextvars
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import jobqueue, links, sandbox, tokens
from .cli import NAME_RE, data, examples, init_workspace, new_part as _new_part
from .config import WORKSPACE_FILE, formats_configured, load_settings, parse_formats
from .project import find_parts

MAX_SCRIPT_BYTES = 256_000

INSTRUCTIONS = """\
Design 3D-printable parts as build123d Python scripts, then build, look at, check and export them.
Workflow: new_part -> write_part (whole script) -> build_part -> render_preview + section ->
check -> fix and repeat -> export. Read the resource b123d-print://guide (or the prompt
design_part_from_photos) for the rules: named UPPER_CASE dimensions in a Dims dataclass, mm,
print orientation with the bed at Z=0, 0.2 mm mating clearance, HOLE_COMP from the user's config,
list photo-read dimensions and wait for confirmation, verify with renders, sections and checks
before reporting. render_preview and section return PNG images. When this server is remote (HTTP),
the files it writes stay on it: download them from the links that export returns (plain HTTPS GET,
no token, they expire; e.g. curl -fO <url>) or read the b123d-print://files/ resources. Never try
to SSH into the server for them."""

WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WORKSPACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("b123d_print_workspace", default=None)
_REQUEST: contextvars.ContextVar = contextvars.ContextVar("b123d_print_request", default=None)


async def _request_workspace(ctx, call_next):
    """HTTP: the workspace this request asked for (?workspace=<name> or X-B123D-Workspace)."""
    req = getattr(ctx, "request", None)
    name = None
    if req is not None and hasattr(req, "query_params"):
        name = (req.query_params.get("workspace") or req.headers.get("x-b123d-workspace")
                or req.scope.get("state", {}).get("b123d_workspace"))  # a token's default workspace (TokenAuth)
    token, rtoken = _WORKSPACE.set(name), _REQUEST.set(req)
    try:
        return await call_next(ctx)
    finally:
        _WORKSPACE.reset(token)
        _REQUEST.reset(rtoken)


mcp = MCPServer("b123d-print", instructions=INSTRUCTIONS, middleware=[_request_workspace])
STATE: dict = {"root": Path.cwd(), "timeout": 120.0, "transport": "stdio", "max_builds": 2, "limiter": None,
               "link_secret": b"", "link_ttl": 3600.0, "public_url": None, "allowed_hosts": [],
               "tokens": None, "queue": None}
EMBED_MAX = 2_000_000  # bytes: export(embed=True) inlines files up to this size ...
EMBED_TOTAL = 8_000_000  # ... and this much in all


def _root() -> Path:
    name = _WORKSPACE.get()
    if not name:
        return STATE["root"]
    if not WORKSPACE_RE.match(name):
        raise ToolError(f"bad workspace name {name!r}: letters, digits, '_' and '-', up to 64")
    ws = STATE["root"] / "workspaces" / name
    if not (ws / WORKSPACE_FILE).exists():
        init_workspace(ws)
    return ws


def _limiter() -> anyio.CapacityLimiter:
    # at most max_builds worker processes at once, across all clients; the rest wait their turn
    if STATE["limiter"] is None:
        STATE["limiter"] = anyio.CapacityLimiter(STATE["max_builds"])
    return STATE["limiter"]


def _parts_dir() -> Path:
    return _root() / load_settings(_root()).parts_dir


def _script(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ToolError(f"bad part name {name!r}: lower_snake_case, starting with a letter")
    p = _parts_dir() / name / f"{name}.py"
    if not p.is_file():
        have = [s.parent.name for s in find_parts(_root(), load_settings(_root()).parts_dir)]
        raise ToolError(f"no part {name!r}. Parts: {have or 'none yet (use new_part)'}")
    return p


async def _run(job: dict, out_dir: Path) -> dict:
    """Every job that runs untrusted code or parses untrusted files goes through here: sandboxed,
    and under the shared build limit."""
    root = _root()  # resolve the client's workspace here, not in the worker thread
    queue = STATE["queue"]

    def run() -> dict:
        if queue is None:
            return sandbox.run_job(job, root, out_dir, STATE["timeout"])
        try:  # a separate worker (container) runs it: see jobqueue.py
            return jobqueue.submit(queue, job, root, out_dir, STATE["timeout"])
        except jobqueue.WorkerDown as e:
            return {"ok": False, "error": str(e)}

    return await anyio.to_thread.run_sync(run, limiter=_limiter())


async def _job(name: str, op: str, **kw) -> dict:
    script = _script(name)
    return await _run({"op": op, "script": str(script), **{k: v for k, v in kw.items() if v is not None}}, script.parent / "out")


def _error_text(res: dict) -> str:
    s = f"ERROR: {res.get('error')}"
    if res.get("traceback"):
        s += f"\n\n{res['traceback']}"
    if res.get("log"):
        s += f"\n\nOutput:\n{res['log']}"
    return s


def _http() -> bool:
    return STATE["transport"] == "http"


def _token_name() -> str | None:
    """HTTP: the name of the token this request came with (see TokenAuth)."""
    req = _REQUEST.get()
    return req.scope.get("state", {}).get("b123d_token") if req is not None else None


def _ws_name() -> str:
    return _WORKSPACE.get() or links.ROOT_WS


def _ws_dir(name: str) -> Path | None:
    """The folder of workspace `name` ("_" = the root workspace), or None if there is no such workspace."""
    if name == links.ROOT_WS:
        return STATE["root"]
    if not WORKSPACE_RE.match(name):
        return None
    d = STATE["root"] / "workspaces" / name
    return d if d.is_dir() else None


def _host_allowed(host: str) -> bool:
    for a in STATE["allowed_hosts"]:
        if host == a or (a.endswith(":*") and host.startswith(a[:-2] + ":")):
            return True
    return False


def _base_url() -> str:
    """Where clients reach this server: --public-url, else the request's own Host header. Proxy
    headers (X-Forwarded-Host/-Proto) are trusted only for a host listed in --allowed-hosts."""
    if STATE["public_url"]:
        return STATE["public_url"]
    req = _REQUEST.get()
    if req is None:
        return ""
    h = req.headers
    fwd = (h.get("x-forwarded-host") or "").split(",")[0].strip()
    if fwd and _host_allowed(fwd):
        proto = (h.get("x-forwarded-proto") or "").split(",")[0].strip()
        return f"{proto if proto in ('http', 'https') else req.url.scheme}://{fwd}"
    return f"{req.url.scheme}://{h.get('host') or req.url.netloc}"


def _file_info(path: Path) -> dict | None:
    """HTTP: how a client gets a file the server wrote (None if it is not one the server serves)."""
    root = _root()
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        links.servable(root, load_settings(root).parts_dir, rel)
    except (ValueError, links.LinkError):
        return None
    url, expires = links.sign(STATE["link_secret"], _ws_name(), rel, STATE["link_ttl"])
    return {"path": rel, "url": _base_url() + url, "expires": expires, "size": path.stat().st_size,
            "mime": links.content_type(rel), "uri": f"b123d-print://files/{_ws_name()}/{rel}"}


def _expiry_note(expires: int) -> str:
    return (f"Download links need no token and expire {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))}"
            f" (e.g. curl -fO <url>); after that, call the tool again.")


def _resource_link(info: dict):
    from mcp_types import ResourceLink

    return ResourceLink(uri=info["uri"], name=Path(info["path"]).name, mime_type=info["mime"], size=info["size"],
                        description=f"download: {info['url']}")


def _embedded(path: Path, info: dict):
    import base64

    from mcp_types import BlobResourceContents, EmbeddedResource

    blob = base64.b64encode(path.read_bytes()).decode()
    return EmbeddedResource(resource=BlobResourceContents(uri=info["uri"], mime_type=info["mime"], blob=blob))


def _image_links(image: str) -> tuple[str, list]:
    """HTTP: a download line and a ResourceLink for a PNG the server wrote; nothing over stdio."""
    info = _file_info(Path(image)) if _http() else None
    if not info:
        return "", []
    return f"\nDownload: {info['url']}\n{_expiry_note(info['expires'])}", [_resource_link(info)]


def _image_options(size: str) -> None:
    from .render import SIZES

    if size not in SIZES:
        raise ToolError(f"size must be one of {list(SIZES)}")


def _with_image(text: str, image: str, inline: bool) -> list:
    """A tool result for a PNG the server wrote: the text, the image itself unless inline=False,
    and over HTTP its download link and resource link."""
    note, extra = _image_links(image)
    if not inline and not extra:
        note = f"\nImage file: {image}"
    return [text + note, *([Image(path=image)] if inline else []), *extra]


def _show(image: str) -> str:
    """The image's path as the client should see it: workspace-relative over HTTP, absolute over stdio."""
    return Path(image).relative_to(_root()).as_posix() if _http() else image


# ---------------------------------------------------------------------------------------------
# Tools


@mcp.tool()
def list_parts() -> str:
    """List the part scripts in the workspace, with the settings in effect."""
    s = load_settings(_root())
    parts = [p.parent.name for p in find_parts(_root(), s.parts_dir)]
    return json.dumps(
        {
            "version": _pkg_version(),
            "workspace": str(_root()),
            "parts_dir": s.parts_dir,
            "parts": parts,
            "examples": examples(),
            "settings": {"hole_comp": s.hole_comp, "hole_comp_h": s.hole_comp_h, "clearance": s.clearance,
                         "press_fit": s.press_fit, "free_fit": s.free_fit, "pip_clearance": s.pip_clearance,
                         "min_wall": s.min_wall, "max_overhang": s.max_overhang, "max_bridge": s.max_bridge,
                         "formats": list(s.formats)},
            "printer": _printer_summary(s),
            "sandbox": sandbox.describe(),
            "max_concurrent_builds": STATE["max_builds"],
            **({"token": _token_name(), "build_worker": "separate process (job queue)" if STATE["queue"] else "in-process"}
               if _http() else {}),
        },
        indent=1,
    )


def _pkg_version() -> str:
    from importlib.metadata import version

    return version("b123d-print")


def _printer_summary(s) -> dict:
    from .profiles import load_material, load_printer

    if not s.printer:
        return {"mode": "generic", "note": "no printer profile: no build-volume check; use_printer to set one"}
    out = {"mode": "printer", **load_printer(s.printer).as_dict()}
    if s.material:
        out["material"] = load_material(s.material).as_dict()
    return out


@mcp.tool()
def use_printer(name: str = "", material: str = "", search: str = "") -> str:
    """Optional printer profile (default is generic mode). search: find printer names
    ("bambu a1", "prusa mk4"). name: make it active (saved in the user's config, or over HTTP in
    this workspace's b123d-print.toml; "generic" clears it). material: pla, petg, asa, abs, tpu or
    the user's own. Only change the printer when the user asks for it."""
    from .config import set_user_setting as _set
    from .profiles import load_material, load_printer, search as find

    path = None
    if STATE["transport"] == "http":  # shared server: never change other clients' printer
        init_workspace(_root())
        path = _root() / WORKSPACE_FILE

    def set_user_setting(key, value):
        _set(key, value, path)

    if search and not name:
        hits = find("printers", search)
        return json.dumps({"matches": hits[:50], "more": max(0, len(hits) - 50)})
    try:
        if name in ("generic", "none"):
            set_user_setting("printer", None)
            set_user_setting("material", None)
            return "Generic mode: no printer profile."
        if name:
            load_printer(name)
            set_user_setting("printer", name)
        if material:
            load_material(material)
            set_user_setting("material", material)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e).strip('"')) from None
    return json.dumps(_printer_summary(load_settings(_root())), indent=1)


@mcp.tool()
def new_part(name: str, description: str = "", example: str | None = None) -> str:
    """Create parts/<name>/<name>.py from the template (Dims dataclass, build(d), VARIANTS,
    views, checks) and return its code. name: lower_snake_case. example: copy a bundled example
    instead (see list_parts), e.g. 'hole_coupon' to calibrate hole compensation."""
    if not (_root() / "b123d-print.toml").exists():
        init_workspace(_root())
    try:
        p = _new_part(_root(), load_settings(_root()).parts_dir, name, description, example)
    except (ValueError, FileExistsError) as e:
        raise ToolError(str(e)) from None
    return f"Created {p.relative_to(_root())}. Edit it with write_part. Current code:\n\n{p.read_text(encoding="utf-8")}"


@mcp.tool()
def read_part(name: str) -> str:
    """Return the current code of a part script."""
    return _script(name).read_text(encoding="utf-8")


@mcp.tool()
def write_part(name: str, code: str) -> str:
    """Replace the whole part script with `code` (create the part with new_part first).
    The script must define build(d) (+ Dims, VARIANTS); see b123d-print://guide. Then call build_part."""
    p = _script(name)
    if len(code.encode()) > MAX_SCRIPT_BYTES:
        raise ToolError(f"script too large (> {MAX_SCRIPT_BYTES} bytes)")
    try:
        compile(code, str(p), "exec")
    except SyntaxError as e:
        return f"NOT SAVED: syntax error at line {e.lineno}: {e.msg}\n{e.text or ''}"
    p.write_text(code, encoding="utf-8")
    return f"Saved {p.relative_to(_root())} ({len(code.splitlines())} lines). Next: build_part('{name}')."


@mcp.tool()
async def build_part(name: str, variant: str | None = None) -> str:
    """Run the part script (sandboxed, with a timeout) and report, per variant and part: bounding
    box size and min/max (mm), volume (mm^3), solid count, is_valid, the Dims values, and any
    error with its traceback. Writes no files. variant: key from VARIANTS ('standard' = '')."""
    res = await _job(name, "build", variant=variant)
    if not res.get("ok"):
        return _error_text(res)
    res.pop("ok", None)
    return json.dumps(res, indent=1, default=str)


@mcp.tool(structured_output=False)
async def render_preview(name: str, variant: str | None = None, parts: str | None = None,
                         size: str = "normal", inline: bool = True) -> list:
    """Render six views (iso, top, front, right, iso from below, bottom) as a PNG image.
    parts: comma-separated part names from build() (several are laid out side by side), 'assembly'
    (assembled position with stand-ins), or omit: the assembly if the script has one, else every
    printable part side by side. One variant (default: the first). size: 'normal' or 'small'
    (~800 px wide, cheaper). inline=False returns only the file (over HTTP: its download link),
    not the image itself."""
    _image_options(size)
    res = await _job(name, "render", variant=variant, parts=parts, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    summary = {"variant": res["variant"], "layout": res["layout"], "drawn": res["drawn"], "parts": res["parts"],
               "file": _show(res["image"])}
    return _with_image(json.dumps(summary, indent=1), res["image"], inline)


@mcp.tool(structured_output=False)
async def section(name: str, plane: str, at: float, variant: str | None = None, parts: str | None = None,
                  size: str = "normal", inline: bool = True) -> list:
    """Cross-section as a PNG image, each part in its own color. plane: 'XY' (at = Z height),
    'XZ' (at = Y) or 'YZ' (at = X), in mm. parts: default the assembly if the script has one
    (shows fit and clearances), else all printable parts; or comma-separated names.
    size: 'normal' or 'small' (~800 px wide). inline=False returns only the file (over HTTP: its
    download link), not the image itself."""
    if plane.upper() not in ("XY", "XZ", "YZ"):
        return ["plane must be XY, XZ or YZ"]
    _image_options(size)
    res = await _job(name, "section", variant=variant, parts=parts, plane=plane, at=at, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    return _with_image(f"{res['plane']} section at {res['at']:g} mm ({res['variant']}): {_show(res['image'])}", res["image"], inline)


@mcp.tool()
async def check(name: str, variant: str | None = None) -> str:
    """Run the print checks: validity, overlap between assembly parts (incl. stand-ins),
    overhangs > 45 deg from vertical in print orientation (bed face ignored) and bridge spans,
    thin features (walls under one line width fail), round-topped horizontal holes, fillets on
    bed edges, gaps between parts printed in place, the script's Wall checks (thinnest material
    around deep cuts) and Probes. Fix every FAIL; report every WARN."""
    res = await _job(name, "check", variant=variant)
    if not res.get("ok"):
        return _error_text(res)
    lines = [f"{'PASSED' if res['passed'] else 'FAILED'}"]
    for v, findings in res["variants"].items():
        lines.append(f"\n{name} [{v}]")
        for f in findings:
            lines.append(f"  [{f['level'].upper():4}] {f['check']:8} {f['target']}: {f['message']}")
    return "\n".join(lines)


@mcp.tool(structured_output=False)
async def export(name: str, variant: str | None = None, formats: str | None = None, parts: str | None = None,
                 embed: bool = False) -> list:
    """Export printable parts to parts/<name>/out/. Default: every part, all variants.
    parts: comma-separated part names from build() to export only those; variant: one variant.
    formats: comma-separated from step (other CAD: Onshape, Fusion, FreeCAD), stl and 3mf
    (slicers; 3MF keeps units), png (6-view preview + section views), or 'all'. Omit to use the
    user's `formats` setting (default: all four). Ask the user which they want if unclear.
    Over HTTP (a remote server) each file comes with a download link (no token needed, expires)
    and a b123d-print://files/ resource link; embed=True also puts files up to 2 MB into the
    result itself, for clients that can neither fetch URLs nor read resources."""
    if formats:
        try:
            parse_formats(formats)
        except ValueError as e:
            raise ToolError(str(e)) from None
    res = await _job(name, "export", variant=variant, formats=formats, parts=parts)
    if not res.get("ok"):
        return [_error_text(res)]
    out, extra, expires, budget = [], [], None, EMBED_TOTAL
    files = [Path(f) for v in res["variants"] for f in v["files"]]
    total = sum(f.stat().st_size for f in files)
    out.append(f"Exported {len(files)} file(s), {total / 1e6:.1f} MB in all.")
    if not formats and not formats_configured(_root()):
        out.append("These are the default formats (STEP, STL, 3MF and PNG). Narrow them: 3MF for Bambu/Orca/Prusa "
                   "slicers, STEP to edit in other CAD; pass formats= (e.g. formats='3mf') or set `formats` in the config.")
    for v in res["variants"]:
        out.append(f"[{v['variant']}]")
        for pname, r in v["parts"].items():
            out.append(f"  {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, valid={r['valid']}")
        for f in v["files"]:
            info = _file_info(Path(f)) if _http() else None
            if not info:
                out.append(f"  {Path(f).relative_to(_root())}")
                continue
            out.append(f"  {info['path']}  {info['url']}")
            extra.append(_resource_link(info))
            expires = info["expires"]
            if embed and info["size"] <= min(EMBED_MAX, budget):
                extra.append(_embedded(Path(f), info))
                budget -= info["size"]
    if expires:
        out.append("\n" + _expiry_note(expires))
    return ["\n".join(out), *extra]


def _workspace_file(rel: str) -> Path:
    """A mesh file inside the workspace (relative to it); anything outside is refused."""
    from .compare import MESH_SUFFIXES

    p = (_root() / rel).resolve()
    if not p.is_relative_to(_root().resolve()):
        raise ToolError(f"{rel!r} is outside the workspace; use a path relative to {_root()}")
    if p.suffix.lower() not in MESH_SUFFIXES:
        raise ToolError(f"{rel!r}: use one of {', '.join(MESH_SUFFIXES)}")
    if not p.is_file():
        raise ToolError(f"no file {rel!r} in the workspace")
    return p


@mcp.tool(structured_output=False)
async def compare(reference: str, candidate: str, thresholds: str = "", image: bool = False,
                  size: str = "normal", inline: bool = True) -> list:
    """Compare a part with a reference model: bounding box, volume and surface area differences,
    surface distances (mean, Hausdorff) after aligning orientation, an F-score, a 0-100 score and
    pass/fail. reference, candidate: STL, 3MF or STEP files inside the workspace, as paths relative
    to it (e.g. 'refs/bracket.stl', 'parts/bracket/out/bracket.3mf'). thresholds: optional
    overrides, comma-separated name=value (e.g. 'hausdorff_mm=2,volume_rel=0.05'). image: also
    return a view of the reference colored by deviation (green = matches, red = off); size:
    'normal' or 'small' (~800 px wide); inline=False returns only its file (over HTTP: a link)."""
    from dataclasses import asdict

    from .compare import Criteria

    _image_options(size)
    ref, cand = _workspace_file(reference), _workspace_file(candidate)
    try:
        crit = Criteria.from_pairs([t for t in thresholds.split(",") if t.strip()])
    except ValueError as e:
        raise ToolError(str(e)) from None
    # the files may come from model-written scripts: parse them in the sandbox, like a build
    job = {"op": "compare", "reference": str(ref), "candidate": str(cand), "criteria": asdict(crit),
           "image": f"{cand.stem}_vs_{ref.stem}{'_small' if size == 'small' else ''}.png" if image else None, "size": size}
    res = await _run(job, cand.parent)
    if not res.get("ok"):
        return [_error_text(res)]
    text = res["text"] + "\n\n" + json.dumps({k: res[k] for k in ("metrics", "checks", "alignment")}, indent=1)
    return _with_image(text, res["image"], inline) if res.get("image") else [text]


# ---------------------------------------------------------------------------------------------
# Resources and prompts (the workflow, model-neutral)


@mcp.resource("b123d-print://guide", mime_type="text/markdown")
def guide() -> str:
    """The workflow and print rules (same text as AGENTS.md)."""
    return data("AGENTS.md")


@mcp.resource("b123d-print://template", mime_type="text/x-python")
def template() -> str:
    """The part-script template new_part starts from."""
    return data("part_template.py")


@mcp.resource("b123d-print://files/{workspace}/{+path}", mime_type="application/octet-stream")
def workspace_file(workspace: str, path: str) -> bytes:
    """A file the server wrote (parts/<part>/out/...), in this session's own workspace ('_' = the
    root workspace). Tool results link to these; over HTTP the same files have download links."""
    from mcp.server.mcpserver.exceptions import ResourceError

    if workspace != _ws_name():
        raise ResourceError(f"workspace {workspace!r} is not this session's ({_ws_name()!r})")
    root = _root()
    try:
        return links.servable(root, load_settings(root).parts_dir, path).read_bytes()
    except links.LinkError:
        raise ResourceError(f"no file {path!r} (only parts/<part>/out/ files are served)") from None


def _rules() -> str:
    return data("AGENTS.md")


@mcp.prompt()
def design_part_from_photos(description: str = "") -> str:
    """Design a new part from photos and measurements: confirm dimensions first, then model,
    verify and report."""
    return f"""I want a 3D-printable part designed with the b123d-print tools.

{description or '(I will describe the part and attach photos.)'}

Work in these steps:
1. From my photos and text, LIST EVERY DIMENSION you read, the feature it belongs to and its
   source (typed by me / read from a photo / estimate). List features you can see that have no
   dimension. Flag any conflict between a photo and a typed number (typed wins). Ask about
   anything missing or ambiguous. Then STOP and wait for my confirmation. Do not model yet.
2. After I confirm: new_part, then write_part with every dimension as a named UPPER_CASE field
   of the Dims dataclass (mm, with a source comment). Mating features get CLEARANCE (0.2 mm
   default per side, from config). Holes get HOLE_COMP (from config; horizontal ones a teardrop and
   HOLE_COMP_H). Model in print orientation, bed at Z=0.
3. Verify: build_part, render_preview, section through every pocket, boss, rib, hole and mating
   feature, and check. Add Wall checks wherever a cut goes deeper than the wall it starts in.
   Fix and repeat until check passes.
4. Report: overall X x Y x Z, key feature sizes, validity, clearances (per side or total) and
   hole compensation applied, check results and warnings, print orientation, supports needed.

The full rules:

{_rules()}"""


@mcp.prompt()
def modify_part(name: str, change: str) -> str:
    """Change an existing part, keeping its conventions, and re-verify."""
    return f"""Change the part '{name}': {change}

read_part first. Keep the script's conventions: change Dims fields rather than numbers in the
geometry, add a variant to VARIANTS instead of copying the script if the old version should stay.
If the change needs a dimension I have not given, ask. After write_part: build_part,
render_preview, a section through what changed, and check (add a Wall check if the change cuts
deeper than a wall). Report what changed in numbers.

The full rules:

{_rules()}"""


@mcp.prompt()
def verify_part(name: str) -> str:
    """Review an existing part against the rules and report findings."""
    return f"""Review the part '{name}' before I print it. read_part, build_part, render_preview,
section through every pocket, boss, rib, hole and mating feature, and check. Look for: missing
Wall checks around cuts deeper than their wall, magic numbers outside Dims, missing clearance or
hole compensation, overhangs that need supports, bed edges with fillets. Report findings
most serious first; do not change the script unless I ask.

The full rules:

{_rules()}"""


@mcp.prompt()
def calibrate_hole_comp() -> str:
    """Walk through measuring HOLE_COMP with the calibration coupon."""
    return """Help me calibrate hole compensation for my printer.
1. If the workspace has no 'hole_coupon' part, create it with
   new_part('hole_coupon', example='hole_coupon') (vertical holes 2-8 mm in the plate, horizontal
   round and teardrop holes 3-8 mm in the tab, all cut at NOMINAL size, labeled), then export it
   and tell me where the file is.
2. Ask me to print it with my usual material and settings and to measure every vertical hole
   and every teardrop (the upper row of the tab).
3. Compute HOLE_COMP = average(nominal - measured) over the vertical holes I use, and
   HOLE_COMP_H the same over the teardrops; point out if the error grows with size. Tell me to
   store them with `b123d-print printer calibrate hole_comp <value>` (and hole_comp_h) when a
   printer profile is set, else in ~/.config/b123d-print/config.toml:
       [print]
       hole_comp = <value>
       hole_comp_h = <value>
   Do not hard-code them in part scripts. The fit_coupon and overhang_bridge_coupon examples
   measure the fits and the overhang and bridge limits the same way."""


# ---------------------------------------------------------------------------------------------
# HTTP transport


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Liveness for Docker / monitors; needs no token and reveals nothing but the version (and, with
    a separate build worker, whether it is alive: 503 "degraded" when it is not)."""
    from starlette.responses import JSONResponse

    body = {"status": "ok", "version": _pkg_version()}
    if STATE["queue"] is not None:
        age = jobqueue.worker_age(STATE["queue"])
        body["worker"] = "ok" if age is not None and age < jobqueue.HEARTBEAT_STALE else "down"
        if body["worker"] != "ok":
            body["status"] = "degraded"
            return JSONResponse(body, status_code=503)
    return JSONResponse(body)


@mcp.custom_route("/files/{workspace}/{token}/{path:path}", methods=["GET", "HEAD"])
async def download(request):
    """A signed download link (see links.py): needs no bearer token, serves one file until it expires."""
    from starlette.responses import FileResponse, PlainTextResponse

    ws, token, path = (request.path_params[k] for k in ("workspace", "token", "path"))
    try:
        links.check_path(path)
        links.verify(STATE["link_secret"], ws, token, path)
        root = _ws_dir(ws)
        if root is None:
            raise links.LinkError(404, "not found")
        f = links.servable(root, load_settings(root).parts_dir, path)
    except links.LinkError as e:
        return PlainTextResponse(str(e) + "\n", status_code=e.status)
    mime = links.content_type(path)
    return FileResponse(f, media_type=mime, filename=f.name,
                        content_disposition_type="inline" if mime == "image/png" else "attachment",
                        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


async def _deny(send, status: int, error: str, description: str) -> None:
    body = json.dumps({"error": error, "error_description": description}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer error="invalid_token"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _log(scope, who: str, status: int, workspace: str | None = None) -> None:
    path = scope["path"]
    if path.startswith("/files/"):  # never log the signature: a log line must not be a working link
        parts = path.split("/", 4)
        path = f"/files/{parts[2] if len(parts) > 2 else '?'}/…/{parts[4] if len(parts) > 4 else ''}"
    client = (scope.get("client") or ("-",))[0]
    ws = f" ws={workspace}" if workspace is not None else ""
    print(f"b123d-print-mcp: {client} {who} {scope['method']} {path}{ws} -> {status}", file=sys.stderr, flush=True)


class TokenAuth:
    """ASGI wrapper: every HTTP request except /health and the signed /files/ links (which carry
    their own HMAC, see download) needs `Authorization: Bearer <token>` of a known named token, and
    may use only that token's workspaces (403 otherwise). A request without ?workspace= gets the
    token's single workspace if it has exactly one, else the shared root workspace. Every request
    is logged with the token's name.

    (The SDK's own bearer auth is the OAuth resource-server path: it wants an issuer URL and a
    token verifier fixed when MCPServer is built, and advertises OAuth metadata that would send
    clients looking for an authorization server that does not exist.)"""

    def __init__(self, app, store: tokens.Store | None):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = {"code": 0}

        async def send_logged(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        path = scope["path"]
        if path == "/health":
            return await self.app(scope, receive, send)
        if path.startswith("/files/"):
            await self.app(scope, receive, send_logged)
            return _log(scope, "link", status["code"])
        if self.store is None:  # --insecure-no-auth
            await self.app(scope, receive, send_logged)
            return _log(scope, "(no auth)", status["code"])
        headers = dict(scope["headers"])
        scheme, _, cred = headers.get(b"authorization", b"").partition(b" ")
        tok = self.store.check(cred.strip().decode(errors="replace")) if scheme.lower() == b"bearer" and cred.strip() else None
        if tok is None:
            await _deny(send, 401, "invalid_token", "missing, wrong or revoked bearer token")
            return _log(scope, "(bad token)", 401)
        from urllib.parse import parse_qs

        ws = (parse_qs(scope.get("query_string", b"").decode()).get("workspace") or [None])[0] \
            or headers.get(b"x-b123d-workspace", b"").decode() or None
        if ws is None and tok.default_workspace():
            ws = tok.default_workspace()
            scope.setdefault("state", {})["b123d_workspace"] = ws
        if not tok.allows(ws):
            await _deny(send, 403, "forbidden", f"token {tok.name!r} may use workspaces {tok.workspaces}; this request "
                        f"asked for {('workspace ' + repr(ws)) if ws else 'the shared root workspace (no ?workspace=)'}")
            return _log(scope, tok.name, 403, ws or tokens.ROOT_WS)
        scope.setdefault("state", {})["b123d_token"] = tok.name
        await self.app(scope, receive, send_logged)
        _log(scope, tok.name, status["code"], ws or tokens.ROOT_WS)


def _token() -> str | None:
    tok = os.environ.get("B123D_PRINT_TOKEN")
    if not tok and os.environ.get("B123D_PRINT_TOKEN_FILE"):
        tok = Path(os.environ["B123D_PRINT_TOKEN_FILE"]).expanduser().read_text(encoding="utf-8")
    return tok.strip() if tok else None


def http_app(host: str, store: tokens.Store | None, allowed_hosts: str | None = None):
    """The Streamable HTTP app (stateless: survives server restarts, any replica can answer)."""
    from mcp.server.transport_security import TransportSecuritySettings

    sec = None  # SDK default: Host/Origin checks on when bound to localhost, off otherwise
    if allowed_hosts:  # e.g. behind a reverse proxy: "cad.example.com,cad.example.com:*"
        hosts = [h.strip() for h in allowed_hosts.split(",") if h.strip()]
        sec = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts)
    app = mcp.streamable_http_app(stateless_http=True, host=host, transport_security=sec)
    return TokenAuth(app, store)


def _healthcheck(args) -> int:
    if args.transport != "http":
        return 0  # stdio: nothing listens; the container is healthy while the process runs
    import urllib.request

    host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    try:
        with urllib.request.urlopen(f"http://{host}:{args.port}/health", timeout=5) as r:
            return 0 if r.status == 200 else 1
    except OSError as e:
        print(f"unhealthy: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    """The server's command line; the docs' reference is generated from it."""
    env = os.environ.get
    ap = argparse.ArgumentParser(prog="b123d-print-mcp", description=" ".join(__doc__.split("\n\n")[0].split()))
    ap.add_argument("--workspace", default=env("B123D_PRINT_WORKSPACE"),
                    help="folder with b123d-print.toml / parts/ (default: $B123D_PRINT_WORKSPACE, else the cwd)")
    ap.add_argument("--timeout", type=float, default=float(env("B123D_PRINT_TIMEOUT", 120)),
                    help="seconds per build (default 120)")
    ap.add_argument("--max-builds", type=int, default=int(env("B123D_PRINT_MAX_BUILDS", 0)) or max(1, (os.cpu_count() or 2) // 2),
                    help="build processes at once, across all clients; more calls wait (default: half the CPUs; $B123D_PRINT_MAX_BUILDS)")
    ap.add_argument("--transport", choices=("stdio", "http"), default=env("B123D_PRINT_TRANSPORT", "stdio"),
                    help="stdio (default) or http: Streamable HTTP at /mcp ($B123D_PRINT_TRANSPORT)")
    ap.add_argument("--host", default=env("B123D_PRINT_HOST", "127.0.0.1"),
                    help="http: address to bind (default 127.0.0.1; $B123D_PRINT_HOST)")
    ap.add_argument("--port", type=int, default=int(env("B123D_PRINT_PORT", 8000)), help="http: port (default 8000; $B123D_PRINT_PORT)")
    ap.add_argument("--allowed-hosts", default=env("B123D_PRINT_ALLOWED_HOSTS"),
                    help="http: comma-separated Host header values to accept (DNS-rebinding check; $B123D_PRINT_ALLOWED_HOSTS)")
    ap.add_argument("--shutdown-grace", type=float, default=float(env("B123D_PRINT_SHUTDOWN_GRACE", 30)),
                    help="http: on SIGTERM/Ctrl-C, seconds to let running calls finish before their builds are killed (default 30)")
    ap.add_argument("--public-url", default=env("B123D_PRINT_PUBLIC_URL"),
                    help="http: base URL clients reach the server at, for download links, e.g. https://cad.example.com "
                         "(default: from the request; $B123D_PRINT_PUBLIC_URL)")
    ap.add_argument("--link-ttl", type=float, default=float(env("B123D_PRINT_LINK_TTL", 3600)),
                    help="http: seconds a download link stays valid (default 3600; $B123D_PRINT_LINK_TTL)")
    ap.add_argument("--tokens-file", default=env("B123D_PRINT_TOKENS_FILE"),
                    help="http: named tokens, each limited to workspaces (see `token add`); re-read when it changes "
                         "($B123D_PRINT_TOKENS_FILE)")
    ap.add_argument("--job-queue", default=env("B123D_PRINT_JOB_QUEUE"),
                    help="http: hand builds to a separate `worker` process through this folder instead of running "
                         "them here (the Docker setup's network-less worker container; $B123D_PRINT_JOB_QUEUE)")
    ap.add_argument("--insecure-no-auth", action="store_true",
                    help="http: run without any token (otherwise $B123D_PRINT_TOKENS_FILE, $B123D_PRINT_TOKEN or "
                         "$B123D_PRINT_TOKEN_FILE is required)")
    ap.add_argument("--healthcheck", action="store_true", help="check the running HTTP server's /health and exit (for Docker)")
    sub = ap.add_subparsers(dest="command", metavar="{token,worker}")
    tk = sub.add_parser("token", help="manage the named tokens in --tokens-file")
    tsub = tk.add_subparsers(dest="token_command", required=True)
    add = tsub.add_parser("add", help="create a token, print it once, store only its SHA-256")
    add.add_argument("name", help="who uses it, e.g. grok-chromebook")
    add.add_argument("--workspace", action="append",
                     help="workspace name or pattern it may use, e.g. 'grok-*' (repeatable; default: every workspace)")
    tsub.add_parser("list", help="the tokens, their workspaces and when they were made (never the tokens)")
    rv = tsub.add_parser("revoke", help="delete a token; the server stops accepting it at once")
    rv.add_argument("name")
    wk = sub.add_parser("worker", help="run builds handed over through --queue (pairs with the server's --job-queue)")
    wk.add_argument("--queue", required=True, help="the folder shared with the server")
    wk.add_argument("--check", action="store_true", help="exit 0 if a worker's heartbeat is fresh (Docker health check)")
    return ap


def main() -> None:
    env = os.environ.get
    args = build_parser().parse_args()
    if args.command == "token":
        sys.exit(tokens.cli(args))
    if args.command == "worker" and env("B123D_PRINT_CONFIG_IN_WORKSPACE") == "1" and args.workspace:
        # the worker container must read the same user settings (calibrations) as the server
        os.environ["XDG_CONFIG_HOME"] = str(Path(args.workspace).expanduser().resolve() / ".config")
    if args.command == "worker":
        sys.exit(jobqueue.main(Path(args.queue).expanduser().resolve(), max(1, args.max_builds), args.check))
    if args.healthcheck:
        sys.exit(_healthcheck(args))
    root = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".b123d-print-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        sys.exit(f"b123d-print-mcp: workspace {root} is not writable: {e}")
    if env("B123D_PRINT_CONFIG_IN_WORKSPACE") == "1":
        # containers: keep user settings (printer, calibration) with the mounted parts, not in a
        # home folder that disappears with the container
        os.environ["XDG_CONFIG_HOME"] = str(root / ".config")
    STATE.update(root=root, timeout=args.timeout, transport=args.transport, max_builds=max(1, args.max_builds))
    if args.transport == "stdio":
        mcp.run("stdio")
        return
    try:
        token = _token()
    except OSError as e:
        sys.exit(f"b123d-print-mcp: cannot read B123D_PRINT_TOKEN_FILE: {e}")
    if token and len(token) < 16:
        sys.exit("b123d-print-mcp: B123D_PRINT_TOKEN is too short (use at least 16 characters)")
    tokens_file = Path(args.tokens_file).expanduser() if args.tokens_file else None
    if tokens_file and not tokens_file.is_file():
        sys.exit(f"b123d-print-mcp: no tokens file {tokens_file}: create it with "
                 f"`b123d-print-mcp --tokens-file {tokens_file} token add <name> --workspace <pattern>`")
    store = None
    if tokens_file or token:
        try:
            store = tokens.Store(tokens_file, token)
        except (OSError, ValueError) as e:
            sys.exit(f"b123d-print-mcp: cannot read the tokens file: {e}")
    if (store is None or not store.names()) and not args.insecure_no_auth:
        sys.exit("b123d-print-mcp: HTTP needs a token: add named tokens with `b123d-print-mcp --tokens-file <path> "
                 "token add <name>` and set B123D_PRINT_TOKENS_FILE, or set B123D_PRINT_TOKEN (or "
                 "B123D_PRINT_TOKEN_FILE), or pass --insecure-no-auth")
    if args.insecure_no_auth:
        store = None
    secret = env("B123D_PRINT_LINK_SECRET") or (store.link_secret if store else None)
    queue = Path(args.job_queue).expanduser().resolve() if args.job_queue else None
    if queue:
        queue.mkdir(parents=True, exist_ok=True)
    STATE.update(tokens=store, queue=queue,
                 link_secret=links.derive_secret(token, secret), link_ttl=max(1.0, args.link_ttl),
                 public_url=(args.public_url or "").rstrip("/") or None,
                 allowed_hosts=[h.strip() for h in (args.allowed_hosts or "").split(",") if h.strip()])
    if STATE["public_url"] and not re.match(r"^https?://[^/\s]+(/\S*)?$", STATE["public_url"]):
        sys.exit(f"b123d-print-mcp: --public-url must look like https://host[:port][/prefix], got {args.public_url!r}")
    import uvicorn

    auth = f"tokens {', '.join(store.names())}" if store else "NONE"
    print(f"b123d-print-mcp: http://{args.host}:{args.port}/mcp  workspace {root}  auth {auth}  "
          f"max builds {STATE['max_builds']}  builds {'in worker via ' + str(queue) if queue else 'here'}", file=sys.stderr)
    if store:  # SIGHUP: re-read the tokens file now (it is also re-read whenever it changes)
        signal.signal(signal.SIGHUP, lambda *_: store.request_reload())
    # uvicorn handles SIGTERM/SIGINT: stop accepting, let running calls finish for up to
    # --shutdown-grace seconds, then cancel them; any build still running is killed here
    # uvicorn re-raises the signal after its shutdown; make SIGTERM a normal exit so the cleanup runs
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        # access_log off: TokenAuth logs every request with the token's name instead
        uvicorn.run(http_app(args.host, store, args.allowed_hosts), host=args.host, port=args.port,
                    log_level="info", access_log=False, timeout_graceful_shutdown=args.shutdown_grace)
    finally:
        n = sandbox.kill_all()
        if queue:
            jobqueue.cancel_all(queue)
        print(f"b123d-print-mcp: stopped{f' ({n} running build(s) killed)' if n else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
