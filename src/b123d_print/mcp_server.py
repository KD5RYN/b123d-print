"""b123d-print MCP server (stdio): design, check and export 3D-printable build123d parts from any MCP
client. Part scripts are model-written code: every build runs in a sandboxed subprocess.

    b123d-print-mcp --workspace ~/parts            # or B123D_PRINT_WORKSPACE=~/parts; default: the cwd
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import anyio
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import sandbox
from .cli import NAME_RE, data, examples, init_workspace, new_part as _new_part
from .config import load_settings, parse_formats
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

mcp = MCPServer("b123d-print", instructions=INSTRUCTIONS)
STATE: dict = {"root": Path.cwd(), "timeout": 120.0}


def _root() -> Path:
    return STATE["root"]


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
    script = _script(name)
    job = {"op": op, "script": str(script), **{k: v for k, v in kw.items() if v is not None}}
    return await anyio.to_thread.run_sync(
        lambda: sandbox.run_job(job, _root(), script.parent / "out", STATE["timeout"])
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
            "workspace": str(_root()),
            "parts_dir": s.parts_dir,
            "parts": parts,
            "examples": examples(),
            "settings": {"hole_comp": s.hole_comp, "clearance": s.clearance, "min_wall": s.min_wall,
                         "max_overhang": s.max_overhang, "formats": list(s.formats)},
            "sandbox": sandbox.describe(),
        },
        indent=1,
    )


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
    return f"Created {p.relative_to(_root())}. Edit it with write_part. Current code:\n\n{p.read_text()}"


@mcp.tool()
def read_part(name: str) -> str:
    """Return the current code of a part script."""
    return _script(name).read_text()


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
    p.write_text(code)
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


def main() -> None:
    ap = argparse.ArgumentParser(prog="b123d-print-mcp", description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=os.environ.get("B123D_PRINT_WORKSPACE"),
                    help="folder with b123d-print.toml / parts/ (default: $B123D_PRINT_WORKSPACE, else the cwd)")
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("B123D_PRINT_TIMEOUT", 120)),
                    help="seconds per build (default 120)")
    args = ap.parse_args()
    root = Path(args.workspace).expanduser().resolve() if args.workspace else Path.cwd()
    root.mkdir(parents=True, exist_ok=True)
    STATE.update(root=root, timeout=args.timeout)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
