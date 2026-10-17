"""b123d-print MCP server: design, check and export 3D-printable build123d parts from any MCP
client. Part scripts are model-written code: every build runs in a sandboxed subprocess.

    b123d-print-mcp --workspace ~/parts            # stdio; or B123D_PRINT_WORKSPACE=~/parts; default: the cwd
    B123D_PRINT_TOKEN=... b123d-print-mcp --transport http --port 8000   # Streamable HTTP at /mcp

Over HTTP every request needs `Authorization: Bearer <token>`, and each client picks its own
workspace with `/mcp?workspace=<name>` (or the header `X-B123D-Workspace`), which is the folder
<workspace>/workspaces/<name>; without one, clients share <workspace> itself.
"""

from __future__ import annotations

import argparse
import contextvars
import hmac
import json
import os
import re
import signal
import sys
from pathlib import Path

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import sandbox
from .cli import NAME_RE, data, examples, init_workspace, new_part as _new_part
from .config import WORKSPACE_FILE, load_settings, parse_formats
from .project import find_parts

MAX_SCRIPT_BYTES = 256_000

INSTRUCTIONS = """\
Design 3D-printable parts as build123d Python scripts, then build, look at, check and export them.
Workflow: new_part -> write_part (whole script) -> build_part -> render_preview + section ->
check -> fix and repeat -> export. Read the resource b123d-print://guide (or the prompt
design_part_from_photos) for the rules: named UPPER_CASE dimensions in a Dims dataclass, mm,
print orientation with the bed at Z=0, 0.2 mm mating clearance, HOLE_COMP from the user's config,
list photo-read dimensions and wait for confirmation, verify with renders, sections and checks
before reporting. render_preview and section return PNG images."""

WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WORKSPACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("b123d_print_workspace", default=None)


async def _request_workspace(ctx, call_next):
    """HTTP: the workspace this request asked for (?workspace=<name> or X-B123D-Workspace)."""
    req = getattr(ctx, "request", None)
    name = None
    if req is not None and hasattr(req, "query_params"):
        name = req.query_params.get("workspace") or req.headers.get("x-b123d-workspace")
    token = _WORKSPACE.set(name)
    try:
        return await call_next(ctx)
    finally:
        _WORKSPACE.reset(token)


mcp = MCPServer("b123d-print", instructions=INSTRUCTIONS, middleware=[_request_workspace])
STATE: dict = {"root": Path.cwd(), "timeout": 120.0, "transport": "stdio", "max_builds": 2, "limiter": None}


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


async def _job(name: str, op: str, **kw) -> dict:
    script, root = _script(name), _root()
    job = {"op": op, "script": str(script), **{k: v for k, v in kw.items() if v is not None}}
    return await anyio.to_thread.run_sync(
        lambda: sandbox.run_job(job, root, script.parent / "out", STATE["timeout"]), limiter=_limiter()
    )


def _error_text(res: dict) -> str:
    s = f"ERROR: {res.get('error')}"
    if res.get("traceback"):
        s += f"\n\n{res['traceback']}"
    if res.get("log"):
        s += f"\n\nOutput:\n{res['log']}"
    return s


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
            "settings": {"hole_comp": s.hole_comp, "clearance": s.clearance, "min_wall": s.min_wall,
                         "max_overhang": s.max_overhang, "formats": list(s.formats)},
            "printer": _printer_summary(s),
            "sandbox": sandbox.describe(),
            "max_concurrent_builds": STATE["max_builds"],
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
async def render_preview(name: str, variant: str | None = None, parts: str | None = None) -> list:
    """Render six views (iso, top, front, right, iso from below, bottom) as a PNG image.
    parts: comma-separated part names from build(), 'assembly' (assembled position with
    stand-ins), or omit for all printable parts. One variant (default: the first)."""
    res = await _job(name, "render", variant=variant, parts=parts)
    if not res.get("ok"):
        return [_error_text(res)]
    summary = {"variant": res["variant"], "parts": res["parts"], "file": res["image"]}
    return [json.dumps(summary, indent=1), Image(path=res["image"])]


@mcp.tool(structured_output=False)
async def section(name: str, plane: str, at: float, variant: str | None = None, parts: str | None = None) -> list:
    """Cross-section as a PNG image, each part in its own color. plane: 'XY' (at = Z height),
    'XZ' (at = Y) or 'YZ' (at = X), in mm. parts: default the assembly if the script has one
    (shows fit and clearances), else all printable parts; or comma-separated names."""
    if plane.upper() not in ("XY", "XZ", "YZ"):
        return ["plane must be XY, XZ or YZ"]
    res = await _job(name, "section", variant=variant, parts=parts, plane=plane, at=at)
    if not res.get("ok"):
        return [_error_text(res)]
    return [f"{res['plane']} section at {res['at']:g} mm ({res['variant']}): {res['image']}", Image(path=res["image"])]


@mcp.tool()
async def check(name: str, variant: str | None = None) -> str:
    """Run the print checks: validity, overlap between assembly parts (incl. stand-ins),
    overhangs > 45 deg from vertical in print orientation (bed face ignored), the script's Wall
    checks (thinnest material around deep cuts) and Probes. Fix every FAIL; report every WARN."""
    res = await _job(name, "check", variant=variant)
    if not res.get("ok"):
        return _error_text(res)
    lines = [f"{'PASSED' if res['passed'] else 'FAILED'}"]
    for v, findings in res["variants"].items():
        lines.append(f"\n{name} [{v}]")
        for f in findings:
            lines.append(f"  [{f['level'].upper():4}] {f['check']:8} {f['target']}: {f['message']}")
    return "\n".join(lines)


