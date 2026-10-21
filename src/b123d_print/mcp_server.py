"""b123d-print MCP server: design, check and export 3D-printable build123d parts from any MCP
client. Part scripts are model-written code: every build runs in a sandboxed subprocess.

    b123d-print-mcp --workspace ~/parts            # stdio; or B123D_PRINT_WORKSPACE=~/parts; default: the cwd
    B123D_PRINT_TOKEN=... b123d-print-mcp --transport http --port 8000   # Streamable HTTP at /mcp

Over HTTP every request needs `Authorization: Bearer <token>`, and each client picks its own
workspace with `/mcp?workspace=<name>` (or the header `X-B123D-Workspace`), which is the folder
<workspace>/workspaces/<name>; without one, clients share <workspace> itself. Files the server
writes come back as signed download links (GET /files/..., no token, they expire) and as
b123d-print://files/ resources; download_part gives one signed link (GET /zip/...) to a zip of a
whole part, and export a signed 3D view link (GET /view/..., viewer.py). A named workspace nobody uses for --retention-days (default 30) is removed.
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

from . import handoff, jobqueue, links, outdir, sandbox, tokens, viewer
from .cli import NAME_RE, data, examples, init_workspace, new_part as _new_part
from .config import WORKSPACE_FILE, formats_configured, hole_comp_source, load_settings, parse_formats, safe_console, user_config_path
from .partfiles import find_parts, timing_lines

MAX_SCRIPT_BYTES = 256_000

# The first 512 characters stand on their own: some clients (Codex) keep no more than that.
INSTRUCTIONS = """\
Design 3D-printable parts as build123d scripts. Before the first part, call read_guide (the full
rules). Before modeling, list every dimension with its source and the ones missing, ask the user
and WAIT for confirmation: never model on guesses. Dimensions: named UPPER_CASE Dims fields, mm;
print orientation, bed at Z=0. Verify with render_preview, section and check before reporting. On
a remote server a part is done only when download_part has brought its files to the user.
Workflow: new_part -> write_part (whole script) -> build_part -> render_preview + section ->
check -> fix and repeat -> (offer a fit-test template: list_faces, make_template) -> export (it returns a
3D view of the part: give the user that link or file so they can turn it in a browser). To remix an existing STL/3MF/STEP: upload_reference ->
describe_model -> import_model in the script (prompt remix_part). The rules (read_guide, the
resource b123d-print://guide, or the prompt design_part_from_photos) also cover 0.2 mm mating
clearance, HOLE_COMP from the user's config, holes, overhangs and strength. render_preview and
section return PNG images.
A failed result carries a DIAGNOSIS (cause, where, fixes): read it before changing the script;
diagnose_failure looks deeper. Change a dimension with set_params (params lists them), not a
rewrite. Check fits and walls with measure, not by eye.
Fillets and chamfers: list_edges (highlight=ids) gives a verified selector for the edges you mean.
Several pieces: return lazy pieces from build(d) ({"name": lambda: piece(d)}) and pass parts= to
build_part, render_preview, section and export to work on one; built pieces are cached, so later
calls reuse them (fresh=True rebuilds). build_part reports each piece's time and faces.
Pieces with an assembly(d): check_fit (overlaps, gaps, hole alignment). A flat outline from a scan
or grid photo: upload_reference, then trace_outline. Common features (teardrop holes, nut traps,
snap arms, hinges, lids, text, bed chamfers): read the recipe tool before improvising one.
When this server is remote (HTTP or SSH), it is a workbench, not storage: what it writes is a
temporary working copy, deleted after some days unused. Use ONLY these MCP tools and the links they
return; the server gives no shell, ssh or scp access. Last step, before reporting: download_part
(name) and bring the part home into the project folder in the same layout as a local install
(parts/<name>/<name>.py, parts/<name>/out/, parts/<name>/ref/): over HTTP `curl -fLo <name>.zip
'<link>'` and unzip it in the project folder; over SSH the `b123d-print pull` command it gives.
Then check the files are there on the user's machine. If your shell has no network or is
sandboxed (Antigravity/agy, web and mobile clients), call download_part(name, embed=True): the zip
comes inside the result; unzip it from where your client saved it (unzip -o <zip> -d <project folder>).
A part is not done until its files are on the user's machine: after export, call download_part
(embed=True if your shell has no network) and unzip into the project folder, unless the user says to
leave them on the server. Locally (stdio) the files are already in the project folder."""

# The rules a model skips most, in every first result (list_parts, new_part, a part's first
# write_part) and read_guide(essentials=True): tool results reach the model in every client,
# resources and server instructions do not.
ESSENTIALS = """\
Rules (all of them: read_guide):
1. Before modeling, list every dimension with its source (typed / photo / estimate) and the ones missing; ask the user and WAIT for confirmation. For a hole, say whether its size is the printed hole or what goes in it (then + clearance per side); holes are drawn true to size, plus hole_comp only if the user opted in.
2. Every dimension is a named UPPER_CASE field of the Dims dataclass, in mm; build(d) in print orientation, bottom face on Z=0.
3. Before reporting: build_part, render_preview, section through holes and pockets, and check; fix every FAIL. Report holes with their cut size: "hole for a 4 mm dowel (cut 4.30: clearance 0.15 per side)".
4. export; on a remote server bring the files home: download_part(name) (embed=True if your shell has no network)."""

REMOTE_DOC = """
    Remote server (HTTP/SSH): the files stay on the server, as a temporary working copy deleted
    when unused; bring the part home with download_part (one zip in the parts/<name>/ layout).
    Never use ssh, scp or a shell on the server: there is none."""

WORKSPACE_RE = handoff.WORKSPACE_RE
_WORKSPACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("b123d_print_workspace", default=None)
_REQUEST: contextvars.ContextVar = contextvars.ContextVar("b123d_print_request", default=None)


def _requested_workspace(scope) -> str | None:
    """The workspace an HTTP request names: ?workspace=<name> or the X-B123D-Workspace header, None
    for none (the shared root workspace). Refuses (ValueError) a request that names it more than
    once, or differently in the query and the header, so every layer reads the same one."""
    from urllib.parse import parse_qs

    values = parse_qs(scope.get("query_string", b"").decode(errors="replace"), keep_blank_values=True).get("workspace", [])
    headers = [v.decode(errors="replace") for k, v in scope.get("headers", []) if k.lower() == b"x-b123d-workspace"]
    if len(values) > 1 or len(headers) > 1:
        raise ValueError("the workspace is given more than once")
    q, h = (values[0] if values else ""), (headers[0] if headers else "")
    if q and h and q != h:
        raise ValueError("?workspace= and the X-B123D-Workspace header name different workspaces")
    return q or h or None


async def _request_workspace(ctx, call_next):
    """HTTP: the workspace this request asked for (?workspace=<name> or X-B123D-Workspace). The
    request counts as a use of that workspace: retention never removes it meanwhile (see handoff.py)."""
    req = getattr(ctx, "request", None)
    name = None
    if req is not None and hasattr(req, "query_params"):
        state = req.scope.get("state", {})
        if "b123d_workspace" in state:  # TokenAuth resolved and authorized it: use exactly that, nothing else
            name = state["b123d_workspace"]
        else:  # no TokenAuth in front (--insecure-no-auth): read the request the same way it does
            try:
                name = _requested_workspace(req.scope)
            except ValueError as e:
                raise ToolError(str(e)) from None
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
STATE: dict = {"root": Path.cwd(), "timeout": sandbox.DEFAULT_TIMEOUT, "check_timeout": 300.0, "transport": "stdio", "max_builds": 2, "limiter": None,
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
    res = await _run({"op": op, "script": str(script), **{k: v for k, v in kw.items() if v is not None}}, script.parent / "out")
    if not res.get("ok") and not res.get("usage_error"):  # a timeout or a dead worker: no diagnosis from the worker
        from .diagnose import from_result

        res["diagnosis"], res["part_name"] = from_result(res, script), name
    return res


def _error_text(res: dict) -> str:
    from .diagnose import PROGRESS, text

    s = f"ERROR: {res.get('error')}"
    if res.get("usage_error"):  # a wrong argument (piece, variant, face, measurement): the message says it all
        return _scrub(s)
    if res.get("diagnosis"):
        s += "\n\n" + text(res["diagnosis"], res.get("part_name"))
    if res.get("traceback"):
        s += f"\n\n{res['traceback']}"
    log = "\n".join(line for line in (res.get("log") or "").splitlines() if not line.startswith(PROGRESS))
    if log:
        s += f"\n\nOutput:\n{log}"
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


def _next_step(name: str) -> str:
    """Remote: the closing NEXT STEP of a result that wrote files the user needs (empty over stdio):
    bring the part home with download_part, embedded in the result when the client's shell can't fetch."""
    if not _remote():
        return ""
    try:
        size = sum(p.stat().st_size for _, p in _part_files(name, None, None))
    except (ToolError, OSError):
        size = None
    how = ("it gives the `b123d-print pull` command; run it in the project folder" if not _http() else
           f"run the curl command it gives, then unzip -o {name}.zip in the project folder")
    if size is None or size <= EMBED_TOTAL:
        embed = (f"If your shell has no network or runs sandboxed (Antigravity/agy, a web or mobile client), call "
                 f"download_part('{name}', embed=True) instead: the zip"
                 + (f" ({_human_size(size)}, under the {EMBED_TOTAL // 1_000_000} MB embed limit)" if size else "")
                 + " comes inside the result; unzip it into the project folder from where your client saved it.")
    else:
        embed = (f"The part is {_human_size(size)}, over the {EMBED_TOTAL // 1_000_000} MB embed limit: if your shell "
                 f"has no network, narrow it to fit, e.g. download_part('{name}', formats='3mf', embed=True).")
    return (f"NEXT STEP: a part is not done until its files are on the user's machine. Call "
            f"download_part('{name}') ({how}). {embed} Skip this only if the user said to leave the files on the server.")


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
    from .config import IMAGE_SIZES

    if size not in IMAGE_SIZES:
        raise ToolError(f"size must be one of {list(IMAGE_SIZES)}")


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
def read_guide(essentials: bool = False) -> str:
    """The workflow and print rules (the b123d-print://guide resource). Call it once before the
    first part in a session: many clients never load that resource. essentials=True: only the
    short checklist of the rules most often skipped."""
    return ESSENTIALS if essentials else data("AGENTS.md")


@mcp.tool()
def list_parts() -> str:
    """List the part scripts in the workspace, with the settings in effect."""
    s = load_settings(_root())
    parts = [p.parent.name for p in find_parts(_root(), s.parts_dir)]
    return json.dumps(
        {
            "rules": ESSENTIALS.splitlines(),
            "version": _pkg_version(),
            **({"workspace": _ws_name(), "files": "on the server: a temporary working copy; download_part(<name>) "
                                                    "brings a part home"} if _remote() else {"workspace": str(_root())}),
            "parts_dir": s.parts_dir,
            "parts": parts,
            "out": f"{s.parts_dir}/<name>/out/: print/ (3MF, STL, print sheet: for the slicer; templates in "
                   "print/templates/), cad/ (STEP, GLB), images/, docs/ (BOM, view HTML), README.md",
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
        return {"mode": "generic", "note": "no printer profile: no build-volume check, generic limits. Offer the user "
                                           "setup (the setup_workspace prompt: printer, material, formats, style, calibration)"}
    from .profiles import calibrated

    out = {"mode": "printer", **({"nickname": s.nickname} if s.nickname else {}), **load_printer(s.printer).as_dict()}
    if s.material:
        out["material"] = load_material(s.material).as_dict()
    out["calibration"] = {"for": f"{s.calibration_key}/{s.material or 'any'}",
                          "measured": calibrated(s.calibration_key, s.material, s.root)}
    return out


@mcp.tool()
def use_printer(name: str = "", material: str = "", search: str = "", nickname: str = "") -> str:
    """Optional printer profile (default is generic mode). search: find printer names
    ("bambu a1", "prusa mk4"). name: make it active (saved in the user's config, or over HTTP and
    SSH in this workspace's b123d-print.toml; "generic" clears it); a nickname given before works
    too. nickname: only for two printers of the same model, e.g. name='bambu_lab_p2s_0_4_nozzle',
    nickname='p2s-garage': each nickname keeps its own calibration. material: pla, petg, asa, abs,
    tpu or the user's own. Only change the printer when the user asks for it."""
    from .config import printer_nicknames, set_user_setting as _set
    from .profiles import load_material, load_printer, save_nickname, search as find

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
        if nickname:
            save_nickname(nickname, name or load_settings(_root()).printer, path)
            name = nickname
        if name:
            load_printer(printer_nicknames(_root()).get(name, name))
            set_user_setting("printer", name)
        if material:
            load_material(material)
            set_user_setting("material", material)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e).strip('"')) from None
    return json.dumps(_printer_summary(load_settings(_root())), indent=1)


@mcp.tool()
def save_setup(printer: str = "", material: str = "", formats: str = "", style: str = "", hole_comp: float | None = None,
               hole_comp_h: float | None = None, calibration: dict[str, float] | None = None, overwrite: bool = False,
               move_flat: bool = False) -> str:
    """Save the user's first-run answers (the setup_workspace prompt): printer (a name from
    use_printer's search, or a nickname), material, formats ("3mf,png"), default style;
    hole_comp=0 records that the slicer corrects holes (the default way); a nonzero, MEASURED
    hole_comp / hole_comp_h is an opt-in that builds the correction into every file;
    calibration: other coupon results, e.g. {"clearance": 0.18, "max_bridge": 15}. With a printer, measured values are stored for it and the material. Written
    where use_printer writes. A value already set there is kept and listed as a conflict: ask the
    user, then call again with overwrite=True. Empty arguments change nothing. move_flat=True
    (after asking the user) moves measured values set for every printer of a workspace under the
    active printer."""
    from . import setup as st

    path = user_config_path()
    if STATE["transport"] == "http" or STATE["ssh_dest"]:  # shared server: this workspace only
        init_workspace(_root())
        path = _root() / WORKSPACE_FILE
    answers = {"printer": printer, "material": material, "formats": formats, "style": style,
               "hole_comp": hole_comp, "hole_comp_h": hole_comp_h, **(calibration or {})}
    try:
        changes = st.plan(answers, path, overwrite)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e).strip('"')) from None
    written = st.apply(changes, overwrite)
    conflicts = [c for c in changes if c.conflict and c not in written]
    s = load_settings(_root())
    moved = st.move_flat(path, s.calibration_key) if move_flat and s.printer and path != user_config_path() else {}
    flat = st.flat_calibration(path) if s.printer and path != user_config_path() else {}
    s = load_settings(_root()) if moved else s
    nexts = [*(["these are already set: ask the user, then save_setup(..., overwrite=True) to replace them"] if conflicts else []),
             *([f"{', '.join(sorted(flat))} are set for every printer in this workspace, so they override what is "
                f"measured for {s.calibration_key} and stay when the printer changes: ask the user, then "
                "save_setup(move_flat=True) moves them under this printer"] if flat else [])]
    return json.dumps({
        "written": [{"key": c.key, "value": c.new, "was": c.old, "file": _scrub(str(c.where)),
                     **({"for": c.scope} if c.scope else {})} for c in written],
        "unchanged": [c.key for c in changes if c.same],
        "conflicts": [{"key": c.key, "now": c.old, "answer": c.new} for c in conflicts],
        **({"moved": {"values": moved, "to": f"{s.calibration_key}/any"}} if moved else {}),
        **({"next": " ".join(nexts)} if nexts else {}),
        "printer": _printer_summary(s),
        "settings": {"formats": list(s.formats), "style": s.style or "functional", "hole_comp": s.hole_comp,
                     "hole_comp_h": s.hole_comp_h, "clearance": s.clearance},
        "slicer": st.hole_note(s),
        "calibration": st.next_steps(hole_comp_source(_root()) is not None),
    }, indent=1)


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
    the new file's code here. Usually the next step is write_part with the whole script.
    If you haven't, call read_guide first; confirm the dimensions with the user before writing the script."""
    if not (_root() / "b123d-print.toml").exists():
        init_workspace(_root())
    try:
        p = _new_part(_root(), load_settings(_root()).parts_dir, name, description, example)
    except (ValueError, FileExistsError) as e:
        raise ToolError(str(e)) from None
    rel = p.relative_to(_root()).as_posix()
    _reminded(name)
    if show_code:
        return f"Created {rel}. Edit it with write_part.\n\n{ESSENTIALS}\n\nCurrent code:\n\n{p.read_bytes().decode('utf-8')}"
    src = f"the bundled example {example!r}" if example else "the template (resource b123d-print://template)"
    return (f"Created {rel} from {src}. Next: write_part('{name}', <whole script>); read_part('{name}') "
            "shows the current code. A single part returned by build() is named 'part' in checks "
            f"(or '{name}'); return {{'name': part}} to name several.\n\n{ESSENTIALS}")


