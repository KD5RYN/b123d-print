"""Edge listing and selection by id (edges.py) on shapes with known edges."""

import json

import anyio
import pytest
from build123d import Align, Axis, Box, Cylinder, fillet

from b123d_print import edges as ed

BED = (Align.CENTER, Align.CENTER, Align.MIN)
MIN = (Align.MIN, Align.MIN, Align.MIN)


def box():
    return Box(30, 20, 10, align=BED)


def ell():
    """An L: a 20 x 10 x 5 slab with a 5 x 10 x 15 upright at its X=0 end; one inside corner."""
    return Box(20, 10, 5, align=MIN) + Box(5, 10, 15, align=MIN)


def holed():
    return box() - Cylinder(3, 40)


def counts(part):
    return ed.list_edges(part)["counts"]


def test_box_has_twelve_convex_edges():
    res = ed.list_edges(box())
    assert res["total"] == 12 and res["counts"] == {"convex": 12}
    assert [e["length"] for e in res["edges"]] == [30.0] * 4 + [20.0] * 4 + [10.0] * 4  # longest first
    first = res["edges"][0]
    assert first["type"] == "line" and first["turn"] == 90.0 and len(first["faces"]) == 2
    assert all(isinstance(f, int) for e in res["edges"] for f in e["faces"])  # flat faces: list_faces ids


def test_l_has_one_inside_corner():
    res = ed.list_edges(ell(), convexity="concave")
    assert counts(ell()) == {"convex": 17, "concave": 1}
    (e,) = res["edges"]
    assert e["type"] == "line" and e["length"] == 10.0
    assert sorted([e["start"], e["end"]]) == [[5.0, 0.0, 5.0], [5.0, 10.0, 5.0]]


def test_box_with_a_hole_has_its_rims_and_a_seam():
    res = ed.list_edges(holed(), kind="circle")
    assert counts(holed()) == {"convex": 14, "seam": 1}
    assert len(res["edges"]) == 2 and {e["center"][2] for e in res["edges"]} == {0.0, 10.0}
    assert all(e["radius"] == 3.0 and e["convexity"] == "convex" and "cylinder r3" in e["faces"] for e in res["edges"])
    top = ed.list_edges(holed(), face="top")["edges"]
    assert len(top) == 5 and sum(e["type"] == "circle" for e in top) == 1
    near = ed.list_edges(holed(), near=(-3, 0, 10), radius=0.5)["edges"]
    assert [e["type"] for e in near] == ["circle"] and near[0]["distance"] == 0.0


def test_fillet_sides_are_tangent_and_ids_are_stable():
    part = fillet(box().edges().filter_by(Axis.Z), 2)
    c = counts(part)
    assert c["tangent"] == 8 and c["convex"] == 16 and "concave" not in c
    assert ed.list_edges(part) == ed.list_edges(fillet(box().edges().filter_by(Axis.Z), 2))


def test_filters_and_ids():
    with pytest.raises(ed.EdgeError, match="edge type"):
        ed.list_edges(box(), kind="curve")
    with pytest.raises(ed.EdgeError, match="ids are 1 to 12"):
        ed.find_edges(box(), [13])
    assert ed.parse_ids("3-5, 9", 12) == [3, 4, 5, 9] and ed.id_text([3, 4, 5, 9]) == "3-5, 9"
    res = ed.list_edges(box(), limit=5)
    assert len(res["edges"]) == 5 and res["matched"] == 12 and "7 more" in res["note"]


@pytest.mark.parametrize("make,pick", [
    (box, lambda r: [1, 2, 3, 4]),
    (box, lambda r: [e["id"] for e in r["edges"] if e["type"] == "line" and e["start"][2] == e["end"][2] == 10.0]),
    (ell, lambda r: [e["id"] for e in r["edges"] if e["convexity"] == "concave"]),
    (ell, lambda r: [e["id"] for e in r["edges"] if e["convexity"] == "convex" and e["type"] == "line"
                     and e["start"][2] == e["end"][2] == 15.0]),
    (holed, lambda r: [e["id"] for e in r["edges"] if e["type"] == "circle"]),
    (holed, lambda r: [e["id"] for e in r["edges"] if e["type"] == "circle"][:1]),
    (holed, lambda r: [r["edges"][0]["id"], next(e["id"] for e in r["edges"] if e["type"] == "circle")]),
])
def test_selector_selects_exactly_the_chosen_edges(make, pick):
    part = make()
    ids = pick(ed.list_edges(part))
    sel = ed.selector(part, ids)
    assert sel["verified"] and sel["stable"], sel
    got = ed.evaluate(sel["expr"], part)
    want, _ = ed.find_edges(part, ids)
    assert {hash(e) for e in got} == {hash(e) for e in want} and len(got) == len(ids)
    fillet(got, 0.5)  # and it works where it is meant to go


