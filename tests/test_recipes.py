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
    assert hole.bounding_box().size.X == pytest.approx(R._screw("M3")["head_d"] + 1.2, abs=1e-3)  # head + 1 + hole_comp
    assert R._screw("M3")["head_d"] == pytest.approx(5.68, abs=0.2) and R._screw("M3")["clearance"] == 3.4
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


# --- organic shapes (#151) ----------------------------------------------------------------------


def _bed(p):
    from b123d_print.render import bbox

    return bbox(p).min.Z


def test_spine_loft_places_sections_across_the_spine():
    from build123d import Spline

    spine = Spline((0, 0, 0), (40, 10, 0), (80, 0, 0))
    body = R.spine_loft(spine, [(0, 10), (0.5, 24), (1, 10)])
    assert body.is_valid and len(body.solids()) == 1
    mid = R._frames(spine, [0.5])[0]  # the middle section is a 24 mm circle across the spine there
    from build123d import section

    cut = section(body, mid).faces()[0]
    assert cut.area == pytest.approx(3.1416 * 12**2, rel=0.01)
    # a 0 at an end closes it to a point: no flat cap, no edge but the loft's seam
    tip = R.spine_loft(spine, [(0, 0), (0.05, 8), (0.5, 24), (0.95, 8), (1, 0)])
    assert tip.is_valid and len(tip.faces()) == 1
    with pytest.raises(ValueError, match="first or the last"):
        R.spine_loft(spine, [(0, 10), (0.5, 0), (1, 10)])


def test_frames_do_not_twist():
    from build123d import Spline

    spine = Spline((0, 0, 0), (30, 20, 5), (60, 0, 10), (90, -20, 0))
    planes = R._frames(spine, [i / 10 for i in range(11)])
    for a, b in zip(planes, planes[1:]):
        assert a.x_dir.dot(a.z_dir) == pytest.approx(0, abs=1e-9)
        assert a.x_dir.dot(b.x_dir) > 0.9  # carried along, never flipped round the spine


def test_tapered_sweep_follows_its_path():
    from build123d import Spline

    path = Spline((0, 0, 0), (2, 0, 20), (15, 0, 35), tangents=((0, 0, 1), (1, 0, 0.5)))
    horn = R.tapered_sweep(path, [12, 6, 2])
    assert horn.is_valid and len(horn.solids()) == 1
    assert _bed(horn) == pytest.approx(0, abs=1e-3)
    with pytest.raises(ValueError, match="cannot end in a point"):
        R.tapered_sweep(path, [12, 0])


def test_organic_blend_joins_in_one_smooth_solid():
    from build123d import Align, Cylinder, Plane, Pos, Rot, Vector, split, Keep

    a = Cylinder(10, 40, align=(Align.CENTER, Align.CENTER, Align.MIN))
    axis = Vector(0.866, 0, 0.5)
    b = Pos(30, 0, 60) * Rot(0, 60, 0) * Cylinder(5, 40)
    at_a = Plane(origin=(0, 0, 35), z_dir=(0, 0, 1))
    at_b = Plane(origin=b.center() - axis * 10, z_dir=-axis)
    j = R.organic_blend(a, b, at_a, at_b)
    assert j.is_valid and len(j.solids()) == 1
    kept = split(a, at_a, keep=Keep.BOTTOM).volume + split(b, at_b, keep=Keep.BOTTOM).volume
    assert kept < j.volume < kept + 3.1416 * 10**2 * 30  # the cut bodies plus a collar no fatter than a
    # sewn, not fused with slivers: two cylinders, their two outer ends and the collar
    assert len(j.faces()) == 5 and min(f.area for f in j.faces()) > 50


def test_flat_base_stands_on_the_bed():
    from build123d import Sphere, Spline

    egg = R.flat_base(Sphere(10), 2)
    assert egg.is_valid and egg.bounding_box().min.Z == pytest.approx(0, abs=1e-6)
    assert egg.bounding_box().size.Z == pytest.approx(18, abs=1e-3)
    with pytest.raises(ValueError, match="depth"):
        R.flat_base(Sphere(10), 0)
    # a lofted body lying down: OpenCascade's own box still reaches under the bed (it bounds a face
    # by its whole parameter rectangle); render.bbox does not, and flat_base uses it
    body = R.spine_loft(Spline((0, 0, 0), (35, 8, -3), (70, 0, 6)), [(0, 10), (0.5, 30), (1, 10)])
    cut = R.flat_base(body, 4)
    assert cut.bounding_box().min.Z < -1
    assert _bed(cut) == pytest.approx(0, abs=0.03)
    from build123d import Plane, section

    assert section(cut, Plane.XY.offset(0.1)).area > 100  # a real strip on the bed


def test_banana_example():
    """The bundled organic example: one valid solid on the bed, nothing a box or a cylinder, and
    the organic style finds nothing to suggest."""
    from pathlib import Path

    from b123d_print import metrics as M
    from b123d_print.project import dims, load, printables

    mod = load(Path(R.__file__).parent / "examples" / "banana" / "banana.py")
    d = dims(mod, "")
    part = printables(mod, d)[""]
    assert part.is_valid and len(part.solids()) == 1
    assert _bed(part) == pytest.approx(0, abs=0.03)
    assert {f.geom_type.name for f in part.faces()} <= {"BSPLINE", "PLANE"}  # the bed and the stem's cut end
    res = M.design_metrics(mod, d, {"": part}, Settings())
    assert res["style"] == "organic"
    assert not [f for f in res["findings"] if f["level"] == "suggest"], res["findings"]


def test_section_loop_closure_is_not_a_knife_edge():
    """A section's edges meet within ~1e-5, not exactly: the loop's last point sat on its first, and
    the near-zero segment between them read as a 0.00 mm knife edge where a collar meets a body."""
    from b123d_print.checks import wall_thickness

    r = wall_thickness(R.demo_organic_blend(), "XZ", 4.0, step=0.25, limit=0.8)
    assert r is None or r["min"] == float("inf"), r
