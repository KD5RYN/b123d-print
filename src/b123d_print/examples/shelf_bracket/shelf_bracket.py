"""Shelf bracket: an L bracket with a diagonal brace, screwed to a wall, a shelf resting on it.

Shows the `structural` design style (DESIGN_GUIDE DS-T*): the part prints lying on its side, so
the L and its brace are in the layers and the shelf's load bends them along the roads, never
across a layer line (BP-S4, BP-S5, DS-T1). Every inside corner of the profile is filleted at
least half the wall thick (DS-T3); the outside corner follows outside radius = inside radius +
wall (BP-R2); the arms and the brace are 6 mm, 13 lines of 0.45 (DS-T4). The screw holes are
teardrops (they lie on their side, BP-H3), at least 2.5 diameters from every edge (DS-T7).

Print orientation: side face on the bed (Z=0), the L profile in XY. In use: the wall arm runs
along Y against the wall (its back face at X=0), the shelf arm along +X at the top (Y=ARM_H).
Load: the shelf presses down (-Y) on the shelf arm, the top screw takes it in tension.
Slicer: 4-6 walls and 4+ top/bottom layers (DS-T2); not measured or printed yet: an example.
"""

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin

from build123d import Align, Axis, Box, Cylinder, Part, Polygon, Pos, Rot, chamfer, extrude, fillet

from b123d_print import hole_comp

BED = (Align.MIN, Align.MIN, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: estimates for a light bookshelf, not measured)."""

    STYLE: str = "structural"  # strong, load-bearing (DS-T*)
    WIDTH: float = 25.0  # Z in print orientation: the bracket's width under the shelf
    ARM_H: float = 100.0  # wall arm length, along Y
    ARM_L: float = 95.0  # shelf arm length, along X
    WALL: float = 6.0  # thickness of both arms and the brace: 13 lines of 0.45 (DS-T4)
    BRACE_FROM: float = 30.0  # the brace starts this far up the wall arm (Y)
    BRACE_TO: float = 70.0  # and meets the shelf arm this far out (X)
    INSIDE_R: float = 6.0  # the main inside corner: 1.0 x wall (DS-T3 asks >= 0.5)
    BRACE_R: float = 3.0  # inside corners at the brace ends: 0.5 x wall
    OUTSIDE_R: float = 12.0  # outside corner of the L = INSIDE_R + WALL (BP-R2)
    END_R: float = 2.0  # the arm ends
    # top edges only: on the bed a chamfer runs on round the tangent inside fillets as a 45 deg cone,
    # which the bed-edge check reads as a rounded bed edge; elephant's foot is the slicer's job (BP-B1)
    EDGE_CHAMFER: float = 0.5
    # screw holes: target printed size; HOLE_COMP_H is added when cutting (they lie on their side)
    HOLE_COMP_H: float = hole_comp(__file__, horizontal=True)
    SCREW_D: float = 4.5  # M4 clearance (wood screws #8 fit too)
    TEARDROP_ANGLE: float = 45.0  # roof sides from vertical (BP-H3)
    WALL_SCREWS_Y: tuple = (15.0, 82.0)  # along the wall arm: under the brace, and near the top (a
    # driver up to ~50 mm long reaches the top one inside the brace's triangle)
    SHELF_SCREW_X: float = 83.0  # one screw up into the shelf, past the brace, 12 mm from the end


VARIANTS = {"": {}}


def teardrop(dia: float, length: float, angle: float) -> Part:
    """A hole along Y, centered on the origin, with a pointed roof toward +Z (BP-H3)."""
    r = dia / 2
    a = radians(angle)
    s, c = sin(a), cos(a)
    roof = Polygon((-r * c, r * s), (0, r / s), (r * c, r * s), (0, 0), align=None)
    return Rot(90, 0, 0) * Cylinder(r, length) + Rot(90, 0, 0) * extrude(roof, length / 2, both=True)


def build(d: Dims) -> Part:
    t, h, ln = d.WALL, d.ARM_H, d.ARM_L
    top = h - t  # underside of the shelf arm
    wall_arm = Box(t, h, d.WIDTH, align=BED)
    shelf_arm = Pos(0, top, 0) * Box(ln, t, d.WIDTH, align=BED)
    # brace: a bar of thickness WALL from (t, BRACE_FROM) on the wall arm to (BRACE_TO, top)
    dx, dy = d.BRACE_TO - t, top - d.BRACE_FROM
    length = (dx * dx + dy * dy) ** 0.5
    ang = degrees(atan2(dy, dx))
    brace = Pos(t + dx / 2, d.BRACE_FROM + dy / 2, 0) * Rot(0, 0, ang) * Box(length + 2 * t, t, d.WIDTH,
                                                                              align=(Align.CENTER, Align.CENTER, Align.MIN))
    p = wall_arm + shelf_arm + brace
    # trim the brace's ends that stick out past the arms' outer faces
    p = p & Box(ln, h, d.WIDTH, align=BED)
    p = fillet_profile(p, d)
    p = chamfer(p.edges().group_by(Axis.Z)[-1], length=d.EDGE_CHAMFER)  # the top; see EDGE_CHAMFER
    k = d.SCREW_D + d.HOLE_COMP_H
    for y in d.WALL_SCREWS_Y:  # through the wall arm, along X
        p -= Pos(t / 2, y, d.WIDTH / 2) * Rot(0, 0, 90) * teardrop(k, t * 3, d.TEARDROP_ANGLE)
    p -= Pos(d.SHELF_SCREW_X, h - t / 2, d.WIDTH / 2) * teardrop(k, t * 3, d.TEARDROP_ANGLE)  # up into the shelf
    return p


def fillet_profile(p: Part, d: Dims) -> Part:
    """Round the Z-parallel edges of the profile: the main inside corner, the brace's inside
    corners, the outside corner and the arm ends. Vertical in print orientation, so no overhang."""
    t, h, ln = d.WALL, d.ARM_H, d.ARM_L

    def at(p, *xy, tol=0.5):  # the Z-parallel edges at these (x, y)
        return [e for e in p.edges().filter_by(Axis.Z) for x, y in xy
                if abs(e.center().X - x) < tol and abs(e.center().Y - y) < tol]

    p = fillet(at(p, (0, h)), d.OUTSIDE_R)
    p = fillet(at(p, (ln, h), (ln, h - t), (0, 0), (t, 0)), d.END_R)
    p = fillet(at(p, (t, h - t)), d.INSIDE_R)
    a = atan2(h - t - d.BRACE_FROM, d.BRACE_TO - t)  # where the brace's sides meet the arms
    up, out = t / (2 * cos(a)), t / (2 * sin(a))
    return fillet(at(p, (t, d.BRACE_FROM + up), (t, d.BRACE_FROM - up), (d.BRACE_TO + out, h - t),
                     (d.BRACE_TO - out, h - t)), d.BRACE_R)


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
