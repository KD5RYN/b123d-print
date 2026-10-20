"""Known bad: holes right from datum A, but the origin left at datum A instead of the plate's centre."""

from build123d import Align, Box, Cylinder, Part, Pos

from datum_hole_plate import Dims

VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Box(d.L, d.W, d.T, align=(Align.MIN, Align.MIN, Align.MIN))
    for x, y, dia in d.HOLES:
        p -= Pos(x, y, 0) * Cylinder(dia / 2, 3 * d.T)
    return p
