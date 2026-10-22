"""Checks on mesh-imported parts: fast section outlines, the prefiltered ray cast, the cache of the
original's findings, partial results at the time limit, and the benchmark script."""

import math
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Box, Cylinder, Pos, Rot

from b123d_print import checks as ck, sandbox
from b123d_print.config import load_settings
from b123d_print.project import OriginalFindings, load, run_checks, shape_fingerprint

ROOT = Path(__file__).resolve().parents[1]
BED = (Align.CENTER, Align.CENTER, Align.MIN)


def faceted(tmp_path, tol=0.02):
    """A mesh-derived solid (import_model's conversion of a faceted plate with rings and holes)."""
    from b123d_print.compare import mesh_from_shape
    from b123d_print.remix import load as load_model

    from test_remix import write_stl

    shape = Box(60, 30, 3, align=BED)
    for x in (-15, 15):
        shape += Pos(x, 0, 9) * Rot(90, 0, 0) * (Cylinder(8, 12) - Cylinder(6, 14))
        shape -= Pos(x, 0, 16) * Box(5, 14, 4)
    shape -= Pos(0, 8, 0) * Cylinder(2, 10)
    path = write_stl(tmp_path / "m.stl", mesh_from_shape(shape, tol).triangles)
    return load_model(path)[0]


def test_wire_edges_in_order_and_fast_outline(tmp_path):
    part = faceted(tmp_path)
    faces = ck.section_faces(part, "XZ", 0.0)
    assert faces
    for f in faces:
        for w in [f.outer_wire(), *f.inner_wires()]:
            edges = ck.wire_edges(w)
            assert len(edges) == len(w.edges())
            for e0, e1 in zip(edges, edges[1:]):  # each edge starts where the previous one ends
                assert (e0.end_point() - e1.start_point()).length < 1e-4
    # a straight edge's points are the same as Edge.positions gives
    e = next(e for f in faces for e in f.edges() if e.geom_type.name == "LINE" and e.length > 0.5)
    pts = ck.edge_points(e, 0.1)
    ref = np.array([(p.X, p.Y, p.Z) for p in e.positions(list(np.linspace(0, 1, len(pts))))])
    assert np.allclose(pts, ref, atol=1e-9)


@pytest.mark.parametrize("plane,at,near,radius,limit", [
    ("XZ", 0.0, None, None, None),
    ("XZ", 0.0, (-15, 9), 10, None),
    ("XY", 1.5, (0, 8), 4, None),
    ("XY", 10.0, None, None, 0.8),
    ("YZ", 15.0, None, None, None),
])
def test_prefiltered_ray_cast_equals_the_full_one(tmp_path, monkeypatch, plane, at, near, radius, limit):
    """Rays cast in rounds of growing reach give exactly what one cast against every segment gives
    (on the same outline: OCC starts a section's outline at a different point each time)."""
    part = faceted(tmp_path)
    assert same_cast(monkeypatch, part, plane, at, near, radius, limit)


def same_cast(monkeypatch, part, plane, at, near=None, radius=None, limit=None) -> bool:
    loops = [ck._loops(f, plane, 0.1) for f in ck.section_faces(part, plane, at)]
    assert loops
    fast = [ck._face_thinnest(lp, near, radius, limit, ()) for lp in loops]
    with monkeypatch.context() as m:
        m.setattr(ck, "REACH", math.inf)
        m.setattr(ck, "CHUNK", 512)  # and the chunks of the cast before rounds
        full = [ck._face_thinnest(lp, near, radius, limit, ()) for lp in loops]
    return fast == full


def test_prefilter_on_designed_shapes(monkeypatch):
    ring = Cylinder(10, 10, align=BED) - Cylinder(9.9, 12, align=BED)
    plate = Box(30, 20, 4, align=BED) - Pos(12, 0, 0) * Cylinder(1.5, 10)
    assert same_cast(monkeypatch, ring, "XY", 5)
    assert same_cast(monkeypatch, plate, "XY", 2, (12, 0), 5)
    assert same_cast(monkeypatch, plate, "XZ", 0)
    assert same_cast(monkeypatch, plate, "XZ", 0, limit=2.0)


def test_meshy():
    assert not ck.meshy(Box(10, 10, 10))
    assert not ck.meshy(Cylinder(5, 5))


REMIX = '''
from build123d import Cylinder, Pos
from b123d_print import Wall, import_model


def build(d=None):
    return import_model("ref/o.stl") - Pos(0, 8, 0) * Cylinder(1.5, 10)


def checks(d=None):
    return [Wall("part", "XY", 1.5, near=(0, 8), radius=4, label="new hole")]
'''


