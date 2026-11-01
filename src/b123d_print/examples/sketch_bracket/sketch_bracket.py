"""Sketch bracket: a flat L mounting plate drawn sketch first.

The part is a 2D shape made solid, so its outline comes first: `sketches(d)` returns it (rounded
corners with one radius per corner, two screw holes and an adjustment slot), `render_sketch`
(CLI `b123d-print sketch sketch_bracket`) draws it with its dimensions and checks it, and once
the user OKs the sketch, `build(d)` extrudes that same outline and adds the 3D-only features:
countersinks and the bed chamfer (recipes.bed_chamfer: it chamfers the inside radius too).

Print orientation: flat on the bed, countersinks opening upward. The holes are vertical, so they
print round; the L's arms bend in XY, along the layers (BP-S4). No supports. An example with
estimated sizes: not printed yet.
"""

from dataclasses import dataclass

from build123d import Circle, Part, Pos, Sketch, extrude

from b123d_print import View, Wall, hole_comp
from b123d_print.recipes import bed_chamfer, rounded_outline, screw_hole, slot


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: estimates, not measured)."""

    ARM_X: float = 70.0  # the long arm, along X
    ARM_Y: float = 50.0  # the short arm, along Y
    ARM_W: float = 14.0  # both arms' width
    THICK: float = 4.0  # Z: the extrusion
    CORNER_R: float = 3.0  # outside corners
    INSIDE_R: float = 5.0  # the inside corner of the L: the most loaded spot (BP-R1)
    SCREW: str = "M3"  # countersunk screws (recipes.screw_hole's table)
    HOLE_D: float = 3.4  # M3 clearance (ISO 273 normal), printed size
    HOLE_INSET: float = 7.0  # hole centres from the arm ends
    SLOT_FROM: float = 30.0  # the adjustment slot's centres along the long arm, from X=0
    SLOT_TO: float = 50.0
    HOLE_COMP: float = hole_comp(__file__)  # added to hole and slot widths when cutting (from config)
    BED_CHAMFER: float = 0.5  # BP-B1, B2
    STYLE: str = "structural"


VARIANTS = {"": {}, "long": dict(ARM_X=100.0, SLOT_TO=80.0)}


def outline(d: Dims) -> Sketch:
    """The L, its corners in order from the origin, one radius each; then the holes and the slot."""
    w = d.ARM_W
    pts = [(0, 0), (d.ARM_X, 0), (d.ARM_X, w), (w, w), (w, d.ARM_Y), (0, d.ARM_Y)]
    radii = [d.CORNER_R, d.CORNER_R, d.CORNER_R, d.INSIDE_R, d.CORNER_R, d.CORNER_R]
    s = rounded_outline(pts, radii)
    hole = Circle((d.HOLE_D + d.HOLE_COMP) / 2)
    s -= Pos(d.ARM_X - d.HOLE_INSET, w / 2) * hole
    s -= Pos(w / 2, d.ARM_Y - d.HOLE_INSET) * hole
    s -= slot((d.SLOT_FROM, w / 2), (d.SLOT_TO, w / 2), d.HOLE_D + d.HOLE_COMP)
    return s


def sketches(d: Dims):
    return {"outline": lambda: outline(d)}


def build(d: Dims) -> Part:
    p = extrude(outline(d), d.THICK)
    p = bed_chamfer(p, d.BED_CHAMFER)  # an edge chamfer on the inside radius leaves a cone that flares
    for x, y in ((d.ARM_X - d.HOLE_INSET, d.ARM_W / 2), (d.ARM_W / 2, d.ARM_Y - d.HOLE_INSET)):
        p -= Pos(x, y, d.THICK) * screw_hole(d.SCREW, d.THICK, head="countersink", hole_comp=d.HOLE_COMP)
    return p


def views(d: Dims):
    return [View("XZ", d.ARM_W / 2, "through the long arm's hole and slot")]


def checks(d: Dims):
    # the countersink cone reaches nearly through the plate: the material left around it
    return [Wall("", "XY", d.THICK - 0.3, near=(d.ARM_X - d.HOLE_INSET, d.ARM_W / 2), radius=6, min=1.2,
                 label="plate around the countersink")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
