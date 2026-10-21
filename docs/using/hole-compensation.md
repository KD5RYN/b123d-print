# Hole compensation

!!! warning "Holes are drawn true to size. Set hole shrinkage in your slicer."
    b123d-print never enlarges holes by default: a 4 mm hole is cut at 4.00 mm. Set the
    correction in your slicer's **X-Y hole compensation**, from the hole coupon (below). Turning
    on `hole_comp` instead bakes the correction into the exported files, for **one printer
    only**, and the slicer's hole compensation must then be **0**.

FDM printers print small holes undersize, by an amount that depends on printer, nozzle,
material and slicer, and holes lying on their side (axis in XY) differently again, because
their top sags.

**b123d-print models parts true to size, and the slicer corrects the holes.** A 4 mm hole is
drawn at 4.00 mm. You measure the error once per printer and material with the hole coupon,
and enter it in the slicer's **X-Y hole compensation**. The model files stay right for any
printer.

**Fits stay in the model.** A hole for something to go into is its size plus the clearance on
each side; that is design intent, not compensation. With a sliding clearance of 0.15 mm per
side:

| Hole | Cut at (default) | Cut at with opt-in `hole_comp = 0.45` |
| --- | --- | --- |
| "a 4 mm hole" | 4.00 mm | 4.45 mm |
| "a hole for a 4 mm dowel", sliding | 4 + 2 × 0.15 = **4.30 mm** | 4.30 + 0.45 = **4.75 mm** |

So say which you mean: the hole's printed size, or the size of what goes in it. The agent
reports each hole with its cut size.

![Hole calibration coupon](../images/hole_coupon.png)

## Set the slicer's hole compensation

1. Get the coupon: `new_part("coupon", example="hole_coupon")` over MCP (or the
   `calibrate_hole_comp` prompt, which walks you through all of it), or
   `b123d-print new coupon --from hole_coupon`.
2. Print it with your usual material and settings, but with the slicer's X-Y hole compensation
   at **0**, or you measure its old correction too. Its holes are cut at their nominal size on
   purpose: this part measures the error.
3. Measure each vertical hole in the plate with calipers (or the largest drill bit or gauge pin
   that passes). Diameter error = average(nominal − measured) over the sizes you use.
4. Enter **half** of it in the slicer: the slicer's value is per side (it moves each hole's
   edge). Holes 0.3 mm small on the diameter → 0.15. OrcaSlicer and Bambu Studio: **X-Y hole
   compensation** on the Precision page; Cura: **Hole Horizontal Expansion**. Save it in the
   filament or process profile for that printer and material.
5. Tell b123d-print the slicer does it: `b123d-print printer calibrate hole_comp 0`, or
   `save_setup(hole_comp=0)` over MCP. Until then `check` reminds you, once per run, on parts
   with holes.

## Building it into the files (opt-in)

Some people prefer the correction in the model, or want holes lying on their side corrected
apart from vertical ones (the slicer treats them alike). Then set `hole_comp` to the diameter
error (not half), and `hole_comp_h` to the same measured over the coupon's **teardrop** (upper)
row in the tab:

```bash
b123d-print printer calibrate hole_comp 0.45
b123d-print printer calibrate hole_comp_h 0.5
```

Over MCP, `save_setup(hole_comp=0.45, hole_comp_h=0.5)`. With a [printer profile](printer-profiles.md)
set it is kept for that printer + material (on a shared server, in your workspace:
[Printer profiles](printer-profiles.md#calibration-on-a-shared-server)); without one, put it
under `[print]` in your user config.

Every exported file then has the correction built in, so:

- the slicer's X-Y hole compensation must be **0**, or the holes are corrected twice;
- the files are for **that printer and material only**.

`export`, the build output and the [print sheet](slicing.md#the-print-sheet) say so in capitals:
"HOLE COMPENSATION BUILT IN: every hole is cut 0.45 mm larger than drawn …".

Part scripts cut every hole with `HOLE_COMP: float = hole_comp(__file__)` added (and
`HOLE_COMP_H: float = hole_comp(__file__, horizontal=True)` for horizontal holes): both are 0
unless you opted in. Never hard-code a value from somewhere else (see
[The part script](../scripts/convention.md)).

**Elephant foot compensation** stays on in the slicer either way; the model never corrects for it.

## Calibration order, and shrinkage

Shrinkage and overall size are the slicer's job too, per filament: an XYZ calibration cube sets
the filament's shrinkage % or the X-Y contour (size) compensation. b123d-print keeps the model
at nominal size and has no scale setting or cube of its own ([BP-M1](../BEST_PRACTICES.md)).
Calibrate in this order:

1. the slicer's XYZ cube, if you use one;
2. `hole_coupon`: the slicer's X-Y hole compensation (above);
3. `fit_coupon` (`clearance`, `press_fit`, `free_fit`, `pip_clearance`), printed with the same
   slicer settings as real parts, so the measured fits include the slicer's corrections;
4. `overhang_bridge_coupon` (`max_overhang`, `max_bridge`).

The coupons measure whatever the slicer does at the time they are printed. Redo them when you
change the slicer's compensation (shrinkage, contour, hole) or the filament.
