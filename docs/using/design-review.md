# Design review

The [checks](checks.md) answer "will it print and will it fit". The design review comes after
them: is the part a good design for its purpose and for the **style** you chose? The AI looks
at the numbers from `design_metrics` and at renders, then suggests concrete changes. It never
changes the part without your OK.

The rules it applies, with their sources, are on [Design styles and review](../DESIGN_GUIDE.md)
(IDs `DS-*`).

## Styles

| Style | For | What the review pushes |
| --- | --- | --- |
| `functional` (default) | brackets, mounts, jigs | visible faces oriented well, no supports on show faces, a corner for the seam, one or two screw sizes |
| `modern` | things on a desk or a wall | one radius language (an edge-break size and at most one styling radius), ≥ 90 % of edges rounded or chamfered, symmetry where the function allows, screws out of sight |
| `least_cost` | spares, prototypes, many copies | less support, pocketed bulk, several copies when a small part is all layer time |
| `rugged` | outdoors, in a car, dropped | ASA (or PETG in shade) instead of PLA, no water traps, rounded corners, inserts and stainless screws |
| `soft` | held in the hand | rounded edges, grips 30-40 mm across, no gently domed tops that show layer steps |
| `structural` | brackets, mounts, clamps, hooks, hinges, gears, tool holders | the load along the layers, filleted inside corners (r ≥ half the wall), walls ≥ 3 lines and 4-6 walls in the slicer, gussets, inserts and washers |
| `organic` | fruit, plants, animals, figurines, shells, sculpture | modeled from sections along curves (not boxes and cylinders), sections that vary along the length, joins blended with big lofted collars, a few features and a little asymmetry; printed lying along its curve on a flat base, tree supports, variable layer height |
| `decorative` | vases, planters, lamp shades, ornaments | a twist, a taper or a few strong pattern features that read from a step back; whether it can print in vase mode (one closed contour per layer, no lean past the overhang limit); thin even walls and an air gap to the bulb for lamp shades |

