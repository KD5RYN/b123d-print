"""The review checklist (#146): per part and script version, which design steps ran; the block
that ends build_part, check, design_metrics and export; export's warn / required / off modes."""

import json
import os
from pathlib import Path

import anyio
import pytest

from b123d_print import review
from b123d_print.config import load_settings

SCRIPT = '''from dataclasses import dataclass
from build123d import Box, Pos


@dataclass(frozen=True)
class Dims:
    L: float = 12.0  # typed by the user
    STYLE: str = ""  # design review style


VARIANTS = {"": {}}


def build(d):
    return Pos(0, 0, d.L / 2) * Box(d.L, d.L, d.L)
'''


def _part(root: Path, name: str, code: str) -> Path:
    p = root / "parts" / name / f"{name}.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(code, encoding="utf-8")
    return p


@pytest.fixture()
def server(tmp_path, monkeypatch):
    from b123d_print import mcp_server as m
    from b123d_print import sandbox

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("B123D_PRINT_REVIEW", raising=False)
    (tmp_path / "b123d-print.toml").write_text('[workspace]\nparts_dir = "parts"\n', encoding="utf-8")
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setitem(m.STATE, "max_builds", 1)
    monkeypatch.setitem(m.STATE, "review_shown", {})
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / ".slots")
    return m, tmp_path


def _mode(root: Path, mode: str) -> None:
    (root / "b123d-print.toml").write_text(f'[workspace]\nparts_dir = "parts"\nreview = "{mode}"\n', encoding="utf-8")


# --- the state, without a server ---------------------------------------------------------------

def test_the_checklist_is_kept_per_script_version(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT)
    s = load_settings(p)
    c = review.checklist("cube", p, s)
    assert [i.key for i in c.missing] == ["style", "check", "look", "metrics", "orient"]
    review.record(p, "check", passed=True)
    review.record(p, "preview")
    assert (p.parent / "out" / ".cache" / review.STATE_FILE).is_file()  # next to the build cache
    c = review.checklist("cube", p, s)
    assert "check" not in [i.key for i in c.missing]
    p.write_text(SCRIPT.replace("12.0", "13.0"), encoding="utf-8")  # an edit: a new version, nothing done yet
    assert review.steps(p) == {} and "check" in [i.key for i in review.checklist("cube", p, s).missing]
    p.write_text(SCRIPT, encoding="utf-8")  # back to the earlier version: its steps are found again
    assert set(review.steps(p)) == {"check", "preview"}


def test_a_step_is_not_recorded_on_a_version_it_did_not_run_on(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT)
    before = review.script_hash(p)
    p.write_text(SCRIPT.replace("12.0", "14.0"), encoding="utf-8")  # edited while the check ran
    review.record(p, "check", version=before, passed=True)
    assert review.steps(p) == {}


def test_only_missing_steps_carry_a_call(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT.replace('STYLE: str = ""', 'STYLE: str = "structural"'))
    s = load_settings(p)
    review.record(p, "check", passed=True)
    text = review.checklist("cube", p, s).block()
    assert text.splitlines()[0] == "Before printing cube (style: structural):"
    assert "  ✓ check passed (this version)" in text.splitlines()
    assert "  ✗ design review not run: design_metrics('cube', style='structural')" in text
    assert "suggest_orientation('cube', load=" in text  # structural: the load direction
    assert "render_preview('cube'), then section('cube', 'XY'" in text
    for step in ("preview", "section", "orient"):
        review.record(p, step)
    review.record(p, "metrics", style="modern")  # the wrong style: run it again
    assert "design review ran with style 'modern', not 'structural': design_metrics('cube', style='structural')" \
        in review.checklist("cube", p, s).block()
    review.record(p, "metrics", style="structural")
    c = review.checklist("cube", p, s)
    assert not c.missing and c.block().startswith("Ready to print cube (style: structural)") and "\n" not in c.block()


def test_a_failed_check_and_no_style(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT)
    review.record(p, "check", passed=False)
    text = review.checklist("cube", p, load_settings(p)).block()
    assert "✗ check FAILED on this version: fix every FAIL, then check('cube')" in text
    assert "✗ no style chosen: ask the user which style" in text and "set_params('cube', {'STYLE': '<style>'})" in text
    (tmp_path / "b123d-print.toml").write_text('[workspace]\nstyle = "rugged"\n', encoding="utf-8")
    assert "✓ style: rugged (the workspace default)" in review.checklist("cube", p, load_settings(p)).block()


