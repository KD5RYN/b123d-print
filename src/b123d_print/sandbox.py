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
import math
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
_EPOCH = 0  # bumped by kill_all(): a build claimed before a cancel must not start after it


def current_epoch() -> int:
    with _LIVE_LOCK:
        return _EPOCH

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


def macos_profile(writable: list[str], readable: list[str], hidden: list[str] = (), secrets: list[str] = ()) -> str:
    """`hidden`: folders a job never reads, even inside `readable` (other workspaces), except the
    `readable`/`writable` folders inside them; `secrets`: files never read or even listed."""
    home = _real(Path.home())
    w = " ".join(f"(subpath {_sbpl_str(_real(p))})" for p in writable)
    r = " ".join(f"(subpath {_sbpl_str(_real(p))})" for p in readable + writable)
    # later rules win: hide, then allow back the job's own folders inside a hidden one, then the secrets for good
    hide = "".join(f"(deny file-read* (subpath {_sbpl_str(_real(p))}))\n" for p in hidden)
    inside = _inside(readable + writable, hidden)
    back = f"(allow file-read* {' '.join(f'(subpath {_sbpl_str(p)})' for p in inside)})\n" if inside else ""
    sec = "".join(f"(deny file-read* file-read-metadata (literal {_sbpl_str(_real(p))}))\n" for p in secrets)
    # hide the home folder, but never when it is "/" (that would deny every read); then allow back
    # what the job needs to read
    hide_home = f"(deny file-read* (subpath {_sbpl_str(home)}))\n" if home and home != os.sep else ""
    return f"""(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny file-write*)
(allow file-write* {w} (literal "/dev/null") (literal "/dev/stdout") (literal "/dev/stderr"))
{hide_home}(allow file-read* (literal {_sbpl_str(home)}) {r})
(allow file-read-metadata)
{hide}{back}{sec}"""


def linux_bwrap(writable: list[str], readable: list[str], hidden: list[str] = (), secrets: list[str] = (),
                proc: bool | None = None) -> list[str]:
    """`hidden` folders become empty (tmpfs) before the job's own folders are bound back in;
    `secrets` files read as empty (/dev/null over them), wherever they are.

    `proc`: mount a fresh procfs at /proc (True), or leave /proc an empty tmpfs (False). None asks
    `_bwrap_caps()`. A fresh procfs is refused where the container masks parts of /proc (Docker's
    `mount_too_revealing`); an empty /proc keeps the job from seeing other jobs' `/proc/<pid>` in
    the same container, and `--unshare-pid` still gives it its own PID namespace."""
    if proc is None:
        proc = _bwrap_caps()["proc"]
    home = _real(Path.home())
    proc_args = ["--proc", "/proc"] if proc else ["--tmpfs", "/proc"]
    # --unshare-user: create a user namespace explicitly. On a normal host bwrap does this on its
    # own when unprivileged, but inside an unprivileged container (the Docker worker, uid != 0, no
    # CAP_SYS_ADMIN) it is the user namespace that grants the privilege to mount/pivot_root, so it
    # must be requested or every bind fails.
    cmd = ["bwrap", "--unshare-user", "--ro-bind", "/", "/", "--dev", "/dev", *proc_args,
           "--unshare-net", "--unshare-pid", "--die-with-parent", "--new-session"]
    # hide the home folder (scripts don't read ~), but never when HOME is "/" — a container running
    # as a uid with no passwd entry gets HOME=/, and a tmpfs over / would wipe the whole root
    # (including the dynamic loader), so the interpreter could not even start
    if home and home != os.sep:
        cmd += ["--tmpfs", home]
    for p in readable:
        cmd += ["--ro-bind-try", p, p]
    for p in writable:
        cmd += ["--bind", p, p]
    for p in hidden:  # after the binds (a hidden folder may lie inside a readable one) ...
        if os.path.isdir(p):
            cmd += ["--tmpfs", p]
    for p in _inside(readable, hidden):  # ... then the job's own folders inside it, back again
        cmd += ["--ro-bind-try", p, p]
    for p in _inside(writable, hidden):
        cmd += ["--bind", p, p]
    for p in secrets:
        if os.path.isfile(p):
            cmd += ["--ro-bind", "/dev/null", p]
    return cmd


def _inside(paths: list[str], dirs: list[str]) -> list[str]:
    """The `paths` that lie strictly inside one of `dirs` (real paths)."""
    ds = [_real(d) for d in dirs]
    return [p for p in map(_real, paths) if any(p.startswith(d + os.sep) for d in ds)]


# files no job may read, wherever they are: the HTTP server's tokens (hashes and the link secret);
# mcp_server adds the tokens file it was started with
SECRET_FILES: set[str] = set()


def _secret_files() -> list[str]:
    out = set(SECRET_FILES)
    for var in ("B123D_PRINT_TOKENS_FILE", "B123D_PRINT_TOKEN_FILE"):
        if os.environ.get(var):
            out.add(os.path.expanduser(os.environ[var]))
    return sorted({_real(p) for p in out} | {os.path.abspath(p) for p in out})


