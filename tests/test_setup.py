"""First-run setup (setup.py, `b123d-print setup`, the save_setup tool): what it writes, and that
it never replaces a value without being told to."""

import io
import json
import sys
import tomllib

import pytest

from b123d_print import setup as st
from b123d_print.cli import main
from b123d_print.config import load_settings, user_config_path
from b123d_print.profiles import calibrated


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for var in ("B123D_PRINT_HOLE_COMP", "B123D_PRINT_FORMATS", "B123D_PRINT_PRINTER"):
        monkeypatch.delenv(var, raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    return ws


def _toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_writes_user_config_and_calibration():
    changes = st.plan({"printer": "bambu_lab_a1_mini", "material": "PETG", "formats": "3MF, png", "style": "structural",
                       "hole_comp": "0.2"}, user_config_path())
    written = st.apply(changes)
    assert len(written) == 5
    assert _toml(user_config_path())["print"] == {"printer": "bambu_lab_a1_mini", "material": "petg", "formats": "3mf,png",
                                                  "style": "structural"}
    assert calibrated("bambu_lab_a1_mini", "petg") == {"hole_comp": 0.2}  # per printer + material, not global
    s = load_settings()
    assert (s.printer, s.material, s.formats, s.style, s.hole_comp) == ("bambu_lab_a1_mini", "petg", ("3mf", "png"), "structural", 0.2)


def test_never_overwrites_without_confirmation():
    st.apply(st.plan({"material": "petg", "style": "rugged"}, user_config_path()))
    changes = st.plan({"material": "pla", "style": "rugged", "formats": "3mf"}, user_config_path())
    conflict = {c.key for c in changes if c.conflict}
    assert conflict == {"material"} and [c.key for c in changes if c.same] == ["style"]
    written = st.apply(changes)
    assert [c.key for c in written] == ["formats"]
    assert _toml(user_config_path())["print"]["material"] == "petg"
    assert "kept petg" in st.report(changes, written)
    st.apply(st.plan({"material": "pla"}, user_config_path(), overwrite=True), overwrite=True)
    assert _toml(user_config_path())["print"]["material"] == "pla"


def test_workspace_file_keeps_the_rest(cfg):
    assert main(["init", str(cfg)]) == 0
    written = st.apply(st.plan({"printer": "bambu_lab_a1_mini", "hole_comp": 0.15}, cfg / "b123d-print.toml"))
    assert {c.where for c in written} == {cfg / "b123d-print.toml"}  # not calibration.toml: a workspace value
    text = (cfg / "b123d-print.toml").read_text(encoding="utf-8")
    assert 'parts_dir = "parts"' in text and "# hole_comp = 0.0" in text  # the template's lines stay
    assert _toml(cfg / "b123d-print.toml")["print"] == {"printer": "bambu_lab_a1_mini", "hole_comp": "0.15"}
    assert load_settings(cfg).hole_comp == 0.15
    assert not user_config_path().exists()


@pytest.mark.parametrize("answers, match", [
    ({"printer": "no_such_printer"}, "no printer profile"),
    ({"material": "unobtainium"}, "no material profile"),
    ({"formats": "obj"}, "unknown format"),
    ({"style": "no_such_style"}, "no style"),
    ({"hole_comp": "a bit"}, "must be a number"),
    ({"color": "red"}, "unknown setup key"),
])
def test_bad_answers_write_nothing(answers, match):
    with pytest.raises((KeyError, ValueError), match=match):
        st.plan(answers, user_config_path())
    assert not user_config_path().exists()


def test_generic_and_empty_answers_are_skipped():
    assert st.plan({"printer": "generic", "material": "", "formats": None}, user_config_path()) == []


def test_next_steps_order():
    text = st.next_steps(False)
    assert text.index("hole_coupon") < text.index("fit_coupon") < text.index("overhang_bridge_coupon")
    assert "hole_coupon" not in st.next_steps(True) and "1. fit_coupon" in st.next_steps(True)


def test_cli_flags(capsys):
    assert main(["setup", "--printer", "bambu a1 mini", "--material", "pla", "--formats", "3mf,png", "--no-input"]) == 0
    assert load_settings().printer == "bambu_lab_a1_mini"  # search words with one match
    assert main(["setup", "--material", "petg", "--no-input"]) == 0
    assert "kept pla" in capsys.readouterr().out and load_settings().material == "pla"
    assert main(["setup", "--material", "petg", "--overwrite", "--no-input"]) == 0
    assert load_settings().material == "petg"
    with pytest.raises(SystemExit, match="no printer profile"):
        main(["setup", "--printer", "bambu", "--no-input"])  # many matches: no guess


def test_cli_workspace_flag(cfg):
    assert main(["setup", "--workspace", "--style", "soft", "--no-input"]) == 0
    assert (cfg / "AGENTS.md").exists() and _toml(cfg / "b123d-print.toml")["print"]["style"] == "soft"


def test_cli_asks(monkeypatch, capsys):
    st.apply(st.plan({"material": "petg"}, user_config_path()))
    monkeypatch.setattr(sys, "stdin", io.StringIO("bambu a1\n2\npla\n3mf\nstructural\n0.25\ny\n"))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "bambu_lab_a1_mini" in out and "material is petg" in out
    s = load_settings()
    assert (s.printer, s.material, s.formats, s.style, s.hole_comp) == ("bambu_lab_a1_mini", "pla", ("3mf",), "structural", 0.25)


def test_mcp_save_setup(tmp_path, monkeypatch):
    from b123d_print import mcp_server as ms

    monkeypatch.setitem(ms.STATE, "root", tmp_path / "ws")
    res = json.loads(ms.save_setup(printer="bambu_lab_a1_mini", formats="3mf,png"))
    assert {w["key"] for w in res["written"]} == {"printer", "formats"} and res["printer"]["mode"] == "printer"
    res = json.loads(ms.save_setup(formats="step"))
    assert res["conflicts"] == [{"key": "formats", "now": "3mf,png", "answer": "step"}] and "overwrite=True" in res["next"]
    res = json.loads(ms.save_setup(formats="step", overwrite=True))
    assert res["settings"]["formats"] == ["step"]
    with pytest.raises(ms.ToolError, match="did you mean"):
        ms.save_setup(printer="bambu a1")