def test_what_the_script_declares_is_read_without_running_it():
    d = review.declared(SCRIPT.replace('STYLE: str = ""', 'STYLE: str = "soft"'))
    assert d.style == "soft" and d.style_field and not d.exempt and not d.locked
    d = review.declared('STYLE = "modern"\nPRINT = {"orientation": "locked", "review": "exempt", "why": "a coupon"}\n')
    assert d.style == "modern" and not d.style_field and d.exempt == "a coupon" and d.locked
    assert review.declared("def broken(:\n") == review.Declared()


@pytest.mark.parametrize("name", ["hole_coupon", "fit_coupon", "overhang_bridge_coupon"])
def test_calibration_coupons_are_exempt(name):
    from importlib.resources import files

    src = files("b123d_print").joinpath("examples", name, f"{name}.py").read_text(encoding="utf-8")
    assert review.declared(src).exempt.startswith("a calibration coupon")


def test_intent_accepts_review_exempt_only():
    from b123d_print import intent

    assert intent.validate({"review": "exempt", "why": "a coupon"})["review"] == "exempt"
    with pytest.raises(ValueError, match="review takes"):
        intent.validate({"review": "skip", "why": "a coupon"})


def test_the_review_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("B123D_PRINT_REVIEW", raising=False)
    assert load_settings(tmp_path).review == "warn"
    _mode(tmp_path, "Required")
    assert load_settings(tmp_path).review == "required"
    monkeypatch.setenv("B123D_PRINT_REVIEW", "off")  # a shared server's operator
    assert load_settings(tmp_path).review == "off"
    monkeypatch.delenv("B123D_PRINT_REVIEW")
    _mode(tmp_path, "sometimes")
    with pytest.raises(ValueError, match="review must be warn, required or off"):
        load_settings(tmp_path)


