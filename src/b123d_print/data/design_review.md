# Design review rubric (b123d-print)

The rules, their sources and the reasoning are in DESIGN_GUIDE
(https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/). IDs: [DS-G*] general, [DS-S*] FDM
surfaces, [DS-C*] cost, [DS-R*] rugged, [DS-H*] handheld, [DS-T*] structural, [DS-O*] organic. Thresholds marked
"proposed" are the project's starting values, not sourced numbers. The review never fails a part: findings are
**suggest** (worth changing for this style) or **note** (information, a trade-off).

## In the part script

- `STYLE` in `Dims`: `"functional"` (default), `"modern"`, `"least_cost"`, `"rugged"`, `"soft"`,
  `"structural"`, `"organic"` or a style file's name. A variant can override it. Else the workspace `style` setting, else
  functional.
- `EDGES` (optional, `Dims` or module): `"chamfer"` or `"fillet"`, the edge language the part
  should use. Functional with `EDGES = "chamfer"` and exposed standard screws is the
  industrial/utilitarian look.
- `SHOW` (optional): the sides seen in use, in print orientation, e.g. `SHOW = ["+Y", "+Z"]`.
  Stair-stepping and support findings are then limited to those sides. Without it, ask which
  sides show when it matters, or judge all faces.
- `UP` (optional): the side that points up in use, e.g. `UP = "+Y"`, for the water-trap check.

## Every style (notes)

- [DS-G1] Coherence: a small, consistent set of edge treatments and radii; like edges treated
  alike. Some variety is fine; pure uniformity is not the goal.
- [DS-G2] Economy: as little as possible; features that do several jobs; every separate part
  justified (moves, other material, must come apart).
- [DS-G3] Fasteners: few, one or two sizes, standard, one tool.
- [DS-G4] Assembly: lead-in chamfers, keys; symmetric, or obviously asymmetric.
- [DS-G5] Signifiers: it must be clear where to grip, open, press or insert.
- [DS-G6] Honesty: no fake screws, fake vents or decoration pretending to be function.
- [DS-G7] Symmetry and [DS-G8] curvature are style choices, not quality scores.
- [DS-G9] Never suggest a proportion rule (golden ratio): no evidence supports one.
- [DS-S1] Shallow slopes (1-30 deg from flat) show layer steps; vertical walls and flat tops are
  clean. [DS-S2] Visible faces: vertical walls or flat tops, not supported faces.
- [DS-S3] The seam hides in a sharp vertical corner; a round part needs one on its back.
- [DS-S4] Chamfers print at a constant angle; fillets that face down overhang. [DS-S5] Texture
  or deliberate grooves hide layer lines. [DS-S6] Split lines go on edges or the back.
- [DS-C4] Supports cost filament and time and leave rough faces.

## The styles (suggest)

Each style is a small TOML file: its thresholds produce the suggestions in `design_metrics`, and
its `review` text (printed at the end of `design_metrics`) is the rubric to apply. Built in:
`functional` (default: does its job, prints well, looks deliberate), `modern` (few elements, one
radius language), `least_cost` (least filament and time), `rugged` (sun, water, drops),
`soft` (held in the hand), `structural` (carries load: the load along the layers, filleted
inside corners, walls and screws) and `organic` (natural objects: modeled from sections along
curves, blended joins, a few features, a flat base; DS-O1..O5). The user's own styles live in `~/.config/b123d-print/styles/` or the
workspace's `styles/` folder (`list_parts` lists them); `based_on` starts one from another, and a
file with a built-in's name replaces it.

## The estimates

Filament is a simple estimate (shell + 15 % infill), roughly +-20 %. Time is one rule
(extruded volume / `print_flow` + layers x 3 s), a rough estimate. Supports are rough. Say so
whenever you quote them, and use them to compare versions, not as a quote.