# folders no job may see beyond the ones derived from its workspace: the HTTP job queue, which
# jobqueue.serve registers so a worker's jobs cannot read each other's queue files
EXTRA_HIDDEN: set[str] = set()


def _hidden_dirs(workspace: Path) -> list[str]:
    """Other workspaces: the root workspace's workspaces/ folder (a job in the root workspace) and
    the siblings of a named workspace (workspaces/<name>), plus the job queue (EXTRA_HIDDEN)."""
    ws = Path(_real(workspace))
    out = [ws / "workspaces"]
    if ws.parent.name == "workspaces":
        out.append(ws.parent)
    return sorted({str(p) for p in out} | {_real(p) for p in EXTRA_HIDDEN})


def mpl_cache(workspace: Path) -> Path:
    """Matplotlib's cache and config folder, one per workspace (a job may write it)."""
    import hashlib

    return CACHE / "matplotlib" / hashlib.sha256(_real(workspace).encode("utf-8")).hexdigest()[:16]


def _auto_kind() -> str:
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bwrap"
    return "none"


# B123D_PRINT_SANDBOX values: "none" (explicit opt-out: run with the audit hook only, e.g. the
# single-container Docker image); unset or "auto" (use the best OS sandbox available, else none —
# for local and dev use); a sandbox name ("bubblewrap"/"bwrap", "sandbox-exec") to REQUIRE it, so
# a deployment that must isolate jobs fails closed instead of running them with the hook alone.
_REQUIRE_ALIASES = {"bubblewrap": "bwrap", "bwrap": "bwrap", "sandbox-exec": "sandbox-exec"}


def required_sandbox() -> str | None:
    """The sandbox the operator requires (B123D_PRINT_SANDBOX names one), or None for opt-out/auto."""
    v = (os.environ.get("B123D_PRINT_SANDBOX") or "").strip().lower()
    if v in ("", "auto", "none"):
        return None
    return _REQUIRE_ALIASES.get(v, v)


def kind() -> str:
    if os.environ.get("B123D_PRINT_SANDBOX") == "none":
        return "none"
    req = required_sandbox()
    k = _auto_kind()
    if req and req != k:  # required but not what is available here: run_job fails closed
        return "none"
    return k


def _bwrap_try(extra: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["bwrap", "--unshare-user", "--ro-bind", "/", "/", "--dev", "/dev", *extra,
                            "--unshare-net", "--unshare-pid", "--die-with-parent", "true"],
                           capture_output=True, timeout=15)
        return r.returncode, (r.stderr or b"").decode(errors="replace").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


@functools.cache
def _bwrap_caps() -> dict:
    """What bubblewrap can do here, probed once: {"usable": bool, "proc": bool, "error": str|None}.
    `proc` is False where a fresh procfs cannot be mounted (a container that masks parts of /proc);
    the job then gets an empty /proc instead. `usable` is False only if even that minimal namespace
    cannot start (no unprivileged user namespaces) — that is what fails the deployment closed."""
    if not shutil.which("bwrap"):
        return {"usable": False, "proc": False, "error": "bubblewrap (bwrap) is not installed"}
    rc, _ = _bwrap_try(["--proc", "/proc"])
    if rc == 0:
        return {"usable": True, "proc": True, "error": None}
    rc2, err = _bwrap_try(["--tmpfs", "/proc"])  # can we at least run without a real /proc?
    if rc2 == 0:
        return {"usable": True, "proc": False, "error": None}
    last = err.splitlines()
    return {"usable": False, "proc": False,
            "error": "bubblewrap could not start a namespace" + (f": {last[-1]}" if last else
                     " (unprivileged user namespaces may be disabled on the host)")}


@functools.cache
def sandbox_error() -> str | None:
    """Why the required sandbox is unusable here, or None if there is none to require or it works.
    Used to fail closed: a deployment that asked for a sandbox must not silently run with the hook
    only. B123D_PRINT_SANDBOX=none is the explicit opt-out and never reports an error."""
    req = required_sandbox()
    if not req:
        return None
    if _auto_kind() != req:
        return f"sandbox {req!r} is required (B123D_PRINT_SANDBOX) but not available in this environment"
    return _bwrap_caps()["error"] if req == "bwrap" else None


