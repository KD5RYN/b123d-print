"""Motion clearance (b123d_print.motion): Motion and Slide sweep a piece of assembly(d)."""

import math
from dataclasses import replace
from pathlib import Path

import pytest
from build123d import Align, Box, Pos

from b123d_print import Motion, Slide
from b123d_print.checks import FAIL, OK
from b123d_print.config import Settings

MIN = (Align.MIN, Align.MIN, Align.MIN)
EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "b123d_print" / "examples"


def block(lo, size):
    return Pos(*lo) * Box(*size, align=MIN)


# A lid 30 mm deep, hinged along X at its back bottom edge (the origin), over a box whose top is
# 0.5 mm below it. It opens toward +Z: axis_dir -X turns -Y up.
LID = block((-20, -30, 0), (40, 30, 3))
BASE = block((-20, -30, -20), (40, 30, 19.5))
# a shelf above the lid, low enough that the lid's top far corner reaches it at 60 deg:
# that corner, (y, z) = (-30, 3), turned 60 deg is at z = 30 sin 60 + 3 cos 60
SHELF_Z = 30 * math.sin(math.radians(60)) + 3 * math.cos(math.radians(60))
SHELF = block((-20, -40, SHELF_Z), (40, 35, 5))


def lid_motion(**kw):
    return Motion("lid", axis_point=(0, 0, 0), axis_dir=(-1, 0, 0), start_deg=0, end_deg=110, **kw)


def run(spec, asm):
    found = spec.run({}, [(p, None, lbl) for lbl, p in asm.items()], Settings())
    assert len(found) == 1
    return found[0]


def test_lid_clears_through_0_to_110():
    f = run(lid_motion(), {"lid": LID, "box": BASE})
    assert f.level == OK, f.line()
    # past 90 deg the lid's back face swings down behind the hinge, toward the box's back top
    # edge: at 110 deg the gap is 0.5 cos 20 deg, less than the 0.5 when closed
    assert f.data["min_clearance"] == pytest.approx(0.5 * math.cos(math.radians(20)), abs=0.005)
    assert f.data["min_at"] == pytest.approx(110, abs=0.1)
    assert run(replace(lid_motion(), end_deg=90), {"lid": LID, "box": BASE}).data["min_clearance"] == pytest.approx(0.5, abs=0.005)
    assert f.data["min_pair"] == ["lid", "box"]
    assert "first_contact" not in f.data


def test_lid_corner_hits_the_shelf_at_60_deg():
    f = run(lid_motion(), {"lid": LID, "box": BASE, "shelf": SHELF})
    assert f.level == FAIL
    assert f.data["first_contact"] == pytest.approx(60, abs=0.5)
    assert f.data["first_pair"] == ["lid", "shelf"]
    assert f.data["volume"] > 1
    assert "lid hits shelf at 60" in f.message
    # against= leaves the shelf out: clear again
    assert run(lid_motion(against=("box",)), {"lid": LID, "box": BASE, "shelf": SHELF}).level == OK
    # a smaller range stops short of it, with the closest approach at the end
    f = run(replace(lid_motion(against=("shelf",)), end_deg=55), {"lid": LID, "box": BASE, "shelf": SHELF})
    assert f.level == OK and f.data["min_pair"] == ["lid", "shelf"] and f.data["min_at"] == pytest.approx(55, abs=0.1)


def test_rotating_bar_known_minimum_clearance():
    """A bar 10 mm long (2 wide) turned about Z past a block 11 mm out: its corner (radius
    sqrt(101)) comes closest, 11 - sqrt(101) = 0.950 mm, at 90 - atan(1/10) = 84.29 deg (or the
    other corner at 95.71)."""
    bar = block((0, -1, 0), (10, 2, 2))
    post = block((-1, 11, 0), (2, 2, 2))
    f = run(Motion("bar", (0, 0, 0), (0, 0, 1), 0, 180), {"bar": bar, "post": post})
    assert f.level == OK
    assert f.data["min_clearance"] == pytest.approx(11 - math.sqrt(101), abs=0.01)
    assert min(abs(f.data["min_at"] - 84.29), abs(f.data["min_at"] - 95.71)) < 1.0
    # min_clearance above it fails, below it passes
    assert run(Motion("bar", (0, 0, 0), (0, 0, 1), 0, 180, min_clearance=1.0), {"bar": bar, "post": post}).level == FAIL
    assert run(Motion("bar", (0, 0, 0), (0, 0, 1), 0, 180, min_clearance=0.9), {"bar": bar, "post": post}).level == OK


