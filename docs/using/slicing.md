# From part to print

The part is checked and exported; here is how to get it from `parts/<name>/out/` onto the
printer with Bambu Studio, OrcaSlicer or PrusaSlicer (Cura works the same way). Over a remote
server, [bring the part home](workflow.md) first (`download_part`, or `b123d-print pull`).

## Which file

| File | Use it when | Why |
| --- | --- | --- |
| `print/<name>.3mf` | almost always | carries millimeters, so it can't be scaled wrong; standard 3MF that Bambu Studio, OrcaSlicer, PrusaSlicer and Cura all open |
| `print/<name>.stl` | a slicer or service that wants STL | no units: slicers assume millimeters, which is right for these files; a mesh, a little larger |
| `cad/<name>.step` | you want to edit the part in other CAD | an exact solid without history. Slicers that import STEP turn it into a mesh themselves; use the 3MF instead, which b123d-print meshes finely |
| `print/<name>_print.md` | always worth a look | the [print sheet](#the-print-sheet): what the part assumes, in one page |

The paths are inside `out/`; `out/README.md` lists the files to open in the slicer. Pick the
formats with `formats=` on `export` (or `formats` in your config): `3mf,print` is a good default
for printing at home. See [Output formats](formats.md) and [What to save](what-to-save.md).

!!! note "Bambu Studio: \"The 3mf file has invalid config, load geometry data only\""
    Expected. The 3MF has the shape in millimeters but no Bambu project settings (printer,
    filament, plate). Click **OK** and slice it with your own settings
    ([more](formats.md), [troubleshooting](../troubleshooting.md)).

## Orientation: as exported

Every piece is exported **in print orientation**, with its bed face on Z = 0: the part
script's `build(d)` returns it that way, and the checks ran on it that way (overhangs,
bridges, bed edges, tip-over). So:

