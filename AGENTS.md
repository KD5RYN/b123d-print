# Designing 3D-printable parts with b123d-print (instructions for AI agents)

This workspace holds parts for FDM 3D printing, modeled in Python with
[build123d](https://github.com/gumyr/build123d) and checked with `b123d-print`. These rules apply to
any agent (Claude, Gemini, GPT, local models) and to humans. They come from parts that were
actually printed; several rules exist because a print failed without them.

## Tools

Use the **b123d-print MCP server** tools if your client has them (`new_part`, `write_part`,
`build_part`, `render_preview`, `section`, `check`, `export`). Otherwise use the CLI:

- `b123d-print new <name>` — scaffold `parts/<name>/<name>.py`
- `uv run parts/<name>/<name>.py [--variant <key>] [--formats 3mf,png]` or `b123d-print build <name>` —
  export to `parts/<name>/out/` and run the checks
- `b123d-print check [<name> ...]` — checks only; exit code 1 on any failure
- `b123d-print config` — show the print settings in effect (hole compensation, clearance, limits)

## The part script

1. **One script per part** at `parts/<name>/<name>.py`. Units are **mm**.
2. **Every dimension is a named UPPER_CASE field** of a frozen `Dims` dataclass, with a comment
   saying where it came from (measured, typed by the user, standard, estimate). No magic numbers
   in the geometry code. Derived values are `@property`s.
3. **Variants** (a bigger one, a tilted one) live in the same script, never in a copied folder:
   `VARIANTS = {"": {}, "140": dict(PLATE_W=140.0)}` holds only the overrides. Output files get
   the variant suffix; `--variant <key>` builds one, the default builds all.
4. `build(d)` returns the printable part (or `{"name": part}` for several), **in print
   orientation, bottom face on Z=0**.
5. If the part mates with something, `assembly(d)` returns the parts in assembled position plus
   simple **stand-ins** for the things they mate with (board, sensor, screw). The overlap check
   uses it: nothing printed may intersect a stand-in.
6. `views(d)` lists cross-sections saved with each export; `checks(d)` declares wall checks and
   any overhang rules (see below).

## Print rules

- **Mating clearance: 0.2 mm** by default, as a named `CLEARANCE` (or more specific) field —
  unless the user gives another value. In your report say which features got clearance and
  whether it is per side or total.
- **Hole compensation** is per printer and comes from the user's config:
  `HOLE_COMP: float = hole_comp(__file__)`. Keep hole fields at the target *printed* size and add
  `HOLE_COMP` when cutting. It defaults to 0; the `hole_coupon` example measures it. Never
  hard-code a value from somewhere else.
- **Fillets and chamfers:** break sharp edges (~0.5–1 mm). Edges on the bed get a **chamfer, not
  a fillet** (a fillet there is an overhang and flares), unless the user says otherwise.
- **Overhangs:** keep downward faces within 45° of vertical where you can. Flat ceilings must
  span between two walls (a bridge) or get supports. Say in the report what needs supports.
- **Walls:** keep at least ~1.2 mm (three perimeters) where strength matters.

## Output formats

`export` writes, per printable part: **STEP** (opens in other CAD — Onshape, Fusion, FreeCAD —
as a plain solid without feature history), **STL** and **3MF** (slicers; 3MF keeps units),
and **PNG** previews plus the section views. The user picks: the `formats` setting in their
config, or `formats="3mf,png"` on one export. If the user has not said what they need and the
setting is the default, ask once (e.g. "3MF for Bambu/Orca/Prusa, STEP to edit in other CAD?").
The parametric source is always the `.py` script and its `Dims`.

## Printer profile (optional)

By default b123d-print is in generic mode. If the user has set a printer (`list_parts` shows it, or
`b123d-print printer show`), use it: keep the part inside the build volume in print orientation
(the `fit` check fails otherwise — split the part or turn it), make walls whole multiples of the
line width, and read the material notes (e.g. PLA is not for outdoor or hot places). Change the
printer only when the user asks.

## Photos and measurements

- **Before modeling: list every dimension you read from the photos** and which feature it
  belongs to, list features you can see that have no dimension, and **wait for the user to
  confirm**. Do not start modeling on guesses.
- **Photos show intent; typed measurements are truth.** If a photo reading conflicts with a
  typed number, flag the conflict and use the typed number unless told otherwise.
- **Missing or ambiguous dimension → ask. Don't guess.** If you must assume something to make
  progress, name it as an estimate in its comment and in your report.

## Verify before reporting

Do all of this every time you change geometry, before telling the user the part is done:

1. **Build it** and confirm every part is a valid solid with the volume and size you expect.
2. **Look at the preview render.** Compare it against the user's description and photos.
3. **Look at cross-sections** through every pocket, rib, boss, hole and mating feature. Sections
   show what the 3D render hides.
4. **Run the checks** and fix every failure; mention every warning you leave.
5. **Wall check around deep cuts:** wherever a cut goes deeper than the wall it starts in
   (a counterbore into a boss, a pocket next to a rib, a dimple in a thin side), add a `Wall`
   check that slices just past the wall and measures the material left around the cut.
   `is_valid` and hole-diameter checks do not catch a 0.05 mm skin — a real print broke there.
6. **Report:** overall size (X × Y × Z), key feature dimensions, validity, the clearances and
   hole compensation applied, check results, print orientation and any supports needed.

## Checks reference

```python
from b123d_print import Overhang, Probe, Wall

def checks(d):
    return [
        # thinnest material in the section, within `radius` of `near` (the section's 2D coords:
        # XY -> (x, y), XZ -> (x, z), YZ -> (y, z)); fails below `min` (default: config min_wall)
        Wall("base", "XY", d.FLOOR_T + 1.0, near=(x, y), radius=5, label="standoff pilot"),
        # downward faces > 45 deg are always reported; fail=True for parts that must print
        # without supports (flat bridges are allowed unless bridges_ok=False)
        Overhang("cover", fail=True),
        # material must exist (or not) in a small box: "roof is closed", "channel is clear"
        Probe("cover", (0, 10, 70), (1, 1, 0.5), expect="solid", label="roof closed"),
    ]
```
