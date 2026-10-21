"""Trace the outline of a flat object from a flatbed scan or a photo on a grid, in mm.

    res = trace("ref/gasket.png", Scale(dpi=600))            # a scan (dpi read from the file if omitted)
    res = trace("ref/plate.jpg", Scale(grid=10))              # a photo on a 10 mm grid / cutting mat
    res = trace("ref/plate.jpg", Scale(reference="card"))     # a credit card (85.60 x 53.98 mm) beside it
    res = trace("ref/plate.jpg", Scale(points=(x1, y1, x2, y2), distance=100))  # two pixels 100 mm apart

Pipeline: grayscale -> Otsu threshold (the object is whichever side the image border is not) ->
an opening that removes thin grid lines and specks -> the largest object (not the reference
card) -> its sub-pixel contour (contourpy, already a matplotlib dependency) with the inner
contours as holes -> Ramer-Douglas-Peucker simplification to `tolerance` mm (dense polylines
make slow builds) -> optionally a periodic spline fit (scipy). Coordinates are mm, +Y up,
centered on the outline's bounding box.

Accuracy: about one pixel plus the scale's own error. A flatbed scan has neither lens distortion
nor perspective and is the best source; a photo is only as good as it is square-on and far away,
and the scale holds only in the plane of the grid or card. See docs/using/tracing.md.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
MAX_SIDE = 4000  # px: larger images are scaled down first (the contour is sub-pixel anyway)
MAX_PIXELS = 120_000_000  # refuse bigger images (decompression bombs)
CARD = (85.60, 53.98)  # ISO/IEC 7810 ID-1: credit and bank cards
REFERENCES = {"card": CARD, "credit_card": CARD, "id1": CARD}


class TraceError(ValueError):
    pass


@dataclass
class Scale:
    """Where the scale comes from; give one (dpi alone may come from the file's metadata)."""

    dpi: float | None = None  # a flatbed scan's resolution
    grid: float | None = None  # mm per grid cell (a cutting mat, graph paper)
    reference: str | tuple | None = None  # "card", or (long, short) mm of a rectangular object in the image
    points: tuple | None = None  # (x1, y1, x2, y2) in image pixels (origin top left, as image viewers show)
    distance: float | None = None  # mm between `points`

    def kind(self) -> str:
        given = [k for k in ("dpi", "grid", "reference", "points") if getattr(self, k) is not None]
        if len(given) > 1:
            raise TraceError(f"give one scale source, not {given}")
        if self.points is not None and not self.distance:
            raise TraceError("points needs distance (mm between the two points)")
        if self.points is not None and len(self.points) != 4:
            raise TraceError("points: x1, y1, x2, y2 (pixels)")
        return given[0] if given else "metadata"


@dataclass
class Trace:
    outline: list  # [[x, y], ...] mm, counter-clockwise, not repeating the first point
    holes: list  # [[[x, y], ...], ...] clockwise
    mm_per_px: float
    scale_source: str
    size: tuple  # (w, h) mm of the outline's bounding box
    area: float  # mm^2, holes taken off
    points_dense: int
    tolerance: float
    spline: bool
    notes: list = field(default_factory=list)
    image: str = ""
    files: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Image and scale


def load_image(path: str | Path) -> tuple[np.ndarray, dict, float]:
    """Gray image (0..1 floats), its metadata (dpi), and the factor it was scaled down by (>= 1)."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    path = Path(path)
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise TraceError(f"{path.name}: trace reads {', '.join(IMAGE_SUFFIXES)} images")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            im = Image.open(path)
            im.load()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise TraceError(f"{path.name}: over {MAX_PIXELS // 1_000_000} megapixels") from None
        except OSError as e:
            raise TraceError(f"{path.name}: not a readable image ({e})") from None
    info = {"dpi": im.info.get("dpi"), "px": im.size}
    from PIL import ImageOps

    im = ImageOps.exif_transpose(im).convert("L")
    factor = max(1.0, max(im.size) / MAX_SIDE)
    if factor > 1:
        im = im.resize((round(im.size[0] / factor), round(im.size[1] / factor)), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 255.0, info, factor


def otsu(gray: np.ndarray) -> float:
    if float(gray.max() - gray.min()) < 0.05:
        raise TraceError("nothing to trace: the image is one flat tone")
    hist, edges = np.histogram(gray, bins=256, range=(0, 1))
    p = hist.astype(float) / hist.sum()
    w = np.cumsum(p)
    mu = np.cumsum(p * (edges[:-1] + edges[1:]) / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    return float(edges[int(np.nanargmax(between)) + 1])


def foreground(gray: np.ndarray, threshold: float | None = None, invert: bool | None = None, clean: int = 1) -> np.ndarray:
    """Object pixels: the side of the threshold the image border mostly is not; then an opening
    of radius `clean` px (removes grid lines and specks thinner than 2*clean+1)."""
    from scipy import ndimage

    t = otsu(gray) if threshold is None else threshold
    dark = gray < t
    if invert is None:
        border = np.concatenate([dark[0], dark[-1], dark[:, 0], dark[:, -1]])
        invert = border.mean() > 0.5  # a dark background: the object is the light side
    mask = ~dark if invert else dark
    if clean > 0:
        yy, xx = np.mgrid[-clean:clean + 1, -clean:clean + 1]
        disk = xx * xx + yy * yy <= clean * clean
        mask = ndimage.binary_opening(mask, structure=disk)
    return mask


def grid_pitch(gray: np.ndarray, exclude: np.ndarray | None = None) -> tuple[float, float]:
    """Grid pitch in px along x and y: the period of the line profile (autocorrelation peak,
    refined over its multiples). exclude: pixels to leave out (the object)."""
    ink = 1.0 - gray
    if exclude is not None:
        ink = np.where(exclude, np.nan, ink)
    out = []
    for axis in (0, 1):  # mean over rows -> profile along x; over columns -> along y
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            prof = np.nanmean(ink, axis=axis)
        prof = np.nan_to_num(prof - np.nanmean(prof))
        n = len(prof)
        f = np.fft.rfft(prof, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        ac /= ac[0] or 1.0
        lag0 = 3
        # first peak: the highest local maximum after the autocorrelation first dips below zero
        neg = np.nonzero(ac[lag0:] < 0)[0]
        if not len(neg):
            raise TraceError("no grid found in the image (no repeating lines)")
        start = lag0 + int(neg[0])
        seg = ac[start:n // 2]
        if not len(seg):
            raise TraceError("no grid found: fewer than two grid cells across the image")
        p = start + int(np.argmax(seg))
        if ac[p] < 0.15:
            raise TraceError(f"no clear grid in the image (autocorrelation {ac[p]:.2f})")
        # refine with the furthest clear multiple k*p
        best = float(p)
        for k in range(2, max(2, (n // 2) // p) + 1):
            lo, hi = int(k * best - best / 4), int(k * best + best / 4)
            if hi >= n // 1.5 or lo <= 0:
                break
            q = lo + int(np.argmax(ac[lo:hi]))
            if 0 < q < n - 1:  # parabolic peak
                y0, y1, y2 = ac[q - 1], ac[q], ac[q + 1]
                den = y0 - 2 * y1 + y2
                qf = q + (0.5 * (y0 - y2) / den if den else 0.0)
            else:
                qf = float(q)
            if ac[q] < 0.1:
                break
            best = qf / k
        out.append(best)
    return out[0], out[1]


def min_rect(points: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    """Minimum-area rectangle of 2D points: (long side, short side, angle deg, its 4 corners)."""
    from scipy.spatial import ConvexHull

    hull = points[ConvexHull(points).vertices]
    best = None
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        ang = math.atan2(e[1], e[0])
        c, s = math.cos(-ang), math.sin(-ang)
        r = hull @ np.array([[c, s], [-s, c]])
        lo, hi = r.min(0), r.max(0)
        area = float(np.prod(hi - lo))
        if best is None or area < best[0]:
            corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]) @ np.array([[c, -s], [s, c]])
            best = (area, hi - lo, ang, corners)
    _, (w, h), ang, corners = best
    return float(max(w, h)), float(min(w, h)), math.degrees(ang), corners


# ---------------------------------------------------------------------------------------------
# Contours


def _area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    L = float(np.dot(ab, ab))
    if L == 0:
        return np.hypot(*(p - a).T)
    t = np.clip((p - a) @ ab / L, 0, 1)
    return np.hypot(*(p - (a + t[:, None] * ab)).T)


def rdp(p: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on an open polyline (keeps both ends)."""
    keep = np.zeros(len(p), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(p) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        d = _seg_dist(p[i + 1:j], p[i], p[j])
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return p[keep]


def simplify_closed(p: np.ndarray, tol: float) -> np.ndarray:
    """RDP on a closed loop: split at the two points farthest apart, simplify each half."""
    if len(p) > 1 and np.allclose(p[0], p[-1]):
        p = p[:-1]
    if len(p) < 4:
        return p
    i = 0
    j = int(np.argmax(np.hypot(*(p - p[i]).T)))
    i = int(np.argmax(np.hypot(*(p - p[j]).T)))
    i, j = min(i, j), max(i, j)
    a = rdp(p[i:j + 1], tol)
    b = rdp(np.concatenate([p[j:], p[:i + 1]]), tol)
    return np.concatenate([a[:-1], b[:-1]])


def spline_fit(p: np.ndarray, tol: float, max_points: int = 200) -> np.ndarray:
    """Through-points for a periodic spline that stays within tol of the dense loop p (sharp corners
    come out rounded: for organic outlines, not prismatic ones): smooth with
    scipy's splprep, then sample it with as few points as keep the interpolating spline within
    tol (checked against the smoothing spline)."""
    from scipy.interpolate import splev, splprep

    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    step = max(1, len(p) // 2000)
    q = p[::step]
    tck, _ = splprep([q[:, 0], q[:, 1]], s=len(q) * (tol / 3) ** 2, per=1)
    fine = np.array(splev(np.linspace(0, 1, 2000, endpoint=False), tck)).T
    n = 8
    while True:
        pts = np.array(splev(np.linspace(0, 1, n, endpoint=False), tck)).T
        t2, _ = splprep([*np.vstack([pts, pts[:1]]).T], s=0, per=1)
        back = np.array(splev(np.linspace(0, 1, 2000, endpoint=False), t2)).T
        from scipy.spatial import cKDTree

        dev = float(cKDTree(back).query(fine)[0].max())
        if dev <= tol or n >= max_points:
            return pts
        n = min(max_points, int(n * 1.5))


def contours(mask: np.ndarray, blur: float = 0.7) -> list[np.ndarray]:
    """Closed sub-pixel contours of a binary mask, (x=col, y=row) pixel coordinates."""
    import contourpy
    from scipy import ndimage

    z = np.pad(mask.astype(np.float32), 2)
    if blur:
        z = ndimage.gaussian_filter(z, blur)
    gen = contourpy.contour_generator(z=z, line_type="Separate")
    return [ln - 2 for ln in gen.lines(0.5) if len(ln) >= 4]


# ---------------------------------------------------------------------------------------------
# The trace


def trace(path: str | Path, scale: Scale | None = None, tolerance: float = 0.2, smooth: bool = False,
          threshold: float | None = None, invert: bool | None = None, clean: int | None = None,
          min_hole: float = 1.0, pick: tuple | None = None) -> Trace:
    """Trace the largest object in the image (see module doc). tolerance: mm the simplified
    outline may deviate from the traced contour. min_hole: mm^2; smaller inner contours are dust.
    threshold: 0..1 gray level (default Otsu); invert: True when the object is lighter than the
    background (default: decided from the image border); clean: opening radius px (default 1,
    or about a tenth of the grid pitch on a grid). pick: (x, y) image pixel inside the object to
    trace (default: the largest object that is not the reference)."""
    from scipy import ndimage

    scale = scale or Scale()
    kind = scale.kind()
    gray, info, factor = load_image(path)
    notes = []
    if factor > 1:
        notes.append(f"image scaled down {factor:.2f}x to {gray.shape[1]} x {gray.shape[0]} px for tracing")
    ref_marks: dict = {}

    pitch = None
    if kind == "grid":
        rough = foreground(gray, threshold, invert, clean=3)
        px, py = grid_pitch(gray, ndimage.binary_dilation(rough, iterations=3))
        pitch = (px + py) / 2
        if abs(px - py) / pitch > 0.02:
            notes.append(f"grid cells measure {px:.1f} x {py:.1f} px: {abs(px - py) / pitch:.1%} apart, so the photo is "
                         "not square-on (perspective) or the grid is not square; the scale is their mean")
        ref_marks["grid"] = (px, py)
    if clean is None:
        clean = max(1, round(pitch * 0.1)) if pitch else 1
    mask = foreground(gray, threshold, invert, clean)
    labels, n = ndimage.label(mask)
    if n == 0:
        raise TraceError("nothing to trace: no object stands out from the background (try threshold= or invert=)")
    sizes = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
    order = [int(i) + 1 for i in np.argsort(-sizes)]
    # fill each component's holes when comparing sizes: a ring is as big as its outline
    candidates = [k for k in order[:8] if sizes[k - 1] >= 0.002 * mask.size]
    if not candidates:
        candidates = order[:1]

    mmpp = None
    if kind == "reference":
        want = REFERENCES.get(str(scale.reference).lower()) if isinstance(scale.reference, str) else tuple(scale.reference)
        if not want or len(want) != 2:
            raise TraceError(f"reference: one of {sorted(REFERENCES)} or (long, short) in mm")
        want = (max(want), min(want))
        best = None
        for k in candidates:
            yx = np.argwhere(labels == k)
            if len(yx) > 200_000:
                yx = yx[:: len(yx) // 200_000 + 1]
            L, S, ang, corners = min_rect(yx[:, ::-1].astype(float))
            fill = sizes[k - 1] / (L * S) if L * S else 0
            err = abs(L / S - want[0] / want[1]) + abs(1 - fill)
            if best is None or err < best[0]:
                best = (err, k, L, S, corners)
        if best is None or len(candidates) < 2:
            raise TraceError("reference: need the reference object and the object to trace as two separate shapes")
        err, kref, L, S, corners = best
        sx, sy = want[0] / L, want[1] / S
        mmpp = (sx + sy) / 2
        if abs(sx - sy) / mmpp > 0.02:
            notes.append(f"the reference reads {L:.1f} x {S:.1f} px: its sides give scales {abs(sx - sy) / mmpp:.1%} apart "
                         "(perspective or a partly hidden reference); the scale is their mean")
        ref_marks["reference"] = corners
        candidates = [k for k in candidates if k != kref]
    elif kind == "grid":
        mmpp = scale.grid / pitch
    elif kind == "points":
        x1, y1, x2, y2 = (float(v) / factor for v in scale.points)
        dpx = math.hypot(x2 - x1, y2 - y1)
        if dpx < 10:
            raise TraceError("points: the two points are under 10 px apart")
        mmpp = scale.distance / dpx
        ref_marks["points"] = (x1, y1, x2, y2)
    else:
        dpi = scale.dpi
        if dpi is None:
            md = info.get("dpi")
            if not md or abs(float(md[0]) - float(md[1])) > 0.5 or float(md[0]) < 150:
                raise TraceError("no scale: the image has no scan resolution (dpi) in its metadata"
                                 + (f" (it says {md}, a screen default, not a scan)" if md else "")
                                 + ". Give dpi (a flatbed scan), grid (cell size in mm), reference ('card') or two points "
                                 "and their distance")
            dpi = float(md[0])
            kind = "metadata"
        mmpp = 25.4 / float(dpi) * factor
        ref_marks["dpi"] = round(float(dpi), 1)
    mmpp = float(mmpp)
    if pick is not None:
        px_, py_ = (int(round(float(v) / factor)) for v in pick)
        if not (0 <= py_ < labels.shape[0] and 0 <= px_ < labels.shape[1]) or labels[py_, px_] == 0:
            raise TraceError(f"pick {tuple(pick)}: no object at that pixel (x right, y down from the top left)")
        candidates = [int(labels[py_, px_])]
    if not candidates:
        raise TraceError("nothing to trace besides the reference object")
    obj = candidates[0]
    comp = labels == obj
    sl = ndimage.find_objects(labels)[obj - 1]
    pad = 3
    r0, c0 = max(0, sl[0].start - pad), max(0, sl[1].start - pad)
    sub = comp[r0:sl[0].stop + pad, c0:sl[1].stop + pad]
    if sl[0].start == 0 or sl[1].start == 0 or sl[0].stop >= mask.shape[0] or sl[1].stop >= mask.shape[1]:
        notes.append("the object touches the image edge: its outline there is the edge of the image, not the object")
    loops = [ln + [c0, r0] for ln in contours(sub)]
    loops.sort(key=lambda ln: -abs(_area(ln)))
    outer_px = loops[0]
    cx = (outer_px[:, 0].min() + outer_px[:, 0].max()) / 2
    cy = (outer_px[:, 1].min() + outer_px[:, 1].max()) / 2

    def to_mm(ln):
        return np.column_stack([(ln[:, 0] - cx) * mmpp, -(ln[:, 1] - cy) * mmpp])

    outer = to_mm(outer_px)
    inner = [to_mm(ln) for ln in loops[1:] if abs(_area(ln)) * mmpp * mmpp >= min_hole]
    dense = len(outer) + sum(len(h) for h in inner)
    tol = max(tolerance, 1e-3)

    def shape(ln, ccw):
        q = spline_fit(ln, tol) if smooth else simplify_closed(ln, tol)
        return q if (_area(q) > 0) == ccw else q[::-1]

    outline = shape(outer, True)
    holes_mm = [shape(h, False) for h in inner]
    if tol < mmpp:
        notes.append(f"tolerance {tol:g} mm is under one pixel ({mmpp:.3f} mm): the outline cannot be that exact")
    w = float(outer[:, 0].max() - outer[:, 0].min())
    h = float(outer[:, 1].max() - outer[:, 1].min())
    area = abs(_area(outer)) - sum(abs(_area(x)) for x in inner)
    if kind == "dpi":
        src = f"scan at {ref_marks['dpi']:g} dpi"
    elif kind == "metadata":
        src = f"scan at {ref_marks['dpi']:g} dpi (from the file)"
    elif kind == "grid":
        src = f"{scale.grid:g} mm grid, {pitch:.2f} px per cell"
    elif kind == "reference":
        src = f"reference {scale.reference if isinstance(scale.reference, str) else 'object'} ({want[0]:g} x {want[1]:g} mm)"
    else:
        src = f"two points {scale.distance:g} mm apart"
    if kind in ("grid", "reference", "points"):
        notes.append("photo scale holds only in the plane of the grid/reference and only as far as the photo is square-on; "
                     "lens distortion bends straight edges near the frame edges. Check a known dimension")
    res = Trace(outline=[[round(float(x), 3), round(float(y), 3)] for x, y in outline],
                holes=[[[round(float(x), 3), round(float(y), 3)] for x, y in hh] for hh in holes_mm],
                mm_per_px=round(mmpp, 5), scale_source=src, size=(round(w, 2), round(h, 2)), area=round(float(area), 1),
                points_dense=dense, tolerance=tol, spline=smooth, notes=notes)
    res._overlay = (gray, outer_px, [ln for ln in loops[1:] if abs(_area(ln)) * mmpp * mmpp >= min_hole], ref_marks,
                    (cx, cy, mmpp))
    return res


# ---------------------------------------------------------------------------------------------
# Output


def snippet(res: Trace, name: str = "OUTLINE") -> str:
    """Python for a part script: the points as constants and a function that makes the face."""
    def fmt(pts, indent):
        rows, line = [], indent
        for x, y in pts:
            item = f"({x:g}, {y:g}), "
            if len(line) + len(item) > 100:
                rows.append(line.rstrip())
                line = indent
            line += item
        rows.append(line.rstrip())
        return "\n".join(rows)

    holes = "".join(f"    [\n{fmt(h, '        ')}\n    ],\n" for h in res.holes)
    if res.spline:
        make = ("    def loop(pts):\n"
                "        return Face(Wire([Edge.make_spline([Vector(x, y) for x, y in pts], periodic=True)]))\n")
        imports = "from build123d import Edge, Face, Vector, Wire"
    else:
        make = "    def loop(pts):\n        return make_face(Polyline(*pts, close=True))\n"
        imports = "from build123d import Polyline, make_face"
    return (f"# traced: {res.scale_source}, {res.mm_per_px:g} mm/px, tolerance {res.tolerance:g} mm;\n"
            f"# size {res.size[0]:g} x {res.size[1]:g} mm, {len(res.outline)} points, {len(res.holes)} hole(s).\n"
            f"# Check a known dimension against the object before trusting it (photo scale is an estimate).\n"
            f"{imports}\n\n"
            f"{name} = [  # mm, +Y up, centered on the bounding box\n{fmt(res.outline, '    ')}\n]\n"
            f"{name}_HOLES = [\n{holes}]\n\n\n"
            f"def {name.lower()}_face():\n"
            f"    \"\"\"The traced outline as a face on XY, holes cut; extrude(face, amount=...) for a part.\"\"\"\n"
            f"{make}"
            f"    face = loop({name})\n"
            f"    for h in {name}_HOLES:\n"
            f"        face -= loop(h)\n"
            f"    return face\n")


def overlay(res: Trace, path: str | Path, title: str = "") -> Path:
    """The traced outline (red; holes blue) on the image, the scale reference in yellow, a mm scale bar."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gray, outer_px, holes_px, marks, (cx, cy, mmpp) = res._overlay
    hgt, wid = gray.shape
    fig_w = 10
    fig, ax = plt.subplots(figsize=(fig_w, fig_w * hgt / wid + 0.6), dpi=110)
    ax.imshow(gray, cmap="gray", vmin=0, vmax=1)

    def back(pts_mm):  # simplified mm points -> image pixels
        p = np.asarray(pts_mm, float)
        return np.column_stack([p[:, 0] / mmpp + cx, -p[:, 1] / mmpp + cy])

    ax.plot(*np.vstack([outer_px, outer_px[:1]]).T, color="#ff3030", lw=0.8, alpha=0.6)
    simp = back(res.outline)
    ax.plot(*np.vstack([simp, simp[:1]]).T, color="#ff3030", lw=1.6, marker="o", ms=2.5)
    for hp, hs in zip(holes_px, res.holes):
        ax.plot(*np.vstack([hp, hp[:1]]).T, color="#3080ff", lw=0.8, alpha=0.6)
        q = back(hs)
        ax.plot(*np.vstack([q, q[:1]]).T, color="#3080ff", lw=1.6, marker="o", ms=2.5)
    if "reference" in marks:
        c = marks["reference"]
        ax.plot(*np.vstack([c, c[:1]]).T, color="#ffd000", lw=2)
    if "points" in marks:
        x1, y1, x2, y2 = marks["points"]
        ax.plot([x1, x2], [y1, y2], color="#ffd000", lw=2, marker="+", ms=14)
    if "grid" in marks:
        px, py = marks["grid"]
        x0, y0 = wid * 0.04, hgt * 0.04
        ax.plot([x0, x0 + px], [y0, y0], color="#ffd000", lw=3)
        ax.plot([x0, x0], [y0, y0 + py], color="#ffd000", lw=3)
    bar = 10 ** math.floor(math.log10(max(wid * mmpp / 4, 1e-6)))
    bx, by = wid * 0.05, hgt * 0.95
    ax.plot([bx, bx + bar / mmpp], [by, by], color="#00c060", lw=4, solid_capstyle="butt")
    ax.text(bx, by - hgt * 0.015, f"{bar:g} mm", color="#00c060", fontsize=10, fontweight="bold")
    ax.set_title((title + "\n" if title else "") + f"{res.size[0]:g} x {res.size[1]:g} mm, {len(res.outline)} points, "
                 f"{len(res.holes)} hole(s); {res.scale_source}", fontsize=9)
    ax.set_axis_off()
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path)
    plt.close(fig)
    return path


def write(res: Trace, out_dir: str | Path, stem: str, title: str = "", sort: bool = False) -> Trace:
    """<stem>_outline.json, <stem>_outline.py and <stem>_trace.png in out_dir; sort=True (a part's
    out/ folder): the outline files in docs/, the picture in images/ (outdir.py)."""
    from . import outdir

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js, py, png = (outdir.path(out, n) if sort else out / n for n in (f"{stem}_outline.json", f"{stem}_outline.py",
                                                                       f"{stem}_trace.png"))
    res.image = str(overlay(res, png, title))
    py.write_text(snippet(res), encoding="utf-8")
    res.files = {"json": str(js), "py": str(py), "png": str(png)}
    d = res.as_dict()
    js.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return res


def text(res: Trace) -> str:
    lines = [f"traced {res.size[0]:g} x {res.size[1]:g} mm, area {res.area:g} mm^2; {res.scale_source}, "
             f"{res.mm_per_px:g} mm/px (about +-{res.mm_per_px:.2g} mm from the pixels alone)",
             f"outline {len(res.outline)} points" + (" (spline through-points)" if res.spline else "")
             + f", {len(res.holes)} hole(s) {[len(h) for h in res.holes] if res.holes else ''}; "
             f"{res.points_dense} points before simplifying to {res.tolerance:g} mm"]
    lines += [f"note: {n}" for n in res.notes]
    return "\n".join(lines)
