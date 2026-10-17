# b123d-print

[![CI](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml/badge.svg)](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Design 3D-printable parts with an AI assistant — any assistant. You describe a part (photos,
caliper readings); the model writes a [build123d](https://github.com/gumyr/build123d) Python
script; b123d-print builds it in a sandbox, renders it, cuts cross-sections, runs print checks,
and exports the formats you pick: STEP, STL, 3MF, PNG.

| | |
| --- | --- |
| ![ESP IR blaster box, assembly with board stand-ins](docs/images/esp_ir_blaster_assembly.png) | ![Section through the LED: base, lid, board and LED stand-ins](docs/images/esp_ir_blaster_xz0.6.png) |
| *Two-part box for an IR transceiver board, with the board stand-ins* | *Section through the LED: lid cone, board, clearances* |
| ![Outdoor motion sensor case, arch cover](docs/images/tuya_motion_sensor_outdoor_case_arch_assembly.png) | ![Wall plate section through the counterbores](docs/images/plate_2gang_to_1gang_xy2.45.png) |
| *Outdoor sensor case: dovetail back plate + support-free cover* | *Wall plate: section just past the face, where the wall check looks* |

**Scope: parts for FDM 3D printing, nothing else.** Everything is built around a printed part:
print orientation with the bed at Z=0, hole compensation, mating clearance, and overhang,
wall-thickness and overlap checks. It is not a general CAD framework.

## What's in it

- **`b123d-print` package + CLI** — export, 6-view renders, colored multi-part cross-sections,
  and print checks: **overlap** between mating parts, **overhang** in print orientation, **wall
  thickness** around cuts, **probes** ("is the roof closed?").
- **`b123d-print-mcp`** — an [MCP](https://modelcontextprotocol.io) server, so it works from
  Claude Desktop, Claude Code, Gemini CLI, Cursor, VS Code, Codex and other MCP clients. Part
  scripts are model-written code: they run in a sandbox with a timeout and no network.
- **The workflow, model-neutral** — MCP prompts plus an [`AGENTS.md`](AGENTS.md) any agent can
  read. The rules come from real prints; one exists because a part broke through a 0.05 mm skin
  that no render showed.
- **Examples** — four parts designed this way and printed, plus a hole calibration coupon, in
  [`src/b123d_print/examples/`](src/b123d_print/examples/).

## Quick start

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It fetches Python 3.12
   and every pinned dependency for you.
2. Add the server to your MCP client — Claude Desktop shown, [others below](#connect-your-mcp-client):

   ```json
   {
     "mcpServers": {
       "b123d-print": {
         "command": "uvx",
         "args": ["--from", "git+https://github.com/KD5RYN/b123d-print", "b123d-print-mcp",
                  "--workspace", "/Users/you/parts"]
       }
     }
   }
   ```

3. Restart the client and ask: *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."*
   Files land in `/Users/you/parts/parts/<name>/out/`.

The first start downloads a few hundred MB (mostly OpenCascade, the geometry kernel) and can
take a few minutes; later starts are fast. See [Troubleshooting](#troubleshooting) if your
client gives up waiting.

> **Images:** `render_preview` and `section` return PNG images. The model can only check its own
> work if your client passes tool-result images to the model. Claude Desktop and Claude Code do;
> check your client's docs for others. Without it the checks still run, but the model designs
> blind — look at the PNGs in `out/` yourself.

## Ways to use it

| Method | When | Sandbox |
| --- | --- | --- |
| **MCP server via `uvx`** | any MCP client; the normal way | yes (macOS; Linux with bubblewrap) |
| **MCP server in Docker** | strongest isolation, or Windows | the container |
| **Claude Code plugin** | Claude Code; adds a skill that points at the workflow | yes |
| **CLI / Python** | agents that run shell commands, or by hand | no — runs your own scripts |

### Connect your MCP client

Every client runs the same command:
`uvx --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --workspace <folder>`.
The **workspace** is the folder that holds your parts (`parts/<name>/<name>.py`); it is created
if missing. Without `--workspace` the server uses `$B123D_PRINT_WORKSPACE`, else the folder the
client starts it in.

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config (`claude_desktop_config.json`): the block in
[Quick start](#quick-start). Always pass `--workspace`. If the server fails with "uvx not
found", use the full path from `which uvx` as `command` (desktop apps don't see your shell's
`PATH`).
</details>

<details>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add b123d-print -- uvx --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --workspace ~/parts
```

Or the plugin (MCP server + skill; uses the project folder as workspace), inside Claude Code:

```text
/plugin marketplace add KD5RYN/b123d-print
/plugin install b123d-print@b123d-print
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

`~/.gemini/settings.json` (or `.gemini/settings.json` in a project):

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/KD5RYN/b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
    }
  }
}
```
</details>

<details>
<summary><b>Cursor</b></summary>

`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project: the same `mcpServers` block as for
Gemini CLI.
</details>

<details>
<summary><b>VS Code (Copilot agent mode)</b></summary>

`.vscode/mcp.json`:

```json
{
  "servers": {
    "b123d-print": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/KD5RYN/b123d-print", "b123d-print-mcp", "--workspace", "${workspaceFolder}"]
    }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b></summary>

`~/.codex/config.toml`:

```toml
[mcp_servers.b123d-print]
command = "uvx"
args = ["--from", "git+https://github.com/KD5RYN/b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
```
</details>

<details>
<summary><b>Other clients</b></summary>

Any client that can start a stdio MCP server: command `uvx`, arguments as above. To pin a
version, use `git+https://github.com/KD5RYN/b123d-print@v0.1.0` once releases exist.
</details>

### Docker

The container is the sandbox: no network, and it sees only the folder you mount.

```bash
git clone https://github.com/KD5RYN/b123d-print && cd b123d-print
```

```bash
docker build -t b123d-print-mcp .
```

Then point your client at Docker instead of `uvx` (Claude Desktop shown):

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--network", "none",
               "-v", "/Users/you/parts:/work", "b123d-print-mcp"]
    }
  }
}
```

- `-i` is required (MCP talks over stdin/stdout); `--rm` removes the container afterwards.
- Your parts and exports appear in the mounted folder (`/Users/you/parts` above). Settings
  (printer, hole compensation) are kept there too, in `.config/b123d-print/`, since the
  container has no lasting home folder.
- On Linux, add `"--user", "1000:1000"` (your `id -u`:`id -g`) so exported files belong to you.
- Released images will also be on GitHub's registry as `ghcr.io/kd5ryn/b123d-print-mcp`.

### CLI and Python (no MCP)

For agents that run shell commands, and for you:

```bash
uv tool install git+https://github.com/KD5RYN/b123d-print
```

```bash
b123d-print init ~/parts && cd ~/parts
```

```bash
b123d-print new bracket
```

Edit `parts/bracket/bracket.py` (or let your agent do it), then:

```bash
b123d-print build bracket --formats 3mf,png
```

```bash
b123d-print check
```

| Command | Does |
| --- | --- |
| `init [dir]` | create a workspace: `b123d-print.toml`, `AGENTS.md`, `parts/` |
| `new <name> [--from <example>]` | scaffold a part from the template or a bundled example |
| `build [parts] [--variant v] [--formats f]` | export + section views, report sizes |
| `check [parts] [-v] [--json]` | run the checks; exit code 1 on any failure |
| `examples` / `list` / `config` | bundled examples / parts in the workspace / settings in effect |

`AGENTS.md` (written by `init`) carries the workflow for agents that read it, such as Codex and
Cursor; for Claude Code put `@AGENTS.md` in `CLAUDE.md`. Running a part script directly also
works: `uv run parts/bracket/bracket.py`. The CLI does **not** sandbox: it runs your scripts
like any Python.

## How a session goes

Start with one of the MCP prompts where your client supports them —
**`design_part_from_photos`**, **`modify_part`**, **`verify_part`**, **`calibrate_hole_comp`** —
or just ask; the server's instructions and the `b123d-print://guide` resource carry the same
rules. An illustrative, shortened exchange:

