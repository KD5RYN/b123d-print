import pytest
from build123d import Box

from b123d_print import profiles as pf
from b123d_print.checks import Fit
from b123d_print.cli import main
from b123d_print.config import load_settings, set_user_setting


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from b123d_print.config import _ENV

    for v in (*_ENV.values(), "B123D_PRINT_PRINTER"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path / "cfg" / "b123d-print"


def test_generic_is_default(cfg):
    s = load_settings()
    assert (s.printer, s.min_wall, s.max_overhang) == ("", 0.8, 45.0)
    assert Fit("part").run({"part": Box(900, 900, 900)}, None, s) == []  # nothing to check


def test_orca_table():
    p = pf.load_printer("bambu_lab_p1s")
    assert (p.bed_x, p.bed_y, p.nozzle) == (256, 256, 0.4) and p.min_wall == 0.9
    assert "elegoo_neptune_4_plus" in pf.search("printers", "neptune 4 plus")
    with pytest.raises(KeyError, match="bambu_lab_p1s"):
        pf.load_printer("p1s")


def test_fits():
    p = pf.Printer("t", bed_x=200, bed_y=100, height=50)
    assert pf.fits(p, (150, 80, 40))[0]
    ok, why = pf.fits(p, (80, 150, 40))
    assert ok and "turned" in why
    assert not pf.fits(p, (150, 80, 60))[0]
    assert not pf.fits(pf.Printer("d", bed_x=100, round_bed=True), (80, 80, 10))[0]  # 113 diagonal


def test_printer_settings_and_fit_check(cfg):
    (cfg / "printers").mkdir(parents=True)
    (cfg / "printers" / "tiny.toml").write_text('label = "Tiny"\nbed_x = 50\nbed_y = 50\nheight = 50\nnozzle = 0.6\n', encoding="utf-8")
    set_user_setting("hole_comp", "0.3")
    assert main(["printer", "use", "tiny", "--material", "petg"]) == 0
    s = load_settings()
    assert (s.printer, s.material, s.min_wall) == ("tiny", "petg", round(2 * 0.6 * 1.125, 2))
    assert s.hole_comp == 0.3  # user config value until calibrated
    assert main(["printer", "hole-comp", "0.45"]) == 0
    assert load_settings().hole_comp == 0.45  # calibration for tiny/petg wins
    f = Fit("part").run({"part": Box(60, 10, 10)}, None, load_settings())[0]
    assert f.level == "fail" and "Tiny" in f.message
    assert main(["printer", "use", "generic"]) == 0
    assert load_settings().printer == ""
    assert "[print]" in (cfg / "config.toml").read_text(encoding="utf-8")


def test_new_settings_defaults(cfg):
    s = load_settings()
    assert (s.press_fit, s.clearance, s.free_fit, s.pip_clearance, s.max_bridge) == (0.05, 0.2, 0.3, 0.3, 10.0)
    assert s.hole_comp_h == s.hole_comp == 0.0
    set_user_setting("hole_comp", "0.3")
    assert load_settings().hole_comp_h == 0.3  # follows hole_comp until set
    set_user_setting("hole_comp_h", "0.5")
    from b123d_print.config import hole_comp

    assert (hole_comp(), hole_comp(horizontal=True)) == (0.3, 0.5)


def test_calibrate_every_key(cfg, monkeypatch):
    (cfg / "printers").mkdir(parents=True)
    (cfg / "printers" / "tiny.toml").write_text('bed_x = 50\nbed_y = 50\nheight = 50\nmax_bridge = 15\n', encoding="utf-8")
    set_user_setting("free_fit", "0.35")
    assert main(["printer", "use", "tiny", "--material", "pla"]) == 0
    s = load_settings()
    assert (s.max_bridge, s.free_fit) == (15.0, 0.35)  # from the printer; user config until calibrated
    for key, value in (("free_fit", "0.25"), ("pip_clearance", "0.2"), ("max_bridge", "30"), ("hole_comp_h", "0.4")):
        assert main(["printer", "calibrate", key, value]) == 0
    s = load_settings()
    assert (s.free_fit, s.pip_clearance, s.max_bridge, s.hole_comp_h) == (0.25, 0.2, 30.0, 0.4)
    assert pf.calibrated("tiny", "petg") == {}  # another material: nothing measured
    monkeypatch.setenv("B123D_PRINT_MAX_BRIDGE", "12")
    assert load_settings().max_bridge == 12.0  # the environment still wins
    with pytest.raises(SystemExit):
        main(["printer", "calibrate", "min_wall", "1"])  # not a calibration value


def test_nicknames_keep_their_own_calibration(cfg):
    """Locally too: two of the same model, each with its own calibration in calibration.toml."""
    assert main(["printer", "use", "bambu_lab_p2s", "--nickname", "p2s-left", "--material", "pla"]) == 0
    assert main(["printer", "calibrate", "hole_comp", "0.3"]) == 0
    assert main(["printer", "use", "bambu_lab_p2s", "--nickname", "p2s-right"]) == 0
    assert main(["printer", "calibrate", "hole_comp", "0.5"]) == 0
    assert load_settings().hole_comp == 0.5
    assert main(["printer", "use", "p2s-left"]) == 0
    s = load_settings()
    assert (s.printer, s.nickname, s.hole_comp) == ("bambu_lab_p2s", "p2s-left", 0.3)
    assert pf.calibrated("p2s-right", "pla") == {"hole_comp": 0.5} and pf.calibrated("bambu_lab_p2s", "pla") == {}
    with pytest.raises(ValueError, match="already a printer profile"):
        pf.save_nickname("bambu_lab_a1_mini", "bambu_lab_p2s")
    with pytest.raises(KeyError):
        pf.save_nickname("p2s-ghost", "p2s-left")  # a nickname must point at a profile


def test_calibrate_into_the_workspace(cfg, tmp_path, monkeypatch, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)
    assert main(["init", str(ws)]) == 0
    assert main(["printer", "use", "bambu_lab_a1_mini", "--material", "pla"]) == 0
    assert main(["printer", "calibrate", "hole_comp", "0.2"]) == 0  # calibration.toml, as before
    assert main(["printer", "calibrate", "hole_comp", "0.35", "--workspace"]) == 0
    assert "every hole is cut 0.35 mm larger" in capsys.readouterr().out
    assert pf.calibrated("bambu_lab_a1_mini", "pla") == {"hole_comp": 0.2}
    assert pf.calibrated("bambu_lab_a1_mini", "pla", ws) == {"hole_comp": 0.35}  # the workspace wins key by key
    s = load_settings()
    assert s.hole_comp == 0.35
    from b123d_print.config import hole_comp_source

    assert hole_comp_source() == "workspace calibration"
    set_user_setting("hole_comp", "0.1", ws / "b123d-print.toml")
    assert load_settings().hole_comp == 0.1  # a flat workspace value still wins
