"""V-slot mount: a plate that bolts onto 2020 V-slot extrusion with two M5 screws into T-nuts, keyed
into the slot so it stays square to the rail.

Shows mounting to aluminium extrusion (Threads, fasteners and gears in the docs): the rail and its
T-nuts are stand-ins from `bd_warehouse.open_builds` (`VSlotLinearRail("20x20")`, `TNut`), so the
overlap and gap checks prove the key drops into the slot and clears the nuts. The key is a V with
45 deg sides that sits in the slot's V groove and centers the plate, the user's sliding fit
clear of the groove's flanks; it is only 0.7 mm tall, because the T-nut's neck fills the slot
below that, and it stops short of the screw holes. The M5 clearance size comes from bd_warehouse's
`SocketHeadCapScrew`, plus HOLE_COMP. Four 2.8 mm pilot holes take M3 self-tapping screws for
whatever rides on the plate (an estimate: print a test pair, BP-T6).

Print orientation: the plate's outer face on the bed (Z=0), the key up; every hole vertical, no
supports. In use (assembly): the plate lies on the rail's top face, key down in the slot. Screws:
M5 x 8, through the 4 mm plate and 3 mm into the 4 mm T-nut; an M5 x 10 would end within 0.3 mm
of the slot's floor (measured on the stand-in).
An example: not printed yet.
"""

from dataclasses import dataclass

from bd_warehouse.fastener import SocketHeadCapScrew
from bd_warehouse.open_builds import TNut, VSlotLinearRail
from build123d import Align, Axis, Box, Cylinder, Part, Plane, Polygon, Pos, Rot, chamfer, extrude

from b123d_print import Gap, View, hole_comp, load_settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: a generic plate, not measured)."""

    PLATE_L: float = 60.0  # along the rail (X)
    PLATE_W: float = 36.0  # across it (Y)
    PLATE_T: float = 4.0  # ~9 lines of 0.45
    CORNER_C: float = 4.0  # the plate's vertical corners, chamfered: a chamfer at the bed running round
    # a rounded corner reads as a rounded bed edge to the bed-edge check
    # the key is a V that sits in the slot's 45 deg V groove and centers itself. V_MOUTH: the groove's
    # width at the rail's face, from bd_warehouse's OpenBuilds rail (its lips' opening is 6.24; suppliers
    # list the slot as 6 mm)
    V_MOUTH: float = 9.16
    CLEARANCE: float = load_settings(__file__).clearance  # per side, normal to the V's flanks (BP-F1)
    T_NUT_NECK: float = 1.0  # the T-nut's neck fills the lips' opening up to this far below the face
    NUT_GAP: float = 0.3  # between the key and the T-nut's neck
    KEY_HOLE_WALL: float = 1.0  # the key stops this far from each screw hole
    SCREW: str = "M5-0.8"  # into the T-nuts
    SCREW_PITCH: float = 40.0  # between the two screws, along the rail
    PILOT_D: float = 2.8  # M3 self-tapping, estimate (BP-T6: 2.6-2.9 by material and orientation)
    PILOT_X: float = 22.0  # the M3 pattern, from the center
    PILOT_Y: float = 12.0
    HOLE_COMP: float = hole_comp(__file__)  # all holes vertical
    BED_CHAMFER: float = 0.5  # BP-B1, B2
    RAIL_L: float = 80.0  # the stand-in rail's length

    @property
    def key_h(self) -> float:
        return self.T_NUT_NECK - self.NUT_GAP

    @property
    def key_w(self) -> float:  # at the plate: the V's mouth less the clearance measured across a 45 deg flank
        return self.V_MOUTH - 2 * self.CLEARANCE * 2 ** 0.5

    @property
    def screw_hole_d(self) -> float:  # bd_warehouse's "Normal" clearance (5.5 for M5), target printed size
        return SocketHeadCapScrew(self.SCREW, 10).clearance_hole_diameters["Normal"]


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    p = Box(d.PLATE_L, d.PLATE_W, d.PLATE_T, align=BED)
    p = chamfer(p.edges().filter_by(Axis.Z), d.CORNER_C)
    p = chamfer(p.edges().group_by(Axis.Z)[0], d.BED_CHAMFER)
    # the key, in three pieces that stop short of the screw holes (a hole through it would leave thin
    # slivers each side)
    gap = d.screw_hole_d + d.HOLE_COMP + 2 * d.KEY_HOLE_WALL
    ends = [-d.PLATE_L / 2, -d.SCREW_PITCH / 2 - gap / 2, -d.SCREW_PITCH / 2 + gap / 2,
            d.SCREW_PITCH / 2 - gap / 2, d.SCREW_PITCH / 2 + gap / 2, d.PLATE_L / 2]
    w, h = d.key_w / 2, d.key_h
    v = Polygon((-w, d.PLATE_T), (w, d.PLATE_T), (w - h, d.PLATE_T + h), (-w + h, d.PLATE_T + h), align=None)
    for x0, x1 in zip(ends[::2], ends[1::2]):  # sides at 45 deg, facing up in print: no overhang
        p += Pos(x0, 0, 0) * extrude(Plane.YZ * v, x1 - x0)
    for x in (-d.SCREW_PITCH / 2, d.SCREW_PITCH / 2):
        p -= Pos(x, 0, 0) * Cylinder((d.screw_hole_d + d.HOLE_COMP) / 2, d.PLATE_T, align=BED)
    for x in (-d.PILOT_X, d.PILOT_X):
        for y in (-d.PILOT_Y, d.PILOT_Y):
            p -= Pos(x, y, 0) * Cylinder((d.PILOT_D + d.HOLE_COMP) / 2, d.PLATE_T, align=BED)
    return p


def assembly(d: Dims):
    """The plate on the rail's top face (Z=0), key down; the rail along X below it."""
    plate = Pos(0, 0, d.PLATE_T) * Rot(180, 0, 0) * build(d)
    rail = Pos(-d.RAIL_L / 2, 0, -10) * Rot(0, 90, 0) * VSlotLinearRail("20x20", d.RAIL_L)
    # the T-nut turned across the slot, pulled up by the screw: its 10 mm flange under the lips, its
    # 0.8 mm neck in their opening
    nuts = [Pos(x, 0, -d.T_NUT_NECK) * Rot(0, 0, 90) * TNut() for x in (-d.SCREW_PITCH / 2, d.SCREW_PITCH / 2)]
    return [(plate, "#3a6ea5", "plate"), (rail, "#aaaaaa", "2020 rail (stand-in)"),
            (nuts[0] + nuts[1], "#c9a227", "T-nuts (stand-in)")]


def views(d: Dims):
    return [View("YZ", d.SCREW_PITCH / 2, "through a screw and T-nut"), View("YZ", 0, "the key in the slot")]


def checks(d: Dims):
    # the key must clear the slot's V and the T-nuts' necks
    # (below the rail's face: the plate rests on it by design)
    key_zone = ((0, 0, -(d.key_h + 1) / 2 - 0.05), (d.PLATE_L - 2, 12, d.key_h + 1))
    return [Gap("plate", "2020 rail (stand-in)", min=0.1, within=key_zone, label="key in the slot"),
            Gap("plate", "T-nuts (stand-in)", min=0.1, within=key_zone, label="key above the T-nuts")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
