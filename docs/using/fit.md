# Fit between pieces

A part with several pieces, or with an `assembly(d)` that places them with
[stand-ins](../scripts/convention.md#what-a-script-defines) for what they mate with, can be
checked for how the pieces meet: `check_fit(name)` (MCP) or `b123d-print fit <name>` (CLI).

!!! note "Opt-in"
    `check` does not run the fit check on its own (its automatic **overlap** check already fails
    intersecting pieces). To make `check` run it too, list it in the script:

    ```python
    from b123d_print import Mates

    def checks(d):
        return [Mates()]   # or Mates(hole_tol=0.3, joints=[("peg", "socket", d.CLEARANCE)])
    ```

    `check_fit` and `b123d-print fit` use that `Mates(...)` and its arguments when the script
    has one.

It looks at the pieces **as placed in `assembly(d)`**, so build the assembly the way the part
goes together: the lid on the box, the screws' parts lined up.

## Placing pieces by contact

Hand-computed `Pos`/`Rot` math in `assembly(d)` is easy to get off by one wall thickness, which
spoils the interference and hole-alignment checks. Use `place_on` and `align_axis` from
`b123d_print` (or `b123d_print.fit`) instead:

```python
from b123d_print import align_axis, place_on

def assembly(d):
    b = base(d)
    # set the lid's bottom face on the base's top rim, then slide in that plane to line up the holes
    l = place_on(lid(d), "bottom", b, "top")
    l = align_axis(l, d.POSTS[0], b, clock=d.POSTS[1])
    return [(b, "#3a6ea5", "base"), (l, "#e0a030", "lid")]
```

- `place_on(piece, face_a, target, face_b, offset=0.0, spin=0.0, shift=(0.0, 0.0))` turns and
  moves `piece` so its flat `face_a` rests on `target`'s flat `face_b` (coplanar, with opposed
  outward normals). Faces are picked as in `list_faces`: a side (`"bottom"`, `"top"`, `"-Z"`,
  `"+X"`, ... — the outermost flat face facing that way), a face id from `list_faces`, a point
  `(x, y, z)` on the face, or a `Face`. `offset` adds a gap along `face_b`'s outward normal
  (`0` = touching, `d.CLEARANCE` = a clearance gap); `spin` turns `piece` in the contact plane
  (degrees); `shift` slides it in that plane.
- `align_axis(piece, axis_a, target, axis_b=None, *, clock=None, offset=None, flip=False, keep_contact=None)`
  lines up a round hole, boss or pin on `piece` coaxially with one on `target`. Each axis is a
  point `(x, y, z)` or `(x, y)` near the hole or pin, a cylindrical `Face`, a dict from
  `holes()`/`bores()`, an `Axis`, `(point, direction)`, a 1-based id, or `None` when the piece has
  only one. When the axes are already parallel (as after `place_on`), `piece` slides only in the
  contact plane so the face contact or `offset` from `place_on` stays untouched. Pass `clock=`
  (a second hole/pin pair `(axis_a2, axis_b2)`, or a point looked up on both) to also turn `piece`
  around the first axis until the second pair lines up.

## Interference

Each pair of assembly items whose bounding boxes come within the clearance:

| Finding | Level | What it means |
| --- | --- | --- |
| overlap *v* mm³ around (x, y, z) | FAIL | the pieces intersect: the volume, the center and extent of the overlap |
| gap *g* mm at (x, y, z) under the clearance | WARN | closer than the `clearance` setting (per side) without touching: a sliding fit binds there; a fixed one is fine |
| touch at (x, y, z) | OK | faces resting on each other (a lid on a box), no overlap |
| gap *g* mm | OK | at least the clearance |

**Stand-ins** count as obstacles: a printed piece that overlaps a board stand-in fails like any
other pair. Two stand-ins are never compared. An assembly item is a stand-in when its label says
so (`"board (stand-in)"`, `"dummy"`) or matches no piece of `build()` (`"back plate"` matches
the piece `backplate`).

**Joints.** A male/female pair meant to fit with a clearance (a dovetail, a peg in a socket) is
measured against its own clearance: under it fails ("it will not go together"). Declare the
pairs with a `joints(d)` function in the script, or `Mates(joints=...)`:

```python
def joints(d):
    return [("peg", "socket", d.CLEARANCE)]   # labels from assembly(d); clearance per side
```

Each item is a tuple `(male, female[, clearance])`, a dict with those keys, or an object with
`male` and `female` attributes and an optional `clearance`, so the pairs a joints helper returns
can be passed straight in.

## Hole alignment

Round holes are found on every item (concave cylinders; a counterbore and its clearance hole
count as one hole of the smaller size). Two holes in pieces that meet, on parallel axes that
overlap, are partners:

| Finding | Level | What it means |
| --- | --- | --- |
| holes ... are *o* mm off-axis | FAIL | partners further apart than `hole_tol` (0.2 mm by default) |
| holes ... line up: M3: clearance + insert | OK | the diameters read as one screw size: a clearance hole over a pilot hole, a [heat-set insert](../BEST_PRACTICES.md) hole or another clearance hole (bolt and nut) |
| sizes match no one screw | WARN | e.g. two pilot holes (nothing lets the screw through), or an M3 clearance over an M4 insert hole |
| hole has no partner: its axis runs into solid ... | WARN | a hole that ends on solid material of the next printed piece |

Diameters are read after taking off the configured `hole_comp`, against ISO 273 clearance holes,
pilot holes for thread-forming screws (M3 2.5–2.95 mm, [BP-T6](../BEST_PRACTICES.md)) and
CNC Kitchen's insert holes (M3 4.0 mm, [BP-T2](../BEST_PRACTICES.md)), M2 to M6. Holes into
stand-ins are not reported as unpartnered (a stand-in usually has no holes).

## Example

A lid on a box with four M3 screws into heat-set inserts, one lid hole 0.5 mm off:

```text
box [standard]: 1 fail, 0 warn, 5 ok; assembly: box, lid
  [FAIL] align    box / lid: holes at (-24.75, -15.0, 18.25) are 0.50 mm off-axis (tolerance 0.2): box 4.00 (M3 insert) over lid 3.40 (M3 clearance or M4 pilot)
```

and the same lid 0.1 mm too low:

```text
  [FAIL] mate     box / lid: overlap 48.123 mm^3 around (0.0, 0.0, 19.95) (extent 60 x 40 x 0.1 mm)
```

## Speed

Pairs are pre-filtered on bounding boxes; at most `max_pairs` (60) close pairs are measured,
nearest first, and the report says when it stopped there. The pieces come from the
[build cache](../scripts/convention.md#big-and-multi-piece-projects) when an earlier call built
them.
