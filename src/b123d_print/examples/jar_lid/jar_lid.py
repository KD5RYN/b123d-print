"""Jar lid: a screw cap for a 38-400 neck, with a modeled plastic bottle thread from bd_warehouse.

Shows a modeled thread that prints well (Threads, fasteners and gears in the docs): a coarse
bottle thread (6 per inch, 4.2 mm pitch), printed with its axis vertical, so every turn lies in
the layers and its flanks are no steeper than the overhang limit. The thread comes from
`bd_warehouse.thread.PlasticBottleThread` (ASTM D2911 finish 400, M style: a modified buttress
for plastic closures), with the user's sliding fit as its radial clearance
(`manufacturing_compensation`, per side). bd_warehouse fades both ends of a bottle thread, so
there is no blunt start to catch.

Print orientation: the top of the cap on the bed (Z=0), the skirt and its thread up. The grip ribs
run along Z. No supports. `check` warns of knife edges on the grip ribs: the XZ and YZ sections
graze the sides of ribs that run at an angle to them; the ribs are 1.6 mm wide. An example with the standard's sizes: check it on your jar before
printing many (a fit-test print: `b123d-print template jar_lid --slice XY:6` is a ring through
the thread).
"""

from dataclasses import dataclass
from functools import cached_property
from math import cos, radians, sin

from bd_warehouse.thread import PlasticBottleThread
from build123d import Align, Axis, Cylinder, Part, Plane, Polygon, Pos, Rot, chamfer, extrude

from b123d_print import ThinFeature, View, Wall, load_settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    FINISH: str = "M38SP400"  # ASTM D2911: M style, 38 mm over the bottle's thread crests (T), finish 400
    # radial clearance of the thread, per side: the user's sliding fit (BP-F1); bd_warehouse moves an
    # internal thread outward by this much
    THREAD_CLEARANCE: float = load_settings(__file__).clearance
    TOP_T: float = 2.0  # the cap's top (on the bed): 5 layers of 0.4 mm
    SKIRT_WALL: float = 2.0  # wall outside the thread root, ~4 lines of 0.45 (BP-W3)
    SEAL_GAP: float = 1.0  # between the top's inside and the first turn: room for the jar's lip
    SKIRT_EXTRA: float = 1.5  # skirt beyond the last turn, a lead-in for the jar's thread
    GRIP_RIBS: int = 24  # ribs around the skirt for grip
    GRIP_RIB_W: float = 1.6  # tangential width (~4 lines)
    GRIP_RIB_H: float = 1.0  # radial height
    RIB_END_GAP: float = 0.5  # the ribs stop this far short of the top chamfer
    BED_CHAMFER: float = 0.5  # the cap's rim on the bed (BP-B1, B2)
    TOP_CHAMFER: float = 0.6  # the skirt's open end, inside and out

    @cached_property
    def thread(self) -> PlasticBottleThread:
        return PlasticBottleThread(self.FINISH, external=False,
                                   manufacturing_compensation=self.THREAD_CLEARANCE)

    @property
    def root_r(self) -> float:  # where the thread meets the skirt: the bottle's T/2 plus the clearance
        return self.thread.root_radius

    @property
    def outer_r(self) -> float:
        return self.root_r + self.SKIRT_WALL

    @property
    def thread_z(self) -> float:  # the thread's own frame starts at 0; put its first turn here
        return self.TOP_T + self.SEAL_GAP

    @property
    def height(self) -> float:
        return self.thread_z + self.thread.length + self.SKIRT_EXTRA


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    cap = Cylinder(d.outer_r, d.height, align=BED)
    cap -= Pos(0, 0, d.TOP_T) * Cylinder(d.root_r, d.height, align=BED)
    cap = chamfer(cap.edges().group_by(Axis.Z)[0], d.BED_CHAMFER)
    cap = chamfer(cap.edges().group_by(Axis.Z)[-1], d.TOP_CHAMFER)
    # grip ribs standing on the bed, sunk past the bed chamfer into the skirt so they fuse without a
    # sliver; their tops slope back into the skirt at 45 deg (BP-O1), short of the top chamfer
    r0, r1 = d.outer_r - d.BED_CHAMFER - 0.1, d.outer_r + d.GRIP_RIB_H
    top = d.height - d.TOP_CHAMFER - d.RIB_END_GAP
    profile = Polygon((r0, 0), (r1, 0), (r1, top - d.GRIP_RIB_H), (r0, top - d.GRIP_RIB_H - d.BED_CHAMFER - 0.1), align=None)
    rib = extrude(Plane.XZ * profile, d.GRIP_RIB_W / 2, both=True)
    cap = cap.fuse(*[Rot(0, 0, 360 * i / d.GRIP_RIBS) * rib for i in range(d.GRIP_RIBS)])  # one boolean
    return cap + Pos(0, 0, d.thread_z) * d.thread


def thread_ends(d: Dims):
    """The boxes (center, size) of the thread's two faded ends, in print coordinates: bd_warehouse
    builds each as its own small solid next to the full-profile thread."""
    fades = sorted((Pos(0, 0, d.thread_z) * d.thread).solids(), key=lambda s: s.volume)[:2]
    return [(tuple(s.bounding_box().center()), tuple(s.bounding_box().size + (1, 1, 1))) for s in fades]


def views(d: Dims):
    return [View("XZ", 0, "through the thread"), View("XY", d.thread_z + d.thread.length / 2, "across the thread")]


def checks(d: Dims):
    r, a = d.root_r + d.SKIRT_WALL / 2, radians(180 / d.GRIP_RIBS)
    return [
        # the skirt carries the thread: measured halfway between two grip ribs
        Wall("", "XY", d.thread_z + d.thread.length / 2, near=(r * cos(a), r * sin(a)), radius=1.5,
             min=1.2, label="skirt behind the thread"),
        # the faded ends of the thread taper to nothing on purpose: a lead-in, not a wall
        ThinFeature("", ignore=thread_ends(d)),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
