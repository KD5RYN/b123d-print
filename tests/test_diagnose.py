"""Build-failure diagnosis: the patterns (from error text), the evidence read from a live
exception (fillet widths, offset sizes), shape problems, and the diagnosis in tool results."""

import json
from pathlib import Path

import anyio
import pytest
from build123d import Align, Axis, Box, BuildLine, BuildSketch, Circle, Line, Pos, Rectangle, Spline, fillet, loft
from build123d import make_face, offset

from b123d_print import diagnose as dg

BED = (Align.CENTER, Align.CENTER, Align.MIN)


# --- patterns, from the error text alone -----------------------------------------------------------


@pytest.mark.parametrize("error, kind", [
    ("ValueError: Failed creating a fillet with radius of 3.0, try a smaller value or use max_fillet()", "fillet"),
    ("ValueError: Failed creating a chamfer, try a smaller length value(s)", "chamfer"),
    ("ValueError: Nothing to fillet", "fillet-selection"),
    ("RuntimeError: 2D offset failed with distance 40.0", "offset2d"),
    ("RuntimeError: Failed to create valid loft", "loft"),
    ("ValueError: All sections must have the same number of inner wires", "loft"),
    ("Standard_ConstructionError: BRepSweep_Translation::Constructor", "extrude"),
    ("ValueError: Null TopoDS_Shape object", "boolean"),
    ("AttributeError: 'Dims' object has no attribute 'WAAL'", "missing-dim"),
    ("TypeError: Dims.__init__() got an unexpected keyword argument 'WIDHT'", "variant-field"),
    ("dataclasses.FrozenInstanceError: cannot assign to field 'WIDTH'", "frozen-dims"),
    ("AttributeError: 'NoneType' object has no attribute 'bounding_box'", "wrong-type"),
    ("AttributeError: 'BuildPart' has no attribute 'bounding_box'. Did you intend '<BuildPart>.part.bounding_box'?",
     "wrong-type"),
    ("AttributeError: 'list' object has no attribute 'is_valid'", "wrong-type"),
    ("AttributeError: script defines neither build(d) nor a module-level `part`", "no-build"),
    ("SandboxViolation: blocked in part scripts: socket.connect", "sandbox"),
    ("ZeroDivisionError: division by zero", "other"),
])
def test_patterns(error, kind):
    d = dg.classify(error, fields=[{"name": "WALL"}, {"name": "WIDTH"}], part="box")
    assert d["kind"] == kind, d
    assert d["fixes"] and d["cause"]


def test_missing_dim_names_the_close_field():
    d = dg.classify("AttributeError: 'Dims' object has no attribute 'WAAL'", fields=[{"name": "WALL"}, {"name": "R"}])
    assert d["cause"] == "the script uses WAAL but Dims has no field WAAL"
    assert d["fixes"][0].startswith("did you mean WALL?")


def test_selection_needs_a_selector_on_the_line():
    where = {"file": "parts/x/x.py", "line": 3, "function": "build", "code": "top = part.faces().sort_by(Axis.Z)[7]"}
    assert dg.classify("IndexError: list index out of range", where_=where)["kind"] == "selection"
    where["code"] = "x = values[i]"
    assert dg.classify("IndexError: list index out of range", where_=where)["kind"] == "other"


def test_unable_to_clean_warning_points_at_the_boolean():
    d = dg.classify("ValueError: something", warnings=["Unable to clean <Part>"])
    assert d["kind"] == "boolean" and "warning: Unable to clean <Part>" in d["evidence"]


def test_where_and_text_from_a_traceback(tmp_path):
    script = tmp_path / "parts" / "box" / "box.py"
    tb = (f'Traceback (most recent call last):\n  File "/x/b123d_print/project.py", line 182, in part\n'
          f'    shape = v() if _lazy(v) else v\n  File "{script}", line 18, in <lambda>\n    "lid": lambda: lid(d)\n'
          f'  File "{script}", line 14, in lid\n    part = fillet(edges, radius=d.R)\n'
          f'  File "/x/build123d/topology/three_d.py", line 371, in fillet\n    raise ValueError(\n'
          "ValueError: Failed creating a fillet with radius of 3.0")
    w = dg.where(dg.frames_from_text(tb), script)
    assert w == {"file": "parts/box/box.py", "line": 14, "function": "lid", "code": "part = fillet(edges, radius=d.R)",
                 "chain": "<lambda> -> lid"}
    d = dg.from_result({"ok": False, "error": "ValueError: Failed creating a fillet with radius of 3.0", "traceback": tb},
                       script)
    assert d["kind"] == "fillet" and d["where"]["line"] == 14
    txt = dg.text(d, "box")
    assert "where: parts/box/box.py line 14 in lid: part = fillet(edges, radius=d.R)" in txt
    assert "deeper look: diagnose_failure('box')" in txt


