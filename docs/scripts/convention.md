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
| `build(d)` | yes | the printable part, or `{"name": part}` for several, in print orientation, bottom face on Z=0; for several, the values may be zero-argument functions ([lazy pieces](#big-and-multi-piece-projects)) |
| `assembly(d)` | no | `[(part, color, label), ...]` in assembled position, plus simple stand-ins for what the parts mate with (a board, a sensor, a screw); the overlap check uses it |
| `views(d)` | no | `[View(...)]` cross-sections saved with every export |
| `templates(d)` | no | `[Template.slice(...), Template.face_of(...), Template.crop(...)]` [fit-test templates](../using/templates.md) written with every export ([arguments](checks-api.md#template)) |
| `checks(d)` | no | `[Wall(...), Overhang(...), Probe(...), ...]` — see [Checks API](checks-api.md) |
| `original(d)` | no | for a [remix](../using/remix.md): the original model placed as the remix is; default: what `build(d)` loaded with `import_model`. The automatic checks also run on it, so its findings are labeled inherited, and `before_after` and export compare the remix with it |

A script with only a module-level `part = ...` (no `Dims`) also works, without variants.

## Big and multi-piece projects

When `build(d)` returns several pieces, return each one as a zero-argument function: a **lazy
piece**, built only when it is needed.

```python
import functools

@functools.cache                  # Dims is frozen, so d can be the cache key: built once per process
def end_rear(d):
    ...                           # the slow, curved piece

def build(d):
    return {
        "end_rear": lambda: end_rear(d),
        "end_front": lambda: mirror(end_rear(d), Plane.YZ),   # a mirror image, not a second build
        "key": lambda: key(d),
    }
```

Then `parts="end_rear"` on `build_part`, `render_preview`, `section` and `export`, or
`--only end_rear` on `b123d-print build` and on the part script itself, builds just that piece.
Plain shapes (`{"a": part_a, "b": part_b}`) keep working, but `build(d)` builds them all every
time. `assembly(d)` calls the piece functions itself (`end_rear(d)`), not the lambdas.

**The timing report.** `build_part` and `b123d-print build` list each piece's face count and
build time, and whether it came from the cache. A piece over ~1,500 faces or ~10 s gets the
hint *dense polyline or many stacked offsets: fewer curve points, a spline, or build once and
mirror/copy the result*. Build time grows with the points on a curve: a 96-point polyline that is
offset and extruded several times makes thousands of faces, and halving the points halves the
time. Plain (eager) pieces have no time of their own; the report gives `build(d)`'s.

**The build cache.** The MCP server's sandboxed worker saves each piece it builds in the part's
`out/.cache/` (one BREP file per piece and per assembly item, with a JSON note), and the next
`build_part`, `render_preview`, `section`, `check`, `export`, `design_metrics`, `list_faces`,
`make_template` or `before_after` reads it back instead of building again. An entry is used only
while all of these stay the same:

- every `.py` file in the part's folder (the script and its helpers), the variant and its `Dims`;
- the settings a build can read (`hole_comp`, the clearances, `min_wall`, the printer and
  material, ...), and the versions of b123d-print, build123d and OCP;
- every other file the build read in the part's folder (a table, a model in `ref/`), by its hash.

Anything else is a miss, and so is an entry that does not read back exactly (its BREP hash, face
count and volume are checked): the piece is simply built again. `assembly(d)` is cached the same
way. Not cached: a build that reads a file elsewhere in the workspace (nothing could tell when it
changes), a build that loads a model with `import_model` (a remix: the conversion has its own
cache, and the checks need the original it loaded) and `original(d)`. `fresh=True` on a tool
rebuilds and overwrites the entry; `B123D_PRINT_NO_CACHE=1` on the server turns the cache off.
The CLI and `uv run` build in your own process and do not use it. The build has to depend only on
these inputs: a script that reads the clock or random numbers gets the same pieces back.

**One part script per piece** is the other way: pieces that share little but their dimensions
build, check and export on their own. Two scripts cannot share a dimensions module by
convention yet: a script imports only from its own folder.

## For the design review

Optional names the [design review](../using/design-review.md) reads, in `Dims` (so a variant can
override them) or at module level:

| Name | Example | What |
| --- | --- | --- |
| `STYLE` | `STYLE: str = "modern"` | `functional`, `modern`, `least_cost`, `rugged`, `soft` or `structural`; `""` (the template's) uses the workspace's `style`, else functional |
| `SHOW` | `SHOW = ["+Y", "+Z"]` | the sides seen in use, in print orientation; surface findings are limited to them |
| `UP` | `UP = "+Y"` | the side that points up in use (print orientation), for the water-trap check; default `+Z` |
| `EDGES` | `EDGES = "chamfer"` | the edge language: `chamfer` or `fillet`; functional with `chamfer` is the industrial look |

## Values from the user's config

| Helper | Use |
| --- | --- |
| `hole_comp(__file__)` | `HOLE_COMP: float = hole_comp(__file__)`; add it to hole diameters when cutting ([Hole compensation](../using/hole-compensation.md)) |
| `clearance(__file__)` | `CLEARANCE: float = clearance(__file__)`; the default mating gap (0.2 mm) |
| `printer(__file__)` | the active [printer profile](../using/printer-profiles.md), or `None` in generic mode |

## Splitting into pieces

| Helper | Use |
| --- | --- |
| `split(part, plane, joints, clearance)` | from `b123d_print.joints`: cut a part at a plane into two pieces with matching joint features (`Dowel`, `Bowtie`, `Dovetail`, `Lap`, `Insert`), the female `clearance` bigger on every side; loose keys and pins come back laid flat. See [Splitting parts](../using/splitting.md) |

## Starting from an existing model

| Helper | Use |
| --- | --- |
| `import_model(path, scale?, max_triangles?, merge?, script?)` | an STL, 3MF or STEP as a solid to change: `base = import_model("ref/bracket.stl")`; paths are relative to the script's folder (`ref/`) or the workspace (`refs/`). See [Remixing a part](../using/remix.md) |

Never hard-code a hole compensation from somewhere else; keep hole fields at the size you want
printed.

`new_part` / `b123d-print new` start from a template with all of this in place. The rules for
agents (and humans) writing scripts are in [Workflow rules](rules.md); the modeling API itself
is in the [build123d docs](https://build123d.readthedocs.io). For real parts, see the
[Examples](examples.md).
