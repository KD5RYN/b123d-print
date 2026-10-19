"""measure: gaps and interference, walls, faces and holes on simple shapes with known answers."""

import json
from pathlib import Path

import anyio
import pytest
from build123d import Align, Box, Cylinder, Pos

from b123d_print import measure as ms
from b123d_print.config import load_settings
from b123d_print.project import Pieces, load

BED = (Align.CENTER, Align.CENTER, Align.MIN)
TOP = (Align.CENTER, Align.CENTER, Align.MAX)


def cube(x=0.0, s=10.0):
    return Pos(x, 0, 0) * Box(s, s, s, align=BED)


def hollow():
    """A 20 mm open box with 2 mm walls and a 2 mm floor."""
    return Box(20, 20, 20, align=BED) - Pos(0, 0, 2) * Box(16, 16, 20, align=BED)


def plate():
    """30 x 20 x 5 plate: a 3.2 through hole at x=-8, a 4 mm blind hole 3 deep at x=8 (from the top)."""
    return (Box(30, 20, 5, align=BED) - Pos(-8, 0, 0) * Cylinder(1.6, 20)
            - Pos(8, 0, 5) * Cylinder(2, 3, align=TOP))


def test_gap_between_two_boxes():
    r = ms.distance(cube(), cube(10.5))
    assert r == {"overlap": False, "distance": 0.5, "touching": False, "points": [[5.0, -5.0, 10.0], [5.5, -5.0, 10.0]]}
    assert ms.distance(cube(), cube(10.0))["touching"] is True


def test_interference_volume_box_and_depth():
    r = ms.distance(cube(), cube(9.5))
    r.pop("_shape")
    assert r["overlap"] and r["interference_volume"] == 50.0 and r["depth"] == 0.5
    assert r["interference_box"]["size"] == [0.5, 10.0, 10.0] and r["interference_center"] == [4.75, 0.0, 5.0]
    inner = Pos(0, 0, 2) * Box(2, 2, 2, align=BED)  # wholly inside, touching no face: still interference
    r = ms.distance(cube(), inner)
    assert r["overlap"] and r["interference_volume"] == 8.0


def test_wall_from_a_surface_point_and_along_a_direction():
    r = ms.wall(hollow(), (10, 0, 10))
    assert r["thickness"] == 2.0 and r["from"] == [10.0, 0.0, 10.0] and r["to"] == [8.0, 0.0, 10.0]
    assert [(b["kind"], b["length"]) for b in r["beyond"]] == [("gap", 16.0), ("material", 2.0)]
    r = ms.wall(hollow(), (9.5, 3, 10))  # inside the wall: the same wall
    assert r["thickness"] == 2.0 and r["point_inside"]
    r = ms.wall(hollow(), (0, 0, 10), direction=(1, 0, 0))  # from the cavity: the first wall along +X
    assert r["thickness"] == 2.0 and r["from"] == [8.0, 0.0, 10.0]
    assert ms.wall(hollow(), (0, 0, 10), direction=(0, 0, -1))["thickness"] == 2.0  # the floor
    with pytest.raises(ms.MeasureError, match="no material"):
        ms.wall(hollow(), (0, 0, 10), direction=(0, 0, 1))


def test_faces_parallel_and_at_an_angle():
    r = ms.faces(Box(20, 10, 6, align=BED), "top", "bottom")
    r.pop("_shapes")
    assert r["parallel"] and r["distance"] == 6.0 and r["between"].startswith("the part")
    slot = Box(20, 10, 6, align=BED) - Box(4, 20, 20)  # a 4 mm slot across Y
    from b123d_print.templates import list_faces

    ids = {tuple(f["normal"]): f["id"] for f in list_faces(slot)["planar"] if abs(f["center"][0]) == 2.0}
    r = ms.faces(slot, ids[(1.0, 0.0, 0.0)], ids[(-1.0, 0.0, 0.0)])
    assert r["distance"] == 4.0 and r["between"].startswith("space")
    r = ms.faces(Box(20, 10, 6, align=BED), "top", "front")
    assert not r["parallel"] and r["angle"] == 90.0


def test_holes_in_a_face_with_compensation():
    r = ms.hole(plate(), "top", comp=0.2, comp_h=0.3)
    through, blind = r["holes"]
    assert through["modeled_d"] == 3.2 and through["prints_about"] == 3.0 and through["through"] and through["length"] == 5.0
    assert through["center"] == [-8.0, 0.0, 5.0] and through["orientation"] == "vertical"
    assert blind["modeled_d"] == 4.0 and not blind["through"] and blind["depth"] == 3.0
    (one,) = ms.hole(plate(), "top", at=(8, 0, 5))["holes"]
    assert one["modeled_d"] == 4.0
    (by_point,) = ms.hole(plate(), at=(-8, 1.6, 2))["holes"]
    assert by_point["modeled_d"] == 3.2 and by_point["through"]
    side = Box(20, 10, 10, align=BED) - Pos(0, 0, 5) * Cylinder(1.5, 30, rotation=(90, 0, 0))
    (h,) = ms.hole(side, "front", comp=0.2, comp_h=0.3)["holes"]
    assert h["orientation"] == "horizontal" and h["prints_about"] == 2.7  # hole_comp_h for a hole on its side
    with pytest.raises(ms.MeasureError, match="boss or pin"):
        ms.hole(Box(20, 20, 2, align=BED) + Pos(0, 0, 2) * Cylinder(2, 5, align=BED), at=(2, 0, 4))
    with pytest.raises(ms.MeasureError, match="no holes"):
        ms.hole(Box(10, 10, 10, align=BED), "top")


