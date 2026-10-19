"""Multi-piece projects: lazy pieces, building one piece at a time, the build cache in out/.cache/,
the per-piece timing report and the default build time limit."""

import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest

from b123d_print import project, sandbox
from b123d_print.config import load_settings
from b123d_print.project import CacheConfig, Pieces, ReadLog, load, make_pieces

ROOT = Path(__file__).resolve().parents[1]

# CALLS counts the pieces each module object built: a fresh load starts at zero
LAZY = '''\
from dataclasses import dataclass

from build123d import Align, Box, Cylinder, Pos

CALLS = []
BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    W: float = 20.0


def make(name, *size):
    CALLS.append(name)
    return Box(*size, align=BED)


def build(d):
    return {
        "a": lambda: make("a", d.W, 10, 5),
        "b": lambda: make("b", 10, d.W, 5) - Cylinder(2, 20),
        "c": lambda: make("c", 5, 5, 5),
    }


def assembly(d):
    CALLS.append("assembly")
    return [(Box(d.W, 10, 5), "#4c8bf5", "a"), (Pos(50, 0, 0) * Box(10, 10, 10), None, "stand-in")]
'''


def write_part(ws: Path, name: str = "trim", code: str = LAZY) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
    script = ws / "parts" / name / f"{name}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(code, encoding="utf-8")
    return script


def pieces(script: Path, reads: ReadLog | None = None, fresh: bool = False, key: str = "") -> Pieces:
    """A fresh load of the script (CALLS empty) built through the cache, like the worker does."""
    mod = load(script)
    cfg = CacheConfig(script.parents[2], reads if reads is not None else ReadLog(), fresh)
    return make_pieces(mod, key, project.dims(mod, key), load_settings(script), cfg)


def cache_dirs(script: Path) -> list[Path]:
    root = script.parent / "out" / ".cache"
    return sorted(p for p in root.iterdir() if p.name.startswith("build-")) if root.is_dir() else []


# --- lazy pieces and one piece at a time ---------------------------------------------------------


def test_lazy_pieces_are_built_only_when_asked_for(tmp_path):
    script = write_part(tmp_path)
    mod = load(script)
    pc = Pieces(mod, mod.Dims())
    assert pc.names() == ["a", "b", "c"] and mod.CALLS == []  # build(d) ran; no piece did
    assert list(pc.parts("b")) == ["b"] and mod.CALLS == ["b"]
    assert list(pc.parts(["c", "b"])) == ["c", "b"] and mod.CALLS == ["b", "c"]  # b once only
    with pytest.raises(KeyError, match=r"no part\(s\) \['x'\]; parts: \['a', 'b', 'c'\]"):
        pc.parts("a,x")
    assert set(project.printables(load(script), mod.Dims())) == {"a", "b", "c"}  # printables builds all


def test_plain_shapes_work_as_before(tmp_path):
    single = write_part(tmp_path, "single", "from build123d import Box\n\n\ndef build(d=None):\n    return Box(10, 10, 10)\n")
    mod = load(single)
    pc = Pieces(mod, None)
    assert list(pc.parts()) == [""] and pc.part("part").volume == pytest.approx(1000)
    assert list(pc.parts("part")) == [""]
    eager = write_part(tmp_path, "eager", "from build123d import Box\n\n\ndef build(d=None):\n"
                                          "    return {'a': Box(1, 1, 1), 'b': Box(2, 2, 2)}\n")
    pc = Pieces(load(eager), None)
    assert {n: round(p.volume) for n, p in pc.parts().items()} == {"a": 1, "b": 8}
    t = pc.timing()
    assert t["pieces"]["a"]["seconds"] is None and t["build_seconds"] >= 0  # build(d) built them all at once
    module_part = write_part(tmp_path, "modpart", "from build123d import Box\n\npart = Box(3, 3, 3)\n")
    assert round(project.printables(load(module_part), None)[""].volume) == 27


# --- the build cache ---------------------------------------------------------------------------


def test_cache_hit_and_miss(tmp_path, monkeypatch):
    script = write_part(tmp_path)
    pc = pieces(script)
    first = {n: p.volume for n, p in pc.parts().items()}
    assert pc.mod.CALLS == ["a", "b", "c"] and not any(st["cached"] for st in pc.stats.values())
    assert pc.timing()["cache"] == "on"
    pc = pieces(script)  # a new worker: everything from the cache, build(d) not even called
    again = {n: p.volume for n, p in pc.parts().items()}
    assert pc.mod.CALLS == [] and all(st["cached"] for st in pc.stats.values())
    assert again == pytest.approx(first)
    assert type(pc.part("b")).__name__ == "Part" and pc.part("b").is_valid
    # the assembly too, with its colors and labels
    asm = pieces(script).assembly()
    pc = pieces(script)
    assert [(c, lbl) for _, c, lbl in pc.assembly()] == [(c, lbl) for _, c, lbl in asm] and pc.mod.CALLS == []
    # other settings: a miss
    monkeypatch.setenv("B123D_PRINT_CLEARANCE", "0.25")
    pc = pieces(script)
    pc.parts("a")
    assert pc.mod.CALLS == ["a"]


