"""Known bad: the screw stand-ins at the nominal 3 mm, overlapping the 2.7 mm pilot holes."""

from dataclasses import replace

from build123d import Pos

from box_lid_screws import Dims, box, build, lid, screw, screw_xy  # noqa: F401

VARIANTS = {"": {}}


def assembly(d: Dims) -> list:
    thick = replace(d, PILOT_D=3.0)
    out = [(box(d), "tan", "box"), (Pos(0, 0, d.H) * lid(d), "lightblue", "lid")]
    return out + [(Pos(x, y, d.H + d.LID_T) * screw(thick), "gray", f"screw {i + 1}") for i, (x, y) in enumerate(screw_xy(d))]
