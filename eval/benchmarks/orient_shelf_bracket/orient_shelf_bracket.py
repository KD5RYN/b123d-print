"""Benchmark reference: an L shelf bracket (no brace), printed lying on its side.

In use the wall leg stands against the wall and the shelf leg sticks out from its top. Lying on
its side, the L profile is in XY and the shelf's load bends it along the layers; nothing needs
support. Print orientation: side face on the bed (Z=0), wall leg along Y, shelf leg along +X at
the top (Y = WALL_H - T).
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Cylinder, Part, Pos, Rot, fillet

BED = (Align.MIN, Align.MIN, Align.MIN)


@dataclass(frozen=True)
class Dims:
    WIDTH: float = 30.0  # task: bracket width (Z when printed)
    WALL_H: float = 80.0  # task: wall leg length
    SHELF_D: float = 60.0  # task: shelf leg length, from the wall face
    T: float = 5.0  # task: both legs
    INSIDE_R: float = 6.0  # task: inside corner fillet
    HOLE_D: float = 4.5  # task: screw holes
    WALL_HOLES: tuple = (20.0, 50.0)  # task: from the wall leg's bottom end
    SHELF_HOLE: float = 40.0  # task: from the wall face


VARIANTS = {"": {}}


def bracket(d: Dims) -> Part:
    """The bracket on its side: wall leg along Y at X 0..T, shelf leg along +X at the top."""
    p = Box(d.T, d.WALL_H, d.WIDTH, align=BED) + Pos(0, d.WALL_H - d.T, 0) * Box(d.SHELF_D, d.T, d.WIDTH, align=BED)
    inside = p.edges().filter_by(Axis.Z).filter_by(lambda e: abs(e.center().X - d.T) < 1e-6 and abs(e.center().Y - (d.WALL_H - d.T)) < 1e-6)
    p = fillet(inside, d.INSIDE_R)
    for y in d.WALL_HOLES:
        p -= Pos(0, y, d.WIDTH / 2) * Rot(0, 90, 0) * Cylinder(d.HOLE_D / 2, 3 * d.T)
    p -= Pos(d.SHELF_HOLE, d.WALL_H, d.WIDTH / 2) * Rot(90, 0, 0) * Cylinder(d.HOLE_D / 2, 3 * d.T)
    return p


def build(d: Dims) -> Part:
    return bracket(d)
