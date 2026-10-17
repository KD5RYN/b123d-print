# b123d-print

Design 3D-printable parts with an AI assistant — any assistant. You describe a part (photos,
caliper readings); the model writes a [build123d](https://github.com/gumyr/build123d) Python
script; b123d-print builds it in a sandbox, renders it, cuts cross-sections, runs print checks and
exports the formats you pick: STEP, STL, 3MF, PNG.

- **`b123d-print`** — Python package + CLI: export (STEP/STL/3MF/PNG, your choice), 6-view renders, colored
  multi-part cross-sections, and print checks: **overlap** between mating parts, **overhang**
  report in print orientation, **wall thickness** around cuts, plus simple **probes**.
- **`b123d-print-mcp`** — an [MCP](https://modelcontextprotocol.io) server, so it works from Claude
  Desktop / Claude Code, Gemini CLI, Cursor, VS Code, Codex and other MCP clients. Part scripts
  are model-written code, so they run in a sandboxed subprocess with a timeout and no network.
- **The workflow**, model-neutral: MCP prompts + [`AGENTS.md`](AGENTS.md). The rules came from
  real prints (one of them broke through a 0.05 mm skin the model could not see).
- **Examples**: parts that were designed this way and printed, in
  [`src/b123d_print/examples/`](src/b123d_print/examples/), plus a **hole calibration coupon**.

> **Images:** `render_preview` and `section` return PNG images. The model can only check its own
> work if your MCP client passes tool-result images to the model. Claude Desktop and Claude Code
> do; check your client's docs for others. Without it the checks still run, but the model is
> designing blind — look at the PNGs in `parts/<name>/out/` yourself.

## Install

Needs [uv](https://docs.astral.sh/uv/); it installs Python 3.12 and the pinned dependencies.
Below, `<b123d-print>` is where b123d-print comes from: a local checkout path today
(`/path/to/cad-kit`), or a published location once there is one.

```bash
uvx --from <b123d-print> b123d-print-mcp --help
```

The server works in one folder, the **workspace** (parts go in `parts/<name>/<name>.py`):
`--workspace DIR`, or `B123D_PRINT_WORKSPACE`, else the folder the client starts it in.

### Claude Code

```bash
claude mcp add b123d-print -- uvx --from <b123d-print> b123d-print-mcp --workspace ~/parts
```

or install the plugin (MCP server + a small skill that points at the same workflow):
`/plugin marketplace add <b123d-print>` then `/plugin install b123d-print@b123d-print`. The plugin uses the
folder Claude Code starts the server in (the project) as the workspace.

### Claude Desktop

`claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "uvx",
      "args": ["--from", "<b123d-print>", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
    }
  }
}
```

Always pass `--workspace` here. If `uvx` is not found, use its full path (`which uvx`).

### Gemini CLI

`~/.gemini/settings.json` (or `.gemini/settings.json` in a project):

```json
{
  "mcpServers": {
    "b123d-print": { "command": "uvx", "args": ["--from", "<b123d-print>", "b123d-print-mcp", "--workspace", "/Users/you/parts"] }
  }
}
```

### Cursor

`~/.cursor/mcp.json` or `.cursor/mcp.json` in the project — same `mcpServers` block as above.

### VS Code (Copilot agent mode)

`.vscode/mcp.json`:

```json
{
  "servers": {
    "b123d-print": { "type": "stdio", "command": "uvx", "args": ["--from", "<b123d-print>", "b123d-print-mcp", "--workspace", "${workspaceFolder}"] }
  }
}
```

### Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.b123d-print]
command = "uvx"
args = ["--from", "<b123d-print>", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
```

### Docker (strongest isolation)

```bash
docker build -t b123d-print-mcp .
# client config: command "docker", args:
#   ["run", "-i", "--rm", "--network", "none", "-v", "/Users/you/parts:/work", "b123d-print-mcp"]
```

## Using it

Start with a prompt: **`design_part_from_photos`** (new part), **`modify_part`**,
**`verify_part`** (review before printing) or **`calibrate_hole_comp`**. In clients without
prompt support, just ask: the server's instructions and the `b123d-print://guide` resource carry the
same rules.

The model first **lists every dimension it read** from your photos and waits for you to
confirm. Then it scaffolds the part, writes it, loops build → render → sections → checks until
the checks pass, and reports size, clearances, hole compensation, warnings and print orientation.

| Tool | What it does |
| --- | --- |
| `list_parts` | parts, bundled examples, settings in effect, sandbox in use |
| `new_part(name, description?, example?)` | scaffold from the template, or copy a bundled example |
| `read_part` / `write_part` | read / replace the script (syntax-checked before saving) |
| `build_part(name, variant?)` | run it: bounding box, volume, validity, Dims, errors |
| `render_preview(name, variant?, parts?)` | 6-view PNG; `parts="assembly"` shows the fit |
| `section(name, plane, at, ...)` | colored cross-section PNG, `XY`/`XZ`/`YZ` |
| `check(name, variant?)` | validity, overlap, overhang, wall, probe checks |
| `export(name, variant?, formats?)` | to `parts/<name>/out/`: any of `step,stl,3mf,png` (default: your `formats` setting) |

### Without MCP (any agent that runs shell commands, or by hand)

```bash
uvx --from <b123d-print> b123d-print init ~/parts     # b123d-print.toml, AGENTS.md, parts/
```

Then, in that folder (with b123d-print installed in its environment, e.g. `uv add <b123d-print>`):

```bash
b123d-print new bracket                  # parts/bracket/bracket.py from the template
b123d-print new coupon --from hole_coupon
uv run parts/bracket/bracket.py     # or: b123d-print build bracket
b123d-print check                        # all parts; exit code 1 on failure
```

Agents that read `AGENTS.md` (Codex, Cursor, and others; Claude Code via `@AGENTS.md` in
`CLAUDE.md`) get the workflow from the file `b123d-print init` writes.

## A part script

```python
from dataclasses import dataclass
from build123d import Align, Box, Cylinder, Mode, Part
from b123d_print import View, Wall, hole_comp

BED = (Align.CENTER, Align.CENTER, Align.MIN)

@dataclass(frozen=True)
class Dims:                      # every dimension named, in mm, with its source
    W: float = 30.0              # typed measurement
    H: float = 8.0
    HOLE_D: float = 3.4          # M3 clearance, target printed size
    CBORE_D: float = 6.5
    CBORE_DEPTH: float = 3.0
    HOLE_COMP: float = hole_comp(__file__)   # from YOUR config, default 0

VARIANTS = {"": {}, "wide": dict(W=40.0)}   # overrides only

def build(d: Dims) -> Part:      # print orientation, bed at Z=0
    p = Box(d.W, d.W, d.H, align=BED)
    p -= Cylinder((d.HOLE_D + d.HOLE_COMP) / 2, 50, mode=Mode.PRIVATE)
    p -= Cylinder((d.CBORE_D + d.HOLE_COMP) / 2, d.CBORE_DEPTH, align=BED, mode=Mode.PRIVATE)
    return p

def views(d):                    # sections saved with every export
    return [View("XZ", 0.0, "through the hole")]

def checks(d):                   # how much material is left around the counterbore?
    return [Wall("", "XY", d.CBORE_DEPTH / 2, near=(0, 0), radius=d.W, label="around the counterbore")]

if __name__ == "__main__":
    from b123d_print import run
    run(__file__)
```

Optional `assembly(d)` returns the parts in assembled position plus stand-ins for what they
mate with (a PCB, a sensor); the overlap check makes sure nothing printed hits them. See
`esp_ir_blaster` and `tuya_motion_sensor_outdoor_case` for multi-part designs.

## Settings and hole compensation

FDM printers print small holes undersize, by an amount that depends on printer, nozzle,
material and slicer. b123d-print never assumes a value: `hole_comp` defaults to **0**. Print the
`hole_coupon` example, measure the holes, and set the average error:

```toml
# ~/.config/b123d-print/config.toml       (`b123d-print config` shows what is in effect)
[print]
hole_comp = 0.4      # mm added to hole diameters when cutting
clearance = 0.2      # default mating gap
min_wall = 0.8       # Wall checks fail below this unless they set their own limit
max_overhang = 45    # degrees from vertical
formats = ["step", "stl", "3mf", "png"]   # what export writes (default: all four)
```

| Format | For |
| --- | --- |
| `.py` (always) | the parametric source: change a `Dims` value, rebuild |
| `step` | editing in other CAD (Onshape, Fusion, FreeCAD, SolidWorks): a solid without feature history |
| `stl` | any slicer |
| `3mf` | slicers that read it (Bambu Studio, OrcaSlicer, PrusaSlicer); keeps units |
| `png` | 6-view preview and the section views from `views(d)` |

Per run: `b123d-print build part --formats 3mf,png`, `uv run part.py --formats step`, or
`formats="3mf"` on the MCP `export` tool. `B123D_PRINT_FORMATS=3mf,png` works too.

A workspace `b123d-print.toml` overrides the user config; `B123D_PRINT_HOLE_COMP` etc. override both.

## The checks

- **overlap** — intersection volume between every pair of `assembly(d)` parts; > 0.01 mm³ fails.
- **overhang** — downward faces in print orientation, angle from vertical (wall = 0°, ceiling =
  90°); > 45° is reported, the bed face is ignored, flat ceilings are marked `bridge`.
  `Overhang(part, fail=True)` for parts that must print without supports.
- **wall** — thinnest material in a cross-section, optionally only around one cut: measured
  across the wall along the surface normal and between separate boundaries (hole to edge),
  ignoring the tips of ordinary corners.
- **probe** — material must be present (or absent) in a small box: "the roof is closed".
- **valid** — every printable part is a valid, non-empty solid.

## Sandbox

Part scripts are written by a model, so `b123d-print-mcp` runs each one in a separate process:

| Platform | Isolation |
| --- | --- |
| macOS | `sandbox-exec` profile: no network, no child processes, writes only to the part's `out/` and a scratch folder, home folder unreadable except the workspace |
| Linux with `bwrap` | bubblewrap: no network, read-only system, same writable folders, home hidden |
| Linux without `bwrap`, Windows | process + audit hook only (blocks sockets, subprocesses, ctypes, writes elsewhere) — **install bubblewrap or use Docker** |
| Docker | the container (`--network none`, only `/work` mounted) |

Every build also gets a timeout (default 120 s, `--timeout`) and a CPU limit. The audit hook is
defense in depth, not a boundary by itself. `b123d-print build`/`check` and `uv run part.py` on the
command line are **not** sandboxed: they run your scripts like any Python.

## Development

```bash
uv sync
uv run pytest                       # unit tests
uv run b123d-print check                 # all bundled examples
uv run python tests/mcp_smoke.py    # end to end over MCP stdio, incl. sandbox escapes
```

## Credits and license

b123d-print stands on [build123d](https://github.com/gumyr/build123d) (Apache-2.0),
[OCP](https://github.com/CadQuery/OCP) and [Open CASCADE Technology](https://dev.opencascade.org)
(LGPL-2.1 with exception), [matplotlib](https://matplotlib.org), [NumPy](https://numpy.org) and
the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). See
[THIRD_PARTY.md](THIRD_PARTY.md). b123d-print itself is [MIT](LICENSE).