def _reminded(name: str) -> bool:
    """True the first time this server process sees the part `name` in this workspace (new_part
    or its first write_part): its result then carries ESSENTIALS. Later calls stay short."""
    seen = STATE.setdefault("reminded", set())
    key = (_ws_name(), name)
    if key in seen:
        return False
    seen.add(key)
    return True


@mcp.tool()
def read_part(name: str) -> str:
    """Return the current code of a part script."""
    return _script(name).read_bytes().decode("utf-8")  # exactly as stored: what download_part / pull bring home


@mcp.tool()
def write_part(name: str, code: str) -> str:
    """Replace the whole part script with `code` (create the part with new_part first).
    The script must define build(d) (+ Dims, VARIANTS). If you haven't, call read_guide first;
    confirm the dimensions with the user before writing the script. Then call build_part."""
    p = _script(name)
    err = _save_script(p, code)
    if err:
        return f"NOT SAVED: {err}"
    first = not (p.parent / "out").exists() and _reminded(name)  # the part's first save, never built
    return (f"Saved {p.relative_to(_root()).as_posix()} ({len(code.splitlines())} lines). Next: build_part('{name}')."
            + (f"\n\n{ESSENTIALS}" if first else ""))


def _save_script(p: Path, code: str) -> str | None:
    """Write a part script the way write_part does (size limit, must compile, bytes exactly as
    given); the reason it was not saved, or None."""
    if len(code.encode()) > MAX_SCRIPT_BYTES:
        raise ToolError(f"script too large (> {MAX_SCRIPT_BYTES} bytes)")
    try:
        compile(code, str(p), "exec")
    except SyntaxError as e:
        return f"syntax error at line {e.lineno}: {e.msg}\n{e.text or ''}"
    p.write_text(code, encoding="utf-8", newline="")  # exactly as sent, on every OS (no CRLF on Windows)
    return None


