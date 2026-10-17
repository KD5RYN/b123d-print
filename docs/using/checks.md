# The checks

`check` (MCP tool or CLI command) builds every variant and runs these. A **FAIL** must be fixed;
a **WARN** is reported and left to you. The CLI exits with code 1 on any failure.

- **valid** — every printable part is a valid, non-empty solid.
- **overlap** — intersection volume between every pair of `assembly(d)` parts, stand-ins
  included; > 0.01 mm³ fails. This is how a box is checked against the board it holds.
- **overhang** — downward faces in print orientation, angle from vertical (wall 0°, ceiling
  90°); > 45° (or the `max_overhang` setting) is reported, the bed face is ignored. Flat
  ceilings are told apart: a **bridge** rests on walls on two opposite sides and is listed with
  its span; a **cantilever** hangs off one side and is an overhang like any other. The top of a
  horizontal round hole is marked `hole`. `Overhang(part, fail=True)` for parts that must print
  without supports (bridges never fail).
- **bridge** — a bridge longer than `max_bridge` (10 mm unless your printer or the
  [overhang/bridge coupon](../scripts/examples.md#overhang_bridge_coupon) says more) warns: it sags.
- **wall** — thinnest material in a cross-section, optionally only around one cut: across the
  wall along the surface normal, and between separate outlines (hole to edge). Tips of ordinary
  corners don't count as thin; knife edges sharper than about 25° do. Below `min_wall` fails.
- **thin** — the wall measurement on sections all over the part (XY, XZ and YZ, at every
  flat-face level and every 2 mm). A wall thinner than one line width (0.45 mm, or your
  printer's) **fails**: it does not print as modeled. Thinner than `min_wall` warns. A spot that
  is thin in only one plane, or tapers, is a **knife edge** (a wedge tip, a corner cut at an
  angle) and warns.
- **holes** — lists the round holes. Warns on a horizontal hole with a round top (its top sags
  and prints small: use a teardrop or a flat roof, or turn the part) and on holes under 1 mm.
- **bed edge** — warns on a fillet (any curved face) that starts on the bed: its lowest band is a
  flat overhang that flares. Bed edges get a chamfer.
- **gap** — for a part made of several solids (printed in place): fails when two are closer than
  `pip_clearance`, because they fuse. Declared between two parts, it checks a fit:
  `Gap("lid", "base", min=..., max=...)`.
- **fit** — only with a [printer profile](printer-profiles.md): the part fits the build volume
  in print orientation.
- **probe** — material must be present (or absent) in a small box: "the roof is closed",
  "the cable channel is clear".

**valid**, **overlap**, **overhang** (with **bridge**), **thin**, **holes**, **bed edge**,
**gap** and **fit** run on every part on their own; **wall** and **probe** run where the script
asks for them in `checks(d)`, which can also change or narrow the automatic ones — see the
[Checks API](../scripts/checks-api.md). The rules behind each check, with their sources, are in
[Design rules](../BEST_PRACTICES.md).

!!! warning "Why wall checks matter"
    `is_valid` and hole-diameter checks do not catch a 0.05 mm skin. A real print broke there.
    Wherever a cut goes deeper than the wall it starts in, add a `Wall` check just past the wall.

Example output (`b123d-print check -v` on the wall plate example):

```text
plate: 3 ok, 1 warn, 0 fail
  [OK  ] valid    part: valid solid
  [OK  ] wall     part (corner counterbore in its boss): min wall 1.10 mm (limit 0.8) at [-23.0, -38.0], XY @ 2.45 near (-23.0, -41.65)
  [OK  ] wall     part (center screw boss): min wall 2.05 mm (limit 0.8) at [-0.0, -39.22], XY @ 3.4 near (0, -41.65)
  [WARN] overhang part: 16 face(s), 1064 mm^2 steeper than 45 deg: 4 x 228 mm^2 at 80 deg, z 0.03..0.88 (cylinder); ...
all checks passed
```
