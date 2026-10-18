"""Time `check` on a mesh-imported part the size of a downloaded model (~10k triangles).

    uv run python tools/bench_mesh_checks.py [--triangles 10000] [--keep DIR] [--repeat 2]

Generates a cable-holder-like part (a filleted base plate with C-shaped clips, slots and screw
holes), exports it as a faceted STL (made here: no third-party model), writes a remix script that
imports it with import_model, cuts a hole and declares two Wall checks around it, and runs every
check the way `b123d-print check` does, printing the time per check. The second run shows what
the caches save (the import conversion and the original's findings).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = '''\
"""Benchmark remix: a generated cable holder (CC0, made by tools/bench_mesh_checks.py)."""
from dataclasses import dataclass

from build123d import Cylinder, Pos

from b123d_print import Wall, import_model


@dataclass(frozen=True)
class Dims:
    HOLE_D: float = 4.0  # a new screw hole in the base plate


def build(d):
    base = import_model("ref/holder.stl")
    return base - Pos(0, -14, 0) * Cylinder(d.HOLE_D / 2, 20)


def checks(d):
    return [
        Wall("part", "XY", 1.5, near=(0, -14), radius=6, label="new hole"),
        Wall("part", "XZ", 8.0, near=(-42, 11), radius=12, label="clip ring"),  # through the faceted clips
    ]
'''


def holder(clips: int = 4, seg: float = 0.0):
    """The generated original: plate, filleted edges, C clips with a slot, two countersunk holes."""
    from build123d import Axis, Box, Cylinder, Pos, Rot, fillet

    plate = Pos(0, 0, 1.5) * Box(110, 40, 3)
    plate = fillet(plate.edges().filter_by(Axis.Z), 6)
    part = plate
    for i in range(clips):
        x = -42 + i * 28
        ring = Pos(x, 8, 11) * Rot(90, 0, 0) * (Cylinder(9, 14) - Cylinder(6.5, 16))
        part += ring
        part -= Pos(x, 8, 20) * Box(7, 16, 6)  # the slot the cable snaps through
    for x in (-48, 48):
        part -= Pos(x, -12, 0) * Cylinder(2.2, 10)
    return part


def make_ref(path: Path, triangles: int) -> int:
    from build123d import export_stl

    from b123d_print.compare import load_mesh

    part = holder()
    tol, ang = 0.05, 0.2
    for _ in range(12):  # tighten until the mesh is about as fine as asked
        export_stl(part, path, tolerance=tol, angular_tolerance=ang)
        n = len(load_mesh(path).tris)
        if n >= triangles * 0.9:
            break
        tol, ang = tol * 0.7, ang * 0.7
    return n


def run(ws: Path, repeat: int) -> list[dict]:
    from b123d_print import checks as ck
    from b123d_print.config import load_settings
    from b123d_print.project import load, run_checks

    script = ws / "parts" / "bench" / "bench.py"
    mod = load(script)
    settings = load_settings(script)
    times = []
    orig_run = {}
    for cls in (ck.Wall, ck.ThinFeature, ck.Overhang, ck.Holes, ck.BedEdge, ck.Gap, ck.Fit):
        orig_run[cls] = cls.run

        def timed(self, *a, _f=cls.run, **k):
            t0 = time.perf_counter()
            try:
                return _f(self, *a, **k)
            finally:
                key = f"{type(self).__name__}({getattr(self, 'part', '')!s}{', ' + self.label if getattr(self, 'label', '') else ''})"
                cur[key] = cur.get(key, 0.0) + time.perf_counter() - t0

        cls.run = timed
    try:
        for i in range(repeat):
            cur: dict = {}
            t0 = time.perf_counter()
            findings = run_checks(mod, "", settings)
            total = time.perf_counter() - t0
            times.append({"total": total, "per_check": dict(cur), "findings": findings})
    finally:
        for cls, f in orig_run.items():
            cls.run = f
    return times


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--triangles", type=int, default=10000)
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--keep", type=Path, help="write the workspace here and keep it")
    args = ap.parse_args()
    ws = args.keep or Path(tempfile.mkdtemp(prefix="b123d-bench-"))
    try:
        part_dir = ws / "parts" / "bench"
        (part_dir / "ref").mkdir(parents=True, exist_ok=True)
        (ws / "b123d-print.toml").write_text('parts_dir = "parts"\n', encoding="utf-8")
        shutil.rmtree(part_dir / "out", ignore_errors=True)  # cold caches
        n = make_ref(part_dir / "ref" / "holder.stl", args.triangles)
        (part_dir / "bench.py").write_text(SCRIPT, encoding="utf-8")
        print(f"reference mesh: {n} triangles")
        for i, r in enumerate(run(ws, args.repeat)):
            print(f"run {i + 1}: {r['total']:.1f} s")
            for k, v in sorted(r["per_check"].items(), key=lambda kv: -kv[1]):
                print(f"  {v:7.2f} s  {k}")
            for f in r["findings"]:
                if f.check in ("import", "wall", "thin"):
                    print("   " + f.line()[:150])
    finally:
        if args.keep is None:
            shutil.rmtree(ws, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
