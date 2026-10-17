from pathlib import Path

from cadkit.cli import main
from cadkit.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_hole_comp_default_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("CADKIT_HOLE_COMP", raising=False)
    assert load_settings(tmp_path).hole_comp == 0.0


def test_config_layers(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg" / "cadkit"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text("[print]\nhole_comp = 0.4\nclearance = 0.3\n")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "cadkit.toml").write_text("[print]\nclearance = 0.25\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    s = load_settings(ws)
    assert (s.hole_comp, s.clearance) == (0.4, 0.25)  # workspace overrides user
    monkeypatch.setenv("CADKIT_HOLE_COMP", "0.6")
    assert load_settings(ws).hole_comp == 0.6  # env overrides both


def test_init_new_build_check(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    assert main(["init", str(ws)]) == 0
    assert (ws / "AGENTS.md").exists() and (ws / "cadkit.toml").exists()
    monkeypatch.chdir(ws)
    assert main(["new", "bracket"]) == 0
    assert main(["new", "coupon", "--from", "hole_coupon"]) == 0
    assert main(["check"]) == 0
    assert main(["build", "bracket"]) == 0
    assert (ws / "parts/bracket/out/bracket.stl").exists()


def test_agents_md_in_sync():
    """The repo's AGENTS.md is the packaged workflow text, verbatim."""
    assert (ROOT / "AGENTS.md").read_text() == (ROOT / "src/cadkit/data/AGENTS.md").read_text()


def test_template_renders():
    from cadkit.cli import data

    code = data("part_template.py").format(name="x", title="X", description="d")
    compile(code, "x.py", "exec")
