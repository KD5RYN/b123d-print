"""Checks against shapes with known answers."""

import math

import pytest
from build123d import Align, Box, Compound, Cone, Cylinder, Polygon, Pos, Rot, extrude, fillet, chamfer, Axis

from b123d_print.checks import (BedEdge, Gap, Holes, Overhang, ThinFeature, holes, overhang_faces, overlap,
                                round_topped_holes, wall_thickness)
from b123d_print.config import Settings

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
    assert all(f["kind"] == "cantilever" for f in r["faces"])  # ledges off one wall (BP-O4)
    assert overhang_faces(Cone(5, 10, 5, align=BED))["faces"] == []  # exactly 45 deg: fine
    assert overhang_faces(Cone(5, 15, 5, align=BED))["max_angle"] == pytest.approx(63.4, abs=0.5)
    assert overhang_faces(Box(10, 10, 10, align=BED))["faces"] == []  # bed face ignored


def test_wall_limit_and_exclude():
    fin = Box(20, 10, 5) + Pos(0, 7.4, 0) * Box(0.3, 5, 5)
    assert wall_thickness(fin, "XY", 0, limit=1.0)["min"] == pytest.approx(0.3, abs=0.01)
    assert wall_thickness(fin, "XY", 0, limit=0.2)["min"] == math.inf  # nothing thinner than the limit
    assert wall_thickness(fin, "XY", 0, limit=1.0, exclude=[(-1, 4, 1, 11)])["min"] == math.inf


S = Settings()


def run(check, part, **kw):
    return check("part", **kw).run({"part": part}, None, S)


def levels(findings):
    return sorted(f.level for f in findings)


def test_thin_feature():  # BP-W1, BP-W2
    base = Box(20, 10, 5, align=BED)
    assert levels(run(ThinFeature, base + Pos(0, 7.4, 0) * Box(0.3, 5, 5, align=BED))) == ["fail"]  # fin < 1 line
    assert levels(run(ThinFeature, base + Pos(0, 7.4, 0) * Box(0.6, 5, 5, align=BED))) == ["warn"]  # < min_wall
    assert levels(run(ThinFeature, base + Pos(0, 7.4, 0) * Box(1.2, 5, 5, align=BED))) == ["ok"]
    assert levels(run(ThinFeature, base + Pos(0, 0, 5) * Box(30, 10, 0.3, align=BED))) == ["fail"]  # thin plate
    assert levels(run(ThinFeature, Box(20, 10, 2, align=BED) + Pos(0, 0, 2) * Cylinder(0.2, 5, align=BED))) == ["fail"]  # pin
    fin = base + Pos(0, 7.4, 0) * Box(0.3, 5, 5, align=BED)
    assert levels(run(ThinFeature, fin, ignore=[((0, 7.5, 2.5), (2, 6, 6))])) == ["ok"]  # an intended thin region
    assert levels(run(ThinFeature, fin, planes=())) == ["ok"]


def test_thin_feature_knife_edge_warns():  # BP-R3: a wedge tapers to nothing; an edge, not a wall
    wedge = extrude(Polygon((0, 0), (30, 0), (30, 30 * math.tan(math.radians(15))), align=None), 10)
    f = run(ThinFeature, wedge)
    assert levels(f) == ["warn"] and "knife edge" in f[0].message


def test_holes():  # BP-H3, BP-H5
    plate = Box(40, 20, 20, align=BED)
    round_h = plate - Pos(-10, 0, 10) * Rot(90, 0, 0) * Cylinder(2.5, 40)
    hs = holes(round_h)
    assert len(hs) == 1 and hs[0]["d"] == pytest.approx(5) and not hs[0]["vertical"] and hs[0]["span"] == 360
    assert len(round_topped_holes(round_h)) == 1
    # teardrop: the circle plus a 45 deg roof up to a point
    r = 2.5
    tip = r * math.sqrt(2)
    roof = Pos(-10, 0, 10) * Rot(90, 0, 0) * extrude(Polygon((-r / math.sqrt(2), r / math.sqrt(2)), (0, tip),
                                                              (r / math.sqrt(2), r / math.sqrt(2)), (0, 0), align=None), 20, both=True)
    tear = plate - Pos(-10, 0, 10) * Rot(90, 0, 0) * Cylinder(r, 40) - roof
    assert len(holes(tear)) == 1 and round_topped_holes(tear) == []
    assert levels(run(Holes, round_h)) == ["warn"] and levels(run(Holes, tear)) == ["ok"]
    vert = plate - Cylinder(0.4, 50)  # 0.8 mm vertical hole: too small to print round
    f = run(Holes, vert)
    assert levels(f) == ["warn"] and "under 1 mm" in f[0].message
    assert levels(run(Holes, plate)) == ["ok"]
    fil = fillet(Box(20, 20, 10, align=BED).edges().filter_by(Axis.Z), 3)  # convex: not holes
    assert holes(fil) == []


