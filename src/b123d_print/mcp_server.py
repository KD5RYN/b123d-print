"""b123d-print MCP server: design, check and export 3D-printable build123d parts from any MCP
client. Part scripts are model-written code: every build runs in a sandboxed subprocess.

    b123d-print-mcp --workspace ~/parts            # stdio; or B123D_PRINT_WORKSPACE=~/parts; default: the cwd
    B123D_PRINT_TOKEN=... b123d-print-mcp --transport http --port 8000   # Streamable HTTP at /mcp

Over HTTP every request needs `Authorization: Bearer <token>`, and each client picks its own
workspace with `/mcp?workspace=<name>` (or the header `X-B123D-Workspace`), which is the folder
<workspace>/workspaces/<name>; without one, clients share <workspace> itself. Files the server
writes come back as signed download links (GET /files/..., no token, they expire) and as
b123d-print://files/ resources; download_part gives one signed link (GET /zip/...) to a zip of a
whole part. A named workspace nobody uses for --retention-days (default 30) is removed.
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
from importlib.metadata import version as _dist_version
from pathlib import Path

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import handoff, jobqueue, links, sandbox, tokens
from .cli import NAME_RE, data, examples, init_workspace, new_part as _new_part
from .config import WORKSPACE_FILE, formats_configured, load_settings, parse_formats, safe_console
from .project import find_parts

MAX_SCRIPT_BYTES = 256_000

INSTRUCTIONS = """\
Design 3D-printable parts as build123d Python scripts, then build, look at, check and export them.
Workflow: new_part -> write_part (whole script) -> build_part -> render_preview + section ->
check -> fix and repeat -> (offer a fit-test template: list_faces, make_template) -> export. To remix an existing STL/3MF/STEP: upload_reference ->
describe_model -> import_model in the script (prompt remix_part). Read the resource
b123d-print://guide (or the prompt design_part_from_photos) for the rules: named UPPER_CASE dimensions in a Dims dataclass, mm,
print orientation with the bed at Z=0, 0.2 mm mating clearance, HOLE_COMP from the user's config,
list photo-read dimensions and wait for confirmation, verify with renders, sections and checks
before reporting. render_preview and section return PNG images.
When this server is remote (HTTP or SSH), it is a workbench, not storage: what it writes is a
temporary working copy, deleted after some days unused. Use ONLY these MCP tools and the links they
return; the server gives no shell, ssh or scp access. Last step, before reporting: download_part
(name) and bring the part home into the project folder in the same layout as a local install
(parts/<name>/<name>.py, parts/<name>/out/, parts/<name>/ref/): over HTTP `curl -fLo <name>.zip
'<link>'` and unzip it in the project folder; over SSH the `b123d-print pull` command it gives.
Then check the files are there on the user's machine. Locally (stdio) the files are already in
the project folder."""

REMOTE_DOC = """
    Remote server (HTTP/SSH): the files stay on the server, as a temporary working copy deleted
    when unused; bring the part home with download_part (one zip in the parts/<name>/ layout).
    Never use ssh, scp or a shell on the server: there is none."""

WORKSPACE_RE = handoff.WORKSPACE_RE
_WORKSPACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("b123d_print_workspace", default=None)
_REQUEST: contextvars.ContextVar = contextvars.ContextVar("b123d_print_request", default=None)


async def _request_workspace(ctx, call_next):
    """HTTP: the workspace this request asked for (?workspace=<name> or X-B123D-Workspace). The
    request counts as a use of that workspace: retention never removes it meanwhile (see handoff.py)."""
    req = getattr(ctx, "request", None)
    name = None
    if req is not None and hasattr(req, "query_params"):
        name = (req.query_params.get("workspace") or req.headers.get("x-b123d-workspace")
                or req.scope.get("state", {}).get("b123d_workspace"))  # a token's default workspace (TokenAuth)
    token, rtoken = _WORKSPACE.set(name), _REQUEST.set(req)
    _in_use(name, True)
    try:
        return _scrub_result(await call_next(ctx))
    finally:
        _in_use(name, False)
        _WORKSPACE.reset(token)
        _REQUEST.reset(rtoken)


def _scrub_result(result):
    """Remote: no tool result, error messages included, shows the server's own folders (_scrub)."""
    content = result.get("content") if isinstance(result, dict) else getattr(result, "content", None)
    if not _remote() or not isinstance(content, list):
        return result
    try:
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                c["text"] = _scrub(c["text"])
            elif getattr(c, "type", "") == "text":
                c.text = _scrub(c.text)
    except ToolError:  # a bad workspace name: _root() refused it, and the result says so
        pass
    return result


def _in_use(name: str | None, start: bool) -> None:
    """A request for workspace `name` starts or ends: touch it, and hold it against retention."""
    if not name or not WORKSPACE_RE.match(name):
        return
    ret = STATE.get("retention")
    if ret is not None:
        (ret.enter if start else ret.leave)(name)
    handoff.touch(STATE["root"] / "workspaces" / name)


# version: what initialize reports as serverInfo.version (the SDK default is "")
mcp = MCPServer("b123d-print", version=_dist_version("b123d-print"), instructions=INSTRUCTIONS,
                middleware=[_request_workspace])
STATE: dict = {"root": Path.cwd(), "timeout": 120.0, "check_timeout": 300.0, "transport": "stdio", "max_builds": 2, "limiter": None,
               "link_secret": b"", "link_ttl": 3600.0, "public_url": None, "allowed_hosts": [],
               "tokens": None, "queue": None, "retention_days": 30.0, "retention": None,
               "ssh_dest": None}  # ssh_dest: user@host when started by `b123d-print ssh-serve`
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
    timeout = STATE["check_timeout"] if job.get("op") == "check" else STATE["timeout"]

    def run() -> dict:
        if queue is None:
            return sandbox.run_job(job, root, out_dir, timeout)
        try:  # a separate worker (container) runs it: see jobqueue.py
            return jobqueue.submit(queue, job, root, out_dir, timeout)
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
    return _scrub(s)


def _http() -> bool:
    return STATE["transport"] == "http"


def _remote() -> bool:
    """HTTP or SSH: the files are on a server, not on the client's machine."""
    return _http() or bool(STATE["ssh_dest"])


def _kept() -> str:
    """How long the server keeps this workspace, for the notes in results."""
    days = STATE["retention_days"]
    if _http() and _WORKSPACE.get() and days > 0:
        return f"deleted after {days:g} days unused"
    return "kept for now, but it is not your copy"


def _home_note(name: str | None) -> str:
    """Remote: where the files are and how to bring them home (empty over stdio)."""
    if not _remote():
        return ""
    call = f"download_part('{name}')" if name else "download_part('<part>')"
    how = (f"{call} and unzip it in your project folder (it creates parts/{name or '<part>'}/)" if _http() else
           f"{call} gives the `b123d-print pull` command that copies it into parts/{name or '<part>'}/ in your project folder")
    return (f"The server copy is a temporary working copy ({_kept()}). Bring it home: {how}. "
            "Do not use ssh/scp: the server gives no shell access.")


def _files_doc(f):
    """Tools that write files: their description says how a remote client gets them (REMOTE_DOC)."""
    f.__doc__ = f.__doc__.rstrip() + REMOTE_DOC
    return f


