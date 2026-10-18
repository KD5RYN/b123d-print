"""{title}

{description}

Print orientation: TODO (which face is on the bed).
"""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Part, chamfer

from b123d_print import Overhang, View, Wall, clearance, hole_comp  # noqa: F401

BED = (Align.CENTER, Align.CENTER, Align.MIN)  # sit on Z=0


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. Say where each one came from."""

    WIDTH: float = 40.0  # X, TODO: measured / typed / estimate
    DEPTH: float = 20.0  # Y
    HEIGHT: float = 10.0  # Z
    BED_CHAMFER: float = 0.5  # bed edges: chamfer, not fillet
    CLEARANCE: float = clearance(__file__)  # mating gap, per side
    HOLE_COMP: float = hole_comp(__file__)  # added to hole diameters when cutting (from config)

    # --- Derived ---
    # @property
    # def INNER_W(self):
    #     return self.WIDTH - 2 * self.WALL


# Only overrides; "" is the standard part. Output files get the key as a suffix.
VARIANTS = {{"": {{}}}}


def build(d: Dims) -> Part:
    """The printable part, in print orientation (bottom on Z=0). A single Part is named "part" in
    checks() (the script's own name works too); return {{"base": ..., "lid": ...}} to name several."""
    part = Box(d.WIDTH, d.DEPTH, d.HEIGHT, align=BED)
    part = chamfer(part.edges().group_by(Axis.Z)[0], length=d.BED_CHAMFER)
    return part


# def assembly(d: Dims):
#     """Assembled position + stand-ins for what it mates with -> overlap check."""
#     return [(build(d), "#3a6ea5", "{name}"), (stand_in, "#bbbbbb", "board (stand-in)")]


def views(d: Dims):
    """Cross-sections saved with every export."""
    return [View("XY", d.HEIGHT / 2, "mid height")]


def checks(d: Dims):
    """Wall checks around every cut deeper than the wall it starts in; overhang rules."""
    return []


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
