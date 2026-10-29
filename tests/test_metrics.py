"""Design metrics on shapes with known answers (sanity tests; the estimates are rough by design)."""

import math
import sys
from types import SimpleNamespace

import pytest
from build123d import Align, Axis, Box, Cylinder, Location, Sphere, chamfer, fillet

from b123d_print import metrics as M
from b123d_print.config import Settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)
P = M.Params()


def box():
    return Box(60, 40, 20, align=BED)


def cup(drain: bool = False):
    c = Box(40, 40, 30, align=BED) - Box(36, 36, 30, align=BED).moved(Location((0, 0, 2)))
    return c - Cylinder(1.5, 10).moved(Location((10, 10, 0))) if drain else c


def tee():  # a 60 x 30 x 5 top on a 10 x 30 post: two 25 x 30 ledges 30 mm up
    return Box(10, 30, 30, align=BED) + Box(60, 30, 5, align=BED).moved(Location((0, 0, 30)))


# --- M2 filament, M3 time, M5 supports -------------------------------------------------------


def test_mass_is_the_shell_formula_on_a_cube():
    c = Box(20, 20, 20, align=BED)
    shell = 400 * 5 * 0.2 + 400 * 3 * 0.2 + 1600 * 2 * 1.1 * 0.4  # top, bottom, 4 sides
    assert M.shell_volume(M.Mesh(c), c.volume, P) == pytest.approx(shell)
    m = M.mass(c, M.Mesh(c), P)
    assert m["extruded_mm3"] == pytest.approx(shell + 0.15 * (8000 - shell), abs=1)
    assert m["grams"] == pytest.approx(m["extruded_mm3"] * 1.24 / 1000, abs=0.05)
    assert "20 %" in m["accuracy"]


def test_mass_grows_with_infill_and_thin_parts_are_all_shell():
    c = Box(40, 40, 40, align=BED)
    lo = M.mass(c, M.Mesh(c), M.Params(infill=0.15))["grams"]
    hi = M.mass(c, M.Mesh(c), M.Params(infill=0.5))["grams"]
    assert hi > lo
    plate = Box(50, 50, 0.6, align=BED)
    assert M.mass(plate, M.Mesh(plate), P)["shell_share"] == 1.0


def test_cost_only_with_a_price():
    c = box()
    assert "cost" not in M.mass(c, M.Mesh(c), P)
    m = M.mass(c, M.Mesh(c), M.Params(price=25.0))
    assert m["cost"] == pytest.approx(m["grams"] * 25 / 1000, abs=0.01)


def test_time_is_the_stated_rule():
    c = box()
    t = M.print_time(c, 10_000, P)
    assert t["layers"] == 100
    assert t["minutes"] == pytest.approx((10_000 / M.FLOW + 100 * M.LAYER_S) / 60, abs=0.05)
    assert M.print_time(c, 10_000, M.Params(flow=20.0))["minutes"] < t["minutes"]
    assert "rough" in t["accuracy"]


def test_supports_column_of_a_tee():
    t = tee()
    s = M.supports(t, M.Mesh(t), P)
    assert s["column_mm3"] == pytest.approx(2 * 25 * 30 * 30, rel=0.01)
    assert s["volume_mm3"] == pytest.approx(M.SUPPORT_FILL * s["column_mm3"], abs=1)
    assert M.supports(box(), M.Mesh(box()), P)["grams"] == 0.0


def test_short_bridge_needs_no_support():
    arch = Box(40, 20, 20, align=BED) - Box(8, 20, 10, align=BED)  # an 8 mm tunnel
    assert M.supports(arch, M.Mesh(arch), P)["grams"] == 0.0


# --- M6 stepping, M7 edges, M8 symmetry, M10 seams, M11 water ------------------------------


def test_stepping_band():
    assert M.stepping(M.Mesh(box()), P)["band_up_cm2"] == 0.0
    dome = Sphere(20) & Box(60, 60, 30, align=BED)
    st = M.stepping(M.Mesh(dome), P)
    # up-facing hemisphere: area with polar angle 1-30 deg is (cos 1 - cos 30) of it; the mesh's
    # 0.1 rad facets quantize the tilt near 30 deg, hence 10 %
    assert st["band_up_cm2"] == pytest.approx(2 * math.pi * 400 * (math.cos(math.radians(1)) - math.cos(math.radians(30))) / 100, rel=0.1)
    assert M.stepping(M.Mesh(dome), P, ["+X"])["band_up_cm2"] < st["band_up_cm2"]


def test_edges_sharp_box():
    e = M.edges(box())
    assert e["sharp_share"] == 1.0 and e["radii"] == [] and e["chamfer_sizes"] == []
    assert e["outside_mm"] == pytest.approx(280)  # top 200 + 4 verticals; bed edges apart
    assert e["bed_edges"]["sharp_mm"] == pytest.approx(200)


