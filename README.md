# b123d-print

<!-- mcp-name: io.github.KD5RYN/b123d-print -->

[![PyPI](https://img.shields.io/pypi/v/b123d-print.svg)](https://pypi.org/project/b123d-print/)
[![CI](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml/badge.svg)](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml)
[![Docs](https://github.com/KD5RYN/b123d-print/actions/workflows/docs.yml/badge.svg)](https://kd5ryn.github.io/b123d-print/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Vibe CAD for 3D printing.** Tell your AI assistant what you need, in plain words, with a
photo and a few caliper readings. It designs the part, looks at it from every side, checks it
for printing problems and hands you a file for your slicer. No CAD skills needed, and it works
with any assistant that supports MCP: Claude, Gemini CLI, Cursor, VS Code Copilot, Codex and
[more](<https://kd5ryn.github.io/b123d-print/getting-started/mcp-clients/#which-clients>) (which clients, and how to connect each).

## What you can make

Ask the way you would ask a friend who owns calipers and a CAD program. These were designed
this way, and printed:

- *"A box for this IR blaster board: the LED pointing out the top, a screw-on lid, two tabs to
  mount it on the wall."* A two-part case, checked against a stand-in of the board so it fits.
- *"An outdoor case for this motion sensor. It should slide off a wall plate and keep the rain
  out."* Dovetail rails, a click-in detent, a drain slot, and a cover that prints without
  supports.
- *"An adapter plate: 2-gang box behind, 1-gang smart switch in front."* Counterbored screw
  holes, and a wall check added after the first print broke through a 0.05 mm skin no render
  showed.

Or [remix](https://kd5ryn.github.io/b123d-print/using/remix/) a model you downloaded (STL, 3MF or STEP) and change it:

- *"Here's an L bracket STL I downloaded: turn its two mounting holes into slots and add
  gussets."* The original is loaded as a solid and changed, the checks tell the original's
  flaws from new ones, and a before/after view shows exactly what moved. (A demo for the docs,
  not printed yet.)

Before a long print, test the fit with a [fit-test template](https://kd5ryn.github.io/b123d-print/using/templates/): a thin, quick print
cut from the real part.

- *"Make a fit-test template of the mounting face so I can check the hole pattern."* The
  assistant shows you the face in red, asks you to confirm, and gives you a 1.2 mm plate with the
  part's exact holes: minutes to print instead of hours.

Measuring something big, curved or awkward? [Measuring for the AI](https://kd5ryn.github.io/b123d-print/using/measuring/) shows which tool
to use, how to photograph it with a scale, and a copy-paste measurement sheet and table of
offsets (stations along a datum) that hand the numbers over without ambiguity.

And the everyday things: a spacer, a knob, a bracket, a cable clip, a replacement for a broken
part you can measure. Then keep talking to it: *"make it 5 mm taller"*, *"add a hole for an M4
screw"*, *"the lid is too tight"*. Every dimension stays a named number in a short
[build123d](https://github.com/gumyr/build123d) script, so each change is exact, and you get
STEP files to keep editing in other CAD if you want.

| | |
| --- | --- |
| ![ESP IR blaster box, assembly with board stand-ins](docs/images/esp_ir_blaster_assembly.png) | ![Section through the LED: base, lid, board and LED stand-ins](docs/images/esp_ir_blaster_xz0.6.png) |
| *Two-part box for an IR transceiver board, with the board stand-ins* | *Section through the LED: lid cone, board, clearances* |
| ![Outdoor motion sensor case, arch cover](docs/images/tuya_motion_sensor_outdoor_case_arch_assembly.png) | ![Wall plate section through the counterbores](docs/images/plate_2gang_to_1gang_xy2.45.png) |
| *Outdoor sensor case: dovetail back plate + support-free cover* | *Wall plate: section just past the face, where the wall check looks* |
| ![Remix: the downloaded L bracket and the version with slots and gussets](docs/images/remix_bracket_before_after.png) | ![Remix: the original colored where the remix differs](docs/images/remix_bracket_vs_original.png) |
| *Remix: a downloaded bracket, before and after* | *Where the remix differs: red cut, grey added* |

**Documentation: https://kd5ryn.github.io/b123d-print/**

## Get started in 2 minutes

b123d-print's MCP server is a plug-in that gives your AI assistant CAD tools. It runs on your
own computer.

**The easy way:** paste this into your AI assistant (Claude Code, Claude Desktop, Cursor,
Gemini CLI, Codex, …):

```text
Install the b123d-print MCP server for me. It runs with
`uvx --from b123d-print b123d-print-mcp --workspace <folder>`
where <folder> is a folder for my parts, such as ~/parts.
Install uv first if it is missing (https://docs.astral.sh/uv/).
Add the server to your MCP settings, tell me when to restart you,
and after the restart check that its tools (list_parts, new_part,
build_part, ...) are available.
```

It will probably ask to run a few commands (to install uv and add the server): that is expected.

**By hand:**

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), which fetches Python
   and everything else b123d-print needs.
2. Add the server. Claude Code:

   ```bash
   claude mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp --workspace ~/parts
   ```

   Or install the Claude Code plugin (server + skill) in one step:

   ```text
   /plugin install b123d-print --marketplace KD5RYN/b123d-print
   ```

   Claude Desktop (Settings → Developer → Edit Config):

   ```json
   {
     "mcpServers": {
       "b123d-print": {
         "command": "uvx",
         "args": ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
       }
     }
   }
   ```

   Cursor, VS Code, Gemini CLI, Codex and others: [Connect your MCP client](https://kd5ryn.github.io/b123d-print/getting-started/mcp-clients/).
3. Restart the assistant.

**Tell it your printer:** ask *"Set up b123d-print for my printer"* (the `setup_workspace`
prompt; `b123d-print setup` in a terminal): printer, material, export formats, style, then the
calibration coupons.

**Then ask:** *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."* The files land in
your parts folder under `parts/<name>/out/`; the file for your slicer is in `out/print/`
([what to save](https://kd5ryn.github.io/b123d-print/using/what-to-save/)). The first start downloads a
few hundred MB and can take a few minutes ([Troubleshooting](https://kd5ryn.github.io/b123d-print/troubleshooting/)).
The assistant checks its work by looking at its renders, so use a client that passes tool
images to the model (Claude Desktop and Claude Code do).

**Follow a whole session:** [your first part, a shelf bracket](https://kd5ryn.github.io/b123d-print/tutorials/first-bracket/)
from install to print, and [remix a downloaded STL](https://kd5ryn.github.io/b123d-print/tutorials/remix-stl/).

**Scope: parts for FDM 3D printing, nothing else.** Everything is built around a printed part:
print orientation with the bed at Z=0, hole compensation, mating clearance, calibration coupons,
and print checks built on [sourced FDM design rules](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/).
It is not a general CAD framework.

## What's in it

- **`b123d-print` package + CLI** — export, 6-view renders, colored multi-part cross-sections,
  and print checks: **overlap** between mating parts, **overhang** and **bridges** in print
  orientation, **thin features** and **wall thickness** around cuts, **holes** (round tops that
  sag), **bed-edge** fillets, **gaps** between moving parts, **probes** ("is the roof closed?").
- **`b123d-print-mcp`** — an [MCP](https://modelcontextprotocol.io) server, so it works from
  Claude Desktop, Claude Code, Gemini CLI, Cursor, VS Code, Codex and other MCP clients. Part
  scripts are model-written code: they run in a sandbox with a timeout and no network.
- **`compare`** — measure a part against a reference STL, 3MF or STEP: size, volume and surface
  differences, a 0–100 score, pass/fail, and a deviation view
  ([comparing parts](https://kd5ryn.github.io/b123d-print/using/compare/)).
- **Remix** — start from someone else's STL, 3MF or STEP: `import_model` makes a mesh a solid
  (coplanar triangles merged), the checks tell the original's problems from the ones the remix
  added, and a before/after view shows the change
  ([remixing a part](https://kd5ryn.github.io/b123d-print/using/remix/)).
- **Fit-test templates** — a quick thin print of a face, a slice or a region of the real part
  (same holes and clearances) to check the hole pattern and the fits before the full print
  ([fit-test templates](https://kd5ryn.github.io/b123d-print/using/templates/)).
- **Design review** — after the print checks pass, the assistant reviews the part for a style
  you pick (functional, modern, least cost, rugged/outdoor, soft/handheld, structural/load-bearing,
  organic/natural, decorative/vase):
  rough filament and time estimates, supports, edge treatment, layer steps, water traps, inside
  corners and walls, and concrete suggestions
  from [sourced design rules](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/). It changes
  nothing without your OK ([design review](https://kd5ryn.github.io/b123d-print/using/design-review/)).
- **The workflow, model-neutral** — MCP prompts plus an [`AGENTS.md`](AGENTS.md) any agent can
  read. The rules come from real prints; one exists because a part broke through a 0.05 mm skin
  that no render showed.
- **Examples** — four parts designed this way and printed, plus calibration coupons for holes,
  fits, and overhangs and bridges, in
  [`src/b123d_print/examples/`](src/b123d_print/examples/).

## Advanced: run it on another machine

Not needed for most people. To keep the parts on a home server and design from a laptop, use
[SSH](https://kd5ryn.github.io/b123d-print/getting-started/ssh/); for many agents sharing one server (eval runs, a team),
[HTTP](https://kd5ryn.github.io/b123d-print/getting-started/http/) with a named token per tool; for the strongest isolation
(also on Windows), [Docker](https://kd5ryn.github.io/b123d-print/getting-started/docker/).
[Which mode?](https://kd5ryn.github.io/b123d-print/advanced/) compares them.

## Documentation

| | |
| --- | --- |
| **Start here** | [Tutorial: your first part](https://kd5ryn.github.io/b123d-print/tutorials/first-bracket/) · [Tutorial: remix a downloaded STL](https://kd5ryn.github.io/b123d-print/tutorials/remix-stl/) |
| **Getting started** | [Quick start](https://kd5ryn.github.io/b123d-print/getting-started/quick-start/) · [MCP clients](https://kd5ryn.github.io/b123d-print/getting-started/mcp-clients/) (Claude Desktop, Claude Code, claude.ai, ChatGPT, Gemini CLI, Antigravity, OpenCode, Qwen Code, pi, Cursor, VS Code, Codex, Grok, Windsurf, Zed, LM Studio) · [CLI and Python](https://kd5ryn.github.io/b123d-print/getting-started/cli/) |
| **Advanced** | [Which mode?](https://kd5ryn.github.io/b123d-print/advanced/) · [Remote over SSH](https://kd5ryn.github.io/b123d-print/getting-started/ssh/) · [Over the network (HTTP)](https://kd5ryn.github.io/b123d-print/getting-started/http/) · [Docker](https://kd5ryn.github.io/b123d-print/getting-started/docker/) |
| **Using it** | [How a session goes](https://kd5ryn.github.io/b123d-print/using/workflow/) · [Measuring for the AI](https://kd5ryn.github.io/b123d-print/using/measuring/) · [MCP tools and prompts](https://kd5ryn.github.io/b123d-print/using/tools/) · [Output formats](https://kd5ryn.github.io/b123d-print/using/formats/) · [From part to print](https://kd5ryn.github.io/b123d-print/using/slicing/) · [Settings](https://kd5ryn.github.io/b123d-print/using/settings/) · [Hole compensation](https://kd5ryn.github.io/b123d-print/using/hole-compensation/) · [Printer profiles](https://kd5ryn.github.io/b123d-print/using/printer-profiles/) · [The checks](https://kd5ryn.github.io/b123d-print/using/checks/) · [Sandbox](https://kd5ryn.github.io/b123d-print/using/sandbox/) · [Comparing parts](https://kd5ryn.github.io/b123d-print/using/compare/) · [Remixing a part](https://kd5ryn.github.io/b123d-print/using/remix/) · [Fit-test templates](https://kd5ryn.github.io/b123d-print/using/templates/) |
| **Part scripts** | [The part script](https://kd5ryn.github.io/b123d-print/scripts/convention/) · [Checks API](https://kd5ryn.github.io/b123d-print/scripts/checks-api/) · [Examples](https://kd5ryn.github.io/b123d-print/scripts/examples/) · [Workflow rules](https://kd5ryn.github.io/b123d-print/scripts/rules/) · [Design rules (sourced)](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) |
| **More** | [FAQ](https://kd5ryn.github.io/b123d-print/faq/) · [Reference](https://kd5ryn.github.io/b123d-print/reference/) · [Updating](https://kd5ryn.github.io/b123d-print/updating/) · [Troubleshooting](https://kd5ryn.github.io/b123d-print/troubleshooting/) · [Contributing](CONTRIBUTING.md) · [Agent evals](https://kd5ryn.github.io/b123d-print/contributing/evals/) · [Credits and licenses](https://kd5ryn.github.io/b123d-print/credits/) |

## Status

**0.x — early.** The part-script convention may still change. CI tests macOS, Ubuntu and
Windows, the built package via `uvx`, and the Docker image on every push. On Windows the server
runs natively for local use, but without an OS sandbox (process isolation and an audit hook
only); use WSL2 or Docker for isolation. SSH mode's server side is macOS and Linux only; Windows
works as an SSH or HTTP client. [Platforms and status](https://kd5ryn.github.io/b123d-print/#platforms-and-status).

## Credits and license

b123d-print is a thin layer over [build123d](https://github.com/gumyr/build123d),
[Open CASCADE Technology](https://dev.opencascade.org) (via [OCP](https://github.com/CadQuery/OCP)),
[lib3mf](https://github.com/3MFConsortium/lib3mf), [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)'s
printer data, [bd_warehouse](https://github.com/gumyr/bd_warehouse) and
[py_gearworks](https://github.com/GarryBGoode/py_gearworks) for part scripts,
[matplotlib](https://matplotlib.org), [NumPy](https://numpy.org), the
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and [uv](https://github.com/astral-sh/uv).
Details and redistribution notes: [THIRD_PARTY.md](THIRD_PARTY.md).

[MIT](LICENSE) © KD5RYN and contributors.