def _scrub(text: str) -> str:
    """Remote: the server's own folders never show in a result (workspace-relative paths only)."""
    if not _remote():
        return text
    return handoff.hide_paths(text, [_root(), _root().resolve(), STATE["root"], STATE["root"].resolve()])


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


def _file_info(path: Path, link: bool = True) -> dict | None:
    """How a client gets a file the server wrote (None if it is not one the server serves): its
    resource URI and, over HTTP with link=True, a signed download link."""
    root = _root()
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        links.servable(root, load_settings(root).parts_dir, rel)
    except (ValueError, links.LinkError):
        return None
    info = {"path": rel, "size": path.stat().st_size, "mime": links.content_type(rel),
            "uri": f"b123d-print://files/{_ws_name()}/{rel}"}
    if link and _http():
        url, expires = links.sign(STATE["link_secret"], _ws_name(), rel, STATE["link_ttl"])
        info.update(url=_base_url() + url, expires=expires)
    return info


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
        note = f"\nImage file: {_show(image)}"
    return [text + note, *([Image(path=image)] if inline else []), *extra]


def _with_note(result: list, name: str | None) -> list:
    """Remote: the bring-it-home note after a result that wrote files."""
    note = _home_note(name)
    if note and result and isinstance(result[0], str):
        result[0] += "\n\n" + note
    return result


def _show(image: str) -> str:
    """The image's path as the client should see it: workspace-relative over HTTP and SSH, absolute over stdio."""
    return Path(image).relative_to(_root()).as_posix() if _remote() else image


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
            **({"workspace": _ws_name(), "files": "on the server: a temporary working copy; download_part(<name>) "
                                                    "brings a part home"} if _remote() else {"workspace": str(_root())}),
            "parts_dir": s.parts_dir,
            "parts": parts,
            "examples": examples(),
            "settings": {"hole_comp": s.hole_comp, "hole_comp_h": s.hole_comp_h, "clearance": s.clearance,
                         "press_fit": s.press_fit, "free_fit": s.free_fit, "pip_clearance": s.pip_clearance,
                         "min_wall": s.min_wall, "max_overhang": s.max_overhang, "max_bridge": s.max_bridge,
                         "formats": list(s.formats)},
            "printer": _printer_summary(s),
            "styles": _styles(),
            "sandbox": sandbox.describe(),
            "max_concurrent_builds": STATE["max_builds"],
            **({"token": _token_name(), "build_worker": "separate process (job queue)" if STATE["queue"] else "in-process"}
               if _http() else {}),
        },
        indent=1,
    )


def _styles() -> dict:
    from .styles import available

    return available(_root())


