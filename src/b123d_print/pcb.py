"""PCB support bodies and measured reference geometry, in millimetres.

Board stand-ins are rectangular envelopes, not component or copper models. Keep components
as separately labelled stand-ins in assembly() so the existing fit check can find interference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from build123d import Align, Box, Cone, Cylinder, Part, Pos

BED = (Align.CENTER, Align.CENTER, Align.MIN)


def pcb_standoff(height: float, outside_d: float, pilot_d: float, pilot_depth: float,
                 flare: float = 0.0, flare_h: float = 0.0, hole_comp: float = 0.0) -> Part:
    """A PCB support from Z=0 to height, with a vertical pilot opening on its top.

    pilot_d is the target printed diameter; hole_comp is added once, diametrically. The blind
    pilot leaves height - pilot_depth material underneath; depth == height makes it through.
    flare is extra radius at the base, tapering to outside_d at flare_h. Supply both or neither.
    Choose a pilot from the screw/insert maker or a coupon; this does not assume M3 or a thread.
    For a clearance spacer, pass the selected bd_warehouse screw's clearance_hole_diameters
    value as pilot_d and height as pilot_depth. Outside dimensions receive no compensation.
    """
    values = (height, outside_d, pilot_d, pilot_depth, flare, flare_h, hole_comp)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("pcb_standoff: dimensions must be finite")
    if height <= 0 or outside_d <= 0 or pilot_d <= 0:
        raise ValueError("pcb_standoff: height, outside_d and pilot_d must be positive")
    if not 0 < pilot_depth <= height:
        raise ValueError("pcb_standoff: pilot_depth must be positive and no greater than height")
    if not 0 < pilot_d + hole_comp < outside_d:
        raise ValueError("pcb_standoff: compensated pilot must be positive and smaller than outside_d")
    if flare < 0 or flare_h < 0 or flare_h > height or (flare == 0) != (flare_h == 0):
        raise ValueError("pcb_standoff: flare and flare_h must both be positive or both zero; flare_h <= height")
    support = Cylinder(outside_d / 2, height, align=BED)
    if flare:
        support += Cone(outside_d / 2 + flare, outside_d / 2, flare_h, align=BED)
    return support - Pos(0, 0, height - pilot_depth) * Cylinder(
        (pilot_d + hole_comp) / 2, pilot_depth, align=BED
    )


def pcb_board(width: float, length: float, thickness: float, holes: tuple[tuple[float, float], ...],
              hole_d: float) -> Part:
    """A rectangular PCB stand-in centered in XY, underside on Z=0, with explicit mounting holes.

    X spans width, Y spans length; holes are (x, y) centers from the board center, viewed from
    above (+Z). Arbitrary/asymmetric patterns and an empty sequence are accepted. hole_d is
    the measured/manufacturer board hole diameter, without printer compensation. Add separate
    component/connector stand-ins; this envelope makes no assumptions about their clearance.
    """
    if not all(math.isfinite(v) and v > 0 for v in (width, length, thickness, hole_d)):
        raise ValueError("pcb_board: width, length, thickness and hole_d must be finite and positive")
    points = []
    for point in holes:
        if len(point) != 2 or not all(math.isfinite(v) for v in point):
            raise ValueError("pcb_board: each hole must be a finite (x, y) pair")
        x, y = point
        if abs(x) + hole_d / 2 >= width / 2 or abs(y) + hole_d / 2 >= length / 2:
            raise ValueError("pcb_board: mounting holes must lie entirely inside the board")
        if any(math.dist((x, y), other) <= hole_d for other in points):
            raise ValueError("pcb_board: mounting holes must not touch or overlap")
        points.append((x, y))
    board = Box(width, length, thickness, align=BED)
    for x, y in points:
        board -= Pos(x, y, 0) * Cylinder(hole_d / 2, thickness, align=BED)
    return board


@dataclass(frozen=True)
class PCBPattern:
    """Exact board drawing data; thickness and component envelopes are deliberately not assumed."""

    model: str
    width: float
    length: float
    holes: tuple[tuple[float, float], ...]
    hole_d: float
    datum: str
    source: str


PCB_PATTERNS = {
    "raspberry_pi_zero_v1_2": PCBPattern(
        "Raspberry Pi Zero, drawing RPI-ZERO-V1_2, 2015-09-23", 65.0, 30.0,
        ((-29.0, -11.5), (29.0, -11.5), (-29.0, 11.5), (29.0, 11.5)), 2.75,
        "Board center, top view; +X away from microSD, +Y toward GPIO header",
        "https://datasheets.raspberrypi.com/rpizero/raspberry-pi-zero-mechanical-drawing.pdf",
    ),
    "raspberry_pi_pico_rev3": PCBPattern(
        "Raspberry Pi Pico RP2040 Rev3 (non-wireless)", 21.0, 51.0,
        ((-5.7, -23.5), (5.7, -23.5), (-5.7, 23.5), (5.7, 23.5)), 2.1,
        "Board center, component-side top view; +Y toward micro-USB, +X right",
        "https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf",
    ),
}


def pcb_mounting_pattern(model: str) -> PCBPattern:
    """Look up an exact board model/revision in PCB_PATTERNS; unknown models raise ValueError.

    These are mounting data only, not universal ESP32 footprints, full outlines, component
    keep-outs or standoff sizes. Measure the actual board and its underside before printing.
    """
    try:
        return PCB_PATTERNS[model]
    except KeyError:
        raise ValueError(f"PCB model {model!r}: one of {', '.join(PCB_PATTERNS)}") from None
