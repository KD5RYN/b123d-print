"""Hole-size calibration coupon: find HOLE_COMP for your printer and material.

FDM printers print small vertical holes undersize (the outline is a polygon inside the circle,
and the slicer's outer wall squeezes in). Print this coupon with your usual settings, measure
each hole with calipers (or the largest drill bit / gauge pin that passes), then:

    HOLE_COMP = average(nominal - measured)          # mm, on the diameter

and put it in your user config, ~/.config/b123d-print/config.toml:

    [print]
    hole_comp = 0.4

The holes here are cut at their NOMINAL size on purpose (no compensation): this part measures it.
If the error grows with size, use the average over the sizes you actually use.

Print orientation: flat on the bed, labels up.
"""

from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Mode, Part, Pos, Text, chamfer, extrude, Axis

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    HOLE_SIZES: tuple = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0)  # M2 ... M8 clearance/pilot range
    PER_ROW: int = 4
    PITCH: float = 14.0  # hole center to center
    ROW_PITCH: float = 17.0  # room for the label above each hole
    MARGIN: float = 6.0  # plate edge to the outermost hole edge (and labels)
    THICKNESS: float = 3.0  # thick enough to measure, thin enough to print fast
    LABEL_SIZE: float = 4.0
    LABEL_DEPTH: float = 0.4  # engraved, two layers at 0.2
    LABEL_GAP: float = 1.5  # hole edge to label
    EDGE_CHAMFER: float = 0.4  # top edges only; bed edges stay sharp (no elephant-foot flare)

    @property
    def ROWS(self):
        return -(-len(self.HOLE_SIZES) // self.PER_ROW)

    @property
    def WIDTH(self):
        return (self.PER_ROW - 1) * self.PITCH + max(self.HOLE_SIZES) + 2 * self.MARGIN

    @property
    def DEPTH(self):
        return (self.ROWS - 1) * self.ROW_PITCH + max(self.HOLE_SIZES) + self.LABEL_GAP + self.LABEL_SIZE + 2 * self.MARGIN

    def hole_xy(self, i: int):
        row, col = divmod(i, self.PER_ROW)
        x = (col - (self.PER_ROW - 1) / 2) * self.PITCH
        y0 = -self.DEPTH / 2 + self.MARGIN + max(self.HOLE_SIZES) / 2
        return x, y0 + (self.ROWS - 1 - row) * self.ROW_PITCH


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Box(d.WIDTH, d.DEPTH, d.THICKNESS, align=BED)
    p = chamfer(p.edges().group_by(Axis.Z)[-1], length=d.EDGE_CHAMFER)
    for i, size in enumerate(d.HOLE_SIZES):
        x, y = d.hole_xy(i)
        p -= Pos(x, y, 0) * Cylinder(size / 2, d.THICKNESS * 3, mode=Mode.PRIVATE)  # nominal, no comp
        label = Text(f"{size:g}", d.LABEL_SIZE, align=(Align.CENTER, Align.MIN))
        p -= Pos(x, y + size / 2 + d.LABEL_GAP, d.THICKNESS - d.LABEL_DEPTH) * extrude(label, d.LABEL_DEPTH + 1)
    return p


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
