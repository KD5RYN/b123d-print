"""Known bad: the hole positions used as part coordinates (from the origin, not from datum A)."""

from build123d import Box, Cylinder, Part, Pos

from datum_hole_plate import CENTER_BED, Dims

VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Box(d.L, d.W, d.T, align=CENTER_BED)
    for x, y, dia in d.HOLES:
        p -= Pos(x, y, 0) * Cylinder(dia / 2, 3 * d.T)
    return p
