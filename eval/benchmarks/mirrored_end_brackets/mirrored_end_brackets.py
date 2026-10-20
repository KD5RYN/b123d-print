"""Benchmark reference: a left and a right end bracket, the right one the mirror image of the left.

Left, print orientation = in use: base plate on the bed, lip standing along its back edge (+Y),
the front corner at the outer (+X) end cut off at 45 deg, the screw hole near the inner (-X) end.
Right: the left mirrored across the YZ plane (lip still at the back, the cut corner and the hole
swapped end for end). A copy, or a copy turned 180 deg, is not a right-hand part.
"""

from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Part, Plane, Polygon, Pos, extrude, mirror

BED = (Align.MIN, Align.MIN, Align.MIN)


@dataclass(frozen=True)
class Dims:
    L: float = 60.0  # task: base length, X
    W: float = 30.0  # task: base depth, Y (lip included)
    T: float = 4.0  # task: base thickness
    LIP_T: float = 4.0  # task: lip thickness (Y)
    LIP_H: float = 15.0  # task: lip height above the base
    CUT: float = 15.0  # task: 45 deg corner cut, leg length
    HOLE_D: float = 4.5  # task
    HOLE_X: float = 12.0  # task: from the inner end
    HOLE_Y: float = 13.0  # task: from the front edge


VARIANTS = {"": {}}


def left(d: Dims) -> Part:
    outline = Polygon((0, 0), (d.L - d.CUT, 0), (d.L, d.CUT), (d.L, d.W), (0, d.W), align=None)
    p = extrude(outline, d.T)
    p += Pos(0, d.W - d.LIP_T, 0) * Box(d.L, d.LIP_T, d.T + d.LIP_H, align=BED)
    p -= Pos(d.HOLE_X, d.HOLE_Y, 0) * Cylinder(d.HOLE_D / 2, 3 * d.T)
    return p


def right(d: Dims) -> Part:
    return mirror(left(d), Plane.YZ)


def build(d: Dims) -> dict:
    return {"left": lambda: left(d), "right": lambda: right(d)}
