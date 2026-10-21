"""Fit-test templates (templates.py) on known shapes."""

import itertools
import math

import pytest
from build123d import Align, Box, Cylinder, Pos

from b123d_print import checks as ck
from b123d_print import templates as tp
from b123d_print import outdir

BED = (Align.CENTER, Align.CENTER, Align.MIN)
HOLES = [(20.0, 10.0, 3.4), (-20.0, 10.0, 3.4), (-20.0, -10.0, 4.4), (20.0, -10.0, 4.4)]  # x, y, d


def plate(w=60.0, d=40.0, h=6.0):
    p = Box(w, d, h, align=BED)
    for x, y, dia in HOLES:
        p -= Pos(x, y, 0) * Cylinder(dia / 2, 30)
    return p


def mounted():
    """A plate with a post on top, the plate's holes the mounting pattern."""
    return plate() + Pos(0, 0, 6) * Box(10, 10, 10, align=BED)


def round_holes(part):
    return sorted((h["d"], round(h["center"][0], 3), round(h["center"][1], 3)) for h in ck.holes(part))


def spacings(holes):
    return sorted(round(math.dist(a[1:], b[1:]), 4) for a, b in itertools.combinations(holes, 2))


def test_slice_of_a_plate_has_the_outline_and_hole_sizes():
    m = tp.slice_template(plate(), "XY", 3.0, label=None)
    bb = m.part.bounding_box()
    assert (round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)) == (60.0, 40.0, 1.2)
    assert bb.min.Z == pytest.approx(0) and m.part.is_valid
    assert m.info["range"] == [2.4, 3.6] and m.info["print_orientation"] and m.info["pieces"] == 1
    got = round_holes(m.part)
    assert sorted(h[0] for h in got) == sorted(d for _, _, d in HOLES)
    assert sorted((h[1], h[2]) for h in got) == sorted((x, y) for x, y, _ in HOLES)  # centered: the plate was too
    assert m.part.volume == pytest.approx(plate().volume * 1.2 / 6, rel=1e-6)


def test_slice_near_the_end_moves_inward_and_a_miss_is_an_error():
    m = tp.slice_template(plate(), "XY", 0.0, label=None)
    assert m.info["range"] == [0.0, 1.2]
    m = tp.slice_template(plate(), "XY", 6.0, label=None)
    assert m.info["range"] == [4.8, 6.0]
    with pytest.raises(tp.TemplateError, match="misses the part: it spans Z 0.00 to 6.00"):
        tp.slice_template(plate(), "XY", 9.0)
    with pytest.raises(tp.TemplateError, match="plane"):
        tp.slice_template(plate(), "XW", 1.0)


def test_slice_on_its_side_keeps_the_hole_pattern_and_joins_pieces():
    """An XZ slice through the holes at Y=10 falls apart into three pieces: the base plate joins
    them, so the distance between them is kept."""
    m = tp.slice_template(plate(), "XZ", 10.0, label=None)
    assert m.info["pieces"] == 3 and m.info["base"]["thickness"] == tp.BASE_T
    assert len(m.part.solids()) == 1 and m.part.is_valid
    assert not m.info["print_orientation"] and any("print orientation" in n for n in m.info["notes"])
    bb = m.part.bounding_box()
    assert bb.size.Z == pytest.approx(1.2 + tp.BASE_T) and bb.size.X == pytest.approx(60)
    no_base = tp.slice_template(plate(), "XZ", 10.0, base=False, label=None)
    assert len(no_base.part.solids()) == 3 and any("not kept" in n for n in no_base.info["notes"])


def test_face_template_keeps_the_hole_spacing_exactly():
    part = mounted()
    m = tp.face_template(part, "bottom", label=None)
    assert m.info["face"] == 1 and m.info["normal"] == [0.0, 0.0, -1.0]
    bb = m.part.bounding_box()
    assert bb.size.Z == pytest.approx(1.2) and bb.min.Z == pytest.approx(0)
    got = round_holes(m.part)
    want = sorted((d, x, y) for x, y, d in HOLES)
    assert [h[0] for h in got] == [h[0] for h in want]
    assert spacings(got) == spacings(want)
    # the top of the plate (around the post) as a template: laid face down, i.e. turned over
    top = tp.face_template(part, (25.0, 0.0, 6.0), label=None)
    assert top.info["down"] == "top" and not top.info["print_orientation"]
    assert spacings(round_holes(top.part)) == spacings(want)