def test_script_or_helper_change_invalidates(tmp_path):
    script = write_part(tmp_path)
    pieces(script).parts()
    old = cache_dirs(script)
    script.write_text(LAZY.replace("W: float = 20.0", "W: float = 22.25"), encoding="utf-8")  # another size: no stale .pyc
    pc = pieces(script)
    assert pc.part("a").bounding_box().size.X == pytest.approx(22.25) and pc.mod.CALLS == ["a"]
    assert cache_dirs(script) != old and len(cache_dirs(script)) == 1  # the variant's older entry removed
    pieces(script).parts()
    (script.parent / "helper.py").write_text("X = 1\n", encoding="utf-8")  # any .py in the part's folder
    pc = pieces(script)
    pc.parts("c")
    assert pc.mod.CALLS == ["c"]


def test_files_the_build_read(tmp_path):
    """A file read in the part's folder is part of the entry: changing it is a miss. A file read
    elsewhere in the workspace makes the build uncacheable."""
    script = write_part(tmp_path)
    data = script.parent / "ref" / "table.csv"
    data.parent.mkdir()
    data.write_text("1,2\n", encoding="utf-8")
    reads = ReadLog()
    reads.paths.append(str(data))
    pieces(script, reads).parts()
    pc = pieces(script, reads)
    pc.parts()
    assert pc.mod.CALLS == []
    data.write_text("1,3\n", encoding="utf-8")
    pc = pieces(script, reads)
    pc.parts("a")
    assert pc.mod.CALLS == ["a"]
    shared = tmp_path / "lib" / "dims.py"
    shared.parent.mkdir()
    shared.write_text("W = 1\n", encoding="utf-8")
    reads.paths.append(str(shared))
    pc = pieces(script, reads, fresh=True)
    pc.parts()
    assert "outside the part's folder" in pc.timing()["cache"] and "lib/dims.py" in pc.timing()["cache"]
    pc = pieces(script, reads)
    pc.parts("b")
    assert pc.mod.CALLS == ["b"]  # nothing was saved for it


def test_corrupt_entries_are_rebuilt(tmp_path):
    script = write_part(tmp_path)
    pieces(script).parts()
    (d,) = cache_dirs(script)
    breps = sorted(d.glob("piece-*.brep"))
    breps[0].write_bytes(breps[0].read_bytes()[:-200])  # truncated
    notes = sorted(d.glob("piece-*.json"))
    notes[1].write_text("{not json", encoding="utf-8")
    pc = pieces(script)
    assert {n: round(p.volume) for n, p in pc.parts().items()} == {"a": 1000, "b": 1000 - 63, "c": 125}
    assert len(pc.mod.CALLS) == 2  # the two broken pieces (the same order of names: two different ones)
    pc = pieces(script)  # rewritten: all cached again
    pc.parts()
    assert pc.mod.CALLS == []


def test_fresh_and_the_bypass(tmp_path, monkeypatch):
    script = write_part(tmp_path)
    pieces(script).parts()
    pc = pieces(script, fresh=True)
    pc.parts()
    assert pc.mod.CALLS == ["a", "b", "c"] and "fresh" in pc.timing()["cache"]
    monkeypatch.setenv("B123D_PRINT_NO_CACHE", "1")
    pc = pieces(script)
    assert pc.cache is None
    pc.parts()
    assert pc.mod.CALLS == ["a", "b", "c"] and "cache" not in pc.timing()
    monkeypatch.setenv("B123D_PRINT_NO_CACHE", "0")
    assert pieces(script).cache is not None


