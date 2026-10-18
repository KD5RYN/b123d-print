# MCP tools and prompts

What the `b123d-print-mcp` server offers. The full descriptions the model sees are in the
[Reference](../reference.md#mcp-server), generated from the server itself.

## Tools

| Tool | What it does |
| --- | --- |
| `list_parts` | parts, bundled examples, settings in effect, printer, [design styles](design-review.md#custom-styles) and where each comes from, sandbox in use, version |
| `new_part(name, description?, example?, show_code?)` | scaffold from the template, or copy a bundled example; returns a short confirmation (`show_code=True` also returns the new file's code; the template itself is the `b123d-print://template` resource) |
| `read_part(name)` | the script's current code |
| `write_part(name, code)` | replace the script (syntax-checked before saving) |
| `build_part(name, variant?)` | run it: bounding box, volume, validity, dimensions, errors; writes no files |
| `render_preview(name, variant?, parts?, size?, inline?)` | 6-view PNG. With several printable parts it draws `assembly()` if the script has one, else the parts side by side on the bed (also for `parts="a,b"`); `parts="assembly"` shows the fit |
| `section(name, plane, at, variant?, parts?, size?, inline?)` | colored cross-section PNG on `XY` (at = Z), `XZ` (at = Y) or `YZ` (at = X) |
| `check(name, variant?)` | validity, overlap, overhang and bridge, thin, holes, bed edge, gap, wall, probe and fit checks ([the checks](checks.md)) |
| `design_metrics(name, variant?, style?, up?, as_json?)` | the design numbers per part: size, filament (roughly ±20 %) and cost, print time (rough), supports, shallow slopes that show layer steps, edge treatment (sharp / filleted / chamfered, radii), symmetry, screw sizes, seam corners, water traps (`up` = the side up in use); then the suggestions the part's `style` triggers, each citing its rule ([design review](design-review.md)). Changes nothing; `as_json` for the full numbers |
| `export(name, variant?, formats?, parts?, embed?)` | files to `parts/<name>/out/` ([formats](formats.md)), for every part or only `parts="lid"`; says how many files and how many MB, and suggests narrowing `formats` while it is still the default; over HTTP each file also gets a [download link](../getting-started/http.md#get-the-files) and a resource link, over SSH the result ends with the [`b123d-print pull`](../getting-started/ssh.md#get-the-files) command that copies the files, and `embed=true` puts files up to 2 MB into the result |
| `compare(reference, candidate, thresholds?, image?, size?, inline?)` | measure a part against a reference STL/3MF/STEP in the workspace: size, volume and surface differences, a 0-100 score, pass/fail; `image` adds a deviation view ([comparing parts](compare.md)) |
| `upload_reference(part, filename, data_base64?, overwrite?)` | get an original model (STL, 3MF or STEP, up to 50 MB) into `parts/<part>/ref/` to [remix](remix.md#get-the-original-onto-the-server) it: `data_base64` stores it now (practical only for small files); without it the result tells the user how: over HTTP a signed upload link for `curl -fT`, over SSH the `b123d-print push` command, locally the folder to copy it into |
| `describe_model(part, file, scale?, image?, size?, inline?)` | inspect an original before remixing it: format, units, size, faces before and after merging, the curved (faceted) share, round holes, repairs, the designer and license metadata it carries, and a suggestion to modify or redraw it; `image` adds a 6-view render |
| `before_after(name, variant?, size?, inline?)` | for a remix: the original and the remix side by side, and the original colored where the remix differs, with `compare`'s score |
| `use_printer(name?, material?, search?)` | search printer profiles, or set the active printer and material ([printer profiles](printer-profiles.md)); over HTTP and SSH it is saved per workspace |

`variant` is a key from the script's `VARIANTS` (`standard` for the default); `build_part`,
`render_preview` and `section` take one variant, `check` and `export` default to all of them.
The image tools take `size="small"` for a ~800 px wide image (about a third of the bytes) and
`inline=false` to get only the file, or over HTTP its download link, instead of the image itself.
Every tool except `list_parts`, `use_printer`, `new_part`, `read_part`, `write_part` and
`upload_reference` runs in the
[sandbox](sandbox.md): the part script, or for `compare` and `describe_model` the parsing of
the model files (they may come from model-written scripts or from the internet). `compare` only takes files inside the workspace.

## Prompts

Prompts are ready-made requests; clients show them as slash commands or in a menu. Each one
carries the full [workflow rules](../scripts/rules.md).

| Prompt | Use it to |
| --- | --- |
| `design_part_from_photos(description?)` | design a new part: dimensions confirmed first, then model, verify, report |
| `modify_part(name, change)` | change a part, keeping its conventions, and re-verify |
| `verify_part(name)` | review a part against the rules before printing; changes nothing |
| `remix_part(name, source?, change?)` | remix someone else's model: inspect it, choose modify or redraw, confirm the changes, then verify with inherited and new findings told apart ([remixing](remix.md)) |
| `design_review(name, style?)` | after the print checks pass: review the design for its style (functional, modern, least_cost, rugged, soft) with `design_metrics` and renders; 3-7 suggestions with rule IDs; changes nothing without your OK ([design review](design-review.md)) |
| `calibrate_hole_comp` | walk through printing and measuring the [hole coupon](hole-compensation.md) |

## Resources

| Resource | Holds |
| --- | --- |
| `b123d-print://guide` | the workflow and print rules (the same text as [`AGENTS.md`](../scripts/rules.md)) |
| `b123d-print://template` | the part-script template `new_part` starts from |
| `b123d-print://files/{workspace}/{+path}` | a file the server wrote (`parts/<part>/out/...`), only in the session's own workspace (`_` = the root workspace). Tool results link to these |

The server also sends short instructions on connect, which point the model at the guide.
