"""Named tokens: the file, workspace patterns, default workspace, hot reload, the CLI."""

import os
import subprocess
import sys
import time

import pytest

from b123d_print import tokens


def tok(name="t", ws=("*",)):
    return tokens.Token(name, tokens.digest(name + "-secret"), list(ws), "2026-10-17")


def test_patterns_and_default_workspace():
    t = tok(ws=["grok-*"])
    assert t.allows("grok-1") and not t.allows("penguin-jon") and not t.allows(None)
    assert t.default_workspace() is None
    one = tok(ws=["mac-jon"])
    assert one.default_workspace() == "mac-jon" and one.allows("mac-jon") and not one.allows("mac-jon2")
    everything = tok()
    assert everything.allows(None) and everything.allows("anything") and everything.default_workspace() is None
    root = tok(ws=["_"])
    assert root.allows(None) and not root.allows("x") and root.default_workspace() is None


def test_round_trip(tmp_path):
    p = tmp_path / "tokens.toml"
    tokens.write(p, {"a": tok("a", ["a-*", "shared"]), "b": tok("b")}, "link-secret")
    got, secret = tokens.read(p)
    assert secret == "link-secret" and got["a"].workspaces == ["a-*", "shared"] and got["b"].sha256 == tok("b").sha256
    if sys.platform != "win32":  # no POSIX modes on Windows (the file inherits the folder's ACL)
        assert oct(os.stat(p).st_mode & 0o777) == "0o600"


@pytest.mark.parametrize("bad", ['[tokens.x]\nsha256 = "nothex"\n', '[tokens.x]\nsha256 = "' + "a" * 64 + '"\nworkspaces = []\n',
                                 '[tokens.x]\nsha256 = "' + "a" * 64 + '"\nworkspaces = ["../x"]\n'])
def test_malformed(tmp_path, bad):
    p = tmp_path / "tokens.toml"
    p.write_text(bad)
    with pytest.raises(ValueError):
        tokens.read(p)


def test_store_reloads_on_change_and_keeps_the_old_set_on_a_bad_file(tmp_path, capsys):
    p = tmp_path / "tokens.toml"
    tokens.write(p, {"a": tok("a")}, None)
    s = tokens.Store(p, legacy="legacy-token-0123456789")
    assert s.check("a-secret").name == "a" and s.check("legacy-token-0123456789").name == "default"
    assert s.check("b-secret") is None
    time.sleep(0.01)
    tokens.write(p, {"b": tok("b")}, None)  # a: revoked, b: added
    assert s.check("a-secret") is None and s.check("b-secret").name == "b"
    p.write_text("not [toml")
    assert s.check("b-secret").name == "b"  # broken file: keep what worked
    assert "keeping the previous tokens" in capsys.readouterr().err
    s.request_reload()
    assert s.check("b-secret").name == "b"


def test_store_refuses_a_bad_file_at_start(tmp_path):
    p = tmp_path / "tokens.toml"
    p.write_text("not [toml")
    with pytest.raises(Exception):
        tokens.Store(p)


def cli(tmp_path, *args):
    env = {**os.environ, "B123D_PRINT_TOKENS_FILE": str(tmp_path / "tokens.toml")}
    return subprocess.run([sys.executable, "-m", "b123d_print.mcp_server", "token", *args], env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_cli(tmp_path):
    r = cli(tmp_path, "add", "grok-chromebook", "--workspace", "grok-*")
    assert r.returncode == 0 and r.stdout.startswith("b1p_") and "only this once" in r.stderr
    secret = r.stdout.strip()
    text = (tmp_path / "tokens.toml").read_text(encoding="utf-8")
    assert secret not in text and tokens.digest(secret) in text  # only the hash is stored
    assert cli(tmp_path, "add", "grok-chromebook").returncode == 1  # no silent replace
    assert cli(tmp_path, "add", "x", "--workspace", "../etc").returncode == 2
    r = cli(tmp_path, "list")
    assert "grok-chromebook" in r.stdout and "grok-*" in r.stdout and secret not in r.stdout
    assert cli(tmp_path, "revoke", "grok-chromebook").returncode == 0
    assert "grok-chromebook" not in cli(tmp_path, "list").stdout
    assert cli(tmp_path, "revoke", "grok-chromebook").returncode == 1


def test_cli_default_workspace_and_client_config(tmp_path):
    r = cli(tmp_path, "add", "claude-laptop", "--url", "https://cad.example.com/")
    tok = r.stdout.strip()
    assert r.returncode == 0 and tokens.read(tmp_path / "tokens.toml")[0]["claude-laptop"].workspaces == ["claude-laptop"]
    # one workspace: the URL needs no ?workspace=; the Claude Code line is project-scoped
    assert "URL     https://cad.example.com/mcp\n" in r.stderr
    assert f'claude mcp add --scope project --transport http b123d-print "https://cad.example.com/mcp" --header "Authorization: Bearer {tok}"' in r.stderr
    assert '"url": "https://cad.example.com/mcp"' in r.stderr and "token revoke claude-laptop" in r.stderr
    r = cli(tmp_path, "add", "eval", "--workspace", "eval-*")
    assert "https://<your-server>/mcp?workspace=eval-1" in r.stderr and "--url" in r.stderr
    assert cli(tmp_path, "add", "has.dot").returncode == 2  # a token name is also its default workspace name
