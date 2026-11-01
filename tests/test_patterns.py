"""Pattern recipes (patterns.py) place the expected number of features, and the loop hint finds a
boolean on every pass of a for loop (loops.py) in a script, the build report and the diagnosis."""

import math
from pathlib import Path

import pytest
from build123d import Box, GeomType, Part, Pos, Vector

from b123d_print import diagnose, project
from b123d_print import patterns as P
from b123d_print import recipes as R
from b123d_print.loops import loop_booleans, loop_hint

ROOT = Path(__file__).resolve().parents[1]


def _holes(part, r):
    """Cylindrical faces of radius r (one per round hole through a plate)."""
    return [f for f in part.faces() if f.geom_type == GeomType.CYLINDER and abs(f.radius - r) < 1e-6]


def test_bolt_circle_count_radius_and_start_angle():
    c = P.bolt_circle(25, 6, 4.5, 5, start_angle=30, hole_comp=0.2)
    assert c.is_valid and len(c.solids()) == 6
    centers = sorted((round(math.degrees(math.atan2(s.center().Y, s.center().X))) % 360, round(math.hypot(s.center().X, s.center().Y), 6))
                     for s in c.solids())
    assert [a for a, _ in centers] == [30, 90, 150, 210, 270, 330]
    assert all(r == pytest.approx(25) for _, r in centers)
    assert c.solids()[0].bounding_box().size.X == pytest.approx(4.7)  # hole_d + hole_comp
    assert c.bounding_box().max.Z == pytest.approx(0) and c.bounding_box().min.Z == pytest.approx(-5)
    assert len(_holes(P.demo_bolt_circle(), 4.5 / 2)) == 6


def test_hole_grid_count_and_pitch():
    c = P.hole_grid(10, 8, 6, 4, 3.0, 3)
    assert len(c.solids()) == 24
    xs = sorted({round(s.center().X, 6) for s in c.solids()})
    ys = sorted({round(s.center().Y, 6) for s in c.solids()})
    assert xs == pytest.approx([-25, -15, -5, 5, 15, 25]) and ys == pytest.approx([-12, -4, 4, 12])
    assert len(_holes(P.demo_hole_grid(), 1.5)) == 24


def test_hex_grille_cells_web_and_border():
    cell, web = 6.0, 1.6
    c = P.hex_grille(68, 48, cell, web, 3)
    cells = c.solids()
    assert c.is_valid and len(cells) == 60
    bb = c.bounding_box()
    assert bb.max.X <= 34 + 1e-6 and bb.max.Y <= 24 + 1e-6 and bb.min.Z == pytest.approx(-3)
    # each cell is `cell` across the flats (along Y) and nearest neighbours are cell + web apart
    assert cells[0].bounding_box().size.Y == pytest.approx(cell)
    pts = [s.center() for s in cells]
    nearest = min((a - b).length for i, a in enumerate(pts) for b in pts[i + 1:])
    assert nearest == pytest.approx(cell + web)
    plate = P.demo_hex_grille()
    assert plate.is_valid and len(plate.faces()) == 6 + 6 * 60
    with pytest.raises(ValueError, match="no 6 mm cell fits"):
        P.hex_grille(5, 5, 6, 1, 3)
    with pytest.raises(ValueError, match="must be > 0"):
        P.hex_grille(50, 50, 6, 0, 3)


def test_slot_grille_count_web_and_pitch_guard():
    c = P.slot_grille(40, 3.0, 8, 6.0, 2.4)
    assert len(c.solids()) == 8
    ys = sorted(s.center().Y for s in c.solids())
    assert [b - a for a, b in zip(ys, ys[1:])] == pytest.approx([6.0] * 7)
    assert c.solids()[0].bounding_box().size.X == pytest.approx(40)
    assert c.bounding_box().max.Z == pytest.approx(0) and c.bounding_box().min.Z == pytest.approx(-2.4)
    with pytest.raises(ValueError, match="pitch 3 must be more"):
        P.slot_grille(40, 3.0, 8, 3.0, 2.4)


def test_grip_ridges_face_out_and_fuse():
    knob = P.demo_grip_ridges()
    assert knob.is_valid and len(knob.solids()) == 1
    # each ridge's outer face is flat, faces out (rotate=True) and stands ridge_h proud of r = 15
    outer = [f for f in knob.faces() if f.geom_type == GeomType.PLANE and abs(f.normal_at().Z) < 1e-6
             and math.hypot(f.center().X, f.center().Y) > 15.7]
    assert len(outer) == 24
    for f in outer:
        n, c = f.normal_at(), f.center()
        assert n.dot(Vector(c.X, c.Y, 0).normalized()) == pytest.approx(1, abs=1e-6)
    assert knob.bounding_box().size.X == pytest.approx(31.6)


