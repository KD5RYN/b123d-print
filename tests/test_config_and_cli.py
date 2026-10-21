from pathlib import Path

from b123d_print.cli import main
from b123d_print.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def test_hole_comp_default_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("B123D_PRINT_HOLE_COMP", raising=False)
    assert load_settings(tmp_path).hole_comp == 0.0


def test_config_layers(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg" / "b123d-print"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text("[print]\nhole_comp = 0.4\nclearance = 0.3\n", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b123d-print.toml").write_text("[print]\nclearance = 0.25\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    s = load_settings(ws)
    assert (s.hole_comp, s.clearance) == (0.4, 0.25)  # workspace overrides user
    monkeypatch.setenv("B123D_PRINT_HOLE_COMP", "0.6")
    assert load_settings(ws).hole_comp == 0.6  # env overrides both


def test_formats(tmp_path, monkeypatch):
    import pytest

    from b123d_print.config import parse_formats

    assert parse_formats("3MF, .png") == ("3mf", "png")
    assert parse_formats("all") == ("step", "stl", "3mf", "png", "glb", "print", "hardware", "bom", "bom_csv")
    with pytest.raises(ValueError):
        parse_formats("obj")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "b123d-print.toml").write_text('[print]\nformats = ["3mf"]\n', encoding="utf-8")
    assert load_settings(ws).formats == ("3mf",)
    monkeypatch.chdir(ws)
    assert main(["new", "blk"]) == 0
    assert main(["build", "blk"]) == 0
    assert sorted(p.suffix for p in (ws / "parts/blk/out").iterdir()) == [".3mf"]
    assert main(["build", "blk", "--formats", "step,png"]) == 0
    assert {p.suffix for p in (ws / "parts/blk/out").iterdir()} >= {".step", ".png"}


def test_init_new_build_check(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    assert main(["init", str(ws)]) == 0
    assert (ws / "AGENTS.md").exists() and (ws / "b123d-print.toml").exists()
    monkeypatch.chdir(ws)
    assert main(["new", "bracket"]) == 0
    assert main(["new", "coupon", "--from", "hole_coupon"]) == 0
    assert main(["check"]) == 0
    assert main(["build", "bracket"]) == 0
    assert (ws / "parts/bracket/out/bracket.stl").exists()


def test_agents_md_in_sync():
    """The repo's AGENTS.md is the packaged workflow text, verbatim."""
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8") == (ROOT / "src/b123d_print/data/AGENTS.md").read_text(encoding="utf-8")


def test_template_renders():
    from b123d_print.cli import data

    code = data("part_template.py").format(name="x", title="X", description="d")
    compile(code, "x.py", "exec")


def test_single_part_alias(tmp_path, monkeypatch):
    """A bare Part from build() is "part" in checks, and the script's own name works too (issue #23)."""
    from b123d_print.project import load, run_checks
    from b123d_print.config import load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    p = tmp_path / "spacer_tube.py"
    p.write_text(
        "from build123d import Box\nfrom b123d_print import Wall\n"
        "def build(d=None):\n    return Box(20, 20, 10)\n"
        "def checks(d=None):\n    return [Wall('spacer_tube', 'XY', 0, label='by script name'), Wall('part', 'XY', 0)]\n",
        encoding="utf-8",
    )
    findings = run_checks(load(p), "", load_settings(tmp_path))
    walls = [f for f in findings if f.check == "wall"]
    assert len(walls) == 2 and all(f.level == "ok" for f in walls), [f.line() for f in findings]
    assert sum(f.check == "overhang" for f in findings) == 1  # the alias does not add a second part


def test_human_size():
    from b123d_print.mcp_server import _human_size

    assert (_human_size(512), _human_size(34_000), _human_size(2_500_000)) == ("512 B", "34 KB", "2.5 MB")


def test_mcp_subcommand_starts_the_server_cli(capsys):
    """`b123d-print mcp ...` is the MCP server (what `uvx b123d-print mcp` runs for registry clients)."""
    import pytest

    with pytest.raises(SystemExit) as e:
        main(["mcp", "--help"])
    assert e.value.code == 0 and "b123d-print-mcp" in capsys.readouterr().out


def test_server_json_matches_the_package():
    """The MCP Registry entry and the package always carry the same version and name. (The plugin's
    version follows the server version it runs: test_plugin_pins_the_released_package.)"""
    import json
    import tomllib

    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert server["version"] == server["packages"][0]["version"] == version
    assert server["packages"][0]["identifier"] == "b123d-print"
    assert f"mcp-name: {server['name']}" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_plugin_pins_the_released_package():
    """The Claude plugin runs the server with `uvx b123d-print==<pin> mcp` and ships a lockfile for that
    pin (exact versions and hashes, which the directory wants), pinned to a released version no newer than this one; it ships its own LICENSE,
    an icon, and no OS junk files."""
    import json
    import tomllib

    def ver(s):
        return tuple(int(x) for x in s.split("."))

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    mcp = json.loads((ROOT / "plugin/.mcp.json").read_text(encoding="utf-8"))["mcpServers"]["b123d-print"]
    deps = tomllib.loads((ROOT / "plugin/pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert len(deps) == 1 and deps[0].startswith("b123d-print==")
    pin = deps[0].removeprefix("b123d-print==")
    assert ver(pin) <= ver(version)  # the plugin moves to a release after it is on PyPI
    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert plugin["version"] == pin  # a release leaves plugin/ alone until its plugin-pin PR is merged
    assert mcp["command"] == "uvx" and mcp["args"] == [f"b123d-print=={pin}", "mcp"]  # the form a lock can pin
    lock = tomllib.loads((ROOT / "plugin/uv.lock").read_text(encoding="utf-8"))
    locked = [p for p in lock["package"] if p["name"] == "b123d-print"]
    assert [p["version"] for p in locked] == [pin], "run `uv lock --directory plugin` after changing the pin"
    assert locked[0]["source"] == {"registry": "https://pypi.org/simple"}
    assert (ROOT / "plugin/uv.lock").stat().st_size < 256 * 1024  # the directory reads files up to 256 KiB
    assert (ROOT / "plugin/LICENSE").read_text(encoding="utf-8") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert (ROOT / "plugin/.claude-plugin/icon.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    junk = [p for p in (ROOT / "plugin").rglob("*") if p.name in (".DS_Store", "Thumbs.db", "desktop.ini")]
    assert not junk, junk


def test_initialize_reports_the_package_version():
    """serverInfo in the MCP initialize response carries the package version (the SDK's default is "")."""
    from importlib.metadata import version

    import anyio
    from mcp.client import Client

    from b123d_print.mcp_server import mcp

    async def info():
        async with Client(mcp) as c:
            return c.server_info

    got = anyio.run(info)
    assert got.name == "b123d-print" and got.version == version("b123d-print") != ""
