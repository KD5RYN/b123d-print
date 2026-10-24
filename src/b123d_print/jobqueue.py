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
    worker.degraded  why the worker is close to failing, e.g. its container's process limit
                   nearly used up (worker writes, removes when fine; /health and --check report it)
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
DEGRADED = "worker.degraded"
PIDS_WARN = 0.8  # share of the container's process limit (pids.max) in use that marks the worker degraded
PRESSURE_EVERY = 10.0  # seconds between looks at it
CGROUP = Path("/sys/fs/cgroup")  # cgroup v2, as a container sees its own


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def worker_age(queue: Path) -> float | None:
    """Seconds since the worker's last heartbeat, or None if there never was one."""
    try:
        return time.time() - (queue / "worker.alive").stat().st_mtime
    except OSError:
        return None


def pids_pressure(cgroup: Path | None = None) -> tuple[int, int] | None:
    """(processes and threads in use, limit) of this container's process limit (cgroup v2 pids;
    zombies count too), or None where there is no limit to read."""
    cgroup = CGROUP if cgroup is None else cgroup
    try:
        cur = int((cgroup / "pids.current").read_text(encoding="ascii"))
        limit = (cgroup / "pids.max").read_text(encoding="ascii").strip()
        return None if limit == "max" else (cur, int(limit))
    except (OSError, ValueError):
        return None


def pressure_problem(cgroup: Path | None = None) -> str | None:
    """Why the worker is close to failing, or None. Every job needs new processes (bubblewrap), so
    a process limit nearly used up fails every build with "Can't fork" while the heartbeat looks fine."""
    p = pids_pressure(cgroup)
    if p and p[0] >= PIDS_WARN * p[1]:
        return (f"{p[0]} of the container's {p[1]} processes are in use: new builds will soon fail with "
                "\"Can't fork\" (zombie processes nobody reaps? the image runs tini as its init for that; "
                "restart the worker, or raise pids_limit)")
    return None


def degraded(queue: Path) -> str | None:
    """The worker's own report of a problem (DEGRADED), or None."""
    try:
        return (queue / DEGRADED).read_text(encoding="utf-8").strip() or "degraded"
    except OSError:
        return None


class WorkerDown(RuntimeError):
    pass