@mcp.tool()
def params(name: str) -> str:
    """The part's named dimensions, read from the script without running it: each Dims field
    with its type, default as written, value (when the default is a literal), the comment saying
    where it came from, and its line; the derived values (@property) and the fields they use;
    and each variant's overrides in VARIANTS. Change one with set_params, not a whole rewrite."""
    from .params import ParamError, read

    p = _script(name)
    try:
        info = read(p.read_bytes().decode("utf-8"))
    except ParamError as e:
        raise ToolError(str(e)) from None
    return json.dumps({"file": p.relative_to(_root()).as_posix(), **info}, indent=1, ensure_ascii=False)


@mcp.tool()
async def set_params(name: str, values: dict[str, float | int | str | bool | list[float | int | str | bool]],
                     variant: str | None = None, rebuild: bool = True, parts: str | None = None) -> str:
    """Change Dims values in the script in place, leaving every other character of the file as
    it was: values {"FIELD": new value, ...} replaces each field's default (only literal defaults:
    a default computed by an expression such as hole_comp(__file__) is refused with the reason;
    so are unknown fields, derived @property values and values of the wrong type). variant: change
    (or add) that variant's override in VARIANTS instead of the default. rebuild (default true):
    build before and after (the build cache makes "before" quick) and report what changed per
    piece: size and volume; parts: only those pieces. Saved like write_part (size limit, must
    compile). If the new build fails, the result has the diagnosis and the call to undo it."""
    import ast

    from .params import ParamError, read, set_values

    p = _script(name)
    src = p.read_bytes().decode("utf-8")
    try:
        new, changes, notes = set_values(src, values, variant)
        keys = list(read(src).get("variants", {}))
    except ParamError as e:
        raise ToolError(str(e)) from None
    build_v = variant or (keys[0] if keys else None)
    before = await _job(name, "build", variant=build_v, parts=parts) if rebuild else None
    err = _save_script(p, new)
    if err:
        raise ToolError(f"not saved: {err}")
    rel = p.relative_to(_root()).as_posix()
    lines = [f"Changed {rel}:"]
    for c in changes:
        where = f"VARIANTS[{c['variant']!r}]" if c.get("variant") else "Dims"
        lines.append(f"  {c['field']} ({where}, line {c['line']}): {c['old'] if c['old'] is not None else '(not set)'} -> {c['new']}")
    lines += [f"  note: {n}" for n in notes]
    undo = {c["field"]: ast.literal_eval(c["old"]) for c in changes if c["old"] is not None}
    undo_call = f"set_params('{name}', {json.dumps(undo)}" + (f", variant={variant!r})" if variant else ")")
    if not rebuild:
        lines.append(f"Not rebuilt (rebuild=false). Next: build_part('{name}').")
        return "\n".join(lines)
    after = await _job(name, "build", variant=build_v, parts=parts)
    if not after.get("ok"):
        lines.append(f"\nThe change is saved, but the build now FAILS. Undo: {undo_call}\n")
        return "\n".join(lines) + _error_text(after)
    for v, res in after["variants"].items():
        old = ((before or {}).get("variants") or {}).get(v, {}).get("parts", {}) if (before or {}).get("ok") else {}
        lines.append(f"Rebuilt [{v}]:")
        for pname, r in res["parts"].items():
            o = old.get(pname)
            size = f"{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm"
            if o:
                size = f"{o['x']:.2f} x {o['y']:.2f} x {o['z']:.2f} -> {size}"
                dv = r["volume"] - o["volume"]
                vol = f"volume {o['volume']:.1f} -> {r['volume']:.1f} mm^3 ({dv:+.1f}" + (
                    f", {100 * dv / o['volume']:+.1f} %)" if o["volume"] else ")")
            else:
                vol = f"volume {r['volume']:.1f} mm^3" + ("" if before is None else " (new: no build before to compare)"
                                                         if before.get("ok") else " (the build failed before this change)")
            lines.append(f"  {pname}: {size}; {vol}; valid={r['valid']}")
        for pname, probs in res.get("problems", {}).items():
            lines += [f"  PROBLEM {pname}: {pr['cause']}; try: {pr['fixes'][0]}" for pr in probs]
    lines.append(f"Undo: {undo_call}")
    return _scrub("\n".join(lines))


@mcp.tool()
async def build_part(name: str, variant: str | None = None, parts: str | None = None, fresh: bool = False) -> str:
    """Run the part script (sandboxed, with a timeout) and report, per variant and part: bounding
    box size and min/max (mm), volume (mm^3), solid count, is_valid, the Dims values, and any
    error with its traceback; and under "timing" each piece's face count and build time, with a
    hint for a piece that is slow or dense. variant: key from VARIANTS ('standard' = '').
    parts: comma-separated piece names from build(): build only those (lazy pieces: the others
    are never built). Built pieces are cached in out/.cache/, so render_preview, section, check
    and export reuse them while the script, its Dims and the settings stay the same; fresh=True
    builds again and replaces the cached pieces. Writes no other files."""
    res = await _job(name, "build", variant=variant, parts=parts, fresh=fresh or None)
    if not res.get("ok"):
        return _error_text(res)
    res.pop("ok", None)
    return json.dumps(res, indent=1, default=str)


@mcp.tool()
async def diagnose_failure(name: str, variant: str | None = None, parts: str | None = None) -> str:
    """The deeper look after a failed or broken build (failed results already carry a short
    DIAGNOSIS): builds one variant piece by piece, each on its own and without the build cache,
    and for each piece reports the error with its likely cause and specific fixes (where in the
    script, the piece, the numbers: e.g. the largest fillet radius that works on those edges),
    or for a piece that built, what makes it unprintable (invalid solid, zero volume, a 2D shape,
    not on the bed) and, for an invalid one, which faces and edges are bad, tiny edges and sliver
    faces left by booleans, and whether part.fix() repairs it. Then the assembly. parts: only
    those pieces. Stops before the time limit and names the pieces it did not get to."""
    from .diagnose import deep_text

    res = await _job(name, "diagnose", variant=variant, parts=parts)
    if not res.get("ok"):
        return _error_text(res)
    return _scrub(deep_text(res, name))


@mcp.tool(structured_output=False)
@_files_doc
async def render_preview(name: str, variant: str | None = None, parts: str | None = None,
                         size: str = "normal", inline: bool = True, fresh: bool = False) -> list:
    """Render six views (iso, top, front, right, iso from below, bottom) as a PNG image.
    parts: comma-separated part names from build() (several are laid out side by side; only those
    are built), 'assembly' (assembled position with stand-ins), or omit: the assembly if the
    script has one, else every printable part side by side. One variant (default: the first).
    size: 'normal' or 'small' (~800 px wide, cheaper). inline=False returns only the file (over
    HTTP: its download link), not the image itself. Uses the pieces cached by an earlier build;
    fresh=True builds them again."""
    _image_options(size)
    res = await _job(name, "render", variant=variant, parts=parts, size=size, fresh=fresh or None)
    if not res.get("ok"):
        return [_error_text(res)]
    summary = {"variant": res["variant"], "layout": res["layout"], "drawn": res["drawn"], "parts": res["parts"],
               "timing": res["timing"], "file": _show(res["image"])}
    return _with_note(_with_image(json.dumps(summary, indent=1), res["image"], inline), name)


