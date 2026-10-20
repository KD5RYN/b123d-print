"""The worker's audit hook is defense in depth; this pins the behaviour it promises. Each script
below is a hostile part script. With the OS sandbox off (B123D_PRINT_SANDBOX=none) the hook is the
only barrier, so every one of these must fail and leave nothing behind. A normal build, run the
same way, must still succeed."""

import os
import sys

import pytest

from b123d_print import sandbox

pytestmark = pytest.mark.filterwarnings("ignore")

# a valid part, so the "normal build still works" case exercises the real build path
GOOD = """
from dataclasses import dataclass
from build123d import Box, Part

@dataclass(frozen=True)
class Dims:
    W: float = 10.0

def build(d: Dims) -> Part:
    return Box(d.W, d.W, d.W)
"""


def _run(tmp_path, body, guard=True):
    """Run `body` as a part script's top level and return the worker's result dict."""
    ws = tmp_path
    out = ws / "parts" / "p" / "out"
    script = ws / "parts" / "p" / "p.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")
    env = dict(os.environ)
    env["B123D_PRINT_SANDBOX"] = "none"  # isolate the audit hook as the only boundary
    old = os.environ.get("B123D_PRINT_SANDBOX")
    os.environ["B123D_PRINT_SANDBOX"] = "none"
    try:
        return sandbox.run_job({"op": "build", "script": str(script), "guard": guard}, ws, out, timeout=60)
    finally:
        if old is None:
            os.environ.pop("B123D_PRINT_SANDBOX", None)
        else:
            os.environ["B123D_PRINT_SANDBOX"] = old


def _blocked(res) -> bool:
    return not res.get("ok") and "blocked in part scripts" in (res.get("error", "") + res.get("traceback", ""))


def test_a_normal_build_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    res = _run(tmp_path, GOOD)
    assert res.get("ok"), res


def test_rebinding_the_guard_settings_does_not_weaken_it(tmp_path, monkeypatch):
    # the worker runs as __main__, so a script can reach these names; the hook must not consult them
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    body = GOOD + """
import __main__
for name in ("BLOCKED_EVENTS", "BLOCKED_IMPORTS", "WRITE_ONE", "WRITE_TWO", "WRITE_EVENTS"):
    try:
        setattr(__main__, name, type(getattr(__main__, name, ()))())  # empty tuple/set
    except Exception:
        pass
import os
os.system("true")  # a blocked action is still blocked
"""
    res = _run(tmp_path, body)
    assert _blocked(res), res


def test_introspection_to_the_guard_closure_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    body = GOOD + "\nimport gc\ngc.get_referrers(object())\n"
    res = _run(tmp_path, body)
    assert _blocked(res), res


def test_utime_outside_the_writable_folders_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    target = tmp_path / "parts" / "p" / "p.py"  # readable, not writable
    body = GOOD + f"\nimport os\nos.utime({str(target)!r})\n"
    res = _run(tmp_path, body)
    assert _blocked(res), res


def test_symlink_created_outside_the_writable_folders_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    link = tmp_path / "parts" / "p" / "evil_link"  # the link location, not the target, decides
    body = GOOD + f"\nimport os\nos.symlink('/etc/hosts', {str(link)!r})\n"
    res = _run(tmp_path, body)
    assert _blocked(res) and not link.is_symlink(), res


def test_reading_another_workspace_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    other = tmp_path / "workspaces" / "victim"
    other.mkdir(parents=True)
    (other / "secret.txt").write_text("sensitive", encoding="utf-8")
    body = GOOD + f"\nopen({str(other / 'secret.txt')!r}).read()\n"
    res = _run(tmp_path, body)
    assert _blocked(res), res


def test_reading_the_tokens_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    tokens = tmp_path / "secrets" / "tokens.toml"
    tokens.parent.mkdir(parents=True)
    tokens.write_text("link_secret = 'abcd'\n", encoding="utf-8")
    monkeypatch.setattr(sandbox, "SECRET_FILES", {str(tokens)})
    body = GOOD + f"\nopen({str(tokens)!r}).read()\n"
    res = _run(tmp_path, body)
    assert _blocked(res), res


def test_reading_another_jobs_queue_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    queue = tmp_path / ".b123d-print" / "jobs"
    queue.mkdir(parents=True)
    (queue / "other.running").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sandbox, "EXTRA_HIDDEN", {str(queue), str(queue.parent)})
    body = GOOD + f"\nopen({str(queue / 'other.running')!r}).read()\n"
    res = _run(tmp_path, body)
    assert _blocked(res), res
