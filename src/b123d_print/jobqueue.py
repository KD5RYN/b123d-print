"""Hand sandbox jobs to a separate worker process through a folder: the Docker HTTP setup runs the
model-written part scripts in a worker container with no network, apart from the HTTP front.

    b123d-print-mcp --transport http --job-queue /work/.b123d-print/jobs     # front: network, no builds
    b123d-print-mcp worker --queue /work/.b123d-print/jobs                   # worker: network_mode none

The folder is on the volume both containers share; nothing travels over a network. Every file is
written to a temporary name and renamed into place, so the other side never reads half of it:

    <id>.job       the front submits a job                      (front writes)
    <id>.running   a worker claimed it (renamed from .job)       (worker renames; one worker wins)
    <id>.result    the result                                    (worker writes, front reads + deletes)
    worker.alive   heartbeat, rewritten every second             (worker)
    cancel         the front shut down: stop what is running     (front writes, worker deletes)
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import sys
import threading
import time
from pathlib import Path

POLL = 0.05  # seconds between looks at the folder
HEARTBEAT_STALE = 10.0  # a worker that has not written worker.alive for this long is gone
CLAIM_WAIT = 30.0  # a job no worker claims within this long fails


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def worker_age(queue: Path) -> float | None:
    """Seconds since the worker's last heartbeat, or None if there never was one."""
    try:
        return time.time() - (queue / "worker.alive").stat().st_mtime
    except OSError:
        return None


class WorkerDown(RuntimeError):
    pass


def submit(queue: Path, job: dict, workspace: Path, out_dir: Path, timeout: float) -> dict:
    """Run `job` in the worker and return its result dict (what sandbox.run_job returns). Blocking."""
    age = worker_age(queue)
    if age is None or age > HEARTBEAT_STALE:
        raise WorkerDown(f"the build worker is not running (no heartbeat in {queue}"
                         + (f" for {age:.0f} s)" if age is not None else ")"))
    jid = f"{time.time_ns()}-{secrets.token_hex(4)}"
    _write(queue / f"{jid}.job", {"job": job, "workspace": str(workspace), "out_dir": str(out_dir), "timeout": timeout})
    result, started = queue / f"{jid}.result", time.monotonic()
    while True:
        if result.exists():
            res = json.loads(result.read_text(encoding="utf-8"))
            result.unlink(missing_ok=True)
            return res
        waited = time.monotonic() - started
        if (queue / f"{jid}.job").exists() and waited > CLAIM_WAIT:
            try:
                (queue / f"{jid}.job").unlink()
            except FileNotFoundError:  # claimed just now: keep waiting
                continue
            raise WorkerDown(f"no build worker took the job within {CLAIM_WAIT:g} s")
        if waited > CLAIM_WAIT + timeout + 30:
            raise WorkerDown(f"the build worker gave no result within {timeout:g} s (+ queue time)")
        time.sleep(POLL)


def cancel_all(queue: Path) -> None:
    """The front is shutting down: tell the worker to stop the builds it is running."""
    try:
        _write(queue / "cancel", {"at": time.time()})
    except OSError:
        pass


def serve(queue: Path, max_jobs: int, stop: threading.Event | None = None) -> None:
    """The worker: claim jobs, run each in the local sandbox (sandbox.run_job), write the result."""
    from . import sandbox

    queue.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    slots = threading.Semaphore(max_jobs)
    print(f"b123d-print worker: queue {queue}, {max_jobs} job(s) at once, sandbox: {sandbox.describe()}", file=sys.stderr)

    def run(running: Path) -> None:
        try:
            spec = json.loads(running.read_text(encoding="utf-8"))
            res = sandbox.run_job(spec["job"], Path(spec["workspace"]), Path(spec["out_dir"]), float(spec["timeout"]))
        except Exception as e:  # never leave the front waiting
            res = {"ok": False, "error": f"worker: {type(e).__name__}: {e}"}
        _write(running.with_suffix(".result"), res)
        running.unlink(missing_ok=True)
        slots.release()

    last_beat = last_sweep = 0.0
    while not stop.is_set():
        try:
            now = time.time()
            if now - last_beat >= 1.0:
                (queue / "worker.alive").write_text(str(now), encoding="utf-8")
                last_beat = now
            if (queue / "cancel").exists():
                n = sandbox.kill_all()
                (queue / "cancel").unlink(missing_ok=True)
                if n:
                    print(f"b123d-print worker: front shut down, {n} running build(s) killed", file=sys.stderr)
            for job in sorted(queue.glob("*.job")):
                if not slots.acquire(blocking=False):
                    break
                running = job.with_suffix(".running")
                try:
                    os.rename(job, running)  # atomic: if another worker got it first, this fails
                except OSError:
                    slots.release()
                    continue
                threading.Thread(target=run, args=(running,), daemon=True).start()
            if now - last_sweep > 60:  # results nobody collected (the front restarted)
                last_sweep = now
                for p in queue.glob("*.result"):
                    try:
                        if now - p.stat().st_mtime > 600:
                            p.unlink()
                    except OSError:  # the front took it meanwhile
                        pass
        except OSError as e:  # never let one bad moment (a full disk, a race) stop the worker
            print(f"b123d-print worker: {e}", file=sys.stderr)
        stop.wait(POLL)


def main(queue: Path, max_jobs: int, check: bool = False) -> int:
    if check:  # Docker HEALTHCHECK for the worker container
        age = worker_age(queue)
        ok = age is not None and age < HEARTBEAT_STALE
        print("worker ok" if ok else f"worker heartbeat missing or stale ({age})", file=sys.stderr)
        return 0 if ok else 1
    stop = threading.Event()

    def on_signal(*_):
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        serve(queue, max_jobs, stop)
    finally:
        from . import sandbox

        n = sandbox.kill_all()
        (queue / "worker.alive").unlink(missing_ok=True)
        print(f"b123d-print worker: stopped{f' ({n} running build(s) killed)' if n else ''}", file=sys.stderr)
    return 0
