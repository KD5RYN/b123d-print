"""Sketch first: the sketches(d) hook, the sketch checks, the picture, the CLI and the worker op."""

from pathlib import Path

import pytest
from build123d import Circle, Plane, Polyline, Pos, Rectangle, Sketch, make_face

from b123d_print import sandbox
from b123d_print import sketch as skt
from b123d_print.cli import main, new_part
from b123d_print.config import Settings
from b123d_print.project import dims, load, printables
from b123d_print.recipes import rounded_outline, slot

EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "b123d_print" / "examples" / "sketch_bracket" / "sketch_bracket.py"


def levels(findings) -> dict:
    return {f.check: f.level for f in findings}


def test_bracket_features_and_checks():
    s = rounded_outline([(0, 0), (60, 0), (60, 12), (12, 12), (12, 40), (0, 40)], [2, 2, 2, 4, 2, 2])
    s -= Pos(50, 6) * Circle(1.7)
    s -= slot((20, 6), (35, 6), 3.4)
    f = skt.features(s)
    assert f["size"] == [60, 40] and f["min"] == [0, 0] and f["axes"] == "XY"
    assert f["holes"] == [{"d": 3.4, "center": [50, 6]}]
    assert len(f["slots"]) == 1 and f["slots"][0]["width"] == 3.4 and f["slots"][0]["length"] == 15
    assert sorted(map(tuple, f["slots"][0]["centers"])) == [(20, 6), (35, 6)]
    assert sorted(a["r"] for a in f["arcs"] if a["inside"]) == [4.0]
    assert sorted(a["r"] for a in f["arcs"] if not a["inside"]) == [2.0] * 5
    assert f["sharp_inside"] == []
    found = skt.check(s, Settings(), "outline", f)
    assert levels(found) == {"region": "ok", "neck": "ok", "corners": "ok"}
    neck = next(x for x in found if x.check == "neck")
    assert neck.data["min"] == pytest.approx(6 - 1.7, abs=0.05)  # hole edge to the bottom edge


def test_sharp_and_tight_inside_corners_warn():
    sharp = rounded_outline([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)], [1, 1, 1, 0, 1, 1])
    f = skt.check(sharp, Settings())
    c = next(x for x in f if x.check == "corners")
    assert c.level == "warn" and c.data["sharp"] == [[10, 10]]
    tight = rounded_outline([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)], [1, 1, 1, 0.3, 1, 1])
    c = next(x for x in skt.check(tight, Settings()) if x.check == "corners")
    assert c.level == "warn" and [t["r"] for t in c.data["tight"]] == [0.3] and not c.data["sharp"]
    # a rectangular cutout's corners are inside corners too
    cut = Sketch() + Rectangle(40, 30) - Rectangle(10, 10)
    c = next(x for x in skt.check(cut, Settings()) if x.check == "corners")
    assert c.level == "warn" and len(c.data["sharp"]) == 4


def test_neck_small_hole_regions_and_open_outline():
    weak = Sketch() + Rectangle(40, 10) - Pos(0, 2.9) * Rectangle(4, 5.2) - Pos(0, -2.9) * Rectangle(4, 5.2)
    n = next(x for x in skt.check(weak, Settings()) if x.check == "neck")
    assert n.level == "warn" and n.data["min"] == pytest.approx(0.6, abs=0.02)  # a line width < 0.6 < min_wall
    thin = Sketch() + Rectangle(40, 10) - Pos(0, 2.8) * Rectangle(4, 5.4) - Pos(0, -2.8) * Rectangle(4, 5.4)
    n = next(x for x in skt.check(thin, Settings()) if x.check == "neck")
    assert n.level == "fail" and n.data["min"] == pytest.approx(0.2, abs=0.02)  # under one line width
    holes = Sketch() + Rectangle(20, 20) - Circle(0.4)
    h = next(x for x in skt.check(holes, Settings()) if x.check == "holes")
    assert h.level == "warn" and h.data["small"][0]["d"] == 0.8
    two = Sketch() + Rectangle(10, 10) + Pos(30, 0) * Rectangle(10, 10)
    assert levels(skt.check(two, Settings()))["region"] == "fail"
    opened = Polyline((0, 0), (20, 0), (20, 10))
    r = skt.check(opened, Settings())
    assert [x.level for x in r] == ["fail"] and "open" in r[0].message
    closed = Polyline((0, 0), (20, 0), (20, 10), close=True)
    assert "make_face" in skt.check(closed, Settings())[0].message


def test_profile_on_xz_reads_in_its_own_plane():
    profile = Plane.XZ * (Sketch() + Pos(15, 10) * Rectangle(10, 20))  # a revolve profile: radius 10..20, z 0..20
    f = skt.features(profile)
    assert f["axes"] == "XZ" and f["size"] == [10, 20]
    assert f["min"] == [10, 0]


