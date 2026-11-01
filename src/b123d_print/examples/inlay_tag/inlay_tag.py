"""Inlay tag: a key tag with flush text in a second colour, for an AMS / MMU printer.

Shows a multi-body part (`bodies`, issue #167): the `inlay` recipe cuts the text's pocket out of
the tag with the text itself and keeps the text as its own body, so the 3MF opens in the slicer
as one object with two named, coloured parts (`tag` and `text`). Give each part its filament
there. The `bodies` check confirms the two do not overlap and touch; the other checks run on
their union, what the printer makes. The print sheet lists both bodies and the layers they share.

Print orientation: flat, text up, bottom on the bed (Z=0). An example with chosen sizes, not
measured or printed yet. Author: b123d-print contributors. License: CC0 1.0 (no attribution
needed).
"""

from dataclasses import dataclass

from build123d import Align, Box, Compound, Cylinder, Pos, fillet, Axis

from b123d_print import hole_comp
from b123d_print.recipes import bed_chamfer, inlay, text_label


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: chosen, not measured)."""

    TEXT: str = "KEYS"  # the inlaid text
    TEXT_SIZE: float = 9.0  # cap height: bold sans-serif >= 5 mm keeps strokes >= 2 line widths (BP-X1)
    TAG_W: float = 56.0  # along X
    TAG_H: float = 22.0  # along Y
    TAG_T: float = 3.2  # thickness: 16 layers at 0.2
    CORNER_R: float = 4.0  # rounded footprint corners
    RING_D: float = 5.0  # key-ring hole, printed size (a split ring's wire is ~1.5 mm)
    RING_EDGE: float = 4.5  # ring hole centre from the tag's left end
    INLAY_DEPTH: float = 0.6  # 3 layers at 0.2: few filament changes, still opaque (recipe notes)
    TEXT_SHIFT: float = 3.0  # text centre right of the tag centre, clear of the ring hole
    BED_CHAMFER: float = 0.5  # bed edge chamfer (BP-B2, provisional)
    TAG_COLOR: str = "#2b5fa8"  # display colour of the tag (the slicer assigns the filament)
    TEXT_COLOR: str = "white"  # display colour of the text
    HOLE_COMP: float = hole_comp(__file__)


VARIANTS = {"": {}, "name": dict(TEXT="SAM", TEXT_COLOR="#f2c230")}


def build(d: Dims) -> Compound:
    tag = Box(d.TAG_W, d.TAG_H, d.TAG_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    tag = fillet(tag.edges().filter_by(Axis.Z), d.CORNER_R)
    tag -= Pos(-d.TAG_W / 2 + d.RING_EDGE, 0, 0) * Cylinder((d.RING_D + d.HOLE_COMP) / 2, d.TAG_T,
                                                            align=(Align.CENTER, Align.CENTER, Align.MIN))
    tag = bed_chamfer(tag, d.BED_CHAMFER)
    text = Pos(d.TEXT_SHIFT, 0, d.TAG_T - d.INLAY_DEPTH) * text_label(d.TEXT, size=d.TEXT_SIZE, depth=d.INLAY_DEPTH + 1)
    return inlay(tag, text, color=d.TEXT_COLOR, base_color=d.TAG_COLOR, name="text", base_name="tag")


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
