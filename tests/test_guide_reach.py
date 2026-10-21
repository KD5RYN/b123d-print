"""The workflow rules reach every client: tool results and descriptions (which every client passes
to the model), not only the b123d-print://guide resource and the initialize instructions (which
many clients drop, or cut at 512 characters like Codex)."""

import json

import anyio
import pytest

from b123d_print import mcp_server as m
from b123d_print.cli import data

SCRIPT = '''from dataclasses import dataclass
from build123d import Box


@dataclass(frozen=True)
class Dims:
    L: float = 10.0  # typed by the user


VARIANTS = {"": {}}


def build(d):
    return Box(d.L, d.L, d.L)
'''


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "reminded", set())
    return tmp_path


def test_read_guide_is_the_resource():
    assert m.read_guide() == data("AGENTS.md") == m.guide()
    short = m.read_guide(essentials=True)
    assert short == m.ESSENTIALS and len(short.splitlines()) <= 6 and "read_guide" in short


def test_essentials_cover_the_skipped_rules():
    e = m.ESSENTIALS
    for words in ("WAIT", "UPPER_CASE", "Dims", "mm", "Z=0", "render_preview", "section", "check", "export",
                  "download_part", "embed=True"):
        assert words in e, words


def test_first_512_characters_stand_alone():
    head = m.INSTRUCTIONS[:512]
    for words in ("read_guide", "WAIT for confirmation", "UPPER_CASE", "Z=0", "render_preview", "section", "check",
                  "download_part"):
        assert words in head, words


def test_descriptions_point_to_the_guide():
    tools = {t.name: t.description for t in anyio.run(m.mcp.list_tools)}
    assert "read_guide" in tools
    for name in ("new_part", "write_part"):
        assert "read_guide first" in tools[name] and "confirm the dimensions with the user" in tools[name], name
    assert "must reach the user" in tools["export"]


def test_first_results_carry_the_essentials(ws):
    assert json.loads(m.list_parts())["rules"] == m.ESSENTIALS.splitlines()
    assert m.ESSENTIALS in m.new_part("cradle")
    first = m.write_part("cradle", SCRIPT)
    assert first.startswith("Saved parts/cradle/cradle.py") and m.ESSENTIALS not in first  # new_part already showed them
    m.STATE["reminded"].clear()  # a part from an earlier session, never built: its first save reminds
    assert m.ESSENTIALS in m.write_part("cradle", SCRIPT)
    assert m.ESSENTIALS not in m.write_part("cradle", SCRIPT)  # once per part, not every save
    m.STATE["reminded"].clear()
    (ws / "parts" / "cradle" / "out").mkdir()
    assert m.ESSENTIALS not in m.write_part("cradle", SCRIPT)  # already built: an ongoing design


def test_docs_show_the_checklist():
    from pathlib import Path

    tools_md = (Path(__file__).resolve().parents[1] / "docs/using/tools.md").read_text(encoding="utf-8")
    assert m.ESSENTIALS in tools_md, "docs/using/tools.md: the rules checklist differs from mcp_server.ESSENTIALS"
    assert "read_guide" in data("AGENTS.md")