@pytest.mark.symlinks
def test_never_through_a_link(tmp_path):
    """An out/.cache that is a link to somewhere else is neither read nor written."""
    script = write_part(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (script.parent / "out").mkdir()
    os.symlink(elsewhere, script.parent / "out" / ".cache", target_is_directory=True)
    pc = pieces(script)
    pc.parts()
    assert not pc.cache.ok and list(elsewhere.iterdir()) == []


def test_remix_builds_are_not_cached(tmp_path):
    from b123d_print import remix

    script = write_part(tmp_path)
    mod = load(script)
    cfg = CacheConfig(tmp_path, ReadLog())
    pc = make_pieces(mod, "", mod.Dims(), load_settings(script), cfg)
    real = mod.make
    mod.make = lambda name, *size: remix.IMPORTED.append((None, None)) or real(name, *size)  # as if import_model ran
    pc.parts("a")
    remix.reset_imports()
    assert "import_model" in pc.timing()["cache"] and not list(cache_dirs(script)[0].glob("piece-*"))


# --- the timing report ---------------------------------------------------------------------------


def test_timing_hint(tmp_path, monkeypatch):
    script = write_part(tmp_path)
    mod = load(script)
    pc = Pieces(mod, mod.Dims())
    pc.parts()
    t = pc.timing()
    assert set(t["pieces"]) == {"a", "b", "c"} and t["hints"] == []
    assert t["pieces"]["b"]["faces"] == 7 and t["pieces"]["b"]["seconds"] >= 0
    monkeypatch.setattr(project, "HEAVY_FACES", 6)
    t = pc.timing()
    assert len(t["hints"]) == 1 and t["hints"][0].startswith("b: 7 faces")
    assert project.HEAVY_HINT in t["hints"][0]
    assert "fewer curve points, a spline, or build once and mirror/copy the result" in project.HEAVY_HINT
    monkeypatch.setattr(project, "HEAVY_SECONDS", -1.0)
    assert len(pc.timing()["hints"]) == 3
    lines = project.timing_lines(pc.timing())
    assert lines[0].startswith("a: 6 faces, ") and lines[-1].startswith("hint: c: 6 faces")


def test_eager_dict_gets_the_lazy_hint(tmp_path, monkeypatch):
    script = write_part(tmp_path, "eager", "from build123d import Box\n\n\ndef build(d=None):\n"
                                           "    return {'a': Box(1, 1, 1), 'b': Box(2, 2, 2)}\n")
    pc = Pieces(load(script), None)
    pc.parts()
    monkeypatch.setattr(project, "HEAVY_SECONDS", -1.0)
    assert any("return lazy pieces" in h for h in pc.timing()["hints"])


# --- through the worker, the MCP tools and the CLI -----------------------------------------------


def test_worker_reuses_the_cache_and_builds_one_piece(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    monkeypatch.delenv("B123D_PRINT_NO_CACHE", raising=False)
    ws = tmp_path / "ws"
    script = write_part(ws)
    out = script.parent / "out"
    res = sandbox.run_job({"op": "build", "script": str(script), "parts": "b"}, ws, out, 60)
    assert res["ok"], res
    v = res["variants"]["standard"]
    assert list(v["parts"]) == ["b"] and "assembly" not in v and v["timing"]["pieces"]["b"]["cached"] is False
    res = sandbox.run_job({"op": "render", "script": str(script), "parts": "a,b"}, ws, out, 60)
    assert res["ok"], res
    assert {n: st["cached"] for n, st in res["timing"]["pieces"].items()} == {"a": False, "b": True}
    res = sandbox.run_job({"op": "export", "script": str(script), "parts": "c", "formats": "stl"}, ws, out, 60)
    assert res["ok"], res
    assert [Path(f).name for f in res["variants"][0]["files"]] == ["trim_c.stl"]
    res = sandbox.run_job({"op": "check", "script": str(script)}, ws, out, 120)
    assert res["ok"] and res["passed"], res
    res = sandbox.run_job({"op": "build", "script": str(script)}, ws, out, 60)
    assert all(st["cached"] for st in res["variants"]["standard"]["timing"]["pieces"].values())
    assert res["variants"]["standard"]["assembly"] == ["a", "stand-in"]
    res = sandbox.run_job({"op": "build", "script": str(script), "fresh": True}, ws, out, 60)
    assert not any(st["cached"] for st in res["variants"]["standard"]["timing"]["pieces"].values())
    # a job whose out folder is not the part's own out/: no cache
    res = sandbox.run_job({"op": "build", "script": str(script)}, ws, tmp_path / "other", 60)
    assert "cache" not in res["variants"]["standard"]["timing"]


READS_FILES = '''\
import sys
from pathlib import Path

from build123d import Box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "lib"))  # a module shared by several part scripts
import shared_dims  # noqa: E402


def build(d=None):
    w = float((HERE / "ref" / "width.txt").read_text())
    return {"a": lambda: Box(w, shared_dims.DEPTH, 2)}
'''


def test_worker_records_what_the_build_read(tmp_path, monkeypatch):
    """Through the real worker: a file the build read in the part's folder is checked on every hit;
    a module read elsewhere in the workspace (a shared lib/) makes the build uncacheable."""
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    monkeypatch.delenv("B123D_PRINT_NO_CACHE", raising=False)
    ws = tmp_path / "ws"
    script = write_part(ws, "reader", READS_FILES)
    (script.parent / "ref").mkdir()
    (script.parent / "ref" / "width.txt").write_text("12", encoding="utf-8")
    (ws / "lib").mkdir()
    (ws / "lib" / "shared_dims.py").write_text("DEPTH = 7.0\n", encoding="utf-8")
    out = script.parent / "out"

    def build():
        res = sandbox.run_job({"op": "build", "script": str(script)}, ws, out, 60)
        assert res["ok"], res
        return res["variants"]["standard"]

    v = build()
    assert v["parts"]["a"]["x"] == 12 and v["parts"]["a"]["y"] == 7  # a shared module imports today
    assert v["timing"]["cache"] == "not cached: the build read lib/shared_dims.py, outside the part's folder"
    assert build()["timing"]["pieces"]["a"]["cached"] is False
    script.write_text(READS_FILES.replace('sys.path.insert(0, str(HERE.parents[1] / "lib"))', "")
                      .replace("import shared_dims  # noqa: E402", "").replace("shared_dims.DEPTH", "7.0"), encoding="utf-8")
    assert build()["timing"]["cache"] == "on"
    assert build()["timing"]["pieces"]["a"]["cached"] is True
    (script.parent / "ref" / "width.txt").write_text("14", encoding="utf-8")
    v = build()
    assert v["timing"]["pieces"]["a"]["cached"] is False and v["parts"]["a"]["x"] == 14


def test_tools_pass_parts_and_fresh(tmp_path, monkeypatch):
    from b123d_print import mcp_server as m

    seen = []
    monkeypatch.setattr(m.sandbox, "run_job", lambda job, root, out, timeout: seen.append(job) or {"ok": False, "error": "x"})
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "max_builds", 1)
    write_part(tmp_path)
    anyio.run(lambda: m.build_part("trim", parts="a", fresh=True))
    anyio.run(lambda: m.render_preview("trim", parts="a"))
    anyio.run(lambda: m.section("trim", "XY", 1.0, fresh=True))
    anyio.run(lambda: m.check("trim", fresh=True))
    anyio.run(lambda: m.export("trim", parts="a,b", fresh=True))
    assert [(j["op"], j.get("parts"), j.get("fresh")) for j in seen] == [
        ("build", "a", True), ("render", "a", None), ("section", None, True), ("check", None, True), ("export", "a,b", True)]


def test_cli_build_only(tmp_path, capsys):
    from b123d_print.cli import main

    write_part(tmp_path)
    assert main(["--root", str(tmp_path), "build", "trim", "--only", "b", "--formats", "stl"]) == 0
    out = capsys.readouterr().out
    assert "trim b: 10.00 x 20.00 x 5.00 mm" in out and "trim a:" not in out
    assert "  b: 7 faces, " in out
    assert sorted(f.name for f in (tmp_path / "parts" / "trim" / "out").iterdir()) == ["trim_b.stl"]
    with pytest.raises(SystemExit, match="no part"):
        main(["--root", str(tmp_path), "build", "trim", "--only", "x"])


def test_part_script_only(tmp_path):
    script = write_part(tmp_path, code=LAZY + '\n\nif __name__ == "__main__":\n    from b123d_print import run\n\n    run(__file__)\n')
    r = subprocess.run([sys.executable, str(script), "--only", "c", "--formats", "stl"], capture_output=True, text=True,
                       timeout=120, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "trim_c: 5.00 x 5.00 x 5.00 mm" in r.stdout and "checks skipped with --only" in r.stdout


# --- the time limit ----------------------------------------------------------------------------


def test_default_build_timeout(monkeypatch):
    import inspect

    from b123d_print import mcp_server as m

    assert sandbox.DEFAULT_TIMEOUT == 240.0
    assert inspect.signature(sandbox.run_job).parameters["timeout"].default == 240.0
    monkeypatch.delenv("B123D_PRINT_TIMEOUT", raising=False)
    assert m.build_parser().parse_args([]).timeout == 240.0
    monkeypatch.setenv("B123D_PRINT_TIMEOUT", "100")
    assert m.build_parser().parse_args([]).timeout == 100.0
    # the worker's soft limit stays inside the hard one, and under a client's 300 s read timeout
    assert sandbox.soft_margin(240) == 24 and 240 < 300
    compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "B123D_PRINT_TIMEOUT: ${B123D_PRINT_TIMEOUT:-240}" in compose
