"""The build123d part libraries part scripts may import (bd_warehouse, py_gearworks): they import,
build inside the sandbox with the audit hook on, and the examples that use them build."""

from pathlib import Path

import pytest

from b123d_print import sandbox
from b123d_print.project import dims, load, printables

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "b123d_print" / "examples"

# one of everything the docs and examples use, built by the sandboxed worker
PROBE = '''
from bd_warehouse.fastener import HeatSetNut, InsertHole, SocketHeadCapScrew
from bd_warehouse.open_builds import TNut, VSlotLinearRail
from bd_warehouse.thread import IsoThread, PlasticBottleThread
import py_gearworks as gw

def build():
    gear = gw.SpurGear(number_of_teeth=12, module=1.5, height=5, profile_shift=0.29).build_part()
    return {
        "iso": IsoThread(major_diameter=8, pitch=1.25, length=6, external=True, end_finishes=("fade", "fade")),
        "bottle": PlasticBottleThread("M38SP400", external=False, manufacturing_compensation=0.2),
        "screw": SocketHeadCapScrew("M4-0.7", 10, simple=False),
        "insert_hole": InsertHole(HeatSetNut("M4-0.7-8.1", "CNCKitchen"), depth=9.1),
        "rail": VSlotLinearRail("20x20", 20),
        "tnut": TNut(),
        "gear": gear,
    }
'''


def test_libraries_import():
    import bd_warehouse.fastener
    import bd_warehouse.gear
    import bd_warehouse.open_builds
    import bd_warehouse.thread
    import py_gearworks

    assert py_gearworks.SpurGear and bd_warehouse.thread.PlasticBottleThread


def test_libraries_build_in_the_sandbox(tmp_path):
    script = tmp_path / "probe" / "probe.py"
    script.parent.mkdir()
    script.write_text(PROBE, encoding="utf-8")
    res = sandbox.run_job({"op": "build", "script": str(script)}, tmp_path, script.parent / "out", timeout=240)
    assert res["ok"], res.get("error", "") + "\n" + res.get("traceback", "") + "\n" + res.get("log", "")
    parts = res["variants"]["standard"]["parts"]
    assert set(parts) == {"iso", "bottle", "screw", "insert_hole", "rail", "tnut", "gear"}
    assert all(p["valid"] and p["volume"] > 0 for p in parts.values()), parts


@pytest.mark.parametrize("name, sizes", [
    ("jar_lid", {"part": (43.89, 43.89, 11.91)}),
    ("insert_bracket", {"part": (68.0, 20.0, 16.0)}),
    ("gear_pair", {"pinion": (21.25, 21.25, 15.0), "gear": (48.0, 47.83, 15.0)}),
    ("vslot_mount", {"part": (60.0, 36.0, 4.7)}),
])
def test_library_examples_build(name, sizes):
    mod = load(EXAMPLES / name / f"{name}.py")
    parts = {(k or "part"): p for k, p in printables(mod, dims(mod, "")).items()}
    assert set(parts) == set(sizes)
    for k, p in parts.items():
        assert p.is_valid and len(p.solids()) == 1, k
        bb = p.bounding_box()
        assert bb.min.Z == pytest.approx(0, abs=1e-3), f"{k}: not on the bed"
        assert tuple(bb.size) == pytest.approx(sizes[k], abs=0.02), k
