"""Known bad: a good orientation, but centred on the origin instead of resting on Z=0."""

from dataclasses import dataclass

from build123d import Part, Pos

from orient_shelf_bracket import Dims as _Dims, bracket


@dataclass(frozen=True)
class Dims(_Dims):
    pass


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    return Pos(0, 0, -d.WIDTH / 2) * bracket(d)
