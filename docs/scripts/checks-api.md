# Checks API

`checks(d)` in a part script returns a list of check objects, all importable from
`b123d_print`. What each check does is described in [The checks](../using/checks.md); this
page lists their arguments.

```python
from b123d_print import Gap, Overhang, Probe, ThinFeature, Wall

def checks(d):
    return [
        # thinnest material in the section, within `radius` of `near` (the section's 2D coords:
        # XY -> (x, y), XZ -> (x, z), YZ -> (y, z)); fails below `min` (default: config min_wall)
        Wall("base", "XY", d.FLOOR_T + 1.0, near=(0, 0), radius=5, label="standoff pilot"),
        # downward faces > 45 deg are always reported; fail=True for parts that must print
        # without supports (flat bridges are allowed unless bridges_ok=False)
        Overhang("cover", fail=True),
        # material must exist (or not) in a small box: "roof is closed", "channel is clear"
        Probe("cover", (0, 10, 70), (1, 1, 0.5), expect="solid", label="roof closed"),
        # automatic, listed only to change it: a living hinge is thin on purpose
        ThinFeature("lid", ignore=[((0, 20, 0.25), (40, 2, 0.6))]),
        # the gap between two assembly parts inside a box: the lid's sliding fit
        Gap("lid", "base", min=d.CLEARANCE, max=d.CLEARANCE + 0.1, within=((0, 0, 30), (60, 60, 4))),
    ]
```

The automatic checks (`Overhang`, `ThinFeature`, `Holes`, `BedEdge`, `Gap`, `Fit`) run for every
part; list one for a part to replace its automatic copy with your arguments.

`part` is a name from `build()`. A script whose `build()` returns a single `Part` names it
`"part"` (`""` and the script's own name work too); return `{"name": part, ...}` to choose names.

## `Wall`

Thinnest wall in a section, optionally only around one feature. Add one wherever a cut goes
deeper than the wall it starts in, slicing just past the wall.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `plane` | — | `"XY"`, `"XZ"` or `"YZ"` |
| `at` | — | position of the section along the third axis, mm |
| `near` | `None` | 2D point in the section's coordinates; only material near it counts |
| `radius` | `None` | how far from `near` to look, mm |
| `min` | `None` | fail below this, mm (default: the `min_wall` setting) |
| `label` | `""` | shown in the report |
| `frame` | `"print"` | `"print"`: `part` is a name from `build()`, coordinates as printed; `"assembly"`: `part` is a label from `assembly(d)`, coordinates as assembled |

The result says what was measured: the section's area, how far `near` is from material (0 when
it is inside material) and the region within `radius`. It **fails** when the section misses the
part, when nothing lies within `radius` of `near` (the check would measure nothing), or when
`near` is deep inside solid material with no wall within `radius`.

## `Overhang`

Downward faces steeper than the limit, in print orientation. Added automatically (report only)
for every part a script does not list.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `max_angle` | `None` | degrees from vertical (default: the `max_overhang` setting) |
| `fail` | `False` | fail instead of warn: for parts meant to print without supports |
| `min_area` | `1.0` | mm²; smaller flagged areas are listed but not counted |
| `ignore_below` | `0.0` | mm above the bed to ignore, e.g. `1.0` to accept a small fillet on a bed edge |
| `bridges_ok` | `True` | bridges (flat ceilings resting on walls on two opposite sides) never fail; a cantilever (hanging off one side) is an overhang |
| `max_bridge` | `None` | mm; longer bridges warn (default: the `max_bridge` setting) |

## `ThinFeature`

Walls thinner than one line width fail, thinner than `min_wall` warn; knife edges warn.
Automatic for every part.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `min` | `None` | warn below, mm (default: the `min_wall` setting) |
| `fail_below` | `None` | fail below, mm (default: one line width, 0.45 in generic mode) |
| `ignore` | `()` | boxes `((cx, cy, cz), (sx, sy, sz))` where thin is intended: a living hinge, engraved labels |
| `step` | `2.0` | mm between the extra sections |
| `planes` | `("XY", "XZ", "YZ")` | section planes; `()` turns the check off |

## `Holes`

Lists round holes; warns on horizontal holes with a round top and on tiny holes. Automatic for
every part.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `min_diameter` | `1.0` | mm; smaller holes warn |
| `round_top_from` | `2.0` | mm; horizontal holes this size and up need a teardrop or flat roof |

## `BedEdge`

Warns on fillets (curved faces) that start on the bed. Automatic for every part.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `min_area` | `0.2` | mm² of steep surface before a face counts |

## `Gap`

The smallest gap between two parts, or between the solids of one part printed in place.
Automatic (with `other=None`) for every part made of several solids.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name or `assembly(d)` label (assembled position preferred), or a `Part` |
| `other` | `None` | the second part; `None`: between the separate solids of `part` |
| `min` | `None` | fail below, mm (default: `pip_clearance` for solids of one part, `clearance` for two parts) |
| `max` | `None` | fail above, mm |
| `within` | `None` | box `((cx, cy, cz), (sx, sy, sz))`: only measure inside it, e.g. one mating face |
| `label` | `""` | shown in the report |