@mcp.tool(structured_output=False)
@_files_doc
async def section(name: str, plane: str, at: float, variant: str | None = None, parts: str | None = None,
                  size: str = "normal", inline: bool = True, fresh: bool = False) -> list:
    """Cross-section as a PNG image, each part in its own color. plane: 'XY' (at = Z height),
    'XZ' (at = Y) or 'YZ' (at = X), in mm. parts: default the assembly if the script has one
    (shows fit and clearances), else all printable parts; or comma-separated names (only those
    are built). size: 'normal' or 'small' (~800 px wide). inline=False returns only the file (over
    HTTP: its download link), not the image itself. Uses the pieces cached by an earlier build;
    fresh=True builds them again."""
    if plane.upper() not in ("XY", "XZ", "YZ"):
        return ["plane must be XY, XZ or YZ"]
    _image_options(size)
    res = await _job(name, "section", variant=variant, parts=parts, plane=plane, at=at, size=size, fresh=fresh or None)
    if not res.get("ok"):
        return [_error_text(res)]
    hints = "".join(f"\nhint: {h}" for h in res["timing"]["hints"])
    return _with_note(_with_image(f"{res['plane']} section at {res['at']:g} mm ({res['variant']}): {_show(res['image'])}{hints}",
                                  res["image"], inline), name)


