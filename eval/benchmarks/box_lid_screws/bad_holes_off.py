"""Known bad: the lid's holes 1.5 mm from where the bosses are (a chained dimension added up wrong)."""

from build123d import Box, Cylinder, Part, Pos

from box_lid_screws import BED, Dims, box, screw, screw_xy

VARIANTS = {"": {}}


def lid(d: Dims) -> Part:
    p = Box(d.L, d.W, d.LID_T, align=BED)
    for x, y in screw_xy(d):
        p -= Pos(x + (1.5 if x > 0 else 0), y, 0) * Cylinder(d.CLEAR_D / 2, 3 * d.LID_T)
    return p


def build(d: Dims) -> dict:
    return {"box": lambda: box(d), "lid": lambda: lid(d)}


def assembly(d: Dims) -> list:
    out = [(box(d), "tan", "box"), (Pos(0, 0, d.H) * lid(d), "lightblue", "lid")]
    return out + [(Pos(x, y, d.H + d.LID_T) * screw(d), "gray", f"screw {i + 1}") for i, (x, y) in enumerate(screw_xy(d))]
