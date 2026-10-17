# b123d-print

Design 3D-printable parts with an AI assistant — any assistant. You describe a part (photos,
caliper readings); the model writes a [build123d](https://github.com/gumyr/build123d) Python
script; b123d-print builds it in a sandbox, renders it, cuts cross-sections, runs print checks,
and exports the formats you pick: STEP, STL, 3MF, PNG.

| | |
| --- | --- |
| ![ESP IR blaster box, assembly with board stand-ins](images/esp_ir_blaster_assembly.png) | ![Section through the LED: base, lid, board and LED stand-ins](images/esp_ir_blaster_xz0.6.png) |
| *Two-part box for an IR transceiver board, with the board stand-ins* | *Section through the LED: lid cone, board, clearances* |
| ![Outdoor motion sensor case, arch cover](images/tuya_motion_sensor_outdoor_case_arch_assembly.png) | ![Wall plate section through the counterbores](images/plate_2gang_to_1gang_xy2.45.png) |
| *Outdoor sensor case: dovetail back plate + support-free cover* | *Wall plate: section just past the face, where the wall check looks* |

**Scope: parts for FDM 3D printing, nothing else.** Everything is built around a printed part:
print orientation with the bed at Z=0, hole compensation, mating clearance, and overhang,
wall-thickness and overlap checks. It is not a general CAD framework.

## What's in it

- **`b123d-print` package + CLI** — export, 6-view renders, colored multi-part cross-sections,
  and print checks: **overlap** between mating parts, **overhang** in print orientation, **wall
  thickness** around cuts, **probes** ("is the roof closed?"). See [CLI and Python](getting-started/cli.md).
- **`b123d-print-mcp`** — an [MCP](https://modelcontextprotocol.io) server, so it works from
  Claude Desktop, Claude Code, Gemini CLI, Cursor, VS Code, Codex and other MCP clients. Part
  scripts are model-written code: they run in a [sandbox](using/sandbox.md) with a timeout and
  no network.
- **The workflow, model-neutral** — [MCP prompts](using/tools.md#prompts) plus an
  [`AGENTS.md`](scripts/rules.md) any agent can read. The rules come from real prints; one exists
  because a part broke through a 0.05 mm skin that no render showed.
- **[Examples](scripts/examples.md)** — four parts designed this way and printed, plus a hole
  calibration coupon.

## Where to start

- New here: [Quick start](getting-started/quick-start.md), then
  [connect your MCP client](getting-started/mcp-clients.md).
- Writing or reviewing part scripts: [The part script](scripts/convention.md) and the
  [Checks API](scripts/checks-api.md).
- Something wrong: [Troubleshooting](troubleshooting.md).

## Platforms and status

**0.x — early.** The part-script convention may still change. CI tests macOS and Ubuntu, the
built package via `uvx`, and the Docker image on every push. Windows is untested: the MCP
server should run there without the OS sandbox; [Docker](getting-started/docker.md) is the safe
route.
