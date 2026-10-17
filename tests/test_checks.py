"""Checks against shapes with known answers."""

import math

import pytest
from build123d import Align, Box, Cone, Cylinder, Polygon, Pos, extrude

from cadkit.checks import overhang_faces, overlap, wall_thickness

BED = (Align.CENTER, Align.CENTER, Align.MIN)


def test_wall_thin_ring():  # an 8.0 boss around a 7.8 counterbore: the print that broke
    ring = Cylinder(4.0, 10, align=BED) - Cylinder(3.9, 30)
    assert wall_thickness(ring, "XY", 5)["min"] == pytest.approx(0.1, abs=0.01)


def test_wall_hole_to_edge_and_region():
    plate = Box(30, 30, 4, align=BED) - Pos(12, 0, 0) * Cylinder(1.5, 30)
    assert wall_thickness(plate, "XY", 2, near=(12, 0), radius=5)["min"] == pytest.approx(1.5, abs=0.02)
    assert wall_thickness(plate, "XZ", 0)["min"] == pytest.approx(1.5, abs=0.02)  # 13.5..15 strip
    assert wall_thickness(plate, "XZ", 0, near=(0, 2), radius=3)["min"] == pytest.approx(4.0, abs=0.02)


def test_wall_corners_are_not_walls():
    tri = extrude(Polygon((0, 0), (20, 0), (10, 10 * math.sqrt(3)), align=None), 5)  # 60 deg corners
    assert wall_thickness(tri, "XY", 2)["min"] > 10
    fin = Box(20, 10, 5) + Pos(0, 7.4, 0) * Box(0.3, 5, 5)
    assert wall_thickness(fin, "XY", 0)["min"] == pytest.approx(0.3, abs=0.01)
    knife = extrude(Polygon((0, 0), (20, 0), (20, 20 * math.tan(math.radians(20))), align=None), 5)
    assert wall_thickness(knife, "XY", 2)["min"] < 0.2  # a 20 deg knife edge is thin


def test_wall_misses():
    assert wall_thickness(Box(10, 10, 10, align=BED), "XY", 50) is None


def test_overhang():
    t = Box(10, 10, 10, align=BED) + Pos(0, 0, 10) * Box(30, 10, 2, align=BED)
    r = overhang_faces(t)
    assert r["area"] == pytest.approx(200, abs=0.5) and r["max_angle"] == 90
    assert all(f["kind"] == "bridge" for f in r["faces"])
    assert overhang_faces(Cone(5, 10, 5, align=BED))["faces"] == []  # exactly 45 deg: fine
    assert overhang_faces(Cone(5, 15, 5, align=BED))["max_angle"] == pytest.approx(63.4, abs=0.5)
    assert overhang_faces(Box(10, 10, 10, align=BED))["faces"] == []  # bed face ignored


def test_overlap():
    f = overlap([(Box(10, 10, 10), "a"), (Pos(9, 0, 0) * Box(10, 10, 10), "b"), (Pos(30, 0, 0) * Box(1, 1, 1), "c")])
    levels = {x.target: x.level for x in f}
    assert levels == {"a / b": "fail", "a / c": "ok", "b / c": "ok"}
    assert overlap([(Box(10, 10, 10), "a"), (Pos(9, 0, 0) * Box(10, 10, 10), "b")], ignore=[("b", "a")]) == []