@mcp.tool()
async def export(name: str, variant: str | None = None, formats: str | None = None) -> str:
    """Export every printable part to parts/<name>/out/. Default: all variants.
    formats: comma-separated from step (other CAD: Onshape, Fusion, FreeCAD), stl and 3mf
    (slicers; 3MF keeps units), png (6-view preview + section views), or 'all'. Omit to use the
    user's `formats` setting (default: all four). Ask the user which they want if unclear."""
    if formats:
        try:
            parse_formats(formats)
        except ValueError as e:
            raise ToolError(str(e)) from None
    res = await _job(name, "export", variant=variant, formats=formats)
    if not res.get("ok"):
        return _error_text(res)
    out = []
    for v in res["variants"]:
        out.append(f"[{v['variant']}]")
        for pname, r in v["parts"].items():
            out.append(f"  {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, valid={r['valid']}")
        out += [f"  {Path(f).relative_to(_root())}" for f in v["files"]]
    return "\n".join(out)


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
   default, from config). Holes get HOLE_COMP (from config). Model in print orientation, bed at Z=0.
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
   new_part('hole_coupon', example='hole_coupon') (holes 2-8 mm cut at NOMINAL size, labeled),
   then export it and tell me where the STL is.
2. Ask me to print it with my usual material and settings and to measure every hole.
3. Compute HOLE_COMP = average(nominal - measured) over the sizes I use; point out if the error
   grows with size. Tell me to set it in ~/.config/b123d-print/config.toml:
       [print]
       hole_comp = <value>
   (or B123D_PRINT_HOLE_COMP). Do not hard-code it in part scripts."""


# ---------------------------------------------------------------------------------------------
# HTTP transport


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """Liveness for Docker / monitors; needs no token and reveals nothing but the version."""
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "version": _pkg_version()})


class RequireToken:
    """ASGI wrapper: every HTTP request except GET /health needs `Authorization: Bearer <token>`.

    One shared static token. (The SDK's own bearer auth is the OAuth resource-server path: it
    wants an issuer URL and a token verifier fixed when MCPServer is built, and advertises OAuth
    metadata that would send clients looking for an authorization server that does not exist.)"""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/health":
            scheme, _, cred = dict(scope["headers"]).get(b"authorization", b"").partition(b" ")
            if scheme.lower() != b"bearer" or not hmac.compare_digest(cred.strip(), self.token):
                body = b'{"error": "invalid_token", "error_description": "missing or wrong bearer token"}'
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer error="invalid_token"')]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def _token() -> str | None:
    tok = os.environ.get("B123D_PRINT_TOKEN")
    if not tok and os.environ.get("B123D_PRINT_TOKEN_FILE"):
        tok = Path(os.environ["B123D_PRINT_TOKEN_FILE"]).expanduser().read_text(encoding="utf-8")
    return tok.strip() if tok else None


def http_app(host: str, token: str | None, allowed_hosts: str | None = None):
    """The Streamable HTTP app (stateless: survives server restarts, any replica can answer)."""
    from mcp.server.transport_security import TransportSecuritySettings

    sec = None  # SDK default: Host/Origin checks on when bound to localhost, off otherwise
    if allowed_hosts:  # e.g. behind a reverse proxy: "cad.lan.cqspot.com,cad.lan.cqspot.com:*"
        hosts = [h.strip() for h in allowed_hosts.split(",") if h.strip()]
        sec = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts)
    app = mcp.streamable_http_app(stateless_http=True, host=host, transport_security=sec)
    return RequireToken(app, token) if token else app


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


def main() -> None:
    env = os.environ.get
    ap = argparse.ArgumentParser(prog="b123d-print-mcp", description=__doc__.splitlines()[0])
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
    ap.add_argument("--insecure-no-auth", action="store_true",
                    help="http: run without a token (otherwise $B123D_PRINT_TOKEN or $B123D_PRINT_TOKEN_FILE is required)")
    ap.add_argument("--healthcheck", action="store_true", help="check the running HTTP server's /health and exit (for Docker)")
    args = ap.parse_args()
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
    if not token and not args.insecure_no_auth:
        sys.exit("b123d-print-mcp: HTTP needs a token: set B123D_PRINT_TOKEN (or B123D_PRINT_TOKEN_FILE), "
                 "e.g. from `python -c 'import secrets; print(secrets.token_urlsafe(32))'`, "
                 "or pass --insecure-no-auth")
    if token and len(token) < 16:
        sys.exit("b123d-print-mcp: B123D_PRINT_TOKEN is too short (use at least 16 characters)")
    import uvicorn

    print(f"b123d-print-mcp: http://{args.host}:{args.port}/mcp  workspace {root}  "
          f"auth {'bearer token' if token else 'NONE'}  max builds {STATE['max_builds']}", file=sys.stderr)
    # uvicorn handles SIGTERM/SIGINT: stop accepting, let running calls finish for up to
    # --shutdown-grace seconds, then cancel them; any build still running is killed here
    # uvicorn re-raises the signal after its shutdown; make SIGTERM a normal exit so the cleanup runs
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        uvicorn.run(http_app(args.host, token, args.allowed_hosts), host=args.host, port=args.port,
                    log_level="info", timeout_graceful_shutdown=args.shutdown_grace)
    finally:
        n = sandbox.kill_all()
        print(f"b123d-print-mcp: stopped{f' ({n} running build(s) killed)' if n else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
