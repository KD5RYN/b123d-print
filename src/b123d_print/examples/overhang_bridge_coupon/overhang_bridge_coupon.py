"""Overhang and bridge calibration coupon: how steep an overhang and how long a bridge your printer
prints cleanly without supports (BP-O1, BP-O3).

- Back row: a wall with a ledge on each side whose underside is the labeled angle from vertical
  (40 to 75 deg). Look at the undersides: the steepest one still smooth, without drooping or
  curled edges, is your max_overhang.
- Front rows: flat bridges between two pillars, spans 5 to 40 mm (labeled). The longest one
  whose underside is flat (no sag you care about, strands not loose) is your max_bridge.

Print it with your usual material and settings, no supports. Store the values for your printer
+ material:

    b123d-print printer calibrate max_overhang 60
    b123d-print printer calibrate max_bridge 25

or in ~/.config/b123d-print/config.toml under [print]. The overhang and bridge checks use them.
Its PRINT intent says no supports, so the overhang check reports the steep ledges and long bridges
as accepted (OK) instead of warning: they are what it tests.

Print orientation: flat on the bed, as modeled.
"""

import math
from dataclasses import dataclass

from build123d import Align, Box, Part, Plane, Polygon, Pos, Text, extrude

from b123d_print import Overhang, ThinFeature

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    BASE_T: float = 2.0
    MARGIN: float = 5.0
    LABEL_SIZE: float = 5.0  # BP-X3
    LABEL_DEPTH: float = 0.6  # BP-X1

    # --- overhang ladder ---
    ANGLES: tuple = (40, 45, 50, 55, 60, 65, 70, 75)  # deg from vertical
    LEDGE_W: float = 9.0  # along X
    LEDGE_GAP: float = 2.0  # between ledges
    LEDGE_OUT: float = 8.0  # how far the underside reaches out from the wall
    LEDGE_FRONT: float = 2.0  # vertical front face, so the ledge has no knife edge
    LEDGE_START: float = 2.0  # underside starts this far above the base
    SPINE_T: float = 4.0

    # --- bridges ---
    SPANS: tuple = ((5, 10, 15, 20), (30, 40))  # mm, one tuple per row
    PILLAR_W: float = 5.0  # along X
    BRIDGE_D: float = 8.0  # along Y
    BRIDGE_H: float = 8.0  # underside above the base
    BRIDGE_T: float = 1.2  # slab thickness (BP-W2)
    BRIDGE_GAP: float = 4.0  # between neighbouring bridges
    ROW_GAP: float = 4.0  # between rows, plus the label strip

    def rise(self, angle: float) -> float:  # height the underside climbs over LEDGE_OUT
        return self.LEDGE_OUT / math.tan(math.radians(angle))

    @property
    def LADDER_W(self):
        return len(self.ANGLES) * self.LEDGE_W + (len(self.ANGLES) - 1) * self.LEDGE_GAP

    def row_w(self, spans) -> float:
        return sum(s + 2 * self.PILLAR_W for s in spans) + (len(spans) - 1) * self.BRIDGE_GAP

    @property
    def WIDTH(self):
        return max([self.LADDER_W] + [self.row_w(r) for r in self.SPANS]) + 2 * self.MARGIN

    @property
    def ROW_D(self):  # one bridge row with its label strip
        return self.BRIDGE_D + self.LABEL_SIZE + 2 + self.ROW_GAP

    @property
    def DEPTH(self):
        return self.MARGIN + len(self.SPANS) * self.ROW_D + self.LEDGE_OUT + self.SPINE_T + self.MARGIN

    @property
    def SPINE_Y(self):  # back face of the ledges = front face of the spine
        return self.DEPTH / 2 - self.MARGIN - self.SPINE_T

    @property
    def SPINE_H(self):
        return self.BASE_T + self.LEDGE_START + max(self.rise(a) for a in self.ANGLES) + self.LEDGE_FRONT

    def ledge_x(self, i: int) -> float:
        return -self.LADDER_W / 2 + self.LEDGE_W / 2 + i * (self.LEDGE_W + self.LEDGE_GAP)

    def row_y(self, r: int) -> float:  # bridge center line of row r (0 = the one nearest the ladder)
        return self.SPINE_Y - self.LEDGE_OUT - self.ROW_GAP - self.BRIDGE_D / 2 - r * self.ROW_D


VARIANTS = {"": {}}

