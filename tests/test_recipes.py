"""Every recipe builds a valid part and its demo passes `check` (no FAIL)."""

import types

import pytest

from b123d_print import checks as ck
from b123d_print import recipes as R
from b123d_print.config import Settings
from b123d_print.project import run_checks


@pytest.mark.parametrize("name", list(R.RECIPES))
def test_recipe_demo_builds_and_passes_check(name):
    r = R.RECIPES[name]
    mod = types.ModuleType(f"recipe_{name}")
    mod.build = r.demo
    if name == "living_hinge":  # the web is thin on purpose (BP-N7)
        box = R.living_hinge()[1]
        mod.checks = lambda d: [ck.ThinFeature("part", ignore=[box])]
    part = r.demo()
    assert part.is_valid and part.volume > 0
    found = run_checks(mod, "", Settings(), nudge=False)
    fails = [f.line() for f in found if f.level == ck.FAIL]
    assert not fails, fails


@pytest.mark.parametrize("name", list(R.RECIPES))
def test_recipe_text_has_code_notes_and_sources(name):
    t = R.RECIPES[name].text()
    for f in R.RECIPES[name].functions:
        assert f"def {f.__name__}" in t
    assert "## Printing notes" in t and "## Sources" in t and "BP-" in t + "ISO"


def test_lookup_and_index():
    assert R.get("snap-arm").name == "snap_arm" and R.get("snap_strain").name == "snap_arm"
    assert R.get("cable_slot").name == "zip_tie_slot"
    with pytest.raises(KeyError, match="no recipe"):
        R.get("flux_capacitor")
    idx = R.index()
    assert all(f"`{n}`" in idx for n in R.RECIPES)


def test_snap_strain_formulas():
    # Bayer: 1.5 y h / L^2 constant section, 1.09 y h / L^2 tapered to half
    assert R.snap_strain(1.0, 2.0, 20.0, taper=1.0) == pytest.approx(1.5 * 2 / 400)
    assert R.snap_strain(1.0, 2.0, 20.0) == pytest.approx(1.09 * 2 / 400)
    L = R.snap_length(1.0, 1.6, 0.04)
    assert R.snap_strain(1.0, 1.6, L) == pytest.approx(0.04)


def test_sizes_follow_the_tables():
    from build123d import Box, Pos

    nut = R.nut_trap("M3", screw_depth=0)
    bb = nut.bounding_box()
    assert bb.size.Y == pytest.approx(5.7, abs=1e-3)  # across flats 5.5 + 0.2 total (BP-T7)
    hole = R.screw_hole("M3", 10, "counterbore", hole_comp=0.2)
    assert hole.bounding_box().size.X == pytest.approx(6.7, abs=1e-3)  # 5.5 head + 1 + hole_comp
    mag = R.magnet_pocket(10, 3, fit=0.05)
    assert mag.bounding_box().size.X == pytest.approx(10.1) and mag.bounding_box().size.Z == pytest.approx(3.1)
    lid = R.lid_with_lip(50, 35, wall=2, clearance=0.2)
    assert lid.bounding_box().size.Z == pytest.approx(6.0)
    # the lid fits its box with the clearance per side: the fit check sees the gap
    from b123d_print.fit import Mates

    base = R.box_shell(50, 35, 20)
    placed = Pos(0, 0, 22) * (lid.rotate(__import__("build123d").Axis.X, 180))
    found = Mates(align=False).run({"base": 0, "lid": 0}, [(base, None, "base"), (placed, None, "lid")], Settings())
    assert not [f for f in found if f.level != ck.OK], [f.line() for f in found]
    with pytest.raises(ValueError, match="screw size"):
        R.screw_hole("M7")
    assert Box(1, 1, 1).volume == pytest.approx(1)


def test_pip_hinge_has_two_solids_with_the_clearance():
    from b123d_print.checks import gap

    h = R.pip_hinge()
    a, b = h.solids()
    assert gap(a, b) == pytest.approx(0.3, abs=0.02)
    with pytest.raises(ValueError, match="over the bore"):
        R.pip_hinge(knuckle_d=7)
