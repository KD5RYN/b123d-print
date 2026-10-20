"""Benchmark reference: a mounting plate whose holes are dimensioned from datum A, the plate's
-X -Y corner, while the part's origin is at the plate's centre (bottom on Z=0)."""

from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Part, Pos

CENTER_BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    L: float = 90.0  # task: along X
    W: float = 60.0  # task: along Y
    T: float = 4.0  # task: thickness
    # task: (x, y, d) from datum A, the -X -Y corner
    HOLES: tuple = ((8.0, 8.0, 3.4), (82.0, 8.0, 3.4), (8.0, 52.0, 3.4), (30.0, 40.0, 6.5), (65.0, 30.0, 10.0))


VARIANTS = {"": {}}


def from_datum(d: Dims, x: float, y: float) -> tuple[float, float]:
    """A position from datum A in the part's frame (origin at the centre)."""
    return x - d.L / 2, y - d.W / 2


def build(d: Dims) -> Part:
    p = Box(d.L, d.W, d.T, align=CENTER_BED)
    for x, y, dia in d.HOLES:
        p -= Pos(*from_datum(d, x, y), 0) * Cylinder(dia / 2, 3 * d.T)
    return p