def submit(queue: Path, job: dict, workspace: Path, out_dir: Path, timeout: float, client: str = "") -> dict:
    """Run `job` in the worker and return its result dict (what sandbox.run_job returns). Blocking.
    `client`: whose job it is (the token), so the worker takes turns between clients too."""
    age = worker_age(queue)
    if age is None or age > HEARTBEAT_STALE:
        raise WorkerDown(f"the build worker is not running (no heartbeat in {queue}"
                         + (f" for {age:.0f} s)" if age is not None else ")"))
    jid = f"{time.time_ns()}-{secrets.token_hex(4)}"
    _write(queue / f"{jid}.job", {"job": job, "workspace": str(workspace), "out_dir": str(out_dir), "timeout": timeout,
                                  "client": client})
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
    # a job must never read the queue (other clients' job files live here): hide it from every build
    sandbox.EXTRA_HIDDEN.update({str(queue), str(queue.parent)})
    stop = stop or threading.Event()
    slots = threading.Semaphore(max_jobs)
    running: dict[str, int] = {}  # client -> jobs running (claim order, see `order`)
    lock = threading.Lock()
    mem = sandbox.human_size(sandbox.MAX_MEMORY) + " per job" if sandbox.memory_limited() else "no limit"
    print(f"b123d-print worker: queue {queue}, {max_jobs} job(s) at once, memory {mem}, sandbox: {sandbox.describe()}",
          file=sys.stderr)
    err = sandbox.sandbox_error()
    if err:  # loud, repeated: the worker keeps running but refuses every job (fail closed) until fixed
        print(f"b123d-print worker: REFUSING ALL JOBS — {err}. Set B123D_PRINT_SANDBOX=none to run with "
              "the audit hook only (not an isolation boundary), or enable it.", file=sys.stderr)

    def run(path: Path, client: str, epoch: int) -> None:
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            res = sandbox.run_job(spec["job"], Path(spec["workspace"]), Path(spec["out_dir"]), float(spec["timeout"]),
                                  epoch=epoch)
        except Exception as e:  # never leave the front waiting
            res = {"ok": False, "error": f"worker: {type(e).__name__}: {e}"}
        _write(path.with_suffix(".result"), res)
        path.unlink(missing_ok=True)
        with lock:
            running[client] -= 1
            if not running[client]:
                del running[client]
        slots.release()

    def client_of(job: Path) -> str:
        try:
            return str(json.loads(job.read_text(encoding="utf-8")).get("client") or "")
        except (OSError, ValueError):  # claimed meanwhile, or half-written by an old front: no client
            return ""

    def order(jobs: list[Path]) -> list[Path]:
        """The front already shares its slots fairly (sched.py) and submits no more than the worker
        runs; this keeps the worker fair too when jobs pile up here anyway (a front that gave up on
        a job while it still runs): fewest running jobs per client first, then oldest first."""
        if len(jobs) < 2:
            return jobs
        with lock:
            busy = dict(running)
        keyed = [(client_of(j), j) for j in sorted(jobs)]
        out, seen = [], dict(busy)
        while keyed:  # round-robin: take the oldest job of the least busy client, count it, repeat
            i = min(range(len(keyed)), key=lambda k: (seen.get(keyed[k][0], 0), k))
            c, j = keyed.pop(i)
            seen[c] = seen.get(c, 0) + 1
            out.append(j)
        return out

    last_beat = last_sweep = last_pressure = 0.0
    reported = None
    while not stop.is_set():
        try:
            now = time.time()
            if now - last_beat >= 1.0:
                (queue / "worker.alive").write_text(str(now), encoding="utf-8")
                last_beat = now
            if now - last_pressure >= PRESSURE_EVERY:
                last_pressure = now
                problem = pressure_problem()
                if problem:
                    _write_text(queue / DEGRADED, problem)
                    if problem != reported:
                        print(f"b123d-print worker: DEGRADED — {problem}", file=sys.stderr)
                else:
                    (queue / DEGRADED).unlink(missing_ok=True)
                reported = problem
            if (queue / "cancel").exists():
                n = sandbox.kill_all()
                (queue / "cancel").unlink(missing_ok=True)
                if n:
                    print(f"b123d-print worker: front shut down, {n} running build(s) killed", file=sys.stderr)
            for job in order(sorted(queue.glob("*.job"))):
                if not slots.acquire(blocking=False):
                    break
                client = client_of(job)
                claimed = job.with_suffix(".running")
                try:
                    os.rename(job, claimed)  # atomic: if another worker got it first, this fails
                except OSError:
                    slots.release()
                    continue
                with lock:
                    running[client] = running.get(client, 0) + 1
                threading.Thread(target=run, args=(claimed, client, sandbox.current_epoch()), daemon=True).start()
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
    from . import sandbox

    if check:  # Docker HEALTHCHECK for the worker container
        err = sandbox.sandbox_error()
        if err:  # a required sandbox that cannot start: report unhealthy so the operator sees it
            print(f"worker sandbox unavailable: {err}", file=sys.stderr)
            return 1
        age = worker_age(queue)
        if age is None or age >= HEARTBEAT_STALE:
            print(f"worker heartbeat missing or stale ({age})", file=sys.stderr)
            return 1
        problem = degraded(queue) or pressure_problem()
        if problem:  # unhealthy, so `docker ps` and monitors show it before builds start failing
            print(f"worker degraded: {problem}", file=sys.stderr)
            return 1
        print("worker ok", file=sys.stderr)
        return 0
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
        (queue / DEGRADED).unlink(missing_ok=True)
        print(f"b123d-print worker: stopped{f' ({n} running build(s) killed)' if n else ''}", file=sys.stderr)
    return 0
