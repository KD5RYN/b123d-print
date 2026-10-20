"""Known bad: the lid placed 1 mm into the box in assembly(d) (wrong Z for the rim)."""

import box_lid_screws as ref
from box_lid_screws import Dims, build  # noqa: F401

VARIANTS = {"": {}}


def assembly(d: Dims) -> list:
    return ref.assembly(d, lid_z=d.H - 1.0)
