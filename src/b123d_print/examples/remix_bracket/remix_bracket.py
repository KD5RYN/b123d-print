"""Remix of an L bracket: slots instead of the two mounting holes, and two gussets.

The remix example: the original is a mesh (ref/l_bracket.stl), loaded with import_model and
changed, not redrawn. Its faceted holes stay as they are where nothing changes; the new slots are
cut as real shapes.

Source: ref/l_bracket.stl, made for this example by tools/make_remix_ref.py in the b123d-print
repository (a stand-in for a downloaded model). Author: b123d-print contributors. License: CC0 1.0
(no attribution needed). For a real download, record its URL, author and license here, and check
the license first: -ND allows no remixes, -NC no commercial use, BY needs the author credited.

Changes (all named in Dims): the 4.5 mm holes become 4.5 x 10 mm slots along Y so the bracket
can be adjusted; two 3 mm gussets stiffen the corner. The 6 mm horizontal hole in the upright is
the original's (its round top is an inherited finding: the checks say so).
Print orientation: as the original, base on the bed. Standalone part, no mating clearance.
"""

from dataclasses import dataclass

from build123d import Mode, Part, Plane, Polygon, Pos, SlotCenterToCenter, extrude

from b123d_print import Wall, hole_comp, import_model


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. The original's are read from describe_model (and match its generator)."""

    REF: str = "ref/l_bracket.stl"  # the original
    BASE_T: float = 4.0  # original: base thickness (describe_model: flat faces at Z 0 and 4)
    UPRIGHT_Y: float = 11.0  # original: front face of the upright
    HOLE_X: float = 10.0  # original: mounting holes at X +-10 (describe_model holes)
    HOLE_Y: float = -4.0  # original: ... and Y -4
    SLOT_W: float = 4.5  # remix: the original hole diameter, for the same M4 screw
    SLOT_L: float = 10.0  # remix: center to center along Y, so +-5 mm of adjustment
    GUSSET_X: float = 20.0  # remix: gussets at X +-20, clear of the slots
    GUSSET_T: float = 3.0  # remix: as thick as the walls they stiffen (BP-R4 says >= 1.5)
    GUSSET_H: float = 14.0  # remix: height up the upright, and depth along the base (45 deg)
    HOLE_COMP: float = hole_comp(__file__)  # printed holes come out small; from the user's config


VARIANTS = {"": {}}


def build(d: Dims) -> Part:
    part = import_model(d.REF)
    w = d.SLOT_W + d.HOLE_COMP
    for x in (-d.HOLE_X, d.HOLE_X):
        slot = SlotCenterToCenter(d.SLOT_L, w, rotation=90, mode=Mode.PRIVATE)
        part -= Pos(x, d.HOLE_Y, -1) * extrude(slot, d.BASE_T + 2)
    for x in (-d.GUSSET_X, d.GUSSET_X):
        # a right triangle in the YZ plane, against the upright's front face and the base's top
        tri = Polygon((0, 0), (-d.GUSSET_H, 0), (0, d.GUSSET_H), align=None, mode=Mode.PRIVATE)
        g = extrude(Plane.YZ.offset(x - d.GUSSET_T / 2) * tri, d.GUSSET_T)
        part += Pos(0, d.UPRIGHT_Y + 0.01, d.BASE_T - 0.01) * g  # overlap a hair so they fuse
    return part


def checks(d: Dims):
    # what is left of the base beside each slot: the slot cuts deeper than nothing, but it comes
    # within a few mm of the base's front edge
    return [Wall("", "XY", d.BASE_T / 2, near=(d.HOLE_X, d.HOLE_Y - d.SLOT_L / 2 - 2), radius=4, min=1.2,
                 label="base in front of the slot")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