- **Don't re-orient it.** Skip Auto Orient, and don't lay it on another face (OrcaSlicer's
  "Lay on Face", PrusaSlicer's "Place on face", **F**): the overhang and strength choices were
  made for this side down. If you think another side is better, ask the assistant to run
  `suggest_orientation` and change `build(d)`, so the checks follow.
- **Move it freely in X and Y.** If a piece lands off the plate, use **Arrange** (**A**).
- **Strength:** layers are the weak direction. For a part that carries load (the `structural`
  [style](design-review.md)), the main load should run along the layers; that is why a bracket
  may lie on its side. Turning it in the slicer undoes that.

## Settings the part assumes

Most parts print with your usual profile. What to check:

!!! warning "Hole compensation"
    Holes are drawn true to size; hole shrinkage is set in your slicer (X-Y hole
    compensation, from the [hole coupon](hole-compensation.md)). Turning on `hole_comp` bakes
    the correction into the files for one printer, with the slicer's hole compensation then at 0.

- **Material.** The fits (`clearance`, `press_fit`, `free_fit`) and hole compensation are tuned
  for your printer and material ([Settings](settings.md), [calibration](hole-compensation.md)).
  Printing in another material changes them: PETG fits a little tighter than PLA, and ABS, ASA
  and nylon shrink and warp (brim, enclosure, [BP-B3/B4](../BEST_PRACTICES.md)).
- **Walls before infill.** Strength comes from the walls (perimeters). The slicer default (2-3
  walls, 15 % infill) is fine for most parts. For the `structural` style use **4-6 walls and
  15-30 % gyroid infill**, and **3-4 or more walls around screw holes and bosses**
  ([design guide](../DESIGN_GUIDE.md)). The setting is **Wall loops** in OrcaSlicer (Bambu
  Studio, which OrcaSlicer comes from, uses the same idea), **Perimeters** in PrusaSlicer and
  **Wall Line Count** in Cura; infill is **Sparse infill density** (OrcaSlicer), **Fill density**
  (PrusaSlicer). For a few bosses only, use a modifier instead of more walls everywhere:
  PrusaSlicer right-click → **Add modifier** or **Height range modifier**; OrcaSlicer and Bambu
  Studio have the same right-click modifiers.
- **Hole compensation: in the slicer.** Holes are modeled true to size. Set the slicer's hole
  correction from the [hole coupon](hole-compensation.md), half the diameter error, per side
  (OrcaSlicer and Bambu Studio: **X-Y hole compensation** on the Precision page; Cura: **Hole
  Horizontal Expansion**). If you opted in to `hole_comp`, the files have it built in: keep the
  slicer's at 0 (the print sheet says so). PrusaSlicer has only a general **XY Size
  Compensation**, which also shrinks or grows the outside: leave it at 0, unless it is your
  shrinkage correction from an XYZ cube. Shrinkage belongs in the slicer, per filament; the CAD
  stays nominal. Calibrate the cube first, then the coupons, and redo the coupons when either
  changes ([calibration order](hole-compensation.md#calibration-order-and-shrinkage)).
- **Elephant's foot.** Keep the slicer's **Elephant foot compensation** on (OrcaSlicer:
  Precision; PrusaSlicer: Print settings → Advanced). The CAD stays at nominal size; the bed
  edges get a chamfer rather than a fillet so they print cleanly.
- **Supports.** `check` (the overhang check) and `suggest_orientation` say what needs support,
  unless the part declares otherwise ([print intent](../scripts/convention.md#print-intent): a
  calibration coupon prints without supports on purpose).
  Most parts here need none: turn supports off, or set them to **On build plate only**
  (OrcaSlicer) / **Supports on build plate only** (PrusaSlicer), so nothing grows inside
  holes and pockets. Where the report or print sheet names supported faces, enable supports;
  those faces come out rough.
- **Brim.** The tip-over check warns about tall parts on a small footprint: use a brim of 5-10 mm
  or mouse ears (OrcaSlicer: Brim type **Auto** or **Mouse Ears**).

## Several pieces

A part with several pieces exports one file per piece (`out/print/<name>_base.3mf`, `out/print/<name>_lid.3mf`),
each in its own print orientation.

- **Open them together** (select all the files, or import one after another) and use
  **Arrange**. If the slicer asks whether to load them as **one object with several parts**,
  answer **no**: they are separate objects, each with its own bed face.
- **Print them together or apart.** Together saves time; apart lets each use its own settings
  (a lid with fewer walls, a bracket with more).
- **Fit-test templates** (`out/print/templates/<name>_template_*.3mf`) are separate quick prints: print one first
  when the fit matters ([templates](templates.md)).
- **Assembly:** the order, glue and inserts are in the assistant's report and, if the script sets
  `PRINT_NOTES`, in the print sheet. For split parts see [Splitting parts](splitting.md).

## The print sheet

`export` with the `print` format writes `out/print/<name>[_<variant>]_print.md`, one per variant: the
report you'd otherwise scroll back for, next to the files, and `download_part` brings it home
with them. It is off by default; ask for it with `formats="3mf,print"`, `--formats 3mf,print`,
or `formats = ["3mf", "png", "print"]` in your config (`all` includes it). It costs about a
second per piece.

It lists, from the part as built:

- per piece: size, volume, filament (simple estimate, roughly ±20 %) and print time (rough);
- the orientation, the faces that need supports (and small overhangs right at the bed), bridges
  longer than `max_bridge`, tip-over risk with brim advice, and holes lying on their side;
- the material and printer it was designed for, the supports, walls and infill (and brim) to
  use, screw holes that want more walls, the script's `Wall` checks, the fits and hole
  compensation applied (and the reminder to leave the slicer's hole compensation off);
- the pieces and `PRINT_NOTES` (a string or list in `Dims`, see
  [the part script](../scripts/convention.md#for-the-print-sheet)).

**Facts and recommendations.** The geometry is always reported as found: the faces that would
need supports, the bridges, the tip-over risk. Each recommendation (supports, walls, infill,
brim, orientation) says where it comes from, in this order:

| Label | Source |
| --- | --- |
| **set by the part** | the script's [`PRINT`](../scripts/convention.md#print-intent), with its `why` |
| **your settings** | `supports`, `walls`, `infill` in the workspace `b123d-print.toml`, else your user config ([Settings](settings.md#keys)) |
| **suggested from the geometry/style** | the overhang rule and the part's style (structural: 4-6 walls), else the slicer defaults (2 walls, 15 %) |

So the hole coupon's sheet lists the five hole roofs that would need supports, then
**Supports: none, set by the part**: it measures holes printed without supports. Walls and
infill from the part or your settings also feed the filament and time estimates.

It uses the cheap estimates from [`design_metrics`](design-review.md) and the tip-over check,
not the full check run: run `check` for the verdict. The numbers are the same rough estimates;
the slicer's are the real ones.

If the script defines `hardware(d)`, the sheet includes a **Declared hardware** table: exact
specifications and quantities supplied by the author for the **whole selected variant assembly**,
even when `parts=` / `--only` exports one piece. Hole-based screw classes remain inferred advice,
not a shopping list. An empty specification says **Needs confirmation**; never guess a screw
length, thread, head or insert model from a hole or imported mesh.

Add `hardware` to the formats (`formats="3mf,print,hardware"`) for the matching
`out/docs/<name>[_<variant>]_hardware.json`. Both artifacts go home through the existing export links,
`download_part` and SSH `pull` (include both `print,hardware` when filtering formats).
See [declared hardware](../scripts/convention.md#declared-hardware) for the hook, custom imported
stand-ins and JSON format. A script with no hook keeps its existing print sheet.

## What do I need to buy?

Ask the assistant "what do I need to buy for this?" (or "for 4 of them"). The `hardware_list`
tool returns the declared hardware as one table in the chat. From the command line, run
`b123d-print bom <part>`, adding `--count 4` for four assemblies and `--csv` for a spreadsheet:

```text
| Qty | Item      | Specification                       | Used for    | Source/link                    | Status                    |
| --: | --------- | ----------------------------------- | ----------- | ------------------------------ | ------------------------- |
|   2 | Insert    | not specified; Confirm manufacturer |             |                                | **check before ordering** |
|   4 | Lid screw | M3 x 10 mm ISO 4762                 | lid corners | <https://example.invalid/spec> | confirmed                 |

Total: 6 items on 2 lines, 1 to check before ordering.
```

The list merges identical items (same description and specification) and sums their
quantities. Several parts, or no part name at all (every part in the workspace), make one list
for the whole project. **Check before ordering** marks an item whose specification the script
has not confirmed: settle it before you buy. To keep the list with the part, add `bom` (Markdown)
or `bom_csv` (for Excel, Google Sheets or a shopping cart) to the export formats. It covers only
what the script declares in `hardware(d)`, never screws guessed from holes.