@pytest.fixture
def remix_ws(tmp_path, monkeypatch):
    from build123d import export_stl

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    (w / "parts" / "rx" / "ref").mkdir(parents=True)
    (w / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    shape = Box(40, 30, 3, align=BED) + Pos(0, -10, 0) * Box(40, 3, 20, align=BED)
    shape -= Pos(0, -10, 12) * Rot(90, 0, 0) * Cylinder(4, 10)  # a round-topped horizontal hole: inherited
    export_stl(shape, w / "parts" / "rx" / "ref" / "o.stl", tolerance=0.02, angular_tolerance=0.2)
    (w / "parts" / "rx" / "rx.py").write_text(REMIX, encoding="utf-8")
    return w / "parts" / "rx" / "rx.py"


def test_original_findings_are_cached(remix_ws, monkeypatch):
    calls = []
    real = OriginalFindings.get

    def counting(self, twin):
        n = len(list((remix_ws.parent / "out" / ".cache").glob("original-*.json")))
        calls.append(n)
        return real(self, twin)

    monkeypatch.setattr(OriginalFindings, "get", counting)
    ran = []
    real_run = ck.ThinFeature.run
    monkeypatch.setattr(ck.ThinFeature, "run", lambda self, *a: ran.append(self.part) or real_run(self, *a))
    settings = load_settings(remix_ws)
    first = run_checks(load(remix_ws), "", settings)
    assert ran == ["part", "original"]
    cached = sorted((remix_ws.parent / "out" / ".cache").glob("original-*.json"))
    assert len(cached) >= 4  # one per automatic check that also runs on the original
    ran.clear()
    second = run_checks(load(remix_ws), "", settings)
    assert ran == ["part"]  # the original's findings came from the cache
    assert [(f.level, f.check, f.message) for f in first] == [(f.level, f.check, f.message) for f in second]
    assert any(f.data.get("inherited") for f in second)
    # other settings: other findings, so a fresh run on the original
    from dataclasses import replace

    ran.clear()
    run_checks(load(remix_ws), "", replace(settings, min_wall=1.2))
    assert ran == ["part", "original"]


def test_fingerprint_survives_a_brep_round_trip(tmp_path):
    from build123d import Part, export_brep, import_brep

    part = faceted(tmp_path)
    export_brep(part, tmp_path / "p.brep")
    again = Part(import_brep(tmp_path / "p.brep").wrapped)
    assert shape_fingerprint(part) == shape_fingerprint(again)
    assert shape_fingerprint(part) != shape_fingerprint(part - Pos(0, 0, 0) * Cylinder(1, 20))


SLOW = '''
import time
from dataclasses import dataclass
from build123d import Box
from b123d_print import Wall


@dataclass
class Slow:
    part: str = "part"
    label: str = "spins"

    def run(self, parts, assembly, settings):
        end = time.time() + 60
        while time.time() < end:
            pass
        return []


def build(d=None):
    return Box(20, 20, 4)


def checks(d=None):
    return [Wall("part", "XY", 0, near=(0, 0), radius=15, label="first"), Slow()]
'''


def test_deadline_returns_partial_findings(tmp_path):
    script = tmp_path / "parts" / "slow" / "slow.py"
    script.parent.mkdir(parents=True)
    script.write_text(SLOW, encoding="utf-8")
    before = signal.getsignal(signal.SIGINT)
    # stopped at the deadline: the spinning check is reported as the one running (it would
    # otherwise end after 60 s with no timeout finding); no wall-clock bound needed
    found = run_checks(load(script), "", load_settings(script), deadline=time.time() + 3)
    assert signal.getsignal(signal.SIGINT) == before
    wall = [f for f in found if f.check == "wall"]
    assert len(wall) == 1 and wall[0].level == ck.OK  # finished before the limit: kept
    to = [f for f in found if f.check == "timeout"]
    assert len(to) == 1 and to[0].level == ck.FAIL
    assert to[0].data["running"] == "Slow(part, spins)"
    assert "Overhang(part)" in to[0].data["not_run"] and "ThinFeature(part)" in to[0].data["not_run"]
    # a deadline already past: nothing is built
    late = run_checks(load(script), "", load_settings(script), deadline=time.time() - 1)
    assert [f.check for f in late] == ["timeout"]


def test_deadline_through_the_worker(tmp_path, monkeypatch):
    """The sandboxed worker stops at its soft limit and returns the findings instead of being killed."""
    script = tmp_path / "parts" / "slow" / "slow.py"
    script.parent.mkdir(parents=True)
    script.write_text(SLOW, encoding="utf-8")
    out = script.parent / "out"
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")  # its soft deadline starts before the slot wait
    res = sandbox.run_job({"op": "check", "script": str(script)}, tmp_path, out, timeout=30)
    assert res["ok"], res  # stopped at the soft limit: a kill at the hard limit would be ok=False, "timed out"
    found = res["variants"]["standard"]
    assert any(f["check"] == "wall" and f["level"] == "ok" for f in found)
    assert any(f["check"] == "timeout" and f["data"]["running"] == "Slow(part, spins)" for f in found)
    assert not res["passed"]


def test_check_timeout_option(monkeypatch):
    from b123d_print import mcp_server as m

    monkeypatch.delenv("B123D_PRINT_CHECK_TIMEOUT", raising=False)
    assert m.build_parser().parse_args([]).check_timeout is None  # -> max(300, --timeout) in main()
    monkeypatch.setenv("B123D_PRINT_CHECK_TIMEOUT", "450")
    assert m.build_parser().parse_args([]).check_timeout == 450
    assert m.build_parser().parse_args(["--check-timeout", "90"]).check_timeout == 90


def test_check_jobs_get_the_check_timeout(monkeypatch, tmp_path):
    import anyio

    from b123d_print import mcp_server as m

    seen = []
    monkeypatch.setattr(m.sandbox, "run_job", lambda job, root, out, timeout: seen.append((job["op"], timeout)) or {"ok": True})
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "timeout", 120.0)
    monkeypatch.setitem(m.STATE, "check_timeout", 300.0)
    monkeypatch.setitem(m.STATE, "queue", None)
    anyio.run(m._run, {"op": "check"}, tmp_path)
    anyio.run(m._run, {"op": "render"}, tmp_path)
    assert seen == [("check", 300.0), ("render", 120.0)]


