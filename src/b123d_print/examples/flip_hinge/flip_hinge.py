"""Flip hinge: the print-in-place hinge recipe (`pip_hinge`) with its motion checked.

Shows the Motion check (Motion clearance in the docs): the two leaves print flat, side by side,
already joined by the pin; in use leaf B folds over about the pin's axis onto leaf A. The closed
(flat) and folded positions alone say nothing about the knuckles in between, so `checks(d)`
declares the fold as a Motion: leaf B turned 0..OPEN_DEG about the hinge axis, against leaf A,
with the gap held at MIN_CLEARANCE all the way (a gap that closes up part-way fuses in print).

- Every gap is the print-in-place clearance: the user's `pip_clearance` (0.3 default; sources
  give at least 0.2-0.3 mm per side, 0.1-0.15 only on a tuned printer; BP-F3). The pin and the
  bore's roof are 45-degree points, so nothing overhangs.
- Leaf B folds 180 degrees until it lies over leaf A (OPEN_DEG). Past that, about 15 degrees
  later, the leaves meet: setting OPEN_DEG = 220 makes the Motion check fail there, which the
  test suite does on purpose.

Print orientation: both leaves flat on the bed (Z=0), knuckles along X. No supports. Break it
free by flexing the leaves gently. An example: not printed yet.
"""

from dataclasses import dataclass

from build123d import Compound, Part

from b123d_print import Motion, load_settings
from b123d_print.recipes import pip_hinge


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example, not measured)."""

    LENGTH: float = 30.0  # along the hinge axis (X)
    KNUCKLE_D: float = 10.0  # the axis sits at half of it above the bed
    PIN_D: float = 3.0
    LEAF: float = 12.0  # each leaf's width away from the knuckles (Y)
    LEAF_T: float = 2.0
    KNUCKLES: int = 3
    CLEARANCE: float = load_settings(__file__).pip_clearance  # per side, every gap (BP-F3)
    MIN_CLEARANCE: float = 0.2  # per side: smallest gap allowed anywhere in the motion (BP-F3 low end)
    OPEN_DEG: float = 180.0  # leaf B folded flat over leaf A

    @property
    def axis_z(self) -> float:
        return self.KNUCKLE_D / 2


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    return pip_hinge(d.LENGTH, d.KNUCKLE_D, d.PIN_D, d.LEAF, d.LEAF_T, d.KNUCKLES, d.CLEARANCE)


def assembly(d: Dims):
    """The two leaves as printed (they are one print, two solids): leaf A (-Y, with the pin) and
    leaf B (+Y, with the bore), which turns."""
    a, b = sorted(build(d).solids(), key=lambda s: s.center().Y)
    return [(Part(Compound([a]).wrapped), "#3a6ea5", "leaf A"), (Part(Compound([b]).wrapped), "#e0a030", "leaf B")]


def checks(d: Dims):
    return [Motion("leaf B", axis_point=(0, 0, d.axis_z), axis_dir=(1, 0, 0), start_deg=0, end_deg=d.OPEN_DEG,
                   against=("leaf A",), min_clearance=d.MIN_CLEARANCE, label="fold over")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
