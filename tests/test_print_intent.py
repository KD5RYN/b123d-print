"""Print intent (PRINT, issue #115): the vocabulary, where each recommendation comes from, the print
sheet keeping the facts while the part overrides the advice, and the overhang check accepting
declared overhangs without ever hiding a FAIL."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from build123d import Align, Box, Pos

import b123d_print
from b123d_print import checks as ck
from b123d_print import intent, printsheet, project
from b123d_print.config import Settings, load_settings

A = (Align.CENTER, Align.CENTER, Align.MIN)
WHY = "a coupon: it tests unsupported overhangs"


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # the user's own config stays out


def shelf():
    """A post with a flat shelf hanging off one side: a cantilever the overhang rule flags."""
    return Box(10, 10, 20, align=A) + Pos(10, 0, 18) * Box(10, 10, 2, align=A)


# --- vocabulary ---------------------------------------------------------------------------------


def test_vocabulary_normalized():
    got = intent.validate({"supports": "Build-Plate-Only", "walls": 3, "infill": 20, "infill_pattern": "gyroid",
                           "brim": 5, "orientation": "locked", "why": "  test  "})
    assert got == {"supports": "build_plate_only", "walls": 3, "infill": 20.0, "infill_pattern": "gyroid",
                   "brim": 5.0, "orientation": "locked", "why": "test"}
    assert intent.validate(None) == {} and intent.validate({}) == {}
    assert intent.validate({"brim": False, "why": "x"})["brim"] is False


def test_typo_is_an_error_listing_the_keys():
    with pytest.raises(ValueError) as e:
        intent.validate({"suports": "none", "why": "x"})
    msg = str(e.value)
    assert "suports" in msg and all(k in msg for k in intent.KEYS)


@pytest.mark.parametrize("bad", [{"supports": "sometimes", "why": "x"}, {"walls": 2.5, "why": "x"},
                                 {"walls": True, "why": "x"}, {"infill": 150, "why": "x"},
                                 {"orientation": "free", "why": "x"}, {"brim": -1, "why": "x"}, ["supports"]])
def test_bad_values(bad):
    with pytest.raises(ValueError):
        intent.validate(bad)


def test_why_required():
    with pytest.raises(ValueError, match="why"):
        intent.validate({"supports": "none"})


def test_bad_print_is_a_build_error(tmp_path):
    mod = SimpleNamespace(PRINT={"support": "none", "why": "x"}, build=lambda d: shelf(), __file__=str(tmp_path / "p.py"))
    found = project.run_checks(mod, "", Settings(), nudge=False)
    assert found[0].level == ck.FAIL and "unknown key" in found[0].message


# --- precedence and sources ---------------------------------------------------------------------


def test_precedence_part_then_settings_then_suggested(tmp_path):
    (tmp_path / "b123d-print.toml").write_text('[print]\nsupports = "tree"\nwalls = 3\ninfill = 25\n', encoding="utf-8")
    s = load_settings(tmp_path)
    assert (s.supports, s.walls, s.infill) == ("tree", 3, 25.0)
    mod = SimpleNamespace(PRINT={"walls": 5, "why": WHY})
    got = intent.resolve(mod, None, s)
    assert got["walls"] == (5, intent.PART) and got["supports"] == ("tree", intent.SETTINGS)
    assert got["infill"] == (25.0, intent.SETTINGS) and "brim" not in got and got["why"] == (WHY, intent.PART)
    bare = intent.resolve(SimpleNamespace(), None, Settings())
    assert set(bare) == {"why"}  # nothing set: the sheet suggests from the geometry


def test_user_config_under_workspace(tmp_path, monkeypatch):
    user = tmp_path / "xdg" / "b123d-print"
    user.mkdir(parents=True)
    (user / "config.toml").write_text('[print]\nsupports = "auto"\nwalls = 4\n', encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b123d-print.toml").write_text('[print]\nsupports = "none"\n', encoding="utf-8")
    s = load_settings(ws)
    assert (s.supports, s.walls) == ("none", 4)  # the workspace wins, the user config fills in


def test_bad_setting_is_an_error(tmp_path):
    (tmp_path / "b123d-print.toml").write_text('[print]\nsupports = "maybe"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="supports"):
        load_settings(tmp_path)


@dataclass(frozen=True)
class VDims:
    W: float = 20.0  # test
    PRINT: dict | None = field(default=None, hash=False, compare=False)  # test


def test_variant_overrides_module_print():
    mod = SimpleNamespace(PRINT={"supports": "none", "why": WHY}, Dims=VDims,
                          VARIANTS={"": {}, "tree": dict(PRINT={"supports": "tree", "why": "tall part"})})
    assert intent.declared(mod, project.dims(mod, ""))["supports"] == "none"
    d = project.dims(mod, "tree")
    assert intent.declared(mod, d) == {"supports": "tree", "why": "tall part"}
    assert intent.no_supports_why(mod, d) == ""
    hash(d)  # functools.cache on piece functions still works


# --- the print sheet ----------------------------------------------------------------------------


def _sheet(mod, s=None):
    return printsheet.sheet(mod, None, {"": shelf()}, s or Settings(), "t")


def test_sheet_keeps_facts_and_overrides_advice():
    base = _sheet(SimpleNamespace())
    assert "would need supports by the geometry" in base and "**Supports: on, suggested from the geometry/style**" in base
    mod = SimpleNamespace(PRINT={"supports": "none", "walls": 4, "infill": 30, "brim": 3, "orientation": "locked", "why": WHY})
    text = _sheet(mod)
    assert "would need supports by the geometry" in text  # the facts stay
    assert f"**Supports: none, set by the part**: {WHY}." in text and "print unsupported, as intended" in text
    assert "Supports: on" not in text
    assert f"**Walls: 4, set by the part**: {WHY}" in text and f"**Infill: 30 %, set by the part**" in text
    assert "The estimates assume 4 walls and 30% infill" in text
    assert "**Brim: 3 mm, set by the part**" in text and "**Orientation: locked, set by the part**" in text


def test_sheet_settings_source(tmp_path):
    s = Settings(supports="none", walls=3)
    text = _sheet(SimpleNamespace(), s)
    assert "**Supports: none, your settings**" in text and "would need them" in text
    assert "**Walls: 3, your settings**" in text and "**Infill: 15%, suggested from the geometry/style**" in text


def test_walls_change_the_estimate():
    plain, more = (printsheet.sheet(m, None, {"": Box(30, 30, 30, align=A)}, Settings(), "t")
                   for m in (SimpleNamespace(), SimpleNamespace(PRINT={"walls": 6, "infill": 50, "why": "x"})))
    grams = [float(t.split("| 30 × 30 × 30 |")[1].split("|")[1]) for t in (plain, more)]
    assert grams[1] > grams[0]


# --- the overhang check -------------------------------------------------------------------------


def test_declared_no_supports_accepts_overhangs():
    parts = {"part": shelf()}
    warn = ck.Overhang("part").run(parts, None, Settings())
    assert warn[0].level == ck.WARN
    ok = ck.Overhang("part", accept=WHY).run(parts, None, Settings())
    assert ok[0].level == ck.OK and "accepted" in ok[0].message and WHY in ok[0].message
    assert ok[0].data["accepted"] == WHY and ok[0].data["faces"]  # still reported, with the facts


def test_accept_never_hides_a_fail():
    found = ck.Overhang("part", fail=True, accept=WHY).run({"part": shelf()}, None, Settings())
    assert found[0].level == ck.FAIL and "accepted" not in found[0].message


def test_check_specs_take_the_intent():
    mod = SimpleNamespace(PRINT={"supports": "none", "why": WHY},
                          checks=lambda d: [ck.Overhang("part", fail=True)])
    specs = project.check_specs(mod, None, {"part": shelf()}, None)
    over = [s for s in specs if isinstance(s, ck.Overhang)]
    assert over and all(s.accept == WHY for s in over) and over[0].fail
    tree = SimpleNamespace(PRINT={"supports": "tree", "why": "tall"})
    assert not any(s.accept for s in project.check_specs(tree, None, {"part": shelf()}, None) if isinstance(s, ck.Overhang))


# --- the calibration coupons --------------------------------------------------------------------


@pytest.mark.parametrize("name", ["hole_coupon", "fit_coupon", "overhang_bridge_coupon"])
def test_coupon_sheets_say_no_supports(name):
    script = Path(b123d_print.__file__).parent / "examples" / name / f"{name}.py"
    mod = project.load(script)
    d = project.dims(mod, "")
    assert intent.no_supports_why(mod, d)
    text = printsheet.sheet(mod, d, project.printables(mod, d), Settings(), name)
    assert "**Supports: none, set by the part**: a calibration coupon" in text
    assert "Supports: on" not in text
