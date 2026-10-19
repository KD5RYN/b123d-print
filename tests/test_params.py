"""params / set_params: the Dims read from the ast, and exact in-place edits of their defaults."""

import json

import anyio
import pytest

from b123d_print.params import ParamError, read, set_values

SRC = '''\
"""A lid."""

from dataclasses import dataclass, field

from b123d_print import clearance, hole_comp


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    WIDTH: float = 40  # X, measured with calipers (±0.1)
    WALLS: int = 3  # perimeters
    HOLE_COMP: float = hole_comp(__file__)  # from the user's config
    CLEARANCE: float = clearance(__file__)  # sliding fit, per side
    SIZE: tuple[float, float] = (10.0, 20.0)  # typed by the user
    LABEL: str = "lid"  # engraved — on top
    LIP: float = field(default=1.5)  # lip height
    THICK: float = 2 * 1.2  # three lines
    ROUND: bool = True

    @property
    def INNER_W(self):
        """inside width"""
        return self.WIDTH - 2 * self.THICK


VARIANTS = {"": {}, "big": dict(WIDTH=80.0,), "thick": {"WALLS": 4}}


def build(d):
    return None
'''


def diff(a: str, b: str) -> list[tuple[str, str]]:
    return [(x, y) for x, y in zip(a.splitlines(), b.splitlines(), strict=True) if x != y]


def test_read_lists_fields_comments_derived_and_variants():
    info = read(SRC)
    f = {x["name"]: x for x in info["fields"]}
    assert list(f) == ["WIDTH", "WALLS", "HOLE_COMP", "CLEARANCE", "SIZE", "LABEL", "LIP", "THICK", "ROUND"]
    assert f["WIDTH"] == {"name": "WIDTH", "type": "float", "line": 12, "default": "40", "literal": True, "value": 40,
                          "comment": "X, measured with calipers (±0.1)"}
    assert f["HOLE_COMP"]["literal"] is False and "value" not in f["HOLE_COMP"]
    assert f["LIP"]["value"] == 1.5 and f["SIZE"]["value"] == [10.0, 20.0]
    assert "comment" not in f["ROUND"]
    assert info["derived"] == [{"name": "INNER_W", "line": 23, "uses": ["THICK", "WIDTH"], "doc": "inside width"}]
    assert info["variants"] == {"standard": {}, "big": {"WIDTH": "80.0"}, "thick": {"WALLS": "4"}}


def test_set_values_changes_only_the_defaults():
    out, changes, notes = set_values(SRC, {"WIDTH": 42.5, "WALLS": 4.0, "SIZE": [12, 22.5], "LABEL": "top",
                                           "LIP": 2, "ROUND": False})
    assert diff(SRC, out) == [
        ("    WIDTH: float = 40  # X, measured with calipers (±0.1)", "    WIDTH: float = 42.5  # X, measured with calipers (±0.1)"),
        ("    WALLS: int = 3  # perimeters", "    WALLS: int = 4  # perimeters"),
        ("    SIZE: tuple[float, float] = (10.0, 20.0)  # typed by the user",
         "    SIZE: tuple[float, float] = (12.0, 22.5)  # typed by the user"),
        ('    LABEL: str = "lid"  # engraved — on top', '    LABEL: str = "top"  # engraved — on top'),
        ("    LIP: float = field(default=1.5)  # lip height", "    LIP: float = field(default=2.0)  # lip height"),
        ("    ROUND: bool = True", "    ROUND: bool = False"),
    ]
    assert changes[0] == {"field": "WIDTH", "old": "40", "new": "42.5", "line": 12}
    assert any("big" in n and "WIDTH" in n for n in notes)  # the variant that overrides it does not change
    assert any("INNER_W" in n for n in notes)  # the derived value that follows it


def test_set_values_keeps_crlf_and_everything_else_byte_for_byte():
    src = SRC.replace("\n", "\r\n")
    out, _, _ = set_values(src, {"WIDTH": 41.0})
    assert out == src.replace("WIDTH: float = 40  #", "WIDTH: float = 41.0  #")


@pytest.mark.parametrize("values, msg", [
    ({"WIDHT": 1.0}, "did you mean WIDTH"),
    ({"WALLS": 2.5}, "not a whole number"),
    ({"WIDTH": "wide"}, "give a number"),
    ({"WIDTH": True}, "give a number"),
    ({"ROUND": 1}, "true or false"),
    ({"HOLE_COMP": 0.1}, "settings"),  # an expression: computed when the script runs
    ({"THICK": 3.0}, r"expression `2 \* 1\.2`"),
    ({"INNER_W": 30.0}, "derived"),
    ({"SIZE": [1.0]}, "has 2 values"),
    ({"WIDTH": float("nan")}, "finite"),
    ({}, "no values"),
])
def test_set_values_refuses(values, msg):
    with pytest.raises(ParamError, match=msg):
        set_values(SRC, values)


