"""Banana half

Cut banana half (no stem), decorative. Stands on its flat cut face and curves over to a
tapered tip that rounds smoothly into a blunt end, like a banana cut in two. 5 in (127 mm)
long measured along the curve. Soft ridges run the whole length, sharpening down the taper
and fading out just before the tip.

Print orientation: cut face on the bed, printed upright. The curve leans at most BEND_DEG
from vertical, so no supports.
"""

import math
from dataclasses import dataclass

from build123d import Face, Part, Plane, Spline, Vector, Wire, loft

from b123d_print import Overhang, Template, View, Wall, clearance, hole_comp  # noqa: F401


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. Say where each one came from."""

    LENGTH: float = 127.0  # along the centre curve, cut face to tip: typed (5 in)
    BEND_DEG: float = 42.0  # how far the curve bends from vertical: user, "bend a little more"; < 45
    W_CUT: float = 27.0  # width at the cut face: 38 mm scaled to the 5 in length
    TAPER_START: float = 0.62  # fraction of LENGTH where the taper begins: user, "quicker ramp down"
    TAPER_POWER: float = 1.3  # taper fullness: lower = more pointed; user, "more pointy"
    TIP_ROUND: float = 0.5  # how the taper rounds into the end: 0.5 = smooth dome, user "organic"
    TIP_FLAT: float = 0.08  # tiny untapered stub left at the very end, mm along the curve (loft needs a face)
    RIDGES: int = 5  # banana ridges around the section: user, "soft ridges"
    RIDGE_DEPTH: float = 0.05  # ridge bulge at the cut, fraction of the radius: soft
    RIDGE_TIP: float = 0.12  # ridge bulge near the tip: user, ridges "down to the point"
    RIDGE_FADE: float = 4.0  # ridges fade out over this last length, mm: user, "blend in"
    STEP_BODY: float = 4.0  # loft section spacing along the body (smoothness)
    TIP_ZONE: float = 14.0  # length near the tip with dense sections
    TIP_STATIONS: int = 24  # sections in TIP_ZONE, closer together right at the end
    CLEARANCE: float = clearance(__file__)  # mating gap, per side (unused: no mating parts)
    HOLE_COMP: float = hole_comp(__file__)  # unused: no holes
    STYLE: str = "soft"  # decorative, rounded

    @property
    def BEND_R(self):
        return self.LENGTH / math.radians(self.BEND_DEG)

    @property
    def S_TAPER(self):
        return self.TAPER_START * self.LENGTH

    @property
    def S_END(self):
        return self.LENGTH - self.TIP_FLAT


SHOW = ["+Y", "-Y", "+X", "-X"]
UP = "+Z"
EDGES = "fillet"

VARIANTS = {"": {}}


def _centre(d: Dims, s: float):
    """Point, tangent and section x axis on the centre arc at arc length s.
    Starts at the origin going +Z and bends towards +X."""
    phi = s / d.BEND_R
    p = Vector(d.BEND_R * (1 - math.cos(phi)), 0, d.BEND_R * math.sin(phi))
    t = Vector(math.sin(phi), 0, math.cos(phi))
    x = Vector(math.cos(phi), 0, -math.sin(phi))
    return p, t, x


def _radius(d: Dims, s: float) -> float:
    """Mean section radius: full width, then one smooth taper that rounds into a blunt dome.
    r = r_cut * (1 - u^p)^q: q = 0.5 gives a round end (tip radius ~ r_cut^2 p / 2 L_taper)."""
    u = min(1.0, max(0.0, (s - d.S_TAPER) / (d.LENGTH - d.S_TAPER)))
    return d.W_CUT / 2 * (1 - u**d.TAPER_POWER) ** d.TIP_ROUND


def _ridge(d: Dims, s: float) -> float:
    """Ridge bulge fraction: soft along the body, sharper down the taper, fading at the tip."""
    u = min(1.0, max(0.0, (s - d.S_TAPER) / (d.LENGTH - d.S_TAPER)))
    k = d.RIDGE_DEPTH + (d.RIDGE_TIP - d.RIDGE_DEPTH) * u
    fade = min(1.0, (d.LENGTH - s) / d.RIDGE_FADE)
    return k * fade * fade * (3 - 2 * fade)  # smoothstep


def _stations(d: Dims):
    """Arc lengths of the loft sections: even along the body, ever closer towards the end."""
    s_dense = d.LENGTH - d.TIP_ZONE
    n_body = max(2, round(s_dense / d.STEP_BODY))
    body = [s_dense * i / n_body for i in range(n_body)]
    span = d.S_END - s_dense
    n = d.TIP_STATIONS
    tip = [s_dense + span * (1 - (1 - i / n) ** 2) for i in range(n + 1)]
    return body + tip


def _section(d: Dims, s: float) -> Face:
    """Rounded-pentagon section (banana ridges), perpendicular to the curve at s."""
    p, t, x = _centre(d, s)
    pl = Plane(origin=p, x_dir=x, z_dir=t)
    r, k = _radius(d, s), _ridge(d, s)
    n = 40
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * (1 + k * math.cos(d.RIDGES * a))
        pts.append(pl.from_local_coords((rr * math.cos(a), rr * math.sin(a), 0)))
    return Face(Wire([Spline(*pts, periodic=True)]))


def build(d: Dims) -> Part:
    """The banana, cut face on Z=0."""
    return loft([_section(d, s) for s in _stations(d)])


def views(d: Dims):
    """Cross-sections saved with every export."""
    return [
        View("XY", 0.3 * d.LENGTH, "body section"),
        View("XZ", 0.0, "side profile through the curve"),
    ]


def checks(d: Dims):
    """No cuts; the overhang rule is the one that matters here."""
    return []


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
