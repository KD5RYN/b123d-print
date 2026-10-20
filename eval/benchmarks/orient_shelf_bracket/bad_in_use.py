"""Known bad: the bracket printed the way it is used (wall leg standing, shelf leg overhanging)."""

from dataclasses import dataclass

from build123d import Part, Pos, Rot

from orient_shelf_bracket import Dims as _Dims, bracket


@dataclass(frozen=True)
class Dims(_Dims):
    pass


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Rot(90, 0, 0) * bracket(d)  # Y (wall leg) up: the shelf leg sticks out at the top
    return Pos(0, 0, -p.bounding_box().min.Z) * p
