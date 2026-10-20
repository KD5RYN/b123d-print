"""Geometric insertion, travel and retention checks; no physical print validation."""
import importlib.util
from pathlib import Path

import pytest
from build123d import Align, Box, Cylinder, Pos

from b123d_print import recipes as R

BED = (Align.CENTER, Align.CENTER, Align.MIN)


def overlap(a, b):
    common = a & b
    return 0 if common is None else common.volume


def plate(recipe, **kwargs):
    return Box(20, 32, 5, align=BED) - Pos(0, -5, 5) * recipe(
        shaft_d=3, head_d=6, plate_t=5, travel=10, size=None, **kwargs)


@pytest.mark.parametrize("recess", [0, 3.4])
def test_keyhole_head_inserts_then_shaft_and_head_travel(recess):
    p = plate(R.keyhole_mount, head_depth=recess)
    # Head traverses the entire plate axially at the entry.
    for z in [-3, 0, 1, 3, 5]:
        head = Pos(0, -5, z) * Cylinder(3, 3, align=BED)
        assert overlap(p, head) < 1e-7
    # Inside the opposite-face cavity (or beyond the face), the whole head travels.
    head_z = 0.2 if recess else -3.2
    for y in [-5, -2.5, 0, 2.5, 5]:
        head = Pos(0, y, head_z) * Cylinder(3, 3, align=BED)
        shaft = Pos(0, y, head_z + 3) * Cylinder(1.5, 8, align=BED)
        assert overlap(p, head + shaft) < 1e-7
    # Pulling the retained head through the lip is blocked by material.
    assert overlap(p, Pos(0, 5, 3.5) * Cylinder(3, 1, align=BED)) > 1


def test_slot_retains_head_but_allows_adjustment():
    p = plate(R.mounting_slot, head_depth=3.4)
    for y in [-5, 0, 5]:
        screw = Pos(0, y, 0.2) * Cylinder(3, 3, align=BED)
        screw += Pos(0, y, 3.2) * Cylinder(1.5, 8, align=BED)
        assert overlap(p, screw) < 1e-7
        assert overlap(p, Pos(0, y, 3.5) * Cylinder(3, 1, align=BED)) > 1


def test_mount_dimensions_tables_compensation_and_lip():
    slot = R.mounting_slot(shaft_d=3, head_d=6, head_depth=3.4, clearance=0.2, hole_comp=0.1)
    assert slot.bounding_box().size.X == pytest.approx(6.5)
    assert slot.bounding_box().size.Y == pytest.approx(16.5)
    assert slot.bounding_box().size.Z == pytest.approx(5)
    # The shaft width receives the SAME total allowance once, even with a recess.
    narrow = slot & (Pos(0, 5, -0.5) * Box(20, 1, 0.1))
    assert narrow.bounding_box().size.X == pytest.approx(3.5)
    table_slot = R.mounting_slot(size="M4", clearance=0, head_depth=1)
    assert table_slot.bounding_box().size.X == pytest.approx(R._screw("M4")["head_d"])
    p = plate(R.keyhole_mount, head_depth=3.4, min_lip=1.6)
    lip = Pos(2.5, 5, 3.4) * Box(0.2, 0.2, 1.6, align=BED)
    assert overlap(p, lip) == pytest.approx(lip.volume)
    cavity = Pos(2.5, 5, 0) * Box(0.2, 0.2, 3.4, align=BED)
    assert overlap(p, cavity) < 1e-7
    # Recess edge at X=3.2 leaves a continuous 6.8 mm side wall to the plate edge.
    edge_wall = Pos(6.6, 5, 0) * Box(6.8, 0.2, 3.4, align=BED)
    assert overlap(p, edge_wall) == pytest.approx(edge_wall.volume)


@pytest.mark.parametrize("kwargs", [
    {"shaft_d": 0}, {"head_d": 3}, {"hole_comp": 3}, {"head_depth": 5},
    {"head_depth": 3.5, "min_lip": 1.6}, {"travel": -1}, {"clearance": -0.1},
    {"hole_comp": -1}, {"plate_t": float("nan")}, {"travel": float("inf")},
])
@pytest.mark.parametrize("recipe", [R.keyhole_mount, R.mounting_slot])
def test_mount_rejects_invalid_dimensions(recipe, kwargs):
    args = dict(shaft_d=3, head_d=6, plate_t=5, size=None)
    args.update(kwargs)
    with pytest.raises(ValueError):
        recipe(**args)


def test_keyhole_rejects_head_that_can_still_escape_entry():
    with pytest.raises(ValueError, match="travel"):
        R.keyhole_mount(shaft_d=3, head_d=6, travel=0.23, clearance=0.2, size=None)
    with pytest.raises(ValueError, match="supply"):
        R.keyhole_mount(size=None)
    assert R.mounting_slot(travel=0).is_valid  # round clearance hole is a valid zero-travel slot


@pytest.mark.parametrize("name", ["keyhole_mount", "mounting_slot"])
def test_mount_recipe_resource_code_can_be_executed(name):
    text = R.get(name).text()
    code = text.split("## Code\n", 1)[1].split("```python\n", 1)[1].split("```", 1)[0]
    scope = {}
    exec(code, scope)
    assert scope[name]().is_valid


def test_documented_coupon_builds_and_has_clear_screw_standins():
    file = Path(__file__).parents[1] / "docs/fixtures/wall_mount_coupon.py"
    spec = importlib.util.spec_from_file_location("wall_mount_coupon", file)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    d = mod.Dims()
    p = mod.build(d)
    assert p.is_valid and p.bounding_box().min.Z == pytest.approx(0)
    assembled = mod.assembly(d)
    for screw, _, _ in assembled[1:]:
        assert overlap(assembled[0][0], screw) < 1e-7
    from b123d_print.config import Settings
    from b123d_print.project import run_checks
    mod.build = lambda _: p
    found = run_checks(mod, "", Settings(), nudge=False)
    assert not [f.line() for f in found if f.level == "FAIL"]
