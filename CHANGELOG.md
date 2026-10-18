# Changelog

## 0.2.1 — unreleased

**Native Windows support for local use.** The MCP server and the CLI run on Windows 10/11 with
`uvx`, like on macOS and Linux; CI now tests Windows too (unit tests, MCP end to end over stdio
and HTTP).
- Part scripts run in a separate process inside a Job Object: a CPU-time limit, and on a timeout
  (or when the server stops) the worker and anything it started are killed together. There is
  **no OS sandbox** on Windows: process isolation and the audit hook only. Use WSL2 (with
  bubblewrap) or Docker when you need isolation; `list_parts` says which you have.
- The build limit shared by all server processes works on Windows too (`msvcrt` file locks).
- The audit hook also blocks `_winapi.CreateProcess` and registry writes, and compares paths
  case-insensitively on Windows.
- HTTP mode stops gracefully on Ctrl-Break (Windows has no SIGTERM); SIGHUP reload is POSIX only.
- Windows as an SSH client: `--ssh` keeps backslashes in paths (`ssh -i C:\Users\...`), and
  `pull`/`push` work with the built-in `ssh.exe`. SSH mode's server side stays macOS/Linux.
- CLI output no longer fails on a console that is not UTF-8 (characters it cannot show become `?`).

## 0.2.0 — 2026-10-17

The part-script convention is unchanged from 0.1.0; existing scripts keep working.

**Remixing an existing model**
- `import_model("ref/bracket.stl")` loads an STL, 3MF or STEP as a solid to change. Meshes are
  welded, small gaps closed, triangles oriented, and coplanar triangles merged into planar
  faces (curves stay faceted); units are checked (`scale="inch"`), meshes over `max_triangles`
  (new setting, default 50,000) are refused with advice to simplify, the conversion is cached.
- Reference files go to `parts/<part>/ref/`: `b123d-print push` over SSH, the `upload_reference`
  tool (base64, or a signed upload link for `curl -fT`) over HTTP.
- New tools `describe_model` and `before_after`, prompt `remix_part`, command `b123d-print to-step`.
- The checks also run on the original: findings it already had are labeled *inherited from the
  original* and never fail the check. Exports of a remix add before/after and deviation images.
- New example `remix_bracket`.

**Faster**
- Tessellation reads triangles by index (rendering and the overhang check on a 9k-face solid:
  20 s -> 1 s each); the thin check slices the triangle mesh on solids with many faces.

**Remote use**
- **SSH mode (recommended for a home server):** MCP over `ssh`, one `authorized_keys` line per
  machine pins the key to the MCP server and its own workspace (`restrict`, forced command).
  `b123d-print setup-ssh` writes the line and the client config; `b123d-print pull` fetches
  exported files; a build limit shared by all sessions.
- **HTTP mode (many agents, evals):** Streamable HTTP with **named tokens** (`b123d-print-mcp token
  add|list|revoke`, each limited to its workspaces, logged by name), per-client workspaces, a
  server-wide build limit, health check, graceful shutdown.
- **Exported files over HTTP** come back as signed, expiring download links (no token, no SSH)
  and as `b123d-print://files/` resources.
- **Docker:** a two-container setup for HTTP — the worker that runs part scripts has no network
  at all; `deploy/compose.yaml` example.

**Checks and design rules**
- Sourced FDM best practices (`docs/BEST_PRACTICES.md`, rule IDs cited by checks and AGENTS.md).
- New checks: thin features (fail below one line width), horizontal holes (teardrop), bridge span
  and one-wall ceilings (`max_bridge`), fillets on bed edges, print-in-place gaps.
- Checks report what they measured; `Wall`/`Probe` can be declared in the assembly frame, so
  flipping a part for printing cannot silently redirect them; a reminder when holes are cut
  with no hole compensation set.
- New calibration prints: `fit_coupon`, `overhang_bridge_coupon`, `hole_coupon` with horizontal
  holes; `b123d-print printer calibrate` stores the results per printer + material.

**Tools**
- `compare`: a part against a reference STL/3MF/STEP (aligned distances, score, deviation view);
  CLI and MCP tool. A repo-only eval harness scores agents against reference parts.
- `export`: `parts=` filter, file count and size, a note when the default formats are used.
- `render_preview`: multi-part builds use `assembly()` or lay parts side by side; image `size=`.
- Optional printer/material profiles (405 printers from OrcaSlicer's library) with a fit check.

**Project**
- Docs site: https://kd5ryn.github.io/b123d-print/ (with drift tests against the code).
- Dependabot and a monthly OrcaSlicer printer-table sync.

## 0.1.0 — 2026-10-17

First release: package + CLI, MCP server (stdio, sandboxed part scripts), print checks (overlap,
overhang, wall, probe), STEP/STL/3MF/PNG export, examples, Docker image, Claude Code plugin.
