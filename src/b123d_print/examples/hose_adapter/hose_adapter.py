"""Hose adapter: a round pipe to a rounded-rectangle dust port, with an even wall.

Shows the `transition_loft` recipe: a straight loft from a round section to a rounded rectangle,
hollow, with a straight collar at each end that slips over the pipe and over the port with the
user's sliding clearance. The sides lean well under 45 degrees, so it prints standing on the
round end without supports.

Print orientation: the round collar on the bed (Z=0). An example with chosen sizes, not measured
or printed yet: measure your pipe's outside diameter and your port's outside size and corner
radius before printing. Author: b123d-print contributors. License: CC0 1.0 (no attribution
needed).
"""

from dataclasses import dataclass

from build123d import Part

from b123d_print import View, Wall, clearance
from b123d_print.recipes import bed_chamfer, transition_loft


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: chosen, not measured)."""

    PIPE_OD: float = 58.0  # round pipe outside diameter (estimate: a 2.25 in shop-vac tool end)
    PORT_W: float = 60.0  # dust port outside width (estimate)
    PORT_H: float = 30.0  # dust port outside height (estimate)
    PORT_R: float = 5.0  # dust port corner radius (estimate)
    CLEARANCE: float = clearance(__file__)  # sliding fit over pipe and port, per side
    WALL: float = 2.0  # 5 lines at 0.4 mm (BP-W3, W4)
    LENGTH: float = 40.0  # loft length: the widest change (14 mm in radius) leans ~19 deg
    COLLAR_PIPE: float = 20.0  # straight length over the pipe
    COLLAR_PORT: float = 20.0  # straight length over the port
    BED_CHAMFER: float = 0.5  # bed edges: chamfer, not fillet (BP-B1)

    # --- Derived ---
    @property
    def ROUND_OD(self):  # outside of the pipe collar: the pipe + clearance + wall, both sides
        return self.PIPE_OD + 2 * (self.CLEARANCE + self.WALL)

    @property
    def PORT_OUT(self):  # outside of the port collar as (w, h, r)
        grow = self.CLEARANCE + self.WALL
        return (self.PORT_W + 2 * grow, self.PORT_H + 2 * grow, self.PORT_R + grow)

    @property
    def HEIGHT(self):
        return self.COLLAR_PIPE + self.LENGTH + self.COLLAR_PORT


VARIANTS = {"": {}, "port80": dict(PORT_W=80.0, LENGTH=50.0)}


def build(d: Dims) -> Part:
    part = transition_loft(d.ROUND_OD, d.PORT_OUT, length=d.LENGTH, wall=d.WALL, collar_a=d.COLLAR_PIPE,
                           collar_b=d.COLLAR_PORT)
    return bed_chamfer(part, d.BED_CHAMFER)


def views(d: Dims):
    return [View("XZ", 0, "through the middle"), View("YZ", 0, "across the port's short side")]


def checks(d: Dims):
    """The wall through the loft, where it leans most (the port's short side)."""
    z = d.COLLAR_PIPE + d.LENGTH / 2
    return [Wall("part", "YZ", 0, near=(d.ROUND_OD / 2 - 4, z), radius=6, min=1.2, label="loft wall")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