async def _check(name: str, variant: str | None, fresh: bool = False) -> dict:
    """Run a check over up to --max-builds workers at once: each builds the part (import_model's
    conversion is cached and shared) and runs its share of the check items (project.partition);
    the findings are merged back in order. Each worker takes a build slot like any build, so on
    a busy server the shares simply take turns; with one slot it is one worker, as before.
    All shares stop at the same soft deadline, so a check that runs out of time still returns
    every finding that finished. fresh: build again instead of reading the build cache (every
    share then rebuilds; they write the same cache entries)."""
    count = max(1, STATE["max_builds"])
    extra = {"fresh": True} if fresh else {}
    if count == 1:
        return await _job(name, "check", variant=variant, **extra)
    from .project import merge_shares

    timeout = STATE["check_timeout"]
    started = time.time()
    deadline = started + timeout - sandbox.soft_margin(timeout)
    results: list = [None] * count

    async def one(i: int) -> None:
        results[i] = await _job(name, "check", variant=variant, share=[i, count], deadline=deadline, started=started,
                                **extra)

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
async def check(name: str, variant: str | None = None, fresh: bool = False) -> str:
    """Run the print checks: validity, overlap between assembly parts (incl. stand-ins),
    overhangs > 45 deg from vertical in print orientation (bed face ignored) and bridge spans,
    thin features (walls under one line width fail), round-topped horizontal holes, fillets on
    bed edges, gaps between parts printed in place, the script's Wall checks (thinnest material
    around deep cuts) and Probes. The fit between an assembly's pieces (hole alignment, gaps) is
    a separate tool, check_fit, unless the script lists Mates() in checks(d). Fix every FAIL;
    report every WARN. On a remote server (HTTP/SSH) the part is not on the user's machine until
    download_part brings it home. Uses the pieces cached by an earlier build, and each unchanged
    piece's findings of the per-piece checks; fresh=True builds and checks everything again."""
    res = await _check(name, variant, fresh)
    if not res.get("ok"):
        return _error_text(res)
    lines = [f"{'PASSED' if res['passed'] else 'FAILED'}"]
    for v, findings in res["variants"].items():
        lines.append(f"\n{name} [{v}]")
        for f in findings:
            lines.append(f"  [{f['level'].upper():4}] {f['check']:8} {f['target']}: {f['message']}")
            if (f.get("data") or {}).get("diagnosis"):
                from .diagnose import text

                lines += ["    " + x for x in text(f["data"]["diagnosis"], name).splitlines()]
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
async def suggest_orientation(name: str, variant: str | None = None, piece: str | None = None, load: str = "",
                              image: bool = False, size: str = "normal", inline: bool = True) -> list:
    """Rank the ways to put the part on the bed, so it does not print upside down or on a thin
    edge: the six axis-aligned orientations and the large flat faces of its convex hull, each
    scored on supports (area and grams under overhangs past max_overhang, bridges apart), bed
    contact, height and print time (rough estimates), bridges, tip-over risk (as the check) and,
    with a load or the structural style, whether the load runs along the layers (DS-T1). Returns
    a ranked table with the Rot(x, y, z) to apply in build(d) and how. Run it before export when
    the part is not obviously flat-bottomed. piece: one printable part (default: each).
    load: the bending or tension direction as build(d) returns the part ('X', 'along Y', 'XZ',
    '1,0,1'). image: also render the top choice (of the first part). Changes nothing."""
    _image_options(size)
    try:
        from .orient import parse_load

        parse_load(load)
    except ValueError as e:
        raise ToolError(str(e)) from None
    res = await _job(name, "orient", variant=variant, piece=piece, load=load or None, image=image or None, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    text = f"{name} [{res['variant']}]\n{res['text']}"
    if not res.get("image"):
        return [text]
    return _with_note(_with_image(f"{text}\n\ntop choice: {_show(res['image'])}", res["image"], inline), name)


@mcp.tool(structured_output=False)
@_files_doc
async def export(name: str, variant: str | None = None, formats: str | None = None, parts: str | None = None,
                 embed: bool = False, fresh: bool = False, view: str = "print") -> list:
    """Export printable parts to parts/<name>/out/, sorted: print/ (3MF, STL, print sheet: for the
    slicer), cad/ (STEP, GLB), images/, docs/ (BOM, view HTML), README.md. Default: every part, all variants. The
    files must reach the user: on a remote server download_part brings them home.
    parts: comma-separated part names from build() to build and export only those; variant: one
    variant. Uses the pieces cached by an earlier build and leaves files already up to date as
    they are (templates too); fresh=True builds and writes everything again.
    formats: comma-separated from step (other CAD: Onshape, Fusion, FreeCAD), stl and 3mf
    (slicers; 3MF keeps units), png (6-view preview + section views), glb (binary glTF, for web
    and 3D apps), print (the print sheet, <name>[_<variant>]_print.md: size, filament and time
    estimates, supports, tip-over, walls and infill, fits and hole compensation, PRINT_NOTES, for
    the slicer, including declared hardware), hardware (versioned whole-assembly BOM JSON,
    <name>[_<variant>]_hardware.json), bom and bom_csv (the shopping list of that hardware as a
    Markdown table, <name>[_<variant>]_bom.md, and as CSV, _bom.csv; hardware_list returns it in
    the result), or 'all'. Omit to use the user's `formats` setting (default: step, stl, 3mf and
    png). Ask the user which they want if unclear.
    view: a 3D view the user can turn in a browser, per variant: 'print' (default: the printable
    parts on the bed), 'assembly' (assembly(d) with its stand-ins) or 'none'. Over HTTP it is a
    signed link (no token, expires like the downloads); locally a self-contained HTML file in
    out/docs/ (works offline). Offer it to the user after an export.
    Over HTTP (a remote server) each file comes with a download link (no token needed, expires)
    and a b123d-print://files/ resource link; download_part gets the whole part (script, out/,
    ref/) in one zip. embed=True also puts files up to 2 MB into the result itself, for clients
    that can neither fetch URLs nor read resources."""
    if formats:
        try:
            parse_formats(formats)
        except ValueError as e:
            raise ToolError(str(e)) from None
    try:
        layout = viewer.parse_layout(view)
    except ValueError as e:
        raise ToolError(str(e)) from None
    res = await _job(name, "export", variant=variant, formats=formats, parts=parts, fresh=fresh or None, view=layout)
    if not res.get("ok"):
        return [_error_text(res)]
    out, extra, expires, budget = [], [], None, EMBED_TOTAL
    files = [Path(f) for v in res["variants"] for f in v["files"]]
    total = sum(f.stat().st_size for f in files)
    out.append(f"Exported {len(files)} file(s), {_human_size(total)} in all.")
    baked = _baked_note(load_settings(_root()))
    if baked:
        out.append(baked)
    if not formats and not formats_configured(_root()):
        out.append("These are the default formats (STEP, STL, 3MF and PNG). Narrow them: 3MF for Bambu/Orca/Prusa "
                   "slicers, STEP to edit in other CAD; pass formats= (e.g. formats='3mf') or set `formats` in the config.")
    for v in res["variants"]:
        out.append(f"[{v['variant']}]")
        for pname, r in v["parts"].items():
            out.append(f"  {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, valid={r['valid']}")
        out += [f"  {line}" for line in timing_lines(v["timing"])]
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
    views = _view_lines(name, res["variants"])
    if views:
        out.append("\n" + "\n".join(views))
    if STATE["ssh_dest"]:
        out.append("\n" + _pull_note(name, formats, None))
    if _remote():
        out.append("\n" + _home_note(name))
        out.append("\n" + _next_step(name))
    return ["\n".join(out), *extra]


def _baked_note(s) -> str:
    """The loud line for an export with an opt-in hole_comp built into the files ("" without one)."""
    from .setup import hole_note

    return hole_note(s) if s.hole_comp or s.hole_comp_h else ""


def _view_link(part: str, glb: Path) -> tuple[str, int]:
    """HTTP: the signed /view/ link of out/cad/<stem>.glb (the page; the model sits behind the same token)."""
    url, expires = links.sign_view(STATE["link_secret"], _ws_name(), part, glb.stem, STATE["link_ttl"])
    return _base_url() + url, expires


def _view_glb(name: str, path: str) -> Path | None:
    """The view GLB a build reported, if it really is a regular <parts_dir>/<name>/out/cad/*_view.glb
    in this workspace (the report comes from the process that ran the part script: never trust a path in it)."""
    root = _root()
    parts_dir = load_settings(root).parts_dir
    try:
        rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
        f = links.servable(root, parts_dir, rel)
    except (ValueError, OSError, links.LinkError):
        return None
    return f if rel == f"{parts_dir}/{name}/out/{outdir.CAD}/{f.name}" and f.name.endswith("_view.glb") else None


def _view_lines(name: str, variants: list[dict]) -> list[str]:
    """What export says about the 3D views it wrote: a link (HTTP), a file (stdio) or how to make one (SSH)."""
    lines = [f"  [{v['variant']}] no 3D view: {v['view_error']}" for v in variants if v.get("view_error")]
    glbs = [(v["variant"], g) for v in variants if v.get("view") and (g := _view_glb(name, str(v["view"])))]
    if not glbs:
        return ["3D view:", *lines] if lines else []
    if _http():
        expires = 0
        for var, glb in glbs:
            url, expires = _view_link(name, glb)
            lines.append(f"  [{var}] {url}")
        when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))
        return [f"3D view (give the user these links: they open in a browser, need no token and expire {when}; "
                "rotate, hide pieces, measure the bounding box, cut a section):", *lines]
    if STATE["ssh_dest"]:
        return [f"3D view: written as out/{outdir.CAD}/{glbs[0][1].name} on the server. After `b123d-print pull {name}`, "
                f"`b123d-print view {name}` on the user's machine writes a self-contained HTML view of it "
                "(opens offline in a browser).", *lines]
    for var, glb in glbs:
        lines.append(f"  [{var}] {viewer.write_offline(glb)}")
    return ["3D view (self-contained HTML files, no server needed: tell the user to open them in a browser; "
            "they work offline):", *lines]


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
async def list_edges(name: str, variant: str | None = None, part: str | None = None,
                     highlight: list[int] | int | str | None = None, face: int | str | None = None,
                     kind: str | None = None, convexity: str | None = None, near: list[float] | str | None = None,
                     radius: float = 1.0, limit: int = 200, size: str = "normal", inline: bool = True) -> list:
    """The edges of a printable part, to pick the ones for a fillet or chamfer by id instead of
    guessing a selector: stable ids (1 = the longest; changed geometry may renumber), type (line,
    circle, arc, ellipse, spline), length, start and end (or center and radius), convexity (convex:
    an outside edge; concave: an inside corner; tangent: a smooth joint such as a fillet's side;
    seam), the turn between its faces and the two faces it joins (flat faces by their list_faces
    id, curved ones by type). Filters: face (an id, side or 'x,y,z' as in list_faces: its edges),
    kind, convexity, near ('x,y,z': edges within `radius` mm, nearest first); limit caps the list.
    part: which printable part. highlight: edge ids ('3,4,7', '3-6' or a list): also returns a
    picture with them in red and `selector`, a build123d expression (filter_by/group_by/sort_by
    on part.edges(), one face's edges or convex_edges/concave_edges(part)) that selects exactly
    those edges, verified on the part; put that in the script, never the ids (they change when the model changes).
    size: 'normal' or 'small'."""
    _image_options(size)
    if isinstance(face, str) and "," in face:
        face = _triple(face, "face")
    res = await _job(name, "edges", variant=variant, part=part, highlight=highlight, face=face, kind=kind,
                     convexity=convexity, near=_triple(near, "near"), radius=radius, limit=limit, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    image = res.pop("image", None)
    res.pop("ok", None)
    text = json.dumps(res, indent=1)
    if not image:
        return [text]
    sel = res["selector"]
    head = (f"edges {sel['ids']} in red: {_show(image)}\nselector: {sel['expr']}\n"
            + (f"import: {sel['import']}\n" if sel.get("import") else "") + f"({sel['note']})")
    return _with_note(_with_image(f"{head}\n{text}", image, inline), name)


@mcp.tool(structured_output=False)
async def measure(name: str, kind: str, a: str | None = None, b: str | None = None,
                  at: list[float] | str | None = None, direction: list[float] | str | None = None,
                  face: int | str | None = None, face2: int | str | None = None, frame: str = "auto",
                  variant: str | None = None, image: bool = False, size: str = "normal", inline: bool = True) -> list:
    """Precise measurements on the built part, in mm, with the points where they were taken: check
    fits with numbers instead of guessing from pictures. kind:
    'distance' (a, b: piece names from build() or assembly labels, stand-ins included): the
    smallest gap and its two points, or when they overlap the interference volume, its box and
    depth. Two assembly labels are measured where assembly(d) puts them (the fit).
    'wall' (at: x,y,z on or in the material; direction: optional x,y,z): the thickness along a
    line through the point (default: into the part along the nearest face's normal), with the gaps
    and walls beyond it.
    'faces' (face, face2: ids or sides from list_faces): the distance between two parallel flat
    faces (a wall, a slot), or the angle between them, and their closest points.
    'hole' (face: a flat face id or side, and/or at: a point at the hole): each round hole's
    modeled diameter, what it prints at after hole_comp, center, axis, through or blind depth.
    a: the piece for wall, faces and hole (default: the only one). frame: 'auto' (default),
    'print' (as build() returns it) or 'assembly' (as assembly(d) places it); points are in that
    frame. image: also a picture of the part with what was measured in red. Uses the build cache."""
    _image_options(size)
    kind = (kind or "").lower()
    if kind not in ("distance", "wall", "faces", "hole"):
        raise ToolError("kind: 'distance', 'wall', 'faces' or 'hole'")

    def fid(v):
        if v is None or str(v).strip() == "":
            return None
        v = str(v).strip()
        return int(v) if v.lstrip("-").isdigit() else (_triple(v, "face") if "," in v else v)

    q = {"kind": kind, "a": a, "b": b, "at": _triple(at, "at"), "direction": _triple(direction, "direction"),
         "face": fid(face), "face2": fid(face2), "frame": frame, "image": image}
    res = await _job(name, "measure", variant=variant, query={k: v for k, v in q.items() if v is not None}, size=size)
    if not res.get("ok"):
        return [_error_text(res)]
    res.pop("ok", None)
    img = res.pop("image", None)
    text = f"{res.pop('summary')}\n{json.dumps(res, indent=1)}"
    if not img:
        return [text]
    return _with_note(_with_image(f"{text}\nhighlight: {_show(img)}", img, inline), name)


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
    part. Writes <name>_template_<id>.* in `formats` (default: the formats setting): 3MF/STL in
    parts/<name>/out/print/templates/, STEP in out/cad/; with png also out/images/<...>_where.png, the part with the template's source in red (returned
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
    out = _with_note(out + extra, name)
    if _remote():
        out[0] += "\n\n" + _next_step(name)
    return out


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
    = ''); formats: only those out/ files (step, stl, 3mf, png, glb, print, hardware, bom, bom_csv); the script and ref/ always come.
    Over HTTP it also gives the 3D view links of the views export wrote (in a browser, no token).
    embed=True also puts the zip (up to 8 MB) into the result (over HTTP and SSH), for clients
    whose shell has no network (Antigravity/agy) or that can neither fetch URLs nor read
    resources: unzip it from where the client saved it. Call it as the last step of remote work,
    before reporting: a part is not done until its files are on the user's machine."""
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
        out = [f"{head}\n{_pull_note(name, formats, variant)}\nThen check the files are there (e.g. ls parts/{name}/out) "
               f"before reporting.\n{listing}\n\n{_home_note(name)}"]
        return _embed_zip(out, files, total, prefix, f"b123d-print://download/{_ws_name()}/{name}", name) if embed else out
    query = links.zip_query(variant, formats)
    url, expires = links.sign_zip(STATE["link_secret"], _ws_name(), name, query, STATE["link_ttl"])
    url = _base_url() + url
    when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))
    views = [f"  {_view_link(name, p)[0]}" for rel, p in _part_files(name, variant, "glb")
             if rel == f"out/{outdir.CAD}/{p.name}" and p.name.endswith("_view.glb")]
    text = (f"{head}\n"
            f"Download it (one zip, no token needed; the link expires {when}; after that call download_part again):\n"
            f"  curl -fLo {name}.zip '{url}'\n"
            f"Then, in the project folder: unzip -o {name}.zip   (Windows: tar -xf {name}.zip)\n"
            f"It creates the same layout as a local install (paths relative to the project folder):\n{listing}\n"
            f"Check the files are there on the user's machine (e.g. ls {prefix}/out) before reporting.\n"
            + (f"3D view in a browser (no token, same expiry; offer it to the user):\n" + "\n".join(views) + "\n"
               if views else "")
            + "\n" + _home_note(name))
    from mcp_types import ResourceLink

    uri = f"b123d-print://download/{_ws_name()}/{name}"
    out: list = [text, ResourceLink(uri=uri, name=f"{name}.zip", mime_type="application/zip",
                                    description=f"the whole part as a zip (unfiltered); download: {url}")]
    return _embed_zip(out, files, total, prefix, uri, name) if embed else out


