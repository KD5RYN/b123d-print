"""Hole-size calibration coupon: find HOLE_COMP (and HOLE_COMP_H) for your printer and material.

FDM printers print small holes undersize (the outline is a polygon inside the circle, and the
slicer's outer wall squeezes in), and holes lying on their side differently again: their top
sags (BP-H1, BP-H4). Print this coupon with your usual settings, then measure each hole with
calipers (or the largest drill bit / gauge pin that passes):

- the plate's vertical holes:       HOLE_COMP   = average(nominal - measured)   # on the diameter
- the tab's teardrop (upper) row:   HOLE_COMP_H = average(nominal - measured)   # pin gauge / drill bit

The tab's lower row is plain round horizontal holes for comparison: their tops sag, which is
why horizontal holes should be teardrops (BP-H3). Store the values in your user config,
~/.config/b123d-print/config.toml:

    [print]
    hole_comp = 0.4
    hole_comp_h = 0.5

or, with a printer profile set, for that printer + material:

    b123d-print printer calibrate hole_comp 0.4
    b123d-print printer calibrate hole_comp_h 0.5

The holes here are cut at their NOMINAL size on purpose (no compensation): this part measures it.
If the error grows with size, use the average over the sizes you actually use.

Print orientation: flat on the bed, labels up, the tab standing at the back.
"""

import math
from dataclasses import dataclass

