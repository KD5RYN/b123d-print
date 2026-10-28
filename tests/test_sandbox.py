"""The worker launcher: a timed-out build dies together with everything it started."""

import os
import sys
import time
from pathlib import Path

import pytest

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


@pytest.mark.skipif(sys.platform == "win32", reason="symlinked interpreters are a POSIX layout")
def test_python_roots_follow_a_venv_interpreter_through_uv_link_folders(tmp_path, monkeypatch):
    # uv's layout under HOME: venv/bin/python -> py/cpython-3.12-gnu/bin/python3.12, where
    # cpython-3.12-gnu is itself a link to cpython-3.12.15-gnu. bwrap hides HOME, so the link
    # folder's own path must be bound, not only its target, or the exec fails with "No such file"
    real = tmp_path / "py" / "cpython-3.12.15-gnu"
    (real / "bin").mkdir(parents=True)
    (real / "bin" / "python3.12").write_text("")
    (tmp_path / "py" / "cpython-3.12-gnu").symlink_to(real, target_is_directory=True)
    venv = tmp_path / "cache" / "env"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(tmp_path / "py" / "cpython-3.12-gnu" / "bin" / "python3.12")
    monkeypatch.setattr(sys, "executable", str(venv / "bin" / "python"))
    roots = sandbox._python_roots()
    link = str(tmp_path / "py" / "cpython-3.12-gnu")
    assert link in roots and link + "/bin" in roots, roots
    assert sandbox._real(real) in roots, roots
    assert str(venv / "bin") in roots, roots
    # only the interpreter's own folders: never the uv cache or python folders above them
    assert str(tmp_path / "py") not in roots and str(tmp_path / "cache") not in roots, roots


def test_bwrap_never_tmpfs_over_root(monkeypatch):
    # a container running as a uid with no passwd entry gets HOME=/; a tmpfs over / would wipe the
    # dynamic loader and the interpreter could not start. The home-hide must be skipped then.
    # _real returns "/" for the root (str(Path("/")) is "/" on POSIX, "\\" on Windows) and passes
    # other paths through unchanged, so the test is cross-platform (bwrap paths are POSIX).
    monkeypatch.setattr(sandbox, "_real", lambda p: "/" if str(p) in ("/", "\\") else str(p))
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


def test_parse_size():
    assert sandbox.parse_size("2g") == sandbox.parse_size("2GB") == sandbox.parse_size("2") == 2 * 2**30
    assert sandbox.parse_size("1536m") == sandbox.parse_size("1.5GiB") == 1536 * 2**20
    assert sandbox.parse_size("0") == sandbox.parse_size("") == 0
    for bad in ("lots", "-1g"):
        with pytest.raises(ValueError):
            sandbox.parse_size(bad)
    assert sandbox.human_size(2 * 2**30) == "2 GB" and sandbox.human_size(512 * 2**20) == "512 MB"


# a part script that allocates far more than the cap (at import, like a runaway build)
HOG = "BIG = bytearray(4 * 2**30)\n"


@pytest.mark.skipif(not (sys.platform.startswith("linux") or sys.platform == "win32"),
                    reason="macOS enforces no per-process memory limit")
def test_a_build_over_the_memory_cap_fails_plainly_and_the_next_one_runs(tmp_path, monkeypatch):
    # in the real sandbox where there is one (bubblewrap in CI): the limit is set before bwrap starts
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    monkeypatch.setattr(sandbox, "MAX_MEMORY", 1 * 2**30)
    out = tmp_path / "parts" / "hog" / "out"
    script = tmp_path / "parts" / "hog" / "hog.py"
    script.parent.mkdir(parents=True)
    script.write_text(HOG, encoding="utf-8")
    res = sandbox.run_job({"op": "build", "script": str(script)}, tmp_path, out, timeout=60)
    assert not res["ok"] and res["usage_error"], res
    assert res["error"].startswith("the build used more than 1 GB of memory"), res
    assert "MemoryError" in res.get("detail", "") or "MemoryError" in res.get("log", ""), res
    # the server (this process) is fine, and the next job runs normally under the same cap
    script.write_text("SMALL = bytearray(10 * 2**20)\n", encoding="utf-8")
    res = sandbox.run_job({"op": "build", "script": str(script)}, tmp_path, out, timeout=60)
    assert "memory" not in res.get("error", ""), res


@pytest.mark.skipif(sys.platform == "win32", reason="no signals on Windows")
def test_a_job_killed_by_the_system_says_so(tmp_path, monkeypatch):
    # SIGKILL from no one here (what the kernel's OOM killer sends) is not reported as a shutdown
    monkeypatch.setenv("B123D_PRINT_SANDBOX", "none")  # the hook would refuse os.kill
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    out = tmp_path / "parts" / "die" / "out"
    script = tmp_path / "parts" / "die" / "die.py"
    script.parent.mkdir(parents=True)
    script.write_text("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n", encoding="utf-8")
    res = sandbox.run_job({"op": "build", "script": str(script), "guard": False}, tmp_path, out, timeout=60)
    assert not res["ok"] and "killed by the system" in res["error"] and "out of memory" in res["error"], res


def _abort_job(tmp_path, monkeypatch):
    """Run a job that aborts, with core dumps allowed in this process; return (result, cores)."""
    import resource

    monkeypatch.setenv("B123D_PRINT_SANDBOX", "none")  # the hook would refuse os.abort
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
    try:  # allow cores here, so only the job's own limit can stop one
        resource.setrlimit(resource.RLIMIT_CORE, (hard, hard))
    except (ValueError, OSError):
        pass
    try:
        out = tmp_path / "parts" / "crash" / "out"
        script = tmp_path / "parts" / "crash" / "crash.py"
        script.parent.mkdir(parents=True)
        script.write_text("import os\nos.abort()\n", encoding="utf-8")
        res = sandbox.run_job({"op": "build", "script": str(script), "guard": False}, tmp_path, out, timeout=60)
    finally:
        resource.setrlimit(resource.RLIMIT_CORE, (soft, hard))
    return res, [p for p in tmp_path.rglob("core*") if p.is_file()]


@pytest.mark.skipif(sys.platform == "win32", reason="no signals or core dumps on Windows")
def test_a_crashing_job_writes_no_core_dump(tmp_path, monkeypatch):
    """#150: OCC aborted under the memory cap and the container wrote a 1.7 GB core into out/."""
    res, cores = _abort_job(tmp_path, monkeypatch)
    assert not res["ok"] and not cores, (res, cores)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the memory cap is enforced on Linux (and Windows)")
def test_a_crash_under_the_memory_cap_says_out_of_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "MAX_MEMORY", 3 * 2**30)
    res, cores = _abort_job(tmp_path, monkeypatch)
    assert not res["ok"] and res.get("usage_error") and not cores, res
    assert "crashed (SIGABRT)" in res["error"] and "3 GB per job" in res["error"], res


def test_crash_signal():
    assert sandbox._crash_signal(-6) == 6 and sandbox._crash_signal(134) == 6
    assert sandbox._crash_signal(1) == 0 and sandbox._crash_signal(0) == 0 and sandbox._crash_signal(None) == 0
