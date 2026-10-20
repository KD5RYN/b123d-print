"""Benchmark reference: a cover plate dimensioned in inches, modeled in mm (1 in = 25.4 mm)."""

from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Part, Pos

INCH = 25.4  # mm, exact
BED = (Align.MIN, Align.MIN, Align.MIN)


@dataclass(frozen=True)
class Dims:
    L: float = 3.00 * INCH  # task: 3.00 in, X
    W: float = 2.00 * INCH  # task: 2.00 in, Y
    T: float = 0.25 * INCH  # task: 1/4 in
    SCREW_D: float = 0.150 * INCH  # task: #6 clearance, 0.150 in
    EDGE: float = 0.25 * INCH  # task: screw holes 1/4 in in from both edges
    CENTER_D: float = 0.75 * INCH  # task: 3/4 in centre hole


VARIANTS = {"": {}}


def plate(d: Dims) -> Part:
    p = Box(d.L, d.W, d.T, align=BED)
    for x in (d.EDGE, d.L - d.EDGE):
        for y in (d.EDGE, d.W - d.EDGE):
            p -= Pos(x, y, 0) * Cylinder(d.SCREW_D / 2, 3 * d.T)
    return p - Pos(d.L / 2, d.W / 2, 0) * Cylinder(d.CENTER_D / 2, 3 * d.T)


def build(d: Dims) -> Part:
    return plate(d)
