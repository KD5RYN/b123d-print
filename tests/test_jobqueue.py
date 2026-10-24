"""The job queue between the HTTP front and a separate build worker."""

import threading
import time

import pytest

from b123d_print import jobqueue

SCRIPT = '''from build123d import Box
def build():
    return Box(10, 20, 30)
'''


@pytest.fixture
def worker(tmp_path):
    q = tmp_path / "queue"
    stop = threading.Event()
    t = threading.Thread(target=jobqueue.serve, args=(q, 2, stop), daemon=True)
    t.start()
    for _ in range(100):
        if (q / "worker.alive").exists():
            break
        time.sleep(0.05)
    yield q
    stop.set()
    t.join(5)


def part(tmp_path, code=SCRIPT):
    d = tmp_path / "ws/parts/p"
    d.mkdir(parents=True)
    (d / "p.py").write_text(code)
    return d / "p.py"


def test_job_runs_in_the_worker(tmp_path, worker):
    script = part(tmp_path)
    res = jobqueue.submit(worker, {"op": "build", "script": str(script)}, tmp_path / "ws", script.parent / "out", 60)
    assert res["ok"] and res["variants"]["standard"]["parts"]["part"]["z"] == 30.0
    assert not list(worker.glob("*.job")) and not list(worker.glob("*.result")) and not list(worker.glob("*.running"))


def test_script_errors_come_back(tmp_path, worker):
    script = part(tmp_path, "raise RuntimeError('boom')\n")
    res = jobqueue.submit(worker, {"op": "build", "script": str(script)}, tmp_path / "ws", script.parent / "out", 60)
    assert not res["ok"] and "boom" in res["error"]


def test_no_worker(tmp_path):
    with pytest.raises(jobqueue.WorkerDown, match="not running"):
        jobqueue.submit(tmp_path, {"op": "build"}, tmp_path, tmp_path, 5)


def test_cancel_stops_running_builds(tmp_path, worker):
    script = part(tmp_path, "while True:\n    pass\n")
    out = {}
    t = threading.Thread(target=lambda: out.update(
        res=jobqueue.submit(worker, {"op": "build", "script": str(script)}, tmp_path / "ws", script.parent / "out", 60)))
    t.start()
    for _ in range(200):
        if list(worker.glob("*.running")):
            break
        time.sleep(0.05)
    time.sleep(1.0)  # let the worker process start
    jobqueue.cancel_all(worker)
    t.join(120)  # no time budget: an uncancelled endless loop would end "timed out" at 60 s,
    # so the result, not the wait, proves the cancel stopped it
    assert not t.is_alive() and not out["res"]["ok"] and "timed out" not in out["res"].get("error", "")


def test_health_check(tmp_path, worker):
    assert jobqueue.main(worker, 1, check=True) == 0
    assert jobqueue.main(tmp_path / "nothing", 1, check=True) == 1


def test_cancel_before_the_build_starts(tmp_path):
    """A build claimed before a cancel never starts its process (the race the cancel test hit)."""
    from b123d_print import sandbox

    script = part(tmp_path, "while True:\n    pass\n")
    epoch = sandbox.current_epoch()
    sandbox.kill_all()  # the cancel lands between claiming the job and starting its process
    res = sandbox.run_job({"op": "build", "script": str(script)}, tmp_path / "ws", script.parent / "out", 60, epoch=epoch)
    # no time bound: on a busy runner other tests hold build slots; the message proves it never ran
    assert not res["ok"] and "cancelled before it started" in res["error"]


def _cgroup(tmp_path, current, limit):
    d = tmp_path / "cgroup"
    d.mkdir(exist_ok=True)
    (d / "pids.current").write_text(f"{current}\n")
    (d / "pids.max").write_text(f"{limit}\n")
    return d


def test_pids_pressure(tmp_path):
    assert jobqueue.pids_pressure(tmp_path / "none") is None
    assert jobqueue.pids_pressure(_cgroup(tmp_path, 7, "max")) is None
    assert jobqueue.pids_pressure(_cgroup(tmp_path, 7, 1024)) == (7, 1024)
    assert jobqueue.pressure_problem(_cgroup(tmp_path, 100, 1024)) is None
    assert "1021 of the container's 1024 processes" in jobqueue.pressure_problem(_cgroup(tmp_path, 1021, 1024))


def test_worker_reports_pids_pressure(tmp_path, monkeypatch):
    """The 0.3.12 fault: zombies filled pids_limit, every build failed, /health still said ok."""
    monkeypatch.setattr(jobqueue, "CGROUP", _cgroup(tmp_path, 1000, 1024))
    monkeypatch.setattr(jobqueue, "PRESSURE_EVERY", 0.05)
    q = tmp_path / "queue"
    stop = threading.Event()
    t = threading.Thread(target=jobqueue.serve, args=(q, 1, stop), daemon=True)
    t.start()
    try:
        for _ in range(100):
            if jobqueue.degraded(q):
                break
            time.sleep(0.05)
        assert "1000 of the container's 1024" in jobqueue.degraded(q)
        assert jobqueue.main(q, 1, check=True) == 1  # the Docker healthcheck says unhealthy
        jobqueue.CGROUP.joinpath("pids.current").write_text("12\n")  # fixed (restarted, reaped)
        for _ in range(100):
            if not jobqueue.degraded(q):
                break
            time.sleep(0.05)
        assert jobqueue.degraded(q) is None and jobqueue.main(q, 1, check=True) == 0
    finally:
        stop.set()
        t.join(5)


def test_health_says_degraded(tmp_path, monkeypatch):
    import asyncio
    import json

    from b123d_print import mcp_server as m

    q = tmp_path / "queue"
    q.mkdir()
    (q / "worker.alive").write_text("now")
    monkeypatch.setitem(m.STATE, "queue", q)
    assert asyncio.run(m.health(None)).status_code == 200
    (q / jobqueue.DEGRADED).write_text("1000 of the container's 1024 processes are in use")
    r = asyncio.run(m.health(None))
    assert r.status_code == 503 and json.loads(r.body) | {"version": ""} == {"status": "degraded", "version": "",
                                                                              "worker": "degraded"}
