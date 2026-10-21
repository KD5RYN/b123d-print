"""Fit calibration coupon: find the clearances (per side) that give a press, sliding and free fit,
and the gap parts printed in place need, on your printer and material (BP-F1, BP-F2, BP-F3).

Three printed parts:

- `peg`: a 6 mm peg on a handle.
- `holes`: holes for the peg, each one bigger by a clearance per side, from 0 to 0.40 mm. The
  label is the clearance in hundredths (5 = 0.05 mm per side). HOLE_COMP is applied, so first
  calibrate it with the hole_coupon example.
- `pip`: discs printed inside rings in one go ("print in place"), gaps 0.10 to 0.40 mm per side,
  same labels. After printing, push each disc out with a finger.

Read it:

- press_fit:     the smallest clearance the peg goes into with firm hand pressure
- clearance:     the smallest it slides into and out of without force (the default fit)
- free_fit:      the smallest it turns in freely, without catching
- pip_clearance: the smallest gap whose disc breaks free and turns

and store them for your printer + material:

    b123d-print printer calibrate clearance 0.15      (and press_fit, free_fit, pip_clearance)

or in ~/.config/b123d-print/config.toml under [print]. The pip discs measure the gap in XY only;
a gap above a part printed in place also needs at least one layer.

Print orientation: everything flat on the bed, labels up; the peg standing on its handle.
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Compound, Cylinder, Mode, Part, Pos, Text, chamfer, extrude

from b123d_print import Gap, ThinFeature, hole_comp

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    HOLE_COMP: float = hole_comp(__file__)  # your printer's; calibrate it first (hole_coupon)
    PEG_D: float = 6.0
    PEG_LEN: float = 8.0
    HANDLE_D: float = 16.0
    HANDLE_T: float = 3.0
    PEG_CHAMFER: float = 0.5  # lead-in on the peg tip
    CLEARANCES: tuple = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)  # per side, BP-F1 range
    PER_ROW: int = 5
    PITCH: float = 14.0  # hole center to center
    ROW_PITCH: float = 18.0
    PLATE_T: float = 6.0  # deep enough to feel the fit
    MARGIN: float = 5.0
    LABEL_SIZE: float = 5.0  # BP-X3
    LABEL_DEPTH: float = 0.6  # BP-X1
    LABEL_GAP: float = 1.5
    EDGE_CHAMFER: float = 0.4  # top edges only; bed edges stay sharp

    # --- print in place: discs inside rings ---
    PIP_GAPS: tuple = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40)  # per side, BP-F3 range
    DISC_D: float = 10.0
    PIP_T: float = 3.0
    PIP_PER_ROW: int = 3
    PIP_PITCH: float = 18.0

    @property
    def ROWS(self):
        return -(-len(self.CLEARANCES) // self.PER_ROW)

    @property
    def HOLES_W(self):
        return (self.PER_ROW - 1) * self.PITCH + self.PEG_D + 1 + 2 * self.MARGIN

    @property
    def HOLES_D(self):
        return (self.ROWS - 1) * self.ROW_PITCH + self.PEG_D + 1 + self.LABEL_GAP + self.LABEL_SIZE + 2 * self.MARGIN

    @property
    def PIP_ROWS(self):
        return -(-len(self.PIP_GAPS) // self.PIP_PER_ROW)

    @property
    def PIP_W(self):
        return (self.PIP_PER_ROW - 1) * self.PIP_PITCH + self.DISC_D + 1 + 2 * self.MARGIN

    @property
    def PIP_D(self):
        return (self.PIP_ROWS - 1) * (self.PIP_PITCH + self.LABEL_SIZE) + self.DISC_D + 1 + self.LABEL_GAP + self.LABEL_SIZE + 2 * self.MARGIN

    def grid(self, i: int, n: int, per_row: int, pitch: float, row_pitch: float, depth: float, d: float):
        """Center of item i of n, laid out in rows from the back; d = item diameter."""
        row, col = divmod(i, per_row)
        rows = -(-n // per_row)
        x = (col - (per_row - 1) / 2) * pitch
        y0 = -depth / 2 + self.MARGIN + d / 2
        return x, y0 + (rows - 1 - row) * row_pitch


    def hole_xy(self, i: int):
        return self.grid(i, len(self.CLEARANCES), self.PER_ROW, self.PITCH, self.ROW_PITCH, self.HOLES_D, self.PEG_D + 1)

    def pip_xy(self, i: int):
        return self.grid(i, len(self.PIP_GAPS), self.PIP_PER_ROW, self.PIP_PITCH, self.PIP_PITCH + self.LABEL_SIZE,
                         self.PIP_D, self.DISC_D + 1)


VARIANTS = {"": {}}

# Print intent (PRINT): fits are measured as printed, with nothing in the gaps.
PRINT = {
    "supports": "none",
    "orientation": "locked",
    "why": "a calibration coupon: it measures fits printed without supports, flat as modeled",
}


def _label(c: float, size: float):
    return Text(f"{round(c * 100):d}", size, align=(Align.CENTER, Align.MIN))


def peg(d: Dims) -> Part:
    p = Cylinder(d.HANDLE_D / 2, d.HANDLE_T, align=BED) + Pos(0, 0, d.HANDLE_T) * Cylinder(d.PEG_D / 2, d.PEG_LEN, align=BED)
    p = chamfer(p.edges().group_by(Axis.Z)[-1], length=d.PEG_CHAMFER)
    return p


def holes(d: Dims) -> Part:
    p = Box(d.HOLES_W, d.HOLES_D, d.PLATE_T, align=BED)
    p = chamfer(p.edges().group_by(Axis.Z)[-1], length=d.EDGE_CHAMFER)
    for i, c in enumerate(d.CLEARANCES):
        x, y = d.hole_xy(i)
        p -= Pos(x, y, 0) * Cylinder((d.PEG_D + 2 * c + d.HOLE_COMP) / 2, d.PLATE_T * 3, mode=Mode.PRIVATE)
        top = d.PEG_D / 2 + 0.5 + d.LABEL_GAP
        p -= Pos(x, y + top, d.PLATE_T - d.LABEL_DEPTH) * extrude(_label(c, d.LABEL_SIZE), d.LABEL_DEPTH + 1)
    return p


def pip(d: Dims) -> Part:
    """A plate with ring holes and a loose disc in each: separate solids, printed together."""
    plate = Box(d.PIP_W, d.PIP_D, d.PIP_T, align=BED)
    plate = chamfer(plate.edges().group_by(Axis.Z)[-1], length=d.EDGE_CHAMFER)
    discs = []
    for i, g in enumerate(d.PIP_GAPS):
        x, y = d.pip_xy(i)
        plate -= Pos(x, y, 0) * Cylinder((d.DISC_D + 2 * g + d.HOLE_COMP) / 2, d.PIP_T * 3, mode=Mode.PRIVATE)
        top = d.DISC_D / 2 + 0.5 + d.LABEL_GAP
        plate -= Pos(x, y + top, d.PIP_T - d.LABEL_DEPTH) * extrude(_label(g, d.LABEL_SIZE), d.LABEL_DEPTH + 1)
        discs.append(Pos(x, y, 0) * Cylinder(d.DISC_D / 2, d.PIP_T, align=BED))
    return Compound([*plate.solids(), *discs])


def build(d: Dims) -> dict:
    return {"peg": peg(d), "holes": holes(d), "pip": pip(d)}


def _label_boxes(d: Dims, centers, item_d: float, top: float) -> list:
    """The engraved labels: thin slivers between glyphs there are cosmetic."""
    y_off = item_d / 2 + 0.5 + d.LABEL_GAP + d.LABEL_SIZE / 2
    return [((x, y + y_off, top - d.LABEL_DEPTH / 2), (3 * d.LABEL_SIZE, 1.4 * d.LABEL_SIZE, d.LABEL_DEPTH + 0.2))
            for x, y in centers]


def checks(d: Dims):
    holes_labels = _label_boxes(d, [d.hole_xy(i) for i in range(len(d.CLEARANCES))], d.PEG_D, d.PLATE_T)
    pip_labels = _label_boxes(d, [d.pip_xy(i) for i in range(len(d.PIP_GAPS))], d.DISC_D, d.PIP_T)
    return [
        # the pip part's gaps are below pip_clearance on purpose: that is what it measures
        Gap("pip", min=min(d.PIP_GAPS) - 0.01, label="test gaps on purpose"),
        ThinFeature("holes", ignore=holes_labels),
        ThinFeature("pip", ignore=pip_labels),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
