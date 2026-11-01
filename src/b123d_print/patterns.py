"""Patterns: repeated features placed with build123d's location sets, cut or added in one boolean.

    from b123d_print.patterns import bolt_circle, hole_grid
    part -= Pos(0, 0, d.T) * bolt_circle(d.BC_R, 6, d.HOLE_D, d.T, hole_comp=d.HOLE_COMP)

build123d places copies with GridLocations, PolarLocations, HexLocations and Locations (and
mirrors with `mirror`). `GridLocations(...) * feature` is a list of placed copies; `Part() + list`
fuses them, and `part - list` cuts them all in one boolean. One boolean per pass of a for loop
costs far more: 400 holes in a plate took 0.22 s fused and 10.2 s one at a time (900 holes:
0.73 s and 58.6 s; build123d 0.13.0). loops.loop_booleans finds those loops in a part script.

The recipes are registered in recipes.RECIPES (the `recipe` tool, b123d-print://recipes/<name>);
docs/using/patterns.md is the guide.
"""

from __future__ import annotations

import math

from build123d import (Align, Box, BuildPart, BuildSketch, Cylinder, GridLocations, HexLocations, Part,
                       PolarLocations, Pos, RegularPolygon, Sketch, SlotOverall, extrude)

BED = (Align.CENTER, Align.CENTER, Align.MIN)
TOP = (Align.CENTER, Align.CENTER, Align.MAX)  # cutters that open on Z=0 and go down


def bolt_circle(radius: float, count: int, hole_d: float, depth: float, start_angle: float = 0.0,
                hole_comp: float = 0.0) -> Part:
    """`count` vertical holes on a circle `radius` around the origin, the first at `start_angle`
    degrees from +X: one cutter opening on Z=0 into -Z (PolarLocations), so the part takes one
    boolean: part -= Pos(0, 0, top) * bolt_circle(...). hole_d is the printed size; add the
    user's HOLE_COMP with hole_comp."""
    hole = Cylinder((hole_d + hole_comp) / 2, depth, align=TOP)
    return Part() + PolarLocations(radius, count, start_angle) * hole


def demo_bolt_circle() -> Part:
    """A round flange: a 22 mm bore and six M4 clearance holes on a 50 mm circle."""
    t = 5.0
    flange = Cylinder(35, t, align=BED) - Cylinder(11, t, align=BED)
    return flange - Pos(0, 0, t) * bolt_circle(25, 6, 4.5, t, start_angle=30)


def hole_grid(x_pitch: float, y_pitch: float, x_count: int, y_count: int, hole_d: float, depth: float,
              hole_comp: float = 0.0) -> Part:
    """A grid of `x_count` x `y_count` vertical holes `x_pitch` and `y_pitch` apart, centered on
    the origin (GridLocations): one cutter opening on Z=0 into -Z. Screw-hole grids, pegboards,
    drain or vent holes. hole_d is the printed size; add HOLE_COMP with hole_comp."""
    hole = Cylinder((hole_d + hole_comp) / 2, depth, align=TOP)
    return Part() + GridLocations(x_pitch, y_pitch, x_count, y_count) * hole


def demo_hole_grid() -> Part:
    """A 6 x 4 grid of 3 mm holes on a 10 mm pitch in a 70 x 50 plate."""
    t = 3.0
    return Box(70, 50, t, align=BED) - Pos(0, 0, t) * hole_grid(10, 10, 6, 4, 3.0, t)


def hex_grille(width: float, length: float, cell: float, web: float, depth: float) -> Part:
    """A honeycomb cutter: hexagonal holes `cell` across the flats, with `web` of material between
    neighbours, filling a `width` (X) x `length` (Y) area centered on the origin with whole cells
    only; it opens on Z=0 into -Z. Vents, speaker grilles, lightening pockets. One sketch (every
    cell placed by HexLocations), one extrude.

    HexLocations' radius is the apothem of the tiling cell (centre to flat side), so neighbours
    sit 2 x radius = cell + web apart; its columns are sqrt(3) x radius apart and every other one
    is shifted half a step. The cells have a corner on +X and -X. On a wall printed standing,
    turn the cutter so a corner points up (the roof is then two 60-degree slopes, no bridge)."""
    if cell <= 0 or web <= 0 or depth <= 0:
        raise ValueError(f"hex_grille: cell {cell:g}, web {web:g} and depth {depth:g} must be > 0")
    r = (cell + web) / 2  # HexLocations radius: the tiling cell's apothem
    corner = cell / math.sqrt(3)  # a hole's centre-to-corner radius (along X)
    nx = int(width / (math.sqrt(3) * r)) + 2
    ny = int(length / (2 * r)) + 2
    eps = 1e-9
    locs = [loc for loc in HexLocations(r, nx, ny)
            if abs(loc.position.X) + corner <= width / 2 + eps and abs(loc.position.Y) + cell / 2 <= length / 2 + eps]
    if not locs:
        raise ValueError(f"hex_grille: no {cell:g} mm cell fits in {width:g} x {length:g}")
    cells = Sketch() + [loc * RegularPolygon(cell / 2, 6, major_radius=False) for loc in locs]
    return extrude(cells, -depth)


def demo_hex_grille() -> Part:
    """A speaker or fan cover: 6 mm hex holes with 1.6 mm webs in a 3 mm plate, a
    solid 6 mm border."""
    t = 3.0
    return Box(80, 60, t, align=BED) - Pos(0, 0, t) * hex_grille(68, 48, 6.0, 1.6, t)


def slot_grille(slot_l: float, slot_w: float, count: int, pitch: float, depth: float) -> Part:
    """`count` round-ended slots `slot_l` long (along X) and `slot_w` wide, `pitch` apart in Y,
    centered on the origin: one cutter opening on Z=0 into -Z, made in builder mode (a
    GridLocations context in a BuildSketch, then one extrude). Vents and speaker slots; the web
    between slots is pitch - slot_w."""
    if pitch <= slot_w:
        raise ValueError(f"slot_grille: pitch {pitch:g} must be more than the slot width {slot_w:g}")
    with BuildPart() as grille:
        with BuildSketch():
            with GridLocations(0, pitch, 1, count):
                SlotOverall(slot_l, slot_w)
        extrude(amount=-depth)
    return grille.part


def demo_slot_grille() -> Part:
    """A vent panel: eight 40 x 3 mm slots on a 6 mm pitch (3 mm webs) in a 2.4 mm plate."""
    t = 2.4
    return Box(56, 60, t, align=BED) - Pos(0, 0, t) * slot_grille(40, 3.0, 8, 6.0, t)


def grip_ridges(diameter: float, height: float, count: int = 24, ridge_w: float = 1.2, ridge_h: float = 0.8) -> Part:
    """`count` straight ridges around a cylinder `diameter` across, `height` tall from Z=0, each
    `ridge_w` wide standing `ridge_h` proud of the surface (PolarLocations with rotate=True turns
    each ridge to face out): add them to a knob or handle, part += grip_ridges(...). Each ridge
    reaches ridge_h into the cylinder so they fuse with it."""
    ridge = Box(2 * ridge_h, ridge_w, height, align=BED)
    return Part() + PolarLocations(diameter / 2, count, rotate=True) * ridge


def demo_grip_ridges() -> Part:
    """A 30 mm knob, 15 mm tall, with 24 ridges 1.2 mm wide (about 3 lines) and 0.8 mm high."""
    return Cylinder(15, 15, align=BED) + grip_ridges(30, 15, 24, 1.2, 0.8)
