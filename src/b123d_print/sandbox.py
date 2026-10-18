"""Run a worker job in a separate, restricted process.

Layers (strongest available is used; see `describe()`):
  - macOS: sandbox-exec profile: no network, no process spawning, writes only to the part's out/
    folder and a scratch folder, no reads of your home folder outside the workspace and Python.
  - Linux: bubblewrap (`bwrap`) if installed: read-only root, no network, the same writable
    folders, home folder hidden except the workspace.
  - Windows: no OS sandbox. The worker runs in a Job Object (CPU-time limit; killing the job on
    a timeout kills every process in it) with the audit hook below; use WSL2 or Docker for more.
  - Always: a timeout (process group or job killed), CPU-time limit, scrubbed environment and the
    worker's audit hook (no sockets, subprocesses or ctypes; writes only to allowed folders).
  - For untrusted input, run the whole server in the Docker image with --network none.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

WINDOWS = sys.platform == "win32"
_LIVE: set[subprocess.Popen] = set()  # running workers, so a server shutdown can stop them
_LIVE_LOCK = threading.Lock()

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "b123d-print"
# builds at once across every server process of this user (each SSH session runs its own server);
# mcp_server sets it from --max-builds / $B123D_PRINT_MAX_BUILDS
MAX_BUILDS = int(os.environ.get("B123D_PRINT_MAX_BUILDS", 0)) or max(1, (os.cpu_count() or 2) // 2)
SLOT_DIR = CACHE / "build-slots"


def _real(p) -> str:
    return os.path.realpath(str(p))


def _python_roots() -> list[str]:
    """Folders the interpreter and installed packages live in (must stay readable)."""
    paths = {sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(sys.executable)}
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        paths.add(sysconfig.get_paths().get(key, ""))
    paths.update(p for p in sys.path if p and os.path.isdir(p))
    paths = {p for p in paths if p}
    return sorted({_real(p) for p in paths} | {os.path.abspath(p) for p in paths})


def _sbpl_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def macos_profile(writable: list[str], readable: list[str]) -> str:
    home = _real(Path.home())
    w = " ".join(f"(subpath {_sbpl_str(_real(p))})" for p in writable)
    r = " ".join(f"(subpath {_sbpl_str(_real(p))})" for p in readable + writable)
    return f"""(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny file-write*)
