"""Multi-body parts (issue #167): bodies(), the multi-colour 3MF (one object, a named, coloured part
per body, in order), STEP/STL/cache round trips, the Bodies check and the print sheet."""

import types
import zipfile
from pathlib import Path

import pytest
from build123d import Align, Box, Color, Compound, Mesher, Pos, import_step

import b123d_print
from b123d_print import checks as ck
from b123d_print import printsheet, project
from b123d_print.bodies import bodies, printable, split
from b123d_print.config import Settings
from b123d_print.project import CacheConfig, ReadLog, load, make_pieces
from b123d_print.recipes import inlay, text_label
from b123d_print.render import export_files

BED = (Align.CENTER, Align.CENTER, Align.MIN)


def tag():
    """A 40 x 20 x 3 plate with a 0.6 mm flush text inlay, plus a third body on top of it."""
    plate = Box(40, 20, 3, align=BED)
    t = inlay(plate, Pos(0, 0, 2.4) * text_label("AB", size=8, depth=1.6), color="white", base_color="#2b5fa8")
    base, text = (b for b, _, _ in split(t))
    dot = Pos(15, 6, 3) * Box(4, 4, 1, align=BED)
    return bodies(base=(base, "#2b5fa8"), text=(text, "white"), dot=(dot, (1, 0, 0)))


def test_bodies_names_colours_and_order():
    t = tag()
    got = split(t)
    assert [n for _, _, n in got] == ["base", "text", "dot"]
    assert tuple(got[1][1]) == pytest.approx((1, 1, 1, 1)) and tuple(got[2][1]) == pytest.approx((1, 0, 0, 1))
    assert split(Box(1, 1, 1)) is None
    u = printable(t)
    assert len(u.solids()) == 1 and u.volume == pytest.approx(40 * 20 * 3 + 16, rel=1e-6)  # one print: the union
    moved = Pos(5, 0, 0) * t  # survives a move into print orientation
    assert [n for _, _, n in split(moved)] == ["base", "text", "dot"]
    plain = Box(2, 2, 2)
    bodies(a=plain, b=Pos(2, 0, 0) * Box(2, 2, 2))
    assert plain.label == "" and plain.color is None  # the caller's shapes are not relabelled


@pytest.mark.parametrize("bad, match", [
    (dict(a=Box(1, 1, 1)), "two or more"),
    (dict(a=Box(1, 1, 1), **{"b c": Box(1, 1, 1)}), "letters, digits"),
    (dict(a=Box(1, 1, 1), b=(Box(1, 1, 1), "not-a-colour")), "not a build123d Color"),
])
def test_bodies_rejects_bad_input(bad, match):
    with pytest.raises(ValueError, match=match):
        bodies(**bad)


def test_3mf_is_one_object_with_named_parts_in_order(tmp_path):
    t = tag()
    f = export_files(t, tmp_path, "tag", ["3mf"])[0]
    m = Mesher()
    shapes = m.read(str(f))
    assert [s.label for s in shapes] == ["base", "text", "dot"]
    for s, (b, c, _) in zip(shapes, split(t)):
        assert s.volume == pytest.approx(b.volume, rel=0.01)
        assert tuple(s.color) == pytest.approx(tuple(c), abs=0.01)
    items = m.model.GetBuildItems()
    assert items.Count() == 1  # one object on the plate ...
    items.MoveNext()
    obj = items.GetCurrent().GetObjectResource()
    assert obj.IsComponentsObject() and obj.GetName() == "tag"
    comps = m.model.GetComponentsObjectByID(obj.GetResourceID())
    names = [comps.GetComponent(i).GetObjectResource().GetName() for i in range(comps.GetComponentCount())]
    assert names == ["base", "text", "dot"]  # ... made of one part per body, in order
    xml = zipfile.ZipFile(f).read("3D/3dmodel.model").decode()
    assert 'name="text #ffffff"' in xml  # the material is named by its body


def test_single_body_3mf_unchanged(tmp_path):
    f = export_files(Box(10, 10, 10), tmp_path, "box", ["3mf"])[0]
    m = Mesher()
    shapes = m.read(str(f))
    assert len(shapes) == 1 and shapes[0].volume == pytest.approx(1000, rel=1e-3)
    assert m.model.GetBuildItems().Count() == 1


def test_step_stl_png_glb(tmp_path):
    t = tag()
    files = export_files(t, tmp_path, "tag", ["step", "stl", "png", "glb"])
    assert [p.name for p in files] == ["tag.step", "tag.stl", "tag_base.stl", "tag_text.stl", "tag_dot.stl", "tag.png", "tag.glb"]
    back = import_step(tmp_path / "tag.step")
    assert [(c.label, tuple(c.color)[:3]) for c in back.children] == [
        ("base", pytest.approx(tuple(Color("#2b5fa8"))[:3], abs=0.01)),
        ("text", pytest.approx((1, 1, 1), abs=0.01)),
        ("dot", pytest.approx((1, 0, 0), abs=0.01))]
    union = Mesher().read(str(tmp_path / "tag.stl"))
    assert len(union) == 1 and union[0].volume == pytest.approx(printable(t).volume, rel=0.01)
    text = Mesher().read(str(tmp_path / "tag_text.stl"))[0]
    assert text.volume == pytest.approx(split(t)[1][0].volume, rel=0.02)


