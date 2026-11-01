"""Shapes from profiles (#166): hollow, transition_loft, swept_section, revolved_profile, and the
two examples that use them."""

from pathlib import Path

import pytest
from build123d import Axis, Box, Circle, Plane, Pos, fillet, section

from b123d_print import checks as ck
from b123d_print import recipes as R
from b123d_print.checks import wall_thickness
from b123d_print.config import Settings
from b123d_print.project import dims, load, printables, run_checks

EXAMPLES = Path(R.__file__).parent / "examples"


def _rounded_box():
    return fillet(Box(60, 40, 30, align=R.BED).edges().filter_by(Axis.Z), 8)


def test_hollow_keeps_the_wall_even_round_the_corners():
    shell = R.hollow(_rounded_box(), 2.0)
    assert shell.is_valid and len(shell.solids()) == 1
    r = wall_thickness(shell, "XY", 15, step=0.1, limit=2.5)
    assert r is not None and r["min"] == pytest.approx(2.0, abs=0.1), r
    # open at the top: material at the rim, none in the middle
    rim = section(shell, Plane.XY.offset(29.9))
    assert rim.area == pytest.approx(shell.volume / 30, rel=0.5) and rim.area < 60 * 40 / 4


def test_hollow_open_sides_and_errors():
    body = _rounded_box()
    both = R.hollow(body, 2.0, open=["top", "bottom"])
    assert both.volume < R.hollow(body, 2.0, open="top").volume  # no floor
    closed = R.hollow(body, 2.0, open=None)
    assert closed.volume > R.hollow(body, 2.0).volume
    with pytest.raises(ValueError, match="a side"):
        R.hollow(body, 2.0, open="sideways")
    with pytest.raises(ValueError, match="> 0"):
        R.hollow(body, 0)
    with pytest.raises(ValueError, match="hollow"):
        R.hollow(Box(10, 10, 10), 6.0)  # thicker than half the body


def test_section_shape_kinds():
    assert R.section_shape(10).area == pytest.approx(78.54, abs=0.01)
    assert R.section_shape((10, 4)).area == pytest.approx(40)
    assert R.section_shape((10, 4, 1)).area < 40
    c = Circle(3)
    assert R.section_shape(c) is c
    with pytest.raises(ValueError, match="diameter"):
        R.section_shape("round")


def test_transition_loft_sizes_and_open_ends():
    p = R.transition_loft(40, (30, 30, 4), length=30, wall=2, collar_a=10, collar_b=5)
    assert p.is_valid and len(p.solids()) == 1
    bb = p.bounding_box()
    assert (bb.size.X, bb.size.Z, bb.min.Z) == pytest.approx((40, 45, 0), abs=1e-3)
    # open both ends: a 2 mm ring on the bed and at the top
    assert section(p, Plane.XY.offset(0.1)).area == pytest.approx(3.1416 * (20 ** 2 - 18 ** 2), rel=0.01)
    assert section(p, Plane.XY.offset(44.9)).area < 30 * 30 - 26 * 26 + 1
    solid = R.transition_loft(40, 20, length=30)
    assert solid.volume > p.volume
    shifted = R.transition_loft(20, 20, length=30, shift=(5, 0))
    assert shifted.bounding_box().size.X == pytest.approx(25, abs=1e-3)
    with pytest.raises(ValueError, match="no opening"):
        R.transition_loft(10, 10, length=10, wall=6)


def test_swept_section_lies_flat_and_follows_the_path():
    from build123d import FilletPolyline

    hook = R.swept_section(FilletPolyline((0, 50, 0), (0, 0, 0), (20, 0, 0), radius=8), (5, 8))
    bb = hook.bounding_box()
    assert hook.is_valid and bb.min.Z == pytest.approx(0, abs=1e-6) and bb.size.Z == pytest.approx(5, abs=1e-3)
    assert (bb.size.X, bb.size.Y) == pytest.approx((24, 54), abs=1e-3)


def test_revolved_profile_ring_and_radii():
    knob = R.revolved_profile([(3, 0), (16, 0), (16, 5), (13, 18), (3, 18)], radius=[0, 0, 1, 2, 0])
    assert knob.is_valid and knob.bounding_box().min.Z == pytest.approx(0, abs=1e-6)
    # a 6 mm bore through the middle
    assert section(knob, Plane.XY.offset(9)).area < section(R.revolved_profile([(0, 0), (16, 0), (16, 18), (0, 18)]),
                                                             Plane.XY.offset(9)).area
    assert R.revolved_profile([(3, 0), (10, 0), (10, 5)], angle=180).volume == pytest.approx(
        R.revolved_profile([(3, 0), (10, 0), (10, 5)]).volume / 2, rel=1e-3)
    with pytest.raises(ValueError, match="radii"):
        R.revolved_profile([(3, 0), (10, 0), (10, 5)], radius=[1, 1])
    with pytest.raises(ValueError, match=">= 0"):
        R.revolved_profile([(-1, 0), (10, 0), (10, 5)])


@pytest.mark.parametrize("name, sizes", [
    ("hose_adapter", {"part": (64.4, 62.4, 80.0)}),
    ("rounded_enclosure", {"box": (80.0, 55.0, 30.0), "lid": (80.0, 55.0, 7.0)}),
])
def test_profile_examples_build_and_pass(name, sizes):
    mod = load(EXAMPLES / name / f"{name}.py")
    parts = {(k or "part"): p for k, p in printables(mod, dims(mod, "")).items()}
    assert set(parts) == set(sizes)
    for k, p in parts.items():
        assert p.is_valid and len(p.solids()) == 1, k
        bb = p.bounding_box()
        assert bb.min.Z == pytest.approx(0, abs=1e-3), k
        assert tuple(bb.size) == pytest.approx(sizes[k], abs=0.05), k
    found = run_checks(mod, "", Settings(), nudge=False)
    assert not [f.line() for f in found if f.level == ck.FAIL]
    walls = [f for f in found if f.check == "wall"]
    assert walls and all(f.level == ck.OK for f in walls)