def test_face_template_from_a_side_wall():
    m = tp.face_template(plate(), "front", thickness=2.0, label=None)
    bb = m.part.bounding_box()
    assert sorted(round(v, 3) for v in (bb.size.X, bb.size.Y, bb.size.Z)) == [2.0, 6.0, 60.0]
    assert bb.size.Z == pytest.approx(2.0)


def test_crop_around_a_corner_is_valid_and_prints_flat():
    part = mounted()
    m = tp.crop_template(part, (25.0, 15.0, 3.0), (14.0, 14.0, 10.0), label=None)
    assert m.part.is_valid and m.info["pieces"] == 1 and "base" not in m.info
    bb = m.part.bounding_box()
    assert bb.min.Z == pytest.approx(0) and (round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)) == (12.0, 12.0, 6.0)
    assert m.info["print_orientation"] and m.info["bed_contact_mm2"] > 40
    assert not [f for f in ck.Overhang("t").run({"t": m.part}, None, _settings()) if f.level == ck.FAIL]
    with pytest.raises(tp.TemplateError, match="holds no material"):
        tp.crop_template(part, (100, 0, 0), (5, 5, 5))


def test_crop_of_an_overhang_gets_a_base_or_turns():
    """A T: a crop of only the flange above the bed has no contact in print orientation; it is
    turned onto a flat side (or gets a base plate), never left floating."""
    tee = Box(4, 30, 20, align=BED) + Pos(0, 0, 20) * Box(30, 30, 3, align=BED)
    m = tp.crop_template(tee, (10, 0, 21.5), (10, 10, 3), label=None)
    contact, touching = tp._contact(m.part, (0, 0, -1))
    assert m.part.bounding_box().min.Z == pytest.approx(0) and touching == len(m.part.solids()) and contact > 20


def test_label_is_engraved_without_cutting_a_feature():
    m = tp.slice_template(plate(), "XY", 3.0, label="plate xy3")
    lab = m.info["label"]
    assert lab and lab["text"] == "plate xy3" and lab["depth"] == tp.LABEL_DEPTH
    assert m.part.volume < plate().volume * 1.2 / 6  # something was engraved
    assert round_holes(m.part) == round_holes(tp.slice_template(plate(), "XY", 3.0, label=None).part)
    assert len(m.part.solids()) == 1 and m.part.is_valid and m.ignore
    x, y, _ = lab["at"]
    for hx, hy, d in HOLES:  # clear of every hole by the margin
        assert abs(x - hx) > d / 2 or abs(y - hy) > d / 2
    found = tp.checks(m, _settings())
    assert not [f for f in found if f.level == ck.FAIL], [f.line() for f in found]


def test_label_is_skipped_when_there_is_no_room():
    small = Box(8, 8, 4, align=BED) - Cylinder(1.5, 20)
    m = tp.slice_template(small, "XY", 2.0, label="tiny xy2")
    assert m.info["label"] is None and any(n.startswith("no label") for n in m.info["notes"])
    assert m.part.volume == pytest.approx(tp.slice_template(small, "XY", 2.0, label=None).part.volume)
    long = tp.slice_template(Box(22, 9, 3, align=BED), "XY", 1.0, label="a_very_long_part_name xy1")
    assert long.info["label"] and long.info["label"]["text"] == "xy1"  # the short form fits


def test_face_ids_are_stable_across_rebuilds():
    a = tp.list_faces(mounted())
    # the same geometry, built in another order
    b_part = Pos(0, 0, 6) * Box(10, 10, 10, align=BED) + Box(60, 40, 6, align=BED)
    for x, y, d in reversed(HOLES):
        b_part -= Pos(x, y, 0) * Cylinder(d / 2, 30)
    b = tp.list_faces(b_part)
    assert a == b
    assert [f["id"] for f in a["planar"]] == list(range(1, len(a["planar"]) + 1))
    first = a["planar"][0]
    assert first["side"] == "bottom" and len(first["holes"]) == 4 and a["curved"] == {"cylinder": 4}
    assert tp.find_face(mounted(), "bottom")[1] == 1 and tp.find_face(mounted(), "-Z")[1] == 1
    assert tp.find_face(mounted(), 2)[1] == 2
    with pytest.raises(tp.TemplateError, match="ids are 1 to"):
        tp.find_face(mounted(), 99)


def test_template_spec_ids():
    T = tp.Template
    assert T.slice("XY", 3).ident() == "xy3" and T.slice("XZ", -2.5).ident() == "xz-2.5"
    assert T.face_of(7).ident() == "face7" and T.face_of("-Z").ident() == "face_bottom"
    assert T.crop((10, 0, 5.5), (5, 5, 5)).ident() == "crop_10_0_5.5"
    assert T.slice("XY", 1, name="holes").ident() == "holes"
    with pytest.raises(tp.TemplateError):
        T.slice("XY", 1, name="../x").ident()


