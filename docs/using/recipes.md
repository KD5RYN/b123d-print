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
| `screw_hole` | Counterbore and countersink | `screw_hole` | A vertical screw clearance hole (ISO 273 normal) with a counterbore for a socket head |
| `keyhole_mount` | Keyhole wall mount | `keyhole_mount` | Head entry and a retained shaft endpoint, with an optional continuous head cavity |
| `mounting_slot` | Adjustable screw mounting slot | `mounting_slot` | Round-ended shaft adjustment slot with optional opposite-face head recess |
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
(socket head cap screws), ISO 10642 (countersunk screws) and ISO 4032 (hex nuts); the screw
hole recipe reads its sizes from bd_warehouse's fastener tables (see
[Threads, fasteners and gears](threads-fasteners-gears.md)). The snap-arm
strain formulas are from Bayer MaterialScience's *Snap-Fit Joints for Plastics* design guide;
the allowable strains are provisional (one source, BP-N4): say they are estimates.


## Wall mounts and adjustable screw slots

`keyhole_mount` and `mounting_slot` cut flat plates for light enclosure mounting. Their geometry
is checked in CAD; the fixture below has **not been physically printed or load tested**. Neither
recipe specifies wall anchors, a safe load, vibration retention or a certified strength rating.

Both take `shaft_d`, `head_d`, `plate_t`, `travel`, `head_depth`, `clearance`, `hole_comp`, `size`
and `min_lip`. All dimensions are mm. Omitted diameters come from `_screw(size)`: bd_warehouse's
ISO 273 Normal clearance and ISO 4762 socket-head tables, with the existing `SCREW` fallback.
Explicit `shaft_d` is the base opening diameter (use the measured shaft for a custom fit), and
`head_d` is the **measured maximum head diameter**, including any washer that must pass. Do not
assume a pan head has socket-head dimensions. Use `size=None` with both explicit diameters for
other metric or inch screws; convert inch measurements to mm.

The cutter adds **2 × `clearance` per diameter** (`clearance` is per side) and then adds
**`hole_comp` once per diameter** (total). Table clearance holes already have an allowance:
`clearance` adds extra to that base, so set it to zero to keep the table's shaft clearance.
Do not pre-add `HOLE_COMP` or also enable slicer hole compensation. The actual head must remain
larger than the compensated shaft opening; excessive allowances are rejected. `head_depth` is
an axial dimension with no diameter compensation: leave axial space for the measured head height.

```python
from build123d import Pos, Rot
from b123d_print.recipes import keyhole_mount, mounting_slot

# Insert at (x, y), then the screw moves +Y relative to the plate by TRAVEL.
part -= Pos(d.X, d.Y, d.PLATE_T) * keyhole_mount(
    shaft_d=d.SHAFT_D, head_d=d.HEAD_D, size=None, plate_t=d.PLATE_T,
    travel=d.TRAVEL, head_depth=d.HEAD_DEPTH, clearance=d.CLEARANCE,
    hole_comp=d.HOLE_COMP, min_lip=d.MIN_LIP)
# Rotate +90 degrees around Z: screw travel becomes -X.
part -= Pos(d.OTHER_X, d.Y, d.PLATE_T) * Rot(0, 0, 90) * mounting_slot(
    size="M3", plate_t=d.PLATE_T, travel=d.TRAVEL, hole_comp=d.HOLE_COMP)
```

The origin is the head entry center (`keyhole_mount`) or first shaft center (`mounting_slot`),
at the insertion face **Z=0**. The cutter ends at **Z=-plate_t**. Shaft center travel is from
**Y=0 to Y=travel**; overall slot length also includes its round ends. For a hanging plate,
choose the orientation so gravity moves the *plate* opposite this relative screw motion. A
`mounting_slot` has no head entry: insert the screw axially before tightening it, and loosen it
to adjust the position. It is not a freely captive slide.

With `head_depth=0`, a keyhole head passes through the entry and remains proud of the opposite
face; provide room for it behind that face. With `head_depth>0`, a head-sized recess opens from
**the opposite face at Z=-plate_t**, up toward Z=0, continuously along the entire travel. This
is not a counterbore on the insertion face. The lip next to Z=0 is `plate_t-head_depth` thick.
`min_lip` is a project-chosen minimum for that axial thickness; its default zero only rejects a
vanished lip. Also inspect the radial overlap `(actual head diameter - compensated shaft width)/2`
and the material between the recess and the plate edges. Positive thickness alone says nothing
about load capacity. A head cavity opening downward in print orientation creates a roof under
the lip; orient the cavity upward where possible, and run the overhang/bridge checks otherwise.

### Two-screw fit coupon

Download the [CAD-only coupon source](../fixtures/wall_mount_coupon.py) and copy it into
`parts/wall_mount_coupon/wall_mount_coupon.py`. It uses two M3 ISO 4762 socket heads at **30 mm
center spacing**, **10 mm center travel**, a **5 mm plate**, and a **3.4 mm head cavity** leaving
**1.6 mm axial lip**. These are chosen fixture dimensions, not a mounting standard. Measure your
actual screws and set the `Dims` fields first. The script uses your clearance and hole compensation.

```bash
uv run parts/wall_mount_coupon/wall_mount_coupon.py --formats 3mf,png
b123d-print check wall_mount_coupon
b123d-print fit wall_mount_coupon
b123d-print view wall_mount_coupon --assembly
```

The saved views and these sections come from the actual coupon CAD, with the cavity facing up
in print orientation. The center section shows the lip depth; the XY section through that lip
shows the two entry/retention profiles.

![Coupon retaining lip section, cavity upward](../images/wall_mount_lip_section.png)

![Coupon XY section through retaining lip](../images/wall_mount_entry_section.png)

Inspect the `Wall` result in assembly coordinates near the retained screw endpoint and verify
that it measured the lip. `assembly(d)` supplies two screw stand-ins at retained positions for
`fit`; it also gives the positions for inspecting head insertion and travel in sections. The
regression tests sweep representative head/shaft positions through entry and travel and confirm
that pulling the head through the narrow lip collides. Tighten the screws to hold the final
position; keyholes alone do not prevent reverse travel or lifting off.

The fixture's `templates(d)` exports a **full-depth crop** with the normal export tools. Print
that small coupon with the same orientation, material, layer height and hole settings planned
for the mount. If the exporter warns that hole compensation has never been calibrated, print
the existing `hole_coupon` and store its result before judging the mounting fit. A thin face/slice template can check the 30 mm pattern and entry diameter, but
cannot check recess depth, head travel or lip retention. Try both screws, head insertion, the
full slide, seating and removal without forcing it. Record screw measurements, printer/material,
allowances and the physical result. A maintainer must print and try this fixture before adding
it as a physically validated bundled example; no such validation is claimed here.

### Which dimensions are standardized?

[ISO 273](https://www.iso.org/standard/4183.html) specifies clearance-hole diameters, and
[ISO 4762](https://www.iso.org/standard/34460.html) specifies metric socket-head cap screws.
[ASME B18.3](https://www.asme.org/codes-standards/find-codes-standards/socket-cap-shoulder-set-screws-and-hex-keys-%28inch-series%29)
covers inch-series socket cap/shoulder/set screws and includes related drill/counterbore data.
Those fastener dimensions are distinct from this recipe's head entry, travel, spacing and lip.
The recipes do not claim a universal ISO/ASME keyhole-mount layout or an ASME inch-size table;
use explicitly measured dimensions for unsupported hardware.
