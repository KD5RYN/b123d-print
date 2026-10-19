"""Split trim: a 420 mm trim strip, too long for a 256 mm bed, cut in two and keyed together.

Shows `b123d_print.joints` (docs/using/splitting.md): `split()` cuts the strip at X = 0 and puts
the joint on the cut. The standard variant uses a bowtie key sunk into the back across the seam
(it takes the pull across the seam) and two square pins (they line the faces up and stop the
pieces twisting); `dovetail` uses one through dovetail instead (the pieces slide together along
Z). The pins and the key are separate prints, laid flat so the load across the seam runs along
their layers (BP-S4); the female features are the male grown by CLEARANCE on every side (BP-J3).

Print orientation: the visible face down on the bed (it comes out smooth, and the bed edges get
chamfers, BP-O2), the back up, so the key recess opens upward and needs no support; the pin
sockets lie on their side, so they are square and stand on a corner (a 45-degree roof, BP-H3).
In use: the back against the wall, the two pieces end to end along X.
Assembly: dry-fit, then CA gel on the key and the pins (PLA, PETG), clamp along X while it sets;
the key also works dry with a screw through each piece into the wall (BP-J4, BP-J5).
Not printed yet: an example. Before printing both pieces, print the joint as a fit test (a crop
around the key and the pins, `templates(d)`).
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Part, Plane, Pos, chamfer

from b123d_print import Gap, Template, View, Wall, clearance
from b123d_print.joints import Bowtie, Dovetail, Dowel, split

BED_ALIGN = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example, not measured)."""

    LENGTH: float = 420.0  # along X; a 256 x 256 bed takes 362 mm at most, on the diagonal
    WIDTH: float = 40.0  # along Y
    THICK: float = 8.0  # along Z: visible face at Z=0, back at Z=THICK
    FACE_CHAMFER: float = 1.0  # the visible long edges, on the bed (BP-O2)
    BACK_CHAMFER: float = 0.5  # break the back's edges (BP-B1)
    CUT_X: float = 0.0  # where the strip is cut (the middle: two 210 mm pieces)
    BED: float = 256.0  # the bed's side each piece must fit (a common 256 x 256 bed)
    CLEARANCE: float = clearance(__file__)  # per side, from your config (default 0.2, BP-F1)
    JOINT: str = "keys"  # "keys": a bowtie key and two square pins; "dovetail": one through dovetail
    # bowtie key, sunk into the back across the seam
    KEY_LENGTH: float = 30.0  # across the seam (15 mm into each piece)
    KEY_WIDTH: float = 16.0  # at its ends
    KEY_WAIST: float = 8.0  # at the seam: half the width, the woodworkers' usual
    KEY_DEPTH: float = 4.0  # half the strip; leaves THICK - KEY_DEPTH - CLEARANCE = 3.8 under it
    # square pins across the cut, at mid-thickness, either side of the key
    PIN: float = 3.5  # side of the square pin
    PIN_LENGTH: float = 16.0  # 8 mm into each piece
    PIN_ANGLE: float = 45.0  # the sockets stand on a corner: a 45 deg pointed roof, no bridge (BP-H3)
    PIN_Y: float = 13.0  # off the center line; the socket clears the key recess by 2.0 mm
    # the dovetail variant
    TAIL_WIDTH: float = 14.0  # at the root, on the cut
    TAIL_LENGTH: float = 10.0  # into the other piece
    TAIL_TAPER: float = 15.0  # degrees each side from the cut normal (see docs/using/splitting.md)

    @property
    def joints(self) -> list:
        if self.JOINT == "dovetail":
            return [Dovetail(self.TAIL_WIDTH, self.TAIL_LENGTH, self.TAIL_TAPER)]
        mid = self.THICK / 2
        return [Bowtie(self.KEY_LENGTH, self.KEY_WIDTH, self.KEY_WAIST, self.KEY_DEPTH, at=(0, self.THICK)),
                Dowel(self.PIN, self.PIN_LENGTH, square=True, at=(-self.PIN_Y, mid), angle=self.PIN_ANGLE),
                Dowel(self.PIN, self.PIN_LENGTH, square=True, at=(self.PIN_Y, mid), angle=self.PIN_ANGLE)]


