# Patterns: repeated features

Holes on a bolt circle, a grid of screw holes, a honeycomb vent, a row of ribs: build123d places
the copies for you with **location sets** (`GridLocations`, `PolarLocations`, `HexLocations`,
`Locations`) and mirrors with `mirror`. Use them instead of a `for` loop that computes positions,
and **cut or add every copy in one boolean**. The tested [recipes](recipes.md) `bolt_circle`,
`hole_grid`, `hex_grille`, `slot_grille` and `grip_ridges` are built this way.

Every code block on this page runs in the test suite against the build123d version b123d-print
pins (0.13.0), so the signatures below are the ones you have.

## Why one boolean

Each `part -= cutter` makes OpenCascade intersect the whole part with the cutter. Inside a loop
the part grows more complex with every hole, so the cost climbs with the square of the count.
Measured on build123d 0.13.0, a 3 mm plate with 1.2–1.5 mm holes:

| Holes | One boolean (`part - GridLocations(...) * hole`) | A boolean per pass of a loop |
| --- | --- | --- |
| 400 | 0.22 s | 10.2 s |
| 900 | 0.73 s | 58.6 s |

Every later step (check, sections, export) works on the same part, so the time saved is once per
build, not once per part. `build_part` and `b123d-print build` add a hint when a script does a
boolean on every pass of a `for` loop (`hint: line 42: a boolean on every pass of a for loop ...`);
a build that times out lists it in its diagnosis too. A loop over a literal pair
(`for sx in (-1, 1)`) is left alone: two booleans cost nothing.

## Algebra mode

A location set times a shape is a **list** of placed copies. A part minus (or plus) a list is one
boolean:

```python
from build123d import Align, Box, Cylinder, GridLocations, Locations, PolarLocations, Pos

TOP = (Align.CENTER, Align.CENTER, Align.MAX)  # a cutter that opens on Z=0 and goes down
plate = Box(80, 60, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
hole = Cylinder(1.6, 4, align=TOP)

plate -= Pos(0, 0, 4) * (GridLocations(20, 15, 4, 3) * hole)  # 12 holes, one boolean
plate -= Pos(0, 0, 4) * (PolarLocations(8, 6) * hole)  # 6 on a circle
plate -= Locations((-35, -25, 4), (35, 25, 4)) * hole  # any points: Locations(*points)
assert len(plate.solids()) == 1
```

- `Pos(...) * list` moves every copy; a recipe cutter is already one fused shape
  (`part -= Pos(0, 0, top) * bolt_circle(...)`).
- Different shapes or sizes: collect them in a list and cut once,
  `part -= [Pos(x, y, top) * Cylinder(r, h, align=TOP) for (x, y), r in zip(points, radii)]`.
  Building the list in a loop (`cuts += [...]`, `cuts.append(...)`) is fine: the booleans are
  what cost.
- `Part() + list` fuses the copies into one shape to keep, place or return (`ribs` does this).
- Points from the script's `Dims`: `Locations(*d.HOLES)` takes `(x, y)` or `(x, y, z)` tuples.

## Builder mode

The same location sets are contexts in `BuildPart` and `BuildSketch`: every shape made inside is
placed at each location, and `mode=Mode.SUBTRACT` cuts it.

```python
from build123d import BuildPart, BuildSketch, Box, Cylinder, GridLocations, HexLocations, Mode, PolarLocations, \
    RegularPolygon, Rectangle, extrude

with BuildPart() as flange_plate:
    Box(100, 100, 4)
    with GridLocations(60, 60, 2, 2):  # four corners ...
        with PolarLocations(10, 6):  # ... each with a bolt circle: nested contexts multiply
            Cylinder(1.6, 4, mode=Mode.SUBTRACT)
assert len(flange_plate.part.faces().filter_by(lambda f: f.geom_type.name == "CYLINDER")) == 24

with BuildPart() as vent:
    with BuildSketch():
        Rectangle(60, 40)
        with HexLocations(3, 7, 5):  # a pattern in the sketch, then one extrude
            RegularPolygon(2.4, 6, major_radius=False, mode=Mode.SUBTRACT)
    extrude(amount=3)
assert vent.part.is_valid
```

Nested contexts compose: `GridLocations` outside `PolarLocations` puts a full bolt circle at every
grid point. A sketch-level pattern (holes in a `BuildSketch`, one `extrude`) is usually the
cheapest of all.

## The location sets