# --- names, frames and the tool -----------------------------------------------------------------------

LID = '''\
from dataclasses import dataclass

from build123d import Align, Box, Pos

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    W: float = 20.0  # inside width of the base
    CLEARANCE: float = 0.2  # per side


def build(d):
    base = Box(d.W + 4, d.W + 4, 10, align=BED) - Pos(0, 0, 2) * Box(d.W, d.W, 10, align=BED)
    plug = Box(d.W - 2 * d.CLEARANCE, d.W - 2 * d.CLEARANCE, 3, align=BED)
    return {"base": base, "lid": Box(d.W + 4, d.W + 4, 2, align=BED) + Pos(0, 0, 2) * plug}


def assembly(d):
    parts = build(d)
    return [(parts["base"], None, "base"), (Pos(0, 0, 12.5) * parts["lid"].rotate(Axis.X, 180), None, "lid"),
            (Pos(0, 0, 2) * Box(5, 5, 5, align=BED), "#999999", "battery")]
'''.replace("from build123d import Align, Box, Pos", "from build123d import Align, Axis, Box, Pos")


@pytest.fixture()
def lid(tmp_path):
    (tmp_path / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    script = tmp_path / "parts" / "lid" / "lid.py"
    script.parent.mkdir(parents=True)
    script.write_text(LID, encoding="utf-8")
    return script


def pieces(script: Path) -> Pieces:
    mod = load(script)
    return Pieces(mod, mod.Dims())


def test_run_measures_the_fit_in_the_assembly(lid):
    pc = pieces(lid)
    r = ms.run(pc, {"kind": "distance", "a": "lid", "b": "base"}, load_settings(lid))
    assert r["frame"] == "assembly" and r["distance"] == 0.2  # the plug's clearance, per side
    assert r["summary"].startswith("gap lid / base: 0.2 mm")
    r = ms.run(pc, {"kind": "distance", "a": "lid", "b": "base", "frame": "print"}, load_settings(lid))
    assert r["frame"] == "print" and r["overlap"]  # printed both at the origin they overlap
    r = ms.run(pc, {"kind": "distance", "a": "battery", "b": "base"}, load_settings(lid))  # a stand-in
    assert r["frame"] == "assembly" and r["touching"]
    r = ms.run(pc, {"kind": "wall", "a": "base", "at": (12, 0, 5)}, load_settings(lid))
    assert r["thickness"] == 2.0 and r["frame"] == "print"
    with pytest.raises(ms.MeasureError, match="several pieces"):
        ms.run(pc, {"kind": "wall", "at": (12, 0, 5)}, load_settings(lid))
    with pytest.raises(ms.MeasureError, match="no piece 'cap'"):
        ms.run(pc, {"kind": "wall", "a": "cap", "at": (12, 0, 5)}, load_settings(lid))
    with pytest.raises(ms.MeasureError, match="kind"):
        ms.run(pc, {"kind": "volume"}, load_settings(lid))


def test_measure_tool_through_the_sandbox(lid, monkeypatch):
    from b123d_print import mcp_server as m
    from b123d_print import sandbox

    monkeypatch.setitem(m.STATE, "root", lid.parents[2])
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setattr(sandbox, "SLOT_DIR", lid.parents[2] / ".slots")
    out = anyio.run(lambda: m.measure("lid", "distance", a="lid", b="base", image=True, inline=False))
    text = out[0]
    assert text.startswith("gap lid / base: 0.2 mm")
    data = json.loads(text.split("\n", 1)[1].split("\nhighlight:")[0])
    assert data["distance"] == 0.2 and data["frame"] == "assembly"
    assert (lid.parent / "out" / "lid_measure_distance.png").is_file()
    out = anyio.run(lambda: m.measure("lid", "faces", a="base", face="top", face2="bottom"))
    assert "2 mm apart" in out[0]  # "top" is the largest face facing up: the floor of the cavity, 2 mm thick
    out = anyio.run(lambda: m.measure("lid", "hole", a="base", face="top"))
    assert out[0].startswith("ERROR: MeasureError: face ") and out[0].endswith("has no holes (list_faces lists the holes "
                                                                                "of each face)")


def test_cli_measure(lid, capsys):
    from b123d_print.cli import main

    assert main(["--root", str(lid.parents[2]), "measure", "lid", "--wall", "12,0,5", "--of", "base"]) == 0
    assert capsys.readouterr().out.startswith("wall of base: 2 mm from [12.0, 0.0, 5.0] to [10.0, 0.0, 5.0]")
    assert main(["--root", str(lid.parents[2]), "measure", "lid", "--distance", "lid,base", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["distance"] == 0.2
