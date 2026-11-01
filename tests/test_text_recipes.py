"""Text beyond flat labels (#168): text_on_surface (wrap and project), text_on_path, multi-line
text_label, the second-colour inlay, the face-does-not-mesh check and the text_knob example."""

import types
from pathlib import Path

import pytest
from build123d import Align, Axis, CenterArc, Cone, Cylinder, Plane, Pos, Rectangle, Sphere, fillet, loft

from b123d_print import checks as ck
from b123d_print import recipes as R
from b123d_print.config import Settings
from b123d_print.project import dims, load, printables, run_checks

BED = (Align.CENTER, Align.CENTER, Align.MIN)


def _radial(shape, axis_xy=(0, 0)):
    """Smallest and largest distance from the Z axis over the shape's vertices."""
    rs = [((v.X - axis_xy[0]) ** 2 + (v.Y - axis_xy[1]) ** 2) ** 0.5 for v in shape.vertices()]
    return min(rs), max(rs)


@pytest.mark.parametrize("deboss", [False, True])
def test_wrap_on_a_cylinder_follows_the_surface(deboss):
    jar = Cylinder(15, 24, align=BED)
    t = R.text_on_surface(jar, "AB", at=(0, -30, 12), size=6, depth=0.6, deboss=deboss)
    assert t.is_valid and len(t.solids()) >= 2  # one solid per glyph piece
    lo, hi = _radial(t)
    if deboss:  # 0.6 into the wall, TEXT_SINK out of it
        assert lo == pytest.approx(15 - 0.6, abs=0.05) and hi == pytest.approx(15 + R.TEXT_SINK, abs=0.05)
    else:
        assert lo == pytest.approx(15 - R.TEXT_SINK, abs=0.05) and hi == pytest.approx(15 + 0.6, abs=0.05)
    bb = t.bounding_box()
    assert bb.max.Y < -10 and bb.min.Z > 8 and bb.max.Z < 16  # on the side facing `at`, centered on Z 12
    part = jar - t if deboss else jar + t
    assert part.is_valid and len(part.solids()) == 1
    assert (part.volume < jar.volume) if deboss else (part.volume > jar.volume)


def test_wrap_works_across_a_closed_face_seam():
    """A cylinder's face has its seam at +X: Face.wrap fails there; the recipe turns the face."""
    jar = Cylinder(15, 24, align=BED)
    t = R.text_on_surface(jar, "SEAM", at=(30, 0, 12), size=5)
    assert t.is_valid and t.bounding_box().min.X > 10
    assert (jar + t).is_valid


@pytest.mark.parametrize("body, at", [
    (Cone(22, 14, 25, align=BED), (0, -40, 12)),
    (Pos(0, 0, 20) * Sphere(20), (0, -40, 24)),
])
def test_wrap_on_cones_and_spheres(body, at):
    t = R.text_on_surface(body, "HI", at=at, size=6, depth=0.8, deboss=True)
    part = body - t
    assert part.is_valid and len(part.solids()) == 1 and part.volume < body.volume


def test_project_crosses_face_edges_onto_a_lofted_lid():
    lid = loft([Rectangle(60, 40), Plane.XY.offset(8) * Rectangle(40, 24)])
    lid = fillet(lid.edges().group_by(Axis.Z)[-1], 6)
    t = R.text_on_surface(lid, "LID", at=(0, 0, 30), size=9, method="project")
    assert t.is_valid and t.bounding_box().max.Z == pytest.approx(8 + 0.6, abs=0.05)
    part = lid + t
    assert part.is_valid and len(part.solids()) == 1
    with pytest.raises(ValueError, match="method"):
        R.text_on_surface(lid, "X", at=(0, 0, 30), method="paint")


def test_deboss_inlay_fills_the_pocket_exactly():
    """The text body is the second colour: part & pocket is flush with the surface and is what
    the cut took away."""
    jar = Cylinder(15, 24, align=BED)
    pocket = R.text_on_surface(jar, "OK", at=(0, -30, 12), size=7, depth=0.8, deboss=True)
    body = jar - pocket
    inlay = jar & pocket
    assert inlay.volume > 0
    assert body.volume + inlay.volume == pytest.approx(jar.volume, abs=0.01 * inlay.volume)  # booleans differ by OS
    assert _radial(inlay)[1] == pytest.approx(15, abs=0.01)  # flush, nothing proud of the surface