def test_selector_follows_the_shape_when_it_changes():
    """Chosen on one size, the expression still picks the matching edges of another."""
    sel = ed.selector(ell(), [e["id"] for e in ed.list_edges(ell(), convexity="concave")["edges"]])
    assert sel["expr"] == "concave_edges(part)" and sel["import"] == "from b123d_print.edges import concave_edges"
    other = Box(40, 12, 6, align=MIN) + Box(8, 12, 20, align=MIN)
    (e,) = ed.evaluate(sel["expr"], other)
    assert ed.list_edges(other, convexity="concave")["edges"][0]["length"] == pytest.approx(e.length)


def test_highlight_picture(tmp_path):
    part = holed()
    chosen, ids = ed.find_edges(part, "1,5")
    img = ed.highlight(part, chosen, tmp_path / "e.png", "edges", size="small")
    assert img.is_file() and img.stat().st_size > 5000


SCRIPT = '''
from dataclasses import dataclass
from build123d import Align, Box, Cylinder

@dataclass(frozen=True)
class Dims:
    W: float = 30.0

def build(d):
    return Box(d.W, 20, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Cylinder(3, 40)
'''


@pytest.fixture
def plate(tmp_path):
    script = tmp_path / "parts" / "plate" / "plate.py"
    script.parent.mkdir(parents=True)
    script.write_text(SCRIPT)
    (tmp_path / "b123d-print.toml").write_text("")
    return script


def test_cli_edges(plate, capsys):
    from b123d_print.cli import main

    root = str(plate.parents[2])
    assert main(["--root", root, "edges", "plate", "--kind", "circle", "--highlight", "9,10"]) == 0
    out = capsys.readouterr().out
    assert "plate part: 2 of 15 edges (14 convex, 1 seam)" in out
    assert "selector: part.edges().filter_by(GeomType.CIRCLE)" in out
    assert (plate.parent / "out" / "images" / "plate_edges9-10.png").is_file()
    assert main(["--root", root, "edges", "plate", "--json", "--convexity", "seam"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] == 1
    with pytest.raises(SystemExit, match="ids are 1 to 15"):
        main(["--root", root, "edges", "plate", "--highlight", "16"])


def test_list_edges_tool_through_the_sandbox(plate, monkeypatch):
    from b123d_print import mcp_server as m
    from b123d_print import sandbox

    monkeypatch.setitem(m.STATE, "root", plate.parents[2])
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setattr(sandbox, "SLOT_DIR", plate.parents[2] / ".slots")
    out = anyio.run(lambda: m.list_edges("plate", face="top", highlight="1-4", inline=False))
    head, _, rest = out[0].partition("\n{")
    assert "selector: part.edges().filter_by(Axis.X)" in head
    data = json.JSONDecoder().raw_decode("{" + rest)[0]
    assert data["face"] and len(data["edges"]) == 5 and data["selector"]["verified"]
    assert (plate.parent / "out" / "images" / "plate_edges1-2-3-4.png").is_file()
    out = anyio.run(lambda: m.list_edges("plate", kind="curve"))
    assert out[0].startswith("ERROR: EdgeError: edge type 'curve'")


def test_selector_falls_back_to_positions(monkeypatch):
    """No chain at all: the edges are picked by their midpoints, still verified, and not called stable."""
    monkeypatch.setattr(ed, "_search", lambda *a, **k: None)
    sel = ed.selector(holed(), [1, 9])
    assert sel["verified"] and not sel["stable"] and "midpoints" in sel["note"]
    assert sel["expr"].startswith("part.edges().filter_by(lambda e:")


def test_fillet_diagnosis_points_to_list_edges():
    from b123d_print import diagnose as dg

    try:
        fillet(Box(10, 4, 4).edges().filter_by(Axis.Z), radius=3)
    except Exception as e:  # noqa: BLE001
        d = dg.from_exception(e)
    assert d["kind"] == "fillet" and dg.LIST_EDGES in d["fixes"]