# Print intent (PRINT): the steep ledges and long bridges are what it tests; supports under them
# would hide the result. The overhang check reports them as accepted, the print sheet says so.
PRINT = {
    "supports": "none",
    "orientation": "locked",
    "why": "a calibration coupon: it measures how steep an overhang and how long a bridge print without supports",
}


def ledge(d: Dims, angle: float) -> Part:
    """Profile in YZ: from the wall at the start height, out and up along the underside, then up
    the front face, back to the wall at the top. Extruded LEDGE_W along X."""
    z0 = d.BASE_T + d.LEDGE_START
    z1 = z0 + d.rise(angle)
    top = z1 + d.LEDGE_FRONT
    y_wall = d.SPINE_Y
    prof = Polygon((y_wall, z0), (y_wall - d.LEDGE_OUT, z1), (y_wall - d.LEDGE_OUT, top), (y_wall, top), align=None)
    return extrude(Plane.YZ * prof, d.LEDGE_W / 2, both=True)  # Plane.YZ: local x -> Y, y -> Z


def build(d: Dims) -> Part:
    p = Box(d.WIDTH, d.DEPTH, d.BASE_T, align=BED)
    p += Pos(0, d.SPINE_Y + d.SPINE_T / 2, 0) * Box(d.LADDER_W, d.SPINE_T, d.SPINE_H, align=BED)
    for i, a in enumerate(d.ANGLES):
        p += Pos(d.ledge_x(i), 0, 0) * ledge(d, a)
    for r, spans in enumerate(d.SPANS):
        x = -d.row_w(spans) / 2
        y = d.row_y(r)
        for s in spans:
            for px in (x + d.PILLAR_W / 2, x + d.PILLAR_W * 1.5 + s):
                p += Pos(px, y, d.BASE_T) * Box(d.PILLAR_W, d.BRIDGE_D, d.BRIDGE_H, align=BED)
            p += Pos(x + d.PILLAR_W + s / 2, y, d.BASE_T + d.BRIDGE_H) * Box(s + 2 * d.PILLAR_W, d.BRIDGE_D, d.BRIDGE_T, align=BED)
            x += s + 2 * d.PILLAR_W + d.BRIDGE_GAP
    for i, a in enumerate(d.ANGLES):  # labels on the ledge tops
        top = d.BASE_T + d.LEDGE_START + d.rise(a) + d.LEDGE_FRONT
        t = Text(f"{a}", d.LABEL_SIZE * 0.9, align=(Align.CENTER, Align.CENTER))
        p -= Pos(d.ledge_x(i), d.SPINE_Y - d.LEDGE_OUT / 2, top - d.LABEL_DEPTH) * extrude(t, d.LABEL_DEPTH + 1)
    for r, spans in enumerate(d.SPANS):  # labels on the base in front of each bridge
        x = -d.row_w(spans) / 2
        for s in spans:
            t = Text(f"{s}", d.LABEL_SIZE, align=(Align.CENTER, Align.MAX))
            p -= Pos(x + d.PILLAR_W + s / 2, d.row_y(r) - d.BRIDGE_D / 2 - 1, d.BASE_T - d.LABEL_DEPTH) * extrude(t, d.LABEL_DEPTH + 1)
            x += s + 2 * d.PILLAR_W + d.BRIDGE_GAP
    return p


def checks(d: Dims):
    labels = []
    for i, a in enumerate(d.ANGLES):
        top = d.BASE_T + d.LEDGE_START + d.rise(a) + d.LEDGE_FRONT
        labels.append(((d.ledge_x(i), d.SPINE_Y - d.LEDGE_OUT / 2, top - d.LABEL_DEPTH / 2),
                       (d.LEDGE_W, d.LEDGE_OUT, d.LABEL_DEPTH + 0.2)))
    for r, spans in enumerate(d.SPANS):
        x = -d.row_w(spans) / 2
        for s in spans:
            labels.append(((x + d.PILLAR_W + s / 2, d.row_y(r) - d.BRIDGE_D / 2 - 1 - d.LABEL_SIZE / 2, d.BASE_T - d.LABEL_DEPTH / 2),
                           (3 * d.LABEL_SIZE, 1.4 * d.LABEL_SIZE, d.LABEL_DEPTH + 0.2)))
            x += s + 2 * d.PILLAR_W + d.BRIDGE_GAP
    return [
        # steep ledges and long bridges are what this part tests: report them, never fail
        Overhang("", fail=False),
        ThinFeature("", ignore=labels),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
