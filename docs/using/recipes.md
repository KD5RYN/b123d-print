# Recipes

Small, tested build123d functions for features that come up in almost every printed part, with
the printing numbers behind them and their sources. Use one before improvising the feature: each
recipe's demo part is built and run through `check` in the test suite.

```python
from b123d_print.recipes import teardrop_hole, screw_hole, nut_trap, snap_arm

part -= Pos(0, 0, d.H) * screw_hole("M3", depth=d.H, head="counterbore", hole_comp=d.HOLE_COMP)
part -= Pos(10, 0, 6) * teardrop_hole(d.PIN_D + d.HOLE_COMP_H, length=30)
```

The AI reads them with the `recipe(name)` tool or the `b123d-print://recipes/<name>` resource
(the code, a tested example, printing notes, sources); on the command line,
`b123d-print recipes [name]`.

## Conventions

- Every dimension is a named parameter in mm; pass the script's `Dims` fields, never numbers
  from somewhere else.
- **Cutters** (holes, pockets, slots, text to deboss) open on Z=0 and go down, or are centered
  on their axis: `part -= Pos(x, y, top) * nut_trap("M3")`. **Bodies** (snap arm, hinges, lid,
  gusset) come in print orientation, bottom on Z=0.
- Hole diameters are the printed size: pass the user's hole compensation as `hole_comp`
  (`d.HOLE_COMP`, or `d.HOLE_COMP_H` for horizontal holes).
- Fits take the user's values: `clearance=d.CLEARANCE`, `fit=d.PRESS_FIT`,
  `clearance=d.PIP_CLEARANCE` for print-in-place.
- The BP-* ids point to the sourced rules in [Design rules](../BEST_PRACTICES.md).

## The recipes

| Recipe | What | Functions | Summary |
| --- | --- | --- | --- |
| `teardrop_hole` | Teardrop / flat-roof horizontal hole | `teardrop_hole` | A horizontal hole along Y, centered on the origin, that prints without support: a circle |
| `screw_hole` | Counterbore and countersink | `screw_hole` | A vertical screw clearance hole (ISO 273 medium) with a counterbore for a socket head |
| `nut_trap` | Hex nut trap | `nut_trap` | A captive hex nut pocket (ISO 4032 across flats + 2 x clearance; 0.1 per side, BP-T7) with |
| `magnet_pocket` | Magnet pocket | `magnet_pocket` | A round magnet pocket: diameter d + 2 x fit (per side; the user's press_fit, BP-F1) plus |
| `snap_arm` | Snap-fit cantilever | `snap_arm`, `snap_strain`, `snap_length` | A cantilever snap arm lying flat (it bends in XY, along the layers, BP-N1), tapered from |
| `living_hinge` | Living hinge | `living_hinge` | Two leaves joined by a thin web `thickness` thick (0.4-0.6 mm, at least two lines, BP-N7) |
| `pip_hinge` | Print-in-place hinge | `pip_hinge` | A print-in-place hinge lying flat: two leaves (-Y and +Y) on the bed, knuckles along X |
| `lid_with_lip` | Lid with a lip and clearance | `lid_with_lip`, `box_shell` | A lid for a box `outer_w` x `outer_l` with walls `wall` thick: a plate top_t thick and a |
| `text_label` | Embossed and debossed text | `text_label` | Text as a solid from Z=0 up `depth`, centered on the origin. Emboss: part += Pos(x, y, top) |
| `bed_chamfer` | Fillet-safe chamfer on bed edges | `bed_chamfer` | Chamfer every edge on the bed (Z=0) by `size` at 45 degrees, holes included, by cutting a |
| `zip_tie_slot` | Cable and zip-tie slots | `zip_tie_slot`, `cable_slot` | A rectangular tunnel along X for a zip tie (width tie_w, thickness tie_t, + clearance per |
| `gusset` | Ribs and gussets | `gusset`, `ribs` | A triangular gusset in the XZ plane for an inside corner between a floor (Z=0, extending to |

## Sources

The printing numbers come from the [sourced design rules](../BEST_PRACTICES.md) (holes BP-H,
overhangs BP-O, fits BP-F, snap fits and hinges BP-N, screws and nuts BP-T, text BP-X, ribs
BP-R, bed edges BP-B), and for screw and nut sizes from ISO 273 (clearance holes), ISO 4762
(socket head cap screws), ISO 10642 (countersunk screws) and ISO 4032 (hex nuts). The snap-arm
strain formulas are from Bayer MaterialScience's *Snap-Fit Joints for Plastics* design guide;
the allowable strains are provisional (one source, BP-N4): say they are estimates.
