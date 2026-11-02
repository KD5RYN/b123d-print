---
name: cad-parts
description: Design, modify or review a 3D-printable part (bracket, enclosure, adapter plate, case, mount) as a build123d Python script, from photos and measurements. Use when the user wants a part to 3D print or asks about a part in a b123d-print workspace (b123d-print.toml, parts/<name>/<name>.py).
---

# 3D-printable parts with b123d-print

This skill is a thin pointer: the workflow is shared with every other agent and lives in one place.

1. **Read the rules first**: the MCP resource `b123d-print://guide` (same text as `AGENTS.md` in a
   b123d-print workspace). Follow it exactly, in particular:
   - list every dimension read from photos and **wait for confirmation** before modeling;
   - getting measurements: ask for units, a datum, the critical dimensions and the accuracy of
     each; suggest the method for the part (calipers, a scan or photo on a grid, a profile gauge
     or wire for curves, a table of offsets at fixed stations for large or curved parts); ask
     for a scale reference in the photos; record confirmed values in `Dims` with their source
     and accuracy;
   - named UPPER_CASE dimensions in a `Dims` dataclass, mm, print orientation with the bed at Z=0;
   - 0.2 mm mating clearance by default; `HOLE_COMP` comes from the user's config, never hard-coded;
   - verify with `render_preview`, `section` and `check` (plus `Wall` checks around deep cuts)
     before reporting.
2. **For a new design** use the MCP prompt `design_part_from_photos`; to change a part,
   `modify_part`; to review one, `verify_part`; once its checks pass, `design_review` (the design
   for its style; suggestions only, nothing changes without the user's OK); to calibrate holes, `calibrate_hole_comp`; to test a fit before the full print, `fit_test`; to remix someone else's STL, 3MF or
   STEP, `remix_part`.
3. **Tools** (b123d-print MCP server): `list_parts`, `new_part`, `read_part`, `write_part`,
   `build_part`, `render_preview`, `section`, `check`, `design_metrics` (design numbers and the
   style's suggestions; filament and time are rough estimates), `export`, `compare` (to measure a part
   against a reference STL/3MF/STEP the user put in the workspace), `upload_reference`,
   `describe_model` and `before_after` (remixing an existing model: get it onto the server, inspect
   it, compare the remix with it), `list_faces` and `make_template` (a fit-test template: a quick
   thin print of a face, slice or region of the part, offered before the full print when it mates
   with something or has a hole pattern), and `use_printer` (only when the user asks to set a printer). If the server is remote (HTTP or SSH), its copy is
   temporary: the last step before reporting is `download_part` (over HTTP `curl -fLo <name>.zip
   '<link>'` and unzip it in the project folder; over SSH the `b123d-print pull` command it gives),
   which writes `parts/<name>/<name>.py`, `out/` and `ref/` like a local install; check the files
   are there. Use only the MCP tools and their links: never ssh, scp or a shell on the server. Without the MCP server, use the
   CLI from a workspace: `b123d-print new|build|check|metrics|config` (`uvx --from <b123d-print> b123d-print ...`).
