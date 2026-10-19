"""Print orientation (suggest_orientation) and the tip-over check, on shapes whose answer is known."""

import math

import numpy as np
import pytest
from build123d import Align, Box, Cylinder, Pos, Rot

from b123d_print import checks as ck
from b123d_print import orient
from b123d_print.checks import TipOver
from b123d_print.config import Settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)
S = Settings()


def l_bracket():  # a 60 x 40 x 4 leg on the bed and a 4 x 40 x 50 upright: lying as an L
    return Box(60, 40, 4, align=BED) + Pos(-28, 0, 0) * Box(4, 40, 50, align=BED)


def on_bed(p):
    return Pos(0, 0, -p.bounding_box().min.Z) * p


def mushroom():  # a d 8 stem 30 tall under a d 30 cap: upright, the cap overhangs all round
    return Cylinder(4, 30, align=BED) + Pos(0, 0, 30) * Cylinder(15, 6, align=BED)


def ranked(part, **kw):
    res, best = orient.suggest(part, S, **kw)
    return res["candidates"], best


# --- tip-over ----------------------------------------------------------------------------------


def run(part, **kw):
    return TipOver("", **kw).run({"part": part}, None, S)


def test_tall_thin_post_warns_and_a_block_does_not():  # BP-B6
    post = Cylinder(3, 60, align=BED)
    f = run(post)[0]
    assert f.level == "warn" and f.check == "tip-over"
    assert "brim" in f.message and "suggest_orientation" in f.message
    assert f.data["ratio"] == pytest.approx(10, rel=0.02) and f.data["width"] == pytest.approx(6, abs=0.05)
    assert run(Box(40, 40, 20, align=BED))[0].level == "ok"
    assert run(Cylinder(3, 8, align=BED))[0].level == "ok"  # under 10 mm: not checked
    assert run(post, speed=20)[0].level == "ok"  # a slow printer: the estimate scales with speed
    assert TipOver("").run({"part": post}, None, Settings(tip_speed=0)) == []  # off


def test_footprint_is_orcaslicers_auto_brim_measure():
    """Square post a x a x H: I = a^4 / 12 about either axis, W = a, so the estimate is
    speed x H^2 x 12 / (1920 a^3), whichever way the post is turned on the bed."""
    a, h = 10.0, 80.0
    want = 200 * h * h * 12 / (1920 * a ** 3)
    for turn in (0, 30):
        f = run(Rot(0, 0, turn) * Box(a, a, h, align=BED))[0]
        assert f.data["brim"] == pytest.approx(want, rel=0.02)
        assert f.data["width"] == pytest.approx(a, rel=0.01) and f.data["area"] == pytest.approx(a * a, rel=0.01)
    assert f.level == "warn"  # 8 mm: over 5; 60 mm tall (4.5 mm) would pass


def test_tip_over_strip_and_centre_of_mass():
    fin = Box(60, 1.6, 30, align=BED)  # stands on a 1.6 mm strip: area / perimeter 0.78 < 1.1
    assert "strip" in run(fin)[0].message
    leaning = Box(4, 30, 4, align=BED) + Pos(30, 0, 4) * Box(60, 30, 20, align=BED)  # a slab on a small foot at one end
    f = run(leaning)[0]
    assert f.level == "warn" and "centre of mass is outside" in f.message


def test_tip_over_is_automatic():
    from types import SimpleNamespace

    from b123d_print.project import check_specs

    specs = check_specs(SimpleNamespace(), None, {"part": Box(1, 1, 1)}, None)
    assert any(isinstance(s, TipOver) for s in specs)


# --- orientation -------------------------------------------------------------------------------


def test_rotation_puts_the_named_side_on_the_bed():
    """For every candidate, Rot(x, y, z) as reported turns its `down` side to -Z (build123d's Rot is
    intrinsic XYZ), and the turned part sits on the bed."""
    part = l_bracket()
    mesh_pts = orient.M.Mesh(part).tri.reshape(-1, 3)
    for c in orient.candidates(part, mesh_pts):
        probe = Pos(*(c.down * 10)) * Box(0.01, 0.01, 0.01)
        p = (Rot(*c.rot) * probe).center()
        assert (p.X, p.Y, p.Z) == pytest.approx((0, 0, -10), abs=0.02), (c.down, c.rot)
    from scipy.spatial.transform import Rotation

    for d in np.random.default_rng(0).normal(size=(20, 3)):
        d = d / np.linalg.norm(d)
        r = orient._rotation_to_down(d)
        assert r.apply(d) == pytest.approx([0, 0, -1], abs=1e-9)
        again = Rotation.from_euler("XYZ", orient.rot_angles(r), degrees=True)  # the rounded angles
        assert again.apply(d) == pytest.approx([0, 0, -1], abs=1e-3)


def test_l_bracket_lies_down_not_on_its_thin_edge():
    """Stood on the 4 x 40 end of its leg, the bracket is turned: the top choice lies on its
    back or side (contact well over the 160 mm^2 edge), and the thin-edge orientations rank last."""
    edge = on_bed(Rot(0, 90, 0) * l_bracket())  # the leg's 4 x 40 end on the bed
    rows, best = ranked(edge)
    top = rows[0]
    assert top["rot"] != [0.0, 0.0, 0.0]
    assert top["contact_mm2"] > 400 and top["supports_mm2"] < 1
    assert best.bounding_box().min.Z == pytest.approx(0, abs=1e-6)
    as_modeled = next(r for r in rows if r["source"] == "as modeled")
    assert as_modeled["contact_mm2"] == pytest.approx(160, rel=0.02)
    assert as_modeled["rank"] > len(rows) - 3
    assert any("tip-over" in n for n in as_modeled["notes"]) or as_modeled["supports_mm2"] > 100


