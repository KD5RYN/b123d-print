"""Twisted vase: a six-pointed star lofted up with a twist and a taper, printed in vase mode.

Shows the `decorative` design style (DESIGN_GUIDE DS-D*): one strong feature that reads from a
step back, the star's points turned into spiral ridges (DS-D5). The model is a solid on purpose:
in vase mode (spiral vase / spiralize) the slicer prints one continuous wall from its outside,
with no top, no infill and no supports, so every layer is one closed contour and the wall leans
no more than the overhang limit, inward or outward (DS-D1, DS-D3). `PRINT` says so, and the print
sheet gives the slicer settings. Made with the `twisted_loft` recipe. Holds dry flowers: a vase
for water wants a liner (DS-D2).

Print orientation: as used, the base on the bed (Z=0). An example with chosen sizes, not
measured or printed yet. Author: b123d-print contributors. License: CC0 1.0 (no attribution
needed).
"""

from dataclasses import dataclass, field

from build123d import Part

from b123d_print.recipes import star_section, twisted_loft


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example: chosen, not measured)."""

    STYLE: str = "decorative"  # a vase (DS-D*)
    POINTS: int = 6  # star points: 5-8 read well from across a room (DS-D5)
    R_OUTER: float = 38.0  # star point radius at the base
    R_INNER: float = 30.0  # star valley radius at the base: points 8 mm proud, 20+ line widths
    ROUND_R: float = 3.0  # points and valleys rounded: no knife edge for the nozzle (BP-R3)
    HEIGHT: float = 150.0
    TWIST: float = 90.0  # degrees, base to top: a quarter turn keeps the flanks well under 45 deg
    TOP_SCALE: float = 0.8  # the top is 80 % of the base: a gentle taper, the wall leans inward
    STEPS: int = 8  # loft sections; enough for a quarter turn
    # vase mode: one wall, no top, no infill, no supports (DS-D1); kept out of the hash so
    # functools.cache on piece functions still works
    PRINT: dict = field(default_factory=lambda: {
        "vase": True,
        "why": "a vase: one continuous wall from the solid, open top (spiral vase / spiralize)",
    }, hash=False, compare=False)


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    return twisted_loft(star_section(d.POINTS, d.R_OUTER, d.R_INNER, d.ROUND_R), d.HEIGHT, twist=d.TWIST,
                        scale=d.TOP_SCALE, steps=d.STEPS)


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