@pytest.mark.symlinks
def test_never_written_through_a_link(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (p.parent / "out").mkdir()
    os.symlink(elsewhere, p.parent / "out" / ".cache")  # the sandboxed script can write out/
    review.record(p, "check", passed=True)
    assert list(elsewhere.iterdir()) == [] and review.steps(p) == {}


def test_a_huge_or_broken_state_file_is_ignored(tmp_path):
    p = _part(tmp_path, "cube", SCRIPT)
    review.record(p, "check", passed=True)
    f = p.parent / "out" / ".cache" / review.STATE_FILE
    f.write_text("{not json", encoding="utf-8")
    assert review.steps(p) == {}
    f.write_text(json.dumps({"versions": {"x": {"pad": "y" * review.MAX_BYTES}}}), encoding="utf-8")
    assert review.steps(p) == {}
    review.record(p, "check", passed=True)  # rewritten from scratch
    assert review.steps(p) == {"check": {"passed": True}}


# --- through the MCP tools (real sandboxed builds) ---------------------------------------------

def test_the_tools_track_the_steps_and_export_warns(server):
    m, root = server
    _part(root, "cube", SCRIPT.replace('STYLE: str = ""', 'STYLE: str = "functional"'))
    res = json.loads(anyio.run(m.build_part, "cube"))
    block = res["before_printing"]
    assert block[0] == "Before printing cube (style: functional):" and "  ✗ check not run on this version: check('cube')" in block
    again = json.loads(anyio.run(m.build_part, "cube"))["before_printing"]  # nothing changed: one short line
    assert again == ["Before printing cube: 4 steps left; next: check('cube')"]
    out = anyio.run(m.check, "cube")
    assert out.startswith("PASSED") and "✓ check passed (this version)" in out
    out = anyio.run(lambda: m.export("cube", formats="3mf,print", view="none"))[0]
    assert out.startswith("Exported WITHOUT the preview and a section, the design review (design_metrics), "
                          "the orientation check (suggest_orientation). Tell the user")
    assert "The print sheet records it." in out and "✗ design review not run: design_metrics('cube', style='functional')" in out
    sheet = (root / "parts" / "cube" / "out" / "print" / "cube_print.md").read_text(encoding="utf-8")
    assert "## Design review" in sheet and "Exported **without** the preview and a section" in sheet
    assert "- MISSING: design review not run" in sheet

    anyio.run(lambda: m.render_preview("cube", size="small", inline=False))
    anyio.run(lambda: m.section("cube", "XY", 3.0, size="small", inline=False))
    out = anyio.run(lambda: m.design_metrics("cube"))
    assert "✓ design review run (style: functional)" in out and "suggest_orientation('cube')" in out
    anyio.run(m.suggest_orientation, "cube")
    out = anyio.run(lambda: m.export("cube", formats="3mf,print", view="none"))[0]
    assert "WITHOUT" not in out and "Before printing" not in out
    sheet = (root / "parts" / "cube" / "out" / "print" / "cube_print.md").read_text(encoding="utf-8")
    assert "Done on the exported version: style functional, check passed" in sheet

    m.write_part("cube", SCRIPT.replace("12.0", "15.0").replace('STYLE: str = ""', 'STYLE: str = "functional"'))
    res = json.loads(anyio.run(m.build_part, "cube"))  # an edit resets the checklist
    assert "  ✗ check not run on this version: check('cube')" in res["before_printing"]


def test_export_required_refuses_until_done_or_skipped(server):
    m, root = server
    _mode(root, "required")
    _part(root, "cube", SCRIPT)
    out = anyio.run(lambda: m.export("cube", formats="3mf,print", view="none"))[0]
    assert out.startswith('NOT EXPORTED: this workspace requires the design steps before export (review = "required")')
    assert "check('cube')" in out and "export('cube', skip_review=\"<the user's reason>\")" in out
    assert not (root / "parts" / "cube" / "out" / "print").exists()
    out = anyio.run(lambda: m.export("cube", formats="3mf,print", view="none", skip_review="user wants a quick test print"))[0]
    assert out.startswith("Exported WITHOUT a chosen style, a passing check") and "(skipped on purpose: user wants a quick test print)" in out
    sheet = (root / "parts" / "cube" / "out" / "print" / "cube_print.md").read_text(encoding="utf-8")
    assert "Skipped on purpose: user wants a quick test print" in sheet


def test_review_off_is_the_old_behaviour(server):
    m, root = server
    _mode(root, "off")
    _part(root, "cube", SCRIPT)
    assert "before_printing" not in json.loads(anyio.run(m.build_part, "cube"))
    assert "Before printing" not in anyio.run(m.check, "cube")
    out = anyio.run(lambda: m.export("cube", formats="3mf,print", view="none"))[0]
    assert out.startswith("Exported 2 file(s)") and "Before printing" not in out
    assert "Design review" not in (root / "parts" / "cube" / "out" / "print" / "cube_print.md").read_text(encoding="utf-8")


def test_an_exempt_part_is_never_nagged(server):
    m, root = server
    _mode(root, "required")
    _part(root, "coupon", SCRIPT + 'PRINT = {"review": "exempt", "why": "a calibration coupon"}\n')
    assert "before_printing" not in json.loads(anyio.run(m.build_part, "coupon"))
    out = anyio.run(lambda: m.export("coupon", formats="3mf,print", view="none"))[0]
    assert out.startswith("Exported 2 file(s)")
    assert "Design review" not in (root / "parts" / "coupon" / "out" / "print" / "coupon_print.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("remote", ["http", "ssh"])
def test_the_same_over_http_and_ssh(server, monkeypatch, remote):
    """Over HTTP each workspace keeps its own checklist (the state is in the part's out/.cache/);
    over SSH it is the stdio server on the remote machine: the same blocks either way."""
    m, root = server
    if remote == "http":
        monkeypatch.setitem(m.STATE, "transport", "http")
        monkeypatch.setitem(m.STATE, "link_secret", b"0" * 32)
    else:
        monkeypatch.setitem(m.STATE, "ssh_dest", "me@cad")

    async def call(ws, tool, *a, **kw):
        tok = m._WORKSPACE.set(ws)
        try:
            return await getattr(m, tool)(*a, **kw)
        finally:
            m._WORKSPACE.reset(tok)

    names = ["alice", "bob"] if remote == "http" else [None]
    for ws in names:
        tok = m._WORKSPACE.set(ws)
        try:
            _part(m._root(), "cube", SCRIPT.replace('STYLE: str = ""', 'STYLE: str = "modern"'))
        finally:
            m._WORKSPACE.reset(tok)
    out = anyio.run(call, names[0], "check", "cube")
    assert "✓ check passed (this version)" in out and str(root) not in out
    if remote == "http":  # the other workspace's part of the same name has done nothing yet
        res = json.loads(anyio.run(call, "bob", "build_part", "cube"))
        assert "  ✗ check not run on this version: check('cube')" in res["before_printing"]
        assert (root / "workspaces" / "alice" / "parts" / "cube" / "out" / ".cache" / review.STATE_FILE).is_file()
    out = anyio.run(lambda: call(names[0], "export", "cube", formats="3mf", view="none"))[0]
    assert out.startswith("Exported WITHOUT the preview and a section") and "design_metrics('cube', style='modern')" in out
    assert "download_part('cube')" in out  # the bring-it-home step still ends the result
