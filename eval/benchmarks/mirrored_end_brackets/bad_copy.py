"""Known bad: the "right" bracket is a copy of the left one."""

from mirrored_end_brackets import Dims, left

VARIANTS = {"": {}}


def build(d: Dims) -> dict:
    return {"left": lambda: left(d), "right": lambda: left(d)}
