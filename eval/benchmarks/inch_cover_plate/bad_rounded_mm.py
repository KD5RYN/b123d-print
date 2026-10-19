"""Known bad: the inch values rounded to whole millimetres (76 x 51 x 6, 4 mm holes 6 mm in)."""

from dataclasses import dataclass

from inch_cover_plate import plate

VARIANTS = {"": {}}


@dataclass(frozen=True)
class Dims:
    L: float = 76.0
    W: float = 51.0
    T: float = 6.0
    SCREW_D: float = 4.0
    EDGE: float = 6.0
    CENTER_D: float = 19.0


def build(d: Dims):
    return plate(d)
