# Designing 3D-printable parts with b123d-print (instructions for AI agents)

This workspace holds parts for FDM 3D printing, modeled in Python with
[build123d](https://github.com/gumyr/build123d) and checked with `b123d-print`. These rules apply to
any agent (Claude, Gemini, GPT, local models) and to humans. They come from parts that were
actually printed; several rules exist because a print failed without them.

## Tools

Use the **b123d-print MCP server** tools if your client has them (`new_part`, `write_part`,
`build_part`, `render_preview`, `section`, `check`, `export`). Otherwise use the CLI:

- `b123d-print new <name>` — scaffold `parts/<name>/<name>.py`
- `uv run parts/<name>/<name>.py [--variant <key>] [--formats 3mf,png]` or `b123d-print build <name>` —
  export to `parts/<name>/out/` and run the checks
- `b123d-print check [<name> ...]` — checks only; exit code 1 on any failure
- `b123d-print config` — show the print settings in effect (hole compensation, clearance, limits)

## The part script

1. **One script per part** at `parts/<name>/<name>.py`. Units are **mm**.
2. **Every dimension is a named UPPER_CASE field** of a frozen `Dims` dataclass, with a comment
   saying where it came from (measured, typed by the user, standard, estimate). No magic numbers
   in the geometry code. Derived values are `@property`s.
3. **Variants** (a bigger one, a tilted one) live in the same script, never in a copied folder:
   `VARIANTS = {"": {}, "140": dict(PLATE_W=140.0)}` holds only the overrides. Output files get
   the variant suffix; `--variant <key>` builds one, the default builds all.
4. `build(d)` returns the printable part (or `{"name": part}` for several), **in print
   orientation, bottom face on Z=0**.
5. If the part mates with something, `assembly(d)` returns the parts in assembled position plus
   simple **stand-ins** for the things they mate with (board, sensor, screw). The overlap check
   uses it: nothing printed may intersect a stand-in.
6. `views(d)` lists cross-sections saved with each export; `checks(d)` declares wall checks and
   changes the automatic checks (see below).

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

- **Hole compensation** is per printer and comes from the user's config:
  `HOLE_COMP: float = hole_comp(__file__)`, and for holes lying on their side (axis in XY)
  `HOLE_COMP_H: float = hole_comp(__file__, horizontal=True)`. Keep hole fields at the target
  *printed* size and add the compensation when cutting. Both default to 0; the `hole_coupon`
  example measures them. Never hard-code a value from somewhere else, and don't also turn on the
  slicer's hole compensation. [H1, H2, H4]
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
- Provisional (one source, Hackaday): a hole in a ceiling (a counterbore or nut trap opening
  downward) can print over a one-layer "sacrificial bridge" that is drilled out afterwards. [O5]

**Strength and orientation**

- Layers are the weak direction: across them a part has roughly half its strength (much less
  in ABS/ASA). Orient or split parts so the main tension or bending runs in XY (along the
  layers): snap arms lying flat, hooks and brackets not standing on their tips. State the load
  direction and the orientation in the report. [S4, S5, N1]
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

**Text, splitting and gluing**

- Text: on top (XY) faces, ≥ 0.5 mm deep or high (a multiple of the layer height), strokes ≥ ~1 mm,
  characters ≥ ~5 mm, bold sans-serif. [X1, X3]
- Split a part when it exceeds the build volume, would need a lot of support, or when pieces can
  each print in their strongest orientation. Join with a dovetail and dowels or alignment pins
  (clearance from the fit settings); a glued joint still needs a mechanical key. Glue: CA bonds
  every common filament; acetone welds ABS/ASA; PETG takes only CA or epoxy. [J1, J2, J4, J5]

## Output formats

`export` writes, per printable part: **STEP** (opens in other CAD — Onshape, Fusion, FreeCAD —
as a plain solid without feature history), **STL** and **3MF** (slicers; 3MF keeps units),
and **PNG** previews plus the section views. The user picks: the `formats` setting in their
config, or `formats="3mf,png"` on one export. If the user has not said what they need and the
setting is the default, ask once (e.g. "3MF for Bambu/Orca/Prusa, STEP to edit in other CAD?").
The parametric source is always the `.py` script and its `Dims`.

**Remote server (MCP over HTTP):** the files stay on the server. Download them from the links
`export` returns (a plain HTTPS GET with no token, e.g. `curl -fO <url>`; they expire, so export
again for fresh ones) or read the `b123d-print://files/` resources it links. Never SSH into the
server to fetch them.

## Printer profile (optional)

By default b123d-print is in generic mode. If the user has set a printer (`list_parts` shows it, or
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

## Verify before reporting

Do all of this every time you change geometry, before telling the user the part is done:

1. **Build it** and confirm every part is a valid solid with the volume and size you expect.
2. **Look at the preview render.** Compare it against the user's description and photos.
3. **Look at cross-sections** through every pocket, rib, boss, hole and mating feature. Sections
   show what the 3D render hides.
4. **Run the checks** and fix every failure; mention every warning you leave. Every part gets
   the overhang (with bridges), thin-feature, holes, bed-edge and gap checks automatically.
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
   hole compensation applied, check results, print orientation and any supports needed.

## Checks reference

```python
from b123d_print import Gap, Overhang, Probe, ThinFeature, Wall

def checks(d):
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
    ]
```
