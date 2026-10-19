"""Known bad: X and Y of every hole swapped (the plate is still 90 along X)."""

from build123d import Box, Cylinder, Part, Pos

from datum_hole_plate import CENTER_BED, Dims, from_datum

VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Box(d.L, d.W, d.T, align=CENTER_BED)
    for x, y, dia in d.HOLES:
        p -= Pos(*from_datum(d, y, x), 0) * Cylinder(dia / 2, 3 * d.T)
    return p
