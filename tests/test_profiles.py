import pytest
from build123d import Box

from b123d_print import profiles as pf
from b123d_print.checks import Fit
from b123d_print.cli import main
from b123d_print.config import load_settings, set_user_setting


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for v in ("B123D_PRINT_HOLE_COMP", "B123D_PRINT_MIN_WALL", "B123D_PRINT_PRINTER"):
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