def test_soft_margin():
    assert sandbox.soft_margin(120) == 12 and sandbox.soft_margin(300) == 30
    assert sandbox.soft_margin(10) == 3 and sandbox.soft_margin(3600) == 30


def test_benchmark_script_runs(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "bench_mesh_checks.py"), "--triangles", "2000", "--repeat", "2",
                        "--keep", str(tmp_path / "bench")], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "reference mesh:" in r.stdout and "run 2:" in r.stdout
    assert "ThinFeature(original)" in r.stdout.split("run 2:")[0]
    assert "ThinFeature(original)" not in r.stdout.split("run 2:")[1]  # cached


# --- parallel checks: shares of one check run ---------------------------------------------------


def test_partition():
    from b123d_print.project import partition

    assert partition([1.0, 1.0], 3) == [0, 0]  # too little to split
    assert partition([5.0, 1.0, 4.0, 2.0], 1) == [0, 0, 0, 0]
    assert partition([5.0, 1.0, 4.0, 2.0], 2) == [0, 0, 1, 1]  # longest first: 5->0, 4->1, 2->1, 1->0
    assert partition([5.0, 4.0], 2, first=10.0) == [1, 1]  # share 0 is busy with the validity findings


def lines(found):
    return [(f.level, f.check, f.target, f.message) for f in found]


@pytest.mark.parametrize("count", [2, 3])
def test_shares_merge_to_the_sequential_result(remix_ws, monkeypatch, count):
    from b123d_print import project

    settings = load_settings(remix_ws)
    mod = load(remix_ws)
    seq = run_checks(mod, "", settings)
    monkeypatch.setattr(project, "COST_MIN_SPLIT", 0.0)  # split even this small part
    started = time.time()  # one start for the whole run, as the server passes it: an original that share 0
    # caches mid-run must not look "cached before" to a later share, or the shares partition differently
    shares = [project.check_share(mod, "", settings, (i, count), started=started) for i in range(count)]
    assert sum(len(s["assigned"]) for s in shares) == len({a for s in shares for a in s["assigned"]})  # no item twice
    assert sum(bool(s["assigned"]) for s in shares) > 1  # really split
    assert lines(project.merge_shares(shares)) == lines(seq)


