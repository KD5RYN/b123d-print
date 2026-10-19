"""Benchmark reference: an open box and a flat lid held by four M3 self-tapping screws.

Print orientation: the box opening up, the lid flat; both on Z=0. assembly(d): the box as
printed, the lid on its rim, and four screws (stand-ins) through the lid's clearance holes into
the pilot holes of the corner bosses. The screw stand-ins are the thread's core diameter, so they
touch the pilot hole instead of overlapping it.
"""

from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Part, Pos

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    L: float = 60.0  # task: outside, X
    W: float = 40.0  # task: outside, Y
    H: float = 25.0  # task: box height
    WALL: float = 2.0  # task
    FLOOR: float = 2.0  # task
    BOSS_D: float = 7.0  # task: corner bosses
    SCREW_IN: float = 5.5  # task: screw axes from the outside edges
    PILOT_D: float = 2.7  # task: M3 self-tapping pilot (AGENTS: M3 ~2.6-2.9)
    PILOT_DEPTH: float = 12.0  # task
    LID_T: float = 3.0  # task
    CLEAR_D: float = 3.4  # task: M3 clearance
    SCREW_L: float = 14.0  # stand-in: M3 x 14
    HEAD_D: float = 5.5  # stand-in
    HEAD_H: float = 3.0  # stand-in


VARIANTS = {"": {}}


def screw_xy(d: Dims) -> list[tuple[float, float]]:
    x, y = d.L / 2 - d.SCREW_IN, d.W / 2 - d.SCREW_IN
    return [(sx * x, sy * y) for sx in (-1, 1) for sy in (-1, 1)]


def box(d: Dims) -> Part:
    p = Box(d.L, d.W, d.H, align=BED) - Pos(0, 0, d.FLOOR) * Box(d.L - 2 * d.WALL, d.W - 2 * d.WALL, d.H, align=BED)
    for x, y in screw_xy(d):
        p += Pos(x, y, 0) * Cylinder(d.BOSS_D / 2, d.H, align=BED)
        p -= Pos(x, y, d.H - d.PILOT_DEPTH) * Cylinder(d.PILOT_D / 2, d.PILOT_DEPTH + 1, align=BED)
    return p


def lid(d: Dims) -> Part:
    p = Box(d.L, d.W, d.LID_T, align=BED)
    for x, y in screw_xy(d):
        p -= Pos(x, y, 0) * Cylinder(d.CLEAR_D / 2, 3 * d.LID_T)
    return p


def screw(d: Dims) -> Part:
    return Cylinder(d.PILOT_D / 2, d.SCREW_L, align=(Align.CENTER, Align.CENTER, Align.MAX)) + Cylinder(d.HEAD_D / 2, d.HEAD_H, align=BED)


def build(d: Dims) -> dict:
    return {"box": lambda: box(d), "lid": lambda: lid(d)}


def assembly(d: Dims, lid_z: float | None = None, lid_dx: float = 0.0) -> list:
    z = d.H if lid_z is None else lid_z
    out = [(box(d), "tan", "box"), (Pos(lid_dx, 0, z) * lid(d), "lightblue", "lid")]
    out += [(Pos(x + lid_dx, y, z + d.LID_T) * screw(d), "gray", f"screw {i + 1}") for i, (x, y) in enumerate(screw_xy(d))]
    return out
