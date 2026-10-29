# MCP tools and prompts

What the `b123d-print-mcp` server offers. The full descriptions the model sees are in the
[Reference](../reference.md#mcp-server), generated from the server itself.

Part scripts written with these tools can use build123d, bd_warehouse (threads, fasteners,
holes) and py_gearworks (gears): see [Threads, fasteners and gears](threads-fasteners-gears.md).

## Tools

| Tool | What it does |
| --- | --- |
| `read_guide(essentials?)` | the workflow and print rules, the same text as the `b123d-print://guide` resource ([`AGENTS.md`](../scripts/rules.md)), for clients that never load resources; its description tells the model to call it before the first part. `essentials=true` returns only the short checklist below |
| `list_parts` | the rules checklist (below), parts, bundled examples, settings in effect, printer, [design styles](design-review.md#custom-styles) and where each comes from, sandbox in use, version |
| `new_part(name, description?, example?, show_code?)` | scaffold from the template, or copy a bundled example; returns a short confirmation (`show_code=True` also returns the new file's code; the template itself is the `b123d-print://template` resource) |
| `read_part(name)` | the script's current code |
| `write_part(name, code)` | replace the script (syntax-checked before saving) |
| `params(name)` | the `Dims` fields, read from the script without running it: type, default as written, value, the comment saying where it came from, line; derived values and the fields they use; each variant's overrides |
| `set_params(name, values, variant?, rebuild?, parts?)` | change `Dims` values in place: `values={"WIDTH": 42}` replaces those defaults and leaves every other character of the file as it was; refuses unknown fields, derived values, defaults that are expressions (`hole_comp(__file__)`) and values of the wrong type. `variant` changes (or adds) that variant's override instead. `rebuild` (default true) builds before and after and reports each piece's size and volume change (`parts` narrows it), with the call that undoes it |
| `build_part(name, variant?, parts?, fresh?)` | run it: bounding box, volume, validity, dimensions, errors, and the [timing report](../scripts/convention.md#big-and-multi-piece-projects) (each piece's faces and seconds, with a hint for a slow or dense one); `parts="a,b"` builds only those pieces; writes no files but the [build cache](../scripts/convention.md#big-and-multi-piece-projects) |
| `diagnose_failure(name, variant?, parts?)` | the deeper look after a failed or broken build (failed results already carry a short [diagnosis](#build-failures-dimensions-and-measurements)): builds each piece on its own, without the build cache, and gives each failure's cause and fixes with the numbers (the largest fillet radius that fits those edges), what makes a built piece unprintable, and for an invalid solid which faces and edges are bad, tiny edges and sliver faces, and whether `fix()` repairs it |
| `render_preview(name, variant?, parts?, size?, inline?, fresh?)` | 6-view PNG. With several printable parts it draws `assembly()` if the script has one, else the parts side by side on the bed (also for `parts="a,b"`); `parts="assembly"` shows the fit |
| `section(name, plane, at, variant?, parts?, size?, inline?, fresh?)` | colored cross-section PNG on `XY` (at = Z), `XZ` (at = Y) or `YZ` (at = X) |
| `check(name, variant?, fresh?)` | validity, overlap, overhang and bridge, thin, holes, bed edge, gap, wall, probe and fit checks ([the checks](checks.md)); the fit between an assembly's pieces is `check_fit`, or part of `check` when the script lists `Mates()` |
| `design_metrics(name, variant?, style?, up?, as_json?)` | the design numbers per part: size, filament (roughly ±20 %) and cost, print time (rough), supports, shallow slopes that show layer steps, edge treatment (sharp / filleted / chamfered, radii), symmetry, screw sizes, seam corners, water traps (`up` = the side up in use); then the suggestions the part's `style` triggers, each citing its rule ([design review](design-review.md)). Changes nothing; `as_json` for the full numbers. Always before export |
| `suggest_orientation(name, variant?, piece?, load?, image?, size?, inline?)` | ranks the ways to put the part on the bed: supports, bed contact, height, print time, bridges, [tip-over](checks.md) and, with a `load` direction or the `structural` style, whether the load runs along the layers; returns the `Rot(x, y, z)` to apply in `build(d)` and how. `piece` picks one printable part, `image` renders the top choice. Changes nothing; always before export ([how it ranks](#suggest_orientation)) |
| `export(name, variant?, formats?, parts?, embed?, fresh?, view?, skip_review?)` | files to `parts/<name>/out/`, sorted into `print/`, `cad/`, `images/` and `docs/` with an `out/README.md` index ([formats](formats.md#where-each-file-goes), including `print` for a print sheet with declared hardware and `hardware` for its whole-assembly JSON BOM), for every part or only `parts="lid"` (only that piece is built); says how many files and how many MB, and suggests narrowing `formats` while it is still the default; over HTTP each file also gets a [download link](../getting-started/http.md#get-the-files) and a resource link, over SSH the result ends with the [`b123d-print pull`](../getting-started/ssh.md#get-the-files) command that copies the part, and `embed=true` puts files up to 2 MB into the result. `view` makes a [3D view](formats.md#3d-view-in-the-browser) per variant to turn in a browser: `"print"` (default: the printable parts on the bed), `"assembly"` (`assembly(d)` with its stand-ins) or `"none"`; over HTTP a signed [view link](../getting-started/http.md#view-in-3d) (no token, expires), locally a self-contained `out/docs/<name>_view.html` that opens offline, over SSH the `.glb` (then `b123d-print view` at home). With [design steps](design-review.md#the-review-checklist) missing it starts with `Exported WITHOUT ...` (`review = "warn"`, default) or refuses (`"required"`) unless `skip_review="<the user's reason>"` |
| `list_faces(name, variant?, part?, highlight?, size?, inline?)` | the flat faces of a part with stable ids, normal and side, area, center, box and round holes, for a face [fit-test template](templates.md); `highlight` (an id or side) adds a picture with that face in red, to confirm it with you |
| `list_edges(name, variant?, part?, highlight?, face?, kind?, convexity?, near?, radius?, limit?, size?, inline?)` | the edges of a part with stable ids, for a fillet or chamfer: type (line, circle, arc, ellipse, spline), length, start and end or center and radius, `convexity` (convex: outside edge; concave: inside corner; tangent: a smooth joint such as a fillet's side; seam) and the two faces it joins (flat ones by their `list_faces` id). Filters: `face` (id, side or point: its edges), `kind`, `convexity`, `near` (`x,y,z`: edges within `radius` mm, nearest first); `limit` caps the list. `highlight` (ids such as `3,4,7` or `3-6`) adds a picture with them in red and a `selector`: a build123d expression that selects exactly those edges, re-evaluated on the part, to paste into the script instead of the ids (see below) |
| `measure(name, kind, a?, b?, at?, direction?, face?, face2?, frame?, variant?, image?, size?, inline?)` | precise measurements in mm with the points they were taken at. `kind` `distance`: the gap between pieces or assembly labels `a` and `b` (stand-ins too), or their interference volume, box and depth when they overlap; `wall`: the thickness through point `at` (into the part, or along `direction`) and the gaps and walls beyond; `faces`: the distance between two parallel flat faces `face` and `face2` (ids from `list_faces`) or their angle; `hole`: the holes in flat face `face` or at `at`, modeled diameter, the size it prints at after `hole_comp`, through or blind depth. `frame` `print` or `assembly` (default: the assembly for two labels, else the piece as built); `image` adds a picture with what was measured in red |
| `make_template(name, kind, plane?, at?, face?, center?, size?, thickness?, label?, base?, variant?, part?, formats?, inline?)` | a [fit-test template](templates.md): a thin print cut from the part (`kind` `slice`: `plane` + `at`; `face`: `face`; `crop`: `center` + `size`), laid flat, labeled, checked; writes `<name>_template_<id>.*` and returns the picture of where it comes from, the findings and, over HTTP, download links |
| `download_part(name, variant?, formats?, embed?)` | bring a whole part home from a remote server, in the same layout a local install writes (`parts/<name>/<name>.py`, `out/`, `ref/`): over HTTP one signed link to a zip of it (`curl -fLo <name>.zip '<link>'`, then unzip in the project folder), over SSH the `b123d-print pull` command; `variant` and `formats` narrow the `out/` files (`out/README.md` always comes along), `embed=true` puts the zip (up to 8 MB) into the result, over HTTP and SSH, with the `unzip` command for the file the client saves it to (for a shell without network); over HTTP it also lists the [view links](../getting-started/http.md#view-in-3d) of the views `export` made. Locally it says the files are already in the project folder. The last step of remote work ([getting your files](../getting-started/http.md#get-the-files)) |
| `save_version(message, part?, start?)` | save a [version](what-to-save.md#versions) of the project in its history (git, on the user's machine): each part's script, `ref/`, `MEASURE.md` and the `.py` files beside it, and `b123d-print.toml`, never `out/`; `part` saves only that part. Says what was saved and the `Dims` values that changed ("ARM_L 115 → 130"). The model offers it after a change that built and passed its checks and calls it only on a yes. `start=true` first makes the project folder a git repository with a `.gitignore` (only after the user agreed). On a shared server it runs no git and returns the commands for the user's project folder |
| `list_versions(part?)` | the saved versions, newest first: date, id, message and the values that changed; with `part`, numbered for `restore_version`, plus what is not saved yet. On a shared server: the command for the user's project folder |
| `restore_version(part, version)` | bring a part back to a saved version (a number from `list_versions(part)`, or a commit id), saved as a **new** version: no reset, no lost history, files added later are kept; refused while the part has unsaved changes. On a shared server: the commands for the user's project folder, then `write_part` puts the restored script back |
| `compare(reference, candidate, thresholds?, image?, size?, inline?)` | measure a part against a reference STL/3MF/STEP in the workspace: size, volume and surface differences, a 0-100 score, pass/fail; `image` adds a deviation view ([comparing parts](compare.md)) |
| `upload_reference(part, filename, data_base64?, overwrite?)` | get an original model (STL, 3MF or STEP, up to 50 MB) into `parts/<part>/ref/` to [remix](remix.md#get-the-original-onto-the-server) it, or a scan or photo (PNG, JPEG, TIFF, BMP) to [trace](tracing.md): `data_base64` stores it now (practical only for small files); without it the result tells the user how: over HTTP a signed upload link for `curl -fT`, over SSH the `b123d-print push` command, locally the folder to copy it into |
| `describe_model(part, file, scale?, image?, size?, inline?)` | inspect an original before remixing it: format, units, size, faces before and after merging, the curved (faceted) share, round holes, repairs, the designer and license metadata it carries, and a suggestion to modify or redraw it; `image` adds a 6-view render |
| `before_after(name, variant?, size?, inline?)` | for a remix: the original and the remix side by side, and the original colored where the remix differs, with `compare`'s score |
| `check_fit(name, variant?, hole_tol?, verbose?, fresh?)` | [fit between the pieces](fit.md) of `assembly(d)` as placed, stand-ins included: pairs that overlap (volume and where), pairs closer than the clearance without touching, and hole alignment across pieces (partner holes off-axis by more than `hole_tol`, default 0.2 mm; diameters that no one screw explains; holes whose axis runs into solid material); male/female joint pairs are measured against their own clearance. `verbose` lists the pairs that fit too |
| `hardware_list(name?, variant?, count?, parts?, format?)` | what to buy: the bought hardware the scripts declare in `hardware(d)`, returned in the result as one Markdown table (Qty, Item, Specification, Used for, Source/link, Status) to show in chat. Identical items are merged and summed; unconfirmed ones say **check before ordering**. `name` is one part, `parts` several (comma-separated, each may be `part:variant`), neither is every part in the workspace; `variant` defaults to the standard one; `count` multiplies the quantities ("for 4 brackets"); `format="csv"` returns CSV. Reads only `hardware(d)` (sandboxed, builds nothing); the `bom` and `bom_csv` export formats write the same list to files |
| `trace_outline(part, file, dpi?, grid?, reference?, points?, distance?, tolerance?, smooth?, pick?, threshold?, invert?, inline?)` | [trace a flat object](tracing.md) in a scan or photo from `parts/<part>/ref/` into an outline in mm with its holes: scale from `dpi` (or the file's metadata), a `grid` cell size, a `reference` object (`card`, or its sides in mm) or two `points` a known `distance` apart; simplified to `tolerance` mm (or `smooth` spline points); `pick` chooses the object. Writes the points (JSON), a Python snippet and an overlay PNG to confirm with the user |
| `recipe(name?)` | the [recipe library](recipes.md): tested build123d functions for common printable features; no `name` lists them, a name gives the code, a tested example, printing notes and sources |
| `use_printer(name?, material?, search?, nickname?)` | search printer profiles, or set the active printer and material ([printer profiles](printer-profiles.md)); over HTTP and SSH it is saved per workspace. `nickname` names one of [two printers of the same model](printer-profiles.md#two-printers-of-the-same-model), each with its own calibration; `name` then takes the nickname |
| `save_setup(printer?, material?, formats?, style?, hole_comp?, hole_comp_h?, calibration?, overwrite?, move_flat?)` | save the [first-run setup](../getting-started/quick-start.md#tell-it-your-printer) answers (the `setup_workspace` prompt asks for them): printer, material, export formats, default style, a measured hole compensation and other coupon results (`calibration={"clearance": 0.18}`); with a printer they are stored for it and the material. Saved where `use_printer` saves; a value already set is kept and reported as a conflict until `overwrite=true`; `move_flat=true` moves measured values set for every printer of a workspace under the active one. Says how much b123d-print enlarges holes (keep the slicer's X-Y hole compensation at 0) and lists the calibration coupons still to print |

**The rules checklist.** Many clients never pass the `b123d-print://guide` resource or the
server's instructions to the model, but every client passes tool results. So the results of
`list_parts` (its `rules` field), `new_part` and a part's first `write_part` (once per part and
server process, before the part was ever built) end with the rules a model most often skips:

```text
Rules (all of them: read_guide):
1. Before modeling, list every dimension with its source (typed / photo / estimate) and the ones missing; ask the user and WAIT for confirmation. For a hole, say whether its size is the printed hole or what goes in it (then + clearance per side); holes are drawn true to size, plus hole_comp only if the user opted in.
2. Every dimension is a named UPPER_CASE field of the Dims dataclass, in mm; build(d) in print orientation, bottom face on Z=0.
3. Style: confirm the workspace default (list_parts) or ask the user (functional, modern, least_cost, rugged, soft, structural, organic, decorative, toy); set STYLE in Dims. A natural object (fruit, plant, animal, figurine, shell, sculpture): STYLE organic, and start from a recipe (spine_loft, tapered_sweep, organic_blend, flat_base; example banana), not from boxes and cylinders. A vase, planter or lamp shade: STYLE decorative (twisted_loft, patterned_surface, vase_shell; example twisted_vase).
4. The order, every part: build_part -> render_preview + section through holes and pockets -> check (fix every FAIL) -> design_metrics(name, style=...) -> suggest_orientation(name) -> export. The results end with "Before printing": make the calls it lists. Report holes with their cut size: "hole for a 4 mm dowel (cut 4.30: clearance 0.15 per side)".
5. On a remote server bring the files home after export: download_part(name) (embed=True if your shell has no network).
6. After a change that built and passed check, offer "Save this version? (<part>: <what changed>)"; save_version only on a yes, never on your own.
```

`variant` is a key from the script's `VARIANTS` (`standard` for the default); `build_part`,
`render_preview` and `section` take one variant, `check` and `export` default to all of them.

`parts` names pieces from `build()`: with [lazy pieces](../scripts/convention.md#big-and-multi-piece-projects)
only those are built. Every tool that builds the part reads the pieces from the
[build cache](../scripts/convention.md#big-and-multi-piece-projects) when an earlier call built
them from the same script, Dims and settings; `fresh=true` builds them again.
The image tools take `size="small"` for a ~800 px wide image (about a third of the bytes) and
`inline=false` to get only the file, or over HTTP its download link, instead of the image itself.
Every tool except `read_guide`, `list_parts`, `use_printer`, `save_setup`, `new_part`, `read_part`, `write_part`, `params` and
`upload_reference` runs in the
[sandbox](sandbox.md): the part script, or for `compare` and `describe_model` the parsing of
the model files (they may come from model-written scripts or from the internet). `compare` only takes files inside the workspace.

Every tool except `read_guide`, `list_parts`, `use_printer`, `save_setup`, `new_part`, `read_part`, `write_part`,
`upload_reference` and `recipe` runs in the
[sandbox](sandbox.md): the part script, or for `compare`, `describe_model` and `trace_outline`
the parsing of the model and image files (they may come from model-written scripts or from the
internet). `trace_outline` reads only the part's own reference files. `compare` only takes files inside the workspace.

## suggest_orientation

Run it before every export (the [review checklist](design-review.md#the-review-checklist) asks
for it); it matters most when the part is not obviously flat-bottomed (a bracket, a hook, a
part with a cap or a flange). It never edits the script: you apply the rotation it gives.

**Candidates.** The six axis-aligned orientations (as modeled first) and every large flat face
of the part's convex hull put down on the bed: the flat faces it can rest on, its own and the
ones it spans (a wedge's slope, the rim of a cup). The same side down counts once; at most 12
are scored, so a call takes a second or a few.

**Scores.** Each candidate is measured with what `check` and `design_metrics` already use, then
scored, lower is better; the table shows the parts of the score:

| Term | Measured by | Weight |
| --- | --- | --- |
| time | the print-time estimate (M3), supports included: extra time over the fastest candidate | 1 per 100 % extra |
| supports | the supports estimate (M5): downward faces past `max_overhang` that are not bridges within `max_bridge` | 4 × their share of the part's surface |
| contact | the first layer's area | 0.5 × (1 − contact / the best candidate's) |
| tip-over | the [tip-over check](checks.md)'s auto-brim estimate | 1 × estimate / 5 mm, up to 3 |
| falls | nothing on the bed, or the centre of mass outside the footprint | 3 |
| strip | standing on a strip under ~2 mm wide | 1 |
| bridges | bridges longer than `max_bridge` | 0.3 each |
| load | with `load`: how far the load points out of the layers, \|cos\| of its angle to Z (DS-T1) | 3 × \|cos\| |
| assumed load | `structural` style, no `load`: the same for the part's long axis (least inertia) | 1.5 × \|cos\| |

`load` is in the part's frame as `build(d)` returns it: `X`, `along Y`, `XZ` (a diagonal) or
`1,0,1`; its sign does not matter. Filament, time and supports are rough estimates: good for
comparing orientations, not for a quote.

**Applying it.** In `build(d)`, turn the part and put it back on the bed (print orientation,
bed at Z=0):

```python
p = Rot(0, -90, 0) * p
p = Pos(0, 0, -p.bounding_box().min.Z) * p
```

`UP` and `SHOW` are in print orientation, so they turn too: the result says what `UP` becomes.
Wall and Probe checks with `frame="print"` need their coordinates re-checked;
`frame="assembly"` ones stay put. Then `build_part` and `check`.

```text
mush [standard]
mush: 6 orientations ranked (lower score is better; rough estimates)
 #  rotation             on the bed              supports  contact  height   time  score  notes
                                                  mm2 / g      mm2      mm    min
 1  Rot(180, 0, 0)       +Z side                    0 / 0      707    36.0   13.7   0.09
 2  Rot(0, 0, 0)         -Z side                  656 / 4.9       50    36.0   20.2   3.08  supports under 656.3 mm^2; tip-over (auto-brim estimate 5.38 mm (>= 5)); as modeled now
 ...
```

The CLI does the same: [`b123d-print orient`](../getting-started/cli.md).

## Build failures, dimensions and measurements

**Diagnosis.** When a build fails, the result of `build_part`, `render_preview`, `section`,
`check` and `export` carries a `DIAGNOSIS`: the likely cause, where it happened (file, line,
function, the code, and the piece of `build()` being built), the evidence and specific fixes.
The worker reads the failing build123d call itself, so the fix has the numbers:

```text
DIAGNOSIS (fillet): the fillet radius is too big for a face next to the edges, or the edges selected are not the ones meant
  where: parts/box/box.py line 14 in lid, while building piece 'lid': part = fillet(part.edges().filter_by(Axis.Z), radius=d.R)
  Dims on that line: R=3.0
  evidence: fillet radius 3 mm on 4 edge(s)
  evidence: narrowest face next to those edges: 4 mm wide
  try:
    - fillet r 3 on edges between faces 4 mm wide: try r <= 1.9 (R in Dims: set_params('box', {'R': <new value>}))
    - fillet before the cut or boolean that makes the narrow face, so it rounds simpler geometry
```

It covers fillets and chamfers (radius against the faces next to the edges, an empty edge
selection), 2D offsets (an inward offset past half the outline, tight curves, splines: offset a
polyline instead), 3D offsets and shells, booleans (coplanar faces, tangent contact, slivers,
build123d's "Unable to clean"), lofts, sweeps, extrusions, a missing or misspelled `Dims` field
(with the closest names), `build()` returning the wrong type (None, the builder, a list, a
sketch), selections that come back empty, missing imports, and timeouts: the worker says which
piece it is building, so a timeout names the slow piece and the pieces that finished. A build that
runs but makes something unprintable (invalid, zero volume, 2D, not on the bed) gets `problems`
in `build_part`'s result. Automatic in every failed result, because the error is all the model
sees and it fixes the script from there; `diagnose_failure` is the slower, deeper look on demand.

**One dimension.** `params` lists the `Dims`; `set_params` changes values in place with an
exact edit (the ast gives the line and column of each default) instead of a rewrite of the whole
script, and reports what changed in the build.

**Measurements.** `measure` answers "does it fit" with numbers: the gap between the lid and the
box in the assembly, the wall left around a counterbore, the width of a slot between two faces,
the size and depth of a hole.

## Choosing edges for fillets and chamfers

A fillet that fails, or rounds the wrong edges, usually comes from a selector that does not pick
the edges meant. `list_edges` (CLI `b123d-print edges`) lists them instead: each edge with an id,
its type, length and end points, whether it is **convex** (an outside edge), **concave** (an
inside corner, the one to fillet for strength) or **tangent** (already smooth), and the two faces
it joins, flat ones by their `list_faces` id. Narrow the list with `face="top"`,
`convexity="concave"`, `kind="circle"` or `near="x,y,z"`, then show the chosen ones:

```text
list_edges("bracket", convexity="concave", highlight="4,5")
edges [4, 5] in red: ...
selector: concave_edges(part).filter_by(Axis.Y)
import: from b123d_print.edges import concave_edges
```

Ids are only for choosing: they change when the model changes. The `selector` is what goes in the
script. It is the shortest chain of `filter_by`, `group_by` and `sort_by` on `part.edges()`, on the
edges of an outermost face (`part.faces().sort_by(Axis.Z)[-1].edges()`) or on
`convex_edges(part)` / `concave_edges(part)`, joined with `+` when one chain is not enough, and it
was evaluated on the part to check it selects exactly those edges. A chain through a middle group
(`group_by(Axis.X)[2]`) says so (`stable: false`): it can shift when edges are added along that
axis. When no chain fits, the edges are selected by their midpoints, which move with the
dimensions: write those points from `Dims`, or fillet in several calls. The selector was found on
the finished part; to fillet at an earlier step, check `len(...)` of the selection there. In
Python: `from b123d_print.edges import list_edges, selector`.

## Prompts

Prompts are ready-made requests; clients show them as slash commands or in a menu. Each one
carries the full [workflow rules](../scripts/rules.md).

| Prompt | Use it to |
| --- | --- |
| `design_part_from_photos(description?)` | design a new part: dimensions confirmed first, then model, verify, report |
| `modify_part(name, change)` | change a part, keeping its conventions, and re-verify |
| `verify_part(name)` | review a part against the rules before printing; changes nothing |
| `remix_part(name, source?, change?)` | remix someone else's model: inspect it, choose modify or redraw, confirm the changes, then verify with inherited and new findings told apart ([remixing](remix.md)) |
| `design_review(name, style?)` | after the print checks pass: review the design for its style (functional, modern, least_cost, rugged, soft, structural, organic, decorative, toy) with `design_metrics` and renders; 3-7 suggestions with rule IDs; changes nothing without your OK ([design review](design-review.md)) |
| `fit_test(name, what?)` | propose, confirm and make [fit-test templates](templates.md) of a part before the full print |
| `setup_workspace` | first-run setup: asks for your printer, material, export formats and default style, saves them with `save_setup`, then offers the calibration coupons in order (hole, fit, overhang and bridge) |
| `calibrate_hole_comp` | walk through printing and measuring the [hole coupon](hole-compensation.md) |

## Resources

| Resource | Holds |
| --- | --- |
| `b123d-print://guide` | the workflow and print rules (the same text as [`AGENTS.md`](../scripts/rules.md)) |
| `b123d-print://template` | the part-script template `new_part` starts from |
| `b123d-print://recipes` | the [recipe library](recipes.md): every recipe with its functions |
| `b123d-print://recipes/{name}` | one recipe: its code, a tested example, printing notes and sources (the same text as `recipe(name)`) |
| `b123d-print://files/{workspace}/{+path}` | a file the server wrote (`parts/<part>/out/...`), only in the session's own workspace (`_` = the root workspace). Tool results link to these |
| `b123d-print://download/{workspace}/{part}` | a whole part as a zip in the local layout (`parts/<part>/<part>.py`, `out/`, `ref/`), only in the session's own workspace; `download_part` links to it |

The server also sends short instructions on connect, which point the model at the guide.

## Remote servers: bring the part home

Over HTTP and SSH the server is a workbench, not storage: what it writes is a temporary working
copy (over HTTP, a workspace nobody uses for 30 days is [removed](../getting-started/http.md#workspace-retention)).
The descriptions of the tools that write files, their results, the server's instructions,
`AGENTS.md` and the prompts all say the same: use only the MCP tools and the links they return
(the server gives no shell, ssh or scp access), and as the last step call `download_part`, unzip
it in the project folder, and check the files are there before reporting. A remote `export` or
`make_template` result ends with a **NEXT STEP** naming the exact call, and `embed=True` when
the zip fits the 8 MB limit, for a shell without network. Results over HTTP and
SSH show workspace-relative paths (`parts/box/out/print/box.3mf`), never the server's own folders.
