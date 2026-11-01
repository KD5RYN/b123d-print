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
| `pcb_standoff` | PCB supports and reference boards | `pcb_standoff`, `pcb_board`, `pcb_mounting_pattern` | Explicit blind/through pilot, optional base flare, arbitrary board holes, exact sourced patterns |
| `snap_arm` | Snap-fit cantilever | `snap_arm`, `snap_strain`, `snap_length` | A cantilever snap arm lying flat (it bends in XY, along the layers, BP-N1), tapered from |
| `living_hinge` | Living hinge | `living_hinge` | Two leaves joined by a thin web `thickness` thick (0.4-0.6 mm, at least two lines, BP-N7) |
| `pip_hinge` | Print-in-place hinge | `pip_hinge` | A print-in-place hinge lying flat: two leaves (-Y and +Y) on the bed, knuckles along X |
| `lid_with_lip` | Lid with a lip and clearance | `lid_with_lip`, `box_shell` | A lid for a box `outer_w` x `outer_l` with walls `wall` thick: a plate top_t thick and a |
| `text_label` | Embossed and debossed text | `text_label` | Text as a solid from Z=0 up `depth`, centered on the origin. Emboss: part += Pos(x, y, top) |
| `text_on_surface` | Text on curved faces (wrap or project) | `text_on_surface` | Text on a curved (or flat) face as a solid along the surface normal: emboss or deboss |
| `text_on_path` | Text along a curve (arc on a tag or lid) | `text_on_path` | Flat text that follows a curve in the XY plane, as a solid from Z=0 up `depth` |
| `bed_chamfer` | Fillet-safe chamfer on bed edges | `bed_chamfer` | Chamfer every edge on the bed (Z=0) by `size` at 45 degrees, holes included, by cutting a |
| `zip_tie_slot` | Cable and zip-tie slots | `zip_tie_slot`, `cable_slot` | A rectangular tunnel along X for a zip tie (width tie_w, thickness tie_t, + clearance per |
| `gusset` | Ribs and gussets | `gusset`, `ribs` | A triangular gusset in the XZ plane for an inside corner between a floor (Z=0, extending to |
| `bolt_circle` | Bolt circle (PolarLocations) | `bolt_circle` | Holes on a circle as one cutter: one boolean for every hole |
| `hole_grid` | Hole grid (GridLocations) | `hole_grid` | A grid of vertical holes as one cutter: screw grids, pegboards, drain holes |
| `hex_grille` | Honeycomb grille or lightening (HexLocations) | `hex_grille` | Whole hex cells with a set web, filling an area: vents, speaker grilles, lightening |
| `slot_grille` | Vent and speaker slots (builder-mode GridLocations) | `slot_grille` | A row of round-ended slots at a pitch, made in a BuildSketch location context |
| `grip_ridges` | Grip ridges on a knob (PolarLocations, rotate) | `grip_ridges` | Straight ridges around a cylinder, each turned to face out, for knobs and handles |
| `spine_loft` | Body lofted along a curved spine | `spine_loft` | Cross-sections placed perpendicular to a curved spine and lofted: fruit, bodies, limbs |
| `tapered_sweep` | Tapered sweep along a path | `tapered_sweep` | A profile swept along a path while it changes size or shape: stems, tentacles, horns |
| `organic_blend` | Smooth lofted join of two bodies | `organic_blend` | Two bodies joined by a lofted collar that carries on each one's taper, instead of a fillet |
| `flat_base` | Flat base cut under a rounded part | `flat_base` | A flat underside cut at the lowest point, the part put back on Z=0 so it stands |
| `twisted_loft` | Twisted loft (spiral body) | `twisted_loft`, `star_section` | A star or polygon section lofted up Z with a twist and a taper: spiral ridges |
| `patterned_surface` | Fluted (patterned) surface | `patterned_surface`, `fluted_section` | Flutes that follow a revolved profile, straight or spiralling |
| `vase_shell` | Vase-mode body | `vase_shell`, `vase_lean` | A solid body of revolution for vase mode; refuses a wall that leans past the overhang limit |
| `inlay` | Colour inlay (multi-colour 3MF) | `inlay` | Text or a logo in a second filament, flush in its pocket: one object with two named, coloured parts |
| `hollow` | Hollow any body with an even wall | `hollow` | A body made hollow with an even wall square to the surface, one side or more left open |
| `transition_loft` | Transition loft: duct, hose and funnel adapters | `transition_loft`, `section_shape` | A body that changes section along Z, solid or hollow, with straight collars |
| `swept_section` | Section swept along a path: hooks, handles, rails | `swept_section`, `section_shape` | A constant section swept along a path and put on Z=0, lying flat |
| `revolved_profile` | Revolved profile: knobs, pulleys, wheels | `revolved_profile` | A closed (r, z) profile with rounded corners revolved around Z |

## Patterns: bolt circles, grids, grilles

`bolt_circle`, `hole_grid`, `hex_grille`, `slot_grille`, `grip_ridges` and `ribs` place their
copies with build123d's `PolarLocations`, `GridLocations` and `HexLocations` and return one fused
shape, so the part takes one boolean for all of them:

```python
from b123d_print.recipes import bolt_circle, hex_grille

part -= Pos(0, 0, d.T) * bolt_circle(d.BC_R, 6, d.HOLE_D, d.T, start_angle=30, hole_comp=d.HOLE_COMP)
part -= Pos(0, 0, d.T) * hex_grille(d.VENT_W, d.VENT_L, cell=6.0, web=1.6, depth=d.T)
```

[Patterns](patterns.md) explains the location sets, builder and algebra forms, mirroring, the
timings (400 holes: 0.22 s in one boolean, 10.2 s one at a time) and the printing rules for webs,
holes and cells.

## PCB supports and board stand-ins

`pcb_standoff(height, outside_d, pilot_d, pilot_depth, flare=0, flare_h=0, hole_comp=0)`
returns a support with its base on Z=0 and the pilot opening upward at `height`. The remaining
floor is `height - pilot_depth`; equal depth and height makes a through spacer. `flare` adds
that much **radius** at the bottom, tapering to the shaft at `flare_h`; supply both or neither.
Choose height from the measured underside components, solder joints and desired clearance.
Check the wall `(outside_d - pilot_d - HOLE_COMP) / 2` and remaining floor before printing.

Supply the target printed `pilot_d` and pass `hole_comp=d.HOLE_COMP` once. Plastic screw
pilots depend on the screw, material and orientation; use the maker's guidance and a coupon.
For a clearance spacer, reuse the selected hardware's existing dimensions:

```python
from bd_warehouse.fastener import SocketHeadCapScrew
from b123d_print.recipes import pcb_standoff

screw = SocketHeadCapScrew("M2-0.4", 10, "iso4762", simple=True)
# d.SPACER_H, d.SPACER_D and d.HOLE_COMP are named fields in your script.
spacer = pcb_standoff(d.SPACER_H, d.SPACER_D,
                      screw.clearance_hole_diameters["Normal"], d.SPACER_H,
                      hole_comp=d.HOLE_COMP)
```

Metal `tap_hole_diameters` are tap drills, not automatic plastic pilot sizes. For a heat-set
insert use its maker's hole and depth guidance; for enclosure screw clearance/counterbores,
reuse `screw_hole`. These are printed supports, not models of purchased standoff hardware.
Print base down, pilots vertical and open at the top; give bosses 3–4 or more perimeters
([BP-T8](../BEST_PRACTICES.md#8-threads-screws-inserts-nuts-bosses)).

`pcb_board(width, length, thickness, holes, hole_d)` returns a rectangular board **stand-in**.
The datum is the board center in XY, its underside at Z=0; X spans width and Y spans length.
Hole centers are `(x, y)` in that frame, viewed from above (+Z), and need not form a rectangle.
An empty sequence gives a board without holes. Holes must be distinct and entirely within the
board. `hole_d` is the actual board drill diameter and receives **no printer compensation**.
The rectangular envelope excludes connectors, underside components and edge cutouts: add
separate measured component volumes to `assembly(d)`.

`pcb_mounting_pattern(model)` provides two exact manufacturer patterns, also available as
`b123d_print.pcb.PCB_PATTERNS`. The frozen record contains `model`, `width`, `length`, `holes`,
`hole_d`, `datum` and `source`. Thickness and component keep-outs must be supplied separately.
Unknown model keys raise `ValueError`; there is no universal ESP32 pattern.

| Exact model key | Board envelope X × Y | Hole centers from board center | Hole diameter | Top-view axes and source |
| --- | --- | --- | --- | --- |
| `raspberry_pi_zero_v1_2` | 65 × 30 | (±29, ±11.5) | 2.75 | +X away from microSD; +Y toward GPIO. [RPI-ZERO-V1_2 drawing, 2015-09-23](https://datasheets.raspberrypi.com/rpizero/raspberry-pi-zero-mechanical-drawing.pdf) |
| `raspberry_pi_pico_rev3` | 21 × 51 | (±5.7, ±23.5) | 2.1 | +Y toward micro-USB; +X right on component-side view. [RP2040 Pico Rev3 datasheet, chapter 2](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf), [product brief drawing](https://datasheets.raspberrypi.com/pico/pico-product-brief.pdf) |

All table dimensions are mm. These records describe only those boards/drawings; compare your
actual board before using one. For example, `p = pcb_mounting_pattern("raspberry_pi_pico_rev3")`
then `pcb_board(p.width, p.length, d.PCB_T, p.holes, p.hole_d)` preserves its center datum.

### Compose an enclosure and check the underside

This digital fixture illustrates an asymmetric three-hole board; the values are illustrative,
not a newly printed example. The already printed
[`esp_ir_blaster`](../scripts/examples.md#esp_ir_blaster) is the physical workflow reference.
The standoff recipe's demo and these tests establish geometry, not physical fit.

```python
from dataclasses import dataclass
from build123d import Align, Box, Pos
from b123d_print import Mates, Template, Wall, hole_comp
from b123d_print.recipes import box_shell, pcb_board, pcb_standoff

@dataclass(frozen=True)
class Dims:
    BOX_W: float = 48.0  # illustrative envelope
    BOX_L: float = 36.0  # illustrative envelope
    BOX_H: float = 12.0  # illustrative height
    WALL: float = 2.0  # illustrative wall
    FLOOR: float = 2.0  # illustrative floor
    PCB_W: float = 34.0  # replace with measured board width
    PCB_L: float = 24.0  # replace with measured board length
    PCB_T: float = 1.6  # replace with measured board thickness
    HOLES: tuple = ((-13.0, -7.0), (12.0, -7.0), (-10.0, 8.0))  # measured center coordinates
    PCB_HOLE_D: float = 3.4  # replace with actual board holes
    SUPPORT_H: float = 5.0  # chosen underside clearance above floor
    SUPPORT_D: float = 7.0  # chosen boss outside diameter
    PILOT_D: float = 2.5  # illustrative pilot; verify screw/material with a coupon
    PILOT_DEPTH: float = 4.0  # leaves 1 mm within support, plus box floor
    FLARE: float = 1.0  # extra base radius
    FLARE_H: float = 1.0  # base flare height
    UNDER_W: float = 8.0  # replace with measured underside component envelope
    UNDER_L: float = 6.0  # replace with measured envelope
    UNDER_H: float = 3.0  # component extends below board at its center
    TEMPLATE_T: float = 1.2  # existing template default
    MIN_SUPPORT_WALL: float = 1.6  # chosen wall minimum
    HOLE_COMP: float = hole_comp(__file__)  # your printer calibration

    @property
    def PCB_Z(self):
        return self.FLOOR + self.SUPPORT_H


def base(d):
    part = box_shell(d.BOX_W, d.BOX_L, d.BOX_H, wall=d.WALL, floor=d.FLOOR)
    for x, y in d.HOLES:
        part += Pos(x, y, d.FLOOR) * pcb_standoff(
            d.SUPPORT_H, d.SUPPORT_D, d.PILOT_D, d.PILOT_DEPTH,
            flare=d.FLARE, flare_h=d.FLARE_H, hole_comp=d.HOLE_COMP)
    return part


def build(d):
    return {"base": lambda: base(d)}


def assembly(d):
    board = Pos(0, 0, d.PCB_Z) * pcb_board(d.PCB_W, d.PCB_L, d.PCB_T, d.HOLES, d.PCB_HOLE_D)
    underside = Pos(0, 0, d.PCB_Z - d.UNDER_H) * Box(
        d.UNDER_W, d.UNDER_L, d.UNDER_H,
        align=(Align.CENTER, Align.CENTER, Align.MIN))
    return [(base(d), None, "base"), (board, None, "board (stand-in)"),
            (underside, None, "underside component (stand-in)")]


def checks(d):
    return [Mates(), Wall("base", "XY", d.FLOOR + d.SUPPORT_H / 2,
                         near=d.HOLES[0], radius=d.SUPPORT_D / 2,
                         min=d.MIN_SUPPORT_WALL, frame="assembly", label="PCB pilot")]


def templates(d):
    return [Template.slice("XY", d.PCB_Z - d.TEMPLATE_T / 2,
                           part="base", name="pcb_supports", thickness=d.TEMPLATE_T)]
```

Run `b123d-print fit <name>` or the `check_fit` tool: the board contacts its supports without
interference. Moving a support under the central component produces an interference finding;
resolve it by changing the design. The check never removes material automatically.

Inspect the highlighted template region with `make_template` before printing. The slice joins
separate supports with the existing thin base and preserves their spacing. Set the board on it
and try the intended screws to check hole position and printed diameter. It does not verify
standoff height, component clearance, full enclosure fit or long-term screw strength. Measure
and physically validate the fit before printing the full enclosure or publishing it as a
printed example.

## Organic shapes

For a natural object (fruit, plant, animal, figurine, shell, sculpture) use the `organic`
[design style](design-review.md) and start from these four recipes, not from boxes, cylinders and
spheres fused together ([DS-O1..O5](../DESIGN_GUIDE.md#35-organic-natural)). The
[`banana`](../scripts/examples.md#banana) example uses all four.

```python
from build123d import Spline
from b123d_print.recipes import flat_base, organic_blend, spine_loft, tapered_sweep

spine = Spline((0, 0, 8), (45, 19, 1.5), (90, 24, 0), (150, 5, 5))   # the middle of the body
body = spine_loft(spine, [(0, 11), (0.25, 31), (0.5, 36), (0.85, 26), (0.97, 9), (1, 0)])
stem = tapered_sweep(stem_path, [(0, 9), (1, 7.5)])                  # follows its path exactly
part = organic_blend(body, stem, neck_plane, stem_plane, bulge=-0.05)
part = flat_base(part, 4)                                            # stands, on Z=0
```

- **`spine_loft(spine, sections, x_dir=(0, 0, 1))`**: `sections` are `(u, profile)` pairs, `u` the
  fraction of the spine's length; a profile is a Face or Sketch drawn on XY around the origin, or a
  number (a circle of that diameter). Each one is placed perpendicular to the spine, its +X along
  an axis carried down the spine without twisting (from `x_dir`: up, by default). A `0` first or
  last closes the end to a point; a few small sections close together before it make a blunt,
  rounded tip with no rim. Vary the sections: size, and shape too (ridges that sharpen).
- **`tapered_sweep(path, sections, x_dir=(0, 0, 1))`**: the same sections, swept with
  `sweep(multisection=True)`: the body follows the path exactly. For stems, tentacles, horns,
  tails. Sections at `u = 0` and `1` are required, and a sweep cannot end in a point: keep tips
  at least ~0.8 mm across.
- **`organic_blend(a, b, at_a, at_b, bulge=0, steps=4, points=48)`**: `at_a` and `at_b` are planes
  across each body where the join starts, +Z pointing out of that body towards the other. Each
  body is cut there and a lofted collar joins the cuts, leaving each one as its body was tapering,
  so there is no crease. `bulge` swells (+) or pinches (-) the middle of the collar. The faces are
  sewn into one solid (a boolean fuse along a tangent join takes tens of seconds), with a fuse as
  the fallback. The cut outlines should be roughly convex.
- **`flat_base(part, depth)`**: cuts the part `depth` mm above its lowest point and puts the cut on
  Z=0. A quarter of the section's height is a good start; deeper means more bed contact and less
  overhang round the edge. Check the contact with a section at Z = 0.1.

Print it lying along its long curve, with tree (organic) supports under the curves and variable
layer height for the gently domed top ([DS-O5](../DESIGN_GUIDE.md#35-organic-natural)). A flat
cut through a lofted surface leaves OpenCascade's own bounding box reaching under the bed (it
bounds each face by its whole parameter rectangle); the checks and metrics measure such faces
from their mesh instead, so the part is seen on the bed.

## Sources

The printing numbers come from the [sourced design rules](../BEST_PRACTICES.md) (holes BP-H,
overhangs BP-O, fits BP-F, snap fits and hinges BP-N, screws and nuts BP-T, text BP-X, ribs
BP-R, bed edges BP-B), and for screw and nut sizes from ISO 273 (clearance holes), ISO 4762
(socket head cap screws), ISO 10642 (countersunk screws) and ISO 4032 (hex nuts); the screw
hole recipe reads its sizes from bd_warehouse's fastener tables (see
[Threads, fasteners and gears](threads-fasteners-gears.md)). The snap-arm
strain formulas are from Bayer MaterialScience's *Snap-Fit Joints for Plastics* design guide;
the allowable strains are provisional (one source, BP-N4): say they are estimates. The organic
recipes follow the organic style's rules (DS-O1..O5 in the [design guide](../DESIGN_GUIDE.md#35-organic-natural)).


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
Do not pre-add `HOLE_COMP` (0 unless you opted in; then the slicer's hole compensation stays 0). The actual head must remain
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
for the mount. If `check` reminds you that the slicer's hole compensation is not set, print
the existing `hole_coupon` and set it before judging the mounting fit. A thin face/slice template can check the 30 mm pattern and entry diameter, but
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

## Shapes from profiles

Four recipes for the shapes that boxes and cylinders make badly: an even-walled hollow, a body
whose section changes, a section along a path and a round part from its profile. The
[`rounded_enclosure`](../scripts/examples.md#rounded_enclosure) and
[`hose_adapter`](../scripts/examples.md#hose_adapter) examples use the first two.

```python
from build123d import Axis, Box, FilletPolyline, fillet
from b123d_print.recipes import hollow, revolved_profile, swept_section, transition_loft

body = fillet(Box(80, 55, 30, align=BED).edges().filter_by(Axis.Z), 8)
box = hollow(body, d.WALL, open="top")                       # 2 mm everywhere, corners too
duct = transition_loft(62, (64, 34, 7), length=40, wall=2, collar_a=20, collar_b=20)
hook = swept_section(FilletPolyline((0, 70, 0), (0, 0, 0), (30, 0, 0), (30, 20, 0), radius=12), (6, 10))
knob = revolved_profile([(3, 0), (16, 0), (16, 5), (13, 18), (3, 18)], radius=[0, 0, 1, 2, 0])
```

- **`hollow(part, wall, open="top")`**: build123d's `offset(-wall, openings=...)`, so the wall is
  measured square to the surface and stays even round fillets and curves; subtracting a smaller
  copy does not. `open` is a side (`"top"`, `"bottom"`, `"+X"`, `"-Y"`, ...: every flat face on
  the outside of that side), a Face, a list, or `None` for a closed hollow. Hollow the plain body
  first and add bosses, ribs, holes and text after: small details inside the offset are what
  usually makes it fail. Outside fillets come back inside smaller by the wall, so an outside
  radius of at least twice the wall keeps the inside corners round.
- **`transition_loft(a, b, length, wall=None, collar_a=0, collar_b=0, shift=(0, 0))`**: a straight
  loft from section `a` (on the bed) to section `b`, with straight collars at the ends. A section
  is a diameter, `(w, h)`, `(w, h, corner r)` or a Face (`section_shape`). With `wall` it is hollow
  and open at both ends; the wall is measured across the section, so on a side leaning by an
  angle it is `wall x cos(angle)` square to the surface (the example's 2 mm reads 1.89 mm at 19
  degrees). Keep every side within the overhang limit, inside and out: about 1 mm of change in
  radius (or `shift`) per 1 mm of length.
- **`swept_section(path, section, x_dir=(0, 0, 1))`**: one section along a path, put on Z=0. Draw
  the path in XY (`FilletPolyline` for straight runs with rounded bends, arcs, a `Spline`) so the
  part lies flat and a hook or handle bends along the layers. The section's first size is its
  height in Z. Keep it square where it sits on the bed and chamfer that edge with `bed_chamfer`;
  a bend's radius must be bigger than half the section's width across it. A section that changes
  along the path: `tapered_sweep`.
- **`revolved_profile(points, radius=0, angle=360)`**: the half outline as (r, z) points, once
  round, revolved about Z. A profile clear of r = 0 makes a ring with a bore. `radius` is one corner
  radius or one per point (0 sharp): round the corners in the profile, keep the bed corners sharp
  and chamfer them. Print it on its flattest face; a downward-facing side steeper than 45 degrees
  needs support.

## Decorative bodies and vase mode

For the [`decorative` style](design-review.md) (vases, planters, lamp shades, ornaments). The
rules are [DS-D*](../DESIGN_GUIDE.md#36-decorative-vase).

```python
from b123d_print.recipes import star_section, twisted_loft, patterned_surface, vase_shell

body = twisted_loft(star_section(6, d.R_OUT, d.R_IN), d.HEIGHT, twist=d.TWIST, scale=d.TOP_SCALE)
flutes = patterned_surface([(30, 0), (38, 35), (34, 70), (26, 100)], flutes=16, depth=2.0, twist=20)
vase = vase_shell([(30, 0), (40, 30), (34, 75), (24, 110)], max_lean=s.max_overhang)
```

- **All three return a solid, bottom on Z=0.** For vase mode that is what the slicer wants: it
  prints one continuous wall from the outside of the solid, with no top, no infill and no
  supports. Say so in the script with `PRINT = {"vase": True, "why": "..."}` (see
  [print intent](../scripts/convention.md#print-intent)); the print sheet then gives the slicer
  switch ("Spiral vase" in PrusaSlicer, OrcaSlicer and Bambu Studio, "Spiralize Outer Contour"
  in Cura) and flags any layer that is not one closed contour. Without vase mode, shell it
  yourself or let the slicer fill it.
- **One contour per layer:** a handle, a second body or anything inside does not print in vase
  mode. `design_metrics(name, style="decorative")` says whether every layer is one contour and
  how far the wall leans (M16).
- **The wall leans both ways:** a single wall overhangs on a shoulder that closes in just as on a
  flare. `vase_shell` refuses a curve that leans more than `max_lean` (pass the printer's
  `max_overhang`); `vase_lean(profile)` measures it.
- **Patterns that read:** a few strong features (5-8 star points, 12-24 flutes, 1-3 mm deep), at
  least two line widths across; fine detail blurs at 0.2 mm layers and in the slicer's spiral
  smoothing.
- **The wall is one line:** widen the outer wall's line width (0.45 to 0.6 mm at a 0.4 mm
  nozzle) or use a bigger nozzle for a stiffer vase. Lamp shades: even walls, LED bulbs only, an
  air gap to the bulb ([DS-D6, DS-D7](../DESIGN_GUIDE.md#36-decorative-vase)).

The bundled [`twisted_vase` example](../scripts/examples.md) uses `twisted_loft` with
`PRINT = {"vase": True, ...}`.

## Text on curved faces and paths

`text_label` puts flat text on a flat face. For a jar, a knob, a dome or a round tag:

```python
from b123d_print.recipes import text_on_surface, text_on_path, text_label

jar += text_on_surface(jar, "JAM", at=(0, -40, 20), size=8, depth=0.6)            # raised, wrapped
knob -= text_on_surface(knob, "VOL", at=(0, -40, 9), size=6, depth=0.8, deboss=True)  # sunk
lid += text_on_surface(lid, "LID", at=(0, 0, 30), size=9, method="project")        # across fillets
tag -= Pos(0, 0, top - 0.6) * text_on_path("ROUND TAG", CenterArc((0, 0), 15, 160, -140), size=5, depth=1.6)
label = text_label("LINE ONE\nLINE TWO", size=6, text_align=(TextAlign.LEFT, TextAlign.TOP))
```

- **`at`** is a point on or just outside the surface: the text's center goes to the nearest
  point of the nearest face, standing towards **`up`** (+Z by default; a top face reads with +Y up).
- **`method="wrap"`** (default) bends the text onto that one face and keeps its size: cylinders,
  cones, spheres, revolved and spline faces. A closed face's seam is handled. Wrapping onto a
  revolved spline face is slow, about 1 s per letter. **`method="project"`** casts it onto the
  whole part along the normal at `at`: it crosses face edges (a filleted or lofted lid) and is
  fast, but letters stretch where the surface slopes away (keep it within ~30 degrees).
- **Emboss** `part += ...`; **deboss** `part -= ...(deboss=True)`. The solid runs along the surface
  normal, `depth` out (or in) and 0.2 mm the other way, so the boolean is clean.
- **Text along a curve:** `text_on_path` follows an Edge or Wire in XY. The letters stand on
  the left of the path's direction: an arc drawn clockwise reads along the top.
- **Several lines:** `"ONE\nTWO"`, lined up with `text_align` (`TextAlign.LEFT`, `CENTER`,
  `RIGHT`; `TOP`, `CENTER`, `BOTTOM`) in all three.
- **Sizes:** the flat-text minimums hold on the surface (BP-X1..X3): characters >= 5 mm, strokes
  >= 2 line widths, depth >= 0.5 mm along the normal. The thin-feature check measures the strokes
  and fails where a font's own junctions are thinner than a line (Arial Bold's G, R and 4 under
  ~7 mm): bigger letters, sunk text, or a sturdier font. On a wall the strokes stand up: the
  roof of a sunk stroke is a short overhang as deep as the text (0.6-1 mm prints without support).
- **A second colour:** the text is its own solid. Sunk and filled: `body = part - text`,
  `inlay = part & text` (flush with the surface). Raised: `raised = text - part`.
- **A face that does not mesh:** now and then, cutting wrapped text into a revolved spline face
  leaves a face OpenCascade cannot triangulate; the exported STL would have a hole there. The
  validity check fails on it: change `depth` by 0.05 mm or use `method="project"`.
- **Fonts:** `font=` a font installed on the machine that builds the part (the server, for a
  remote server), or `font_path=` a font file (`str(Path(__file__).parent / "font.ttf")`, kept next to the script).

The bundled [`text_knob` example](../scripts/examples.md) wraps "VOL" into a knob's tapered side
and sinks "VOLUME" along an arc on its top.

## Multi-colour inlays

For a printer with several filaments (Bambu AMS, Prusa MMU, a tool changer): text or a logo in a
second colour, flush with a top face. `inlay` cuts the pocket with the insert itself and keeps the
part of the insert inside the base as its own body:

```python
from build123d import Pos
from b123d_print.recipes import inlay, text_label

text = Pos(0, 0, d.TAG_T - d.INLAY_DEPTH) * text_label(d.TEXT, size=9, depth=d.INLAY_DEPTH + 1)
return inlay(tag, text, color="white", base_color="#2b5fa8", name="text", base_name="tag")
```

- **It returns a multi-body part** (`bodies`, see [Output formats](formats.md#multi-colour-parts-several-bodies)):
  the 3MF opens in the slicer as one object with two named, coloured parts. Give each part its
  filament there; the colours in the file are display hints only.
- **Pocket and inlay match exactly:** no clearance between bodies, they print fused like one
  part. The `bodies` check fails on an overlap and warns on a body that touches no other or is
  narrower than one line width.
- **Depth:** at least 2 layers (0.6 mm = 3 x 0.2). The printer changes filament on every layer
  both bodies share, so a shallow inlay at the top keeps the changes and the purge few; the print
  sheet lists the layers.
- **Strokes** at least 2 line widths: bold sans-serif at 5 mm and up (BP-X1..X3).
- **Any solid is an insert:** text, an imported logo, text on a curved face; place it so its top
  is at or above the face (what sticks out is trimmed off).
- Several colours: build the bodies yourself with `bodies(base=..., red=(..., "red"), white=(..., "white"))`,
  each pocket cut with its own insert.

The bundled [`inlay_tag` example](../scripts/examples.md) is a key tag with flush text.