def _pkg_version() -> str:
    return _dist_version("b123d-print")


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
    ("bambu a1", "prusa mk4"). name: make it active (saved in the user's config, or over HTTP and
    SSH in this workspace's b123d-print.toml; "generic" clears it). material: pla, petg, asa, abs, tpu or
    the user's own. Only change the printer when the user asks for it."""
    from .config import set_user_setting as _set
    from .profiles import load_material, load_printer, search as find

    path = None
    if STATE["transport"] == "http" or STATE["ssh_dest"]:  # shared server: never change other clients' printer
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


def _human_size(n: int) -> str:
    """Bytes as B / KB / MB, so a 34 KB export does not read as "0.0 MB"."""
    if n < 1000:
        return f"{n} B"
    if n < 1_000_000:
        return f"{n / 1000:.0f} KB"
    return f"{n / 1e6:.1f} MB"


@mcp.tool()
def new_part(name: str, description: str = "", example: str | None = None, show_code: bool = False) -> str:
    """Create parts/<name>/<name>.py from the template (Dims dataclass, build(d), VARIANTS,
    views, checks). name: lower_snake_case. example: copy a bundled example instead (see
    list_parts), e.g. 'hole_coupon' to calibrate hole compensation. Returns a short confirmation;
    the template is the b123d-print://template resource (or read_part), show_code=True returns
    the new file's code here. Usually the next step is write_part with the whole script."""
    if not (_root() / "b123d-print.toml").exists():
        init_workspace(_root())
    try:
        p = _new_part(_root(), load_settings(_root()).parts_dir, name, description, example)
    except (ValueError, FileExistsError) as e:
        raise ToolError(str(e)) from None
    rel = p.relative_to(_root()).as_posix()
    if show_code:
        return f"Created {rel}. Edit it with write_part. Current code:\n\n{p.read_bytes().decode('utf-8')}"
    src = f"the bundled example {example!r}" if example else "the template (resource b123d-print://template)"
    return (f"Created {rel} from {src}. Next: write_part('{name}', <whole script>); read_part('{name}') "
            "shows the current code. A single part returned by build() is named 'part' in checks "
            f"(or '{name}'); return {{'name': part}} to name several.")


@mcp.tool()
def read_part(name: str) -> str:
    """Return the current code of a part script."""
    return _script(name).read_bytes().decode("utf-8")  # exactly as stored: what download_part / pull bring home


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
    p.write_text(code, encoding="utf-8", newline="")  # exactly as sent, on every OS (no CRLF on Windows)
    return f"Saved {p.relative_to(_root()).as_posix()} ({len(code.splitlines())} lines). Next: build_part('{name}')."


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
@_files_doc
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
    return _with_note(_with_image(json.dumps(summary, indent=1), res["image"], inline), name)


@mcp.tool(structured_output=False)
@_files_doc
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
    return _with_note(_with_image(f"{res['plane']} section at {res['at']:g} mm ({res['variant']}): {_show(res['image'])}",
                                  res["image"], inline), name)


async def _check(name: str, variant: str | None) -> dict:
    """Run a check over up to --max-builds workers at once: each builds the part (import_model's
    conversion is cached and shared) and runs its share of the check items (project.partition);
    the findings are merged back in order. Each worker takes a build slot like any build, so on
    a busy server the shares simply take turns; with one slot it is one worker, as before.
    All shares stop at the same soft deadline, so a check that runs out of time still returns
    every finding that finished."""
    count = max(1, STATE["max_builds"])
    if count == 1:
        return await _job(name, "check", variant=variant)
    from .project import merge_shares

    timeout = STATE["check_timeout"]
    started = time.time()
    deadline = started + timeout - sandbox.soft_margin(timeout)
    results: list = [None] * count

    async def one(i: int) -> None:
        results[i] = await _job(name, "check", variant=variant, share=[i, count], deadline=deadline, started=started)

    async with anyio.create_task_group() as tg:
        for i in range(count):
            tg.start_soon(one, i)
    good = [r for r in results if r.get("ok")]
    if not good:
        return results[0]
    failed = [f"check worker {i + 1} of {count} failed: {r.get('error')}"
              for i, r in enumerate(results) if not r.get("ok")]
    out: dict = {"variants": {}, "workers": count}
    for i, v in enumerate(good[0]["shares"]):
        found = merge_shares([r["shares"][v] for r in good if v in r["shares"]], nudge=i == 0, failed=failed)
        out["variants"][v] = [f.__dict__ for f in found]
    out["passed"] = not any(f["level"] == "fail" for v in out["variants"].values() for f in v)
    return {"ok": True, **out}


@mcp.tool()
async def check(name: str, variant: str | None = None) -> str:
    """Run the print checks: validity, overlap between assembly parts (incl. stand-ins),
    overhangs > 45 deg from vertical in print orientation (bed face ignored) and bridge spans,
    thin features (walls under one line width fail), round-topped horizontal holes, fillets on
    bed edges, gaps between parts printed in place, the script's Wall checks (thinnest material
    around deep cuts) and Probes. Fix every FAIL; report every WARN. On a remote server (HTTP/SSH)
    the part is not on the user's machine until download_part brings it home."""
    res = await _check(name, variant)
    if not res.get("ok"):
        return _error_text(res)
    lines = [f"{'PASSED' if res['passed'] else 'FAILED'}"]
    for v, findings in res["variants"].items():
        lines.append(f"\n{name} [{v}]")
        for f in findings:
            lines.append(f"  [{f['level'].upper():4}] {f['check']:8} {f['target']}: {f['message']}")
    if res["passed"] and _remote():
        lines.append(f"\nNot on your machine yet: download_part('{name}') brings the part home when it is done. "
                     + _home_note(name))
    return _scrub("\n".join(lines))


@mcp.tool()
async def design_metrics(name: str, variant: str | None = None, style: str = "", up: str = "", as_json: bool = False) -> str:
    """Design numbers for the design review, per printable part: size and proportions, filament
    (simple estimate, roughly +-20 %) and cost, print time (rough estimate), supports, shallow
    slopes that show layer steps, edge treatment (sharp / filleted / chamfered shares, distinct
    radii and chamfer sizes), mirror symmetry, screw sizes, seam corners, water traps, inside
    corners, hole edge distance and slenderness across the layers (and the thinnest walls for a
    style that asks); then the suggestions the part's style triggers, each citing its DS-* rule.
    Run it after check passes. style: override the part's STYLE (functional, modern, least_cost,
    rugged, soft, structural, or a style file of the user's: list_parts shows them). up: the
    direction that points up in use for the water-trap check (+X, -Y, ...; default the script's UP,
    else +Z). as_json: the full numbers as JSON instead of the text report. Changes nothing."""
    if style:
        from .styles import StyleError, load_style

        try:
            load_style(style, _root())
        except StyleError as e:
            raise ToolError(str(e)) from None
    res = await _job(name, "metrics", variant=variant, style=style or None, up=up or None)
    if not res.get("ok"):
        return _error_text(res)
    if as_json:
        return json.dumps({"variant": res["variant"], **res["metrics"]}, indent=1, default=str)
    return f"{name} [{res['variant']}]\n{res['text']}"


@mcp.tool(structured_output=False)
@_files_doc
async def export(name: str, variant: str | None = None, formats: str | None = None, parts: str | None = None,
                 embed: bool = False) -> list:
    """Export printable parts to parts/<name>/out/. Default: every part, all variants.
    parts: comma-separated part names from build() to export only those; variant: one variant.
    formats: comma-separated from step (other CAD: Onshape, Fusion, FreeCAD), stl and 3mf
    (slicers; 3MF keeps units), png (6-view preview + section views), or 'all'. Omit to use the
    user's `formats` setting (default: all four). Ask the user which they want if unclear.
    Over HTTP (a remote server) each file comes with a download link (no token needed, expires)
    and a b123d-print://files/ resource link; download_part gets the whole part (script, out/,
    ref/) in one zip. embed=True also puts files up to 2 MB into the result itself, for clients
    that can neither fetch URLs nor read resources."""
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
    out.append(f"Exported {len(files)} file(s), {_human_size(total)} in all.")
    if not formats and not formats_configured(_root()):
        out.append("These are the default formats (STEP, STL, 3MF and PNG). Narrow them: 3MF for Bambu/Orca/Prusa "
                   "slicers, STEP to edit in other CAD; pass formats= (e.g. formats='3mf') or set `formats` in the config.")
    for v in res["variants"]:
        out.append(f"[{v['variant']}]")
        for pname, r in v["parts"].items():
            out.append(f"  {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, valid={r['valid']}")
        for f in v["files"]:
            info = _file_info(Path(f)) if (_http() or embed) else None
            if not info:
                out.append(f"  {Path(f).relative_to(_root()).as_posix()}")
                continue
            if "url" in info:
                out.append(f"  {info['path']}  {info['url']}")
                extra.append(_resource_link(info))
                expires = info["expires"]
            else:
                out.append(f"  {info['path']}")
            if embed and info["size"] <= min(EMBED_MAX, budget):
                extra.append(_embedded(Path(f), info))
                budget -= info["size"]
    if expires:
        out.append("\n" + _expiry_note(expires))
    if STATE["ssh_dest"]:
        out.append("\n" + _pull_note(name, formats, None))
    if _remote():
        out.append("\n" + _home_note(name))
    return ["\n".join(out), *extra]


def _triple(v, what: str) -> list[float] | None:
    """Three numbers from a list or an "x,y,z" string."""
    if v is None or v == "":
        return None
    try:
        vals = [float(x) for x in (v.replace(";", ",").split(",") if isinstance(v, str) else v)]
    except (TypeError, ValueError):
        vals = []
    if len(vals) != 3:
        raise ToolError(f"{what}: three numbers x,y,z in mm")
    return vals


@mcp.tool(structured_output=False)
@_files_doc
async def list_faces(name: str, variant: str | None = None, part: str | None = None, highlight: int | str | None = None,
                     size: str = "normal", inline: bool = True) -> list:
    """The flat faces of a printable part, for picking one for a face fit-test template
    (make_template kind='face'): stable ids (1 = the largest; the same geometry always gets the
    same ids, changed geometry may renumber), outward normal and side (bottom, top, front, back,
    left, right), area, center, bounding box, round holes (diameter, center) and other
    openings; curved faces are only counted. part: which printable part (default: the only one).
    highlight: a face id or side; also returns a picture of the part with that face in red, to
    confirm the choice with the user before making the template. size: 'normal' or 'small'."""
    _image_options(size)
    res = await _job(name, "faces", variant=variant, part=part, highlight=highlight, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    image = res.pop("image", None)
    res.pop("ok", None)
    text = json.dumps(res, indent=1)
    if not image:
        return [text]
    return _with_note(_with_image(f"face {res['highlight']} in red: {_show(image)}\n{text}", image, inline), name)


@mcp.tool(structured_output=False)
@_files_doc
async def make_template(name: str, kind: str, plane: str | None = None, at: float | None = None, face: int | str | None = None,
                        center: list[float] | str | None = None, size: list[float] | str | None = None,
                        thickness: float | None = None, label: bool | str = True, base: bool = True,
                        variant: str | None = None, part: str | None = None, formats: str | None = None,
                        inline: bool = True) -> list:
    """A fit-test template: a quick thin print cut from the real part (same hole compensation and
    clearances) to check size, hole pattern and mating fits before printing the whole part. kind:
    'slice' (plane XY/XZ/YZ at = Z/Y/X: the part between two planes `thickness` apart, centered
    on `at`), 'face' (face: an id from list_faces, a side such as 'bottom', or 'x,y,z' on it: that
    flat face with its holes as a plate; a side means the largest face facing that way) or 'crop' (center, size: x,y,z in mm: the part inside
    that box, with a thin base plate where it needs one; base=False: never). thickness: mm
    (default 1.2). label: engrave '<part> <id>' (default), your own text, or false; skipped when
    there is no room. The template is laid flat (template face down, Z=0) and checked like a
    part. Writes parts/<name>/out/<name>_template_<id>.* in `formats` (default: the formats
    setting); with png also <...>_where.png, the part with the template's source in red (returned
    as the image; inline=False: only the file). Confirm the face or region with the user first
    (list_faces with highlight)."""
    kind = (kind or "").lower()
    if kind not in ("slice", "face", "crop"):
        raise ToolError("kind: 'slice', 'face' or 'crop'")
    if isinstance(label, str) and label.strip().lower() in ("", "false", "no", "none", "off", "true", "yes", "on"):
        label = label.strip().lower() in ("true", "yes", "on")
    spec: dict = {"kind": kind, "thickness": thickness, "label": label, "base": base, "part": part}
    if kind == "slice":
        if not plane or plane.upper() not in ("XY", "XZ", "YZ") or at is None:
            raise ToolError("a slice needs plane ('XY' at = Z, 'XZ' at = Y, 'YZ' at = X) and at (mm)")
        spec.update(plane=plane.upper(), at=float(at))
    elif kind == "face":
        if face is None or str(face).strip() == "":
            raise ToolError("a face template needs face: an id from list_faces, a side (bottom, top, front, back, "
                            "left, right) or a point x,y,z on the face")
        f = str(face).strip()
        spec["face"] = int(f) if f.isdigit() else (_triple(f, "face") if "," in f else f)
    else:
        c, sz = _triple(center, "center"), _triple(size, "size")
        if c is None or sz is None:
            raise ToolError("a crop needs center and size, each x,y,z in mm")
        spec.update(center=c, size=sz)
    if formats:
        try:
            parse_formats(formats)
        except ValueError as e:
            raise ToolError(str(e)) from None
    res = await _job(name, "template", variant=variant, spec=spec, formats=formats)
    if not res.get("ok"):
        return [_error_text(res)]
    info, r = res["info"], res["report"]
    lines = [f"Template {res['name']} ({res['variant']}, from {res['part']}): {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, "
             f"valid={r['valid']}, {info['pieces']} piece(s), laid with the part's {info['down']} side down"
             + (" (its print orientation)" if info["print_orientation"] else "")]
    lab = info.get("label")
    lines.append(f"Label: '{lab['text']}' engraved {lab['depth']:g} mm deep" if lab else "Label: none")
    lines += [f"Note: {n}" for n in info.get("notes", [])]
    findings = res.get("findings", [])
    failed = any(f["level"] == "fail" for f in findings)
    lines.append(f"\nChecks: {'FAILED' if failed else 'PASSED'}")
    lines += [f"  [{f['level'].upper():4}] {f['check']:8} {f['target']}: {f['message']}" for f in findings]
    lines.append("\nDetails: " + json.dumps({k: v for k, v in info.items() if k not in ("notes",)}, default=str))
    lines.append("\nFiles:")
    extra, expires, where = [], None, None
    for f in res["files"]:
        if f.endswith("_where.png"):
            where = f
        info_f = _file_info(Path(f)) if _http() else None
        if info_f and "url" in info_f:
            lines.append(f"  {info_f['path']}  {info_f['url']}")
            extra.append(_resource_link(info_f))
            expires = info_f["expires"]
        else:
            lines.append(f"  {Path(f).relative_to(_root()).as_posix()}")
    if expires:
        lines.append("\n" + _expiry_note(expires))
    if STATE["ssh_dest"]:
        lines.append("\n" + _pull_note(name, formats, variant))
    out = ["\n".join(lines)]
    if where and inline:
        out.append(Image(path=where))
    return _with_note(out + extra, name)


def _pull_cmd(name: str, formats: str | None, variant: str | None) -> str:
    import shlex

    cmd = f"b123d-print pull {name}"
    if formats:
        cmd += f" --formats {shlex.quote(formats)}"
    if variant is not None:
        cmd += f" --variant {shlex.quote(variant or 'standard')}"
    return f"{cmd} --from {STATE['ssh_dest']}"


def _pull_note(name: str, formats: str | None, variant: str | None) -> str:
    """SSH: the files are on the server; this is the command that copies the part to the client."""
    return (f"The part is on the SSH server ({STATE['ssh_dest']}). To copy it to the client machine, run this "
            f"there, in the project folder (it uses the same SSH key as this MCP connection; -o DIR picks another "
            f"project folder). It writes parts/{name}/{name}.py, parts/{name}/out/ and parts/{name}/ref/:\n"
            f"  {_pull_cmd(name, formats, variant)}")


def _part_files(name: str, variant: str | None, formats: str | None) -> list[tuple[str, Path]]:
    _script(name)  # the usual "no part" error, with the list of parts
    try:
        fmts = parse_formats(formats) if formats else None
        return handoff.part_files(_root(), load_settings(_root()).parts_dir, name, variant, fmts)
    except (ValueError, SyntaxError) as e:
        raise ToolError(str(e)) from None


@mcp.tool(structured_output=False)
@_files_doc
def download_part(name: str, variant: str | None = None, formats: str | None = None, embed: bool = False) -> list:
    """Bring a whole part home from a remote server, in the same layout a local install writes:
    parts/<name>/<name>.py, parts/<name>/out/ (exports, renders, sections) and parts/<name>/ref/
    (reference models). Over HTTP: ONE signed link (no token needed, expires) to a zip of all of
    it; run `curl -fLo <name>.zip '<link>'` and unzip it in the project folder, then check the
    files are there. Over SSH: the `b123d-print pull` command that writes the same files. Locally
    (stdio): says where the files already are. variant: only that variant's out/ files ('standard'
    = ''); formats: only those out/ files (step, stl, 3mf, png); the script and ref/ always come.
    embed=True also puts the zip (up to 8 MB) into the result, for clients that can neither fetch
    URLs nor read resources. Call it as the last step of remote work, before reporting."""
    files = _part_files(name, variant, formats)
    total = sum(p.stat().st_size for _, p in files)
    parts_dir = load_settings(_root()).parts_dir
    prefix = f"{parts_dir}/{name}"
    listing = "\n".join(f"  {prefix}/{rel}  ({_human_size(p.stat().st_size)})" for rel, p in files)
    head = f"Part '{name}': {handoff.summary(files)}, {_human_size(total)} in all."
    if not _remote():
        return [f"{head}\nThis server runs locally: the files are already in the project folder, "
                f"{_root() / parts_dir / name}. Nothing to download.\n{listing}"]
    if STATE["ssh_dest"]:
        return [f"{head}\n{_pull_note(name, formats, variant)}\nThen check the files are there (e.g. ls parts/{name}/out) "
                f"before reporting.\n{listing}\n\n{_home_note(name)}"]
    query = links.zip_query(variant, formats)
    url, expires = links.sign_zip(STATE["link_secret"], _ws_name(), name, query, STATE["link_ttl"])
    url = _base_url() + url
    when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))
    text = (f"{head}\n"
            f"Download it (one zip, no token needed; the link expires {when}; after that call download_part again):\n"
            f"  curl -fLo {name}.zip '{url}'\n"
            f"Then, in the project folder: unzip -o {name}.zip   (Windows: tar -xf {name}.zip)\n"
            f"It creates the same layout as a local install (paths relative to the project folder):\n{listing}\n"
            f"Check the files are there on the user's machine (e.g. ls {prefix}/out) before reporting.\n\n"
            + _home_note(name))
    from mcp_types import ResourceLink

    uri = f"b123d-print://download/{_ws_name()}/{name}"
    out: list = [text, ResourceLink(uri=uri, name=f"{name}.zip", mime_type="application/zip",
                                    description=f"the whole part as a zip (unfiltered); download: {url}")]
    if embed:
        if total > EMBED_TOTAL:
            out[0] += f"\n(embed: not embedded, the part is over {EMBED_TOTAL // 1_000_000} MB; use the link)"
        else:
            out.append(_embedded_bytes(handoff.zip_bytes(files, prefix), uri, "application/zip"))
    return out


