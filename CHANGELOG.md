# Changelog

## 0.3.1 — 2026-10-18

**Bringing parts home from a remote server.** Over HTTP and SSH the server is a workbench, not
storage; clients now get the whole part back in one step, in the same layout a local install
writes into the project folder (`parts/<name>/<name>.py`, `out/`, `ref/`).
- `download_part(name, variant?, formats?, embed?)` (MCP tool): over HTTP one signed, expiring
  link (no token) to a zip of the whole part, `curl -fLo <name>.zip '<link>'` and unzip it in the
  project folder; also a `b123d-print://download/{workspace}/{part}` resource. Over SSH it gives
  the `b123d-print pull` command; locally it says the files are already there.
- `b123d-print pull` now copies the whole part (script, `out/`, `ref/`) into `parts/<part>/` of
  the project folder (`-o`, default the current folder) instead of only the `out/` files into
  `-o`; new `--variant`. Needs a 0.3.1 server (`ssh-serve` gains `pull --tree`); 0.3.0 clients
  still get what they got before.
- "MCP tools and links only, the server copy is temporary, never ssh/scp": in the descriptions of
  the tools that write files, in their results over HTTP and SSH (and in `check` once it passes),
  in the server's instructions, `AGENTS.md`, the Claude Code skill and the prompts, which end
  remote work with a required step: `download_part`, unzip, check the files are there, report.
- Over HTTP and SSH, results show workspace-relative paths only (also in error tracebacks and
  `list_parts`, which now names the workspace), never the server's own folders.

**Workspace retention (HTTP).** A named workspace nobody has used for 30 days is removed, checked
at startup and hourly and logged by name; never while a request or build for it is in flight.
`--retention-days` / `B123D_PRINT_RETENTION_DAYS` (`0` = never); in `deploy/compose.yaml` and the
new `deploy/.env.example`. The shared root workspace and SSH and local folders are never removed.

**Faster checks on remixes.** Checking a part made from a downloaded mesh (~10,000 triangles) is
several times faster:
- Section outlines no longer use `Wire.order_edges` and `Edge.positions`, which took seconds per
  section on the thousand-edge outlines of mesh-derived solids. A `Wall` check on such a section:
  14 s → 1 s; it also cuts its section once instead of twice.
- `Wall` measurements cast their rays against only the nearby part of the outline first
  (same results; a test compares them with the full cast).
- `ThinFeature` cuts mesh-derived parts from their triangulation from 400 mostly flat faces up
  (was: over 1500 faces).
- The checks on a remix's original are cached in `out/.cache/` (keyed by its geometry, the
  check, the settings and the b123d-print version): after the first `check`, only the remix is
  checked.
- A remix's thin spot that matches none of the original's listed spots is checked against the
  original's geometry, so knife edges the original already had are labeled inherited every time
  (four identical clips tie, and which one a section reports was arbitrary).
- `tools/bench_mesh_checks.py` times `check` on a generated 10,000-triangle remix.

**Parallel checks.** Over MCP (stdio, HTTP incl. the separate worker container, SSH; Windows
too) one `check` runs in up to `--max-builds` sandboxed workers at once, each with its share of
the checks (the original's included), balanced by an estimate of each check's cost; the server
merges the findings back in order. Workers still cannot start processes: the server starts
them, and each takes a build slot. Each worker builds the part from the cached conversion; the
first to need a mesh converted converts it while the others wait for it. One build slot, or a
small part, is one worker, as before. On the generated 41,000-triangle remix (Apple M4,
`tools/bench_mesh_checks.py --workers N`): 45 s → 30 s (3 workers) / 27 s (4) for the first
check, 26 s → 19 s / 16 s after. A worker takes ~3 s to start, so the 10,000-triangle remix
gains less: 10.8 s → 8.3 s first, 7.7 s → 6.5 s after (3 workers).

**Partial results at the time limit.** A `check` that runs out of time returns every finding it
finished, plus a `timeout` FAIL naming the check that was running and the ones not run, instead
of the worker being killed with nothing.

**A separate time limit for `check`:** `--check-timeout` / `B123D_PRINT_CHECK_TIMEOUT`, default
300 s (or `--timeout` if longer); builds, renders and exports keep `--timeout` (120 s).
`deploy/compose.yaml` reads both from `.env` (`B123D_PRINT_TIMEOUT`, `B123D_PRINT_CHECK_TIMEOUT`),
so a host can change them without editing the file.

## 0.3.0 — 2026-10-18

**Design review.** After the print checks pass, the assistant can review a part for its purpose
and a design style, and suggest changes; it never changes the part without your OK.
- Five styles: `functional` (default), `modern`, `least_cost`, `rugged`, `soft`. Set `STYLE` in
  `Dims` (variants can override it) or `style` in the workspace config. The industrial look is
  functional with `EDGES = "chamfer"`.
- `design_metrics` (MCP tool) and `b123d-print metrics` (CLI): size, filament (a simple estimate,
  roughly ±20 %) and cost, print time (one rule, a rough estimate), supports, shallow slopes that
  show layer steps, edge treatment (sharp / filleted / chamfered, distinct radii), mirror
  symmetry, likely screw sizes, seam corners and water traps; then the findings the style's
  thresholds trigger, each citing a `DS-*` rule.
- `design_review` prompt; a "Design review" step in `AGENTS.md`; `design_part_from_photos` asks
  for a style.
- Optional script fields `SHOW` (sides seen in use), `UP` (side up in use) and `EDGES`.
- Styles are TOML files: write your own in `~/.config/b123d-print/styles/` or the workspace's
  `styles/` folder, start from another with `based_on`, or replace a built-in by its name;
  `b123d-print styles` lists them.
- New settings `style`, `filament_price`, `print_flow`; material profiles gain `density`.
- [Design styles and review](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/): the rules
  (`DS-*`), sourced like the FDM design rules.

**Releases:** each version now gets a GitHub Release page made from its CHANGELOG section
(older versions are filled in too), and PyPI links to the changelog and releases.

## 0.2.1 — 2026-10-18

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

**Fixed:** HTTP mode behind a reverse proxy (Caddy) sometimes cut a reply off ("peer closed
connection without sending complete message body"): replies sent without reading the request body
(a 401/403, a refused upload link) now first read and discard it, up to 8 MiB; beyond that the reply
closes the connection.

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
