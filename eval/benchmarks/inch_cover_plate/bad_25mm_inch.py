"""Known bad: converted with 25 mm to the inch instead of 25.4."""

from dataclasses import dataclass

from inch_cover_plate import plate

VARIANTS = {"": {}}
INCH = 25.0


@dataclass(frozen=True)
class Dims:
    L: float = 3.00 * INCH
    W: float = 2.00 * INCH
    T: float = 0.25 * INCH
    SCREW_D: float = 0.150 * INCH
    EDGE: float = 0.25 * INCH
    CENTER_D: float = 0.75 * INCH


def build(d: Dims):
    return plate(d)
