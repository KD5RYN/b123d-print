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
