"""The worker launcher: a timed-out build dies together with everything it started."""

import os
import sys
import time
from pathlib import Path

from b123d_print import sandbox

# a part script that starts a child process (the audit hook is off for this test) and never ends
RUNAWAY = """
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path(PID_FILE).write_text(str(child.pid))
while True:
    time.sleep(0.1)
"""


def alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) would terminate it on Windows
        import ctypes

        k = ctypes.WinDLL("kernel32")
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k.WaitForSingleObject(ctypes.c_void_p(h), 0) != 0  # 0: signaled = exited
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # our own child would be a zombie until reaped; the grandchild is reaped by init
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def test_bwrap_binds_the_folders_a_job_needs():
    # a render/export job writes to out/ and the Matplotlib cache and reads the workspace and the
    # Python install; all must be in the per-job mount or the job fails inside the sandbox
    cmd = sandbox.linux_bwrap(["/ws/parts/p/out", "/tmp/scratch", "/cache/mpl"],
                              ["/ws", "/py"], proc=False)
    pairs = list(zip(cmd, cmd[1:]))
    for w in ("/ws/parts/p/out", "/tmp/scratch", "/cache/mpl"):
        assert ("--bind", w) in pairs, (w, cmd)
    for r in ("/ws", "/py"):
        assert ("--ro-bind-try", r) in pairs, (r, cmd)


def test_bwrap_never_tmpfs_over_root(monkeypatch):
    # a container running as a uid with no passwd entry gets HOME=/; a tmpfs over / would wipe the
    # dynamic loader and the interpreter could not start. The home-hide must be skipped then.
    monkeypatch.setattr(sandbox, "_real", lambda p: "/" if str(p) in ("/", str(Path.home())) else os.path.realpath(str(p)))
    monkeypatch.setattr(sandbox.Path, "home", classmethod(lambda cls: Path("/")))
    cmd = sandbox.linux_bwrap(["/ws/out"], ["/ws", "/usr/local"], proc=False)
    pairs = list(zip(cmd, cmd[1:]))
    assert ("--tmpfs", "/") not in pairs, cmd
    assert ("--ro-bind", "/") in pairs  # the root is still bound read-only


def test_bwrap_command_proc_variants():
    # a fresh procfs when the host allows it; an empty /proc (not a bound one) where it does not,
    # so a job never sees other jobs' /proc/<pid> in the same container
    with_proc = sandbox.linux_bwrap(["/w/out"], ["/w"], proc=True)
    assert "--proc" in with_proc and "/proc" in with_proc
    no_proc = sandbox.linux_bwrap(["/w/out"], ["/w"], proc=False)
    assert "--proc" not in no_proc
    i = no_proc.index("/proc")
    assert no_proc[i - 1] == "--tmpfs", no_proc  # /proc is an empty tmpfs, never a bind of the host's
    assert "--unshare-pid" in no_proc  # own PID namespace regardless


def test_timeout_kills_the_worker_and_its_children(tmp_path, monkeypatch):
    monkeypatch.setenv("B123D_PRINT_SANDBOX", "none")  # the OS sandboxes refuse to start a child at all
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")  # not queued behind other tests' builds
    out = tmp_path / "parts" / "spin" / "out"
    pid_file = out / "child.pid"
    script = tmp_path / "parts" / "spin" / "spin.py"
    script.parent.mkdir(parents=True)
    script.write_text(f"PID_FILE = {str(pid_file)!r}\n" + RUNAWAY, encoding="utf-8")
    # the outcome, not the wall clock: it timed out (killed by the 15 s limit) and took its child along
    res = sandbox.run_job({"op": "build", "script": str(script), "guard": False}, tmp_path, out, timeout=15)
    assert not res["ok"] and "timed out" in res["error"], res
    pid = int(pid_file.read_text())
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid), f"the worker's child {pid} outlived the timeout"