def test_set_values_in_a_variant_changes_or_adds_the_override():
    out, changes, _ = set_values(SRC, {"WIDTH": 90, "LIP": 3}, variant="big")
    assert 'VARIANTS = {"": {}, "big": dict(WIDTH=90.0, LIP=3.0), "thick": {"WALLS": 4}}' in out
    assert [c["old"] for c in changes] == ["80.0", None]
    out, _, _ = set_values(SRC, {"WALLS": 5, "WIDTH": 50}, variant="thick")
    assert 'VARIANTS = {"": {}, "big": dict(WIDTH=80.0,), "thick": {"WALLS": 5, "WIDTH": 50.0}}' in out
    out, _, _ = set_values(SRC, {"WIDTH": 30}, variant="standard")  # the default part: Dims itself
    assert "WIDTH: float = 30.0" in out
    with pytest.raises(ParamError, match="no variant 'tiny'"):
        set_values(SRC, {"WIDTH": 30}, variant="tiny")
    with pytest.raises(ParamError, match="no literal VARIANTS"):
        set_values(SRC.replace("VARIANTS = ", "OTHER = "), {"WIDTH": 30}, variant="big")
    empty = SRC.replace('"thick": {"WALLS": 4}', '"thick": {}')
    out, _, _ = set_values(empty, {"WALLS": 6}, variant="thick")
    assert '"thick": {"WALLS": 6}' in out


def test_no_dims_and_broken_scripts_are_refused():
    with pytest.raises(ParamError, match="no top-level `class Dims`"):
        read("part = 1\n")
    with pytest.raises(ParamError, match="does not parse"):
        read("class Dims(:\n")


# --- the MCP tools -------------------------------------------------------------------------------

BOX = '''\
from dataclasses import dataclass

from build123d import Align, Box

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    WIDTH: float = 20.0  # X, measured
    DEPTH: float = 10.0  # Y
    HEIGHT: float = 5.0  # Z


VARIANTS = {"": {}, "tall": dict(HEIGHT=8.0)}


def build(d):
    return Box(d.WIDTH, d.DEPTH, d.HEIGHT, align=BED)
'''


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from b123d_print import mcp_server as m
    from b123d_print import sandbox

    (tmp_path / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    script = tmp_path / "parts" / "blk" / "blk.py"
    script.parent.mkdir(parents=True)
    script.write_text(BOX, encoding="utf-8")
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / ".slots")
    return m, script


def test_params_tool(server):
    m, _ = server
    info = json.loads(m.params("blk"))
    assert info["file"] == "parts/blk/blk.py"
    assert [(f["name"], f["value"], f.get("comment")) for f in info["fields"]] == [
        ("WIDTH", 20.0, "X, measured"), ("DEPTH", 10.0, "Y"), ("HEIGHT", 5.0, "Z")]


def test_set_params_tool_edits_rebuilds_and_reports(server):
    from mcp.server.mcpserver.exceptions import ToolError

    m, script = server
    out = anyio.run(m.set_params, "blk", {"WIDTH": 30})
    assert "WIDTH (Dims, line 10): 20.0 -> 30.0" in out
    assert "part: 20.00 x 10.00 x 5.00 -> 30.00 x 10.00 x 5.00 mm" in out
    assert "volume 1000.0 -> 1500.0 mm^3 (+500.0, +50.0 %)" in out
    assert 'Undo: set_params(\'blk\', {"WIDTH": 20.0})' in out
    assert script.read_text(encoding="utf-8") == BOX.replace("WIDTH: float = 20.0", "WIDTH: float = 30.0")
    out = anyio.run(lambda: m.set_params("blk", {"HEIGHT": 9}, variant="tall", rebuild=False))
    assert "HEIGHT (VARIANTS['tall'], line 15): 8.0 -> 9.0" in out and "Not rebuilt" in out
    with pytest.raises(ToolError, match="did you mean WIDTH"):
        anyio.run(m.set_params, "blk", {"WIDHT": 3})
    assert "WIDTH: float = 30.0" in script.read_text(encoding="utf-8")  # a refused call changes nothing


def test_set_params_reports_a_build_it_breaks(server):
    m, script = server
    out = anyio.run(m.set_params, "blk", {"HEIGHT": 0})
    assert "the build now FAILS" in out and "Undo: set_params('blk', {\"HEIGHT\": 5.0})" in out
    assert "HEIGHT: float = 0.0" in script.read_text(encoding="utf-8")