> **You:** A case for this PIR sensor, mounted on a wall outside. *(photos with calipers)*
>
> **Model:** Dimensions I read: body 69.6 × 24.5 × 19.1 (photo 2, calipers), dome Ø18.6
> (photo 3), dome center about 35.5 from the bottom (estimate). Nothing shows how far the dome
> sticks out. Please confirm or correct before I model.
>
> **You:** Dome sticks out 8. The rest is right.
>
> **Model:** *(new_part, write_part, build_part, render_preview, three sections, check; fixes a
> thin wall the check found, checks again)* Done: 35.1 × 38.8 × 76.6 mm, valid. The sensor gets
> 0.6 mm per side, the dovetail 0.2 per face. Prints on its floor without supports (one flat
> bridge over the groove). Exported 3MF and PNG.

| Tool | What it does |
| --- | --- |
| `list_parts` | parts, bundled examples, settings in effect, sandbox in use |
| `new_part(name, description?, example?)` | scaffold from the template, or copy a bundled example |
| `read_part` / `write_part` | read / replace the script (syntax-checked before saving) |
| `build_part(name, variant?)` | run it: bounding box, volume, validity, dimensions, errors |
| `render_preview(name, variant?, parts?)` | 6-view PNG; `parts="assembly"` shows the fit |
| `section(name, plane, at, ...)` | colored cross-section PNG on `XY`, `XZ` or `YZ` |
| `check(name, variant?)` | validity, overlap, overhang, wall and probe checks |
| `export(name, variant?, formats?)` | files to `parts/<name>/out/` |

