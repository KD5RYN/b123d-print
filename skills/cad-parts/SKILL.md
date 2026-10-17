---
name: cad-parts
description: Design, modify or review a 3D-printable part (bracket, enclosure, adapter plate, case, mount) as a build123d Python script, from photos and measurements. Use when the user wants a part to 3D print or asks about a part in a b123d-print workspace (b123d-print.toml, parts/<name>/<name>.py).
---

# 3D-printable parts with b123d-print

This skill is a thin pointer: the workflow is shared with every other agent and lives in one place.

1. **Read the rules first**: the MCP resource `b123d-print://guide` (same text as `AGENTS.md` in a
   b123d-print workspace). Follow it exactly, in particular:
   - list every dimension read from photos and **wait for confirmation** before modeling;
   - named UPPER_CASE dimensions in a `Dims` dataclass, mm, print orientation with the bed at Z=0;
   - 0.2 mm mating clearance by default; `HOLE_COMP` comes from the user's config, never hard-coded;
   - verify with `render_preview`, `section` and `check` (plus `Wall` checks around deep cuts)
     before reporting.
2. **For a new design** use the MCP prompt `design_part_from_photos`; to change a part,
   `modify_part`; to review one, `verify_part`; to calibrate holes, `calibrate_hole_comp`.
3. **Tools** (b123d-print MCP server): `list_parts`, `new_part`, `read_part`, `write_part`,
   `build_part`, `render_preview`, `section`, `check`, `export`. Without the MCP server, use the
   CLI from a workspace: `b123d-print new|build|check|config` (`uvx --from <b123d-print> b123d-print ...`).
