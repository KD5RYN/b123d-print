"""Text knob: a tapered control knob for a 6 mm D shaft, labelled on its curved side and along
an arc on its top.

Shows text beyond flat labels (the `text_on_surface` and `text_on_path` recipes):
- "VOL" is wrapped onto the conical side, sunk into it along the surface normal: wrapping keeps
  the letters' size on the curve, so the flat-text minimums still hold (BP-X1..X3).
- "VOLUME" follows an arc along the far edge of the top, sunk 0.6 mm (three 0.2 mm layers), and a
  pointer groove runs from the middle to the near edge, above the side label.
- The text is its own solid (`label(d)`): for a two-colour print it is the inlay that fills the
  pockets (`knob & label`), flush with the surface.

Print orientation: as used, its base on the bed (Z=0); the D bore opens downward, its roof a
6 mm bridge. The side text stands up on a wall: the roofs of its sunk strokes are 0.8 mm
overhangs, which print without support. No supports. An example with chosen sizes, not printed
yet. Author: b123d-print contributors. License: CC0 1.0 (no attribution needed).
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, CenterArc, Cone, Cylinder, Part, Pos, chamfer

from b123d_print import View, hole_comp, load_settings
from b123d_print.recipes import bed_chamfer, text_on_path, text_on_surface

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: chosen, not measured)."""

    BASE_D: float = 38.0
    TOP_D: float = 32.0  # a 9.5 degree taper: the side leans in, no overhang
    HEIGHT: float = 18.0
    SHAFT_D: float = 6.0  # common 6 mm D shaft (potentiometers, encoders)
    SHAFT_FLAT: float = 4.5  # across the flat
    SHAFT_FIT: float = load_settings(__file__).press_fit  # per side: snug on the shaft (BP-F1)
    HOLE_COMP: float = hole_comp(__file__)  # the bore is vertical
    BORE_DEPTH: float = 12.0  # leaves 6 mm of top over the shaft
    SIDE_TEXT: str = "VOL"
    SIDE_SIZE: float = 6.0  # characters >= 5 mm (BP-X3)
    SIDE_DEPTH: float = 0.8  # into the side, along its normal
    TOP_TEXT: str = "VOLUME"
    TOP_SIZE: float = 5.0
    TOP_ARC_R: float = 10.0  # the baseline's radius: >= 2 x the text size keeps the letters open;
    # the capitals (~0.7 x size) end at 13.5, inside the 15 mm flat of the top
    TOP_DEPTH: float = 0.6  # 3 layers at 0.2 (BP-X1)
    POINTER_W: float = 1.2  # 3 line widths
    POINTER_L: float = 7.0
    EDGE_CHAMFER: float = 1.0  # top edge
    BED_CHAMFER: float = 0.5  # BP-B1, B2

    @property
    def side_at(self) -> tuple:  # a point just outside the side, half way up, facing -Y
        return (0, -self.BASE_D, self.HEIGHT / 2)


VARIANTS = {"": {}}


def body(d: Dims) -> Part:
    knob = Cone(d.BASE_D / 2, d.TOP_D / 2, d.HEIGHT, align=BED)
    knob = chamfer(knob.edges().sort_by(Axis.Z)[-1], d.EDGE_CHAMFER)
    bore_d = d.SHAFT_D + 2 * d.SHAFT_FIT + d.HOLE_COMP
    flat = d.SHAFT_FLAT + 2 * d.SHAFT_FIT + d.HOLE_COMP  # across the flat, to the far side of the bore
    bore = Cylinder(bore_d / 2, d.BORE_DEPTH, align=BED) & Pos(0, flat - bore_d / 2, 0) * Box(
        bore_d, bore_d, d.BORE_DEPTH, align=(Align.CENTER, Align.MAX, Align.MIN))
    return bed_chamfer(knob - bore, d.BED_CHAMFER)


def label(d: Dims) -> Part:
    """The text and the pointer as one solid: what body(d) loses to them, or a second colour."""
    side = text_on_surface(body(d), d.SIDE_TEXT, at=d.side_at, size=d.SIDE_SIZE, depth=d.SIDE_DEPTH, deboss=True)
    top_z = d.HEIGHT - d.TOP_DEPTH
    arc = CenterArc((0, 0), d.TOP_ARC_R, 160, -140)  # clockwise: reads along the top, far side
    top = Pos(0, 0, top_z) * text_on_path(d.TOP_TEXT, arc, size=d.TOP_SIZE, depth=d.TOP_DEPTH + 1)
    pointer = Pos(0, -d.TOP_D / 2 + d.EDGE_CHAMFER, top_z) * Box(
        d.POINTER_W, d.POINTER_L, d.TOP_DEPTH + 1, align=(Align.CENTER, Align.MIN, Align.MIN))
    return side + top + pointer


def build(d: Dims) -> Part:
    return body(d) - label(d)


def views(d: Dims):
    return [View("XY", d.HEIGHT - d.TOP_DEPTH / 2, "top text"), View("YZ", 0.0, "side text and bore")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