def _embed_zip(out: list, files, total: int, prefix: str, uri: str, name: str) -> list:
    """download_part(embed=True): the zip inside the result, and how to unzip it where the client saved it."""
    if total > EMBED_TOTAL:
        out[0] += (f"\n(embed: not embedded, the part is over {EMBED_TOTAL // 1_000_000} MB; use the link, or narrow it "
                   f"with formats= or variant=)")
        return out
    out[0] += (f"\n\nEMBEDDED: the zip ({name}.zip, {prefix}/...) is in this result, no network needed. Your client "
               f"saves it to a file (Antigravity: .../brain/<conversation>/.system_generated/steps/<N>/media_0.zip). "
               f"Unzip it into the project folder, as one command (no && or |):\n"
               f"  unzip -o <saved zip> -d <project folder>   (Windows: tar -xf <saved zip> -C <project folder>)\n"
               f"Then check {prefix}/out/ is there before reporting.")
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
    to it (e.g. 'refs/bracket.stl', 'parts/bracket/out/print/bracket.3mf'). thresholds: optional
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
    res = await _run(job, outdir.out_of(cand) or cand.parent)  # a part's export: the picture in its out/images/
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
    to remix it, or a scan or photo (PNG, JPEG, TIFF, BMP) to trace with trace_outline (the part
    folder may not exist yet). With data_base64 (the whole file, base64) it
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
        return f"Stored {rel} ({len(data):,} bytes). Next: {_ref_next(part, filename)}."
    if os.path.lexists(target) and not overwrite:
        return f"{rel} is already there. Next: {_ref_next(part, filename)} (overwrite=True to replace it)."
    if _http():
        url, expires = links.sign(STATE["link_secret"], _ws_name(), rel, STATE["link_ttl"],
                                  purpose="put-overwrite" if overwrite else "put")
        return (f"Ask the user to upload the file from their machine (no token needed; up to "
                f"{refs.MAX_BYTES // 1_000_000} MB; the link expires "
                f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(expires))}):\n"
                f"  curl -fT <path/to/{filename}> '{_base_url()}{url}'\n"
                f"Then {_ref_next(part, filename)}.")
    if STATE["ssh_dest"]:
        return (f"Ask the user to run this on their machine (the same SSH key as this MCP connection):\n"
                f"  b123d-print push <path/to/{filename}> --part {part} --to {STATE['ssh_dest']}"
                f"{' --overwrite' if overwrite else ''}\n"
                f"Then {_ref_next(part, filename)}.")
    return (f"This server runs locally: copy the file to {target} (create the folder if needed; you may do it "
            f"yourself if you can write files). Then {_ref_next(part, filename)}.")


def _ref_next(part: str, filename: str) -> str:
    from .refs import IMAGE_SUFFIXES

    if Path(filename).suffix.lower() in IMAGE_SUFFIXES:
        return f"trace_outline('{part}', '{filename}', <scale: dpi, grid, reference or points + distance>)"
    return f"describe_model('{part}', '{filename}')"


@mcp.tool(structured_output=False)
async def describe_model(part: str, file: str, scale: str = "", image: bool = True, size: str = "normal",
                         inline: bool = True) -> list:
    """Inspect an original model before remixing it: format, units (and whether they look wrong),
    size, volume, triangles and faces before/after merging coplanar triangles, how much is curved
    (faceted), round holes (diameter, axis, center), repairs needed, the designer/license metadata
    the file carries, and a suggestion: MODIFY it or REDRAW it. part: the part it is for. file: a
    name in parts/<part>/ref/ (or a workspace path such as 'refs/x.stl'). scale: '' (as the file
    says), a factor, or the unit the file was drawn in ('inch', 'cm'). image: also a 6-view render
    (saved as parts/<part>/out/images/<file>_original.png)."""
    _image_options(size)
    path = _ref_file(part, file)
    from .refs import IMAGE_SUFFIXES

    if path.suffix.lower() in IMAGE_SUFFIXES:
        raise ToolError(f"{file} is an image: trace_outline('{part}', '{file}', ...) traces a flat object in it")
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
# Fit between pieces, outline tracing, recipes


@mcp.tool()
async def check_fit(name: str, variant: str | None = None, hole_tol: float | None = None, verbose: bool = False,
                    fresh: bool = False) -> str:
    """How the pieces of assembly(d) fit together, as placed (stand-ins count as obstacles):
    interference (pairs that overlap: the volume and where; pairs closer than the clearance
    without touching: the gap and where; faces resting on each other are contact) and hole
    alignment (round holes of two pieces on one axis are partners: offset beyond hole_tol mm,
    default 0.2, fails; their diameters read as screw holes, clearance + pilot / insert / nut,
    and a pair no single screw explains warns; a hole whose axis runs into solid material of the
    next piece has no partner). Male/female joint pairs from the script's joints(d) (or a
    Mates(joints=...) in checks(d)) are intentional fits measured against their own clearance.
    Stand-ins: labels saying stand-in or dummy, or matching no piece of build(). verbose: list
    the passing pairs too. One variant, or all. Uses the build cache (fresh=True rebuilds)."""
    res = await _job(name, "fit", variant=variant, hole_tol=hole_tol, verbose=verbose or None, fresh=fresh or None)
    if not res.get("ok"):
        return _error_text(res)
    head = "PASSED" if res["passed"] else "FAILED"
    return _scrub(head + "\n" + "\n\n".join(v["text"] for v in res["variants"]))


@mcp.tool()
async def hardware_list(name: str = "", variant: str | None = None, count: int = 1, parts: str | None = None,
                        format: str = "table") -> str:
    """What to buy: the bought hardware the script declares in hardware(d) (screws, inserts,
    magnets, bearings), as one Markdown table to show the user: Qty | Item | Specification |
    Used for | Source/link | Status ("check before ordering" where the specification is not
    confirmed: ask the user, never guess it). Identical items are merged and summed. Offer it
    when a part declares hardware. name: one part; parts: comma-separated part names to merge
    into one list (each may be part:variant); neither: every part in the workspace. variant: the
    variant (default: the standard one). count: how many assemblies ("for 4 brackets"), which
    multiplies every quantity. format: 'table' (Markdown) or 'csv' (for a spreadsheet or cart).
    Reads only hardware(d): builds nothing. The `bom` and `bom_csv` export formats write the
    same list next to the exports. Changes nothing."""
    if format not in ("table", "csv"):
        raise ToolError(f"format {format!r}: use 'table' or 'csv'")
    if type(count) is not int or not 1 <= count <= 100_000:
        raise ToolError("count must be a whole number from 1 to 100000")
    wanted = [x.strip() for x in ([name] if name else []) + (parts.split(",") if parts else []) if x.strip()]
    every = not wanted
    if every:
        wanted = [p.parent.name for p in find_parts(_root(), load_settings(_root()).parts_dir)]
        if not wanted:
            raise ToolError("no parts in the workspace yet (use new_part)")
    picks = []
    for w in dict.fromkeys(wanted):
        part, _, v = w.partition(":")
        _script(part)  # a bad or unknown name is the caller's mistake: say so before running anything
        picks.append((part, v or variant))
    results: dict[int, dict] = {}

    async def one(i: int, part: str, v: str | None) -> None:
        res = await _job(part, "hardware", variant=v)
        if res.get("ok"):
            results[i] = {"part": part, **{k: res[k] for k in ("variant", "variants", "declared", "items")}}
        else:
            results[i] = {"part": part, "error": str(res.get("error")), "res": res}

    async with anyio.create_task_group() as tg:
        for i, (part, v) in enumerate(picks):
            tg.start_soon(one, i, part, v)
    entries = [results[i] for i in range(len(picks))]
    failed = [e for e in entries if "error" in e]
    if failed and (not every or len(failed) == len(entries)):  # a part asked for by name must be read
        return _error_text(failed[0]["res"])
    for e in failed:
        e.pop("res")
    from .hardware import shopping_list

    return _scrub(shopping_list(entries, count, "csv" if format == "csv" else "table"))


