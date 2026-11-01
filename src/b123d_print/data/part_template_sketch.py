"""{title}

{description}

Sketch first: sketches(d) draws the 2D outline; render_sketch (CLI `b123d-print sketch {name}`)
shows it with its dimensions and checks. Once the user OKs the sketch, build(d) makes it solid.

Print orientation: TODO (the outline flat on the bed, extruded up in Z).
"""

from dataclasses import dataclass

from build123d import Circle, Part, Pos, Sketch, extrude

from b123d_print import Overhang, Template, View, Wall, clearance, hole_comp  # noqa: F401
from b123d_print.recipes import bed_chamfer, rounded_outline, slot  # noqa: F401


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. Say where each one came from."""

    WIDTH: float = 60.0  # X, TODO: measured / typed / estimate
    DEPTH: float = 30.0  # Y
    THICK: float = 4.0  # Z: the extrusion
    CORNER_R: float = 3.0  # outline corners (inside corners at least 0.5, BP-R1)
    HOLE_D: float = 3.4  # mounting holes, printed size (M3 clearance)
    HOLE_INSET: float = 6.0  # hole centres from the ends
    BED_CHAMFER: float = 0.5  # bed edges: chamfer, not fillet
    CLEARANCE: float = clearance(__file__)  # mating gap, per side
    HOLE_COMP: float = hole_comp(__file__)  # added to hole diameters when cutting (from config)
    STYLE: str = ""  # design review: functional, modern, least_cost, rugged, soft, structural, organic, decorative, toy ("" = workspace, else functional)


# Only overrides; "" is the standard part. Output files get the key as a suffix.
VARIANTS = {{"": {{}}}}


def outline(d: Dims) -> Sketch:
    """The 2D shape: corner points in order with a radius each (one number, or a list with one per
    point; 0 = sharp), then the holes and slots cut from it (slot(a, b, width))."""
    pts = [(0, 0), (d.WIDTH, 0), (d.WIDTH, d.DEPTH), (0, d.DEPTH)]
    s = rounded_outline(pts, d.CORNER_R)
    for x in (d.HOLE_INSET, d.WIDTH - d.HOLE_INSET):
        s -= Pos(x, d.DEPTH / 2) * Circle((d.HOLE_D + d.HOLE_COMP) / 2)
    return s


def sketches(d: Dims):
    """Named 2D shapes, drawn and checked by render_sketch before any 3D; lazy like pieces."""
    return {{"outline": lambda: outline(d)}}


def build(d: Dims) -> Part:
    """The printable part, in print orientation (bottom on Z=0): the confirmed sketch, extruded."""
    part = extrude(outline(d), d.THICK)
    return bed_chamfer(part, d.BED_CHAMFER)  # every bed edge, inside radii and holes too


def views(d: Dims):
    """Cross-sections saved with every export."""
    return [View("XY", d.THICK / 2, "mid height")]


def checks(d: Dims):
    """Wall checks around every cut deeper than the wall it starts in; overhang rules."""
    return []


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
