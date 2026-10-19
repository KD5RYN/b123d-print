"""Time build + render + export of a multi-piece part, without the build cache and with it.

    uv run python tools/bench_multi_piece.py [--points 96] [--keep DIR] [--only key]

Writes a part script shaped like a run of trim: two curved ends (a --points polygon with stacked
offsets and a tapered extrude: the dense kind of piece), their mirror images, a straight and a
key, as lazy pieces (each curved piece is built once and mirrored). Then runs the jobs the MCP
tools run (build_part, render_preview, export with 3mf,png), sandboxed like the server: first
with B123D_PRINT_NO_CACHE=1 (every call builds every piece), then with the build cache (the first
call builds and saves, the others read it back). --only also times build_part and render_preview
of one piece, cold, which builds just that piece.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = '''\
"""Benchmark: a run of trim in six pieces (made by tools/bench_multi_piece.py)."""
import functools
import math
from dataclasses import dataclass

from build123d import Align, Box, Plane, Polyline, extrude, make_face, mirror, offset


@dataclass(frozen=True)
class Dims:
    POINTS: int = {points}  # points on each curved outline: time grows with it
    R: float = 60.0  # outer radius of a curved end
    W: float = 20.0  # width of the trim
    H: float = 12.0  # height
    LIP: float = 1.5  # each stacked offset


def outline(d, r):
    arc = [(r * math.cos(a), r * math.sin(a)) for a in (i * math.pi / 2 / (d.POINTS - 1) for i in range(d.POINTS))]
    return arc + [(x * (r - d.W) / r, y * (r - d.W) / r) for x, y in reversed(arc)]


@functools.cache  # d is frozen, so hashable: each curved piece is built once per process
def curved(d, r, steps):
    f = make_face(Polyline(*outline(d, r), close=True))
    solid = extrude(f, d.H, taper=3)
    for i in range(steps):
        solid -= extrude(offset(f, -d.LIP * (i + 1)), d.H, taper=2).translate((0, 0, 2 + 2 * i))
    return solid


def build(d):
    bed = (Align.CENTER, Align.CENTER, Align.MIN)
    return {{
        "end_rear": lambda: curved(d, d.R, 3),
        "end_front": lambda: mirror(curved(d, d.R, 3), Plane.YZ),
        "drop_rear": lambda: curved(d, d.R + 15, 2),
        "drop_front": lambda: mirror(curved(d, d.R + 15, 2), Plane.YZ),
        "straight": lambda: Box(200, d.W, d.H, align=bed),
        "key": lambda: Box(12, 6, 4, align=bed),
    }}
'''

STEPS = (("build_part", "build", {}), ("render_preview", "render", {}), ("export 3mf,png", "export", {"formats": "3mf,png"}))


def timed(name: str, op: str, **kw) -> tuple[float, dict]:
    import anyio

    from b123d_print import mcp_server as m

    t0 = time.perf_counter()
    res = anyio.run(lambda: m._job(name, op, **kw))
    if not res.get("ok"):
        raise SystemExit(f"{op} failed: {res.get('error')}\n{res.get('traceback', '')}")
    return time.perf_counter() - t0, res


def run(ws: Path, label: str, no_cache: bool) -> float:
    shutil.rmtree(ws / "parts" / "trim" / "out", ignore_errors=True)
    if no_cache:
        os.environ["B123D_PRINT_NO_CACHE"] = "1"
    else:
        os.environ.pop("B123D_PRINT_NO_CACHE", None)
    total = 0.0
    print(label)
    for title, op, kw in STEPS:
        t, res = timed("trim", op, **kw)
        total += t
        timing = res["variants"]["standard"]["timing"] if op == "build" else (
            res["timing"] if op == "render" else res["variants"][0]["timing"])
        cached = sum(1 for st in timing["pieces"].values() if st.get("cached"))
        print(f"  {title:16} {t:6.1f} s  ({cached} of {len(timing['pieces'])} pieces from the cache)")
        if op == "build":
            for n, st in timing["pieces"].items():
                print(f"      {n:10} {st['faces']:5} faces  {st['seconds'] if st['seconds'] is not None else '-':>5} s")
    print(f"  {'total':16} {total:6.1f} s")
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--points", type=int, default=96)
    ap.add_argument("--keep", type=Path, help="write the workspace here and keep it")
    ap.add_argument("--only", help="also time build_part and render_preview of these pieces alone (comma-separated)")
    args = ap.parse_args()

    from b123d_print import mcp_server as m, sandbox

    ws = args.keep or Path(tempfile.mkdtemp(prefix="b123d-bench-"))
    try:
        (ws / "parts" / "trim").mkdir(parents=True, exist_ok=True)
        (ws / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
        (ws / "parts" / "trim" / "trim.py").write_text(SCRIPT.format(points=args.points), encoding="utf-8")
        m.STATE.update(root=ws, timeout=sandbox.DEFAULT_TIMEOUT, queue=None, limiter=None)
        print(f"sandbox: {sandbox.kind()}, {args.points} points per curve")
        before = run(ws, "without the build cache (B123D_PRINT_NO_CACHE=1)", True)
        after = run(ws, "with the build cache (cold: the first call builds and saves)", False)
        print(f"build + render + export: {before:.1f} s -> {after:.1f} s")
        if args.only:
            os.environ.pop("B123D_PRINT_NO_CACHE", None)
            shutil.rmtree(ws / "parts" / "trim" / "out", ignore_errors=True)
            for title, op in (("build_part", "build"), ("render_preview", "render")):
                shutil.rmtree(ws / "parts" / "trim" / "out", ignore_errors=True)
                t, _ = timed("trim", op, parts=args.only)
                print(f"{title} parts={args.only!r}, cold: {t:.1f} s")
    finally:
        os.environ.pop("B123D_PRINT_NO_CACHE", None)
        if args.keep is None:
            shutil.rmtree(ws, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
