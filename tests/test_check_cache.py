"""The per-piece check findings cache (#72): out/.cache/check-*.json, keyed by the piece's geometry,
the check's arguments, the settings and the code; assembly checks always run."""

from pathlib import Path

import pytest

from b123d_print import checks as ck
from b123d_print import project
from b123d_print.config import load_settings
from b123d_print.project import CacheConfig, ReadLog, load

from test_build_cache import LAZY, write_part

CHECKS = LAZY + '''

def checks(d):
    from b123d_print import ThinFeature, Wall

    return [ThinFeature("b", ignore=IGNORE), Wall("a", "XY", 2.0, near=(0, 0), radius=20),
            Wall("a", "XY", 2.0, near=(0, 0), radius=20, frame="assembly", label="placed")]


IGNORE = ()
'''


def run(script: Path, fresh: bool = False, cache: bool = True) -> list[ck.Finding]:
    """One check run as the worker does it: a fresh load, through the build cache."""
    mod = load(script)
    cfg = CacheConfig(script.parents[2], ReadLog(), fresh) if cache else None
    return project.run_checks(mod, "", load_settings(script), cache=cfg)


def entries(script: Path) -> list[Path]:
    root = script.parent / "out" / ".cache"
    return sorted(root.glob("check-*.json")) if root.is_dir() else []


@pytest.fixture
def calls(monkeypatch):
    """{check class name: [part, ...]} for every run() of a per-piece check and of Overlap."""
    seen: dict = {}
    for cls in (*project.PIECE_CHECKS, ck.Overlap):
        orig = cls.run

        def spy(self, parts, assembly, settings, _orig=orig, _name=cls.__name__):
            seen.setdefault(_name, []).append(getattr(self, "part", None))
            return _orig(self, parts, assembly, settings)

        monkeypatch.setattr(cls, "run", spy)
    return seen


def lines(found: list[ck.Finding]) -> list[str]:
    return [f.line() for f in found]


def test_hit_miss_and_assembly_checks(tmp_path, calls):
    script = write_part(tmp_path, code=CHECKS)
    cold = run(script)
    assert sorted(calls["ThinFeature"]) == ["a", "b", "c"]
    n = len(entries(script))
    assert n >= 3 * 5  # ThinFeature, Overhang, Holes, BedEdge, TipOver (and Gap) per piece, the print-frame Wall
    calls.clear()
    warm = run(script)
    assert lines(warm) == lines(cold)
    assert [f.data for f in warm] == [project.finding_dict(f)["data"] for f in cold]
    # nothing per piece ran again; the assembly checks did
    assert "ThinFeature" not in calls and "Overhang" not in calls and "Holes" not in calls
    assert calls["Overlap"] == [None] and calls["Wall"] == ["a"]  # the frame="assembly" Wall only
    assert len(entries(script)) == n


def test_one_changed_piece_is_rechecked(tmp_path, calls):
    script = write_part(tmp_path, code=CHECKS)
    run(script)
    n = len(entries(script))
    # piece c changes, a and b stay the same
    script.write_text(CHECKS.replace('make("c", 5, 5, 5)', 'make("c", 5, 5, 6.25)'), encoding="utf-8")  # another size: no stale .pyc
    calls.clear()
    found = run(script)
    assert calls["ThinFeature"] == ["c"] and calls["Overhang"] == ["c"]
    assert any(f.check == "overhang" and f.target == "c" for f in found)
    assert len(entries(script)) == n  # c's older entries were replaced, not added to


def test_check_arguments_settings_and_corruption(tmp_path, calls, monkeypatch):
    script = write_part(tmp_path, code=CHECKS)
    run(script)
    # another ThinFeature(ignore=...): that check runs again, nothing else
    script.write_text(CHECKS.replace("IGNORE = ()", "IGNORE = (((0, 0, 0), (1, 1, 1)),)"), encoding="utf-8")
    calls.clear()
    run(script)
    assert calls["ThinFeature"] == ["b"] and "Overhang" not in calls
    # a setting the checks read: every per-piece check runs again
    monkeypatch.setenv("B123D_PRINT_MIN_WALL", "1.6")
    calls.clear()
    found = run(script)
    assert sorted(calls["ThinFeature"]) == ["a", "b", "c"]
    assert any(f.check == "thin" and f.data.get("warn_below") == 1.6 for f in found)
    # a broken entry, and one whose key does not match: run again, and saved again
    a, b = entries(script)[:2]
    a.write_text("{not json", encoding="utf-8")
    b.write_text('{"key": "other", "findings": []}', encoding="utf-8")
    calls.clear()
    run(script)
    assert sum(len(v) for k, v in calls.items() if k != "Overlap") == 3  # the two broken ones + the assembly Wall
    calls.clear()
    run(script)
    assert sum(len(v) for k, v in calls.items() if k != "Overlap") == 1


def test_fresh_and_no_cache(tmp_path, calls, monkeypatch):
    script = write_part(tmp_path, code=CHECKS)
    run(script)
    calls.clear()
    run(script, fresh=True)
    assert sorted(calls["ThinFeature"]) == ["a", "b", "c"]
    monkeypatch.setenv("B123D_PRINT_NO_CACHE", "1")
    calls.clear()
    run(script)
    assert sorted(calls["ThinFeature"]) == ["a", "b", "c"]
    # in-process (the CLI's check, no worker): reads and writes nothing
    other = write_part(tmp_path / "other", code=CHECKS)
    monkeypatch.delenv("B123D_PRINT_NO_CACHE")
    run(other, cache=False)
    assert entries(other) == []


def test_shares_agree_on_cached_items(tmp_path):
    """Every share computes the same partition: an entry counts as cached only when it was saved
    before the check run began, and a replaced entry keeps its time."""
    import os
    import time

    script = write_part(tmp_path, code=CHECKS)
    run(script)
    started = time.time() + 1
    cfg = CacheConfig(script.parents[2], ReadLog())
    shares = [project.check_share(load(script), "", load_settings(script), (i, 2), started=started, cache=cfg)
              for i in range(2)]
    assert shares[0]["costs"] == shares[1]["costs"]
    assert not any(f.check == "error" for f in project.merge_shares(shares))
    old = entries(script)[0]
    t = old.stat().st_mtime
    old.write_text("{not json", encoding="utf-8")
    os.utime(old, (t, t))
    run(script)  # rewrites it, with its old time
    assert entries(script)[0].stat().st_mtime == pytest.approx(t)
