"""Known bad: the lid left 30 mm above the box in assembly(d): nothing touches, nothing is checked."""

import box_lid_screws as ref
from box_lid_screws import Dims, build  # noqa: F401

VARIANTS = {"": {}}


def assembly(d: Dims) -> list:
    return ref.assembly(d, lid_z=d.H + 30.0)