## Output formats

| File | For |
| --- | --- |
| `<name>.py` (always) | the parametric source: change a `Dims` value, rebuild everything |
| `.step` | editing in other CAD (Fusion, Onshape, FreeCAD, SolidWorks): an exact solid you can push/pull, fillet and cut, without feature history; changes there don't flow back to the script |
| `.stl` | any slicer |
| `.3mf` | slicers that read it (Bambu Studio, OrcaSlicer, PrusaSlicer); keeps units |
| `.png` | 6-view preview, assembly render, section views |

Pick them in your config (`formats = ["3mf", "png"]`), per run (`--formats step,3mf`), or with
`formats=` on the MCP `export` tool. Default: all four.

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
[`esp_ir_blaster`](src/b123d_print/examples/esp_ir_blaster/esp_ir_blaster.py) and
[`tuya_motion_sensor_outdoor_case`](src/b123d_print/examples/tuya_motion_sensor_outdoor_case/tuya_motion_sensor_outdoor_case.py).
The modeling API itself is documented in the [build123d docs](https://build123d.readthedocs.io).

## Settings and hole compensation

FDM printers print small holes undersize, by an amount that depends on printer, nozzle,
material and slicer. b123d-print never assumes a value: `hole_comp` defaults to **0**.

![Hole calibration coupon](docs/images/hole_coupon.png)

Print the coupon (`new_part("coupon", example="hole_coupon")` over MCP, or
`b123d-print new coupon --from hole_coupon`), measure each hole, and set the average error:

```toml
# ~/.config/b123d-print/config.toml     (`b123d-print config` shows what is in effect)
[print]
hole_comp = 0.4      # mm added to hole diameters when cutting
clearance = 0.2      # default mating gap
min_wall = 0.8       # Wall checks fail below this unless they set their own limit
max_overhang = 45    # degrees from vertical
formats = ["step", "stl", "3mf", "png"]
```

A workspace `b123d-print.toml` overrides the user config; environment variables
(`B123D_PRINT_HOLE_COMP`, `B123D_PRINT_FORMATS`, ...) override both.

## Printer profile (optional)

By default b123d-print is in **generic mode**: no printer assumed, 0.8 mm minimum wall, 45°
overhang limit. If you set your printer, the model also knows its build volume and nozzle:

```bash
b123d-print printer list bambu a1        # search 405 printer models
```

```bash
b123d-print printer use bambu_lab_a1_mini --material petg
```

- Parts must then fit the build volume in print orientation (`fit` check; it fails otherwise).
- Minimum wall becomes 2 line widths of your nozzle; material notes (PLA vs PETG vs ASA …) reach
  the model.
- `b123d-print printer hole-comp 0.4` stores your coupon result for that printer + material.
- `b123d-print printer use generic` goes back. Over MCP: the `use_printer` tool.

Printer dimensions come from [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)'s printer
library (facts only; see [THIRD_PARTY.md](THIRD_PARTY.md)). Not listed, or modified? Add your own
`~/.config/b123d-print/printers/<name>.toml`:

```toml
label = "My Ender 3 with 0.6 nozzle"
bed_x = 220
bed_y = 220
height = 250
nozzle = 0.6
# round_bed = true      # deltas: bed_x is the diameter
# max_overhang = 50
```

Materials work the same way in `materials/` (`label`, `notes`, optional `clearance`).

## The checks

- **overlap** — intersection volume between every pair of `assembly(d)` parts; > 0.01 mm³ fails.
- **overhang** — downward faces in print orientation, angle from vertical (wall 0°, ceiling
  90°); > 45° is reported, the bed face is ignored, flat ceilings are marked `bridge`.
  `Overhang(part, fail=True)` for parts that must print without supports.
- **wall** — thinnest material in a cross-section, optionally only around one cut: across the
  wall along the surface normal, and between separate outlines (hole to edge). Tips of ordinary
  corners don't count as thin; knife edges sharper than about 25° do.
- **fit** — only with a printer profile: the part fits the build volume in print orientation.
- **probe** — material must be present (or absent) in a small box.
- **valid** — every printable part is a valid, non-empty solid.

## Sandbox

| Platform | Isolation |
| --- | --- |
| macOS | `sandbox-exec`: no network, no child processes, writes only to the part's `out/` and a scratch folder, home folder unreadable except the workspace |
| Linux with [bubblewrap](https://github.com/containers/bubblewrap) | no network, read-only system, same writable folders, home hidden |
| Linux without bubblewrap, Windows | separate process + audit hook only — **install bubblewrap, or use Docker** |
| Docker | the container (`--network none`, only the mounted folder) |

Every build also gets a timeout (default 120 s, `--timeout`) and a CPU limit. The audit hook
(blocks sockets, subprocesses, native libraries, writes elsewhere) is defense in depth, not a
boundary on its own.

## Updating

`b123d-print --version` (or the `version` field of the MCP `list_parts` tool) shows what you run.
Releases and what changed: [GitHub releases](https://github.com/KD5RYN/b123d-print/releases).

| Installed with | Update |
| --- | --- |
| `uvx --from git+https://github.com/KD5RYN/b123d-print ...` (MCP clients) | uvx caches the build: run `uvx --refresh --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --help` once, then restart the client |
| a pinned version `...b123d-print@v0.1.0` | change the tag in your client config, restart the client |
| `uv tool install git+https://github.com/KD5RYN/b123d-print` (CLI) | `uv tool install --force git+https://github.com/KD5RYN/b123d-print` |
| Docker | `git pull && docker build -t b123d-print-mcp .` in your clone, restart the client |
| Claude Code plugin | `/plugin marketplace update b123d-print`, then restart Claude Code |

After updating:

- **Workspaces** keep your parts and settings. The workflow text in a workspace's `AGENTS.md`
  is a copy; refresh it with `b123d-print init --update-agents` (MCP clients always get the
  current text from the server).
- **Printer profiles** ship with the package and update with it; your own files in
  `~/.config/b123d-print/` are never touched.
- **Part scripts**: while b123d-print is 0.x the script conventions may change; the release
  notes say when, and `b123d-print check` tells you what breaks.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| First start is very slow, or the client gives up | it is downloading the dependencies; run `uvx --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --help` once in a terminal, then restart the client |
| Client says `uvx` not found | use the full path from `which uvx` as the command |
| Model never looks at the renders | your client doesn't pass tool images to the model; open `out/*.png` yourself |
| `timed out after 120 s` | a slow or endless script; raise `--timeout` if the part is genuinely heavy |
| `blocked in part scripts: ...` | the script tried the network, a subprocess or files outside the workspace; part scripts only need build123d |
| Holes print small | calibrate `hole_comp` with the coupon |
| Linux: sandbox says "audit hook only" | install bubblewrap (`apt install bubblewrap`); on Ubuntu 24.04 unprivileged user namespaces must also be allowed — or use Docker |

## Platforms and status

**0.x — early.** The part-script convention may still change. CI tests macOS and Ubuntu, the
built package via `uvx`, and the Docker image on every push. Windows is untested: the MCP
server should run there without the OS sandbox; Docker is the safe route.

## Contributing

Issues and pull requests are welcome. To work on it:

```bash
git clone https://github.com/KD5RYN/b123d-print && cd b123d-print && uv sync
```

```bash
uv run pytest && uv run b123d-print check && uv run python tests/mcp_smoke.py
```

The printer table is generated: `python tools/sync_orca_printers.py` refreshes
`src/b123d_print/data/printers_orca.json` from OrcaSlicer (records the commit it used).

New checks and example parts should come from something that was actually printed.

## Credits

b123d-print is a thin layer over:

- [build123d](https://github.com/gumyr/build123d) — the Python CAD API every part is written in (Apache-2.0)
- [Open CASCADE Technology](https://dev.opencascade.org), via [OCP](https://github.com/CadQuery/OCP) — the geometry kernel (LGPL-2.1 with exception; bindings Apache-2.0)
- [lib3mf](https://github.com/3MFConsortium/lib3mf) — 3MF export (BSD)
- [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) — printer dimensions for the optional printer profiles (AGPL-3.0; facts only, no files copied)
- [matplotlib](https://matplotlib.org) and [NumPy](https://numpy.org) — renders, sections, check math
- [Model Context Protocol](https://modelcontextprotocol.io) and its [Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT)
- [uv](https://github.com/astral-sh/uv) — packaging and `uvx`

Details and redistribution notes: [THIRD_PARTY.md](THIRD_PARTY.md).

## License

[MIT](LICENSE) © KD5RYN and contributors.
