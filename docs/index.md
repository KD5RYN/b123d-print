# b123d-print

Design 3D-printable parts with an AI assistant — any assistant. Describe a part (photos,
caliper readings) and the assistant designs it, looks at it from every side, checks it for
printing problems and saves files for your slicer (3MF, STL) or other CAD (STEP). Under the
hood every part is a short [build123d](https://github.com/gumyr/build123d) Python script, so
every dimension stays editable.

| | |
| --- | --- |
| ![ESP IR blaster box, assembly with board stand-ins](images/esp_ir_blaster_assembly.png) | ![Section through the LED: base, lid, board and LED stand-ins](images/esp_ir_blaster_xz0.6.png) |
| *Two-part box for an IR transceiver board, with the board stand-ins* | *Section through the LED: lid cone, board, clearances* |
| ![Outdoor motion sensor case, arch cover](images/tuya_motion_sensor_outdoor_case_arch_assembly.png) | ![Wall plate section through the counterbores](images/plate_2gang_to_1gang_xy2.45.png) |
| *Outdoor sensor case: dovetail back plate + support-free cover* | *Wall plate: section just past the face, where the wall check looks* |

## Get started in 2 minutes

The MCP server is a plug-in that gives your AI assistant CAD tools. It runs on your own
computer. The easy way: paste this into your AI assistant (Claude Code, Claude Desktop, Cursor,
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

It will probably ask to run a few commands: that is expected. Prefer to do it yourself, or want
to see what it does? [Quick start](getting-started/quick-start.md) has the three manual steps.
Then ask: *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."*

**Scope: parts for FDM 3D printing, nothing else.** Everything is built around a printed part:
print orientation with the bed at Z=0, hole compensation, mating clearance, calibration coupons,
and print checks built on [sourced FDM design rules](BEST_PRACTICES.md). It is not a general CAD
framework.

## What's in it

- **`b123d-print` package + CLI** — export, 6-view renders, colored multi-part cross-sections,
  and print checks: **overlap** between mating parts, **overhang** and **bridges** in print
  orientation, **thin features** and **wall thickness** around cuts, **holes** (round tops that
  sag), **bed-edge** fillets, **gaps** between moving parts, **probes** ("is the roof closed?").
  See [The checks](using/checks.md) and [CLI and Python](getting-started/cli.md).
- **`b123d-print-mcp`** — an [MCP](https://modelcontextprotocol.io) server, so it works from
  Claude Desktop, Claude Code, Gemini CLI, Cursor, VS Code, Codex and other MCP clients. Part
  scripts are model-written code: they run in a [sandbox](using/sandbox.md) with a timeout and
  no network.
- **[`compare`](using/compare.md)** — measure a part against a reference STL, 3MF or STEP: size,
  volume and surface differences, a 0–100 score, pass/fail, and a deviation view.
- **The workflow, model-neutral** — [MCP prompts](using/tools.md#prompts) plus an
  [`AGENTS.md`](scripts/rules.md) any agent can read. The rules come from real prints; one exists
  because a part broke through a 0.05 mm skin that no render showed.
- **[Examples](scripts/examples.md)** — four parts designed this way and printed, plus
  calibration coupons for holes, fits, and overhangs and bridges.

## Where to start

- New here: [Quick start](getting-started/quick-start.md); other assistants:
  [connect your MCP client](getting-started/mcp-clients.md).
- Parts on a home server, many agents sharing one server, or Docker:
  [Advanced: run it on another machine](advanced/index.md).
- Writing or reviewing part scripts: [The part script](scripts/convention.md) and the
  [Checks API](scripts/checks-api.md).
- Something wrong: [Troubleshooting](troubleshooting.md).

## Platforms and status

**0.x — early.** The part-script convention may still change. CI tests macOS and Ubuntu, the
built package via `uvx`, and the Docker image on every push. Windows is untested: the MCP
server should run there without the OS sandbox; [Docker](getting-started/docker.md) is the safe
route.