def test_rounded_outline_refuses_radii_that_do_not_fit():
    with pytest.raises(ValueError, match="point 1 .* point 2"):
        rounded_outline([(0, 0), (10, 0), (10, 5), (0, 5)], 3)
    with pytest.raises(ValueError, match="one per point"):
        rounded_outline([(0, 0), (10, 0), (10, 5)], [1, 1])
    sq = rounded_outline([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert sq.area == pytest.approx(100)
    assert slot((0, 0), (0, 0), 4).area == pytest.approx(3.14159 * 4, rel=1e-4)


def test_render_marks_findings(tmp_path):
    s = rounded_outline([(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)], [1, 1, 1, 0, 1, 1]) - Pos(5, 5) * Circle(0.4)
    found = skt.check(s, Settings())
    png = skt.render_sketch(s, tmp_path / "s.png", "s", found)
    assert png.is_file() and png.stat().st_size > 10_000
    assert skt.render_sketch(s, tmp_path / "plain.png", "s", dims=False).is_file()


def test_example_sketch_is_what_build_extrudes():
    mod = load(EXAMPLE)
    for key in ("", "long"):
        d = dims(mod, key)
        sk = skt.Sketches(mod, d)
        assert sk.names() == ["outline"]
        outline = sk.get()
        f = skt.features(outline)
        part = printables(mod, d)[""]
        bb = part.bounding_box()
        assert part.is_valid and bb.min.Z == pytest.approx(0, abs=1e-6)
        assert (bb.size.X, bb.size.Y) == pytest.approx(tuple(f["size"]), abs=1e-3)
        assert bb.size.Z == pytest.approx(d.THICK)
        assert all(x.level == "ok" for x in skt.check(outline, Settings()))


def test_lazy_sketches_and_missing_hook():
    made = []

    class Mod:
        @staticmethod
        def sketches(d):
            return {"a": lambda: made.append("a") or Sketch() + Rectangle(5, 5),
                    "b": lambda: made.append("b") or Sketch() + Circle(3)}

    sk = skt.Sketches(Mod, 1)
    sk.get("b")
    sk.get("b")
    assert made == ["b"]
    with pytest.raises(skt.SketchError, match="no sketch 'c'"):
        sk.get("c")
    with pytest.raises(skt.SketchError, match="no sketches"):
        skt.Sketches(object(), None)


@pytest.mark.parametrize("key", ["../x", "a/b", "two words", "", "-lead", "x" * 41, 3, "a\n"])
def test_bad_sketch_names_are_refused(key):
    class Mod:
        @staticmethod
        def sketches(d):
            return {"ok": Sketch() + Rectangle(5, 5), key: Sketch() + Circle(3)}

    with pytest.raises(skt.SketchError, match="bad sketch name") as e:
        skt.Sketches(Mod, 1)
    assert repr(key) in str(e.value) and "'ok'" not in str(e.value)
    good = {"outline", "a-1", "B_2", "x" * 40}

    class Fine:
        @staticmethod
        def sketches(d):
            return {k: Sketch() + Rectangle(5, 5) for k in good}

    assert set(skt.Sketches(Fine, 1).names()) == good


def test_cli_new_sketch_and_sketch_command(tmp_path, monkeypatch, capsys):
    (tmp_path / "b123d-print.toml").write_text("", encoding="utf-8")
    p = new_part(tmp_path, "parts", "plate", sketch_first=True)
    code = p.read_text(encoding="utf-8")
    assert "def sketches(d" in code and "rounded_outline" in code
    monkeypatch.chdir(tmp_path)
    assert main(["sketch", "plate"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("sketch outline (sketches: outline)")
    assert [ln[7:].split()[0] for ln in lines if ln.startswith("[")] == ["region", "neck", "corners"]
    assert (tmp_path / "parts/plate/out/images/plate_sketch_outline.png").is_file()
    new_part(tmp_path, "parts", "boxy")
    with pytest.raises(SystemExit, match="no sketches"):
        main(["sketch", "boxy"])


def test_worker_sketch_op(tmp_path):
    script = tmp_path / "parts" / "sb" / "sb.py"
    script.parent.mkdir(parents=True)
    script.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    res = sandbox.run_job({"op": "sketch", "script": str(script), "sketch": "outline", "size": "small"}, tmp_path,
                          script.parent / "out", 120)
    assert res["ok"], res.get("error", "") + res.get("traceback", "")
    assert res["sketch"] == "outline" and res["variant"] == "standard"
    assert Path(res["image"]).name == "sb_sketch_outline_small.png" and Path(res["image"]).is_file()
    assert [f["check"] for f in res["findings"]] == ["region", "neck", "corners"]
    assert res["features"]["inside_radii"] == [5.0] and len(res["features"]["holes"]) == 2
    bad = sandbox.run_job({"op": "sketch", "script": str(script), "sketch": "nope"}, tmp_path, script.parent / "out", 60)
    assert not bad["ok"] and bad.get("usage_error") and "no sketch 'nope'" in bad["error"]