## `Probe`

Material must be present (`expect="solid"`) or absent (`expect="empty"`) in a small box: for
design intent the other checks cannot see.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name, or a `Part` (e.g. one in assembled position) |
| `center` | — | box center `(x, y, z)`, mm |
| `size` | — | box size `(x, y, z)`, mm |
| `expect` | `"solid"` | `"solid"` or `"empty"` |
| `fill` | `0.98` | fraction of the box that counts as solid; empty means at most `1 - fill` |
| `label` | `""` | shown in the report |
| `frame` | `"print"` | `"print"`: `part` is a name from `build()`; `"assembly"`: a label from `assembly(d)`, box in assembled coordinates |

The result shows the box against the part's bounding box. A box entirely outside it **fails**
when `expect="solid"` and **warns** when `expect="empty"`: an empty box away from the part
proves nothing about the part, unless the point is that nothing reaches there.

## Which frame

Print orientation and assembled position are often different (a lid printed upside down), and
the print orientation may change while you work. A Wall or Probe declared in print coordinates
then points at a different feature, and may still pass. If the part has an `assembly(d)`,
declare Wall and Probe with `frame="assembly"`: the coordinates are where the feature is in use
and do not move when the part is turned over. Keep `frame="print"` for parts without an
assembly. The automatic checks (overhang, thin, holes, bed edge, fit) are about printing and
always use the print orientation; `Gap` already prefers the assembled position.

## `Overlap`

Fails when two `assembly(d)` parts (stand-ins included) intersect. Added automatically when the
script has an `assembly`; list it yourself only to change its arguments.

| Argument | Default | Meaning |
| --- | --- | --- |
| `ignore` | `()` | label pairs allowed to overlap |
| `tol` | `0.01` | mm³ of intersection allowed |

## `Fit`

The part fits the active printer's build volume in print orientation. Added automatically for
every part; does nothing in generic mode.

| Argument | Default | Meaning |
| --- | --- | --- |
| `part` | — | part name |
| `margin` | `0.0` | mm kept free at each bed edge |

## `Mates`

[Fit between the pieces](../using/fit.md) of `assembly(d)`: overlaps, gaps under the clearance
and hole alignment across pieces. Not automatic: list it in `checks(d)` to run it with `check`
(the `check_fit` tool and `b123d-print fit` run it on any script with an assembly, with the
arguments given here). `from b123d_print import Mates`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `clearance` | `None` | mm per side two pieces must keep apart unless they touch; default the `clearance` setting |
| `hole_tol` | `0.2` | mm: partner holes further off-axis fail |
| `joints` | `()` | male/female pairs that are intentional fits: `("peg", "socket")`, `("peg", "socket", 0.1)`, `{"male": ..., "female": ..., "clearance": ...}` or objects with `male`/`female`/`clearance`; also read from the script's `joints(d)` |
| `ignore` | `()` | label pairs meant to overlap (a screw stand-in in its pilot hole) |
| `tol` | `0.01` | mm³ of overlap allowed |
| `max_pairs` | `60` | at most this many close pairs are measured, nearest first |
| `align` | `True` | also check hole alignment |
| `part` | `"assembly"` | the name findings are reported under |

## `View`

Not a check: a cross-section saved as a PNG with every export, returned by `views(d)`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `plane` | — | `"XY"` (`at` = Z), `"XZ"` (`at` = Y) or `"YZ"` (`at` = X) |
| `at` | — | position, mm |
| `title` | `""` | caption |
| `parts` | `None` | names from `build()` to include; default the assembly if there is one, else all parts |

## `Template`

Not a check either: a [fit-test template](../using/templates.md) written with every export,
returned by `templates(d)`. Make one with `Template.slice(plane, at, ...)`,
`Template.face_of(face, ...)` or `Template.crop(center, size, ...)`; keyword arguments as below.

| Argument | Default | Meaning |
| --- | --- | --- |
| `kind` | — | `"slice"`, `"face"` or `"crop"` (set by the constructors) |
| `plane` | `"XY"` | slice: `"XY"` (`at` = Z), `"XZ"` (`at` = Y) or `"YZ"` (`at` = X) |
| `at` | `0.0` | slice: where, mm; the slice is `thickness` thick, centered there (moved inward at the part's ends) |
| `face` | `None` | face: an id from `list_faces`, a side (`"bottom"`, `"top"`, `"front"`, `"back"`, `"left"`, `"right"` or `"-Z"`, `"+X"`, ...: the largest face facing that way) or a point `(x, y, z)` on the face |
| `center` | `(0, 0, 0)` | crop: the box's center, mm |
| `size` | `(20, 20, 10)` | crop: the box's size, mm |
| `thickness` | `1.2` | slice and face: mm |
| `label` | `True` | engrave `"<part> <id>"`, your own text, or `False` for none; skipped where there is no room |
| `base` | `True` | slice and crop: a 1 mm base plate joins separate pieces (and holds up a crop with little bed contact) |
| `part` | `None` | which printable part (default: the only one) |
| `name` | `""` | the template id in file names (default from the arguments: `xy3`, `face7`, `face_bottom`, `crop_10_0_5`) |