from build123d import Align, Axis, Box, Cylinder, Mode, Part, Polygon, Pos, Rot, Text, chamfer, extrude

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    HOLE_SIZES: tuple = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0)  # M2 ... M8 clearance/pilot range
    PER_ROW: int = 4
    PITCH: float = 16.0  # hole center to center
    ROW_PITCH: float = 18.0  # room for the label above each hole
    MARGIN: float = 6.0  # plate edge to the outermost hole edge (and labels)
    THICKNESS: float = 3.0  # thick enough to measure, thin enough to print fast
    LABEL_SIZE: float = 5.0  # BP-X3: characters >= ~5 mm
    LABEL_DEPTH: float = 0.6  # BP-X1: >= 0.5, three layers at 0.2
    LABEL_GAP: float = 1.5  # hole edge to label
    EDGE_CHAMFER: float = 0.4  # top edges only; bed edges stay sharp (no elephant-foot flare)

    # --- horizontal holes: a tab standing at the back, holes along Y through it ---
    H_SIZES: tuple = (3.0, 4.0, 5.0, 6.0, 8.0)
    H_PITCH: float = 13.0
    TAB_T: float = 5.0  # tab thickness = hole length
    TAB_MARGIN: float = 3.0  # hole edge to the tab's edges and between the rows
    TEARDROP_ANGLE: float = 45.0  # roof angle from vertical, = the overhang limit

    @property
    def ROWS(self):
        return -(-len(self.HOLE_SIZES) // self.PER_ROW)

    @property
    def WIDTH(self):
        grid = (self.PER_ROW - 1) * self.PITCH + max(self.HOLE_SIZES) + 2 * self.MARGIN
        tab = (len(self.H_SIZES) - 1) * self.H_PITCH + max(self.H_SIZES) + 2 * self.MARGIN
        return max(grid, tab)

    @property
    def GRID_DEPTH(self):
        return (self.ROWS - 1) * self.ROW_PITCH + max(self.HOLE_SIZES) + self.LABEL_GAP + self.LABEL_SIZE + 2 * self.MARGIN

    @property
    def H_LABEL_STRIP(self):  # labels for the tab's columns, on the plate in front of it
        return self.LABEL_SIZE + 2 * self.LABEL_GAP

    @property
    def DEPTH(self):
        return self.GRID_DEPTH + self.H_LABEL_STRIP + self.TAB_T

    @property
    def TEAR_TIP(self):  # teardrop roof tip above the center, per unit radius
        return 1 / math.sin(math.radians(self.TEARDROP_ANGLE))

    @property
    def ROW1_Z(self):  # round row
        return self.THICKNESS + self.TAB_MARGIN + max(self.H_SIZES) / 2

    @property
    def ROW2_Z(self):  # teardrop row
        return self.ROW1_Z + max(self.H_SIZES) / 2 + self.TAB_MARGIN + max(self.H_SIZES) / 2

    @property
    def TAB_H(self):
        return self.ROW2_Z + max(self.H_SIZES) / 2 * self.TEAR_TIP + self.TAB_MARGIN

    @property
    def TAB_Y(self):  # tab center
        return self.DEPTH / 2 - self.TAB_T / 2

    def hole_xy(self, i: int):
        row, col = divmod(i, self.PER_ROW)
        x = (col - (self.PER_ROW - 1) / 2) * self.PITCH
        y0 = -self.DEPTH / 2 + self.MARGIN + max(self.HOLE_SIZES) / 2
        return x, y0 + (self.ROWS - 1 - row) * self.ROW_PITCH

    def h_x(self, i: int):
        return (i - (len(self.H_SIZES) - 1) / 2) * self.H_PITCH


VARIANTS = {"": {}}


def teardrop(d: float, length: float, angle: float) -> Part:
    """A horizontal teardrop hole along Y, centered on the origin: a circle with a pointed roof
    whose sides are `angle` from vertical (BP-H3)."""
    r = d / 2
    a = math.radians(angle)
    s, c = math.sin(a), math.cos(a)  # roof tangent to the circle at (+-r c, r s); tip at r / s
    roof = Polygon((-r * c, r * s), (0, r / s), (r * c, r * s), (0, 0), align=None)
    prof = Rot(90, 0, 0) * extrude(roof, length / 2, both=True)
    return Rot(90, 0, 0) * Cylinder(r, length) + prof


def build(d: Dims) -> Part:
    p = Box(d.WIDTH, d.DEPTH, d.THICKNESS, align=BED)
    tab = Pos(0, d.TAB_Y, 0) * Box(d.WIDTH, d.TAB_T, d.TAB_H, align=BED)
    p += tab
    p = chamfer(p.edges().group_by(Axis.Z)[-1], length=d.EDGE_CHAMFER)
    for i, size in enumerate(d.HOLE_SIZES):
        x, y = d.hole_xy(i)
        p -= Pos(x, y, 0) * Cylinder(size / 2, d.THICKNESS * 3, mode=Mode.PRIVATE)  # nominal, no comp
        label = Text(f"{size:g}", d.LABEL_SIZE, align=(Align.CENTER, Align.MIN))
        p -= Pos(x, y + size / 2 + d.LABEL_GAP, d.THICKNESS - d.LABEL_DEPTH) * extrude(label, d.LABEL_DEPTH + 1)
    y_lab = d.TAB_Y - d.TAB_T / 2 - d.LABEL_GAP - d.LABEL_SIZE
    for i, size in enumerate(d.H_SIZES):
        x = d.h_x(i)
        p -= Pos(x, d.TAB_Y, d.ROW1_Z) * Rot(90, 0, 0) * Cylinder(size / 2, d.TAB_T * 3, mode=Mode.PRIVATE)
        p -= Pos(x, d.TAB_Y, d.ROW2_Z) * teardrop(size, d.TAB_T * 3, d.TEARDROP_ANGLE)
        label = Text(f"{size:g}", d.LABEL_SIZE, align=(Align.CENTER, Align.MIN))
        p -= Pos(x, y_lab, d.THICKNESS - d.LABEL_DEPTH) * extrude(label, d.LABEL_DEPTH + 1)
    return p


def label_boxes(d: Dims) -> list:
    """Where the engraved labels are: thin slivers between glyphs there are cosmetic."""
    z = d.THICKNESS - d.LABEL_DEPTH / 2
    h = d.LABEL_DEPTH + 0.2
    w = 3 * d.LABEL_SIZE
    boxes = [((x, y + size / 2 + d.LABEL_GAP + d.LABEL_SIZE / 2, z), (w, d.LABEL_SIZE * 1.4, h))
             for size, (x, y) in ((s, d.hole_xy(i)) for i, s in enumerate(d.HOLE_SIZES))]
    y_lab = d.TAB_Y - d.TAB_T / 2 - d.LABEL_GAP - d.LABEL_SIZE / 2
    boxes += [((d.h_x(i), y_lab, z), (w, d.LABEL_SIZE * 1.4, h)) for i in range(len(d.H_SIZES))]
    return boxes


def checks(d: Dims):
    from b123d_print import ThinFeature

    # The round row's round-top warning is the point of the tab: leave it.
    return [ThinFeature("", ignore=label_boxes(d))]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