def _embedded_bytes(data: bytes, uri: str, mime: str):
    import base64

    from mcp_types import BlobResourceContents, EmbeddedResource

    return EmbeddedResource(resource=BlobResourceContents(uri=uri, mime_type=mime, blob=base64.b64encode(data).decode()))


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
@_files_doc
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
    if not res.get("image"):
        return [text]
    m = re.match(rf"^{re.escape(load_settings(_root()).parts_dir)}/([a-z][a-z0-9_]*)/", cand.relative_to(_root().resolve()).as_posix()
                 if cand.is_relative_to(_root().resolve()) else "")
    return _with_note(_with_image(text, res["image"], inline), m.group(1) if m else None)


# ---------------------------------------------------------------------------------------------
# Remixing (start from someone else's STL / 3MF / STEP)


def _ref_file(part: str, file: str) -> Path:
    """A reference file: a name in parts/<part>/ref/, or a workspace-relative path (refs/x.stl)."""
    from . import refs

    if not NAME_RE.match(part or ""):
        raise ToolError(f"bad part name {part!r}: lower_snake_case, starting with a letter")
    if "/" not in file and "\\" not in file:
        try:
            refs.check_name(file)
        except refs.RefError as e:
            raise ToolError(str(e)) from None
        p = refs.ref_dir(_root(), load_settings(_root()).parts_dir, part) / file
        if p.is_symlink() or not p.is_file():
            have = refs.listing(_root(), load_settings(_root()).parts_dir, part)
            raise ToolError(f"no reference file {file!r} for part {part!r}; it has {have or 'none'} "
                            "(upload_reference puts one there)")
        return p
    return _workspace_file(file)