def test_bridges_and_cantilevers():  # BP-O3, BP-O4
    tee = Box(10, 10, 10, align=BED) + Pos(0, 0, 10) * Box(30, 10, 2, align=BED)
    assert all(f["kind"] == "cantilever" for f in overhang_faces(tee)["faces"])
    slot = Box(40, 10, 10, align=BED) - Box(30, 20, 6, align=BED)  # tunnel along Y: 30 mm between the X walls
    (f,) = overhang_faces(slot)["faces"]
    assert f["kind"] == "bridge" and f["span"] == pytest.approx(30, abs=0.5)
    pocket = Box(40, 40, 10, align=BED) - Pos(0, 0, 2) * Box(30, 20, 4, align=BED)  # closed: the short way
    (f,) = overhang_faces(pocket)["faces"]
    assert f["kind"] == "bridge" and f["span"] == pytest.approx(20, abs=0.5)
    out = run(Overhang, slot)
    assert [x.check for x in out] == ["overhang", "bridge"] and levels(out) == ["warn", "warn"]
    assert levels(run(Overhang, slot, fail=True)) == ["warn", "warn"]  # a bridge never fails
    assert "fail" in levels(run(Overhang, tee, fail=True))  # a cantilever does
    short = Box(20, 10, 10, align=BED) - Box(8, 20, 6, align=BED)
    assert levels(run(Overhang, short)) == ["warn"]  # listed, not too long


def test_bed_edge():  # BP-O2
    block = Box(20, 20, 10, align=BED)
    assert levels(run(BedEdge, fillet(block.edges().group_by(Axis.Z)[0], 2))) == ["warn"]
    assert levels(run(BedEdge, chamfer(block.edges().group_by(Axis.Z)[0], 2))) == ["ok"]
    assert levels(run(BedEdge, fillet(block.edges().group_by(Axis.Z)[-1], 2))) == ["ok"]  # top edges are fine


def test_gap():  # BP-F1, BP-F3
    a, b = Box(10, 10, 5, align=BED), Pos(10.2, 0, 0) * Box(10, 10, 5, align=BED)
    pip = Compound([a, Pos(10.1, 0, 0) * Box(10, 10, 5, align=BED)])
    assert levels(run(Gap, pip)) == ["fail"]  # 0.1 apart, printed in place: they fuse
    assert levels(run(Gap, Compound([a, Pos(10.4, 0, 0) * Box(10, 10, 5, align=BED)]))) == ["ok"]
    assert run(Gap, a) == []  # one solid: nothing to check
    parts = {"a": a, "b": b}
    assert Gap("a", "b").run(parts, None, S)[0].level == "ok"  # 0.2 = clearance
    assert Gap("a", "b", min=0.3).run(parts, None, S)[0].level == "fail"
    assert Gap("a", "b", max=0.1).run(parts, None, S)[0].level == "fail"
    asm = [(Pos(0, 0, 50) * a, "", "a"), (Pos(0, 0, 50) * b, "", "b")]  # assembly labels win
    assert Gap("a", "b").run(parts, asm, S)[0].data["gap"] == pytest.approx(0.2, abs=1e-3)
    far = Gap("a", "b", within=((0, 20, 0), (1, 1, 1))).run(parts, None, S)
    assert far[0].level == "fail" and "nothing to measure" in far[0].message


def test_overlap():
    f = overlap([(Box(10, 10, 10), "a"), (Pos(9, 0, 0) * Box(10, 10, 10), "b"), (Pos(30, 0, 0) * Box(1, 1, 1), "c")])
    levels = {x.target: x.level for x in f}
    assert levels == {"a / b": "fail", "a / c": "ok", "b / c": "ok"}
    assert overlap([(Box(10, 10, 10), "a"), (Pos(9, 0, 0) * Box(10, 10, 10), "b")], ignore=[("b", "a")]) == []