def test_timeout_names_the_piece_from_the_progress_lines():
    log = "\n".join(dg.PROGRESS + x for x in ("building build(d)", "built build(d) in 0.01 s", "building piece rear",
                                              "built piece rear: 812 faces, 31.20 s", "building piece front"))
    d = dg.from_result({"ok": False, "error": "timed out after 240 s (killed)", "log": "hello\n" + log})
    assert d["kind"] == "timeout" and d["where"] == {"piece": "piece 'front'"}
    assert d["evidence"] == ["finished: rear: 812 faces, 31.2 s"]
    assert "parts='front'" in d["fixes"][0]
    d = dg.from_result({"ok": False, "error": "timed out after 240 s (killed)",
                        "log": dg.PROGRESS + "building build(d)"})
    assert "return lazy pieces" in d["fixes"][0]
    assert dg.from_result({"ok": False, "error": "worker was killed (server shutting down, or out of memory)"})["kind"] == "killed"


# --- evidence from a live exception -----------------------------------------------------------------


def _raise(f):
    try:
        f()
    except Exception as e:  # noqa: BLE001
        return e
    raise AssertionError("did not fail")


def test_fillet_too_big_gets_the_face_width_and_a_radius_that_fits():
    e = _raise(lambda: fillet(Box(10, 4, 4, align=BED).edges().filter_by(Axis.Z), radius=3))
    d = dg.from_exception(e)
    assert d["kind"] == "fillet"
    assert d["context"]["edges"] == 4 and d["context"]["narrowest_face"] == 4.0
    assert d["fixes"][0] == "fillet r 3 on edges between faces 4 mm wide: try r <= 1.9"
    deep = dg.from_exception(e, deep=True)
    assert 1.9 <= deep["context"]["max_fillet"] <= 2.0  # the real limit is 2 (half the 4 mm face)


def test_spline_offset_failure_suggests_the_polygon():
    """The real case: a 2D offset on a spline-bounded face failed; the polygon version worked."""
    def inset():
        with BuildSketch() as s:
            with BuildLine():
                Spline((0, 0), (30, 25), (60, -25), (90, 0))
                Line((90, 0), (90, -60))
                Line((90, -60), (0, -60))
                Line((0, -60), (0, 0))
            make_face()
        return offset(s.sketch, -40)

    d = dg.from_exception(_raise(inset))
    assert d["kind"] == "offset2d"
    assert d["context"]["distance"] == -40 and d["context"]["curves"]["bspline"] == 1
    assert any("polyline" in f and "polygon version" in f for f in d["fixes"])


def test_inward_offset_bigger_than_half_the_outline_says_so():
    d = dg.classify("RuntimeError: 2D offset failed with distance -6.0",
                    ctx={"op": "offset2d", "distance": -6.0, "size": [20.0, 10.0], "edges": 4, "curves": {"line": 4}})
    assert d["fixes"][0].startswith("the offset (6 mm) is at least half the outline's narrowest width (10 mm)")


def test_loft_with_mismatched_holes():
    e = _raise(lambda: loft([Pos(0, 0, 0) * (Rectangle(10, 10) - Circle(2)), Pos(0, 0, 10) * Rectangle(10, 10)]))
    d = dg.from_exception(e)
    assert d["kind"] == "loft" and any("holes" in f for f in d["fixes"])


def test_dims_on_the_failing_line_are_named(tmp_path):
    script = tmp_path / "p.py"
    script.write_text("from dataclasses import dataclass\nfrom build123d import *\n\n@dataclass(frozen=True)\n"
                      "class Dims:\n    R: float = 3.0  # radius\n\n"
                      "def build(d):\n    return fillet(Box(10, 4, 4).edges().filter_by(Axis.Z), radius=d.R)\n",
                      encoding="utf-8")
    from b123d_print.project import load

    mod = load(script)
    d = dg.from_exception(_raise(lambda: mod.build(mod.Dims())), script)
    assert d["dims_on_line"] == {"R": 3.0}
    assert d["where"]["line"] == 9 and d["where"]["function"] == "build"
    assert "(R in Dims: set_params('p', {'R': <new value>}))" in d["fixes"][0]


# --- a build that ran: shape problems ---------------------------------------------------------------