@mcp.tool()
def upload_reference(part: str, filename: str, data_base64: str = "", overwrite: bool = False) -> str:
    """Get an original model (STL, 3MF or STEP) onto the server, into parts/<part>/ref/<filename>,
    to remix it (the part folder may not exist yet). With data_base64 (the whole file, base64) it
    is stored now, up to 50 MB; that is only practical for small files, since the model has to
    write out every byte. Without it, the result says how the USER copies the file: over HTTP a
    signed upload link for `curl -fT <file> '<link>'` (no token needed, expires), over SSH the
    `b123d-print push` command, locally the folder to copy it into. Then describe_model."""
    import base64
    import binascii

    from . import refs

    root, parts_dir = _root(), load_settings(_root()).parts_dir
    try:
        refs.check_name(filename)
        target = refs.ref_dir(root, parts_dir, part) / filename
    except refs.RefError as e:
        raise ToolError(str(e)) from None
    rel = target.relative_to(root).as_posix()
    if data_base64:
        if len(data_base64) > refs.MAX_BYTES * 4 // 3 + 8:
            raise ToolError(f"too large: reference files are limited to {refs.MAX_BYTES // 1_000_000} MB")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError):
            raise ToolError("data_base64 is not valid base64") from None
        try:
            refs.store(root, parts_dir, part, filename, data, overwrite)
        except refs.RefError as e:
            raise ToolError(str(e)) from None
        return f"Stored {rel} ({len(data):,} bytes). Next: describe_model('{part}', '{filename}')."
    if os.path.lexists(target) and not overwrite:
        return f"{rel} is already there. Next: describe_model('{part}', '{filename}') (overwrite=True to replace it)."
    if _http():
        url, expires = links.sign(STATE["link_secret"], _ws_name(), rel, STATE["link_ttl"],
                                  purpose="put-overwrite" if overwrite else "put")
        return (f"Ask the user to upload the file from their machine (no token needed; up to "
                f"{refs.MAX_BYTES // 1_000_000} MB; the link expires "
                f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))}):\n"
                f"  curl -fT <path/to/{filename}> '{_base_url()}{url}'\n"
                f"Then describe_model('{part}', '{filename}').")
    if STATE["ssh_dest"]:
        return (f"Ask the user to run this on their machine (the same SSH key as this MCP connection):\n"
                f"  b123d-print push <path/to/{filename}> --part {part} --to {STATE['ssh_dest']}"
                f"{' --overwrite' if overwrite else ''}\n"
                f"Then describe_model('{part}', '{filename}').")
    return (f"This server runs locally: copy the file to {target} (create the folder if needed; you may do it "
            f"yourself if you can write files). Then describe_model('{part}', '{filename}').")


@mcp.tool(structured_output=False)
async def describe_model(part: str, file: str, scale: str = "", image: bool = True, size: str = "normal",
                         inline: bool = True) -> list:
    """Inspect an original model before remixing it: format, units (and whether they look wrong),
    size, volume, triangles and faces before/after merging coplanar triangles, how much is curved
    (faceted), round holes (diameter, axis, center), repairs needed, the designer/license metadata
    the file carries, and a suggestion: MODIFY it or REDRAW it. part: the part it is for. file: a
    name in parts/<part>/ref/ (or a workspace path such as 'refs/x.stl'). scale: '' (as the file
    says), a factor, or the unit the file was drawn in ('inch', 'cm'). image: also a 6-view render
    (saved as parts/<part>/out/<file>_original.png)."""
    _image_options(size)
    path = _ref_file(part, file)
    sc: object = 1.0
    if scale:
        from .remix import UNITS

        try:
            sc = scale if scale in UNITS else float(scale)
        except ValueError:
            raise ToolError(f"scale: a number or one of {sorted(UNITS)}") from None
    out = _parts_dir() / part / "out"
    res = await _run({"op": "describe", "file": str(path), "scale": sc, "image": image, "size": size}, out)
    if not res.get("ok"):
        return [_error_text(res)]
    text = _scrub(json.dumps(res["summary"], indent=1, default=str))
    return _with_note(_with_image(text, res["image"], inline), part) if res.get("image") else [text]


