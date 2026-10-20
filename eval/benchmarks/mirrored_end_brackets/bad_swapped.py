"""Known bad: a correct mirror pair, but the names swapped (the piece called left is the right one)."""

from mirrored_end_brackets import Dims, left, right

VARIANTS = {"": {}}


def build(d: Dims) -> dict:
    return {"left": lambda: right(d), "right": lambda: left(d)}
