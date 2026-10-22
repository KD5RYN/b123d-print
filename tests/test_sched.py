"""Fair build slots (sched.py, #71/#73): round-robin across clients, per-client caps, the quick lane."""

import time

import anyio
import pytest

from b123d_print import sched


async def _hold(s, client, order, gate, quick=False, **kw):
    async with s.slot(client, quick=quick, **kw) as pool:
        order.append((client, pool))
        await gate.wait()


def test_round_robin_across_clients_fifo_within_one():
    async def main():
        s = sched.FairScheduler(1)
        order, gates = [], []
        started = []

        async def job(client, name):
            async with s.slot(client):
                order.append(name)
                g = anyio.Event()
                gates.append(g)
                await g.wait()

        async with anyio.create_task_group() as tg:
            tg.start_soon(job, "A", "a1")
            await anyio.sleep(0.01)
            for c, n in [("A", "a2"), ("A", "a3"), ("A", "a4"), ("B", "b1"), ("B", "b2"), ("C", "c1")]:
                tg.start_soon(job, c, n)
                await anyio.sleep(0.01)  # arrival order as listed
            while len(order) < 7:
                gates[len(order) - 1].set()  # finish the running job: the next one starts
                await anyio.sleep(0.01)
            gates[-1].set()
        started.extend(order)
        return started

    # A came first with four jobs, but once B and C wait they take turns: never two of A's in a row
    # while someone else waits; A's own jobs keep their order
    assert anyio.run(main) == ["a1", "b1", "c1", "a2", "b2", "a3", "a4"]


def test_fewest_running_goes_first():
    async def main():
        s = sched.FairScheduler(3)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            for _ in range(3):  # A takes every slot
                tg.start_soon(_hold, s, "A", order, gate)
            await anyio.sleep(0.01)
            tg.start_soon(_hold, s, "A", order, gate)
            await anyio.sleep(0.01)
            tg.start_soon(_hold, s, "B", order, gate)  # came later, but runs nothing yet
            await anyio.sleep(0.01)
            assert s.running == {"A": 3} and len(s.waiting) == 2
            gate.set()
        return [c for c, _ in order]

    assert anyio.run(main) == ["A", "A", "A", "B", "A"]


def test_per_client_cap_refuses_at_once():
    async def main():
        s = sched.FairScheduler(1, per_client=2)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(_hold, s, "A", order, gate)
            tg.start_soon(_hold, s, "A", order, gate)  # waits: A has 1 running + 1 queued
            await anyio.sleep(0.01)
            t0 = time.monotonic()
            with pytest.raises(sched.Busy) as e:
                async with s.slot("A"):
                    pass
            assert time.monotonic() - t0 < 0.5  # refused, not queued
            assert "2 jobs running or queued" in str(e.value) and "wait for one to finish" in str(e.value)
            assert s.room("A") == 0 and s.room("B") == 2
            tg.start_soon(_hold, s, "B", order, gate)  # another client is not affected by A's cap
            await anyio.sleep(0.01)
            assert s.load("B") == 1
            gate.set()
        return order

    assert len(anyio.run(main)) == 3


def test_quick_call_takes_the_reserved_slot_while_long_builds_queue():
    async def main():
        s = sched.FairScheduler(3, reserved=1)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            for _ in range(6):  # client A: six long builds; two run (the third slot is reserved)
                tg.start_soon(_hold, s, "A", order, gate)
            await anyio.sleep(0.01)
            assert s.in_general == 2 and s.in_reserved == 0 and len(s.waiting) == 4
            done = anyio.Event()

            async def quick():
                async with s.slot("B", quick=True) as pool:
                    order.append(("B", pool))
                done.set()

            tg.start_soon(quick)
            with anyio.fail_after(1):  # at once, not after A's builds
                await done.wait()
            gate.set()
        return order

    order = anyio.run(main)
    assert ("B", "reserved") in order and order.index(("B", "reserved")) == 2


def test_quick_job_uses_a_free_general_slot_and_long_never_the_reserved():
    async def main():
        s = sched.FairScheduler(2, reserved=1)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(_hold, s, "A", order, gate, True)  # quick: the reserved slot
            tg.start_soon(_hold, s, "B", order, gate, True)  # quick: the general one is free
            await anyio.sleep(0.01)
            tg.start_soon(_hold, s, "C", order, gate)  # long: must wait, never the reserved slot
            await anyio.sleep(0.01)
            assert [p for _, p in order] == ["reserved", "general"] and len(s.waiting) == 1
            gate.set()
        return order

    assert anyio.run(main)[-1] == ("C", "general")


def test_reserved_never_takes_every_slot():
    assert sched.FairScheduler(1, reserved=1).reserved == 0
    assert sched.FairScheduler(3, reserved=5).reserved == 2


def test_cancel_while_waiting_or_after_the_grant_frees_everything():
    async def main():
        s = sched.FairScheduler(1)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(_hold, s, "A", order, gate)
            await anyio.sleep(0.01)
            with anyio.move_on_after(0.05):  # waits, then is cancelled: leaves the queue
                async with s.slot("B"):
                    pytest.fail("got a slot that was taken")
            assert s.waiting == [] and s.load("B") == 0
            gate.set()
        assert s.running == {} and s.in_general == 0
        with anyio.CancelScope() as scope:  # granted, then cancelled inside the body: released
            async with s.slot("C"):
                scope.cancel()
                await anyio.sleep(1)
        assert s.running == {} and s.in_general == 0

    anyio.run(main)