| Set | Signature (build123d 0.13.0) | Notes |
| --- | --- | --- |
| `GridLocations` | `(x_spacing, y_spacing, x_count, y_count, align=(CENTER, CENTER))` | Centered on the origin; `align=(Align.MIN, Align.MIN)` starts at it. A single row: `GridLocations(0, pitch, 1, count)`. |
| `PolarLocations` | `(radius, count, start_angle=0, angular_range=360, rotate=True, endpoint=False)` | First copy at `start_angle` degrees from +X. `rotate=True` turns each copy to face out (its local X radial); `rotate=False` keeps the orientation. An arc: `angular_range=90`; `endpoint=True` puts a copy on both ends. |
| `HexLocations` | `(radius, x_count, y_count, major_radius=False, align=(CENTER, CENTER))` | `radius` is the **apothem** of the tiling cell (centre to flat side) unless `major_radius=True`: neighbours are 2 × radius apart. Columns are √3 × radius apart and every other column is shifted half a step. It lines up with `RegularPolygon(r, 6, major_radius=False)` (corners on ±X). For holes `cell` across the flats with `web` between them: `radius = (cell + web) / 2`. |
| `Locations` | `(*points)` | Tuples, `Vector`s, `Location`s, faces, planes: whatever points the feature needs. |
| `mirror` | `mirror(shape, about=Plane.YZ)` | A copy mirrored across a plane (default: across X = 0). Build one side and mirror it: `part + [g, mirror(g, about=Plane.YZ)]`. |

```python
from build123d import HexLocations, PolarLocations

pts = [loc.position for loc in HexLocations(5, 3, 2)]
assert sorted(round(p.Y, 2) for p in pts if abs(p.X) < 1e-9) == [-2.5, 7.5]  # the middle column, shifted
assert min((a - b).length for i, a in enumerate(pts) for b in pts[i + 1:]) == 10  # 2 x radius
arc = [loc.position for loc in PolarLocations(10, 3, 0, 180, endpoint=True)]
assert [round(p.X, 6) for p in arc] == [10, 0, -10]
```

## Mirror and symmetry

A part symmetric about a plane is modeled once and mirrored: half the code and half the risk of
the two sides drifting apart. `mirror(shape, about=Plane.YZ)` mirrors across X = 0,
`Plane.XZ` across Y = 0. The `remix_bracket` example builds one gusset and mirrors it. For a whole
piece that is a mirror of another, build it once with `@functools.cache` and mirror the result
(the guide's "Big and multi-piece projects"); do not build it twice.

## Pattern or one feature?

- **A pattern** when the copies are separate features: holes, bosses, ribs, slots, cells.
- **One swept, lofted or revolved feature** when they are continuous: a thread, flutes around a
  vase (`patterned_surface`), a spiral ridge (`twisted_loft`), a knurl along a helix. A few
  hundred copies of a small feature are fine; thousands of tiny ones (a fine knurl, a dense mesh)
  make thousands of faces, and every check and section slows with them (the build report
  flags a piece over ~1,500 faces).
- **Text in a row** (labels for a coupon, numbers on a dial): one `Text` per label, collected in a
  list and cut once: `part -= [Pos(x, y, top) * extrude(Text(s, 5), -0.6) for (x, y), s in ...]`
  (`text_label` gives the depth and size rules).

## Printing patterned features

The numbers are from [the design rules](../BEST_PRACTICES.md):

- **Holes**: at least 1–2 mm across; the holes check warns below 1 mm (BP-H5). Model them at the
  printed size plus `HOLE_COMP` (BP-H1).
- **Web between features**: a wall at least one line wide prints (BP-W1); for strength 2–4 whole
  lines, 0.9–1.8 mm at a 0.4 mm nozzle (BP-W2, W3). Gaps under ~0.5 mm close up (BP-W7). The
  thin-feature check measures webs.
- **Horizontal holes in a row** (holes in a wall printed standing) sag at the top: use
  `teardrop_hole` copies, or turn the part so they are vertical (BP-H3).
- **Hex cells in a standing wall**: turn them so a corner points up. Its roof is then two
  60-degree slopes; a flat side up is a bridge (BP-O1, O3). `hex_grille` puts corners on ±X:
  `Rot(0, 0, 90) * hex_grille(length, width, ...)` puts them on ±Y, which points up once the
  cutter is laid on a wall whose local Y is Z (`Plane.XZ * ...`).
- **Slots in a standing wall**: run them vertically, or keep the roof short (a bridge as wide as
  the slot, BP-O3).
- **Ribs and gussets** as thick as the wall, at least ~1.5 mm (BP-R4, R5).
- **Lightening a loaded part**: keep a solid border and solid rings around holes and bosses. It is
  the walls that carry the load, not the infill (BP-W4).