def _numbers(v, n: int, what: str) -> list[float] | None:
    if v in (None, "", []):
        return None
    try:
        vals = [float(x) for x in (v.replace(";", ",").split(",") if isinstance(v, str) else v)]
    except (TypeError, ValueError):
        raise ToolError(f"{what}: {n} numbers") from None
    if len(vals) != n:
        raise ToolError(f"{what}: {n} numbers, got {len(vals)}")
    return vals


@mcp.tool(structured_output=False)
@_files_doc
async def trace_outline(part: str, file: str, dpi: float | None = None, grid: float | None = None, reference: str = "",
                        points: str = "", distance: float | None = None, tolerance: float = 0.2, smooth: bool = False,
                        pick: str = "", threshold: float | None = None, invert: bool | None = None,
                        inline: bool = True) -> list:
    """Trace a flat object in a scan or photo (parts/<part>/ref/<file>, from upload_reference) into a
    2D outline in mm for a part script: the largest object's outline and its holes, simplified to
    `tolerance` mm (few points: dense polylines build slowly), or with smooth=True through-points
    for a periodic spline. Scale, one of: dpi (a flatbed scan; omit everything to read it from the
    file), grid (cell size in mm of a grid or cutting mat under the object), reference ('card' =
    a credit card 85.60 x 53.98 mm beside the object, or 'L,S' mm of another rectangle), or points
    ('x1,y1,x2,y2' pixels, origin top left) with distance (mm between them). pick: 'x,y' pixel
    inside the object to trace when it is not the largest. threshold (0..1) and invert (object
    lighter than the background) override the automatic threshold. Writes out/docs/<file>_outline.json
    (the points), out/docs/<file>_outline.py (a snippet with OUTLINE, OUTLINE_HOLES and a face function)
    and out/images/<file>_trace.png (the outline on the image: show it to the user to confirm). A scan is
    accurate to about a pixel; a photo only as far as it is square-on, flat and undistorted:
    check a known dimension before trusting it."""
    path = _ref_file(part, file)
    from .refs import IMAGE_SUFFIXES

    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ToolError(f"{file}: trace_outline reads images ({', '.join(IMAGE_SUFFIXES)}); describe_model is for models")
    scale: dict = {}
    if dpi:
        scale["dpi"] = dpi
    if grid:
        scale["grid"] = grid
    if reference:
        scale["reference"] = reference if "," not in reference else _numbers(reference, 2, "reference")
    if points:
        scale["points"] = _numbers(points, 4, "points")
        scale["distance"] = distance
    args = {"tolerance": tolerance, "smooth": smooth, "threshold": threshold, "invert": invert,
            "pick": _numbers(pick, 2, "pick")}
    res = await _run({"op": "trace", "file": str(path), "scale": scale, "args": args}, _parts_dir() / part / "out")
    if not res.get("ok"):
        return [_error_text(res)]
    t = res["trace"]
    files = ", ".join(_show(f) for f in t["files"].values())
    text = (f"{res['text']}\nfiles: {files}\n\nShow the overlay to the user and confirm the outline and one known "
            f"dimension before modeling with it.\n\n```python\n{res['snippet']}```")
    return _with_note(_with_image(text, t["image"], inline), part)


@mcp.tool()
def recipe(name: str = "") -> str:
    """Tested build123d recipes for common printable features, with printing notes and sources:
    teardrop holes, counterbores and countersinks, nut traps, magnet pockets, snap arms (with
    strain sizing), living hinges, print-in-place hinges, lids with a lip, text, bed-edge
    chamfers, zip-tie and cable slots, ribs and gussets. name: '' lists them; a recipe (or one of
    its function names) gives its code, an example and the notes. Use one before improvising the
    feature; part scripts import them: from b123d_print.recipes import snap_arm."""
    from . import recipes

    if not name:
        return recipes.index()
    try:
        return recipes.get(name).text()
    except KeyError as e:
        raise ToolError(e.args[0]) from None


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


@mcp.resource("b123d-print://recipes", mime_type="text/markdown")
def recipes_index() -> str:
    """The recipe library: tested build123d functions for common printable features."""
    from . import recipes

    return recipes.index()


@mcp.resource("b123d-print://recipes/{name}", mime_type="text/markdown")
def recipe_text(name: str) -> str:
    """One recipe: its code, a tested example, printing notes and sources."""
    from mcp.server.mcpserver.exceptions import ResourceError

    from . import recipes

    try:
        return recipes.get(name).text()
    except KeyError as e:
        raise ResourceError(e.args[0]) from None


@mcp.resource("b123d-print://files/{workspace}/{+path}", mime_type="application/octet-stream")
def workspace_file(workspace: str, path: str) -> bytes:
    """A file the server wrote (parts/<part>/out/..., e.g. out/print/<part>.3mf), in this session's own workspace ('_' = the
    root workspace). Tool results link to these; over HTTP the same files have download links."""
    from mcp.server.mcpserver.exceptions import ResourceError

    if workspace != _ws_name():
        raise ResourceError(f"workspace {workspace!r} is not this session's ({_ws_name()!r})")
    root = _root()
    try:
        return links.servable(root, load_settings(root).parts_dir, path).read_bytes()
    except links.LinkError:
        raise ResourceError(f"no file {path!r} (only files in parts/<part>/out/ and its folders are served)") from None


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
            f"command it gives; if your shell has no network, download_part('{name}', embed=True) and unzip the "
            "embedded zip from where your client saved it. Check the files exist on my machine before reporting. "
            "Use only the MCP tools and "
            "their links: never ssh, scp or a shell on the server (there is none). The server copy is temporary.")


@mcp.prompt()
def design_part_from_photos(description: str = "") -> str:
    """Design a new part from photos and measurements: confirm dimensions first, then model,
    verify and report."""
    return f"""I want a 3D-printable part designed with the b123d-print tools.

{description or '(I will describe the part and attach photos.)'}

Work in these steps:
1. From my photos and text, LIST EVERY DIMENSION you read, the feature it belongs to and its
   source (typed by me / read from a photo / estimate). For each hole, say whether its size is
   the printed hole or the size of what goes in it (a 4 mm dowel: + clearance per side; holes
   are drawn true to size, plus HOLE_COMP only if I opted in). List features you can see that have no
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
   HOLE_COMP_H). Model in print orientation, bed at Z=0. Threads, screws, inserts, gears and
   V-slot parts: use bd_warehouse and py_gearworks, kept to sizes that print (the rules below).
3. Verify: build_part, render_preview, section through every pocket, boss, rib, hole and mating
   feature, and check. Add Wall checks wherever a cut goes deeper than the wall it starts in.
   Fix and repeat until check passes.
4. Remote server (HTTP or SSH) only, required: {_remote_step()}
5. Report: overall X x Y x Z, key feature sizes (holes with their cut size: "hole for a 4 mm
   dowel (cut 4.30: clearance 0.15 per side)"), validity, clearances (per side or total) and hole compensation applied, check results and warnings, print orientation, supports needed,
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
def setup_workspace() -> str:
    """First-run setup: ask the user for the printer, material, export formats and default style,
    save them with save_setup, then offer the calibration coupons in order."""
    return """Set up b123d-print for me before we design anything. Ask one short question at a time
and keep my answers; skip a question I have already answered.
1. list_parts: read the printer, settings and formats in effect. If a printer is already set,
   tell me which and ask whether to keep it.
2. Printer: ask which printer I have, then use_printer(search='<my words>') and let me pick one
   name from the matches (or 'generic' for none). Do not guess a printer.
3. Material: pla, petg, asa, abs, tpu or one of my own (it sets notes and, for some, the clearance).
4. Formats: what my slicer and other CAD want: 3mf for Bambu Studio, OrcaSlicer and PrusaSlicer,
   step to edit the part in other CAD (Onshape, Fusion, FreeCAD), stl for anything else, png
   previews, print for a print sheet, hardware for declared BOM JSON, bom / bom_csv for the
   shopping list. Default: step,stl,3mf,png.
