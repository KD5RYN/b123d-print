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
| `assembly(d)` | no | `[(part, color, label), ...]` in assembled position (use [`place_on` / `align_axis`](../using/fit.md#placing-pieces-by-contact) to place pieces by face contact and hole axes), plus simple stand-ins for what the parts mate with (a board, a sensor, a screw), labeled `"... (stand-in)"`; the overlap check and the [fit check](../using/fit.md) use it |
| `joints(d)` | no | `[("peg", "socket", clearance), ...]`: male/female pairs of `assembly(d)` labels that are intentional fits; the [fit check](../using/fit.md) measures them against their own clearance |
| `views(d)` | no | `[View(...)]` cross-sections saved with every export |
| `templates(d)` | no | `[Template.slice(...), Template.face_of(...), Template.crop(...)]` [fit-test templates](../using/templates.md) written with every export ([arguments](checks-api.md#template)) |
| `hardware(d)` | no | `[Hardware(...), ...]`: bought parts for the whole variant assembly, in the print sheet and optional JSON BOM ([declared hardware](#declared-hardware)) |
| `checks(d)` | no | `[Wall(...), Overhang(...), Probe(...), ...]` — see [Checks API](checks-api.md); moving parts are declared here too, as `Motion(...)` or `Slide(...)` on `assembly(d)` labels ([motion clearance](../using/checks.md#motion-clearance)) |
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

**Check findings and export files are reused too.** In the same `out/.cache/`, the worker keeps
each piece's findings of the per-piece checks (thin features, overhang, holes, bed edge,
tip-over, gaps within the piece, and the script's `Wall` and `Probe` checks in the print frame),
keyed by the piece's geometry, the check's arguments, your settings and the b123d-print version.
A `check` after changing one piece rechecks that piece; the checks across pieces (overlap,
`Mates`, a `Gap` between two parts, `Wall` and `Probe` with `frame="assembly"`, `Motion`,
`Slide`) and the printer's build-volume fit run every time. `export` stamps each file it writes
with what it was made from (the shapes' geometry, names and colors, the format and the code): a
file still as written for the same inputs is not written again, and a fit-test template is read
back instead of cut again. A file you edit, replace or delete is written again. `fresh=True`
reads none of it and writes everything again. Template previews (`_template_<id>.png` and
`_where.png`) are rendered small (about 800 px wide) by `export`; `make_template` renders them at
full size.

**One part script per piece** is the other way: pieces that share little but their dimensions
build, check and export on their own. Two scripts cannot share a dimensions module by
convention yet: a script imports only from its own folder.

## Moving parts

A hinge, flip lid, latch or slider is placed in `assembly(d)` at one end of its motion (closed,
or flat as printed), and its motion is declared in `checks(d)`: `Motion(label, axis_point,
axis_dir, start_deg, end_deg, against=..., min_clearance=...)` for a rotation, `Slide(label,
direction, distance, ...)` for a straight move. `check` sweeps it and fails on the first
collision; see [motion clearance](../using/checks.md#motion-clearance) and the
[`flip_hinge`](examples.md#flip_hinge) example. A print-in-place mechanism is one printed piece
of several solids: split it into its solids in `assembly(d)` so each can move.

## For the design review

Optional names the [design review](../using/design-review.md) reads, in `Dims` (so a variant can
override them) or at module level:

| Name | Example | What |
| --- | --- | --- |
| `STYLE` | `STYLE: str = "modern"` | `functional`, `modern`, `least_cost`, `rugged`, `soft` or `structural`; `""` (the template's) uses the workspace's `style`, else functional |
| `SHOW` | `SHOW = ["+Y", "+Z"]` | the sides seen in use, in print orientation; surface findings are limited to them |
| `UP` | `UP = "+Y"` | the side that points up in use (print orientation), for the water-trap check; default `+Z` |
| `EDGES` | `EDGES = "chamfer"` | the edge language: `chamfer` or `fillet`; functional with `chamfer` is the industrial look |

## For the print sheet

`PRINT_NOTES` (in `Dims` or at module level): a string or a list of strings that the
[print sheet](../using/slicing.md#the-print-sheet) lists under "Assembly and notes": the order
to put the pieces together, the glue, inserts to set, a brim. For example
`PRINT_NOTES: tuple = ("Set the M3 inserts at 230 C before closing the lid.",)`.

### Print intent

The print sheet's advice is inferred from the geometry and the style; it cannot know what the
part is for. A calibration coupon that tests holes printed **without** supports would be told to
use them. `PRINT` states how the part must be printed:

```python
PRINT = {
    "supports": "none",
    "orientation": "locked",
    "why": "a calibration coupon: it measures holes printed without supports",
}
```

| Key | Takes | Effect |
| --- | --- | --- |
| `supports` | `"none"`, `"auto"`, `"build_plate_only"`, `"tree"` | the print sheet's supports advice; `"none"` also makes the overhang check report overhangs and long bridges as accepted |
| `walls` | an int | the walls (perimeters) the sheet recommends and the estimates use |
| `infill` | a percent, 0-100 | the infill the sheet recommends and the estimates use |
| `infill_pattern` | a string, e.g. `"gyroid"` | named next to the infill |
| `brim` | `True` / `False`, or a width in mm | the sheet's brim advice (and its tip-over line) |
| `orientation` | `"locked"` | don't re-orient: the sheet says so and `suggest_orientation` ranks for information only |
| `why` | free text | **required** whenever anything else is set; shown next to every setting it overrides |

- An unknown key or a bad value is an error that lists the valid keys (a typo such as
  `suports` never passes silently); `check` reports it as a build failure.
- **It overrides the recommendation, never the facts.** The sheet still says "5 face(s), ~100 mm²
  would need supports by the geometry", then **Supports: none, set by the part**: the why.
- **A declared intent never turns a FAIL into a pass.** `supports: "none"` changes the overhang
  and bridge warnings only (see [accepted findings](../using/checks.md#accepted-findings)).
- Put it at module level, or in `Dims` so a variant can override it (the `Dims` value replaces the
  module's). In a frozen `Dims` keep it out of the hash, so `functools.cache` on piece functions
  still works: `PRINT: dict | None = field(default=None, hash=False, compare=False)`, then
  `VARIANTS = {"": {}, "tall": dict(PRINT={"supports": "tree", "why": "..."})}`.
- Your own defaults for `supports`, `walls` and `infill` go in the [settings](../using/settings.md#keys);
  a part's `PRINT` wins over them. The calibration coupons in the examples declare
  `supports: "none"`.

## Declared hardware

Declare bought parts explicitly; a hole or a mesh cannot identify screw length, head style,
thread, material or insert model. `hardware(d)` gets the selected variant's dimensions:

```python
from b123d_print import Hardware

def hardware(d):
    return [
        Hardware("lid-screw", "Lid screw", d.SCREW_COUNT,
                 specification="M3 × 10 mm, ISO 4762 socket head, stainless A2",
                 location="lid corners", source_url="https://example.org/part-data"),
        Hardware("magnet", "Magnet", 2, note="Confirm grade and coating before ordering"),
    ]
```

This is an API illustration, not a printed example. Each entry is a `Hardware` or a mapping
with the same fields: required `id` (stable letters/numbers/`_`/`.`/`-`), nonempty `description`,
positive integer `quantity`; optional `specification`, `location`, `note`, `source_url`, `source`,
`units`, boolean `needs_confirmation`, and `model`. Duplicate IDs, invalid quantities (including booleans), unknown mapping
fields and malformed hooks fail export with an explanation. Use one entry per ID with its total
quantity; `location` can describe several positions. An omitted/empty specification is marked
**Needs confirmation** (`needs_confirmation: true` in JSON). Supplying a specification is an
author declaration, not an independent completeness check: set `needs_confirmation=True` for a
partial specification (for example, a known M3 thread with unknown length/head). Both outputs
retain the partial text and mark it for confirmation. Keep assembly instructions in
`PRINT_NOTES`.

The table (`print` format) and optional `<name>[_<variant>]_hardware.json` (`hardware` format)
use the same entries sorted by ID. Quantities always cover the **whole selected variant's
assembly**, even when exporting one printable piece with `parts=` / `--only`. They never scale
by piece selection. `all` includes both formats; neither changes the default export formats.
An absent hook preserves the existing sheet; JSON requested without a hook has `declared: false`
and an empty list, which does not assert that no hardware is needed. An explicit empty hook
has `declared: true`. URLs and descriptions are escaped table data; they are never fetched or
executed. Scripts retain the existing network restrictions.

To order from it, the `bom` and `bom_csv` formats (`_bom.md`, `_bom.csv`) and the `hardware_list`
tool (CLI `b123d-print bom`) turn the same entries into a shopping list: identical items (same
description and specification) are merged with their quantities summed, and unconfirmed items say
**check before ordering** ([what do I need to buy?](../using/slicing.md#what-do-i-need-to-buy)).

### Library and custom model stand-ins

Reuse `bd_warehouse`'s metadata for its `Screw`, `Nut` (including `HeatSetNut`) and `Washer`
objects with `Hardware.from_bd_warehouse("lid-screw", screw, quantity=4)`. This copies the
library's `info` (class, standard/type, thread size, and screw length/hand) into `specification`,
retaining full insert size selectors and left-hand nut metadata that `info` omits. It
records the library class in `source` and the model coordinate units as `mm`. It also retains
the object as `model`. Override `description`, `specification`, `location`, `note` or
`source_url` as needed, especially to specify material/finish or a supplier part number. These
are library declarations, not inferred mesh specifications. Other library objects can use the
ordinary `Hardware` constructor.

For custom hardware, associate a procedural shape or an imported STL/STEP/3MF with the entry's
`model`. Supply `source` and `units` explicitly when a model is supplied. A lazy model factory
keeps geometry conversion out of BOM-only work:

```python
import functools
from b123d_print import Hardware, import_model

@functools.cache
def bought_sensor(d):
    return Hardware("sensor", "Supplier sensor", 1,
                    specification="Supplier ABC-123, revision B",
                    source="ref/sensor.stl", units="inch",
                    model=lambda: import_model("ref/sensor.stl", scale="inch"))

def hardware(d):
    return [bought_sensor(d)]

def assembly(d):
    sensor = bought_sensor(d)
    # Place this shape with place_on/align_axis (or Pos/Rot) in assembly coordinates.
    shape = sensor.model()
    return [(printed_base(d), "orange", "base"), sensor.standin(shape)]
```

This is also an API illustration. `units` records the **source model's units**; it does not
scale geometry. Match it to `import_model(..., scale=...)`, which converts to build123d's mm.
`source` identifies the file or provenance and `source_url` optionally identifies its source.
STL has no trustworthy unit or thread metadata: ask for units/specification and retain the
existing import warnings and checks. A procedural stand-in can use `source="measured envelope"`,
`units="mm"`. Nothing in a mesh is used to fill a specification.

`item.standin(shape=None, color="silver", label=None)` returns the existing
`(shape, color, "<id>[: label] (stand-in)")` assembly tuple. With no shape argument it evaluates
the entry's model. Pass a placed shape to use the existing contact/axis helpers; use distinct
labels when placing several instances. The label retains the BOM ID, and existing fit and
collision checks see a stand-in. Call once per placed instance: this does not count placements
or verify their number against the declared quantity. Only `build(d)` defines printable pieces;
keep hardware models out of it. The model and its factory are never serialized, and BOM export
never calls the factory. Keep imported assets in `ref/` so the normal handoff includes them.

### JSON format (schema version 1)

```json
{
  "schema_version": 1,
  "variant": "standard",
  "scope": "whole_assembly",
  "declared": true,
  "items": [
    {
      "id": "magnet",
      "description": "Magnet",
      "quantity": 2,
      "specification": "",
      "location": "",
      "note": "Confirm grade and coating before ordering",
      "source_url": "",
      "source": "",
      "units": "",
      "needs_confirmation": true
    }
  ]
}
```

All metadata fields are strings except integer `quantity` and boolean `needs_confirmation`.
The default variant is `standard`; other variants use their key. Output is UTF-8, with sorted
JSON keys and ID-sorted entries, without timestamps. Repeated exports reuse unchanged files;
changes to the declaration, variant dimensions or rendered sheet content invalidate them.
Download links and `download_part` / SSH `pull` include these files through the normal flow;
when filtering, use `formats="print,hardware"` for both artifacts and the source/ref files.

## Values from the user's config

| Helper | Use |
| --- | --- |
| `hole_comp(__file__)` | `HOLE_COMP: float = hole_comp(__file__)`; add it to hole diameters when cutting ([Hole compensation](../using/hole-compensation.md)) |
| `clearance(__file__)` | `CLEARANCE: float = clearance(__file__)`; the default mating gap (0.2 mm) |
| `printer(__file__)` | the active [printer profile](../using/printer-profiles.md), or `None` in generic mode |

## Placing assembly pieces

| Helper | Use |
| --- | --- |
| `place_on(piece, face_a, target, face_b, offset=0, spin=0, shift=(0, 0))` | move `piece` so flat `face_a` rests on `target`'s flat `face_b` (coplanar, opposed normals); faces by global side (`"bottom"`, `"top"`, `"+X"`), `list_faces` id, point or `Face`. See [Fit between pieces](../using/fit.md#placing-pieces-by-contact) |
| `align_axis(piece, axis_a, target, axis_b?, clock=...)` | line up round holes, bosses or pins across pieces (slides in the contact plane after `place_on`; `clock=` clocks around a second hole pair) |

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
