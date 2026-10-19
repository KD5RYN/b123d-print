# b123d-print for Claude

**Vibe CAD for 3D printing.** Describe a part — with photos and caliper readings if you have them — and
Claude designs it as a parametric [build123d](https://github.com/gumyr/build123d) script, checks that
it will print (overhangs, thin walls, holes, bridges, fit on your printer's bed), shows you renders and
cross-sections, and exports STEP, STL and 3MF files for your slicer. It can also remix a part you
downloaded (STL, 3MF or STEP), make quick fit-test templates, and review a design for a chosen style.

This plugin adds two things to Claude:

- the **b123d-print MCP server** (the design, check and export tools), and
- the **cad-parts skill**, which tells Claude the workflow: confirm dimensions before modeling, name
  every dimension, verify with renders, sections and checks before reporting.

## Install

```text
/plugin install b123d-print --marketplace KD5RYN/b123d-print
```

Then ask, for example: *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."* The files land in
`parts/<name>/` in your project folder.

Requires [uv](https://docs.astral.sh/uv/) on your machine.

## What it runs, downloads and sends

- **Runs** `uvx --from b123d-print==<version> b123d-print-mcp`: uv downloads that exact version of the
  open-source [`b123d-print`](https://pypi.org/project/b123d-print/) package and its dependencies
  (build123d, OpenCascade, NumPy, matplotlib, the MCP SDK) from PyPI once, then starts it as a local
  MCP server over stdio. The version is pinned in `.mcp.json`.
- **Writes** part scripts and exported files (STEP, STL, 3MF, PNG previews) into `parts/` in your
  project folder, and a `b123d-print.toml` settings file there.
- **Runs part scripts written by Claude** in a separate, sandboxed process with a time limit (macOS:
  `sandbox-exec`; Linux: bubblewrap when installed; Windows: a Job Object with limits only). Where
  the OS sandbox is available, scripts have no network access and can only write to the part's
  output folder. For the strongest isolation, use the Docker image described in the docs.
- **Sends nothing anywhere.** The server has no telemetry and makes no network connections of its own.
  The only network use is uv downloading the package from PyPI. Remote modes (a shared server over
  HTTP or SSH) exist in b123d-print but are not used by this plugin unless you set them up yourself.

## More

Full documentation: https://kd5ryn.github.io/b123d-print/ · Source and issues:
https://github.com/KD5RYN/b123d-print

MIT License © KD5RYN and contributors. Built on build123d, Open CASCADE Technology (via OCP), the MCP
Python SDK and uv; see the project's credits page.