(allow file-write* {w} (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))
(deny file-read* (subpath {_sbpl_str(home)}))
(allow file-read* (literal {_sbpl_str(home)}) {r})
(allow file-read-metadata)
"""


def linux_bwrap(writable: list[str], readable: list[str]) -> list[str]:
    home = _real(Path.home())
    cmd = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-net",
           "--unshare-pid", "--die-with-parent", "--new-session", "--tmpfs", home]
    for p in readable:
        cmd += ["--ro-bind-try", p, p]
    for p in writable:
        cmd += ["--bind", p, p]
    return cmd


def kind() -> str:
    if os.environ.get("B123D_PRINT_SANDBOX") == "none":
        return "none"
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bwrap"
    return "none"


def describe() -> str:
    k = kind()
    return {
        "sandbox-exec": "macOS sandbox-exec (no network, no subprocesses, writes limited to out/ and scratch, home hidden)",
        "bwrap": "Linux bubblewrap (no network, read-only system, writes limited to out/ and scratch, home hidden)",
        "none": ("Windows has no OS sandbox here: process isolation (a Job Object with a CPU-time limit, killed "
                 "with all its child processes on a timeout) + audit hook only; for untrusted scripts run the "
                 "server in WSL2 with bubblewrap, or in the Docker image") if WINDOWS else
                "process isolation + audit hook only (install bubblewrap on Linux, or use the Docker image)",
    }[k] if not (k == "none" and os.environ.get("B123D_PRINT_SANDBOX") == "none") else (
        "OS sandbox off (B123D_PRINT_SANDBOX=none): process isolation + audit hook; in the Docker image the container is the sandbox")


@contextmanager
def build_slot(n: int | None = None, poll: float = 0.2):
    """Hold one of `n` build slots shared by all processes of this user (lock files in SLOT_DIR,
    released by the OS if the process dies); waits while all are taken."""
    n = max(1, n or MAX_BUILDS)
    SLOT_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        for i in range(n):
            fd = os.open(SLOT_DIR / f"slot-{i}", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                _lock(fd)
            except OSError:
                os.close(fd)
                continue
            try:
                yield i
            finally:
                _unlock(fd)
                os.close(fd)
            return
        time.sleep(poll)


if WINDOWS:
    import msvcrt

    def _lock(fd: int) -> None:  # the first byte, non-blocking (OSError if another process has it)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:  # explicit: Windows releases a closed file's locks only eventually
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:  # closing the descriptor releases the lock
        pass


def run_job(job: dict, workspace: Path, out_dir: Path, timeout: float = 120.0) -> dict:
    """Run b123d_print.worker on `job` and return its result dict (never raises for script errors)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mpl = CACHE / "matplotlib"
    mpl.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b123d-print-") as tmp:
        tmp = _real(tmp)
        writable = [_real(out_dir), tmp, _real(mpl)]
        readable = [_real(workspace)] + _python_roots()
        job = {**job, "out_dir": _real(out_dir), "result": os.path.join(tmp, "result.json"), "writable": writable}
        job_file = os.path.join(tmp, "job.json")
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump(job, f)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp,
            "TMPDIR": tmp,
            **(_windows_env(tmp) if WINDOWS else {}),
            "MPLCONFIGDIR": _real(mpl),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p and os.path.isdir(p)),
            "LANG": "C.UTF-8",
        }
        for var in ("B123D_PRINT_HOLE_COMP", "B123D_PRINT_CLEARANCE", "B123D_PRINT_MIN_WALL", "B123D_PRINT_MAX_OVERHANG",
                    "B123D_PRINT_FORMATS", "B123D_PRINT_MAX_TRIANGLES", "XDG_CONFIG_HOME"):
            if var in os.environ:
                env[var] = os.environ[var]
        # settings: the worker resolves the user config from the real home, so pass it explicitly
        env.setdefault("XDG_CONFIG_HOME", _real(Path.home() / ".config"))
        readable.append(_real(Path(env["XDG_CONFIG_HOME"]) / "b123d-print"))  # only b123d-print's own config
        cmd = [sys.executable, "-s", "-m", "b123d_print.worker", job_file]
        k = kind()
        if k == "sandbox-exec":
            prof = os.path.join(tmp, "profile.sb")
            with open(prof, "w", encoding="utf-8") as f:
                f.write(macos_profile(writable, readable))
            cmd = ["sandbox-exec", "-f", prof] + cmd
        elif k == "bwrap":
            cmd = linux_bwrap(writable, readable) + cmd

        def limits():  # in the child, before exec
            try:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 10))
            except Exception:
                pass

        with build_slot():  # shared with every other server process of this user
            if WINDOWS:
                proc = _popen_windows(cmd, env, tmp, timeout)
            else:
                proc = subprocess.Popen(cmd, env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, preexec_fn=limits)
            with _LIVE_LOCK:
                _LIVE.add(proc)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _killpg(proc)
                stdout, stderr = proc.communicate()
                return {"ok": False, "error": f"timed out after {timeout:g} s (killed)", "log": _tail(stdout, stderr)}
            finally:
                with _LIVE_LOCK:
                    _LIVE.discard(proc)
                _close_job(proc)
        if _was_killed(proc) and not Path(job["result"]).exists():
            return {"ok": False, "error": "worker was killed (server shutting down, or out of memory)", "log": _tail(stdout, stderr)}
        rp = Path(job["result"])
        if not rp.exists():
            return {"ok": False, "error": f"worker exited with code {proc.returncode} and no result",
                    "log": _tail(stdout, stderr)}
        res = json.loads(rp.read_text(encoding="utf-8"))
        log = _tail(stdout, stderr)
        if log:
            res["log"] = log
        res["sandbox"] = k
        return res


