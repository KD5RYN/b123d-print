"""CAD-only two-keyhole fit coupon: print/try with the stated M3 socket heads before use.

Copy into parts/wall_mount_coupon/wall_mount_coupon.py, then run with uv.
No physical print or load validation is claimed. Coordinates in assembly(): insertion
face Z=5, head cavity Z=0..3.4. Print orientation flips the cavity upward.
"""
from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Pos, Rot

from b123d_print import Template, View, Wall, hole_comp, load_settings, run
from b123d_print.recipes import _screw, keyhole_mount


@dataclass(frozen=True)
class Dims:
    WIDTH: float = 50.0  # chosen coupon envelope, mm
    HEIGHT: float = 30.0  # chosen coupon envelope, mm
    PLATE_T: float = 5.0  # chosen; cavity plus 1.6 mm lip
    SPACING: float = 30.0  # chosen screw center spacing, not an ISO requirement
    TRAVEL: float = 10.0  # chosen screw center adjustment
    HEAD_DEPTH: float = 3.4  # ISO 4762 M3 head height + chosen 0.4 mm axial space
    SHAFT_D: float = 3.0  # ISO metric M3 nominal shaft; verify actual screw
    HEAD_D: float = _screw("M3")["head_d"]  # ISO 4762 socket head table; verify actual screw
    HEAD_H: float = _screw("M3")["head_h"]  # ISO 4762 head height; verify actual screw
    AXIAL_SPACE: float = 0.2  # chosen gap below retaining lip
    LIP_PROBE_RADIUS: float = 1.0  # chosen local measurement radius
    LIP_PROBE_X: float = 2.5  # chosen point in lip, relative to screw axis
    MIN_LIP: float = 1.6  # chosen coupon lip thickness, not a load rating
    CLEARANCE: float = load_settings(__file__).clearance  # per side, extra to table clearance
    HOLE_COMP: float = hole_comp(__file__)  # total diameter compensation, once


def plate(d):
    p = Box(d.WIDTH, d.HEIGHT, d.PLATE_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x in (-d.SPACING / 2, d.SPACING / 2):
        p -= Pos(x, -d.TRAVEL / 2, d.PLATE_T) * keyhole_mount(
            size="M3", head_d=d.HEAD_D, plate_t=d.PLATE_T, travel=d.TRAVEL, head_depth=d.HEAD_DEPTH,
            clearance=d.CLEARANCE, hole_comp=d.HOLE_COMP, min_lip=d.MIN_LIP)
    return p


def build(d):
    # Cavity upward avoids an underside roof. Print insertion face on the bed.
    return Pos(0, 0, d.PLATE_T) * Rot(180, 0, 0) * plate(d)


def assembly(d):
    result = [(plate(d), None, "plate")]
    for index, x in enumerate((-d.SPACING / 2, d.SPACING / 2)):
        # Socket-head stand-in at retained endpoint, 0.2 mm axial clearance below lip.
        shoulder = d.HEAD_DEPTH - d.AXIAL_SPACE
        head = Pos(x, d.TRAVEL / 2, shoulder - d.HEAD_H) * Cylinder(
            d.HEAD_D / 2, d.HEAD_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        shaft = Pos(x, d.TRAVEL / 2, shoulder) * Cylinder(
            d.SHAFT_D / 2, d.PLATE_T, align=(Align.CENTER, Align.CENTER, Align.MIN))  # M3 nominal shaft
        result.append((head + shaft, None, f"screw {index + 1} (stand-in)"))
    return result


def checks(d):
    # XZ slice through the retained endpoint. Inspect the measured region in the report.
    return [Wall("plate", "XZ", d.TRAVEL / 2,
                 near=(-d.SPACING / 2 + d.LIP_PROBE_X, d.HEAD_DEPTH + d.MIN_LIP / 2),
                 radius=d.LIP_PROBE_RADIUS, min=d.MIN_LIP, frame="assembly", label="retaining lip")]


def views(d):
    return [View("XY", d.MIN_LIP / 2), View("XZ", -d.TRAVEL / 2)]


def templates(d):
    # Full-depth crop preserves the recess and retaining lip; a thin slice cannot test them.
    return [Template.crop((0, 0, d.PLATE_T / 2), (d.WIDTH, d.HEIGHT, d.PLATE_T), label=False)]


if __name__ == "__main__":
    run(__file__)
