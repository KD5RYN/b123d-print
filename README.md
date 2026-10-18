# b123d-print

[![PyPI](https://img.shields.io/pypi/v/b123d-print.svg)](https://pypi.org/project/b123d-print/)
[![CI](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml/badge.svg)](https://github.com/KD5RYN/b123d-print/actions/workflows/ci.yml)
[![Docs](https://github.com/KD5RYN/b123d-print/actions/workflows/docs.yml/badge.svg)](https://kd5ryn.github.io/b123d-print/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Design 3D-printable parts with an AI assistant — any assistant. Describe a part (photos,
caliper readings) and the assistant designs it, looks at it from every side, checks it for
printing problems and saves files for your slicer (3MF, STL) or other CAD (STEP). Under the
hood every part is a short [build123d](https://github.com/gumyr/build123d) Python script, so
every dimension stays editable.

**Documentation: https://kd5ryn.github.io/b123d-print/**

| | |
| --- | --- |
| ![ESP IR blaster box, assembly with board stand-ins](docs/images/esp_ir_blaster_assembly.png) | ![Section through the LED: base, lid, board and LED stand-ins](docs/images/esp_ir_blaster_xz0.6.png) |
| *Two-part box for an IR transceiver board, with the board stand-ins* | *Section through the LED: lid cone, board, clearances* |
| ![Outdoor motion sensor case, arch cover](docs/images/tuya_motion_sensor_outdoor_case_arch_assembly.png) | ![Wall plate section through the counterbores](docs/images/plate_2gang_to_1gang_xy2.45.png) |
| *Outdoor sensor case: dovetail back plate + support-free cover* | *Wall plate: section just past the face, where the wall check looks* |

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

**Then ask:** *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."* The files land in
your parts folder under `parts/<name>/out/`, ready for your slicer. The first start downloads a
few hundred MB and can take a few minutes ([Troubleshooting](https://kd5ryn.github.io/b123d-print/troubleshooting/)).
The assistant checks its work by looking at its renders, so use a client that passes tool
images to the model (Claude Desktop and Claude Code do).

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
- **The workflow, model-neutral** — MCP prompts plus an [`AGENTS.md`](AGENTS.md) any agent can
  read. The rules come from real prints; one exists because a part broke through a 0.05 mm skin
  that no render showed.
- **Examples** — four parts designed this way and printed, plus calibration coupons for holes,
  fits, and overhangs and bridges, in
  [`src/b123d_print/examples/`](src/b123d_print/examples/).

## Advanced: run it on another machine

Not needed for most people. To keep the parts on a home server and design from a laptop, use
[SSH](https://kd5ryn.github.io/b123d-print/getting-started/ssh/); for many agents sharing one server (eval runs, a team),
[HTTP](https://kd5ryn.github.io/b123d-print/getting-started/http/) with a named token per tool; for the strongest isolation,
or on Windows, [Docker](https://kd5ryn.github.io/b123d-print/getting-started/docker/).
[Which mode?](https://kd5ryn.github.io/b123d-print/advanced/) compares them.

## Documentation

| | |
| --- | --- |
| **Getting started** | [Quick start](https://kd5ryn.github.io/b123d-print/getting-started/quick-start/) · [MCP clients](https://kd5ryn.github.io/b123d-print/getting-started/mcp-clients/) (Claude Desktop, Claude Code, Gemini CLI, Cursor, VS Code, Codex) · [CLI and Python](https://kd5ryn.github.io/b123d-print/getting-started/cli/) |
| **Advanced** | [Which mode?](https://kd5ryn.github.io/b123d-print/advanced/) · [Remote over SSH](https://kd5ryn.github.io/b123d-print/getting-started/ssh/) · [Over the network (HTTP)](https://kd5ryn.github.io/b123d-print/getting-started/http/) · [Docker](https://kd5ryn.github.io/b123d-print/getting-started/docker/) |
| **Using it** | [How a session goes](https://kd5ryn.github.io/b123d-print/using/workflow/) · [MCP tools and prompts](https://kd5ryn.github.io/b123d-print/using/tools/) · [Output formats](https://kd5ryn.github.io/b123d-print/using/formats/) · [Settings](https://kd5ryn.github.io/b123d-print/using/settings/) · [Hole compensation](https://kd5ryn.github.io/b123d-print/using/hole-compensation/) · [Printer profiles](https://kd5ryn.github.io/b123d-print/using/printer-profiles/) · [The checks](https://kd5ryn.github.io/b123d-print/using/checks/) · [Sandbox](https://kd5ryn.github.io/b123d-print/using/sandbox/) · [Comparing parts](https://kd5ryn.github.io/b123d-print/using/compare/) |
| **Part scripts** | [The part script](https://kd5ryn.github.io/b123d-print/scripts/convention/) · [Checks API](https://kd5ryn.github.io/b123d-print/scripts/checks-api/) · [Examples](https://kd5ryn.github.io/b123d-print/scripts/examples/) · [Workflow rules](https://kd5ryn.github.io/b123d-print/scripts/rules/) · [Design rules (sourced)](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) |
| **More** | [Reference](https://kd5ryn.github.io/b123d-print/reference/) · [Updating](https://kd5ryn.github.io/b123d-print/updating/) · [Troubleshooting](https://kd5ryn.github.io/b123d-print/troubleshooting/) · [Contributing](CONTRIBUTING.md) · [Agent evals](https://kd5ryn.github.io/b123d-print/contributing/evals/) · [Credits and licenses](https://kd5ryn.github.io/b123d-print/credits/) |

## Status

**0.x — early.** The part-script convention may still change. CI tests macOS and Ubuntu, the
built package via `uvx`, and the Docker image on every push. Windows is untested; Docker is the
safe route there.

## Credits and license

b123d-print is a thin layer over [build123d](https://github.com/gumyr/build123d),
[Open CASCADE Technology](https://dev.opencascade.org) (via [OCP](https://github.com/CadQuery/OCP)),
[lib3mf](https://github.com/3MFConsortium/lib3mf), [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)'s
printer data, [matplotlib](https://matplotlib.org), [NumPy](https://numpy.org), the
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and [uv](https://github.com/astral-sh/uv).
Details and redistribution notes: [THIRD_PARTY.md](THIRD_PARTY.md).

[MIT](LICENSE) © KD5RYN and contributors.