The industrial look (chamfers and exposed standard screws) is `functional` with
`EDGES = "chamfer"`. `structural` is about the load path; `rugged` about sun, water and heat:
a bracket outdoors may need both, so pick the one that matters more and ask about the other.
`organic` (also `natural`, `sculpted`, `figurine`) is about how a natural object is modeled, not a
taste for curves: start it from the [organic recipes](recipes.md#organic-shapes) (`spine_loft`,
`tapered_sweep`, `organic_blend`, `flat_base`); the [`banana`](../scripts/examples.md#banana)
example shows them together.
You can also [write your own styles](#custom-styles).

Pick one per part, in the script's `Dims`:

```python
@dataclass(frozen=True)
class Dims:
    ...
    STYLE: str = "rugged"  # typed by the user
```

A variant can change it (`VARIANTS = {"desk": dict(STYLE="modern")}`). Without `STYLE`, the
workspace's `style` setting applies, else `functional`. For a new part the AI asks once if you
have said nothing about looks.

Optional, for a more precise review (`Dims` or module level, print orientation):

- `SHOW = ["+Y", "+Z"]`: the sides seen in use. Layer-step and support findings are limited to
  them. Without it the AI asks, when it matters, or judges every face.
- `UP = "+Y"`: the side that points up in use, for the water-trap check.
- `EDGES = "chamfer"` or `"fillet"`: the edge language the part should keep to.

## Custom styles

A style is a small TOML file, the same kind as the built-in ones. Put yours in
`~/.config/b123d-print/styles/<name>.toml` (for all your workspaces) or in `styles/<name>.toml`
next to the workspace's `b123d-print.toml` (for one project). The first one found wins:
workspace, then yours, then built-in, so **a file with a built-in's name replaces it**.
`based_on` starts from another style: every field the file sets replaces the inherited one (per
field, including `review`, which is replaced, not appended), and `false` switches an inherited
threshold off.

```toml
# ~/.config/b123d-print/styles/soft_modern.toml
label = "Soft modern"
description = "Modern, with 2 mm fillets everywhere and no visible screws."
based_on = "modern"
edges = "fillet"
min_treated_edge_share = 1.0   # every outside edge rounded
max_edge_break_sizes = 0       # no small edge breaks...
max_styling_radii = 1          # ...one radius: the 2 mm one
max_chamfer_sizes = false      # inherited from modern: switched off (bed chamfers are fine)
review = """
Look for: 2 mm fillets on every outside edge and nothing else; no screw heads on any visible
side (use SHOW); the rest as in modern [DS-G1, DS-G3].
Typical: "the 1 mm and 3 mm fillets become 2 mm".
"""
```

Use it like a built-in: `STYLE = "soft_modern"`.

`b123d-print styles` lists every style and where it comes from; `b123d-print styles soft_modern`
shows one with `based_on` applied. Over MCP, `list_parts` lists them. A field the file does not
know, a wrong type, a missing `based_on` style or a loop is an error that says which file and
which field.

| Field | Type | What it does |
| --- | --- | --- |
| `label` | text | the name shown in reports |
| `description` | text | one line: what the style is for |
| `based_on` | text | another style this one starts from |
| `edges` | `"chamfer"`, `"fillet"` or `""` | the edge language for parts that set no `EDGES` |
| `review` | text | what the reviewer looks for; printed at the end of `design_metrics` and used as the style's rubric |
| `max_shallow_slope_share` | number | suggest when more of the up-facing (or `SHOW`) area than this is tilted 1-30° from flat (layer steps; DS-S1) |
| `supports_on_visible` | true/false | suggest when supports sit under a visible side (`SHOW` with `-Z`; DS-S2) |
| `seam_note` | true/false | note when no contour corner can take the seam (DS-S3) |
| `max_screw_sizes` | whole number | suggest when more distinct screw sizes than this appear (DS-G3) |
| `min_treated_edge_share` | number | suggest when less of the outside edge length than this is rounded or chamfered (DS-G1) |
| `max_edge_break_sizes` | whole number | suggest when more distinct radii up to 1 mm than this appear (DS-G1) |
| `max_styling_radii` | whole number | suggest when more distinct radii over 1 mm than this appear (DS-G1) |
| `max_chamfer_sizes` | whole number | suggest when more distinct chamfer sizes than this appear (DS-G1) |
| `max_sharp_edge_share` | number | suggest when more of the outside edge length than this is sharp (DS-G8, DS-R7) |
| `min_symmetry` | number | note when the best mirror symmetry is below this (DS-G7) |
| `hidden_screws_note` | true/false | note to keep screw heads off the `SHOW` sides (DS-G3) |
| `max_support_share` | number | suggest when supports weigh more than this share of the part (DS-C4) |
| `max_infill_share` | number | suggest pocketing when infill is more than this share of the filament (DS-C5) |
| `max_layer_time_share` | number | suggest printing several when per-layer time is more than this share (DS-C7) |
| `outdoor_material` | true/false | suggest ASA or PETG when the material is PLA or not set (DS-R1) |
| `max_water_cm3` | number | suggest a drain when the part holds more water than this with `UP` up (DS-R3) |
| `curved_supports_note` | true/false | note that organic supports scar curved faces less (DS-H2) |
| `max_sharp_inside_share` | number | suggest when more of the inside (concave) corner length than this is sharp (DS-T3) |
| `min_inside_radius_ratio` | number | suggest when an inside fillet's radius is less than this × the thinner wall it joins (DS-T3) |
| `min_wall_lines` | number | suggest when a wall is thinner than this many line widths (DS-T4); turns on the wall measurement |
| `max_z_slenderness` | number | note when a run standing on a small XY section is more slender than this (DS-T1; 5.6 = a round post 5 diameters tall) |
| `vase_mode_note` | true/false | note whether the part can print in vase mode: every layer one closed contour, the wall within the overhang limit both ways (DS-D1, DS-D3) |

Shares are fractions (0.9 = 90 %). The built-in files are in
[`src/b123d_print/data/styles/`](https://github.com/KD5RYN/b123d-print/tree/main/src/b123d_print/data/styles):
copy one as a starting point.

## The review checklist

Models forget steps: they skip the style, never run `design_metrics` or `suggest_orientation`,
and go straight to export. So the MCP server keeps a short checklist per part and per version of
its script, and ends the results of `build_part`, `check` (when it passes), `design_metrics` and
`export` with it. Only the missing steps carry the call to make:

```text
Before printing shelf_bracket (style: structural):
  ✓ style: structural (the script's STYLE)
  ✓ check passed (this version)
  ✗ not looked at: render_preview('shelf_bracket'), then section('shelf_bracket', 'XY', <a height through the holes and pockets>)
  ✗ design review not run: design_metrics('shelf_bracket', style='structural')
  ✗ orientation not checked: suggest_orientation('shelf_bracket', load='<bending direction, e.g. X>')
```

When everything ran, it is one line: `Ready to print shelf_bracket (style: structural): ...`.
Shown unchanged a second time, it shrinks to the next call.

- **The steps:** a style (the script's `STYLE`, the workspace `style`, or an explicit
  `design_metrics(style=...)`), a passing `check`, a `render_preview` and a `section`,
  `design_metrics` with the part's style, and `suggest_orientation` (done already when the
  script's `PRINT` locks the orientation).
- **Per version:** the server keys it by a hash of the script. Any edit (`write_part`,
  `set_params`, `restore_version`) starts an empty checklist; going back to an earlier version
  finds its steps again.
- **Where it lives:** `parts/<name>/out/.cache/review.json`, next to the build cache. It works
  the same locally, over HTTP and over SSH, survives a server restart, and is never downloaded.
- **Not for coupons:** a part whose `PRINT` says `"review": "exempt"` (the calibration coupons)
  gets no checklist. Fit-test templates (`make_template`) never do.

### What export does

The [`review` setting](settings.md#keys) decides:

| `review` | `export` with steps missing |
| --- | --- |
| `warn` (default) | exports; the result starts with `Exported WITHOUT ...` and ends with the checklist; the [print sheet](slicing.md#the-print-sheet) gets a **Design review** section listing what is missing |
| `required` | refuses with `NOT EXPORTED` and the checklist. `export(name, skip_review="<the user's reason>")` exports anyway; the print sheet records the reason |
| `off` | exports as before 0.3.15: no checklist in any result, nothing on the print sheet |

When every step ran, the print sheet says so in its **Design review** section. Over HTTP the
operator can set `B123D_PRINT_REVIEW=required` for every workspace.

## Running it

From an MCP client, use the `design_review` prompt (or ask for a design review): it runs
`check`, then `design_metrics`, renders the part and reports 3-7 suggestions, each with its
rule ID, the change in numbers, its effect and its trade-off. Then it asks which ones to apply.

From the command line:

```bash
b123d-print metrics bracket --style modern
```

```text
bracket
style: modern (argument), up: +Z
assumes 2 walls, 15% infill, 0.2 mm layers, 5/3 top/bottom, density 1.24 (material not set: PLA assumed), print_flow 10 mm3/s

part: 60.0 x 30.0 x 40.0 mm, 11.4 cm3
  filament 8.2 g, shell 87% / infill 13%  [simple estimate, roughly ±20 %]
  time ~21 min  [rough estimate: extruded / 10 mm3/s + 200 layers x 3 s]
  supports 0.0 g on 0 face(s)
  edges: sharp 100%, filleted 0%, chamfered 0% of 400.0 mm; radii -, chamfers -; bed edges sharp 180 mm
  stepping: 0.0 cm2 up-facing shallow slopes (0%, all faces)
  symmetry: x 0.616, y 1.0; seam corners on 100% of layers; water traps 0 cm3 (+Z up)

economy: 1 part(s), 10 faces, screw sizes {'M3': 2}

findings:
  [SUGGEST] DS-G1 part: 0% of outside edges are rounded or chamfered (target >= 90 %, bed edges excluded)
```

`--json` gives every number. `metrics` never fails: the review only suggests.

## The numbers

| Metric | How |
| --- | --- |
| size | bounding box, volume, area, aspect ratios (reported only: no proportion rule) |
| filament, cost | shell (2 walls, 5 top / 3 bottom layers) plus 15 % infill, times the material's `density`; cost when `filament_price` is set. **A simple estimate, roughly ±20 %** |
| time | extruded volume / `print_flow` + layers × 3 s. **A rough estimate**; `print_flow` (default 10 mm³/s) is the one setting that adjusts it |
| supports | faces steeper than the overhang limit that are not short bridges, times their height above what is below them, about 20 % solid. Rough |
| stepping | the area tilted 1-30° from flat, where layer steps show (vertical walls and flat tops are clean) |
| edges | outside edges: sharp, filleted, chamfered shares; the distinct radii and chamfer sizes; bed edges apart |
| symmetry | overlap of the part with its mirror image about the x and y mid-planes |
| economy | parts, faces; round holes matched to likely screw sizes (a guess) |
| seam corners | share of layers whose outline has a sharp corner where the seam can hide |
| water traps | water left in the part with `UP` up (voxel grid, drains sideways and down) |
| inside corners | inside (concave) edges: sharp, filleted, chamfered shares; the smallest fillet radius over the wall it joins |
| walls | the thinnest walls in line widths, for a style with `min_wall_lines` (the ThinFeature sections; takes seconds) |
| hole edge distance | for each screw hole, axis to the nearest edge of the material, in hole diameters (reported only) |
| slenderness | how tall a run stands on a small XY section: the run over the square root of the section's area |

Use the estimates to compare two versions of a part and to see what dominates (supports,
infill, layer count), not as a quote: a slicer gives the real numbers.

## Settings

`style`, `filament_price` and `print_flow` in the [settings](settings.md); `density` in the
[material profiles](printer-profiles.md). The printer profile's nozzle and layer height are used
when a printer is set.
