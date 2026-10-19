"""Outline tracing on synthetic images of known shapes at a known scale."""

import json
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw

from b123d_print import trace as tr


def poly_area(p):
    p = np.asarray(p)
    return 0.5 * abs(float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))))


def scan(tmp_path, dpi=300, name="scan.png"):
    """An 80 x 50 mm plate with a 20 mm hole, black on white, saved at `dpi`."""
    ppm = dpi / 25.4
    im = Image.new("L", (int(120 * ppm), int(80 * ppm)), 255)
    d = ImageDraw.Draw(im)
    d.rectangle([20 * ppm, 10 * ppm, 100 * ppm - 1, 60 * ppm - 1], fill=0)
    d.ellipse([40 * ppm, 25 * ppm, 60 * ppm - 1, 45 * ppm - 1], fill=255)
    path = tmp_path / name
    im.save(path, dpi=(dpi, dpi))
    return path


def test_rectangle_with_a_hole_from_a_scan(tmp_path):
    res = tr.trace(scan(tmp_path))  # dpi from the file's metadata
    assert "300 dpi (from the file)" in res.scale_source
    assert res.size == pytest.approx((80, 50), abs=0.15)
    assert len(res.outline) == 4  # a rectangle simplifies to its corners
    assert len(res.holes) == 1
    hole = np.asarray(res.holes[0])
    r = np.hypot(*(hole - hole.mean(0)).T)
    assert r.mean() == pytest.approx(10, abs=0.15) and len(hole) < 40
    # the hole sits where it was drawn: center (50, 35) of the 120 x 80 sheet; outline centered on (60, 35)
    assert hole.mean(0) == pytest.approx([-10, 0], abs=0.15)
    assert res.area == pytest.approx(80 * 50 - math.pi * 100, rel=0.01)
    assert tr._area(np.asarray(res.outline)) > 0 and tr._area(hole) < 0  # outline CCW, holes CW


def test_explicit_dpi_and_tolerance(tmp_path):
    res = tr.trace(scan(tmp_path, dpi=200), tr.Scale(dpi=200), tolerance=0.05)
    assert res.size == pytest.approx((80, 50), abs=0.2)
    coarse = tr.trace(scan(tmp_path, dpi=200), tr.Scale(dpi=200), tolerance=0.5)
    assert len(coarse.holes[0]) < len(res.holes[0])


def test_circle_on_a_grid_photo(tmp_path):
    """A 40 mm disc on a 10 mm grid (gray lines on a light mat), 7 px per mm, JPEG."""
    ppm = 7.0
    im = Image.new("L", (1000, 760), 230)
    d = ImageDraw.Draw(im)
    for k in range(30):
        x = 5 + k * 10 * ppm
        d.line([x, 0, x, 760], fill=140, width=2)
        d.line([0, x, 1000, x], fill=140, width=2)
    d.ellipse([300, 200, 300 + 40 * ppm - 1, 200 + 40 * ppm - 1], fill=25)
    path = tmp_path / "grid.jpg"
    im.save(path, quality=92)
    res = tr.trace(path, tr.Scale(grid=10))
    assert res.mm_per_px == pytest.approx(1 / ppm, rel=0.005)
    assert res.size == pytest.approx((40, 40), abs=0.3)
    assert not res.holes and 12 <= len(res.outline) <= 60
    r = np.hypot(*np.asarray(res.outline).T)
    assert r.min() > 19.6 and r.max() < 20.3
    smooth = tr.trace(path, tr.Scale(grid=10), smooth=True)
    assert len(smooth.outline) < len(res.outline) and smooth.spline


def test_card_reference_and_two_points(tmp_path):
    ppm = 5.0
    im = Image.new("L", (1200, 800), 250)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([700, 300, 700 + 85.6 * ppm, 300 + 53.98 * ppm], radius=3 * ppm, fill=60)  # the card
    d.polygon([(100, 100), (100 + 60 * ppm, 100), (100, 100 + 90 * ppm)], fill=10)  # a 60 x 90 triangle
    path = tmp_path / "card.png"
    im.save(path)
    res = tr.trace(path, tr.Scale(reference="card"))
    assert res.mm_per_px == pytest.approx(1 / ppm, rel=0.01)
    assert res.size == pytest.approx((60, 90), abs=0.5)
    assert poly_area(res.outline) == pytest.approx(60 * 90 / 2, rel=0.02)
    pts = tr.trace(path, tr.Scale(points=(100, 100, 400, 100), distance=60), pick=(150, 150))
    assert pts.size == pytest.approx((60, 90), abs=0.5)
    card = tr.trace(path, tr.Scale(points=(100, 100, 400, 100), distance=60))  # the largest object: the card
    assert card.size == pytest.approx((85.6, 53.98), abs=0.5)


def test_outputs_snippet_builds(tmp_path):
    from build123d import extrude

    res = tr.write(tr.trace(scan(tmp_path)), tmp_path / "out", "scan", "scan.png")
    data = json.loads((tmp_path / "out/scan_outline.json").read_text())
    assert data["outline"] == res.outline and len(data["holes"]) == 1
    png = Image.open(tmp_path / "out/scan_trace.png")
    assert png.size[0] > 500
    ns: dict = {}
    exec((tmp_path / "out/scan_outline.py").read_text(), ns)  # the snippet a part script pastes
    part = extrude(ns["outline_face"](), 2)
    assert part.is_valid and part.volume == pytest.approx(2 * (80 * 50 - math.pi * 100), rel=0.01)
    smooth = tr.write(tr.trace(scan(tmp_path), smooth=True), tmp_path / "s", "scan")
    ns = {}
    exec((tmp_path / "s/scan_outline.py").read_text(), ns)
    part = extrude(ns["outline_face"](), 2)
    # a spline rounds the sharp corners: for organic outlines, not a rectangle
    assert part.is_valid and part.volume == pytest.approx(2 * (80 * 50 - math.pi * 100), rel=0.04)
    assert len(smooth.outline) <= 200


def test_refusals(tmp_path):
    p = tmp_path / "photo.png"
    Image.new("L", (400, 300), 255).save(p, dpi=(72, 72))
    with pytest.raises(tr.TraceError, match="no scale"):
        tr.trace(scan(tmp_path, dpi=72, name="screen.png"))  # 72 dpi is a screen default, not a scan
    with pytest.raises(tr.TraceError, match="nothing to trace"):
        tr.trace(p, tr.Scale(dpi=300))
    with pytest.raises(tr.TraceError, match="one scale source"):
        tr.trace(p, tr.Scale(dpi=300, grid=10))
    with pytest.raises(tr.TraceError, match="needs distance"):
        tr.trace(p, tr.Scale(points=(0, 0, 100, 0)))
    with pytest.raises(tr.TraceError, match="no grid"):
        tr.trace(scan(tmp_path), tr.Scale(grid=10))
    bad = tmp_path / "x.stl"
    bad.write_text("solid")
    with pytest.raises(tr.TraceError, match="reads"):
        tr.trace(bad)


def test_refs_accept_images_only_when_they_are_images(tmp_path):
    from b123d_print import refs

    data = scan(tmp_path).read_bytes()
    stored = refs.store(tmp_path, "parts", "gasket", "scan.png", data)
    assert stored.read_bytes() == data and refs.listing(tmp_path, "parts", "gasket") == ["scan.png"]
    with pytest.raises(refs.RefError, match="not a PNG"):
        refs.store(tmp_path, "parts", "gasket", "fake.png", b"<html>nope</html>")
    with pytest.raises(refs.RefError, match="not a JPG"):
        refs.store(tmp_path, "parts", "gasket", "fake.jpg", data)
