"""2-gang to 1-gang adapter wall plate (midway size) for a smart switch.

Mounts to a 2-gang box with 4 #6-32 pan-head screws in counterbored corner holes. The smart switch
mounts on the front and screws into the 2 center holes from the front, so no pocket is needed
on the back.

Status: both variants (standard and 140) printed, mounted and in use.

Variants (see VARIANTS): `uv run plate_2gang_to_1gang.py [--variant 140]`, default builds all.

Shows: Dims dataclass + VARIANTS, hole compensation from the user's config, and a wall check
around the counterbores (the first print of this part broke through a 0.05 mm skin there).

Print orientation: front face down on the bed (Z=0), back rim up. X = installed width
(gangs side by side), Y = installed height.

Back is simplified from the injection-molded original: flat face, perimeter rim, bosses tied
together by an inner rim around the opening and straight stiffening ribs out to the outer rim.
"""

from dataclasses import dataclass
from math import atan2, degrees, hypot

from build123d import (
    Align,
    Axis,
    Box,
    Cone,
    Cylinder,
    Mode,
    Pos,
    Rot,
    RectangleRounded,
    Circle,
    chamfer,
    extrude,
    fillet,
    offset,
)

from b123d_print import View, Wall, hole_comp

BED = (Align.CENTER, Align.CENTER, Align.MIN)  # sit on Z=0


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. Defaults are the standard (midway) plate; variants override a few."""

    # --- Plate (mm) ---
    PLATE_W: float = 125.0  # X, caliper photo 121830300
    PLATE_H: float = 125.0  # Y, typed measurement
    PLATE_DEPTH: float = 6.5  # Z, front face to back of rim, typed measurement
    FACE_T: float = 2.4  # front face thickness, caliper photo 122142770
    RIM_WALL: float = 2.35  # from the original: (125.0 - 120.3 inside of rim) / 2; not critical
    CORNER_R: float = 3.0  # plan-view outer corner radius
    FRONT_EDGE_FILLET: float = 3.0  # front perimeter edge (on the bed); leaves ~2.1 mm wall at the rim
    BACK_EDGE_CHAMFER: float = 0.4  # back edge of the rim

    # --- Opening (original size, already has clearance for the switch) ---
    OPENING_W: float = 52.5  # X, typed measurement
    OPENING_H: float = 73.8  # Y, caliper photo 121922590
    OPENING_CORNER_R: float = 1.0
    OPENING_FRONT_CHAMFER: float = 0.5
    NOTCH_W: float = 6.0  # arc notch at top/bottom center of the opening, estimate from photo
    NOTCH_DEPTH: float = 1.3  # beyond the opening edge, typed measurement (leaves ~2 mm to the center hole)

    # --- Holes (NEMA WD-6 spacing) ---
    BOX_SCREW_SPACING_Y: float = 83.3  # 3-9/32", 2-gang box ears
    GANG_SPACING_X: float = 46.0  # 1-13/16"
    DEVICE_SCREW_SPACING_Y: float = 83.3  # 3-9/32", the switch's screws, centered
    # Hole sizes below are the target printed sizes; HOLE_COMP is added when cutting.
    HOLE_COMP: float = hole_comp(__file__)  # your printer's, from b123d_print config (0 until measured)
    CORNER_HOLE_D: float = 3.7  # #6-32 clearance, typed measurement
    CBORE_D: float = 7.3  # counterbore for pan heads (head is 6.6), matches the original
    CBORE_DEPTH: float = 2.5  # straight wall, gets pan heads below the face; original's depth
    CBORE_LIP_CHAMFER: float = 0.4  # softens the edge at the front face like the original
    CENTER_HOLE_D: float = 2.8  # 6-32 threads straight into the plastic, typed measurement
    BOSS_CLEARANCE: float = 2.2  # bosses/ribs stop this far short of the rim (original: 6.5 rim, 4.3 bosses)
    BOSS_WALL: float = 2.0  # min wall around a hole/counterbore inside a boss (first print: 8.0 boss
    #                       around the 7.8 counterbore left ~0.05 mm and broke through)
    MIN_WALL: float = 0.8  # wall check limit around the cuts. The thinnest spot is the web between
    #                      each corner counterbore and the opening: 1.1 mm (0.85 with 0.5 hole
    #                      comp), which printed fine
    CENTER_BOSS_D: float = 7.0  # 3.3 cut hole -> 1.85 wall
    CORNER_PAD_WALL: float = 4.0  # frame material outside each counterbore at the corner bosses

    # --- Back stiffening (all at BOSS_DEPTH, below the outer rim) ---
    INNER_RIM_W: float = 1.5  # min wall around the opening (frame is wider almost everywhere)
    RIB_W: float = 1.5

    # --- Derived ---
    @property
    def BOSS_DEPTH(self):  # front face to back of boss
        return self.PLATE_DEPTH - self.BOSS_CLEARANCE

    @property
    def CORNER_BOSS_D(self):  # wraps the counterbore with BOSS_WALL all round
        return self.CBORE_D + self.HOLE_COMP + 2 * self.BOSS_WALL

    @property
    def FRAME_CORNER_R(self):  # frame corners are concentric with the corner bosses
        return (self.CBORE_D + self.HOLE_COMP) / 2 + self.CORNER_PAD_WALL

    @property
    def FRAME_X(self):  # half-width of the solid frame around the opening
        return self.GANG_SPACING_X / 2 + self.FRAME_CORNER_R

    @property
    def FRAME_Y(self):  # half-height of the solid frame
        return self.BOX_SCREW_SPACING_Y / 2 + self.FRAME_CORNER_R

    @property
    def RIM_INNER_W(self):
        return self.PLATE_W - 2 * self.RIM_WALL

    @property
    def RIM_INNER_H(self):
        return self.PLATE_H - 2 * self.RIM_WALL

    @property
    def NOTCH_R(self):
        return (self.NOTCH_W**2 / 4 + self.NOTCH_DEPTH**2) / (2 * self.NOTCH_DEPTH)

    @property
    def CORNER_HOLES(self):
        return [
            (sx * self.GANG_SPACING_X / 2, sy * self.BOX_SCREW_SPACING_Y / 2)
            for sx in (-1, 1)
            for sy in (-1, 1)
        ]

    @property
    def CENTER_HOLES(self):
        return [(0, sy * self.DEVICE_SCREW_SPACING_Y / 2) for sy in (-1, 1)]


# Variants: only what differs from the standard plate. Output files get the suffix.
VARIANTS = {
    "": {},  # standard midway plate, 125 x 125 x 6.5
    "140": dict(PLATE_W=140.0, PLATE_H=140.0, PLATE_DEPTH=8.0),  # oversize, deeper rim
}


def rib(d: Dims, p1, p2):
    """Straight rib from p1 to p2 (XY), from inside the face up to d.BOSS_DEPTH."""
    (x1, y1), (x2, y2) = p1, p2
    h = d.BOSS_DEPTH - d.FACE_T / 2
    return (
        Pos((x1 + x2) / 2, (y1 + y2) / 2, d.FACE_T / 2)
        * Rot(0, 0, degrees(atan2(y2 - y1, x2 - x1)))
        * Box(hypot(x2 - x1, y2 - y1), d.RIB_W, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    )


def build(d: Dims):
    # Shell: solid plate minus the back cavity
    plate = extrude(RectangleRounded(d.PLATE_W, d.PLATE_H, d.CORNER_R), d.PLATE_DEPTH)
    plate -= Pos(0, 0, d.FACE_T) * extrude(
        RectangleRounded(d.RIM_INNER_W, d.RIM_INNER_H, max(d.CORNER_R - d.RIM_WALL, 0.5)),
        d.PLATE_DEPTH,
    )

    # Bosses behind the holes
    for x, y in d.CORNER_HOLES:
        plate += Pos(x, y, 0) * Cylinder(d.CORNER_BOSS_D / 2, d.BOSS_DEPTH, align=BED)
    for x, y in d.CENTER_HOLES:
        plate += Pos(x, y, 0) * Cylinder(d.CENTER_BOSS_D / 2, d.BOSS_DEPTH, align=BED)

    # Opening outline with arc notches at top and bottom center
    opening = RectangleRounded(d.OPENING_W, d.OPENING_H, d.OPENING_CORNER_R)
    for sy in (-1, 1):
        opening += Pos(0, sy * (d.OPENING_H / 2 + d.NOTCH_DEPTH - d.NOTCH_R)) * Circle(d.NOTCH_R)

    # Solid frame around the opening that swallows all 6 bosses. Its corners are concentric with
    # the corner bosses. The opening cut below hollows it out.
    frame = RectangleRounded(2 * d.FRAME_X, 2 * d.FRAME_Y, d.FRAME_CORNER_R)
    frame += offset(opening, d.INNER_RIM_W)  # keeps a min wall where the frame is narrow
    plate += Pos(0, 0, d.FACE_T / 2) * extrude(frame, d.BOSS_DEPTH - d.FACE_T / 2)

    # Ribs end inside the outer rim wall so they fuse with it
    RIM_MID_X = d.PLATE_W / 2 - d.RIM_WALL / 2
    RIM_MID_Y = d.PLATE_H / 2 - d.RIM_WALL / 2
    EDGE_Y = d.BOX_SCREW_SPACING_Y / 2
    RIBS = [
        ((-d.GANG_SPACING_X / 2, EDGE_Y), (d.GANG_SPACING_X / 2, EDGE_Y)),  # ties the 3 top bosses
        ((-d.GANG_SPACING_X / 2, -EDGE_Y), (d.GANG_SPACING_X / 2, -EDGE_Y)),  # ties the 3 bottom bosses
        ((0, EDGE_Y), (0, RIM_MID_Y)),  # top center boss to rim
        ((0, -EDGE_Y), (0, -RIM_MID_Y)),  # bottom center boss to rim
        ((d.OPENING_W / 2, 0), (RIM_MID_X, 0)),  # side of opening to rim
        ((-d.OPENING_W / 2, 0), (-RIM_MID_X, 0)),
    ]
    RIBS += [  # corner bosses out to the plate corners
        ((sx * d.GANG_SPACING_X / 2, sy * EDGE_Y), (sx * (RIM_MID_X - 1), sy * (RIM_MID_Y - 1)))
        for sx in (-1, 1)
        for sy in (-1, 1)
    ]
    for p1, p2 in RIBS:
        plate += rib(d, p1, p2)

    # Edge treatment on the outside before cutting openings (simpler edge selection)
    plate = fillet(plate.edges().group_by(Axis.Z)[0], radius=d.FRONT_EDGE_FILLET)
    rim_top = plate.edges().group_by(Axis.Z)[-1]
    plate = chamfer(rim_top, length=d.BACK_EDGE_CHAMFER)

    # Cut the opening
    plate -= extrude(opening, d.PLATE_DEPTH)
    opening_edges = [
        e for e in plate.edges().group_by(Axis.Z)[0]
        if abs(e.center().X) <= d.OPENING_W / 2 + 0.01 and abs(e.center().Y) <= d.OPENING_H / 2 + d.NOTCH_DEPTH + 0.01
    ]
    plate = chamfer(opening_edges, length=d.OPENING_FRONT_CHAMFER)

    # Counterbored corner holes (counterbore opens on the front face, Z=0)
    for x, y in d.CORNER_HOLES:
        plate -= Pos(x, y, 0) * Cylinder((d.CORNER_HOLE_D + d.HOLE_COMP) / 2, d.PLATE_DEPTH, align=BED, mode=Mode.PRIVATE)
        plate -= Pos(x, y, 0) * Cylinder((d.CBORE_D + d.HOLE_COMP) / 2, d.CBORE_DEPTH, align=BED, mode=Mode.PRIVATE)
        plate -= Pos(x, y, 0) * Cone(
            (d.CBORE_D + d.HOLE_COMP) / 2 + d.CBORE_LIP_CHAMFER,
            (d.CBORE_D + d.HOLE_COMP) / 2,
            d.CBORE_LIP_CHAMFER,
            align=BED, mode=Mode.PRIVATE
        )

    # Center holes for the switch screws
    for x, y in d.CENTER_HOLES:
        plate -= Pos(x, y, 0) * Cylinder((d.CENTER_HOLE_D + d.HOLE_COMP) / 2, d.PLATE_DEPTH, align=BED, mode=Mode.PRIVATE)

    return plate


def views(d: Dims):
    # just past the face, where the counterbores cut into the bosses; and through the ribs
    return [View("XY", d.FACE_T + 0.05, "through the counterbores"), View("XY", d.FACE_T + 1.0, "through the ribs")]


def checks(d: Dims):
    x, y = d.CORNER_HOLES[0]
    cx, cy = d.CENTER_HOLES[0]
    return [
        # counterbore (CBORE_DEPTH) goes deeper than the face (FACE_T): material left around it
        Wall("", "XY", (d.FACE_T + d.CBORE_DEPTH) / 2, near=(x, y), radius=d.CORNER_BOSS_D / 2 + 1,
             min=d.MIN_WALL, label="corner counterbore in its boss"),
        Wall("", "XY", d.FACE_T + 1.0, near=(cx, cy), radius=d.CENTER_BOSS_D / 2 + 0.5,
             min=d.MIN_WALL, label="center screw boss"),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