def describe() -> str:
    err = sandbox_error()
    if err:
        return f"REQUIRED SANDBOX UNAVAILABLE: {err}; jobs are refused until this is fixed"
    k = kind()
    bwrap_note = "" if _bwrap_caps().get("proc", True) else ", /proc empty (container masks it)"
    return {
        "sandbox-exec": "macOS sandbox-exec (no network, no subprocesses, writes limited to out/ and scratch, home hidden)",
        "bwrap": f"Linux bubblewrap (no network, read-only system, writes limited to out/ and scratch, home hidden{bwrap_note})",
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


# seconds per build, render, section or export (--timeout, $B123D_PRINT_TIMEOUT): under the 300 s
# a typical MCP client waits for a tool result; a check run has its own limit (300 s)
DEFAULT_TIMEOUT = 240.0


def soft_margin(timeout: float) -> float:
    """Seconds before the hard timeout at which the worker stops checking and reports: 10 %,
    between 3 and 30 s (time to interrupt an OCC call and write the result)."""
    return min(30.0, max(3.0, 0.1 * timeout))


def run_job(job: dict, workspace: Path, out_dir: Path, timeout: float = DEFAULT_TIMEOUT, epoch: int | None = None) -> dict:
    """Run b123d_print.worker on `job` and return its result dict (never raises for script errors)."""
    err = sandbox_error()
    if err:  # a sandbox was required but cannot run here: refuse rather than run with the hook only
        return {"ok": False, "error": f"refusing to run untrusted code: {err}", "sandbox": "unavailable"}
    out_dir.mkdir(parents=True, exist_ok=True)
    mpl = mpl_cache(workspace)
    mpl.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b123d-print-") as tmp:
        tmp = _real(tmp)
        writable = [_real(out_dir), tmp, _real(mpl)]
        cfg = _real(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "b123d-print")
        readable = [_real(workspace)] + _python_roots() + [cfg]
        # other workspaces and the secret files: hidden by the OS sandbox, and refused by the
        # worker's own audit hook too (which is all there is on Windows and SANDBOX=none). readable
        # is what the hook allows a job to read even where it overlaps a hidden folder (its own
        # workspace lives under the hidden workspaces/ parent)
        hidden, secrets = _hidden_dirs(workspace), _secret_files()
        # the worker's own soft limit, a little before the hard one kills it: `check` stops there and
        # returns what it finished instead of nothing (see project.run_checks)
        # workspace: where the build cache looks for files a build read outside the part's folder
        job = {**job, "out_dir": _real(out_dir), "result": os.path.join(tmp, "result.json"), "writable": writable,
               "readable": readable, "hidden": hidden, "secrets": secrets, "workspace": _real(workspace),
               "deadline": min(job.get("deadline", math.inf), time.time() + timeout - soft_margin(timeout))}
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
                    "B123D_PRINT_FORMATS", "B123D_PRINT_MAX_TRIANGLES", "B123D_PRINT_NO_CACHE", "XDG_CONFIG_HOME"):
            if var in os.environ:
                env[var] = os.environ[var]
        # settings: the worker resolves the user config from the real home, so pass it explicitly
        env.setdefault("XDG_CONFIG_HOME", _real(Path.home() / ".config"))
        readable.append(_real(Path(env["XDG_CONFIG_HOME"]) / "b123d-print"))  # only b123d-print's own config
        # keep the venv interpreter (its pyvenv.cfg puts the venv's site-packages on sys.path); the
        # venv must be built on a base Python the sandbox can reach (see the Dockerfile's UV_PYTHON_*)
        cmd = [sys.executable, "-s", "-m", "b123d_print.worker", job_file]
        k = kind()
        if k == "sandbox-exec":
            prof = os.path.join(tmp, "profile.sb")
            with open(prof, "w", encoding="utf-8") as f:
                f.write(macos_profile(writable, readable, hidden, secrets))
            cmd = ["sandbox-exec", "-f", prof] + cmd
        elif k == "bwrap":
            cmd = linux_bwrap(writable, readable, hidden, secrets) + cmd

        def limits():  # in the child, before exec
            try:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, (int(timeout) + 5, int(timeout) + 10))
            except Exception:
                pass

        if epoch is not None and current_epoch() != epoch:  # cancelled before it got this far
            return {"ok": False, "error": "cancelled before it started (server shutting down)"}
        with build_slot():  # shared with every other server process of this user
            if epoch is not None and current_epoch() != epoch:  # cancelled while it waited
                return {"ok": False, "error": "cancelled before it started (server shutting down)"}
            if WINDOWS:
                proc = _popen_windows(cmd, env, tmp, timeout)
            else:
                proc = subprocess.Popen(cmd, env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, preexec_fn=limits)
            with _LIVE_LOCK:
                _LIVE.add(proc)
                cancelled = epoch is not None and _EPOCH != epoch  # kill_all ran while it started
            if cancelled:
                _killpg(proc)
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
        log = _tail(stdout, stderr, progress=False)  # the worker reported: its progress lines say nothing more
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
    """Stop every running worker (server shutdown). Returns how many were running. Builds that
    were claimed but had not started their process yet see the new epoch and do not start."""
    global _EPOCH
    with _LIVE_LOCK:
        _EPOCH += 1
        procs = list(_LIVE)
    for p in procs:
        _killpg(p)
    return len(procs)


def _tail(stdout: bytes, stderr: bytes, n: int = 4000, progress: bool = True) -> str:
    """The end of the worker's output; progress=False drops its progress lines (diagnose.PROGRESS),
    which only matter when it could not report (a timeout: which piece it was building)."""
    from .diagnose import PROGRESS

    s = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
    if not progress:
        s = "".join(line for line in s.splitlines(keepends=True) if not line.startswith(PROGRESS))
    return s[-n:].strip()