def test_shares_on_an_assembly_example(monkeypatch):
    from b123d_print import project

    script = ROOT / "src" / "b123d_print" / "examples" / "esp_ir_blaster" / "esp_ir_blaster.py"
    mod = load(script)
    settings = load_settings(script)
    seq = run_checks(mod, "", settings)
    monkeypatch.setattr(project, "COST_MIN_SPLIT", 0.0)
    shares = [project.check_share(mod, "", settings, (i, 3)) for i in range(3)]
    assert lines(project.merge_shares(shares)) == lines(seq)


def test_a_failed_share_is_reported(remix_ws, monkeypatch):
    from b123d_print import project

    settings = load_settings(remix_ws)
    mod = load(remix_ws)
    monkeypatch.setattr(project, "COST_MIN_SPLIT", 0.0)
    shares = [project.check_share(mod, "", settings, (i, 2)) for i in range(2)]
    found = project.merge_shares(shares[:1], failed=["check worker 2 of 2 failed: killed"])
    err = [f for f in found if f.check == "error"]
    assert len(err) == 1 and "killed" in err[0].message and err[0].data["not_run"]
    # a share that never reported, with no failure known: still not silent
    found = project.merge_shares(shares[:1])
    assert any(f.check == "error" and "no check worker" in f.message for f in found)


def test_mesh_conversion_runs_once_for_concurrent_workers(remix_ws):
    """Workers of one check import the same mesh at once: one converts, the others wait for its cache."""
    code = ("import sys; from b123d_print.remix import import_model, IMPORTED; "
            "import_model('ref/o.stl', script=sys.argv[1]); print(IMPORTED[-1][1].cached)")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(remix_ws)], stdout=subprocess.PIPE, text=True)
             for _ in range(3)]
    outs = sorted(p.communicate(timeout=120)[0].strip() for p in procs)
    assert outs == ["False", "True", "True"], outs


SLOW_SPLIT = SLOW.replace('    label: str = "spins"\n', '    label: str = "spins"\n    cost: float = 30.0\n')


def run_server_check(monkeypatch, root, name, builds, check_timeout=300.0):
    import anyio

    from b123d_print import mcp_server as m

    monkeypatch.setitem(m.STATE, "root", root)
    monkeypatch.setitem(m.STATE, "max_builds", builds)
    monkeypatch.setitem(m.STATE, "check_timeout", check_timeout)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    monkeypatch.setattr(sandbox, "MAX_BUILDS", builds)
    monkeypatch.setattr(sandbox, "SLOT_DIR", root / ".slots")  # its own slots: not queued behind other tests
    return anyio.run(m._check, name, None)


def test_server_splits_a_check_and_merges_it(remix_ws, monkeypatch):
    root = remix_ws.parents[2]
    one = run_server_check(monkeypatch, root, "rx", 1)
    two = run_server_check(monkeypatch, root, "rx", 3)
    assert one["ok"] and two["ok"] and two["workers"] == 2  # at most CHECK_SHARES, even with 3 slots
    key = lambda r: [(f["level"], f["check"], f["target"], f["message"]) for f in r["variants"]["standard"]]  # noqa: E731
    assert key(one) == key(two)
    assert one["passed"] == two["passed"]


def test_timeout_across_workers_keeps_the_finished_shares(tmp_path, monkeypatch):
    script = tmp_path / "parts" / "slow" / "slow.py"
    script.parent.mkdir(parents=True)
    script.write_text(SLOW_SPLIT, encoding="utf-8")
    (tmp_path / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    # 45 s, not less: on a loaded CI runner starting the second worker and building the part can
    # take most of a short budget before its (fast) share finishes; the spinning check still
    # runs into the soft deadline (~40 s) either way
    res = run_server_check(monkeypatch, tmp_path, "slow", 2, check_timeout=45.0)
    assert res["ok"] and not res["passed"]
    found = res["variants"]["standard"]
    assert any(f["check"] == "wall" and f["level"] == "ok" for f in found)  # the other worker's share
    assert any(f["check"] == "overhang" for f in found)
    to = [f for f in found if f["check"] == "timeout"]
    assert len(to) == 1 and to[0]["data"]["running"] == "Slow(part, spins)"


def test_one_build_slot_runs_one_worker(monkeypatch, tmp_path):
    import anyio

    from b123d_print import mcp_server as m

    calls = []

    async def fake(name, op, **kw):
        calls.append(kw)
        return {"ok": True, "passed": True, "variants": {}}

    monkeypatch.setattr(m, "_job", fake)
    monkeypatch.setitem(m.STATE, "max_builds", 1)
    anyio.run(m._check, "x", None)
    assert calls == [{"variant": None}]