def test_l_bracket_as_l_stays():
    rows, _ = ranked(l_bracket())
    assert rows[0]["rot"] == [0.0, 0.0, 0.0] and rows[0]["source"] == "as modeled"
    assert "already in the best orientation" in orient.text("l", {"candidates": rows, "load": None,
                                                                   "assumed_load": None, "up": "+Z"})


def test_tall_post_is_laid_down():
    rows, _ = ranked(Cylinder(3, 60, align=BED))
    assert rows[0]["height"] == pytest.approx(6, abs=0.1)
    standing = [r for r in rows if r["height"] > 50]
    assert standing and all(any("tip-over" in n for n in r["notes"]) for r in standing)


def test_mushroom_is_flipped():
    rows, best = ranked(mushroom())
    assert rows[0]["down"] == "+Z" and rows[0]["rot"] == [180.0, 0.0, 0.0]
    assert rows[0]["supports_mm2"] < 1
    upright = next(r for r in rows if r["source"] == "as modeled")
    assert upright["supports_mm2"] > 500  # under the cap
    assert best.bounding_box().max.Z == pytest.approx(36, abs=0.01)


def test_load_direction_changes_the_ranking():
    """DS-T1: as modeled the L wins; with the load along Z (across the layers as modeled) the
    winner turns the load into the layers."""
    plain, _ = ranked(l_bracket())
    loaded, _ = ranked(l_bracket(), load="along Z")
    assert plain[0]["source"] == "as modeled"
    assert loaded[0]["source"] != "as modeled"
    assert "load along the layers" in loaded[0]["notes"]
    modeled = next(r for r in loaded if r["source"] == "as modeled")
    assert "load 90 deg out of the layers" in modeled["notes"]


def test_structural_style_assumes_the_long_axis():
    beam = Box(10, 10, 80, align=BED)  # standing: its long axis across the layers
    rows, _ = ranked(beam, style="structural")
    assert rows[0]["height"] == pytest.approx(10, abs=0.1)
    assert any("long axis" in n and "along the layers" in n for n in rows[0]["notes"])


@pytest.mark.parametrize("text,want", [("X", (1, 0, 0)), ("-y", (0, 1, 0)), ("along Z", (0, 0, 1)), ("x axis", (1, 0, 0)),
                                       ("XZ", (1 / math.sqrt(2), 0, 1 / math.sqrt(2))), ("1,0,1", (1 / math.sqrt(2), 0, 1 / math.sqrt(2))),
                                       ("(0, 2, 0)", (0, 1, 0))])
def test_parse_load(text, want):
    assert orient.parse_load(text) == pytest.approx(want)


def test_parse_load_rejects_and_empty():
    assert orient.parse_load("") is None and orient.parse_load(None) is None
    for bad in ("sideways", "0,0,0", "along W"):
        with pytest.raises(ValueError):
            orient.parse_load(bad)


def test_hull_faces_of_a_wedge():
    """A wedge rests on its slope too: the hull gives its five flat faces, the slope among them."""
    from build123d import Polygon, extrude

    wedge = extrude(Polygon((0, 0), (40, 0), (0, 20), align=None), 30)
    faces = orient.hull_faces(orient.M.Mesh(wedge).tri.reshape(-1, 3))
    assert len(faces) == 5
    slope = np.array([1, 2, 0]) / math.sqrt(5)
    assert any(float(n @ slope) > 0.999 for n, _ in faces)
    assert sum(a for _, a in faces) == pytest.approx(wedge.area, rel=0.01)


def test_text_says_how_to_apply():
    rows, _ = ranked(mushroom())
    t = orient.text("mush", {"candidates": rows, "load": None, "assumed_load": None, "up": "+Z"})
    assert "p = Rot(180, 0, 0) * p" in t and "Pos(0, 0, -p.bounding_box().min.Z)" in t
    assert "UP +Z becomes -Z" in t and 'frame="print"' in t


def test_cli_orient(tmp_path, monkeypatch, capsys):
    from b123d_print.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "b123d-print.toml").write_text("[workspace]\nparts_dir = \"parts\"\n", encoding="utf-8")
    d = tmp_path / "parts" / "mush"
    d.mkdir(parents=True)
    (d / "mush.py").write_text(
        "from build123d import Align, Cylinder, Pos\n"
        "BED = (Align.CENTER, Align.CENTER, Align.MIN)\n"
        "part = Cylinder(4, 30, align=BED) + Pos(0, 0, 30) * Cylinder(15, 6, align=BED)\n", encoding="utf-8")
    assert main(["orient", "mush", "--image"]) == 0
    out = capsys.readouterr().out
    assert "Rot(180, 0, 0)" in out and (d / "out" / "mush_orient.png").is_file()
    assert main(["orient", "mush", "--json", "--load", "X"]) == 0
    import json

    res = json.loads(capsys.readouterr().out)
    assert res[0]["load"] == [1.0, 0.0, 0.0] and res[0]["candidates"][0]["rank"] == 1
