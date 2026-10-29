"""Banana: a whole banana lying on its side, stem and all (CC0).

Shows the `organic` design style (DESIGN_GUIDE DS-O*) and the organic recipes: nothing here is a
box or a cylinder. The body is `spine_loft`: soft five-ridged sections placed across a curved
spine, full in the middle, tapering to a blunt blossom end and to a neck at the stem; the ridges
sharpen towards both ends, as on a real banana [DS-O2]; the blossom end closes in a blunt round
nub, not a flat cap. The stem is a `tapered_sweep` that bends on with the curve and curls up, and
`organic_blend` joins it to the neck with a lofted collar instead of a fillet [DS-O1, DS-O3].
`flat_base` cuts a flat strip under the belly so it stands and sticks to the bed [DS-O5]. A few defining features (the curve, the ridges, the stem, the nub) and a little
asymmetry (the ends lift by different amounts, the section is wider than tall) rather than detail
[DS-O4].

Print orientation: lying on its side, the curve in XY: the long curve runs along the layers
[DS-O5]. The ends and the stem lift off the bed, so it needs supports under them: tree (organic)
supports leave the fewest scars on curved faces [DS-H2]. Variable layer height smooths the gently
domed top. Size from a medium banana (estimates, not measured): an example, not printed yet.
"""

import math
from dataclasses import dataclass

from build123d import Face, GeomType, Part, Plane, Pos, Spline, Vector, Wire, fillet

from b123d_print import View
from b123d_print.recipes import flat_base, organic_blend, spine_loft, tapered_sweep


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (estimates for a medium banana: an example, not measured)."""

    STYLE: str = "organic"  # natural object: shapes from sections and curves (DS-O*)
    # the middle of the banana, neck to blossom end, (x, y, z): 150 mm long, bowing out 24 mm to +Y
    # past the middle; the neck end lifts 9 mm off the bed, the blossom end 5: asymmetric on purpose
    SPINE: tuple = ((0.0, 0.0, 9.0), (45.0, 19.0, 1.5), (90.0, 24.0, 0.0), (150.0, 5.0, 5.0))
    WIDTH: float = 36.0  # the fullest section, across (Y in the section)
    ASPECT: float = 0.92  # height / width of a section: a little flatter than round
    RIDGES: int = 5  # the banana's ridges around the section
    RIDGE: float = 0.04  # ridge bulge in the middle, a fraction of the radius: soft
    RIDGE_END: float = 0.10  # ridge bulge towards the ends: sharper, still rounded
    # (fraction of the spine's length, diameter as a fraction of WIDTH): full in the middle, a long
    # taper to the neck, a quick one to the blossom end, which closes in a blunt round nub (0: a point)
    PROFILE: tuple = ((0.0, 0.30), (0.08, 0.45), (0.25, 0.86), (0.45, 1.0), (0.65, 0.97), (0.82, 0.78),
                      (0.93, 0.45), (0.975, 0.26), (0.993, 0.13), (1.0, 0.0))
    STEM_REACH: float = 23.0  # the stem's cut end, this far on from its start along the neck's direction
    STEM_SIDE: float = 5.0  # ... this far to the side, bending on with the banana's curve
    STEM_RISE: float = 8.0  # ... and this far up: the stem curls up
    STEM_D: float = 9.0  # at the neck
    STEM_END_D: float = 7.5  # at its cut end
    STEM_END_ROUND: float = 1.2  # fillet on the rim of the stem's cut end: no knife edge, no sharp rim
    STEM_GAP: float = 3.0  # between the body's neck and the stem's start: the collar spans it
    NECK_CUT: float = 0.02  # the collar starts this far along the body (fraction of the spine)...
    STEM_CUT: float = 2.0  # ... and this far into the stem, mm along it
    COLLAR_BULGE: float = -0.05  # the collar pinches a little, like a real banana's neck
    BASE_DEPTH: float = 4.0  # flat strip cut under the belly (flat_base), about 1/8 of the height


VARIANTS = {"": {}}

PRINT = {"supports": "tree", "why": "the stem and both ends lift off the bed: tree supports scar curved faces least"}
PRINT_NOTES = ("Variable layer height (0.08-0.2 mm) smooths the gently domed top and the taper to the tip.",)
SHOW = ["+Z", "+Y", "-Y", "+X", "-X"]  # every side but the bed shows
UP = "+Z"


def spine(d: Dims):
    """The middle of the banana: from the neck (start) to the blossom end."""
    return Spline(*d.SPINE)


def section(d: Dims, dia: float, ridge: float) -> Face:
    """A soft five-ridged section on XY around the origin; +X is up (the frames' x axis)."""
    pts = []
    for i in range(40):
        a = 2 * math.pi * i / 40
        r = dia / 2 * (1 + ridge * math.cos(d.RIDGES * a))  # a ridge on top, a flat face underneath
        pts.append((r * math.cos(a) * d.ASPECT, r * math.sin(a), 0))
    return Face(Wire([Spline(*pts, periodic=True)]))


def ridge_at(d: Dims, u: float) -> float:
    """Ridges soft in the middle, sharper towards both ends."""
    return d.RIDGE + (d.RIDGE_END - d.RIDGE) * abs(2 * u - 1) ** 2


def body(d: Dims) -> Part:
    sp = spine(d)
    return spine_loft(sp, [(u, section(d, k * d.WIDTH, ridge_at(d, u)) if k else 0) for u, k in d.PROFILE])


def stem_path(d: Dims):
    """From just beyond the neck, carrying on the spine's direction, then bending to the side and
    up; halfway along it has a third of the bend, so the bend grows towards the cut end."""
    sp = spine(d)
    t = -(sp % 0)
    start = sp @ 0 + t * d.STEM_GAP
    side, up = Vector(0, 0, 1).cross(t).normalized(), Vector(0, 0, 1)
    mid = start + t * (d.STEM_REACH / 2) + (side * d.STEM_SIDE + up * d.STEM_RISE) / 3
    end = start + t * d.STEM_REACH + side * d.STEM_SIDE + up * d.STEM_RISE
    return Spline(start, mid, end, tangents=(t, end - mid))


def stem(d: Dims) -> Part:
    s = tapered_sweep(stem_path(d), [(0, section(d, d.STEM_D, 0.06)), (1, section(d, d.STEM_END_D, 0.08))])
    end = stem_path(d) @ 1
    cap = min((f for f in s.faces() if f.geom_type == GeomType.PLANE), key=lambda f: (f.center() - end).length)
    return fillet(cap.edges(), d.STEM_END_ROUND)  # a small fillet on a plain rim: one of the few that hold


def build(d: Dims) -> Part:
    """The banana, lying on its side, its flat strip on Z=0."""
    sp, path = spine(d), stem_path(d)
    neck = Plane(origin=sp @ d.NECK_CUT, z_dir=-(sp % d.NECK_CUT))  # +Z out of the body, towards the stem
    u = d.STEM_CUT / path.length
    stem_start = Plane(origin=path @ u, z_dir=-(path % u))  # +Z out of the stem, back at the body
    banana = organic_blend(body(d), stem(d), neck, stem_start, bulge=d.COLLAR_BULGE)
    banana = flat_base(banana, d.BASE_DEPTH)
    c = banana.bounding_box().center()
    return Pos(-c.X, -c.Y, 0) * banana


def views(d: Dims):
    """Cross-sections saved with every export."""
    return [View("YZ", 0.0, "across the belly"), View("XY", 1.0, "bed contact")]


def checks(d: Dims):
    return []


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
