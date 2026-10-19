# Examples

Bundled with the package, in
[`src/b123d_print/examples/`](https://github.com/KD5RYN/b123d-print/tree/main/src/b123d_print/examples).
Start a part from one with `new_part("my_part", example="<example>")` over MCP or
`b123d-print new my_part --from <example>`; `b123d-print examples` lists them.

## `remix_bracket`

![The original L bracket and the remix side by side](../images/remix_bracket_before_after.png)

A [remix](../using/remix.md): an L bracket that exists only as an STL (`ref/l_bracket.stl`, made
for this example, CC0) is loaded with `import_model` and changed: its two mounting holes become
slots, and two gussets stiffen the corner. The faceted 6 mm hole in the upright is the
original's, so its overhang is reported as *inherited from the original*. `new_part(...,
example="remix_bracket")` copies the reference file too.

![The original colored where the remix differs](../images/remix_bracket_vs_original.png)

*The deviation view: red where the slots were cut, grey where the gussets were added.*

[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/remix_bracket/remix_bracket.py)

## `esp_ir_blaster`

![ESP IR blaster box, assembly with board stand-ins](../images/esp_ir_blaster_assembly.png)

A two-part box (base and screw-on lid) for an ESP8285 IR transceiver board. Shows an
`assembly(d)` with board, LED and receiver stand-ins, so the overlap check proves the board fits.

![Section through the LED](../images/esp_ir_blaster_xz0.6.png)

*Section through the LED: lid cone, board, clearances.* Its `templates(d)` adds two
[fit-test templates](../using/templates.md) to every export: the top of the standoffs and lid
posts (set the board on it), and the lid's inner face (lay it on the base, try the screws).
[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/esp_ir_blaster/esp_ir_blaster.py)

## `tuya_motion_sensor_outdoor_case`

![Outdoor motion sensor case, arch cover](../images/tuya_motion_sensor_outdoor_case_arch_assembly.png)

An outdoor case for a PIR motion sensor: a back plate stays on the wall, a hooded cover slides
down over it on dovetails and clicks into detents. Variants: the standard one (flat on the
wall, flat-top cover), `tilt15` (plate tipped 15° down) and `arch` (a cover that prints without
supports).

![Section through the arch cover and back plate](../images/tuya_motion_sensor_outdoor_case_arch_yz0.png)

*Section through the middle of the arch variant.*

[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/tuya_motion_sensor_outdoor_case/tuya_motion_sensor_outdoor_case.py)

## `plate_2gang_to_1gang`

![2-gang to 1-gang wall plate](../images/plate_2gang_to_1gang.png)

A 2-gang to 1-gang adapter wall plate for a smart switch, in two sizes (`VARIANTS`). Shows hole
compensation from the config and the wall check around the counterbores — the first print of
this part broke through a 0.05 mm skin there.

![Wall plate section through the counterbores](../images/plate_2gang_to_1gang_xy2.45.png)

*Section just past the face, where the wall check looks.*
[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/plate_2gang_to_1gang/plate_2gang_to_1gang.py)

## `testblock`

The smallest complete example: a block with a rounded notch, a few measured dimensions, one
fillet, one cut.
[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/testblock/testblock.py)

## `hole_coupon`

![Hole calibration coupon](../images/hole_coupon.png)

The calibration coupon for [hole compensation](../using/hole-compensation.md): vertical holes in
the plate and horizontal ones in the tab (round, and teardrop), cut at their nominal size and
labeled. Measures `hole_comp` and `hole_comp_h`.
[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/hole_coupon/hole_coupon.py)

## `fit_coupon`

![Fit coupon, holes plate](../images/fit_coupon_holes.png)

Measures the fits, per side, for your printer and material: a 6 mm peg (part `peg`) tried in
holes 0 to 0.40 mm bigger per side (part `holes`; the label is hundredths of a mm), and discs
printed inside rings with gaps of 0.10 to 0.40 mm (part `pip`). The results go into
`press_fit`, `clearance`, `free_fit` and `pip_clearance` ([Settings](../using/settings.md#keys)).
Its `checks(d)` shows a declared `Gap` (the discs are closer than `pip_clearance` on purpose)
and `ThinFeature` ignoring the engraved labels.

![Fit coupon, print-in-place discs](../images/fit_coupon_pip.png)

[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/fit_coupon/fit_coupon.py)

## `overhang_bridge_coupon`

![Overhang and bridge coupon](../images/overhang_bridge_coupon.png)

Measures your printer's limits: ledges whose undersides are 40° to 75° from vertical, and
bridges of 5 to 40 mm between pillars. The steepest clean ledge is your `max_overhang`, the
longest clean bridge your `max_bridge`. The overhang and bridge checks warn on it on purpose.
[Script](https://github.com/KD5RYN/b123d-print/blob/main/src/b123d_print/examples/overhang_bridge_coupon/overhang_bridge_coupon.py)
