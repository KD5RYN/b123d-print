# MCP tools and prompts

What the `b123d-print-mcp` server offers. The full descriptions the model sees are in the
[Reference](../reference.md#mcp-server), generated from the server itself.

## Tools

| Tool | What it does |
| --- | --- |
| `list_parts` | parts, bundled examples, settings in effect, printer, sandbox in use, version |
| `new_part(name, description?, example?)` | scaffold from the template, or copy a bundled example |
| `read_part(name)` | the script's current code |
| `write_part(name, code)` | replace the script (syntax-checked before saving) |
| `build_part(name, variant?)` | run it: bounding box, volume, validity, dimensions, errors; writes no files |
| `render_preview(name, variant?, parts?)` | 6-view PNG; `parts="assembly"` shows the fit |
| `section(name, plane, at, variant?, parts?)` | colored cross-section PNG on `XY` (at = Z), `XZ` (at = Y) or `YZ` (at = X) |
| `check(name, variant?)` | validity, overlap, overhang, wall, probe and fit checks ([the checks](checks.md)) |
| `export(name, variant?, formats?)` | files to `parts/<name>/out/` ([formats](formats.md)) |
| `compare(reference, candidate, thresholds?, image?)` | measure a part against a reference STL/3MF/STEP in the workspace: size, volume and surface differences, a 0-100 score, pass/fail; `image` adds a deviation view ([comparing parts](compare.md)) |
| `use_printer(name?, material?, search?)` | search printer profiles, or set the active printer and material ([printer profiles](printer-profiles.md)); over HTTP it is saved per workspace |

`variant` is a key from the script's `VARIANTS` (`standard` for the default); `build_part`,
`render_preview` and `section` take one variant, `check` and `export` default to all of them.
Every tool except `list_parts`, `use_printer`, `new_part`, `read_part` and `write_part` runs in the
[sandbox](sandbox.md): the part script, or for `compare` the mesh parsing (the files may come
from model-written scripts). `compare` only takes files inside the workspace.

## Prompts

Prompts are ready-made requests; clients show them as slash commands or in a menu. Each one
carries the full [workflow rules](../scripts/rules.md).

| Prompt | Use it to |
| --- | --- |
| `design_part_from_photos(description?)` | design a new part: dimensions confirmed first, then model, verify, report |
| `modify_part(name, change)` | change a part, keeping its conventions, and re-verify |
| `verify_part(name)` | review a part against the rules before printing; changes nothing |
| `calibrate_hole_comp` | walk through printing and measuring the [hole coupon](hole-compensation.md) |

## Resources

| Resource | Holds |
| --- | --- |
| `b123d-print://guide` | the workflow and print rules (the same text as [`AGENTS.md`](../scripts/rules.md)) |
| `b123d-print://template` | the part-script template `new_part` starts from |

The server also sends short instructions on connect, which point the model at the guide.