HOOK = '''
from dataclasses import dataclass
from build123d import Align, Box, Cylinder, Part, Pos
from b123d_print import Template

BED = (Align.CENTER, Align.CENTER, Align.MIN)

@dataclass(frozen=True)
class Dims:
    W: float = 40.0
    H: float = 5.0

VARIANTS = {"": {}, "wide": dict(W=60.0)}

def build(d):
    return Box(d.W, 30, d.H, align=BED) - Pos(d.W / 2 - 6, 0, 0) * Cylinder(1.7, 20) - Pos(6 - d.W / 2, 0, 0) * Cylinder(1.7, 20)

def templates(d):
    return [Template.face_of("bottom"), Template.slice("XY", 1.0, label=False)]
'''


def test_templates_hook_exports_with_every_variant(tmp_path):
    from b123d_print.project import export_variant, load, variants

    script = tmp_path / "parts" / "holder" / "holder.py"
    script.parent.mkdir(parents=True)
    script.write_text(HOOK)
    mod = load(script)
    for key in variants(mod):
        s = export_variant(mod, script, key, formats=["stl"])
        tag = "holder" + (f"_{key}" if key else "")
        assert set(s["templates"]) == {f"{tag}_template_face_bottom", f"{tag}_template_xy1"}
        assert s["templates"][f"{tag}_template_face_bottom"]["x"] == (40.0 if not key else 60.0)
    names = [rel for rel, _ in outdir.files(script.parent / "out")]
    assert names == ["README.md", "print/holder.stl", "print/holder_wide.stl",
                     "print/templates/holder_template_face_bottom.stl", "print/templates/holder_template_xy1.stl",
                     "print/templates/holder_wide_template_face_bottom.stl", "print/templates/holder_wide_template_xy1.stl"]


def test_cli_faces_and_template(tmp_path, capsys):
    from b123d_print.cli import main

    script = tmp_path / "parts" / "holder" / "holder.py"
    script.parent.mkdir(parents=True)
    script.write_text(HOOK)
    (tmp_path / "b123d-print.toml").write_text("")
    assert main(["--root", str(tmp_path), "faces", "holder", "--highlight", "bottom"]) == 0
    out = capsys.readouterr().out
    assert "bottom normal (0.0, 0.0, -1.0)" in out and "holes: d 3.4 at (-14.0, 0.0, 0.0), d 3.4 at (14.0, 0.0, 0.0)" in out
    assert (script.parent / "out" / "images" / "holder_face1.png").is_file()
    assert main(["--root", str(tmp_path), "template", "holder", "--crop", "14,0,2:10,10,10", "--formats", "3mf",
                 "--variant", "standard"]) == 0
    out = capsys.readouterr().out
    assert "holder_template_crop_14_0_2: 10.00 x 10.00 x 5.00 mm" in out
    assert (script.parent / "out" / "print" / "templates" / "holder_template_crop_14_0_2.3mf").is_file()
    with pytest.raises(SystemExit, match="misses the part"):
        main(["--root", str(tmp_path), "template", "holder", "--slice", "XY:20"])


def _settings():
    from b123d_print.config import Settings

    return Settings()


def test_base_plate_keeps_a_box_outline_and_its_screw_holes():
    """A slice through a box's walls and two standoffs with pilot holes: the plate fills the box's
    own outline (rounded corners stay rounded), the pilot holes stay open through it."""
    from build123d import RectangleRounded, extrude as ex

    outer = ex(RectangleRounded(40, 30, 4), 10)
    box = outer - Pos(0, 0, 2) * ex(RectangleRounded(34, 24, 1), 10)
    for x in (-10, 10):
        box += Pos(x, 0, 2) * Cylinder(3, 6, align=BED)
        box -= Pos(x, 0, 1) * Cylinder(1.2, 20, align=BED)
    m = tp.slice_template(box, "XY", 7.4, label=None)
    assert m.info["pieces"] == 3 and len(m.part.solids()) == 1 and m.part.is_valid
    bb = m.part.bounding_box()
    assert (round(bb.size.X, 3), round(bb.size.Y, 3)) == (40.0, 30.0)
    assert sorted(h[0] for h in round_holes(m.part)) == [2.4, 2.4]
    plate_area = sum(f.area for f in m.part.faces() if f.center().Z < 1e-6)
    assert plate_area == pytest.approx(ex(RectangleRounded(40, 30, 4), 1).volume - 2 * math.pi * 1.2 ** 2, rel=1e-3)