VARIANTS = {"": {}, "dovetail": dict(JOINT="dovetail")}


def strip(d: Dims) -> Part:
    """The whole strip, before the cut."""
    p = Box(d.LENGTH, d.WIDTH, d.THICK, align=BED_ALIGN)
    p = chamfer(p.edges().group_by(Axis.Z)[0].filter_by(Axis.X), d.FACE_CHAMFER)
    return chamfer(p.edges().group_by(Axis.Z)[-1], d.BACK_CHAMFER)


def cut(d: Dims):
    # Plane.YZ: the joints' at=(u, v) is (Y, Z); piece a is below X = CUT_X
    return split(strip(d), Plane.YZ.offset(d.CUT_X), d.joints, clearance=d.CLEARANCE)


def build(d: Dims) -> dict[str, Part]:
    s = cut(d)
    pieces = {}
    for name, p in (("left", s.a), ("right", s.b)):
        bb = p.bounding_box()
        if max(bb.size.X, bb.size.Y) > d.BED:
            raise ValueError(f"{name}: {bb.size.X:.0f} mm does not fit the {d.BED:.0f} mm bed: cut it again")
        pieces[name] = Pos(-(bb.min.X + bb.max.X) / 2, 0, 0) * p  # centered for printing
    return pieces | s.loose


def assembly(d: Dims):
    s = cut(d)
    return [(s.a, "#3a6ea5", "left"), (s.b, "#e0a030", "right")] + [(p, "#888888", n) for n, p in s.placed.items()]


def views(d: Dims):
    if d.JOINT == "dovetail":
        return [View("XY", d.THICK / 2, "plan through the dovetail")]
    return [View("XY", d.THICK - 1.0, "plan through the key"), View("YZ", d.CUT_X + 4.0, "across the key and the pins"),
            View("XZ", d.PIN_Y, "along a pin")]


def templates(d: Dims):
    """The joint as a quick fit test: each piece's last 15 mm at the cut, with its half of the joint
    (the key recess and the pin sockets, or the tail and the slot); print them with the loose
    pieces and fit them together before the 210 mm pieces."""
    tail = d.TAIL_LENGTH if d.JOINT == "dovetail" else 0.0
    half_a = (d.LENGTH / 2 + d.CUT_X + tail) / 2  # each piece as printed is centered on X
    half_b = (d.LENGTH / 2 - d.CUT_X) / 2
    a0, b1 = half_a - tail - 15.0, -half_b + tail + 15.0
    box = (d.WIDTH + 2, d.THICK + 2)
    return [Template.crop(((a0 + half_a) / 2, 0, d.THICK / 2), (half_a - a0, *box), part="left", name="joint"),
            Template.crop(((b1 - half_b) / 2, 0, d.THICK / 2), (b1 + half_b, *box), part="right", name="joint")]


def checks(d: Dims):
    c = d.CLEARANCE
    pin_half = (d.PIN + 2 * c) / 2 ** 0.5  # half the socket's diagonal
    if d.JOINT == "dovetail":
        return []
    return [
        # the key and the pins sit CLEARANCE off every face of their recesses, in both pieces
        Gap("key1", "left", min=c - 0.01, max=c + 0.01, label="key in its recess"),
        Gap("key1", "right", min=c - 0.01, max=c + 0.01, label="key in its recess"),
        Gap("pin1", "right", min=c - 0.01, max=c + 0.01, label="pin in its socket"),
        # the wall between the key recess and a pin socket, where both are cut (assembled coordinates)
        Wall("left", "XY", d.THICK / 2, near=(d.CUT_X - 5.0, (d.KEY_WIDTH / 2 + d.PIN_Y - pin_half) / 2), radius=1.5,
             frame="assembly", label="between key recess and pin socket"),
        # and under and over a pin socket (it stands on a corner)
        Wall("left", "YZ", d.CUT_X - 4.0, near=(d.PIN_Y, 0.5), radius=1.0, frame="assembly", label="under a pin socket"),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
