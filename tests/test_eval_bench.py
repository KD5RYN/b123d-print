"""Benchmark scorers, offline: every task's reference script must pass its checks and every known
bad script must fail exactly the checks benchmarks.toml lists for it. No model, no network, no
API key; one fake-agent run goes through the real MCP server and the sandboxed scoring."""

import sys
from pathlib import Path

import anyio
import pytest
from build123d import Box, Cylinder, Pos

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))  # repo-only tooling, not in the package
from b123d_eval import benchmarks, scoring  # noqa: E402
from b123d_eval.agents import Limits  # noqa: E402
from b123d_eval.runner import Endpoint  # noqa: E402

TASKS = benchmarks.load_tasks()


def test_manifest_is_valid():
    assert {t.mistake for t in TASKS} >= {"print orientation", "coordinates from a datum", "mirrored pieces", "units",
                                          "assembly placement"}
    for t in TASKS:
        assert t.reference_path.is_file(), t.id
        assert t.bad, f"{t.id}: no known bad script"
        for p, want in t.bad_paths().items():
            assert p.is_file(), p
            assert want and set(want) <= set(scoring.CHECKS) | {"fit_holes", "standins"}, (t.id, p.name, want)
        assert t.prompt.strip() and t.checks, t.id
        assert f'new_part(name="{t.id}")' in benchmarks.prompt_for(t, t.id), t.id


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_selftest(task, tmp_path):
    rows = benchmarks.selftest([task], tmp_path)
    assert all(r["ok"] for r in rows), "\n" + benchmarks.selftest_text(rows)


def test_hole_datums():
    plate = Pos(0, 0, 2) * Box(40, 20, 4) - Pos(-10, 5, 2) * Cylinder(1.5, 10)
    cand = scoring.Candidate(Path("x.py"), {"part": plate})
    assert scoring.check_holes(cand, None, [[10, 15, 3]], datum="min").ok  # from the -X -Y corner
    assert scoring.check_holes(cand, None, [[-10, 5, 3]], datum="origin").ok
    r = scoring.check_holes(cand, None, [[10, 15, 3]], datum="origin")
    assert not r.ok and "missing d 3 at (10, 15)" in r.detail
    assert not scoring.check_holes(cand, None, [[10, 15, 4]]).ok  # a 3 mm hole is not a 4 mm one
    assert scoring.check_holes(cand, None, [[10, 15, 2.8]]).ok  # hole compensation: up to d_tol larger
    assert not scoring.check_holes(cand, None, [], exact=True).ok  # an extra hole
    assert scoring.check_on_bed(cand, None)[0].ok


def test_unknown_check_is_refused(tmp_path):
    (tmp_path / "b.toml").write_text('[[task]]\nid = "x"\ntitle = "x"\nprompt = "x"\nreference = "x.py"\n'
                                     'checks = [{ check = "nope" }]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown check 'nope'"):
        benchmarks.load_tasks(tmp_path / "b.toml")


def test_broken_script_fails_cleanly(tmp_path):
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    (task,) = benchmarks.select(TASKS, "datum_hole_plate")
    res = benchmarks.score_script(task, tmp_path / "broken.py", tmp_path / "out")
    assert not res["passed"] and res["failures"] == ["build"] and "boom" in res["checks"][0]["detail"]


def test_fake_agent_through_server(tmp_path):
    """The fake agent writes the reference through the real MCP server; scoring runs sandboxed."""
    (task,) = benchmarks.select(TASKS, "datum_hole_plate")
    out = tmp_path / "run"
    s = anyio.run(lambda: benchmarks.run_bench([task], "fake", Endpoint.from_args(None, None, None, 120), out,
                                               Limits(timeout_s=300)))
    (r,) = s["results"]
    assert r["agent_run"]["stop"] == "done", r
    assert r["result"] == "scored" and r["passed"] and r["score"] == 100.0, r
    for f in ("results.json", "report.md", "report.html", "datum_hole_plate/candidate.py", "datum_hole_plate/checks.json",
              "datum_hole_plate/prompt.txt", "datum_hole_plate/transcript.json"):
        assert (out / f).is_file(), f
    assert "datum A" in (out / "datum_hole_plate" / "prompt.txt").read_text(encoding="utf-8")
    assert "[ok  ] holes" in (out / "report.md").read_text(encoding="utf-8")