def test_ribs_keep_their_old_positions():
    """ribs now uses GridLocations: the same ribs, at the same places, as the old loop."""
    span, height, count, t, pitch = 30, 4, 4, 2, 7
    old = Part()
    for i in range(count):
        old += Pos(0, (i - (count - 1) / 2) * pitch, 0) * Box(span, t, height, align=R.BED)
    new = R.ribs(span, height, count, t, pitch)
    assert len(new.solids()) == count and new.volume == pytest.approx(old.volume)
    assert sorted(s.center().Y for s in new.solids()) == pytest.approx(sorted(s.center().Y for s in old.solids()))
    assert len(R.ribs(10, 2).solids()) == 3


@pytest.mark.parametrize("name", ["bolt_circle", "hole_grid", "hex_grille", "slot_grille", "grip_ridges"])
def test_pattern_recipes_are_registered_with_their_imports(name):
    r = R.get(name)
    assert r.name == name and r.functions[0] is getattr(P, name)
    assert "Locations" in r.text() and "build123d import" in r.text()


# --- the loop hint ---------------------------------------------------------------------------

LOOPY = """
from build123d import Box, Cylinder, Pos


def build(d=None):
    p = Box(40, 40, 2)
    for x in range(3):
        p -= Pos(x * 10, 0, 0) * Cylinder(1, 5)
    for sx in (-1, 1):
        p += Pos(sx * 15, 0, 0) * Box(2, 2, 4)
    n = 0
    cuts = []
    for i in range(4):
        n += 1
        y = i * 2.0
        y += math.cos(i) * 2
        cuts += [Pos(0, y, 0) * Cylinder(1, 5)]
    return p - cuts
"""


def test_loop_booleans_finds_only_shape_booleans_in_loops():
    assert loop_booleans(LOOPY) == [8]  # not the pair, the counters, the numbers or the list
    assert loop_booleans("for i in range(3):\n    p &= Box(1, 1, 1)\n") == [2]
    assert loop_booleans("for sy in (-1, 1) if LIPS else ():\n    p += Box(1, 1, 1)\n") == []
    assert loop_booleans("for x in X:\n    for sx in (-1, 1):\n        p -= hole.moved(loc)\n") == [3]
    assert loop_booleans("p -= Box(1, 1, 1)\n") == [] and loop_booleans("def (:") == []
    hint = loop_hint(LOOPY)
    assert hint.startswith("line 8: a boolean on every pass") and "GridLocations" in hint
    assert loop_hint("x = 1\n") is None


def test_build_report_and_timeout_diagnosis_carry_the_loop_hint(tmp_path):
    script = tmp_path / "loopy.py"
    script.write_text(LOOPY.replace("from build123d", "import math\nfrom build123d"), encoding="utf-8")
    pc = project.Pieces(project.load(script), None)
    pc.parts()
    hints = pc.timing()["hints"]
    assert any(h.startswith("line 9: a boolean on every pass") for h in hints), hints
    diag = diagnose.from_result({"ok": False, "error": "timed out after 240 s", "log": ""}, script)
    assert any("a boolean on every pass" in f for f in diag["fixes"])
    plain = tmp_path / "plain.py"
    plain.write_text("from build123d import Box\n\n\ndef build(d=None):\n    return Box(1, 1, 1)\n", encoding="utf-8")
    pc = project.Pieces(project.load(plain), None)
    pc.parts()
    assert pc.timing()["hints"] == []


def test_examples_place_repeated_features_in_one_boolean():
    """The shipped examples are what models copy: none does a boolean on every pass of a loop."""
    found = {f.relative_to(ROOT).as_posix(): loop_booleans(f.read_text(encoding="utf-8"))
             for f in sorted((ROOT / "src/b123d_print/examples").glob("*/*.py"))}
    assert not {k: v for k, v in found.items() if v}


def test_patterns_guide_code_runs():
    """Every python block on docs/using/patterns.md runs against the pinned build123d: the
    signatures and behaviour the guide states are the ones a part script gets."""
    import re

    text = (ROOT / "docs/using/patterns.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(blocks) >= 3
    for code in blocks:
        exec(compile(code, "patterns.md", "exec"), {})