def test_edges_fillets_and_chamfers():
    v = M.edges(fillet(box().edges().filter_by(Axis.Z), 3))
    assert v["radii"] == [3.0]
    assert v["fillet_share"] * v["outside_mm"] == pytest.approx(80, abs=0.5)  # 4 x 20 mm
    a = M.edges(fillet(box().edges(), 2))
    assert a["fillet_share"] == 1.0 and a["sharp_share"] == 0.0 and a["radii"] == [2.0]
    assert a["bed_edges"]["filleted_mm"] > 0
    c = M.edges(chamfer(box().edges().group_by(Axis.Z)[-1], 1))
    assert c["chamfer_sizes"] == [1.0] and c["chamfer_share"] > 0.7


def test_edges_hole_is_not_a_radius():
    p = fillet(box().edges().filter_by(Axis.Z), 5) - Cylinder(3, 40).moved(Location((10, 5, 0)))
    e = M.edges(p)
    assert e["radii"] == [5.0] and e["radius_families"] == {"edge_break": [], "styling": [5.0]}


def test_symmetry():
    assert M.symmetry(box())["best"] == 1.0
    off = box() - Cylinder(3, 40).moved(Location((10, 5, 0)))
    s = M.symmetry(off)
    assert 0.95 < s["best"] < 1.0
    ell = Box(60, 30, 4, align=(Align.MIN, Align.MIN, Align.MIN)) + Box(4, 30, 40, align=(Align.MIN, Align.MIN, Align.MIN))
    assert M.symmetry(ell)["x"] < 0.9 and M.symmetry(ell)["y"] == 1.0


def test_seam_corners():
    assert M.seam_corners(M._sections(box(), 0.2))["share"] == 1.0
    assert M.seam_corners(M._sections(Cylinder(15, 20, align=BED), 0.2))["share"] == 0.0
    grooved = Cylinder(15, 20, align=BED) - Box(1, 1, 30, align=BED).moved(Location((0, -15, 0)))
    assert M.seam_corners(M._sections(grooved, 0.2))["share"] == 1.0


def test_water_traps():
    w = M.water_traps(cup())
    assert w["cm3"] == pytest.approx(36 * 36 * 28 / 1000, rel=0.05)
    assert M.water_traps(cup(drain=True))["cm3"] == 0
    assert M.water_traps(cup(), up="-Z")["cm3"] == 0  # upside down
    assert M.water_traps(cup(), up="+X")["cm3"] == 0  # on its side
    closed = Box(30, 30, 30, align=BED) - Box(20, 20, 20, align=BED).moved(Location((0, 0, 5)))
    assert M.water_traps(closed)["cm3"] == 0  # a sealed void holds no rain


# --- M12 inside corners, M13 walls, M14 hole edge distance, M15 slenderness ------------------

MIN = (Align.MIN, Align.MIN, Align.MIN)


def ell(r: float = 0.0, t: float = 5.0):  # an L: 40 x 20 base and a 40 tall upright, both t thick
    p = Box(40, 20, t, align=MIN) + Box(t, 20, 40, align=MIN)
    if r:
        p = fillet(p.edges().filter_by(Axis.Y).filter_by_position(Axis.X, t - 0.01, t + 0.01)
                   .filter_by_position(Axis.Z, t - 0.01, t + 0.01), r)
    return p


def test_inside_corner_is_not_an_outside_edge():
    concave = [row for row in M._edge_info(ell()) if row[3] > 20 and not row[4]]
    assert len(concave) == 1 and concave[0][0].length == pytest.approx(20)
    assert M.edges(ell())["outside_mm"] == pytest.approx(300)  # the 13 convex edges off the bed; not the inside one


def test_inside_corners():
    sharp = M.inside_corners(ell())
    assert sharp["inside_mm"] == pytest.approx(20) and sharp["sharp_share"] == 1.0 and sharp["worst_ratio"] is None
    assert sharp["sharp"][0]["at"] == [5.0, 10.0, 5.0]
    f = M.inside_corners(ell(r=3))
    assert f["fillet_share"] == 1.0 and f["radii"] == [3.0]
    assert f["worst_ratio"]["wall"] == pytest.approx(5, abs=0.01) and f["worst_ratio"]["ratio"] == pytest.approx(0.6)
    assert M.inside_corners(box())["inside_mm"] == 0.0
    # a counterbored hole and a teardrop are holes, not inside corners
    holed = box() - Cylinder(2, 40) - Cylinder(4, 5).moved(Location((0, 0, 17.5)))
    assert M.inside_corners(holed)["inside_mm"] == 0.0


