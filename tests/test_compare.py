"""compare: loaders and metrics on known shapes, with the numbers they must give."""

import json
import math
import zipfile

import numpy as np
import pytest
from build123d import Box, Cylinder, Pos, Rot, export_step, export_stl

from b123d_print.cli import main
from b123d_print.compare import Criteria, Mesh, Surface, compare, load_mesh, mesh_from_shape
from b123d_print.render import export_3mf

# 40 x 30 x 10 block, a 6 mm hole off center and a corner pocket: no symmetry, so a wrong pose shows
HOLE_R, POCKET = 3.0, (12.0, 12.0, 6.0)


def block(hole=True):
    p = Box(40, 30, 10) - Pos(-15, -10, 3) * Box(*POCKET)
    return p - Pos(8, 5, 0) * Cylinder(HOLE_R, 20) if hole else p


@pytest.fixture(scope="module")
def ref():
    return mesh_from_shape(block())


def test_identical(ref):
    r = compare(ref, ref)
    assert r.passed and r.score == 100.0
    assert r.metrics["hausdorff_mm"] < 1e-6 and r.metrics["mean_mm"] < 1e-6
    assert r.metrics["volume_rel"] == 0 and r.metrics["bbox_diff_mm"] == [0, 0, 0]
    assert not r.alignment["mirrored"]


@pytest.mark.parametrize("move", [Pos(5, -3, 2), Rot(90, 0, 0) * Pos(1, 2, 3), Rot(0, 90, 180)])
def test_shifted_and_axis_rotated(ref, move):
    """Moved or turned onto another face (another print orientation): the axis search finds it."""
    r = compare(ref, mesh_from_shape(move * block()))
    assert r.passed and r.score > 99.9
    assert r.metrics["hausdorff_mm"] < 1e-3
    assert r.metrics["bbox_diff_mm"] == pytest.approx([0, 0, 0], abs=1e-3)


def test_rotated_off_axis(ref):
    """30 degrees about Z: principal axes + ICP (tessellation differs, so not exactly 0)."""
    r = compare(ref, mesh_from_shape(Rot(0, 0, 30) * block()))
    assert r.passed and r.alignment["method"] == "principal" and r.alignment["icp"]
    assert r.metrics["mean_mm"] < 0.02 and r.metrics["hausdorff_mm"] < 0.1
    assert r.score > 99.5


def test_scaled_one_percent(ref):
    c = Mesh(ref.verts * 1.01, ref.tris)
    r = compare(ref, c)
    assert r.metrics["volume_rel"] == pytest.approx(1.01 ** 3 - 1, abs=1e-4)  # +3.03 %
    assert r.metrics["area_rel"] == pytest.approx(1.01 ** 2 - 1, abs=1e-4)  # +2.01 %
    assert r.metrics["bbox_diff_mm"] == pytest.approx([0.4, 0.3, 0.1], abs=1e-3)
    # half the diagonal (25.5 mm) x 1 % at the far corners, ~0.09 mm on average
    assert 0.3 < r.metrics["hausdorff_mm"] < 0.45 and 0.05 < r.metrics["mean_mm"] < 0.15
    assert r.failures() == ["volume_rel"]  # just over the default 3 %
    assert 94 < r.score < 98


def test_missing_hole(ref):
    r = compare(ref, mesh_from_shape(block(hole=False)))
    hole_v = math.pi * HOLE_R ** 2 * 10
    assert r.metrics["volume_rel"] == pytest.approx(hole_v / (ref.volume), rel=0.02)  # +2.5 %
    # the middle of the bore is half the 10 mm thickness from the nearest candidate face
    assert r.metrics["hausdorff_ref_to_cand_mm"] == pytest.approx(5.0, abs=0.1)
    assert r.metrics["recall"] < 0.97  # the bore wall (~4.5 % of the surface) is not matched
    assert r.failures() == ["hausdorff_mm"]
    assert r.score < 85


