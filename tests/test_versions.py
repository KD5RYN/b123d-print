"""Version history (#125): save, list and restore on a temp git repo; restore is a new commit;
the repository's hooks, fsmonitor and filters never run; no git, no repo; shared servers run no git."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from b123d_print import versions as v
from b123d_print.cli import init_workspace, main, new_part

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

SCRIPT = '''from dataclasses import dataclass


@dataclass(frozen=True)
class Dims:
    ARM_L: float = {arm}  # typed by the user
    WIDTH: float = 20.0  # typed by the user


def build(d): ...
'''


def git(ws: Path, *args: str) -> str:
    env = {k: val for k, val in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",  # CI runners have no git identity
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")
    return subprocess.run(["git", *args], cwd=ws, env=env, capture_output=True, text=True, check=True).stdout.strip()


def write(ws: Path, arm: float, part: str = "shelf_bracket") -> Path:
    p = ws / "parts" / part / f"{part}.py"
    p.write_text(SCRIPT.format(arm=arm), encoding="utf-8", newline="")
    return p


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    init_workspace(w)
    new_part(w, "parts", "shelf_bracket")
    write(w, 115.0)
    (w / "parts" / "shelf_bracket" / "out").mkdir()
    (w / "parts" / "shelf_bracket" / "out" / "shelf_bracket.stl").write_bytes(b"made again by export")
    (w / "parts" / "shelf_bracket" / "ref").mkdir()
    (w / "parts" / "shelf_bracket" / "ref" / "scan.png").write_bytes(b"\x89PNG scan")
    v.start(w)
    return w


@pytest.fixture
def server(ws, monkeypatch):
    """The MCP server on this workspace, run locally (stdio): never the transport another test left behind."""
    from b123d_print import mcp_server as m

    monkeypatch.setitem(m.STATE, "root", ws)
    monkeypatch.setitem(m.STATE, "transport", "stdio")
    monkeypatch.setitem(m.STATE, "ssh_dest", None)
    token = m._WORKSPACE.set(None)
    yield m
    m._WORKSPACE.reset(token)


def commits(ws: Path) -> list[str]:
    return git(ws, "log", "--format=%H").split()


def test_start_writes_gitignore_and_saves_only_the_source(ws):
    gi = (ws / ".gitignore").read_text(encoding="utf-8")
    for line in ("out/", ".mcp.json", "*.token", "__pycache__/", "*.zip"):
        assert line in gi.splitlines()
    (ws / ".mcp.json").write_text('{"token": "secret"}', encoding="utf-8")
    (ws / "parts" / "shelf_bracket" / "MEASURE.md").write_text("arm 115", encoding="utf-8")
    (ws / "parts" / "shelf_bracket" / "notes.txt").write_text("not saved", encoding="utf-8")
    out = v.save(ws, "first version")
    assert out.startswith("Saved the project") and "shelf_bracket: new part" in out
    tracked = set(git(ws, "ls-files").splitlines())
    assert tracked == {".gitignore", "b123d-print.toml", "parts/shelf_bracket/shelf_bracket.py",
                       "parts/shelf_bracket/MEASURE.md", "parts/shelf_bracket/ref/scan.png"}
    assert v.save(ws, "again").startswith("Nothing to save")
    assert "start" in v.start(ws) or "already" in v.start(ws)  # a second start changes nothing
    assert (ws / ".gitignore").read_text(encoding="utf-8") == gi


def test_gitignore_keeps_the_users_lines(tmp_path):
    (tmp_path / ".gitignore").write_text("mine/\nout/", encoding="utf-8")
    added = v.write_gitignore(tmp_path)
    assert "out/" not in added and ".mcp.json" in added
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("mine/\nout/\n") and text.count("out/") == 1


def test_save_list_restore(ws):
    v.save(ws, "first")
    write(ws, 130.0)
    out = v.save(ws, "arm 115 → 130 mm", part="shelf_bracket")
    assert "version 2" in out and "ARM_L 115 → 130" in out
    listing = v.history(ws, "shelf_bracket")
    assert "1  " in listing and "2  " in listing and "ARM_L 115 → 130" in listing
    assert "Not saved yet" not in listing
    write(ws, 150.0)
    assert "Not saved yet" in v.history(ws, "shelf_bracket")
    v.save(ws, "longer")

    before = commits(ws)
    out = v.restore(ws, "shelf_bracket", "1")
    assert "ARM_L 150 → 115" in out and "new version 4" in out
    assert "ARM_L: float = 115.0" in (ws / "parts/shelf_bracket/shelf_bracket.py").read_text(encoding="utf-8")
    after = commits(ws)
    # a NEW commit on top: every earlier version is still there, nothing reset or rewritten
    assert after[1:] == before and len(after) == len(before) + 1
    assert git(ws, "rev-parse", "HEAD^") == before[0]
    assert git(ws, "status", "--porcelain", "--", "parts") == ""
    # by commit id too, and the restore shows in the list
    assert "ARM_L 115 → 150" in v.restore(ws, "shelf_bracket", before[0][:9])
    assert "Restore shelf_bracket to version 3" in v.history(ws, "shelf_bracket")
    assert "already the same" in v.restore(ws, "shelf_bracket", "3")


def test_restore_keeps_later_files_and_refuses_unsaved_changes(ws):
    v.save(ws, "first")
    (ws / "parts/shelf_bracket/ref/later.stl").write_bytes(b"solid later")
    write(ws, 140.0)
    v.save(ws, "later")
    write(ws, 999.0)  # not saved
    with pytest.raises(v.VersionError, match="not saved"):
        v.restore(ws, "shelf_bracket", "1")
    assert "999.0" in (ws / "parts/shelf_bracket/shelf_bracket.py").read_text(encoding="utf-8")
    v.save(ws, "999")
    out = v.restore(ws, "shelf_bracket", "1")
    assert (ws / "parts/shelf_bracket/ref/later.stl").read_bytes() == b"solid later"  # never deleted
    assert "kept" in out and "later.stl" in out


@pytest.mark.parametrize("version", ["HEAD~1", "--all", "-p", "1;rm -rf /", "0", "../x", "main", "abc"])
def test_bad_versions_refused(ws, version):
    v.save(ws, "first")
    with pytest.raises(v.VersionError):
        v.restore(ws, "shelf_bracket", version)


@pytest.mark.parametrize("part", ["../shelf_bracket", "Shelf", "a/b", "", "-p", "shelf_bracket/../x"])
def test_bad_part_names_refused(ws, part):
    for call in (lambda: v.save(ws, "x", part), lambda: v.history(ws, part), lambda: v.restore(ws, part, "1")):
        with pytest.raises(v.VersionError, match="bad part name"):
            call()


def test_version_of_another_part_refused(ws):
    new_part(ws, "parts", "hook")
    v.save(ws, "first")
    write(ws, 1.0, "hook")
    v.save(ws, "hook only", part="hook")
    sha = commits(ws)[0]
    with pytest.raises(v.VersionError, match="did not change shelf_bracket"):
        v.restore(ws, "shelf_bracket", sha)


def _marker_script(path: Path, marker: Path) -> Path:
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.mark.posix(reason="hook scripts need a POSIX shell")
def test_repository_hooks_never_run(ws, tmp_path):
    marker = tmp_path / "HOOK_RAN"
    hooks = ws / ".git" / "hooks"
    for name in ("pre-commit", "commit-msg", "post-commit", "post-checkout", "post-index-change", "reference-transaction"):
        _marker_script(hooks / name, marker)
    other = tmp_path / "evil_hooks"
    other.mkdir()
    for name in ("pre-commit", "post-commit", "reference-transaction"):
        _marker_script(other / name, marker)
    git(ws, "config", "core.hooksPath", str(other))  # the repository's own setting
    assert sys.platform != "win32"
    v.save(ws, "first")
    write(ws, 130.0)
    v.save(ws, "second")
    v.history(ws, "shelf_bracket")
    v.restore(ws, "shelf_bracket", "1")
    assert not marker.exists()
    git(ws, "commit", "--allow-empty", "-m", "plain git does run them")  # the hooks are real
    assert marker.exists()


@pytest.mark.posix(reason="the fsmonitor hook needs a POSIX shell")
def test_fsmonitor_never_runs(ws, tmp_path):
    marker = tmp_path / "FSMONITOR_RAN"
    script = _marker_script(tmp_path / "fsmonitor.sh", marker)
    git(ws, "config", "core.fsmonitor", str(script))
    v.save(ws, "first")
    write(ws, 130.0)
    v.save(ws, "second")
    v.history(ws)
    v.restore(ws, "shelf_bracket", "1")
    assert not marker.exists()
    subprocess.run(["git", "status"], cwd=ws, capture_output=True)  # plain git does run it
    assert marker.exists()


@pytest.mark.posix(reason="the filter command needs a POSIX shell")
def test_repository_filters_refused(ws, tmp_path):
    marker = tmp_path / "FILTER_RAN"
    git(ws, "config", "filter.evil.clean", f"touch '{marker}'; cat")
    (ws / ".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")
    for call in (lambda: v.save(ws, "x"), lambda: v.history(ws), lambda: v.restore(ws, "shelf_bracket", "1")):
        with pytest.raises(v.VersionError, match="filter.evil.clean"):
            call()
    assert not marker.exists()


def test_worktree_outside_the_workspace_refused(ws, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    git(ws, "config", "core.worktree", str(tmp_path / "elsewhere"))
    with pytest.raises(v.VersionError, match="does not contain the workspace"):
        v.save(ws, "x")


@pytest.mark.symlinks
def test_restore_writes_no_symlinks(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("keep", encoding="utf-8")
    v.save(ws, "first")
    ref = ws / "parts/shelf_bracket/ref"
    os.symlink(secret, ref / "link.txt")
    git(ws, "add", "-f", "parts/shelf_bracket/ref/link.txt")  # a symlink in history, saved by plain git
    git(ws, "commit", "-qm", "link")
    assert "link.txt" not in v.save(ws, "nothing new")  # save itself never takes a symlink
    os.unlink(ref / "link.txt")
    git(ws, "commit", "-qam", "unlink")
    out = v.restore(ws, "shelf_bracket", commits(ws)[1][:12])
    assert not (ref / "link.txt").exists() and "already the same" in out
    # a symlinked ref/ folder: restore refuses to write through it
    write(ws, 130.0)
    v.save(ws, "second")
    shutil.rmtree(ref)
    os.symlink(tmp_path, ref)
    with pytest.raises(v.VersionError):
        v.restore(ws, "shelf_bracket", "1")
    assert not (tmp_path / "scan.png").exists() and secret.read_text(encoding="utf-8") == "keep"


def test_staged_work_of_the_user_stays_out(ws):
    v.save(ws, "first")
    (ws / "notes.txt").write_text("mine", encoding="utf-8")
    git(ws, "add", "notes.txt")
    write(ws, 130.0)
    v.save(ws, "arm")
    assert "notes.txt" not in git(ws, "show", "--name-only", "--format=", "HEAD")
    assert git(ws, "diff", "--cached", "--name-only") == "notes.txt"


def test_no_git_and_no_repo(tmp_path, monkeypatch):
    w = tmp_path / "plain"
    init_workspace(w)
    new_part(w, "parts", "shelf_bracket")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))  # never find a repository above tmp
    with pytest.raises(v.VersionError, match="init --git"):
        v.save(w, "x")
    assert not v.is_repo(w)
    monkeypatch.setattr(v.shutil, "which", lambda name: None)
    for call in (lambda: v.save(w, "x"), lambda: v.history(w), lambda: v.restore(w, "shelf_bracket", "1"), lambda: v.start(w)):
        with pytest.raises(v.VersionError, match="git is not installed"):
            call()
    assert v.offer(w, "shelf_bracket") == ""


def test_cli(ws, capsys, monkeypatch):
    monkeypatch.chdir(ws)
    assert main(["save", "first"]) == 0
    write(ws, 130.0)
    assert main(["save", "arm", "--part", "shelf_bracket"]) == 0
    assert "ARM_L 115 → 130" in capsys.readouterr().out
    assert main(["versions", "shelf_bracket"]) == 0
    assert "arm" in capsys.readouterr().out
    assert main(["restore", "shelf_bracket", "1"]) == 0
    assert "Restored shelf_bracket" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="restore: bad version"):
        main(["restore", "shelf_bracket", "HEAD"])


def test_cli_init_git_only_when_asked(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", open(os.devnull))  # not a terminal: never asks, never starts
    assert main(["init", str(tmp_path / "a")]) == 0
    assert not (tmp_path / "a" / ".git").exists() and "init --git" in capsys.readouterr().out
    assert main(["init", str(tmp_path / "b"), "--git"]) == 0
    assert (tmp_path / "b" / ".git").is_dir() and (tmp_path / "b" / ".gitignore").is_file()


def test_offer_after_a_change(ws):
    assert "Save this version of shelf_bracket?" in v.offer(ws, "shelf_bracket")
    v.save(ws, "first")
    assert v.offer(ws, "shelf_bracket") == ""


def test_mcp_tools_local_and_remote(ws, server, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    m = server
    assert "Saved the project" in m.save_version("first")
    write(ws, 130.0)
    assert "ARM_L 115 → 130" in m.save_version("arm", part="shelf_bracket")
    assert "2  " in m.list_versions("shelf_bracket")
    assert "Restored" in m.restore_version("shelf_bracket", "1")
    with pytest.raises(ToolError, match="bad version"):
        m.restore_version("shelf_bracket", "--all")

    # a shared server: the history is on the user's machine, so no git runs here
    monkeypatch.setitem(m.STATE, "transport", "http")
    write(ws, 160.0)
    n = len(commits(ws))
    out = m.save_version("longer", part="shelf_bracket")
    assert "git commit" in out and "user's machine" in out and len(commits(ws)) == n
    assert "git log" in m.list_versions("shelf_bracket")
    assert "git checkout abc1234 -- parts/shelf_bracket" in m.restore_version("shelf_bracket", "abc1234")
    with pytest.raises(ToolError):
        m.restore_version("shelf_bracket", "1; rm -rf ~")
    assert "160.0" in (ws / "parts/shelf_bracket/shelf_bracket.py").read_text(encoding="utf-8")


def test_resume_note_for_a_missing_part_on_a_server(ws, server, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    m = server
    with pytest.raises(ToolError) as e:
        m.read_part("gone")
    assert "resume" not in str(e.value)
    monkeypatch.setitem(m.STATE, "transport", "http")
    with pytest.raises(ToolError) as e:
        m.read_part("gone")
    assert "write_part('gone'" in str(e.value) and "upload_reference" in str(e.value)


@pytest.mark.parametrize("remote", [False, True])
def test_check_offers_a_save_only_locally(ws, server, monkeypatch, remote):
    """A passing check offers "Save this version?" locally; on a shared server no git runs at all."""
    import anyio

    m = server

    async def passed(name, variant, fresh=False):
        return {"ok": True, "passed": True, "variants": {"": []}}

    monkeypatch.setattr(m, "_check", passed)
    ran = []
    real_run = v.run
    monkeypatch.setattr(v, "run", lambda *a, **k: ran.append(a) or real_run(*a, **k))
    if remote:
        monkeypatch.setitem(m.STATE, "transport", "http")
        monkeypatch.setattr(v, "offer", lambda *a: pytest.fail("offer() ran on a shared server"))
    out = anyio.run(m.check, "shelf_bracket")
    assert out.startswith("PASSED")
    if remote:
        assert ran == [] and "Save this version" not in out
    else:
        assert ran and "Save this version of shelf_bracket?" in out