def test_wait_limit_refuses_with_a_message():
    async def main():
        s = sched.FairScheduler(1)
        order, gate = [], anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(_hold, s, "A", order, gate)
            await anyio.sleep(0.01)
            with pytest.raises(sched.Waited) as e:
                async with s.slot("B", wait_limit=0.05):
                    pass
            assert "server busy" in str(e.value) and s.waiting == []
            gate.set()

    anyio.run(main)


def test_check_shares():
    async def main():
        s = sched.FairScheduler(3, reserved=1, per_client=4)
        assert s.shares("A", 2) == 2  # idle: two workers
        gate, order = anyio.Event(), []
        async with anyio.create_task_group() as tg:
            tg.start_soon(_hold, s, "B", order, gate)
            await anyio.sleep(0.01)
            assert s.shares("A", 2) == 1  # one general slot free
            tg.start_soon(_hold, s, "B", order, gate)
            tg.start_soon(_hold, s, "C", order, gate)
            await anyio.sleep(0.01)
            assert s.shares("A", 2) == 1  # others wait: never more than one
            gate.set()
        assert sched.FairScheduler(4, per_client=3).shares("A", 2) == 2

    anyio.run(main)


def test_server_quick_call_does_not_wait_behind_another_clients_builds(monkeypatch, tmp_path):
    """#73's measurement, with sleeps for builds: client A queues 6 builds, client B measures."""
    from b123d_print import mcp_server as m

    build_s = 0.6

    def fake_run_job(job, root, out, timeout):
        time.sleep(0.05 if job["op"] == "measure" else build_s)
        return {"ok": True, "op": job["op"]}

    monkeypatch.setattr(m.sandbox, "run_job", fake_run_job)
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "transport", "http")
    monkeypatch.setitem(m.STATE, "max_builds", 3)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setitem(m.STATE, "quick_slots", None)
    monkeypatch.setitem(m.STATE, "client_jobs", None)
    who = {"c": "A"}
    monkeypatch.setattr(m, "_client", lambda: who["c"])

    async def main():
        results, latency = [], {}

        async def a_build():
            results.append(await m._run({"op": "build"}, tmp_path))

        async with anyio.create_task_group() as tg:
            for _ in range(6):
                tg.start_soon(a_build)
                await anyio.sleep(0)
            await anyio.sleep(0.05)
            who["c"] = "B"
            t0 = time.monotonic()
            res = await m._run({"op": "measure"}, tmp_path)
            latency["B"] = time.monotonic() - t0
            assert res["ok"], res
        return results, latency

    results, latency = anyio.run(main)
    assert latency["B"] < build_s, latency  # did not wait for any of A's builds
    refused = [r for r in results if not r["ok"]]
    # A's cap (4 running + queued over HTTP): two of the six are refused at once, with the reason
    assert len(refused) == 2 and all("wait for one to finish" in r["error"] and r["usage_error"] for r in refused)
    assert m._scheduler().running == {}


def test_server_check_splits_into_two_at_most(monkeypatch):
    from b123d_print import mcp_server as m

    calls = []

    async def fake(name, op, **kw):
        calls.append(kw.get("share"))
        return {"ok": True, "shares": {}}

    monkeypatch.setattr(m, "_job", fake)
    monkeypatch.setitem(m.STATE, "max_builds", 4)
    monkeypatch.setitem(m.STATE, "transport", "stdio")
    monkeypatch.setitem(m.STATE, "limiter", None)
    anyio.run(m._check, "x", None)
    assert sorted(calls) == [[0, 2], [1, 2]]


def test_worker_takes_turns_between_clients(tmp_path, monkeypatch):
    """The worker side of the queue: jobs piled up in the folder are claimed round-robin by client."""
    import threading

    from b123d_print import jobqueue, sandbox

    started, release = [], threading.Event()

    def fake_run_job(job, workspace, out_dir, timeout, epoch=None):
        started.append(job["name"])
        release.wait(5)
        return {"ok": True}

    monkeypatch.setattr(sandbox, "run_job", fake_run_job)
    q = tmp_path / "q"
    q.mkdir()
    for i, (client, name) in enumerate([("A", "a1"), ("A", "a2"), ("A", "a3"), ("B", "b1"), ("C", "c1")]):
        jobqueue._write(q / f"{1000 + i}-x.job", {"job": {"name": name}, "workspace": str(tmp_path),
                                                  "out_dir": str(tmp_path), "timeout": 5, "client": client})
    stop = threading.Event()
    t = threading.Thread(target=jobqueue.serve, args=(q, 3, stop), daemon=True)
    t.start()
    try:
        for _ in range(100):
            if len(started) >= 3:
                break
            time.sleep(0.05)
        assert sorted(started) == ["a1", "b1", "c1"], started  # not a1, a2, a3
    finally:
        release.set()
        stop.set()
        t.join(5)
