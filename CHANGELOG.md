# Changelog

## 0.2.0 — 2026-10-17

The part-script convention is unchanged from 0.1.0; existing scripts keep working.

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