def test_walls():
    thin = Box(40, 20, 1.0, align=BED)
    three = M.Params(wall_lines=3)
    w = M.walls(thin, three)
    assert w["thinnest_mm"] == pytest.approx(1.0, abs=0.05) and w["lines"] == pytest.approx(2.2, abs=0.15)
    assert "thinnest_mm" not in M.walls(box(), three) and M.walls(box(), three)["below_mm"] == pytest.approx(1.35)
    assert M.walls(thin, P)["skipped"]  # only for a style with min_wall_lines: the sections take seconds


def test_hole_edge_distance():
    plate = Box(40, 20, 4, align=MIN) - Cylinder(1.7, 10).moved(Location((5, 10, 0)))  # M3, 5 mm from the end
    plate -= Cylinder(1.7, 10).moved(Location((25, 10, 0)))  # 10 mm from the sides
    he = M.hole_edges(plate, P)
    assert [(h["size"], h["edge_mm"]) for h in he["holes"]] == [("M3", pytest.approx(5, abs=0.02)), ("M3", pytest.approx(10, abs=0.02))]
    assert he["worst"]["ratio"] == pytest.approx(5 / 3.4, abs=0.01)
    boss = Cylinder(4, 10, align=BED) - Cylinder(2, 10, align=BED)  # an insert boss: BP-T4's Wall check, not an edge
    assert M.hole_edges(boss, P)["holes"] == []
    big = Box(40, 20, 4, align=MIN) - Cylinder(6, 10).moved(Location((20, 10, 0)))  # not a screw hole
    assert M.hole_edges(big, P)["holes"] == []


def test_slenderness():
    post = Cylinder(3, 30, align=BED) + Box(30, 30, 3, align=BED)  # 27 mm of 6 mm post above a plate: 1.13 x 27 / 6
    s = M.slenderness(post, M._sections(post, 0.2))
    assert s["run_mm"] == pytest.approx(27, abs=0.5) and s["value"] == pytest.approx(27 / 3 / math.sqrt(math.pi), rel=0.03)
    assert M.slenderness(box(), M._sections(box(), 0.2))["value"] < 1
    dome = Sphere(10) & Box(30, 30, 10, align=BED)  # a tapering tip: a short run on a small section
    assert M.slenderness(dome, M._sections(dome, 0.2))["value"] < 2


# --- M9 economy, styles and findings -----------------------------------------------------------


def test_fastener_classes():
    assert M.fastener_class(3.4) == ("M3", "clearance")
    assert M.fastener_class(4.0) == ("M3", "insert")
    assert M.fastener_class(2.6) == ("M3", "pilot")
    assert M.fastener_class(12.0) is None
    plate = Box(60, 40, 4, align=BED)
    for x in (-20, 20):
        plate -= Cylinder(1.7, 10).moved(Location((x, 0, 0)))
    plate -= Cylinder(2.25, 10).moved(Location((0, 10, 0)))
    eco = M.economy({"part": plate})
    assert eco["screw_sizes"] == {"M3": {"count": 2, "roles": ["clearance"]}, "M4": {"count": 1, "roles": ["clearance"]}}


def test_directions():
    assert M.parse_dirs(["+Y", "z"]) == ["+Y", "+Z"] and M.parse_dirs("+X,-Y") == ["+X", "-Y"]
    with pytest.raises(ValueError):
        M.parse_dirs("up")


def test_style_resolution():
    d = SimpleNamespace(STYLE="rugged")
    assert M.resolve_style(None, d, Settings(style="modern")) == ("rugged", "script")
    assert M.resolve_style(None, SimpleNamespace(STYLE=""), Settings(style="modern")) == ("modern", "settings")
    assert M.resolve_style(None, None, Settings()) == ("functional", "default")
    assert M.resolve_style(SimpleNamespace(STYLE="Industrial"), None, Settings()) == ("functional", "script")


def _rules(res, level=None):
    return [f["rule"] for f in res["findings"] if level is None or f["level"] == level]