def test_bodies_check():
    s = Settings()
    found = ck.Bodies("tag").run({"tag": tag()}, None, s)
    assert [f.level for f in found] == [ck.OK] and "3 bodies" in found[0].message
    plate = Box(40, 20, 3, align=BED)
    text = Pos(0, 0, 2.4) * text_label("AB", size=8, depth=0.6)
    overlapping = bodies(base=plate, text=text)  # no pocket: the text sits inside the plate
    found = ck.Bodies("tag").run({"tag": overlapping}, None, s)
    assert [(f.level, f.target) for f in found if f.level != ck.OK] == [(ck.FAIL, "tag: base / text")]
    assert found[0].data["volume"] == pytest.approx(text.volume, rel=1e-3)
    floating = bodies(base=plate, lid=Pos(0, 0, 4) * Box(5, 5, 1, align=BED))
    found = ck.Bodies("tag").run({"tag": floating}, None, s)
    assert [f.level for f in found] == [ck.WARN, ck.WARN] and "touches no other body" in found[0].message
    thin = bodies(base=plate, line=Pos(0, 0, 3) * Box(30, 0.3, 0.6, align=BED))
    found = ck.Bodies("tag").run({"tag": thin}, None, s)
    assert [f.level for f in found] == [ck.WARN] and "under one line width" in found[0].message
    assert ck.Bodies("p").run({"p": plate}, None, s) == []  # not multi-body: nothing to say


def test_checks_run_on_the_union():
    mod = types.ModuleType("tagmod")
    mod.build = tag
    found = project.run_checks(mod, "", Settings(), nudge=False)
    by = {}
    for f in found:
        by.setdefault(f.check, []).append(f)
    assert not [f.line() for f in found if f.level == ck.FAIL]
    assert by["bodies"][0].level == ck.OK
    assert "gap" not in by  # the union is one solid: no gap check between bodies that touch on purpose
    assert all(f.level == ck.OK for f in by["overhang"])  # the inlay's floor is not an overhang


def test_print_sheet_lists_the_bodies():
    mod = types.ModuleType("tagmod")
    mod.build = tag
    text = printsheet.sheet(mod, None, {"": tag()}, Settings(), "tag")
    assert "## Bodies (multi-colour)" in text
    rows = [ln for ln in text.splitlines() if ln.startswith("| part |")]
    assert [r.split("|")[2].strip() for r in rows[1:]] == ["base", "text", "dot"]
    assert "one object with 3 parts (base, text, dot) in `tag.3mf`" in text
    assert "about 3 layer(s)" in text  # the text is 0.6 mm deep
    plain = printsheet.sheet(mod, None, {"": Box(10, 10, 10)}, Settings(), "box")
    assert "Bodies" not in plain


CACHED = '''\
from build123d import Align, Box, Pos

from b123d_print import bodies

CALLS = []


def build(d=None):
    CALLS.append("build")
    plate = Box(20, 10, 3, align=(Align.CENTER, Align.CENTER, Align.MIN))
    dot = Pos(0, 0, 2) * Box(4, 4, 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return {"tag": lambda: bodies(base=(plate - dot, "#2b5fa8"), dot=(dot, "white"))}
'''


def test_build_cache_keeps_the_bodies(tmp_path):
    ws = tmp_path
    (ws / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    script = ws / "parts" / "tagc" / "tagc.py"
    script.parent.mkdir(parents=True)
    script.write_text(CACHED, encoding="utf-8")

    def pieces():
        mod = load(script)
        return make_pieces(mod, "", project.dims(mod, ""), b123d_print.load_settings(script), CacheConfig(ws, ReadLog(), False))

    first = pieces().part("tag")
    pc = pieces()
    again = pc.part("tag")
    assert pc.stats["tag"]["cached"] and pc.mod.CALLS == []
    assert [(n, tuple(c)) for _, c, n in split(again)] == [(n, tuple(c)) for _, c, n in split(first)]
    assert [b.volume for b, _, _ in split(again)] == pytest.approx([b.volume for b, _, _ in split(first)])


def test_inlay_example_builds_and_passes_check():
    script = Path(b123d_print.__file__).parent / "examples" / "inlay_tag" / "inlay_tag.py"
    mod = load(script)
    for key in project.variants(mod):
        found = project.run_checks(mod, key, Settings(), nudge=False)
        assert not [f.line() for f in found if f.level == ck.FAIL]
        assert [f.level for f in found if f.check == "bodies"] == [ck.OK]
        part = project.printables(mod, project.dims(mod, key))[""]
        assert [n for _, _, n in split(part)] == ["tag", "text"]


@pytest.mark.parametrize("labels", [("../../x", "y"), ("Base plate", "lid/top"), ("a", "a"), ("a\n", "b"), ("ok", "")])
def test_a_compound_with_other_labels_is_not_multi_body(tmp_path, labels):
    """An ordinary labelled assembly (or a hostile label) is one part: no body files, nothing outside out/."""
    a, b = Box(10, 10, 3, align=BED), Pos(0, 0, 3) * Box(4, 4, 1, align=BED)
    a.label, b.label = labels
    c = Compound(children=[a, b])
    assert split(c) is None and printable(c) is c
    out = tmp_path / "ws" / "out"
    files = export_files(c, out, "part", ["stl", "3mf"])
    assert [p.name for p in files] == ["part.stl", "part.3mf"]
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "ws/out/part.3mf", "ws/out/part.stl"]
    assert len(Mesher().read(str(out / "part.3mf"))) == 2  # Mesher's own handling, as before #167
    assert ck.Bodies("p").run({"p": c}, None, Settings()) == []


def test_stl_files_and_cache_note_refuse_a_bad_name():
    from b123d_print.bodies import stl_files
    from b123d_print.project import _with_bodies

    t = tag()
    split(t)[1][0].label = "../x"  # changed after bodies(): split refuses it, so nothing is written for it
    assert [n for n, _ in stl_files(t, "tag")] == ["tag.stl"]
    notes = [{"type": "Part", "label": "../x", "color": None}, {"type": "Part", "label": "b", "color": None}]
    assert _with_bodies(t, notes) is None
