"""Known bad: the "right" bracket is the left one turned 180 deg about Z (hole and cut corner at
the other end, but the lip now at the front): a rotated copy, not a mirror image."""

from build123d import Rot

from mirrored_end_brackets import Dims, left

VARIANTS = {"": {}}


def build(d: Dims) -> dict:
    return {"left": lambda: left(d), "right": lambda: Rot(0, 0, 180) * left(d)}