5. Default style for parts that set none: functional (default), modern/minimal, least_cost,
   rugged/outdoor, soft/handheld or structural/load-bearing.
6. Holes: parts are modeled true to size and the SLICER corrects holes. Ask whether my slicer
   has X-Y hole compensation, X-Y contour compensation or elephant-foot compensation set, and
   whether I have measured the hole coupon. Its result goes into the slicer's X-Y hole
   compensation (OrcaSlicer/Bambu Studio: Precision; Cura: Hole Horizontal Expansion): half the
   diameter error, per side; tell me the number. Then save_setup(hole_comp=0) records that the
   slicer does it. hole_comp in b123d-print is an opt-in (default 0) that builds the correction
   into the files, for one printer only, with the slicer's at 0: only if I ask for it, and only a
   measured value. Shrinkage and overall size (an XYZ cube: filament shrinkage %, X-Y contour or
   size compensation) also belong in the slicer, per filament; there is no scale setting here.
   Elephant-foot compensation stays on as usual.
   Two printers of the same model: use_printer(name=..., nickname='p2s-garage') gives each its own
   calibration.
7. save_setup with my answers. If it reports conflicts (values already set), show them and ask
   before calling it again with overwrite=True.
8. Calibration order: first the slicer's own dimensional calibration (an XYZ cube, for shrinkage
   and overall size) if I do one, then offer the coupons one at a time: hole_coupon (the slicer's
   hole compensation: the calibrate_hole_comp prompt walks through it), fit_coupon (clearance,
   press_fit, free_fit, pip_clearance; printed with the same slicer settings as real parts, so
   the fits include the slicer's correction), overhang_bridge_coupon (the overhang angle and
   bridge length). The coupons measure whatever the slicer does at the time: redo them when I
   change the slicer's compensation or the filament. For each: new_part('<name>', example='<name>'), export
   it, say how to measure it, and store the result with save_setup
   (calibration={'clearance': ..., 'max_bridge': ...}); it is kept for the active printer +
   material. Locally `b123d-print printer calibrate <key> <value>` does the same.
9. Remote server (HTTP or SSH) only: the settings and measured values are saved in this
   workspace on the server, per printer; coupons are brought home like any part (download_part).
   If save_setup says measured values are set for every printer, ask me, then
   save_setup(move_flat=True) moves them under the active printer.
10. Report what is set, where it is saved, what calibration is still to do, and save_setup's
   'slicer' line (where holes are corrected)."""


@mcp.prompt()
def calibrate_hole_comp() -> str:
    """Walk through measuring HOLE_COMP with the calibration coupon."""
    return """Help me calibrate hole compensation for my printer. Parts are modeled true to size;
the slicer corrects the holes.
1. If the workspace has no 'hole_coupon' part, create it with
   new_part('hole_coupon', example='hole_coupon') (vertical holes 2-8 mm in the plate, horizontal
   round and teardrop holes 3-8 mm in the tab, all cut at NOMINAL size, labeled), then export it
   and tell me where the file is.
2. Ask whether my slicer has X-Y hole compensation, X-Y contour compensation or elephant-foot
   compensation set. Tell me to print the coupon with X-Y hole compensation at 0, or the
   measurement includes the slicer's old correction. Shrinkage and contour compensation from an
   XYZ cube come first and stay as set (elephant-foot compensation too); redo the coupon when
   they or the filament change.
3. Ask me to print it with my usual material and settings and to measure every vertical hole
   and every teardrop (the upper row of the tab).
4. Diameter error = average(nominal - measured) over the vertical holes I use; point out if it
   grows with size. Tell me the slicer value: half of it, per side, in X-Y hole compensation
   (OrcaSlicer/Bambu Studio: Precision; Cura: Hole Horizontal Expansion), e.g. holes 0.3 mm
   small -> 0.15. Then save_setup(hole_comp=0) records that the slicer does it (locally
   `b123d-print printer calibrate hole_comp 0`). Fits stay in the model; print the fit_coupon
   with these same slicer settings.
5. Only if I ask to build the correction into the files instead (opt-in, e.g. to correct
   horizontal holes, which the slicer cannot treat apart): save_setup(hole_comp=<diameter
   error>, hole_comp_h=<the teardrops' error>), and the slicer's X-Y hole compensation stays 0.
   Say that every exported file then has it built in and is for this printer only. Never
   hard-code it in part scripts."""


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


@mcp.custom_route("/view/{workspace}/{token}/{part}/{file}", methods=["GET"])
async def view_link(request):
    """A signed 3D view link (export's view): needs no bearer token. .../<stem> is the viewer page
    (the same static page for every part), .../<stem>.glb the model, which must be
    <parts_dir>/<part>/out/cad/<stem>.glb (or the flat out/<stem>.glb before 0.3.11) in the workspace
    the link was signed for; until it expires."""
    from starlette.responses import FileResponse, PlainTextResponse, Response

    ws, token, part, file = (request.path_params[k] for k in ("workspace", "token", "part", "file"))
    is_model = file.endswith(".glb")
    stem = file[:-4] if is_model else file
    try:
        if not NAME_RE.match(part) or not stem:
            raise links.LinkError(404, "not found")
        links.check_path(f"{part}/{stem}.glb")
        links.verify_view(STATE["link_secret"], ws, token, part, stem)
        root = _ws_dir(ws)
        if root is None:
            raise links.LinkError(404, "not found")
        parts_dir = load_settings(root).parts_dir
        try:
            glb = links.servable(root, parts_dir, f"{parts_dir}/{part}/out/{outdir.CAD}/{stem}.glb")
        except links.LinkError:  # a view exported before 0.3.11, in the flat out/
            glb = links.servable(root, parts_dir, f"{parts_dir}/{part}/out/{stem}.glb")
    except links.LinkError as e:
        return PlainTextResponse(str(e) + "\n", status_code=e.status,
                                 headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    if ws != links.ROOT_WS:
        handoff.touch(root)  # a view is a use too
    if is_model:
        return FileResponse(glb, media_type=viewer.GLB_MIME, filename=glb.name, content_disposition_type="attachment",
                            headers=viewer.MODEL_HEADERS)
    return Response(viewer.served_page(), media_type="text/html; charset=utf-8", headers=viewer.PAGE_HEADERS)


@mcp.custom_route("/view-assets/{name}", methods=["GET"])
async def view_asset(request):
    """The viewer page's static files: a fixed list of package files (viewer.ASSETS), no token."""
    from starlette.responses import PlainTextResponse, Response

    name = request.path_params["name"]
    if name not in viewer.ASSETS:
        return PlainTextResponse("not found\n", status_code=404, headers={"X-Content-Type-Options": "nosniff"})
    return Response(viewer.asset_bytes(name), media_type=viewer.ASSETS[name], headers=viewer.ASSET_HEADERS)


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
    if path.startswith(("/files/", "/upload/", "/zip/", "/view/")):  # never log the signature: a log line must not be a working link
        parts = path.split("/", 4)
        path = f"/{parts[1]}/{parts[2] if len(parts) > 2 else '?'}/.../{parts[4] if len(parts) > 4 else ''}"
    client = (scope.get("client") or ("-",))[0]
    ws = f" ws={workspace}" if workspace is not None else ""
    print(f"b123d-print-mcp: {client} {who} {scope['method']} {path}{ws} -> {status}", file=sys.stderr, flush=True)


class TokenAuth:
    """ASGI wrapper: every HTTP request except /health, the viewer's static /view-assets/ and the signed /files/,
    /zip/, /upload/ and /view/ links (which carry their own HMAC, see download) needs `Authorization: Bearer <token>` of a known named token, and
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
        if path.startswith(("/files/", "/upload/", "/zip/", "/view/", "/view-assets/")):
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
        try:
            ws = _requested_workspace(scope)
        except ValueError as e:
            await _deny(send, 400, "invalid_request", str(e))
            return _log(scope, tok.name, 400)
        if ws is None and tok.default_workspace():
            ws = tok.default_workspace()
        # the one workspace this request runs in: the tools read only this (_request_workspace)
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
    ap.add_argument("--timeout", type=float, default=float(env("B123D_PRINT_TIMEOUT", sandbox.DEFAULT_TIMEOUT)),
                    help=f"seconds per build, render, section or export (default {sandbox.DEFAULT_TIMEOUT:g}; $B123D_PRINT_TIMEOUT)")
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
    for f in (tokens_file, env("B123D_PRINT_TOKEN_FILE")):
        if f:  # never readable by a job, wherever it is
            sandbox.SECRET_FILES.add(str(Path(f).expanduser().resolve()))
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
