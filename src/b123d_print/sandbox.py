"""Run a worker job in a separate, restricted process.

Layers (strongest available is used; see `describe()`):
  - macOS: sandbox-exec profile: no network, no process spawning, writes only to the part's out/
    folder and a scratch folder, no reads of your home folder outside the workspace and Python.
  - Linux: bubblewrap (`bwrap`) if installed: read-only root, no network, the same writable
    folders, home folder hidden except the workspace.
  - Always: a timeout (process group killed), CPU-time limit, scrubbed environment and the
    worker's audit hook (no sockets, subprocesses or ctypes; writes only to allowed folders).
  - For untrusted input, run the whole server in the Docker image with --network none.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
from pathlib import Path

_LIVE: set[subprocess.Popen] = set()  # running workers, so a server shutdown can stop them
_LIVE_LOCK = threading.Lock()

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "b123d-print"


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
        "none": "process isolation + audit hook only (install bubblewrap on Linux, or use the Docker image)",
    }[k] if not (k == "none" and os.environ.get("B123D_PRINT_SANDBOX") == "none") else (
        "OS sandbox off (B123D_PRINT_SANDBOX=none): process isolation + audit hook; in the Docker image the container is the sandbox")


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
            "MPLCONFIGDIR": _real(mpl),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p and os.path.isdir(p)),
            "LANG": "C.UTF-8",
        }
        for var in ("B123D_PRINT_HOLE_COMP", "B123D_PRINT_CLEARANCE", "B123D_PRINT_MIN_WALL", "B123D_PRINT_MAX_OVERHANG",
                    "B123D_PRINT_FORMATS", "XDG_CONFIG_HOME"):
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
        if proc.returncode in (-signal.SIGKILL, -signal.SIGTERM) and not Path(job["result"]).exists():
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
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


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