@mcp.tool(structured_output=False)
async def before_after(name: str, variant: str | None = None, size: str = "normal", inline: bool = True) -> list:
    """For a remix: the original and the remix side by side, and the original colored by how far
    the remix is from it (compare's deviation view: green = unchanged, red = changed), with
    compare's score and metrics. The original is what build() loads with import_model, or what
    the script's original(d) returns. export writes the same two images when it writes PNGs."""
    _image_options(size)
    res = await _job(name, "before_after", variant=variant, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    a, b = res["files"]
    head = f"{name} [{res['variant']}]: {_show(a)}, {_show(b)}\n\n{res['text']}"
    first = _with_image(head, a, inline)
    return _with_note(first + _with_image("", b, inline)[1 if inline else 0:], name)


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


@mcp.resource("b123d-print://download/{workspace}/{part}", mime_type="application/zip")
def part_zip(workspace: str, part: str) -> bytes:
    """A whole part as a zip in the local layout (parts/<part>/<part>.py, out/, ref/), in this
    session's own workspace; download_part links to it."""
    from mcp.server.mcpserver.exceptions import ResourceError

    if workspace != _ws_name():
        raise ResourceError(f"workspace {workspace!r} is not this session's ({_ws_name()!r})")
    if not NAME_RE.match(part or ""):
        raise ResourceError(f"bad part name {part!r}")
    parts_dir = load_settings(_root()).parts_dir
    try:
        return handoff.zip_bytes(handoff.part_files(_root(), parts_dir, part), f"{parts_dir}/{part}")
    except handoff.HandoffError as e:
        raise ResourceError(str(e)) from None


def _rules() -> str:
    return data("AGENTS.md")


def _remote_step(name: str = "<name>") -> str:
    """The last step of remote work, the same in every prompt."""
    return (f"download_part('{name}') and bring the part home into my project folder, in the same layout "
            f"as a local install (parts/{name}/{name}.py, parts/{name}/out/, parts/{name}/ref/): over HTTP "
            f"`curl -fLo {name}.zip '<link>'` and unzip it in the project folder, over SSH the `b123d-print pull` "
            "command it gives. Check the files exist on my machine before reporting. Use only the MCP tools and "
            "their links: never ssh, scp or a shell on the server (there is none). The server copy is temporary.")


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
   anything missing or ambiguous: ask for my units, the datum I measured from and how accurate
   each value is; for a large or curved part propose a table of offsets (stations at a fixed
   spacing along a datum line), and ask for a scale reference in photos. If I have said
   nothing about how it should look, ask once for a style: functional (default), modern/minimal, least cost, rugged/outdoor,
   soft/handheld or structural/load-bearing (it goes in Dims as STYLE). Then STOP and wait for my confirmation. Do not
   model yet.
2. After I confirm: new_part, then write_part with every dimension as a named UPPER_CASE field
   of the Dims dataclass (mm, with a comment on its source and accuracy). Mating features get CLEARANCE (0.2 mm
   default per side, from config). Holes get HOLE_COMP (from config; horizontal ones a teardrop and
   HOLE_COMP_H). Model in print orientation, bed at Z=0.
3. Verify: build_part, render_preview, section through every pocket, boss, rib, hole and mating
   feature, and check. Add Wall checks wherever a cut goes deeper than the wall it starts in.
   Fix and repeat until check passes.
4. Remote server (HTTP or SSH) only, required: {_remote_step()}
5. Report: overall X x Y x Z, key feature sizes, validity, clearances (per side or total) and
   hole compensation applied, check results and warnings, print orientation, supports needed,
   and where the files are on my machine. If the part mates with something or has a hole
   pattern, offer a fit-test template first (a thin print cut from the part: make_template;
   confirm the face or region with me using list_faces' highlight or the template's _where
   picture). Then offer the design review for the part's style (design_metrics and the design
   rubric).

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
deeper than a wall). Remote server (HTTP or SSH) only, required: {_remote_step(name)}
Report what changed in numbers.

The full rules:

{_rules()}"""


@mcp.prompt()
def remix_part(name: str, source: str = "", change: str = "") -> str:
    """Remix someone else's model (STL, 3MF or STEP): inspect it, choose MODIFY or REDRAW, confirm
    the changes, then build, check (inherited vs new findings) and export."""
    return f"""I want to remix an existing model as the part '{name}'.
Source (file, URL, author, license): {source or '(I will tell you)'}
What to change: {change or '(I will tell you)'}

Work in these steps:
1. Get the file: if parts/{name}/ref/ has no model yet, call upload_reference('{name}', '<file name>')
   and give me what it says (a curl link, a `b123d-print push` command or a folder to copy into).
2. Inspect before anything else: describe_model('{name}', '<file>') (size, units, faces, curved
   share, holes, repairs, metadata, suggestion). If its units look wrong (a 3 mm "bracket"), ask me
   before scaling. Note the license: -ND forbids remixes (stop and tell me), -NC means no
   commercial use, BY means the author must be credited; ask me for the source URL, author and
   license if the file does not say.
3. Propose the path, with reasons: MODIFY (the default: load the original with import_model and
   change it; always for STEP and for organic or detailed meshes) or REDRAW (model it again
   parametrically; offer it for a simple prismatic mesh whose proportions change). List each
   intended change as a named UPPER_CASE dimension with its value and source, then STOP and wait
   for my confirmation.
4. new_part('{name}'), then write_part. Record the source URL, author and license in the docstring.
   MODIFY: `base = import_model("ref/<file>")` in build(d) (keep it in the file's position; if you
   must turn or move it, add `original(d)` returning the base placed the same way), then add and
   cut features with named Dims. Curves in a mesh stay faceted: to change a round hole, cut a real
   cylinder at its center. REDRAW: model it from Dims, define `original(d)` returning
   import_model("ref/<file>") placed like the redraw, and call before_after BEFORE changing any
   proportion: the unchanged redraw should match the original (report the score), then change it.
5. Verify: build_part, render_preview, section through what changed, check. Findings marked
   "inherited from the original" were already in the original: report them, do not "fix" them
   unless I ask. Fix every new FAIL. before_after shows the change and its score.
6. Remote server (HTTP or SSH) only, required: {_remote_step(name)}
7. Report as usual, plus: what changed in numbers, inherited vs new findings, the license and the
   attribution line to use when sharing it (e.g. "Remix of <title> by <author>, <license>, <URL>").

The full rules:

{_rules()}"""


@mcp.prompt()
def verify_part(name: str) -> str:
    """Review an existing part against the rules and report findings."""
    return f"""Review the part '{name}' before I print it. read_part, build_part, render_preview,
section through every pocket, boss, rib, hole and mating feature, and check. Look for: missing
Wall checks around cuts deeper than their wall, magic numbers outside Dims, missing clearance or
hole compensation, overhangs that need supports, bed edges with fillets. Report findings
most serious first; do not change the script unless I ask. When check passes, offer a fit-test
template (make_template) for its mating faces or hole pattern if it has any, and a design
review (the design_review prompt) for the part's style.

The full rules:

{_rules()}"""


@mcp.prompt()
def design_review(name: str, style: str = "") -> str:
    """Review a part that passes the print checks for its purpose and design style: metrics,
    renders, 3-7 concrete suggestions with rule IDs. Changes nothing without the user's OK."""
    pick = f"Use the style '{style}'." if style else (
        "Use the part's STYLE (design_metrics reports it and where it came from). If it came from the default "
        "and I never chose one, ask me once: functional (default), modern/minimal, least cost, rugged/outdoor, "
        "soft/handheld, structural/load-bearing, or one of my own styles (list_parts shows them).")
    return f"""Review the design of the part '{name}'. {pick}

1. check('{name}') first. If anything FAILs, stop and report the failures: the design review
   is for parts that print.
2. design_metrics('{name}'{f", style='{style}'" if style else ""}): the numbers and the findings
   the style's thresholds trigger.
3. render_preview, and section where a number points (a handle, a pocket, a water trap). If the
   script has no SHOW and it matters which sides are seen in use, ask me.
4. Judge the part with the general rubric below (notes) and the style's own rubric, which
   design_metrics prints at the end (suggestions; it comes from the style's file, so a user's
   own style brings its own). Every finding names its rule ID (DS-...) and its evidence: a metric or what the
   render shows.
5. Report briefly: the style; the 4-6 numbers that matter for it (filament and time are rough
   estimates: say so); 3-7 findings, most valuable first, each with the concrete change in
   numbers, its expected effect and its trade-off; one line on what is already good. Then ask
   which ones to apply. Do NOT change the part without my OK. You may build a trial variant to
   measure a suggestion, but leave the script as it was.
6. If I say yes: change Dims (a new variant if both should stay), then build_part,
   render_preview, sections, check, and design_metrics again to show before and after.
   Remote server (HTTP or SSH) only, required: {_remote_step(name)}

{data("design_review.md")}"""


