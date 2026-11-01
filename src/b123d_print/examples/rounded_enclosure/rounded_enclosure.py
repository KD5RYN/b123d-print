"""Rounded enclosure: a box with rounded corners hollowed to an even wall, and a lid with a lip.

Shows the `hollow` recipe: the body is drawn solid (a box with its vertical edges rounded), then
hollowed with the top open, so the wall is the same thickness on the flat sides and round the
corners. The lid is drawn from 2D sketches: a rounded plate and a lip ring that follows the
inside of the walls with the user's sliding clearance.

Print orientation: the box on its floor, open side up; the lid top face down, the lip pointing up.
An example with chosen sizes, not measured or printed yet. Author: b123d-print contributors.
License: CC0 1.0 (no attribution needed).
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Part, Pos, RectangleRounded, Rot, extrude, fillet, offset

from b123d_print import Gap, View, Wall, clearance
from b123d_print.recipes import bed_chamfer, hollow

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: chosen, not measured)."""

    OUTER_W: float = 80.0  # X
    OUTER_L: float = 55.0  # Y
    HEIGHT: float = 30.0  # box height without the lid
    CORNER_R: float = 8.0  # outside corner radius: >= 2 x WALL keeps the inside corners round
    WALL: float = 2.0  # 5 lines at 0.4 mm (BP-W3, W4)
    LID_T: float = 2.0  # lid plate
    LIP_H: float = 5.0  # lip depth into the box
    LIP_T: float = 1.6  # lip ring, 4 lines
    CLEARANCE: float = clearance(__file__)  # lip to wall, sliding fit, per side
    BED_CHAMFER: float = 0.5  # bed edges: chamfer, not fillet (BP-B1)

    # --- Derived ---
    @property
    def INNER_R(self):  # inside corner radius after hollowing
        return self.CORNER_R - self.WALL

    @property
    def LIP_W(self):
        return self.OUTER_W - 2 * (self.WALL + self.CLEARANCE)

    @property
    def LIP_L(self):
        return self.OUTER_L - 2 * (self.WALL + self.CLEARANCE)


VARIANTS = {"": {}, "tall": dict(HEIGHT=50.0)}


def box(d: Dims) -> Part:
    body = Box(d.OUTER_W, d.OUTER_L, d.HEIGHT, align=BED)
    body = fillet(body.edges().filter_by(Axis.Z), d.CORNER_R)
    return bed_chamfer(hollow(body, d.WALL, open="top"), d.BED_CHAMFER)


def lid(d: Dims) -> Part:
    """Top face down: the plate on the bed, the lip pointing up."""
    plate = extrude(RectangleRounded(d.OUTER_W, d.OUTER_L, d.CORNER_R), d.LID_T)
    lip_out = RectangleRounded(d.LIP_W, d.LIP_L, d.INNER_R - d.CLEARANCE)
    ring = lip_out - offset(lip_out, -d.LIP_T)
    plate += Pos(0, 0, d.LID_T) * extrude(ring, d.LIP_H)
    return bed_chamfer(plate, d.BED_CHAMFER)


def build(d: Dims):
    return {"box": lambda: box(d), "lid": lambda: lid(d)}


def assembly(d: Dims):
    placed = Pos(0, 0, d.HEIGHT + d.LID_T) * Rot(180, 0, 0) * lid(d)
    return [(box(d), "#3a6ea5", "box"), (placed, "#e0a030", "lid")]


def views(d: Dims):
    return [View("XY", d.HEIGHT / 2, "mid height: the even wall round the corners")]


def checks(d: Dims):
    x = d.OUTER_W / 2 - d.CORNER_R * 0.3
    y = d.OUTER_L / 2 - d.CORNER_R * 0.3
    return [
        Wall("box", "XY", d.HEIGHT / 2, near=(x, y), radius=4, min=1.2, frame="assembly", label="corner wall"),
        Gap("lid", "box", min=d.CLEARANCE * 0.9, within=((0, 0, d.HEIGHT - d.LIP_H / 2), (d.OUTER_W + 2, d.OUTER_L + 2, 1))),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