def test_collision_between_coarse_samples_is_found():
    """A thin post the bar's tip passes through between two coarse samples."""
    bar = block((0, -0.5, 0), (10, 1, 2))
    post = block((-0.2, 8, 0), (0.4, 0.4, 2))  # 0.4 mm wide at 8 mm: about 3 deg of the turn
    f = run(Motion("bar", (0, 0, 0), (0, 0, 1), 0, 180, samples=7), {"bar": bar, "post": post})
    assert f.level == FAIL
    assert f.data["first_contact"] == pytest.approx(90 - math.degrees(math.atan2(0.2 + 0.5, 8)), abs=0.5)


def test_slider_clears_its_channel():
    drawer = block((0, 0, 0), (10, 10, 5))
    channel = block((-5, -2.3, 0), (60, 2, 5)) + block((-5, 10.3, 0), (60, 2, 5))
    f = run(Slide("drawer", (1, 0, 0), 40), {"drawer": drawer, "channel": channel})
    assert f.level == OK
    assert f.data["min_clearance"] == pytest.approx(0.3, abs=0.005)


def test_slider_jams_on_a_stop():
    drawer = block((0, 0, 0), (10, 10, 5))
    stop = block((25, 8, 0), (2, 4, 5))  # catches the drawer's corner 15 mm along
    f = run(Slide("drawer", (1, 0, 0), 40, min_clearance=0.2), {"drawer": drawer, "stop": stop})
    assert f.level == FAIL
    assert f.data["first_contact"] == pytest.approx(15, abs=0.05)
    assert "drawer hits stop at 15" in f.message
    assert f.data["unit"] == " mm" and f.data["kind"] == "translation"
    # a slide that stops short of it: the clearance left at the end
    f = run(Slide("drawer", (1, 0, 0), 14), {"drawer": drawer, "stop": stop})
    assert f.level == OK and f.data["min_clearance"] == pytest.approx(1.0, abs=0.01)


def test_pieces_moving_together_and_bad_labels():
    a, b = block((0, 0, 0), (5, 5, 5)), block((0, 6, 0), (5, 5, 5))
    wall = block((20, -5, 0), (2, 20, 5))
    f = run(Slide(("a", "b"), (1, 0, 0), 20), {"a": a, "b": b, "wall": wall})
    assert f.level == FAIL and f.data["first_contact"] == pytest.approx(15, abs=0.05)
    with pytest.raises(KeyError, match="no assembly piece labeled"):
        run(Slide("nope", (1, 0, 0), 5), {"a": a})
    with pytest.raises(KeyError, match="needs assembly"):
        Slide("a", (1, 0, 0), 5).run({}, None, Settings())


def test_flip_hinge_example_and_its_colliding_variant():
    """The bundled example passes; folded 220 deg instead of 180, the leaves meet past 180."""
    from b123d_print.project import dims, load

    mod = load(EXAMPLES / "flip_hinge" / "flip_hinge.py")
    d = dims(mod, "")
    asm = mod.assembly(d)
    (spec,) = mod.checks(d)
    ok = spec.run({}, asm, Settings())[0]
    assert ok.level == OK, ok.line()
    assert ok.data["min_clearance"] == pytest.approx(d.CLEARANCE, abs=0.01)
    bad = mod.checks(replace(d, OPEN_DEG=220.0))[0].run({}, asm, Settings())[0]
    assert bad.level == FAIL
    assert 185 < bad.data["first_contact"] < 215


def test_check_draws_the_worst_pose(tmp_path):
    """Run by `check`, a motion draws its worst pose (render and section) into out/."""
    from b123d_print.project import load, run_checks

    script = tmp_path / "lidbox" / "lidbox.py"
    script.parent.mkdir()
    script.write_text('''
import math
from dataclasses import dataclass
from build123d import Align, Box, Pos
from b123d_print import Motion

MIN = (Align.MIN, Align.MIN, Align.MIN)

@dataclass(frozen=True)
class Dims:
    SHELF_Z: float = 30 * math.sin(math.radians(60)) + 3 * math.cos(math.radians(60))

VARIANTS = {"": {}}

def lid(d):
    return Pos(-20, -30, 0) * Box(40, 30, 3, align=MIN)

def build(d):
    return {"lid": Pos(20, 30, 0) * lid(d)}

def assembly(d):
    return [(lid(d), "#3a6ea5", "lid"), (Pos(-20, -40, d.SHELF_Z) * Box(40, 35, 5, align=MIN), "#888888", "shelf (stand-in)")]

def checks(d):
    return [Motion("lid", (0, 0, 0), (-1, 0, 0), 0, 110, samples=12)]
''', encoding="utf-8")
    found = [f for f in run_checks(load(script), "", Settings()) if f.check == "motion"]
    assert [f.level for f in found] == [FAIL]
    images = [Path(p) for p in found[0].data["images"]]
    assert [p.name for p in images] == ["lidbox_motion_lid.png", "lidbox_motion_lid_section.png"]
    assert all(p.is_file() and p.parent == script.parent / "out" / "images" for p in images)
