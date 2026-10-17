# Checks API

`checks(d)` in a part script returns a list of check objects, all importable from
`b123d_print`. What each check does is described in [The checks](../using/checks.md); this
page lists their arguments.

```python
from b123d_print import Overhang, Probe, Wall

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
    ]
```

`part` is a name from `build()` (a script that returns a single part uses `""`).

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
| `bridges_ok` | `True` | flat ceilings never fail; a bridge between two walls prints, one hanging off a single wall does not, so look at a section |

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

## `View`

Not a check: a cross-section saved as a PNG with every export, returned by `views(d)`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `plane` | — | `"XY"` (`at` = Z), `"XZ"` (`at` = Y) or `"YZ"` (`at` = X) |
| `at` | — | position, mm |
| `title` | `""` | caption |
| `parts` | `None` | names from `build()` to include; default the assembly if there is one, else all parts |