@mcp.prompt()
def fit_test(name: str, what: str = "") -> str:
    """Make a fit-test template of a part: a quick thin print of a face, slice or region, to check
    size, hole pattern and mating fits before the full print."""
    return f"""I want to test the fit of the part '{name}' before printing all of it.
What to test: {what or '(suggest it: the faces that mate with something, the hole patterns)'}

1. build_part and render_preview; list_faces('{name}') for the flat faces and their holes.
2. Propose one or two templates, each with what it checks and how I use it: a face (a mounting
   face with its holes), a slice (plane and height, e.g. through the top of the standoffs) or a
   crop (a box around a clip or corner). Show me the face with list_faces(highlight=...), then
   STOP and wait for my OK.
3. make_template (kind, plane/at, face or center/size; thickness 1.2 mm unless the fit needs
   more). Look at the _where picture and the template's render; read its notes and findings
   (a template printed on its side checks positions, not hole sizes).
4. If it is a test I will want again for every variant, offer to add it to templates(d).
5. Remote server (HTTP or SSH) only, required: {_remote_step(name)}
6. Report: what each template checks, its size, how to use it, what
   to measure, and where the files are on my machine.

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
    if ws != links.ROOT_WS:
        handoff.touch(root)  # a download is a use too
    mime = links.content_type(path)
    return FileResponse(f, media_type=mime, filename=f.name,
                        content_disposition_type="inline" if mime == "image/png" else "attachment",
                        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@mcp.custom_route("/zip/{workspace}/{token}/{file}", methods=["GET"])
async def download_zip(request):
    """A signed zip link (download_part): needs no bearer token, serves a zip of one part (filtered
    as signed) until it expires. Built when fetched, so it holds the files as they are now."""
    import tempfile

    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse, StreamingResponse

    ws, token, file = (request.path_params[k] for k in ("workspace", "token", "file"))
    variant, formats = request.query_params.get("variant"), request.query_params.get("formats")
    part = file[:-4] if file.endswith(".zip") else ""
    try:
        if not NAME_RE.match(part):
            raise links.LinkError(404, "not found")
        links.verify_zip(STATE["link_secret"], ws, token, part, links.zip_query(variant, formats))
        root = _ws_dir(ws)
        if root is None:
            raise links.LinkError(404, "not found")
    except links.LinkError as e:
        return PlainTextResponse(str(e) + "\n", status_code=e.status)
    name = ws if ws != links.ROOT_WS else None
    _in_use(name, True)
    try:
        parts_dir = load_settings(root).parts_dir

        def build():
            files = handoff.part_files(root, parts_dir, part, variant, parse_formats(formats) if formats else None)
            tmp = tempfile.TemporaryFile()
            handoff.write_zip(files, f"{parts_dir}/{part}", tmp)
            size = tmp.tell()
            tmp.seek(0)
            return tmp, size

        try:
            tmp, size = await anyio.to_thread.run_sync(build)
        except (ValueError, SyntaxError, OSError):
            return PlainTextResponse("not found\n", status_code=404)
    finally:
        _in_use(name, False)

    def chunks():
        while chunk := tmp.read(1 << 20):
            yield chunk

    return StreamingResponse(chunks(), media_type="application/zip", background=BackgroundTask(tmp.close),
                             headers={"Content-Disposition": f'attachment; filename="{part}.zip"', "Content-Length": str(size),
                                      "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@mcp.custom_route("/upload/{workspace}/{token}/{path:path}", methods=["PUT"])
async def upload(request):
    """A signed upload link (upload_reference): needs no bearer token, stores one reference file in
    <parts_dir>/<part>/ref/ until it expires; capped at refs.MAX_BYTES."""
    from starlette.responses import PlainTextResponse

    from . import refs

    ws, token, path = (request.path_params[k] for k in ("workspace", "token", "path"))
    try:
        links.check_path(path)
        try:
            links.verify(STATE["link_secret"], ws, token, path, purpose="put-overwrite")
            overwrite = True
        except links.LinkError as e:
            if e.status == 410:
                raise
            links.verify(STATE["link_secret"], ws, token, path, purpose="put")
            overwrite = False
        root = _ws_dir(ws)
        if root is None:
            raise links.LinkError(404, "not found")
        parts_dir = load_settings(root).parts_dir
        part, filename = links.upload_target(parts_dir, path)
    except links.LinkError as e:
        return PlainTextResponse(str(e) + "\n", status_code=e.status)
    size = int(request.headers.get("content-length") or 0)
    if size > refs.MAX_BYTES:
        return PlainTextResponse(f"too large: the limit is {refs.MAX_BYTES // 1_000_000} MB\n", status_code=413)
    chunks, n = [], 0
    async for chunk in request.stream():
        n += len(chunk)
        if n > refs.MAX_BYTES:
            return PlainTextResponse(f"too large: the limit is {refs.MAX_BYTES // 1_000_000} MB\n", status_code=413)
        chunks.append(chunk)
    try:
        p = refs.store(root, parts_dir, part, filename, b"".join(chunks), overwrite)
    except refs.RefError as e:
        return PlainTextResponse(f"refused: {e}\n", status_code=409 if "already exists" in str(e) else 400)
    return PlainTextResponse(f"stored {p.relative_to(root).as_posix()} ({n} bytes)\n", status_code=201)


DRAIN_LIMIT = 8 * 1024 * 1024  # request body read and thrown away before an early reply; more -> close


class _BodyGuard:
    """Make every reply wait until the request body has been read (the app's own reads count).

    An app may answer without reading the body (a 401, a refused upload link, the SDK's 406).
    Behind a reverse proxy that starts a race: the proxy (Caddy, Go's net/http) gets the reply
    while it is still forwarding the body, its front end throws the rest of the client's body
    away, the forwarding fails short, and the proxy closes the upstream connection in the middle
    of the reply: the client sees "peer closed connection without sending complete message
    body", about every other time. So `start()` drains (reads and discards) what is left, up to
    DRAIN_LIMIT; past that, or when Content-Length says more is coming, it gives up and the
    reply goes out with `Connection: close`."""

    def __init__(self, scope, receive, limit: int = DRAIN_LIMIT):
        h = dict(scope["headers"])
        cl = h.get(b"content-length", b"").strip()
        self.left = int(cl) if cl.isdigit() else None  # bytes still to come, None if unknown (chunked)
        self.done = (self.left == 0) if cl else b"transfer-encoding" not in h
        self._receive, self.limit = receive, limit

    def _saw(self, msg) -> None:
        if msg["type"] == "http.disconnect" or not msg.get("more_body", False):
            self.done = True
        elif self.left is not None:
            self.left -= len(msg.get("body", b""))

    async def receive(self):
        msg = await self._receive()
        self._saw(msg)
        return msg

    async def drain(self) -> bool:
        """Read and discard the rest of the body; False when it is over the limit (then close)."""
        n = 0
        while not self.done:
            if self.left is not None and self.left > self.limit - n:
                return False
            msg = await self._receive()
            self._saw(msg)
            n += len(msg.get("body", b""))
            if n > self.limit and not self.done:
                return False
        return True

    async def start(self, msg) -> dict:
        """Called with http.response.start: drain first; the message, with Connection: close if needed."""
        if not self.done and not await self.drain():
            msg = {**msg, "headers": [*msg.get("headers", []), (b"connection", b"close")]}
        return msg


async def _deny(send, status: int, error: str, description: str) -> None:
    body = json.dumps({"error": error, "error_description": description}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer error="invalid_token"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _log(scope, who: str, status: int, workspace: str | None = None) -> None:
    path = scope["path"]
    if path.startswith(("/files/", "/upload/", "/zip/")):  # never log the signature: a log line must not be a working link
        parts = path.split("/", 4)
        path = f"/{parts[1]}/{parts[2] if len(parts) > 2 else '?'}/.../{parts[4] if len(parts) > 4 else ''}"
    client = (scope.get("client") or ("-",))[0]
    ws = f" ws={workspace}" if workspace is not None else ""
    print(f"b123d-print-mcp: {client} {who} {scope['method']} {path}{ws} -> {status}", file=sys.stderr, flush=True)


class TokenAuth:
    """ASGI wrapper: every HTTP request except /health and the signed /files/, /zip/ and /upload/ links (which carry
    their own HMAC, see download) needs `Authorization: Bearer <token>` of a known named token, and
    may use only that token's workspaces (403 otherwise). A request without ?workspace= gets the
    token's single workspace if it has exactly one, else the shared root workspace. Every request
    is logged with the token's name. No reply starts before the request body is in (_BodyGuard).

    (The SDK's own bearer auth is the OAuth resource-server path: it wants an issuer URL and a
    token verifier fixed when MCPServer is built, and advertises OAuth metadata that would send
    clients looking for an authorization server that does not exist.)"""

    def __init__(self, app, store: tokens.Store | None):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = {"code": 0}
        guard = _BodyGuard(scope, receive)
        receive, send_raw = guard.receive, send

        async def send(msg):  # every reply, ours and the app's, waits for the request body: see _BodyGuard
            if msg["type"] == "http.response.start":
                msg = await guard.start(msg)
            await send_raw(msg)

        async def send_logged(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        path = scope["path"]
        if path == "/health":
            return await self.app(scope, receive, send)
        if path.startswith(("/files/", "/upload/", "/zip/")):
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
                    help="seconds per build, render, section or export (default 120; $B123D_PRINT_TIMEOUT)")
    ap.add_argument("--check-timeout", type=float, default=float(env("B123D_PRINT_CHECK_TIMEOUT", 0)) or None,
                    help="seconds per check run, which builds the part and runs every check (on a remix, on the original "
                         "too); near the limit it stops and returns the findings it has (default: 300, or --timeout if "
                         "longer; $B123D_PRINT_CHECK_TIMEOUT)")
    ap.add_argument("--max-builds", type=int, default=int(env("B123D_PRINT_MAX_BUILDS", 0)) or max(1, (os.cpu_count() or 2) // 2),
                    help="build processes at once, across all clients and all server processes of this user (one per SSH session); "
                         "more calls wait (default: half the CPUs; $B123D_PRINT_MAX_BUILDS)")
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
    ap.add_argument("--retention-days", type=float, default=float(env("B123D_PRINT_RETENTION_DAYS", 30)),
                    help="http: remove a named workspace (workspaces/<name>) nobody has used for this many days; checked "
                         "at startup and hourly, never while it is in use; 0 = never (default 30; $B123D_PRINT_RETENTION_DAYS)")
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
                     help="workspace name or pattern it may use, e.g. 'grok-*' or '*' for all (repeatable; "
                          "default: one workspace named like the token)")
    add.add_argument("--url", help="the server's address for the printed client config, e.g. https://cad.example.com "
                                   "(default: $B123D_PRINT_PUBLIC_URL)")
    tsub.add_parser("list", help="the tokens, their workspaces and when they were made (never the tokens)")
    rv = tsub.add_parser("revoke", help="delete a token; the server stops accepting it at once")
    rv.add_argument("name")
    wk = sub.add_parser("worker", help="run builds handed over through --queue (pairs with the server's --job-queue)")
    wk.add_argument("--queue", required=True, help="the folder shared with the server")
    wk.add_argument("--check", action="store_true", help="exit 0 if a worker's heartbeat is fresh (Docker health check)")
    return ap


def main(argv: list[str] | None = None) -> None:
    safe_console()
    env = os.environ.get
    args = build_parser().parse_args(argv)
    # also the limit across server processes (one per SSH session); set before any early exit
    sandbox.MAX_BUILDS = max(1, args.max_builds)
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
    STATE.update(root=root, timeout=args.timeout, check_timeout=args.check_timeout or max(300.0, args.timeout),
                 transport=args.transport, max_builds=max(1, args.max_builds))
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
    if args.retention_days < 0:
        sys.exit("b123d-print-mcp: --retention-days must be 0 (never) or more")
    retention = handoff.Retention(root, args.retention_days)
    STATE.update(tokens=store, queue=queue, retention_days=args.retention_days, retention=retention,
                 link_secret=links.derive_secret(token, secret), link_ttl=max(1.0, args.link_ttl),
                 public_url=(args.public_url or "").rstrip("/") or None,
                 allowed_hosts=[h.strip() for h in (args.allowed_hosts or "").split(",") if h.strip()])
    if STATE["public_url"] and not re.match(r"^https?://[^/\s]+(/\S*)?$", STATE["public_url"]):
        sys.exit(f"b123d-print-mcp: --public-url must look like https://host[:port][/prefix], got {args.public_url!r}")
    import uvicorn

    auth = f"tokens {', '.join(store.names())}" if store else "NONE"
    print(f"b123d-print-mcp: http://{args.host}:{args.port}/mcp  workspace {root}  auth {auth}  "
          f"max builds {STATE['max_builds']}  builds {'in worker via ' + str(queue) if queue else 'here'}  "
          f"retention {f'{args.retention_days:g} days' if args.retention_days > 0 else 'off'}", file=sys.stderr)
    retention.start()
    if store and hasattr(signal, "SIGHUP"):  # SIGHUP (not on Windows): re-read the tokens file now (it is also re-read whenever it changes)
        signal.signal(signal.SIGHUP, lambda *_: store.request_reload())
    # uvicorn handles SIGTERM/SIGINT: stop accepting, let running calls finish for up to
    # --shutdown-grace seconds, then cancel them; any build still running is killed here
    # uvicorn re-raises the signal after its shutdown; make SIGTERM a normal exit so the cleanup runs
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGBREAK"):  # Windows has no SIGTERM to send: Ctrl+Break is the graceful stop
        signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))
    try:
        # access_log off: TokenAuth logs every request with the token's name instead
        uvicorn.run(http_app(args.host, store, args.allowed_hosts), host=args.host, port=args.port,
                    log_level="info", access_log=False, timeout_graceful_shutdown=args.shutdown_grace)
    finally:
        retention.stop()
        n = sandbox.kill_all()
        if queue:
            jobqueue.cancel_all(queue)
        print(f"b123d-print-mcp: stopped{f' ({n} running build(s) killed)' if n else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
