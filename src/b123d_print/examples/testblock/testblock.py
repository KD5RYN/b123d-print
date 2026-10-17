"""Test block: rectangular block with a rounded notch across one wide face at mid-length.

The smallest complete example: a few measured dimensions, one fillet, one cut.
Print orientation: wide face (LENGTH x WIDTH) on the bed. Standalone part, no mating clearance.
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Cylinder, Mode, Part, Pos, Rot, fillet

BED = (Align.CENTER, Align.CENTER, Align.MIN)  # sit on Z=0


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    LENGTH: float = 35.9  # X, caliper photo 1
    WIDTH: float = 16.9  # Y, typed measurement
    THICKNESS: float = 9.8  # Z, average of caliper photos 2 and 3 (9.7, 9.9)
    END_FILLET: float = 1.0  # the four edges running across the width, at both ends
    NOTCH_WIDTH: float = 1.3  # along X, at the top surface (photo 3, confirmed)
    NOTCH_DEPTH: float = 0.5  # into Z from the top face
    NOTCH_X: float = 0.0  # centered on the length

    @property
    def NOTCH_R(self):  # circular-arc profile: chord NOTCH_WIDTH at sagitta NOTCH_DEPTH
        return (self.NOTCH_WIDTH**2 / 4 + self.NOTCH_DEPTH**2) / (2 * self.NOTCH_DEPTH)


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    part = Box(d.LENGTH, d.WIDTH, d.THICKNESS, align=BED)
    part = fillet(part.edges().filter_by(Axis.Y), radius=d.END_FILLET)
    part -= (
        Pos(d.NOTCH_X, 0, d.THICKNESS - d.NOTCH_DEPTH + d.NOTCH_R)
        * Rot(90, 0, 0)
        * Cylinder(d.NOTCH_R, d.WIDTH + 2, mode=Mode.PRIVATE)
    )
    return part


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
