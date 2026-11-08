"""A part whose script is still the new_part template says so at the top of build_part,
render_preview, check and export. The real case (2026-11-08): a client edited its own downloaded
copy with its own file tools, built on the server again and again, and got the 40x20x10 box."""

import json

import anyio
import pytest

from b123d_print import mcp_server as m
from b123d_print.cli import untouched_template

SCRIPT = '''from dataclasses import dataclass
from build123d import Box


@dataclass(frozen=True)
class Dims:
    L: float = 12.0  # typed by the user


VARIANTS = {"": {}}


def build(d):
    return Box(d.L, d.L, d.L)
'''


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from b123d_print import sandbox

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "reminded", set())
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setitem(m.STATE, "max_builds", 1)
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / ".slots")
    return tmp_path


def test_fresh_template_build_says_so_and_write_part_clears_it(server):
    m.new_part("bracket", description="a wall bracket")
    out = anyio.run(m.build_part, "bracket")
    head, _, body = out.partition("\n\n")
    assert head.startswith("NOTICE: parts/bracket/bracket.py is still the new_part template (a 40x20x10 placeholder box)")
    assert "write_part('bracket'" in head and "client's own file tools" not in head  # stdio: neutral
    size = json.loads(body)["variants"]["standard"]["parts"]["part"]
    assert (round(size["x"]), round(size["y"]), round(size["z"])) == (40, 20, 10)
    assert m.write_part("bracket", SCRIPT).startswith("Saved")
    out = anyio.run(m.build_part, "bracket")
    assert "NOTICE" not in out and json.loads(out)["variants"]["standard"]["parts"]["part"]["x"] == pytest.approx(12)


def test_check_also_says_so(server):
    m.new_part("plate", sketch_first=True)
    out = anyio.run(m.check, "plate")
    assert out.startswith("NOTICE: parts/plate/plate.py is still the new_part template (a 60x30x4 placeholder plate)")


def test_remote_wording_names_the_clients_own_tools(server, monkeypatch):
    m.new_part("knob")
    monkeypatch.setitem(m.STATE, "transport", "http")
    note = m._template_notice("knob")
    assert note.startswith("NOTICE: parts/knob/knob.py is still the new_part template (a 40x20x10 placeholder box). "
                           "Your client's own file tools do not reach this server: send the whole script with "
                           "write_part('knob', <whole script>), then build again.")
    assert m._noticed("knob", ["x", "y"]) == [note + "x", "y"]


def test_only_the_docstring_or_line_endings_changed_is_still_the_template(server):
    m.new_part("hook", description="DESC-XYZ")
    p = server / "parts" / "hook" / "hook.py"
    src = p.read_text(encoding="utf-8")
    p.write_bytes(src.replace("Hook", "A coat hook", 1).replace("DESC-XYZ", "a coat hook, 2 screws").replace("\n", "\r\n").encode())
    assert untouched_template(p) == "a 40x20x10 placeholder box"


def test_a_real_edit_of_the_template_is_not_flagged(server):
    m.new_part("shelf")
    p = server / "parts" / "shelf" / "shelf.py"
    src = p.read_text(encoding="utf-8")
    edited = src.replace("WIDTH: float = 40.0", "WIDTH: float = 55.0")
    assert edited != src
    m.write_part("shelf", edited)
    assert untouched_template(p) is None and m._template_notice("shelf") == ""
    assert "NOTICE" not in anyio.run(m.build_part, "shelf")


def test_an_example_is_not_the_template(server):
    m.new_part("coupon", example="hole_coupon")
    assert m._template_notice("coupon") == ""