def _killpg(proc: subprocess.Popen) -> None:
    """Kill the worker and everything it started (its process group, or its Job Object on Windows)."""
    if WINDOWS:
        proc.b123d_killed = True
        if getattr(proc, "b123d_job", None):
            _kernel32().TerminateJobObject(proc.b123d_job, 1)
        else:
            proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _was_killed(proc: subprocess.Popen) -> bool:
    if WINDOWS:  # no signals: a job kill exits with code 1, so remember who killed it
        return getattr(proc, "b123d_killed", False)
    return proc.returncode in (-signal.SIGKILL, -signal.SIGTERM)


# --- Windows: the worker runs in a Job Object -------------------------------------------------
# No preexec_fn or setrlimit there. The job gives the same two guarantees: a CPU-time limit per
# process, and one handle that kills the worker and every process it started (kill-on-job-close,
# so they also die if this server dies). Plain ctypes on kernel32; nothing to install.

def _windows_env(tmp: str) -> dict:
    """What a Windows process needs to start at all (SYSTEMROOT for the C runtime and crypto,
    a PATH with System32 for DLLs), with the profile and temp folders pointed at the scratch dir."""
    sysroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env = {"SYSTEMROOT": sysroot, "WINDIR": os.environ.get("WINDIR", sysroot),
           "PATH": os.pathsep.join([os.path.dirname(sys.executable), os.path.join(sysroot, "System32"), sysroot]),
           "USERPROFILE": tmp, "TEMP": tmp, "TMP": tmp, "LOCALAPPDATA": tmp, "APPDATA": tmp}
    for var in ("SYSTEMDRIVE", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"):
        if var in os.environ:
            env[var] = os.environ[var]
    return env


class _Win:
    """The few kernel32 calls for Job Objects, loaded on first use."""

    KILL_ON_JOB_CLOSE = 0x2000
    PROCESS_TIME = 0x0002
    EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(f, ctypes.c_uint64) for f in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                       "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.ctypes, self.EXTENDED = ctypes, EXTENDED
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.TerminateJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k = k

    def job(self, cpu_seconds: float) -> int:
        h = self.k.CreateJobObjectW(None, None)
        if not h:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        info = self.EXTENDED()
        info.BasicLimitInformation.LimitFlags = self.KILL_ON_JOB_CLOSE | self.PROCESS_TIME
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu_seconds * 10_000_000)  # 100 ns units
        if not self.k.SetInformationJobObject(h, self.EXTENDED_LIMIT_INFORMATION, self.ctypes.byref(info),
                                              self.ctypes.sizeof(info)):
            err = self.ctypes.get_last_error()
            self.k.CloseHandle(h)
            raise self.ctypes.WinError(err)
        return h

    def assign(self, job: int, process_handle: int) -> None:
        if not self.k.AssignProcessToJobObject(job, int(process_handle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def TerminateJobObject(self, job: int, code: int) -> None:  # noqa: N802 - the Win32 name
        self.k.TerminateJobObject(job, code)

    def close(self, h: int) -> None:
        self.k.CloseHandle(h)


@functools.cache
def _kernel32() -> _Win:
    return _Win()


def _popen_windows(cmd: list[str], env: dict, cwd: str, timeout: float) -> subprocess.Popen:
    """Start the worker and put it in a new job at once. (subprocess cannot start it suspended; the
    worker spends its first second importing libraries and starts nothing, so nothing escapes.)"""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # no Ctrl+C from our console, no window
    job = _kernel32().job(timeout + 5)
    try:
        proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=flags)
    except BaseException:
        _kernel32().close(job)
        raise
    proc.b123d_job = job
    try:
        _kernel32().assign(job, proc._handle)
    except OSError:
        _killpg(proc)
        proc.communicate()
        _close_job(proc)
        raise
    return proc


def _close_job(proc: subprocess.Popen) -> None:
    """Closing the job's last handle kills anything the worker left running (kill-on-job-close)."""
    job = getattr(proc, "b123d_job", None)
    if job:
        proc.b123d_job = None
        _kernel32().close(job)


def kill_all() -> int:
    """Stop every running worker (server shutdown). Returns how many were running."""
    with _LIVE_LOCK:
        procs = list(_LIVE)
    for p in procs:
        _killpg(p)
    return len(procs)


def _tail(stdout: bytes, stderr: bytes, n: int = 4000) -> str:
    s = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
    return s[-n:].strip()