def test_text_on_path_follows_the_arc():
    over = R.text_on_path("TOP", CenterArc((0, 0), 15, 160, -140), size=5)  # clockwise: along the top
    under = R.text_on_path("TOP", CenterArc((0, 0), 15, 200, 140), size=5)  # counter-clockwise: the bottom
    assert over.is_valid and over.bounding_box().size.Z == pytest.approx(0.6)
    assert over.bounding_box().min.Y > 5 and under.bounding_box().max.Y < -5
    lo, hi = _radial(over)
    assert lo > 13 and hi < 15 + 5  # the letters stand on the arc, outward


def test_text_label_takes_several_lines():
    one = R.text_label("AB", size=5).bounding_box().size.Y
    two = R.text_label("AB\nCD", size=5).bounding_box().size.Y
    assert two > 1.8 * one
    left = R.text_label("A\nBBBB", size=5, text_align=(R.TextAlign.LEFT, R.TextAlign.CENTER))
    assert left.is_valid


def _unmeshable_face():
    """A spline face bounded by a bow-tie (self-crossing) wire: OpenCascade cannot mesh it, on
    every platform. (Cutting wrapped text into a revolved spline face can leave such a face too,
    depending on the platform's boolean.)"""
    from build123d import Face
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepLib import BRepLib
    from OCP.Geom2d import Geom2d_Line
    from OCP.gp import gp_Dir2d, gp_Pnt2d

    base = Face.make_surface_from_array_of_points([[(x, y, 0.1 * x * y) for x in range(4)] for y in range(4)])
    surf = BRep_Tool.Surface_s(base.wrapped)
    u0, u1, v0, v1 = base._uv_bounds()
    pts = [gp_Pnt2d(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b) for a, b in ((0.2, 0.2), (0.8, 0.8), (0.8, 0.2), (0.2, 0.8))]
    wire = BRepBuilderAPI_MakeWire()
    for p, q in zip(pts, pts[1:] + pts[:1]):
        line = Geom2d_Line(p, gp_Dir2d(q.X() - p.X(), q.Y() - p.Y()))
        wire.Add(BRepBuilderAPI_MakeEdge(line, surf, 0.0, p.Distance(q)).Edge())
    face = BRepBuilderAPI_MakeFace(surf, wire.Wire()).Face()
    BRepLib.BuildCurves3d_s(face)
    return Face(face)


def test_a_face_that_does_not_mesh_fails_the_validity_check(monkeypatch):
    """A face OpenCascade cannot triangulate is a hole in the exported STL: the validity check says so."""
    from b123d_print import project
    from b123d_print.render import unmeshed_faces

    jar = Cylinder(15, 24, align=BED)
    assert not unmeshed_faces(jar)
    bad = _unmeshable_face()
    assert unmeshed_faces(bad) == [bad]
    monkeypatch.setattr(project, "unmeshed_faces", lambda p: [bad])  # a valid solid with such a face
    mod = types.ModuleType("jar")
    mod.build = lambda: jar
    valid = [f for f in run_checks(mod, "", Settings(), nudge=False) if f.check == "valid"]
    assert [f.level for f in valid] == [ck.OK, ck.FAIL]
    assert "do not mesh" in valid[1].message and "method='project'" in valid[1].message


def test_text_knob_example():
    mod = load(Path(R.__file__).parent / "examples" / "text_knob" / "text_knob.py")
    d = dims(mod, "")
    part = printables(mod, d)[""]
    assert part.is_valid and len(part.solids()) == 1
    body, label = mod.body(d), mod.label(d)
    assert part.volume < body.volume and (body & label).volume > 0  # the text is cut, and is an inlay
    found = run_checks(mod, "", Settings(), nudge=False)
    assert not [f.line() for f in found if f.level == ck.FAIL]



def test_thin_check_ignores_sections_grazing_angled_strokes():
    """An XZ or YZ section grazing the upright corner of a stroke set at an angle (a letter on an
    arc) cuts a sliver of a stroke that is wide, in both planes: it read as a 0.09 mm wall here.
    Only XY may confirm an upright wall. A real thin upright fin at an angle is still found."""
    from build123d import Box, Rot

    from b123d_print.checks import thin_features

    tag = Cylinder(22, 3, align=BED) + Pos(0, 0, 3) * R.text_on_path("ONE TIME", CenterArc((0, 0), 15, 160, -140), size=5)
    walls = [s for s in thin_features(tag, 0.8) if not s["taper"] and s["min"] < 0.45]  # the check's warn limit
    assert not walls, walls
    fin = Box(40, 40, 2, align=BED) + Pos(0, 0, 2) * Rot(0, 0, 30) * Box(0.3, 12, 6, align=BED)
    found = [s for s in thin_features(fin, 0.45) if not s["taper"]]
    assert found and found[0]["min"] == pytest.approx(0.3, abs=0.05)