def test_findings_fire_at_the_thresholds():
    s = Settings()
    assert "DS-G1" in _rules(M.design_metrics(None, None, {"": box()}, s, style="modern"), "suggest")
    r = M.design_metrics(None, None, {"": cup()}, s, style="rugged")
    assert {"DS-R1", "DS-R3", "DS-G8"} <= set(_rules(r, "suggest"))  # sharp edges: DS-G8 (with DS-R7's radius)
    assert "DS-R3" not in _rules(M.design_metrics(None, None, {"": cup(drain=True)}, s, style="rugged"))
    tower = Box(10, 10, 80, align=BED)
    assert "DS-C7" in _rules(M.design_metrics(None, None, {"": tower}, s, style="least_cost"), "suggest")
    assert "DS-C4" in _rules(M.design_metrics(None, None, {"": tee()}, s, style="least_cost"), "suggest")
    soft = M.design_metrics(None, None, {"": fillet(box().edges(), 2)}, s, style="soft")
    assert "DS-G8" not in _rules(soft)
    sharp_l = M.design_metrics(None, None, {"": ell()}, s, style="structural")
    assert _rules(sharp_l) == ["DS-T3"] and "inside corner length is sharp" in sharp_l["findings"][0]["message"]
    small_r = M.design_metrics(None, None, {"": ell(r=1)}, s, style="structural")
    assert _rules(small_r, "suggest") == ["DS-T3"] and "r/wall 0.20" in small_r["findings"][0]["message"]
    assert _rules(M.design_metrics(None, None, {"": ell(r=3)}, s, style="structural")) == []
    thin = M.design_metrics(None, None, {"": Box(40, 20, 1.0, align=BED)}, s, style="structural")
    assert _rules(thin, "suggest") == ["DS-T4"]
    pin = Cylinder(3, 40, align=BED) + Box(30, 30, 3, align=BED)
    assert "DS-T1" in _rules(M.design_metrics(None, None, {"": pin}, s, style="structural"), "note")
    assert "DS-T1" not in _rules(M.design_metrics(None, None, {"": pin}, s, style="functional"))


def test_edges_preference():
    s = Settings()
    filleted = fillet(box().edges().filter_by(Axis.Z), 3)
    mod = SimpleNamespace(EDGES="chamfer")
    assert "DS-G1" in _rules(M.design_metrics(mod, None, {"": filleted}, s), "suggest")
    with pytest.raises(ValueError, match="EDGES"):
        M.design_metrics(SimpleNamespace(EDGES="round"), None, {"": box()}, s)


def test_text_report_says_the_estimates_are_rough():
    t = M.text(M.design_metrics(None, None, {"": box()}, Settings()))
    assert "roughly ±20 %" in t and "rough estimate" in t and "style: functional (default; built-in style functional)" in t


def test_symmetry_on_a_grid():
    from build123d import Box, Pos

    assert M.symmetry(Box(10, 20, 30)) == {"x": 1.0, "y": 1.0, "z": 1.0, "best": 1.0}
    ell = Box(30, 10, 10) + Pos(-10, 10, 0) * Box(10, 10, 10)  # an L: symmetric about XZ? no
    s = M.symmetry(ell)
    assert s["z"] == 1.0 and s["x"] < 0.9 and s["best"] == max(s["x"], s["y"])


@pytest.mark.skipif(sys.platform == "win32", reason="measured with resource.getrusage")
def test_design_metrics_memory_on_a_lofted_part():
    """#150: symmetry's three OCC booleans took 7 s and ~1 GB more on this lofted banana; on the
    server that crashed the job under its memory cap. Measured in a fresh process."""
    import subprocess
    import sys
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "banana_half.py"
    code = "\n".join([
        "import importlib.util, resource, sys, time",
        f"spec = importlib.util.spec_from_file_location('b', {str(fixture)!r})",
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)",
        "part = m.build(m.Dims())",
        "from b123d_print import metrics",
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
        "t = time.time(); metrics.symmetry(part); dt = time.time() - t",
        "after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
        "scale = 1 if sys.platform == 'darwin' else 1024",
        "print((after - before) * scale / 2**20, dt)",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    grew_mb, secs = map(float, r.stdout.split()[-2:])
    assert grew_mb < 200 and secs < 5, (grew_mb, secs)


@pytest.mark.skipif(sys.platform == "win32", reason="measured with resource.getrusage")
def test_design_metrics_stays_light_on_the_banana_example():
    """#151: the bundled organic example (lofted, swept, blended, cut flat) through every metric,
    in a fresh process: well under the server's memory cap. The time bound is a hang guard."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(M.__file__).parent / "examples" / "banana" / "banana.py"
    code = "\n".join([
        "import resource, sys, time",
        "from b123d_print.project import load, dims, printables",
        "from b123d_print.config import Settings",
        "from b123d_print import metrics",
        f"m = load({str(script)!r}); d = dims(m, ''); part = printables(m, d)['']",
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
        "t = time.time(); metrics.design_metrics(m, d, {'': part}, Settings()); dt = time.time() - t",
        "after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss",
        "scale = 1 if sys.platform == 'darwin' else 1024",
        "print((after - before) * scale / 2**20, dt)",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    grew_mb, secs = map(float, r.stdout.split()[-2:])
    assert grew_mb < 300 and secs < 60, (grew_mb, secs)
