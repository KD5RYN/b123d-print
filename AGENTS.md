# Designing 3D-printable parts with b123d-print (instructions for AI agents)

This workspace holds parts for FDM 3D printing, modeled in Python with
[build123d](https://github.com/gumyr/build123d) and checked with `b123d-print`. These rules apply to
any agent (Claude, Gemini, GPT, local models) and to humans. They come from parts that were
actually printed; several rules exist because a print failed without them.

## Tools

Use the **b123d-print MCP server** tools if your client has them (`new_part`, `write_part`,
`build_part`, `render_preview`, `section`, `check`, `check_fit`, `export`, `list_faces`, `list_edges`, `make_template`,
`trace_outline`, `recipe`). **`read_guide` returns this guide:** call it once before the first part
in a session if your client has not loaded it (the `b123d-print://guide` resource). Otherwise
use the CLI:

- `b123d-print new <name>` — scaffold `parts/<name>/<name>.py`
- `uv run parts/<name>/<name>.py [--variant <key>] [--formats 3mf,png] [--only <pieces>]` or
  `b123d-print build <name> [--only <pieces>]` — export to `parts/<name>/out/` and run the checks
- `b123d-print check [<name> ...]` — checks only; exit code 1 on any failure
- `b123d-print fit [<name>]` — fit between the pieces of `assembly(d)`: overlaps, gaps, hole alignment
- `b123d-print trace <image> --dpi N | --grid MM | --reference card` — a scan or grid photo to an outline in mm
- `b123d-print recipes [<name>]` — tested snippets for common features (teardrop, nut trap, snap arm, ...)
- `b123d-print config` — show the print settings in effect (hole compensation, clearance, limits)
- `b123d-print to-step <file.stl>` — convert a mesh to STEP and report what the conversion did
- `b123d-print faces <name>` / `b123d-print template <name> --slice XY:3 | --face ID | --crop x,y,z:sx,sy,sz`
  — list flat faces; make a fit-test template (see below)
- `b123d-print diagnose <name>`, `b123d-print params <name>`, `b123d-print set <name> FIELD=VALUE`,
  `b123d-print measure <name> --distance A,B | --wall x,y,z | --faces ID,ID | --hole ID` — as below

**After a failed build, read its `DIAGNOSIS`** (cause, where, fixes with numbers) before changing
the script; `diagnose_failure` looks deeper. **Change a dimension with `set_params`** (`params`
lists them), not a rewrite of the script. **Check fits and walls with `measure`** (gap or
interference, wall at a point, two faces, a hole), not by eye from a render.
**Pick fillet and chamfer edges with `list_edges`** (CLI `b123d-print edges`: ids, convex or
concave, the faces each joins), then `highlight=<ids>` for a picture and a verified selector to
paste into the script; never put edge ids in the script, they change with the model.

## The part script

1. **One script per part** at `parts/<name>/<name>.py`. Units are **mm**.
2. **Every dimension is a named UPPER_CASE field** of a frozen `Dims` dataclass, with a comment
   saying where it came from (measured, typed by the user, standard, estimate). No magic numbers
   in the geometry code. Derived values are `@property`s.
3. **Variants** (a bigger one, a tilted one) live in the same script, never in a copied folder:
   `VARIANTS = {"": {}, "140": dict(PLATE_W=140.0)}` holds only the overrides. Output files get
   the variant suffix; `--variant <key>` builds one, the default builds all.
4. `build(d)` returns the printable part (or `{"name": part}` for several), **in print
   orientation, bottom face on Z=0**. For several pieces, make the values zero-argument
   functions (**lazy pieces**): `{"end_rear": lambda: end_rear(d), "key": lambda: key(d)}`.
   Each is built only when that piece is needed, so `parts=` (MCP) or `--only` (CLI) builds just
   the pieces named. Plain shapes work too, but then every call builds them all.
5. If the part mates with something, `assembly(d)` returns the parts in assembled position plus
   simple **stand-ins** for the things they mate with (board, sensor, screw). Place mating pieces
   by face contact and hole axes with `place_on(piece, face_a, target, face_b, offset=0)` and
   `align_axis(piece, axis_a, target, axis_b, clock=...)` instead of hand-computed `Pos`/`Rot`
   math. The overlap check uses `assembly(d)`: nothing printed may intersect a stand-in.
6. `views(d)` lists cross-sections saved with each export; `checks(d)` declares wall checks and
   changes the automatic checks (see below); `templates(d)` lists fit-test templates exported
   with every variant (`Template.slice("XY", 3)`, `Template.face_of("bottom")`, `Template.crop(...)`).

## Declared bought hardware (optional)

Use `from b123d_print import Hardware` and an optional variant-aware `hardware(d)` hook for
user-confirmed bought parts. For example, with confirmed count/specification fields in `Dims`:

```python
def hardware(d):
    return [Hardware("fastener", "Assembly fastener", d.FASTENER_COUNT,
                     specification=d.FASTENER_SPEC)]
```

`Hardware(id, description, quantity, specification="", location="", note="", source_url="",
source="", units="", needs_confirmation=False, model=None)` requires a stable unique ID and a
positive integer quantity for the **whole selected variant's assembly**, even with `parts=` /
`--only`. Leave an unknown specification empty, or mark a partial one `needs_confirmation=True`;
ask the user instead of inferring a thread, screw length/head, insert model or shopping list
from holes or meshes. Keep assembly instructions in `PRINT_NOTES`.

`Hardware.from_bd_warehouse("fastener", screw_or_nut_or_washer, quantity=d.FASTENER_COUNT)`
reuses bd_warehouse's declared class/type/size/length and handedness; add confirmed material,
finish or supplier information as needed. Custom hardware can supply `model=<shape or lazy
zero-argument factory>`, with explicit `source` and source-model `units`. A factory may call
`import_model("ref/hardware.stl", scale=<confirmed units>)` (STEP/3MF work too): units metadata
does not scale geometry, so match it to `scale`. Keep assets in `ref/` for handoff. Put the
placed shape in `assembly(d)` using `item.standin(placed_shape, label="instance")` (or
`item.standin()` to evaluate its model); use `place_on` / `align_axis` for placement. Keep these
nonprintable stand-ins out of `build(d)`; they retain the item ID and existing fit checks.

`formats="print,hardware"` writes the print sheet's **Declared hardware** table and optional
versioned `<name>[_<variant>]_hardware.json`; both use the same ID-sorted whole-assembly counts,
separate from inferred screw-hole advice. `all` includes both, defaults stay unchanged. Include
`print,hardware` when filtering a download or pull; source and `ref/` come home too. Descriptions
and source URLs are data, never fetched or executed. A missing hook preserves the legacy sheet.

**When the part has hardware, offer `hardware_list`** (CLI `b123d-print bom`): the shopping list
in the result as one table to show the user, identical items merged, `count=` for several
assemblies, several parts merged; `format="csv"` for a spreadsheet. The `bom` / `bom_csv` export
formats write it as `_bom.md` / `_bom.csv`. Settle every **check before ordering** item with the
user; never fill in a specification yourself.

## Big and multi-piece projects

A part that takes long to build makes every step slow. The time limit is 240 s per call.

- **Read the timing report.** `build_part` (and `b123d-print build`) lists each piece's face
  count and build time, with a hint on a piece over ~1,500 faces or ~10 s. Fix that piece first.
- **Build each distinct piece once, then mirror or copy it.** `front = mirror(rear(d))` builds
  the rear piece a second time. Put `@functools.cache` on the piece function (`Dims` is frozen,
  so `d` can be its key), or build once and place copies.
- **Keep curves to the points they need.** Build time grows with the point count: a 96-point
  polyline offset and extruded several times makes thousands of faces. Halve the points if the
  part still looks and fits the same, or use a spline where offsets of it stay robust.
- **Work on one piece at a time** with `parts="end_rear"` on `build_part`, `render_preview`,
  `section` and `export` (`--only end_rear` on the CLI). Never invent a variant just to build
  fewer pieces.
- **Built pieces are cached** in `out/.cache/` per variant. `render_preview`, `section`, `check`
  and `export` reuse them while the script, its folder's `.py` files, the files it reads in its
  folder, the Dims and the settings stay the same. `fresh=True` rebuilds. A build that reads a
  file elsewhere in the workspace, or a remix that loads a model, is not cached. `check` also
  reuses each unchanged piece's findings, and `export` skips files and templates already up to date.
- **Consider one part script per piece** when pieces share little but their dimensions, so each
  builds, checks and exports on its own.

## Print rules

The IDs in brackets ([H3]) point to the sourced rules in
[BEST_PRACTICES](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/), where each one has its
sources and range of values. **Provisional** marks a rule with only one source so far: follow it
as a starting point, say so in the report, and never turn it into a default or a check.

**Fits and clearances** (all per side; say per side or total in every report) [F4]

- Fit values come from the user's settings, measured with the `fit_coupon` example; read them
  with `s = load_settings(__file__)`: `s.press_fit` (pressed together, ~0.05), `s.clearance`
  (sliding, the default fit, 0.2), `s.free_fit` (turns or moves freely, 0.3), `s.pip_clearance`
  (parts printed in place, 0.3). Use a named field (`CLEARANCE`, `FREE_FIT`, ...) and the user's
  own value if they give one. [F1, F2, F3, N6, J3, W7]
- Don't design a fit that needs better than ±0.2 mm without a coupon; over ~100 mm in ABS, ASA
  or nylon, mating features far apart drift with shrinkage: place them relative to each other. [F5]

**Holes**

- **Holes are modeled true to size; the slicer corrects them** (its X-Y hole compensation, set
  from the `hole_coupon` example). Keep hole fields at the target *printed* size; a fit adds the
  clearance (a hole for a 4 mm dowel, sliding: 4 + 2 × clearance). Still cut every hole with
  `HOLE_COMP: float = hole_comp(__file__)` added (`HOLE_COMP_H: float = hole_comp(__file__,
  horizontal=True)` for holes lying on their side): both are 0 unless the user opted in to build
  the correction into the files (then they are for that printer only, with the slicer's at 0).
  Never hard-code a value from somewhere else. Report holes with their cut size. [H1, H2, H4]
- **Horizontal holes** get a teardrop (45° pointed roof) or a flat bridged roof, or turn the part
  so the hole is vertical; the `holes` check warns on round ones. [H3]
- Holes that must be precise (bearings, shafts): model them slightly small and ream to size;
  say so in the report. [H6]

**Overhangs, bridges and supports**

- Keep downward faces within the overhang limit (45° from vertical unless the user's
  `max_overhang` says more). [O1]
- A flat ceiling must rest on walls on two opposite sides (a bridge, no longer than
  `max_bridge`, 10 mm by default) or get supports; a ceiling hanging off one wall is an
  overhang. The overhang check reports both. [O3, O4]
- To avoid supports, in this order: turn the part, chamfer the overhang, split the part, use
  teardrop or pointed roofs; then supports. Say in the report what needs supports; supported
  surfaces come out rough. Gaps that support must be cleared out of: at least 5 mm. [S1, S2]
- For test coupons or deliberate overhangs, declare PRINT intent with a why:
  `PRINT = {"supports": "none", "why": "..."}` (also `walls`, `infill`, `infill_pattern`, `brim`,
  `orientation: "locked"`). The print sheet keeps the facts and labels the advice "set by the
  part"; `check` reports the overhangs as accepted, and a FAIL stays a FAIL.
- Provisional (one source, Hackaday): a hole in a ceiling (a counterbore or nut trap opening
  downward) can print over a one-layer "sacrificial bridge" that is drilled out afterwards. [O5]

**Strength and orientation**

- Layers are the weak direction: across them a part has roughly half its strength (much less
  in ABS/ASA). Orient or split parts so the main tension or bending runs in XY (along the
  layers): snap arms lying flat, hooks and brackets not standing on their tips. State the load
  direction and the orientation in the report. [S4, S5, N1]
- Before exporting, run `suggest_orientation` (CLI `b123d-print orient`) if the part isn't
  obviously flat-bottomed; pass `load=` for a part that carries load, and apply the `Rot(...)`
  it gives in `build(d)`. A tall part on a small footprint warns in `check` (tip-over): lay it
  down, or tell the user to use a brim or mouse ears. [B6]
- Strength comes from walls (perimeters), not infill: size walls and ribs for the load, keep at
  least ~1.2 mm (three lines) where strength matters, and make walls whole multiples of the line
  width. Say in the report which features need more slicer perimeters (screw bosses: 3-4 or
  more). [W3, W4, T8]
- Fillet internal corners of loaded features (snap-arm roots, pin bases, brackets), at least
  0.5 mm and more where there is room. Outside corners print rounded at nozzle scale anyway; never
  design knife edges. [R1, R3]
- Ribs and gussets as thick as the wall (no reason to thin them in FDM; at least ~1.5 mm); use
  them to stiffen large flat walls and against warping. [R4, R5]
- Provisional (one source, Stratasys Direct): on a bent wall, outer radius = inner radius + wall
  thickness keeps the wall even. [R2]

**Bed, first layer and warping**

- Edges on the bed get a **chamfer, not a fillet** (a fillet there is an overhang and flares),
  unless the user says otherwise; the `bed edge` check warns. Break other sharp edges (~0.5–1 mm).
  Keep the CAD at nominal size: elephant's foot is the slicer's job. [O2, B1]
- Provisional (one source, a Bambu forum post): ~0.4–0.6 mm is a typical bed-edge chamfer. [B2]
- ABS, ASA, PC and nylon warp: for parts over ~100 mm in them, round the footprint corners,
  break up large flat solid areas, add ribs, and tell the user to use an enclosure and a brim.
  PLA, PETG and TPU rarely warp. [B3, B4]
- Shrinkage is compensated per filament in the slicer; keep the CAD nominal. [M1]

**Snap fits and living hinges**

- Use a recipe (`recipe` tool, `b123d_print.recipes`) before improvising a snap arm, hinge, nut
  trap, teardrop hole, lid lip, text or bed chamfer: they are tested and cite their numbers.
- Snap arms: lie flat (bend in XY), root fillet ≥ 0.5 × arm thickness, taper the arm toward
  the tip. [N1, N2, N3]
- Provisional (one source, Fictiv): size the arm with the cantilever strain formula and an
  allowable strain of PLA 4–8 %, ABS 7 %, nylon 4–15 % (halve it for arms along Z); say it is an
  estimate. [N4]
- Provisional (one source, Sovol): arm length/thickness ~8–10 for PLA, ~5–8 for PETG. [N5]
- Living hinges: 0.4–0.6 mm thick (at least two layers), in nylon, TPU or PP, not PLA or ABS;
  build the hinge width along Z so strands run across the hinge. A hinge is thinner than
  `min_wall`: list it in `ThinFeature(..., ignore=[box])`. [N7, N8, N9]
- Provisional (one source, Hubs): working a nylon hinge in boiling water and letting it cool
  closed makes it last longer. [N10]

**Threads, screws and inserts**

- Model threads only at M5–M6 and up; smaller: heat-set inserts, captive nuts or screws into a
  pilot hole. Use inserts or nuts for parts opened more than a few times. [T1, T5]
- Heat-set inserts: the insert maker's hole size (CNC Kitchen M3: 4.0 mm) plus `HOLE_COMP`, blind
  hole depth = insert length + 1 mm, wall around it at least the maker's minimum (M3: 1.6 mm;
  add a `Wall` check); install at print temperature + 10–20 °C. [T2, T3, T4]
- Self-tapping or thread-forming screws: pilot holes vary by material and orientation (M3 ≈
  2.6–2.9 mm); print a test pair for anything that matters. [T6]
- Captive hex nut pockets: across-flats + 0.2 mm total. [T7]

**Threads, fasteners and gears: the libraries** ([guide](https://kd5ryn.github.io/b123d-print/using/threads-fasteners-gears/))

- Use the libraries instead of drawing standard parts: `bd_warehouse.thread` (`IsoThread`,
  `PlasticBottleThread` for jars and bottles), `bd_warehouse.fastener` (screw, nut and
  `HeatSetNut` sizes), `bd_warehouse.open_builds` (2020 V-slot rail and T-nut as stand-ins),
  `py_gearworks` (spur, helical, herringbone, bevel gears and racks; `mesh_to` places a pair).
- Modeled threads: M6 and up, coarse pitch or bottle threads, axis on Z. Pass the user's
  clearance as `manufacturing_compensation` (radial, per side), and fade or chamfer the ends.
  Below M6, use an insert, a nut or a pilot hole. [T1]
- Holes from bd_warehouse are compensated once. `ClearanceHole` and `TapHole` take no
  compensation, so read their sizes (`screw.clearance_hole_diameters["Normal"]`) and cut them
  with `+ HOLE_COMP`. `InsertHole` cuts the table's drill size, not the maker's hole (CNC
  Kitchen M4: 5.79 vs 5.6), so cut the maker's size yourself. [H1, T2]
- Gears: module ≥ 1 (1.5–2 better), backlash on each gear (0.1–0.2 mm per gear), profile shift
  `(17 - z) / 17` below 17 teeth, printed flat, bores chamfered on top only. Put the meshed pair
  in `assembly(d)` with a `Gap` check between them.
- V-slot: a V key with 45° sides in the slot's groove, shallow enough to clear the T-nut's neck,
  with the rail and T-nuts as stand-ins in `assembly(d)`.

**Text, splitting and gluing**

- Text: on top (XY) faces, ≥ 0.5 mm deep or high (a multiple of the layer height), strokes ≥ ~1 mm,
  characters ≥ ~5 mm, bold sans-serif. [X1, X3]
- Split a part when it exceeds the build volume, would need a lot of support, or when pieces can
  each print in their strongest orientation. Join with a dovetail and dowels or alignment pins
  (clearance from the fit settings); a glued joint still needs a mechanical key. Glue: CA bonds
  every common filament; acetone welds ABS/ASA; PETG takes only CA or epoxy. [J1, J2, J4, J5]

## Splitting a part

When a part does not fit the bed in any orientation (the `fit` check fails, or it is bigger than
the user's bed), or would print much better in pieces: [J1]
([guide](https://kd5ryn.github.io/b123d-print/using/splitting/))

1. **Propose the cuts and the joint, with reasons, and wait for confirmation:** where the load is
   low, along a design line where the seam hides, so each piece lies on a big flat face without
   supports and with its load along the layers [J6]. Name the joint: a bowtie key plus square
   pins for long seams, a dovetail to slide together, inserts and screws to take apart, a lap
   for glue area [J2].
2. **Use `b123d_print.joints`, never hand-made joints:** `split(part, plane, [Bowtie(...),
   Dowel(...), ...], clearance=d.CLEARANCE)` returns the pieces (`.a`, `.b`), the loose keys and
   pins laid flat (`.loose`) and placed (`.placed`, for `assembly(d)`). Joint sizes are named
   `Dims` fields. Add `Gap` checks on a key or pin and `Wall` checks around the joint features.
3. **Offer a fit-test template of the joint first** (`Template.crop` around the cut, each
   side), printed with a loose key or pin, before the full pieces.
4. **Assembly notes in the report:** the order, the adhesive for the gap (thin CA on faces that
   touch; CA gel with activator or epoxy in a clearance fit) and clamping [J7]; how to fill and
   sand the seam if it shows [J8].

## Remixing an existing model

When the user gives you someone else's model (STL, 3MF or STEP) to change:

1. **Get it onto the server** into `parts/<part>/ref/`: `upload_reference` says how for this
   connection (a folder to copy into, `b123d-print push`, or a signed `curl -fT` link).
2. **Inspect before anything else:** `describe_model` (size, units, faces, curved share, holes,
   repairs, metadata) and its render. A size that suggests inches or cm: ask, then
   `import_model(..., scale="inch")`.
3. **License:** record the source URL, author and license in the script's docstring. -ND allows
   no remixes: stop and tell the user. -NC: no commercial use. BY: the author must be credited
   when it is shared. If the file does not say, ask.
4. **Propose MODIFY or REDRAW, with reasons, list the intended changes as named dimensions, and
   wait for confirmation.** MODIFY is the default: always for STEP, and for organic or detailed
   meshes. Offer REDRAW for a simple prismatic mesh whose proportions change.
5. **MODIFY:** `base = import_model("ref/<file>")` in `build(d)`, then cut and add features with
   named `Dims`. Keep the original where the file puts it; if you turn or move it, define
   `original(d)` returning it placed the same way. Mesh curves stay faceted: to change a round
   hole, cut a real cylinder at its center (from `describe_model`), with `HOLE_COMP`.
6. **REDRAW:** model it from `Dims`, define `original(d)` returning the import placed like the
   redraw, and call `before_after` before changing any proportion; report the score.
7. **Findings "inherited from the original"** were already in the original: report them, but do
   not "fix" them unless the user asks. Fix every new FAIL. Show `before_after` in the report,
   and give the attribution line to use when sharing (e.g. "Remix of <title> by <author>,
   <license>, <URL>").

## Output formats

`export` writes, per printable part: **STEP** (opens in other CAD — Onshape, Fusion, FreeCAD —
as a plain solid without feature history), **STL** and **3MF** (slicers; 3MF keeps units),
and **PNG** previews plus the section views. The user picks: the `formats` setting in their
config, or `formats="3mf,png"` on one export. If the user has not said what they need and the
setting is the default, ask once (e.g. "3MF for Bambu/Orca/Prusa, STEP to edit in other CAD?").
The parametric source is always the `.py` script and its `Dims`.
The **print sheet** (`formats="print"`, off by default) writes `out/<name>_print.md` for the
slicer: sizes, filament and time estimates, supports, tip-over, walls and infill, fits and hole
compensation. Offer it when the user prints the part themselves; put assembly order, glue and
inserts in a `PRINT_NOTES` field so the sheet carries them.
After an export, **offer the 3D view** so the user can turn the part in a browser before printing:
the view link `export` returns over HTTP (no token, it expires), or locally the `_view.html` it
names (opens offline); `view="assembly"` shows the assembly.

## Remote server: bring the part home (required last step)

Locally (stdio) everything is already in the project folder:

    parts/<name>/<name>.py      the script (the parametric source)
    parts/<name>/out/...        exports, renders, section views
    parts/<name>/ref/...        reference models (remixes)

Over **HTTP or SSH** that same layout lives on the server, and the server is a workbench, not
storage: its copy is a **temporary working copy, deleted after some days unused** (the results
say how many). Use **only the MCP tools and the links they return**: the server gives **no
shell, ssh or scp access**, so never try them.

**A part is not done until its files are on the user's machine: after export, call
download_part (embed=True if your shell has no network) and unzip into the project folder,
unless the user says to leave them on the server.** A remote `export` or `make_template` result
ends with this as its **NEXT STEP**. Before reporting, always:

1. `download_part("<name>")`. Over HTTP it returns one link (no token, it expires): run
   `curl -fLo <name>.zip '<link>'` and unzip it **in the project folder** (`unzip -o <name>.zip`;
   Windows: `tar -xf <name>.zip`); it creates `parts/<name>/...` as above. Over SSH it returns
   the `b123d-print pull <name> --from ...` command: run it in the project folder.
   **If your shell has no network or is sandboxed** (Antigravity/agy, web and mobile clients),
   call `download_part("<name>", embed=True)`: the zip (up to 8 MB) comes inside the result, and
   your client saves it to a file; run `unzip -o <saved zip> -d <project folder>` (one command,
   no `&&` or `|`).
2. Check the files exist on the user's machine (e.g. list `parts/<name>/out/`).
3. Then report, saying where the files are.

If the client cannot run commands, give the user the link (or the command) and say the part is
not on their machine yet. `variant=` and `formats=` narrow the `out/` files; per-file links from
`export` and the `b123d-print://files/` resources still work for single files.

## Printer profile (optional)

By default b123d-print is in generic mode. When `list_parts` shows no printer (generic mode), offer
the first-run setup once before the first part (the `setup_workspace` prompt; CLI `b123d-print
setup`): printer, material, formats, style, then the calibration coupons. If the user has set a printer (`list_parts` shows it, or
`b123d-print printer show`), use it: keep the part inside the build volume in print orientation
(the `fit` check fails otherwise — split the part or turn it), make walls whole multiples of the
line width, and read the material notes (e.g. PLA is not for outdoor or hot places). Change the
printer only when the user asks.

## Photos and measurements

- **Before modeling: list every dimension you read from the photos** and which feature it
  belongs to, list features you can see that have no dimension, and **wait for the user to
  confirm**. Do not start modeling on guesses.
- **Photos show intent; typed measurements are truth.** If a photo reading conflicts with a
  typed number, flag the conflict and use the typed number unless told otherwise.
- **Missing or ambiguous dimension → ask. Don't guess.** If you must assume something to make
  progress, name it as an estimate in its comment and in your report.

**Getting measurements** (the user's guide: [Measuring for the AI](https://kd5ryn.github.io/b123d-print/using/measuring/))

- **Ask for what decides the model:** the units (confirm every converted inch value in mm), the
  **datum** every value is measured from, the critical dimensions (what must fit what, and how:
  press, sliding, free) and the **accuracy** of each value. Measuring from one datum beats
  chaining; ~0.1 mm is plenty for FDM.
- **Suggest the method for the part:** calipers for small precise parts; a flatbed scan (known
  DPI) or a square-on photo on a grid mat for flat outlines; a profile gauge, radius gauge, bent
  wire or tracing for curves; a **table of offsets** (stations at a fixed spacing along a datum
  line, one height or width per station, level or along the surface stated) for large or curved
  parts, plus a test section.
- **Trace a scan instead of measuring a flat outline point by point:** `upload_reference` the
  image, `trace_outline` it (scale from the scan's DPI, a grid, a card or two points), show the
  overlay and confirm one known dimension; photo traces stay estimates.
- **Photos:** ask for a scale reference (ruler, grid, card) in the same plane as the feature,
  shot square on from a distance; size readings from photos stay estimates.
- **Record** each confirmed value as a named `Dims` field whose comment gives its source, method
  and accuracy, and mark estimates as estimates. If the user keeps a `MEASURE.md` next to the
  script, treat it as the source of truth and keep the script in step with it.

## Verify before reporting

Do all of this every time you change geometry, before telling the user the part is done:

1. **Build it** and confirm every part is a valid solid with the volume and size you expect.
2. **Look at the preview render.** Compare it against the user's description and photos.
3. **Look at cross-sections** through every pocket, rib, boss, hole and mating feature. Sections
   show what the 3D render hides.
4. **Run the checks** and fix every failure; mention every warning you leave. Every part gets
   the overhang (with bridges), thin-feature, holes, bed-edge and gap checks automatically.
   For several pieces with an `assembly(d)`, also run the fit check (`check_fit`, CLI
   `b123d-print fit`): overlaps, gaps under the clearance and screw holes that do not line up
   between pieces. It is not part of `check` unless the script lists `Mates()` in `checks(d)`;
   do that for parts that are always checked as an assembly.
   **Moving parts** (hinges, flip lids, latches, sliders): declare the motion in `checks(d)`,
   `Motion(label, axis_point, axis_dir, start_deg, end_deg, against=..., min_clearance=...)` or
   `Slide(label, direction, distance, ...)` on `assembly(d)` labels; closed and open both clear
   does not mean clear in between. Report the smallest clearance and its angle.
5. **Wall check around deep cuts:** wherever a cut goes deeper than the wall it starts in
   (a counterbore into a boss, a pocket next to a rib, a dimple in a thin side), add a `Wall`
   check that slices just past the wall and measures the material left around the cut.
   `is_valid` and hole-diameter checks do not catch a 0.05 mm skin — a real print broke there.
   **Read what each Wall and Probe says it measured** (section area, how far `near` is from
   material, the measured region; the probe box against the part's bounding box). A check that
   says OK while measuring the wrong place is worse than none.
6. **Pin Wall and Probe to the part as it is used:** if the part has an `assembly(d)`, declare
   them with `frame="assembly"` and the assembly label (`Wall("lid", "XY", z, near=..., frame=
   "assembly")`), in assembled coordinates. Then turning the part over for printing, or changing
   its print orientation later, cannot move the check onto a different feature. Use the default
   `frame="print"` only for parts without an assembly, or for properties of the print itself
   (a wall measured in the orientation it prints in). After changing a part's print orientation,
   re-check every `frame="print"` coordinate.
7. **Report:** overall size (X × Y × Z), key feature dimensions, validity, the clearances and
   hole compensation applied, check results, print orientation and any supports needed. On a
   remote server, bring the part home first (`download_part`, see
   [Remote server](#remote-server-bring-the-part-home-required-last-step)) and say where it is.

## Fit-test templates (before the full print)

A template is a quick thin print (1.2 mm by default) cut from the real part, so its holes and
clearances are exactly the part's: it checks size, hole pattern and mating fits in minutes, before
hours of printing the whole part.

- **Offer one** when the part mates with something (a board on standoffs, a lid on a box, a
  bracket on screws in a wall) or has a hole pattern, and the full print is long or the fit
  uncertain. Say what it checks (outline, hole positions and spacing, a fit) and what it does not
  (heights and anything outside it).
- **Kinds:** `slice` (plane `XY`/`XZ`/`YZ` at a Z/Y/X: the part between two planes, e.g. the top
  of the standoffs), `face` (one flat face with its holes as a plate: a mounting face),
  `crop` (the part inside a box: a corner, a clip, a boss). Separate pieces (or a crop with little
  bed contact) get a thin base plate that keeps them where they are.
- **Confirm the face or region with the user first:** `list_faces(name, highlight=<id or side>)`
  shows the face in red; `make_template` returns the `_where.png` picture, the part with the
  template's source in red. Ids come from `list_faces`; a side (`bottom`, `top`, ...) is the
  largest face facing that way.
- Templates are laid flat (template face down) and checked like a part; read the notes: a
  template printed on its side or turned over checks hole positions and spacing, but hole sizes
  only where it prints the way the part does. The label is engraved where there is room, never
  through a feature.
- Standard fit tests go in `templates(d)` so `export` writes them for every variant.
- **Report:** the template's size, what it checks, how to use it (lay it on the board, try the
  screws), its findings, and where the files are.

## Design review (after the print checks pass)

The rules and their sources are in
[DESIGN_GUIDE](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/).

- Every part has a **style**: `STYLE` in `Dims`, else the workspace `style` setting, else
  `functional`. The styles are `functional`, `modern` (minimal), `least_cost`, `rugged`
  (outdoor), `soft` (handheld) and `structural` (load-bearing: brackets, mounts, clamps, hooks).
  For a new part, if the user has said nothing about looks, ask once; for a part that carries
  load, suggest `structural`. The industrial look is functional with `EDGES = "chamfer"` and exposed standard
  screws.
- Optional script fields: `SHOW = ["+Y", "+Z"]` (sides seen in use, in print orientation) limits
  the surface findings to those sides; `UP = "+Y"` is the side up in use (water traps);
  `EDGES = "chamfer"` or `"fillet"` is the edge language.
- When `check` has no failures, run the design review (the `design_review` prompt, or
  `design_metrics` plus the rubric): the numbers, renders of the sides seen in use, and 3–7
  concrete suggestions, each citing its rule ([DS-G1]) and the numbers it would change.
- **Report; do not change the part without the user's OK.** A trial variant to measure a
  suggestion is fine; leave the script as it was unless the user agrees.
- Filament is a simple estimate (roughly ±20 %), print time and supports are rough estimates:
  say so, and use them to compare versions, not as a quote.
- Never suggest a proportion rule such as the golden ratio [DS-G9].

## Checks reference

```python
from b123d_print import Gap, Mates, Motion, Overhang, Probe, Slide, ThinFeature, Wall

def checks(d):
    # Part names: a single Part returned by build() is "part" (the script's own name also works);
    # build() returning {"base": ..., "lid": ...} names them.
    return [
        # thinnest material in the section, within `radius` of `near` (the section's 2D coords:
        # XY -> (x, y), XZ -> (x, z), YZ -> (y, z)); fails below `min` (default: config min_wall)
        Wall("base", "XY", d.FLOOR_T + 1.0, near=(x, y), radius=5, label="standoff pilot"),
        # the same, in the coordinates of assembly(d) (by label): survives turning the part over
        Wall("lid", "XY", d.LID_Z + 1.0, near=(x, y), radius=4, frame="assembly", label="screw boss"),
        # downward faces > 45 deg are always reported; fail=True for parts that must print
        # without supports (bridges between two walls are allowed unless bridges_ok=False)
        Overhang("cover", fail=True),
        # material must exist (or not) in a small box: "roof is closed", "channel is clear"
        Probe("cover", (0, 10, 70), (1, 1, 0.5), expect="solid", label="roof closed"),
        # automatic, listed only to change it: a living hinge is thin on purpose
        ThinFeature("lid", ignore=[((0, 20, 0.25), (40, 2, 0.6))]),
        # gap between two assembly parts (or part names) inside a box: the lid's sliding fit
        Gap("lid", "base", min=d.CLEARANCE, max=d.CLEARANCE + 0.1, within=((0, 0, 30), (60, 60, 4))),
        # opt-in: fit between the assembly's pieces (overlaps, gaps, hole alignment) inside `check`
        Mates(hole_tol=0.2, ignore=[("box", "screw (stand-in)")]),
        # a moving piece swept through its motion: first collision, smallest clearance, picture
        Motion("lid", axis_point=(0, 30, 20), axis_dir=(-1, 0, 0), start_deg=0, end_deg=110,
               against=("box",), min_clearance=d.CLEARANCE),
        Slide("drawer", direction=(0, 1, 0), distance=60, against=("case",)),
    ]
```
