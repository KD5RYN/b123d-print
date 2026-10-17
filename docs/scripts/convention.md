# The part script

One script per part, at `parts/<name>/<name>.py`. It is ordinary
[build123d](https://build123d.readthedocs.io) Python with a few conventions, so every tool
(and every agent) knows where to find the dimensions, the variants and the checks.

```python
from dataclasses import dataclass
from build123d import Align, Box, Cylinder, Mode, Part
from b123d_print import View, Wall, hole_comp

BED = (Align.CENTER, Align.CENTER, Align.MIN)

@dataclass(frozen=True)
class Dims:                      # every dimension named, in mm, with its source
    W: float = 30.0              # typed measurement
    H: float = 8.0
    HOLE_D: float = 3.4          # M3 clearance, target printed size
    CBORE_D: float = 6.5
    CBORE_DEPTH: float = 3.0
    HOLE_COMP: float = hole_comp(__file__)   # from YOUR config, default 0

VARIANTS = {"": {}, "wide": dict(W=40.0)}   # overrides only

def build(d: Dims) -> Part:      # print orientation, bed at Z=0
    p = Box(d.W, d.W, d.H, align=BED)
    p -= Cylinder((d.HOLE_D + d.HOLE_COMP) / 2, 50, mode=Mode.PRIVATE)
    p -= Cylinder((d.CBORE_D + d.HOLE_COMP) / 2, d.CBORE_DEPTH, align=BED, mode=Mode.PRIVATE)
    return p

def views(d):                    # sections saved with every export
    return [View("XZ", 0.0, "through the hole")]

def checks(d):                   # how much material is left around the counterbore?
    return [Wall("", "XY", d.CBORE_DEPTH / 2, near=(0, 0), radius=d.W, label="around the counterbore")]

if __name__ == "__main__":
    from b123d_print import run
    run(__file__)
```

## What a script defines

| Name | Required | What |
| --- | --- | --- |
| `Dims` | by convention | frozen dataclass; every dimension an UPPER_CASE field in mm with a comment saying where it came from; derived values as `@property` |
| `VARIANTS` | no (default: only the standard part) | `{"": {}, "140": dict(PLATE_W=140.0)}` — overrides only; `""` is the standard part; output files get the key as a suffix |
| `build(d)` | yes | the printable part, or `{"name": part}` for several, in print orientation, bottom face on Z=0 |
| `assembly(d)` | no | `[(part, color, label), ...]` in assembled position, plus simple stand-ins for what the parts mate with (a board, a sensor, a screw); the overlap check uses it |
| `views(d)` | no | `[View(...)]` cross-sections saved with every export |
| `checks(d)` | no | `[Wall(...), Overhang(...), Probe(...), ...]` — see [Checks API](checks-api.md) |

A script with only a module-level `part = ...` (no `Dims`) also works, without variants.

## Values from the user's config

| Helper | Use |
| --- | --- |
| `hole_comp(__file__)` | `HOLE_COMP: float = hole_comp(__file__)`; add it to hole diameters when cutting ([Hole compensation](../using/hole-compensation.md)) |
| `clearance(__file__)` | `CLEARANCE: float = clearance(__file__)`; the default mating gap (0.2 mm) |
| `printer(__file__)` | the active [printer profile](../using/printer-profiles.md), or `None` in generic mode |

Never hard-code a hole compensation from somewhere else; keep hole fields at the size you want
printed.

`new_part` / `b123d-print new` start from a template with all of this in place. The rules for
agents (and humans) writing scripts are in [Workflow rules](rules.md); the modeling API itself
is in the [build123d docs](https://build123d.readthedocs.io). For real parts, see the
[Examples](examples.md).