def test_mirror_image(ref):
    m = mesh_from_shape(block().mirror())
    r = compare(ref, m)
    assert r.alignment["mirrored"] and r.metrics["hausdorff_mm"] < 1e-3
    assert r.failures() == ["mirrored"]
    assert compare(ref, m, criteria=Criteria(allow_mirrored=True)).passed


def test_symmetric_part_prefers_a_rotation():
    box = mesh_from_shape(Box(20, 10, 5))
    r = compare(box, mesh_from_shape(Rot(0, 0, 90) * Box(20, 10, 5)))
    assert r.passed and not r.alignment["mirrored"]


def test_file_formats_agree(tmp_path, ref):
    part = block()
    export_stl(part, tmp_path / "p.stl", tolerance=0.005, angular_tolerance=0.1)
    export_step(part, tmp_path / "p.step")
    export_3mf(part, tmp_path / "p.3mf")
    vol = part.volume
    for name in ("p.stl", "p.step", "p.3mf"):
        m = load_mesh(tmp_path / name)
        assert m.volume == pytest.approx(vol, rel=2e-3), name
        assert list(m.size) == pytest.approx([40, 30, 10], abs=1e-3), name
        assert m.watertight(), name
    assert compare(tmp_path / "p.stl", tmp_path / "p.3mf").passed


def test_ascii_stl(tmp_path):
    tri = "facet normal 0 0 1\n outer loop\n  vertex 0 0 0\n  vertex 10 0 0\n  vertex 0 5 0\n endloop\nendfacet\n"
    (tmp_path / "a.stl").write_text(f"solid t\n{tri}endsolid t\n", encoding="ascii")
    m = load_mesh(tmp_path / "a.stl")
    assert m.area == pytest.approx(25.0) and list(m.size) == [10, 5, 0]


def test_3mf_units_and_transforms(tmp_path):
    """A 1 cm cube in centimeters, placed by a build-item transform, comes out 10 mm and moved."""
    verts = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    tris = [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    model = (f'<?xml version="1.0"?><model unit="centimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>'
             f'<object id="2" type="model"><components><component objectid="1" transform="1 0 0 0 1 0 0 0 1 2 0 0"/></components></object>'
             f'</resources><build><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 3"/></build></model>')
    with zipfile.ZipFile(tmp_path / "c.3mf", "w") as z:
        z.writestr("3D/3dmodel.model", model)
    m = load_mesh(tmp_path / "c.3mf")
    assert list(m.size) == pytest.approx([10, 10, 10])
    assert list(m.bbox[0]) == pytest.approx([20, 0, 30])
    assert m.volume == pytest.approx(1000) and m.watertight()


def test_surface_distance_is_exact():
    """Points 1 mm off a box face, and off a corner, against the exact geometry."""
    s = Surface(mesh_from_shape(Box(10, 10, 10)))
    d, near = s.closest(np.array([[0, 0, 6.0], [1, 2, -7.0], [6, 6, 6]]))
    assert d == pytest.approx([1, 2, math.sqrt(3)])
    assert near[2] == pytest.approx([5, 5, 5])


def test_criteria_from_pairs():
    c = Criteria.from_pairs(["hausdorff_mm=2", "allow_mirrored=yes"])
    assert c.hausdorff_mm == 2 and c.allow_mirrored and c.volume_rel == Criteria().volume_rel
    with pytest.raises(ValueError):
        Criteria.from_pairs(["nope=1"])


def test_cli(tmp_path, capsys):
    export_stl(block(), tmp_path / "a.stl")
    export_stl(block(hole=False), tmp_path / "b.stl")
    assert main(["compare", str(tmp_path / "a.stl"), str(tmp_path / "a.stl")]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["compare", str(tmp_path / "a.stl"), str(tmp_path / "b.stl"), "--json", "--image", str(tmp_path / "d.png")]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is False and out["checks"]["hausdorff_mm"]["ok"] is False
    assert (tmp_path / "d.png").stat().st_size > 10_000
    assert main(["compare", str(tmp_path / "a.stl"), str(tmp_path / "b.stl"), "--threshold", "hausdorff_mm=6"]) == 0