def test_shape_problems():
    assert dg.shape_problems("p", Box(10, 10, 10, align=BED)) == []
    off = dg.shape_problems("p", Box(10, 10, 10))
    assert [p["kind"] for p in off] == ["bed"] and "Pos(0, 0, 5)" in off[0]["fixes"][0]
    with BuildSketch() as s:
        Rectangle(5, 5)
    assert dg.shape_problems("p", s.sketch)[0]["kind"] == "flat"
    empty = Box(10, 10, 10) - Box(20, 20, 20)
    assert "empty" in [p["kind"] for p in dg.shape_problems("p", empty)]

    class Broken:  # what an invalid boolean result looks like to shape_problems
        volume, is_valid = 10.0, False

        def bounding_box(self):
            return Box(1, 1, 1, align=BED).bounding_box()

    assert [p["kind"] for p in dg.shape_problems("p", Broken())] == ["invalid"]


def test_analyze_shape_on_a_valid_part():
    a = dg.analyze_shape(Box(10, 10, 10))
    assert a == {"valid": True, "faces": 6, "edges": 12, "solids": 1, "volume": 1000.0}


# --- in the tool results (through the sandbox) --------------------------------------------------------

FAILING = '''\
from dataclasses import dataclass

from build123d import Align, Axis, Box, fillet

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    WIDTH: float = 10.0  # X
    DEPTH: float = 4.0  # Y
    R: float = 3.0  # fillet radius, estimate


def lid(d):
    part = Box(d.WIDTH, d.DEPTH, 4, align=BED)
    return fillet(part.edges().filter_by(Axis.Z), radius=d.R)


def build(d):
    return {"base": lambda: Box(d.WIDTH, d.DEPTH, 2, align=BED), "lid": lambda: lid(d)}
'''


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from b123d_print import mcp_server as m
    from b123d_print import sandbox

    (tmp_path / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setitem(m.STATE, "max_builds", 1)
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / ".slots")

    def part(name: str, code: str) -> Path:
        p = tmp_path / "parts" / name / f"{name}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, encoding="utf-8")
        return p

    return m, part


def test_failed_build_check_and_diagnose_failure_carry_the_diagnosis(server):
    m, part = server
    part("box", FAILING)
    out = anyio.run(m.build_part, "box")
    assert "DIAGNOSIS (fillet)" in out
    assert "where: parts/box/box.py line 17 in lid, while building piece 'lid'" in out
    assert "fillet r 3 on edges between faces 4 mm wide: try r <= 1.9 (R in Dims: set_params('box'" in out
    out = anyio.run(m.check, "box")
    assert "build failed" in out and "DIAGNOSIS (fillet)" in out
    out = anyio.run(m.diagnose_failure, "box")
    assert "piece base: built" in out and "piece lid: FAILED" in out
    assert "largest fillet radius that works on these edges (max_fillet): 2 mm" in out or "max_fillet): 1.99" in out


def test_a_build_that_is_off_the_bed_reports_the_problem(server):
    m, part = server
    part("air", "from build123d import Box\n\ndef build():\n    return Box(10, 10, 10)\n")
    res = json.loads(anyio.run(m.build_part, "air"))
    (prob,) = res["variants"]["standard"]["problems"]["part"]
    assert prob["kind"] == "bed" and "Z=-5" in prob["cause"]


def test_timeout_says_which_piece(server, monkeypatch):
    m, part = server
    part("slow", "import time\nfrom build123d import Box\n\ndef build():\n"
                 "    return {'fast': lambda: Box(1, 1, 1), 'slow': lambda: time.sleep(60) or Box(1, 1, 1)}\n")
    monkeypatch.setitem(m.STATE, "timeout", 12.0)
    out = anyio.run(m.build_part, "slow")
    assert out.startswith("ERROR: timed out after 12 s")
    assert "DIAGNOSIS (timeout): the build ran out of time while building piece 'slow'" in out
    assert "parts='slow'" in out
    assert dg.PROGRESS not in out  # the raw progress lines are not shown


def test_a_wrong_argument_gets_no_diagnosis(server):
    m, part = server
    part("box", FAILING)
    out = anyio.run(m.build_part, "box", None, "nope")
    assert out.startswith("ERROR: KeyError") and "DIAGNOSIS" not in out and "Traceback" not in out


def test_cli_diagnose(server, capsys):
    from b123d_print.cli import main

    _, part = server
    script = part("box", FAILING)
    assert main(["--root", str(script.parents[2]), "diagnose", "box"]) == 1
    out = capsys.readouterr().out
    assert "piece lid: FAILED" in out and "try r <= 1.9" in out
