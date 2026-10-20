"""Known bad: the inch values typed in as millimetres."""

from dataclasses import dataclass

from inch_cover_plate import plate

VARIANTS = {"": {}}


@dataclass(frozen=True)
class Dims:
    L: float = 3.0
    W: float = 2.0
    T: float = 0.25
    SCREW_D: float = 0.15
    EDGE: float = 0.25
    CENTER_D: float = 0.75


def build(d: Dims):
    return plate(d)
