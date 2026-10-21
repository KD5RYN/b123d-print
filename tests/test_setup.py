"""First-run setup (setup.py, `b123d-print setup`, the save_setup tool): what it writes, and that
it never replaces a value without being told to."""

import io
import json
import sys
import tomllib

import pytest

from b123d_print import setup as st
from b123d_print.cli import main
from b123d_print.config import load_settings, set_user_setting, user_config_path
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
    raw = _toml(cfg / "b123d-print.toml")
    assert raw["print"] == {"printer": "bambu_lab_a1_mini"}
    assert raw["calibration"] == {"bambu_lab_a1_mini/any": {"hole_comp": 0.15}}  # per printer, in the workspace
    assert load_settings(cfg).hole_comp == 0.15
    assert not user_config_path().exists() and calibrated("bambu_lab_a1_mini", "") == {}  # calibration.toml untouched


def test_workspace_without_printer_stays_flat(cfg):
    assert main(["init", str(cfg)]) == 0
    st.apply(st.plan({"hole_comp": 0.15}, cfg / "b123d-print.toml"))
    assert _toml(cfg / "b123d-print.toml")["print"] == {"hole_comp": "0.15"}


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
    assert text.index("XYZ cube") < text.index("hole_coupon") and "filament changes" in text  # shrinkage: the slicer, first


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


def _server(ms, monkeypatch, root):
    """The MCP server as a shared (HTTP) server: settings go to the workspace's b123d-print.toml."""
    monkeypatch.setitem(ms.STATE, "root", root)
    monkeypatch.setitem(ms.STATE, "transport", "http")


def test_server_workspace_keeps_calibration_per_printer(tmp_path, monkeypatch):
    """Two printers in one HTTP workspace, two of them the same model: each keeps its own measured
    values, and use_printer switches what is in effect (issue #121)."""
    from b123d_print import mcp_server as ms

    root = tmp_path / "ws"
    _server(ms, monkeypatch, root)
    ms.use_printer(name="bambu_lab_a1_mini", material="pla")
    res = json.loads(ms.save_setup(hole_comp=0.2, calibration={"clearance": 0.15}))
    assert {(w["key"], w["for"]) for w in res["written"]} == {("hole_comp", "bambu_lab_a1_mini/pla"),
                                                              ("clearance", "bambu_lab_a1_mini/pla")}
    assert "every hole is cut 0.2 mm larger" in res["slicer"] and "bambu_lab_a1_mini/pla only" in res["slicer"]
    summary = json.loads(ms.use_printer(name="bambu_lab_p2s", nickname="p2s-garage"))
    assert summary["nickname"] == "p2s-garage" and summary["name"] == "bambu_lab_p2s"
    json.loads(ms.save_setup(hole_comp=0.3))
    ms.use_printer(name="bambu_lab_p2s", nickname="p2s-office")  # a second P2S
    json.loads(ms.save_setup(hole_comp=0.45))

    def effective():
        s = load_settings(root)
        return s.calibration_key, s.hole_comp, s.clearance

    assert effective() == ("p2s-office", 0.45, 0.2)
    ms.use_printer(name="p2s-garage")
    assert effective() == ("p2s-garage", 0.3, 0.2)
    assert load_settings(root).printer == "bambu_lab_p2s"  # the profile behind the nickname
    ms.use_printer(name="bambu_lab_a1_mini")
    assert effective() == ("bambu_lab_a1_mini", 0.2, 0.15)
    listed = json.loads(ms.list_parts())
    assert listed["settings"]["hole_comp"] == 0.2 and "nickname" not in listed["printer"]
    assert listed["printer"]["calibration"] == {"for": "bambu_lab_a1_mini/pla", "measured": {"hole_comp": 0.2, "clearance": 0.15}}
    ms.use_printer(name="p2s-office")
    assert json.loads(ms.list_parts())["printer"]["nickname"] == "p2s-office"
    raw = _toml(root / "b123d-print.toml")
    assert raw["printers"] == {"p2s-garage": "bambu_lab_p2s", "p2s-office": "bambu_lab_p2s"}
    assert not user_config_path().exists() and not (tmp_path / "cfg" / "b123d-print" / "calibration.toml").exists()


def test_server_old_flat_values_load_and_move(tmp_path, monkeypatch):
    from b123d_print import mcp_server as ms

    root = tmp_path / "ws"
    _server(ms, monkeypatch, root)
    ms.use_printer(name="bambu_lab_a1_mini", material="petg")
    path = root / "b123d-print.toml"
    for k, v in (("hole_comp", "0.25"), ("max_bridge", "14")):  # as an older save_setup wrote them
        set_user_setting(k, v, path)
    s = load_settings(root)
    assert (s.hole_comp, s.max_bridge) == (0.25, 14.0)  # old flat values still load
    res = json.loads(ms.save_setup(style="soft"))
    assert "move_flat=True" in res["next"] and "hole_comp, max_bridge" in res["next"]
    res = json.loads(ms.save_setup(move_flat=True))
    assert res["moved"] == {"values": {"hole_comp": "0.25", "max_bridge": "14"}, "to": "bambu_lab_a1_mini/any"}
    raw = _toml(path)
    assert "hole_comp" not in raw["print"] and raw["calibration"]["bambu_lab_a1_mini/any"] == {"hole_comp": 0.25, "max_bridge": 14}
    s = load_settings(root)
    assert (s.hole_comp, s.max_bridge) == (0.25, 14.0)  # the same values, now for this printer only
    ms.use_printer(name="bambu_lab_p2s")
    assert load_settings(root).hole_comp == 0.0  # no longer follows another printer


def test_slicer_note():
    """By default the slicer corrects holes; an opt-in hole_comp is built in, loudly, for one printer."""
    assert st.slicer_note(0.3, 0.4, "p2s-garage/pla") == (
        "HOLE COMPENSATION BUILT IN: every hole is cut 0.3 mm (0.4 mm for holes lying on their side) larger than drawn "
        "(hole_comp), for p2s-garage/pla only. Print these files with the slicer's X-Y hole compensation at 0 (or the "
        "holes are corrected twice), and not on another printer.")
    note = st.slicer_note(0.0)
    assert "true to size" in note and "X-Y hole compensation" in note and "half the diameter error" in note


def test_export_says_when_hole_comp_is_built_in(tmp_path, monkeypatch):
    from b123d_print import mcp_server as ms

    _server(ms, monkeypatch, tmp_path / "ws")
    ms.use_printer(name="bambu_lab_p2s", nickname="p2s-garage", material="petg")
    assert ms._baked_note(load_settings(tmp_path / "ws")) == ""  # the default: true to size, the slicer corrects
    json.loads(ms.save_setup(hole_comp=0))  # the slicer does it: recorded, still nothing built in
    assert ms._baked_note(load_settings(tmp_path / "ws")) == ""
    json.loads(ms.save_setup(hole_comp=0.45, overwrite=True))  # opt-in
    note = ms._baked_note(load_settings(tmp_path / "ws"))
    assert note.startswith("HOLE COMPENSATION BUILT IN") and "p2s-garage/petg only" in note
