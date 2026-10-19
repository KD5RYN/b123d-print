"""Insert bracket: a mounting block with two M4 heat-set inserts on top and two counterbored M4
screw holes in its foot, using bd_warehouse's fastener data.

Shows small threads done the printable way (Threads, fasteners and gears in the docs): below
~M6 the thread is a brass heat-set insert, not a modeled one (BP-T1, T5).
- The insert's length and the wall it needs (2.1 mm for M4) come from bd_warehouse's
  `HeatSetNut("M4-0.7-8.1", "CNCKitchen")` table; a Wall check measures that wall. The hole is
  CNC Kitchen's 5.6 mm plus HOLE_COMP, 1 mm deeper than the insert (BP-T2, T3). bd_warehouse's
  `InsertHole` would cut 5.79 mm (its table's drill size), 0.19 mm looser than the maker asks.
- The screw holes take their sizes from `SocketHeadCapScrew` (clearance 4.5 mm "Normal", head
  7.22 mm) but are cut here with build123d's CounterBoreHole, so HOLE_COMP is added once, like
  every other hole: bd_warehouse's ClearanceHole and TapHole take no compensation.

Print orientation: the foot on the bed (Z=0), inserts and counterbores opening upward, so every
hole is vertical and round. No supports. Install the inserts at print temperature + 10-20 C
(BP-T3). Slicer: 3-4 walls around the inserts (BP-W3). An example: not printed yet.
"""

from dataclasses import dataclass
from functools import cached_property

from bd_warehouse.fastener import HeatSetNut, SocketHeadCapScrew
from build123d import Align, Axis, Box, BuildPart, CounterBoreHole, Cylinder, Locations, Part, Pos, chamfer, fillet

from b123d_print import View, Wall, hole_comp, load_settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: a generic mounting block, not measured)."""

    INSERT: str = "M4-0.7-8.1"  # CNC Kitchen M4 x 8.1 (bd_warehouse HeatSetNut size)
    INSERT_MAKER: str = "CNCKitchen"  # the table in bd_warehouse/data/heatset_nut_parameters.csv
    # the hole for it, target printed size: CNC Kitchen's datasheet (BP-T2). bd_warehouse's table says
    # 5.7 and its InsertHole cuts the drill column, 5.79: up to 0.19 loose, so not used here
    INSERT_HOLE_D: float = 5.6
    INSERT_EXTRA_DEPTH: float = 1.0  # blind hole past the insert's end (BP-T3)
    INSERT_PITCH: float = 16.0  # between the two inserts, along X
    SCREW: str = "M4-0.7"  # the screws through the foot
    SCREW_FIT: str = "Normal"  # bd_warehouse clearance fit: Close 4.3, Normal 4.5, Loose 4.8 for M4
    SCREW_PITCH: float = 52.0  # between the two foot screws, along X
    # target printed sizes; HOLE_COMP is added when cutting (all holes are vertical)
    HOLE_COMP: float = hole_comp(__file__)
    HEAD_FIT: float = load_settings(__file__).free_fit  # per side around the screw head (BP-F1)
    HEAD_SINK: float = 0.5  # the head sits this far below the foot's top
    FOOT_L: float = 68.0
    FOOT_W: float = 20.0
    FOOT_T: float = 8.0  # counterbore 4.5 deep leaves 3.5 under the head
    BLOCK_L: float = 30.0
    BLOCK_W: float = 14.0  # (14 - 5.6) / 2 = 4.2 mm of wall each side of an insert, the maker asks 2.1
    BLOCK_H: float = 16.0  # the 9.1 mm insert hole leaves 6.9 mm of block under it
    CORNER_R: float = 3.0  # vertical corners of foot and block
    ROOT_R: float = 2.0  # block-to-foot inside corner (BP-R1)
    BED_CHAMFER: float = 0.5  # BP-B1, B2
    EDGE_CHAMFER: float = 0.5  # top edges

    @cached_property
    def insert(self) -> HeatSetNut:
        return HeatSetNut(self.INSERT, self.INSERT_MAKER)

    @cached_property
    def screw(self) -> SocketHeadCapScrew:
        return SocketHeadCapScrew(self.SCREW, 16)

    @property
    def insert_depth(self) -> float:  # the blind hole: the insert's length plus the extra
        return self.insert.nut_data["m"] + self.INSERT_EXTRA_DEPTH

    @property
    def head_depth(self) -> float:
        return self.screw.head_height + self.HEAD_SINK


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    foot = Box(d.FOOT_L, d.FOOT_W, d.FOOT_T, align=BED)
    foot = fillet(foot.edges().filter_by(Axis.Z), d.CORNER_R)
    block = Box(d.BLOCK_L, d.BLOCK_W, d.BLOCK_H, align=BED)
    block = fillet(block.edges().filter_by(Axis.Z), d.CORNER_R)
    p = foot + block
    root = [e for e in p.edges() if abs(e.center().Z - d.FOOT_T) < 1e-3
            and abs(e.center().X) <= d.BLOCK_L / 2 + 1e-3 and abs(e.center().Y) <= d.BLOCK_W / 2 + 1e-3]
    p = fillet(root, d.ROOT_R)
    p = chamfer(p.edges().group_by(Axis.Z)[0], d.BED_CHAMFER)
    p = chamfer(p.edges().group_by(Axis.Z)[-1] + p.edges().group_by(Axis.Z)[-3], d.EDGE_CHAMFER)

    # heat-set inserts: the maker's hole size + HOLE_COMP, a straight blind hole 1 mm past the insert
    # (BP-T2, T3); bd_warehouse's HeatSetNut gives the length
    for x in (-d.INSERT_PITCH / 2, d.INSERT_PITCH / 2):
        p -= Pos(x, 0, d.BLOCK_H) * Cylinder((d.INSERT_HOLE_D + d.HOLE_COMP) / 2, d.insert_depth,
                                              align=(Align.CENTER, Align.CENTER, Align.MAX))

    # foot screws: bd_warehouse's sizes, our compensation
    s = d.screw
    with BuildPart() as screws:
        Box(d.FOOT_L, d.FOOT_W, d.FOOT_T, align=BED)
        with Locations((-d.SCREW_PITCH / 2, 0, d.FOOT_T), (d.SCREW_PITCH / 2, 0, d.FOOT_T)):
            CounterBoreHole(radius=(s.clearance_hole_diameters[d.SCREW_FIT] + d.HOLE_COMP) / 2,
                            counter_bore_radius=(s.head_diameter + 2 * d.HEAD_FIT + d.HOLE_COMP) / 2,
                            counter_bore_depth=d.head_depth)
    cut = Box(d.FOOT_L, d.FOOT_W, d.FOOT_T, align=BED) - screws.part
    return p - cut


def views(d: Dims):
    return [View("XZ", 0, "through the inserts and screw holes"),
            View("XY", d.BLOCK_H - d.insert.nut_data["m"] / 2, "across the insert pockets")]


def checks(d: Dims):
    t = d.insert.nut_data["material_thickness"]  # the maker's minimum wall around the insert
    return [Wall("", "XY", d.BLOCK_H - d.insert.nut_data["m"] / 2, near=(x, 0), radius=6, min=t,
                 label=f"wall around the insert (maker's minimum {t:g})")
            for x in (-d.INSERT_PITCH / 2, d.INSERT_PITCH / 2)] + [
        Wall("", "XY", d.FOOT_T - d.head_depth / 2, near=(d.SCREW_PITCH / 2, 0), radius=6, min=1.2,
             label="foot around the counterbore")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
