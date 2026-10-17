# Hole compensation

FDM printers print small holes undersize, by an amount that depends on printer, nozzle,
material and slicer. b123d-print never assumes a value: `hole_comp` defaults to **0**.

![Hole calibration coupon](../images/hole_coupon.png)

1. Get the coupon: `new_part("coupon", example="hole_coupon")` over MCP (or the
   `calibrate_hole_comp` prompt, which walks you through all of it), or
   `b123d-print new coupon --from hole_coupon`.
2. Export and print it with your usual material and settings. Its holes are cut at their
   nominal size on purpose: this part measures the error.
3. Measure each hole with calipers (or the largest drill bit or gauge pin that passes).
4. `hole_comp = average(nominal - measured)`, on the diameter. If the error grows with size,
   average over the sizes you actually use.
5. Save it in your user config:

    ```toml
    # ~/.config/b123d-print/config.toml
    [print]
    hole_comp = 0.4
    ```

    or, with a [printer profile](printer-profiles.md) set, for that printer + material:

    ```bash
    b123d-print printer hole-comp 0.4
    ```

Part scripts read it with `HOLE_COMP: float = hole_comp(__file__)` and add it when cutting
holes; hole fields stay at the size you want printed. Never hard-code a value from somewhere
else (see [The part script](../scripts/convention.md)).
