"""Compare a candidate part with a reference: load STL / 3MF / STEP, align, measure, score.

    from b123d_print.compare import compare
    r = compare("reference.stl", "parts/bracket/out/bracket.3mf")
    print(r.score, r.passed, r.metrics["hausdorff_mm"])

Alignment: the candidate may be modeled in another orientation (print orientation, other axes).
Each candidate pose is a rotation about the bounding-box center followed by matching the
bounding-box centers. Poses tried: the 24 axis rotations (48 with mirrors) in the candidate's own
frame, the same 24/48 between the principal axes of both parts, then the best few are refined with
ICP (rigid, no scaling). Distances are exact point-to-surface (to the nearest triangle), from
area-weighted samples of each surface; units are mm (STL is assumed to be mm, 3MF carries units).

Score (0-100): 100 * (0.4 F + 0.2 v + 0.2 b + 0.2 p), where F is the F-score at `tol_mm` (harmonic
mean of the share of each surface within tol_mm of the other), v = 1 - |volume diff| / 25 %,
b = 1 - largest per-axis size diff / 25 %, p = 1 - p99 distance / (10 tol_mm) (each clamped to
0..1; p99 = the larger 99th percentile of the two directions, so a missing hole or boss costs
points even when it is a small share of the surface). Pass/fail uses the `Criteria` thresholds,
each reported on its own.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree  # scipy comes with build123d

MESH_SUFFIXES = (".stl", ".3mf", ".step", ".stp")
UNITS_3MF = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
NS_3MF = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
NS_PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
MAX_FILE_BYTES = 200_000_000

W_FSCORE, W_VOLUME, W_BBOX, W_P99 = 0.4, 0.2, 0.2, 0.2


# ---------------------------------------------------------------------------------------------
# Meshes


@dataclass
class Mesh:
    """Triangle mesh: verts (N, 3) float mm, tris (M, 3) int indices. Also accepted by render()."""

    verts: np.ndarray
    tris: np.ndarray
    source: str = ""

    def __post_init__(self):
        self.verts = np.asarray(self.verts, dtype=np.float64).reshape(-1, 3)
        self.tris = np.asarray(self.tris, dtype=np.int64).reshape(-1, 3)
        if len(self.tris):
            t = self.triangles
            keep = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) > 1e-12
            self.tris = self.tris[keep]
        if not len(self.tris):
            raise ValueError(f"empty mesh{' in ' + self.source if self.source else ''}")

    @property
    def triangles(self) -> np.ndarray:
        return self.verts[self.tris]

    @property
    def face_areas(self) -> np.ndarray:
        t = self.triangles
        return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)

    @property
    def area(self) -> float:
        return float(self.face_areas.sum())

    @property
    def volume(self) -> float:
        """Enclosed volume (signed tetrahedra; meaningful for a closed mesh). abs() so a mesh with
        inward normals still gives a positive number."""
        t = self.triangles
        return abs(float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()) / 6.0)

    @property
    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        v = self.verts[np.unique(self.tris)]
        return v.min(0), v.max(0)

    @property
    def size(self) -> np.ndarray:
        lo, hi = self.bbox
        return hi - lo

    @property
    def center(self) -> np.ndarray:
        lo, hi = self.bbox
        return (lo + hi) / 2

    def watertight(self) -> bool:
        """Every edge shared by exactly two triangles (after welding coincident vertices)."""
        _, inv = np.unique(np.round(self.verts, 5), axis=0, return_inverse=True)
        t = inv.reshape(-1)[self.tris]
        e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
        _, counts = np.unique(e, axis=0, return_counts=True)
        return bool(np.all(counts == 2))

    def transformed(self, m: np.ndarray) -> Mesh:
        """Apply a 4x4 transform (points as column vectors)."""
        return Mesh(self.verts @ m[:3, :3].T + m[:3, 3], self.tris, self.source)

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """n points uniformly distributed over the surface."""
        a = self.face_areas
        idx = rng.choice(len(a), size=n, p=a / a.sum())
        t = self.triangles[idx]
        r1, r2 = rng.random(n), rng.random(n)
        s = np.sqrt(r1)
        return t[:, 0] * (1 - s)[:, None] + t[:, 1] * (s * (1 - r2))[:, None] + t[:, 2] * (s * r2)[:, None]

    def summary(self) -> dict:
        return {"size": _r(self.size), "volume": round(self.volume, 2), "area": round(self.area, 2),
                "triangles": int(len(self.tris)), "watertight": self.watertight()}


def merge(meshes: list[Mesh]) -> Mesh:
    verts, tris, n = [], [], 0
    for m in meshes:
        verts.append(m.verts)
        tris.append(m.tris + n)
        n += len(m.verts)
    return Mesh(np.concatenate(verts), np.concatenate(tris), ", ".join(m.source for m in meshes))


def load_mesh(path: str | Path, tolerance: float = 0.01) -> Mesh:
    """Read STL (binary or ASCII, assumed mm), 3MF (all build items, units converted to mm) or
    STEP (tessellated at `tolerance` mm)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path}: larger than {MAX_FILE_BYTES // 1_000_000} MB")
    suffix = path.suffix.lower()
    if suffix == ".stl":
        return _load_stl(path)
    if suffix == ".3mf":
        return _load_3mf(path)
    if suffix in (".step", ".stp"):
        from build123d import import_step

        return mesh_from_shape(import_step(path), tolerance, str(path))
    raise ValueError(f"{path}: unsupported format (use {', '.join(MESH_SUFFIXES)})")


def mesh_from_shape(shape, tolerance: float = 0.01, source: str = "") -> Mesh:
    """Tessellate a build123d shape."""
    verts, tris = shape.tessellate(tolerance, 0.1)
    return Mesh(np.array([[v.X, v.Y, v.Z] for v in verts]), np.array(tris), source)


def _load_stl(path: Path) -> Mesh:
    raw = path.read_bytes()
    if len(raw) >= 84:
        n = int(np.frombuffer(raw, dtype="<u4", count=1, offset=80)[0])
        if len(raw) == 84 + 50 * n:
            rec = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            v = np.frombuffer(raw, dtype=rec, count=n, offset=84)["v"].astype(np.float64).reshape(-1, 3)
            return Mesh(v, np.arange(len(v)).reshape(-1, 3), str(path))
    text = raw.decode("ascii", errors="replace")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums or len(nums) % 3:
        raise ValueError(f"{path}: not a valid STL")
    v = np.array(nums, dtype=np.float64)
    return Mesh(v, np.arange(len(v)).reshape(-1, 3), str(path))


def _matrix_3mf(s: str | None) -> np.ndarray:
    """3MF transform 'm00 m01 m02 m10 ... m32' (row vectors) -> 4x4 for column vectors."""
    m = np.eye(4)
    if s:
        a = np.array(s.split(), dtype=np.float64).reshape(4, 3)
        m[:3, :3] = a[:3].T
        m[:3, 3] = a[3]
    return m


def _load_3mf(path: Path) -> Mesh:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        root_model = "3D/3dmodel.model"
        if "_rels/.rels" in names:
            for rel in ET.fromstring(z.read("_rels/.rels")):
                if rel.get("Type", "").endswith("/3dmodel"):
                    root_model = rel.get("Target", root_model).lstrip("/")
        models: dict[str, ET.Element] = {}

        def model(name: str) -> ET.Element:
            name = name.lstrip("/")
            if name not in models:
                if name not in names:
                    raise ValueError(f"{path}: missing {name}")
                models[name] = ET.fromstring(z.read(name))
            return models[name]

        root = model(root_model)
        scale = UNITS_3MF.get(root.get("unit", "millimeter"), 1.0)
        pieces: list[Mesh] = []

        def emit(mname: str, oid: str, m: np.ndarray, depth: int = 0) -> None:
            if depth > 16:
                raise ValueError(f"{path}: components nested too deep")
            obj = model(mname).find(f"{NS_3MF}resources/{NS_3MF}object[@id='{oid}']")
            if obj is None:
                raise ValueError(f"{path}: no object {oid} in {mname}")
            mesh = obj.find(f"{NS_3MF}mesh")
            if mesh is not None:
                v = np.array([(e.get("x"), e.get("y"), e.get("z")) for e in mesh.iter(f"{NS_3MF}vertex")], dtype=np.float64)
                t = np.array([(e.get("v1"), e.get("v2"), e.get("v3")) for e in mesh.iter(f"{NS_3MF}triangle")], dtype=np.int64)
                if len(t):
                    pieces.append(Mesh(v @ m[:3, :3].T + m[:3, 3], t, str(path)))
            comps = obj.find(f"{NS_3MF}components")
            for c in comps if comps is not None else []:
                emit(c.get(f"{NS_PROD}path") or mname, c.get("objectid"), m @ _matrix_3mf(c.get("transform")), depth + 1)

        for item in root.iter(f"{NS_3MF}item"):
            emit(item.get(f"{NS_PROD}path") or root_model, item.get("objectid"), _matrix_3mf(item.get("transform")))
    if not pieces:
        raise ValueError(f"{path}: no meshes in the 3MF build")
    out = merge(pieces) if len(pieces) > 1 else pieces[0]
    out.verts *= scale
    out.source = str(path)
    return out


def as_mesh(x) -> Mesh:
    if isinstance(x, Mesh):
        return x
    if isinstance(x, (str, Path)):
        return load_mesh(x)
    return mesh_from_shape(x)


# ---------------------------------------------------------------------------------------------
# Distances


def closest_points_on_triangles(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Closest point to p on triangle (a, b, c), row by row (Ericson, Real-Time Collision Detection 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    out = np.empty_like(p)
    done = np.zeros(len(p), bool)

    def put(mask, value):
        nonlocal done
        m = mask & ~done
        out[m] = value[m] if value.ndim == 2 else value
        done |= m

    with np.errstate(divide="ignore", invalid="ignore"):
        put((d1 <= 0) & (d2 <= 0), a)
        put((d3 >= 0) & (d4 <= d3), b)
        put((d6 >= 0) & (d5 <= d6), c)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + (d1 / (d1 - d3))[:, None] * ab)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + (d2 / (d2 - d6))[:, None] * ac)
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + ((d4 - d3) / ((d4 - d3) + (d5 - d6)))[:, None] * (c - b))
        denom = va + vb + vc
        put(np.ones(len(p), bool), a + (vb / denom)[:, None] * ab + (vc / denom)[:, None] * ac)
    return out


def _bary_grid(n: int) -> np.ndarray:
    """Barycentric weights (m, 3) of a triangular grid with n divisions per edge."""
    i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
    keep = i + j <= n
    i, j = i[keep], j[keep]
    return np.stack([n - i - j, i, j], axis=1) / n


class Surface:
    """Exact nearest-point queries against a mesh surface.

    Every triangle is covered by grid points no farther apart than `spacing`, so any point of a
    triangle lies within `cover` of one of that triangle's own grid points. A k-d tree over the
    grid points gives candidate triangles; the answer is certain once the next grid point is
    farther than (best distance + cover). Points that are not certain (off the surface, e.g. at
    a missing feature) are asked again with every grid point in that radius."""

    def __init__(self, mesh: Mesh, spacing: float | None = None):
        self.tri = mesh.triangles
        diag = float(np.linalg.norm(mesh.size))
        h = spacing or max(diag / 80.0, 0.25)
        longest = np.max(np.linalg.norm(self.tri - np.roll(self.tri, 1, axis=1), axis=2), axis=1)
        divs = np.maximum(1, np.ceil(longest / h)).astype(int)
        pts, owner = [], []
        for n in np.unique(divs):
            ids = np.flatnonzero(divs == n)
            w = _bary_grid(int(n))
            pts.append(np.einsum("mk,tkc->tmc", w, self.tri[ids]).reshape(-1, 3))
            owner.append(np.repeat(ids, len(w)))
        self.pts, self.owner = np.concatenate(pts), np.concatenate(owner)
        self.cover = h / np.sqrt(3) * 1.001  # a grid cell (edge <= h) is within h/sqrt(3) of a corner
        self.tree = cKDTree(self.pts)

    def _exact(self, p: np.ndarray, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Distances / closest points from p (n, 3) to the triangles idx (n, k)."""
        n, k = idx.shape
        t = self.tri[idx.reshape(-1)]
        pp = np.repeat(p, k, axis=0)
        q = closest_points_on_triangles(pp, t[:, 0], t[:, 1], t[:, 2])
        d = np.linalg.norm(q - pp, axis=1).reshape(n, k)
        best = d.argmin(axis=1)
        return d[np.arange(n), best], q.reshape(n, k, 3)[np.arange(n), best]

    def closest(self, pts: np.ndarray, exact: bool = True, k: int = 16, chunk: int = 10_000) -> tuple[np.ndarray, np.ndarray]:
        """(distances (n,), closest points (n, 3)). exact=False skips the second pass (off-surface
        points may then come out up to ~`cover` too far): enough for the pose search and ICP."""
        pts = np.asarray(pts, dtype=np.float64)
        k = min(k, len(self.pts))
        dist = np.empty(len(pts))
        near = np.empty_like(pts)
        unsure = []
        for s in range(0, len(pts), chunk):
            p = pts[s:s + chunk]
            cd, idx = self.tree.query(p, k=k)
            cd, idx = cd.reshape(len(p), -1), idx.reshape(len(p), -1)
            dist[s:s + chunk], near[s:s + chunk] = self._exact(p, self.owner[idx])
            if exact and k < len(self.pts):
                unsure.append(s + np.flatnonzero(cd[:, -1] < dist[s:s + chunk] + self.cover))
        for i in np.concatenate(unsure) if unsure else []:
            idx = np.unique(self.owner[self.tree.query_ball_point(pts[i], dist[i] + self.cover)])
            if len(idx):
                d, q = self._exact(pts[i:i + 1], idx[None, :])
                if d[0] < dist[i]:
                    dist[i], near[i] = d[0], q[0]
        return dist, near


# ---------------------------------------------------------------------------------------------
# Alignment


def axis_rotations(mirror: bool) -> list[np.ndarray]:
    """The 24 rotations that map axes onto axes (+ the 24 mirror images if mirror)."""
    out = []
    for perm in ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)):
        for signs in np.ndindex(2, 2, 2):
            m = np.zeros((3, 3))
            m[range(3), perm] = [(-1) ** s for s in signs]
            if np.linalg.det(m) > 0 or mirror:
                out.append(m)
    return out


def principal_axes(pts: np.ndarray) -> np.ndarray:
    """Columns = principal axes of a point cloud, largest spread first (a right-handed frame)."""
    w, v = np.linalg.eigh(np.cov((pts - pts.mean(0)).T))
    v = v[:, np.argsort(w)[::-1]]
    if np.linalg.det(v) < 0:
        v[:, 2] *= -1
    return v


def _pose(rot: np.ndarray, cand: Mesh, ref_center: np.ndarray) -> np.ndarray:
    """4x4: rotate the candidate about the origin, then put its bbox center on ref_center."""
    m = np.eye(4)
    m[:3, :3] = rot
    lo, hi = (cand.verts @ rot.T).min(0), (cand.verts @ rot.T).max(0)
    m[:3, 3] = ref_center - (lo + hi) / 2
    return m


def _kabsch(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Rigid 4x4 (no reflection) minimizing |R src + t - dst|."""
    cs, cd = src.mean(0), dst.mean(0)
    u, _, vt = np.linalg.svd((src - cs).T @ (dst - cd))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1, 1, d]) @ u.T
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = cd - r @ cs
    return m


def _sym_mean(ref_s: Surface, ref_pts: np.ndarray, cand_s: Surface, cand_pts: np.ndarray, m: np.ndarray) -> float:
    """Symmetric mean surface distance with the candidate posed by the rigid m (the reference
    points are moved into the candidate's frame instead, so the candidate index is built once)."""
    inv = np.linalg.inv(m)
    d1 = cand_s.closest(ref_pts @ inv[:3, :3].T + inv[:3, 3], exact=False)[0].mean()
    d2 = ref_s.closest(cand_pts @ m[:3, :3].T + m[:3, 3], exact=False)[0].mean()
    return float(d1 + d2) / 2


def align(ref: Mesh, cand: Mesh, mirror: bool = True, icp: bool = True, n: int = 1500, seed: int = 0) -> tuple[np.ndarray, dict]:
    """Best 4x4 placing `cand` onto `ref`, and how it was found."""
    rng = np.random.default_rng(seed)
    ref_pts, cand_pts = ref.sample(n, rng), cand.sample(n, rng)
    ref_s, cand_s = Surface(ref), Surface(cand)
    rots = axis_rotations(mirror)
    pr, pc = principal_axes(ref.sample(4000, rng)), principal_axes(cand.sample(4000, rng))
    poses = [("axes", r) for r in rots] + [("principal", pr @ r @ pc.T) for r in rots]
    # cheap prefilter on the bounding-box size, then the surface distance for the closest third
    ranked = sorted(poses, key=lambda p: float(np.abs(_size(cand, p[1]) - ref.size).max()))
    scored = []
    for how, r in ranked[: max(16, len(ranked) // 3)]:
        m = _pose(r, cand, ref.center)
        scored.append((_sym_mean(ref_s, ref_pts, cand_s, cand_pts, m), how, m))
    scored.sort(key=lambda s: s[0])

    def refine(group):  # ICP from the best 3 poses of one handedness
        best = None
        for d0, how, m in group[:3]:
            d, m2, used = d0, m, False
            if icp:
                m_icp, d_icp = _icp(ref_s, ref_pts, cand_s, cand_pts, m)
                if d_icp < d0:
                    d, m2, used = d_icp, m_icp, True
            if best is None or d < best[0]:
                best = (d, m2, {"method": how, "search_mean_mm": round(float(d0), 4), "icp": used})
        return best

    proper = refine([s for s in scored if np.linalg.det(s[2][:3, :3]) > 0])
    mirrored = refine([s for s in scored if np.linalg.det(s[2][:3, :3]) < 0])
    # a symmetric part matches its mirror image as well: a mirror wins only when clearly better
    pick = proper
    if mirrored and (proper is None or mirrored[0] < 0.95 * proper[0] - 0.005):
        pick = mirrored
    d, m, info = pick
    info["mirrored"] = bool(np.linalg.det(m[:3, :3]) < 0)
    info["mean_mm"] = round(float(d), 4)
    return m, info


def _size(cand: Mesh, r: np.ndarray) -> np.ndarray:
    v = cand.verts @ r.T
    return v.max(0) - v.min(0)


def _icp(ref_s: Surface, ref_pts: np.ndarray, cand_s: Surface, cand_pts: np.ndarray, m: np.ndarray, iters: int = 60) -> tuple[np.ndarray, float]:
    """Point-to-surface ICP from pose m; keeps the handedness of m. Returns (pose, sym. mean)."""
    mirror = np.diag([1.0, 1.0, np.sign(np.linalg.det(m[:3, :3]))])
    base = np.eye(4)
    base[:3, :3] = mirror
    pts = cand_pts @ mirror.T  # ICP below is rotation-only; a mirror is applied first
    cur = m @ base  # cur maps mirrored points
    prev = np.inf
    for _ in range(iters):
        moved = pts @ cur[:3, :3].T + cur[:3, 3]
        d, near = ref_s.closest(moved, exact=False)
        keep = d <= np.percentile(d, 90) + 1e-9  # ignore the worst matches (missing features)
        cur = _kabsch(moved[keep], near[keep]) @ cur
        if abs(prev - d.mean()) < 1e-7:
            break
        prev = d.mean()
    final = cur @ base
    return final, _sym_mean(ref_s, ref_pts, cand_s, cand_pts, final)


# ---------------------------------------------------------------------------------------------
# Comparison


@dataclass(frozen=True)
class Criteria:
    """Pass/fail thresholds (all must hold) and the F-score tolerance. Override any field:
    Criteria(hausdorff_mm=2.0), or `--threshold hausdorff_mm=2` on the command line."""

    bbox_mm: float = 0.5  # largest per-axis bounding-box size difference
    volume_rel: float = 0.03  # |candidate - reference| / reference volume
    area_rel: float = 0.05  # same for surface area
    mean_mm: float = 0.2  # symmetric mean surface distance
    hausdorff_mm: float = 1.0  # largest surface distance either way
    fscore_min: float = 0.95  # F-score at tol_mm
    tol_mm: float = 0.5  # distance that counts as "matching" for the F-score
    score_min: float = 0.0  # overall score (0-100); 0 = not used
    allow_mirrored: bool = False  # a mirror image of a part with handedness is a different part

    @classmethod
    def from_pairs(cls, pairs: list[str] | None, base: Criteria | None = None) -> Criteria:
        """['hausdorff_mm=2', ...] -> Criteria."""
        known = {f.name for f in fields(cls)}
        kw = {}
        for s in pairs or []:
            k, _, v = s.partition("=")
            if k.strip() not in known or not v:
                raise ValueError(f"bad threshold {s!r}; use name=value with name in {sorted(known)}")
            kw[k.strip()] = v.strip().lower() in ("1", "true", "yes") if k.strip() == "allow_mirrored" else float(v)
        return cls(**{**asdict(base or cls()), **kw})


@dataclass
class Comparison:
    reference: dict
    candidate: dict
    metrics: dict
    checks: dict  # name -> {"value", "limit", "ok"}
    score: float
    passed: bool
    alignment: dict
    transform: list = field(default_factory=list)  # 4x4 applied to the candidate

    def as_dict(self) -> dict:
        return asdict(self)

    def failures(self) -> list[str]:
        return [k for k, c in self.checks.items() if not c["ok"]]

    def text(self) -> str:
        m = self.metrics
        lines = [
            f"reference: {_fmt3(self.reference['size'])} mm, volume {self.reference['volume']:.1f} mm^3, area {self.reference['area']:.1f} mm^2",
            f"candidate: {_fmt3(self.candidate['size'])} mm (aligned: {_fmt3(m['aligned_size'])}), volume {self.candidate['volume']:.1f} mm^3, area {self.candidate['area']:.1f} mm^2",
            f"alignment: {self.alignment['method']}{' + ICP' if self.alignment['icp'] else ''}"
            f"{', MIRRORED' if self.alignment['mirrored'] else ''}",
            f"bbox diff {_fmt3(m['bbox_diff_mm'])} mm; volume {m['volume_rel']:+.2%}; area {m['area_rel']:+.2%}",
            f"surface distance: mean {m['mean_mm']:.3f} mm, rms {m['rms_mm']:.3f}, p99 {m['p99_mm']:.3f}, "
            f"Hausdorff {m['hausdorff_mm']:.3f} mm (ref->cand {m['hausdorff_ref_to_cand_mm']:.3f}, cand->ref {m['hausdorff_cand_to_ref_mm']:.3f})",
            f"F-score @ {m['tol_mm']:g} mm: {m['fscore']:.3f} (precision {m['precision']:.3f}, recall {m['recall']:.3f})",
        ]
        for k, c in self.checks.items():
            lines.append(f"  [{'ok' if c['ok'] else 'FAIL':4}] {k}: {c['value']:.4g} (limit {c['limit']:g})")
        lines.append(f"score {self.score:.1f} / 100 -> {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _r(a, n=3) -> list[float]:
    return [round(float(x), n) for x in a]


def _fmt3(a) -> str:
    return " x ".join(f"{x:.2f}" for x in a)


def compare(reference, candidate, *, criteria: Criteria | None = None, samples: int = 20_000,
            mirror: bool = True, icp: bool = True, seed: int = 0) -> Comparison:
    """Compare two parts (paths to STL/3MF/STEP, Mesh, or build123d shapes). See the module doc."""
    c = criteria or Criteria()
    ref, cand = as_mesh(reference), as_mesh(candidate)
    m, info = align(ref, cand, mirror=mirror, icp=icp, seed=seed)
    moved = cand.transformed(m)
    rng = np.random.default_rng(seed + 1)
    rp, cp = ref.sample(samples, rng), moved.sample(samples, rng)
    d_rc = Surface(moved).closest(rp)[0]  # reference surface -> candidate
    d_cr = Surface(ref).closest(cp)[0]
    both = np.concatenate([d_rc, d_cr])
    recall, precision = float((d_rc <= c.tol_mm).mean()), float((d_cr <= c.tol_mm).mean())
    fscore = 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)
    vol_rel = (moved.volume - ref.volume) / ref.volume
    area_rel = (moved.area - ref.area) / ref.area
    bbox_diff = _aligned_size(cand, m) - ref.size
    metrics = {
        "aligned_size": _r(_aligned_size(cand, m)),
        "bbox_diff_mm": _r(bbox_diff),
        "volume_rel": round(float(vol_rel), 5),
        "area_rel": round(float(area_rel), 5),
        "mean_mm": round(float((d_rc.mean() + d_cr.mean()) / 2), 4),
        "rms_mm": round(float(np.sqrt((both ** 2).mean())), 4),
        "p95_mm": round(float(np.percentile(both, 95)), 4),
        "p99_mm": round(float(max(np.percentile(d_rc, 99), np.percentile(d_cr, 99))), 4),
        "hausdorff_mm": round(float(max(d_rc.max(), d_cr.max())), 4),
        "hausdorff_ref_to_cand_mm": round(float(d_rc.max()), 4),
        "hausdorff_cand_to_ref_mm": round(float(d_cr.max()), 4),
        "tol_mm": c.tol_mm,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fscore": round(fscore, 4),
        "samples": samples,
    }
    rel_bbox = float(np.max(np.abs(bbox_diff) / np.maximum(ref.size, 1e-9)))
    score = 100 * (W_FSCORE * fscore + W_VOLUME * _clamp01(1 - abs(vol_rel) / 0.25) + W_BBOX * _clamp01(1 - rel_bbox / 0.25)
                   + W_P99 * _clamp01(1 - metrics["p99_mm"] / (10 * c.tol_mm)))
    score = round(float(score), 2)
    checks = {
        "bbox_mm": {"value": float(np.max(np.abs(bbox_diff))), "limit": c.bbox_mm},
        "volume_rel": {"value": abs(float(vol_rel)), "limit": c.volume_rel},
        "area_rel": {"value": abs(float(area_rel)), "limit": c.area_rel},
        "mean_mm": {"value": metrics["mean_mm"], "limit": c.mean_mm},
        "hausdorff_mm": {"value": metrics["hausdorff_mm"], "limit": c.hausdorff_mm},
    }
    for v in checks.values():
        v["ok"] = v["value"] <= v["limit"]
    checks["fscore"] = {"value": fscore, "limit": c.fscore_min, "ok": fscore >= c.fscore_min}
    if not c.allow_mirrored:
        checks["mirrored"] = {"value": float(info["mirrored"]), "limit": 0.0, "ok": not info["mirrored"]}
    if c.score_min > 0:
        checks["score"] = {"value": score, "limit": c.score_min, "ok": score >= c.score_min}
    return Comparison(
        reference={"file": ref.source, **ref.summary()},
        candidate={"file": cand.source, **cand.summary()},
        metrics=metrics, checks=checks, score=score, passed=all(v["ok"] for v in checks.values()),
        alignment={**info, "criteria": asdict(c)}, transform=[_r(row, 6) for row in m],
    )


def _aligned_size(cand: Mesh, m: np.ndarray) -> np.ndarray:
    """The candidate's bounding-box size along the reference axes. When the pose is within ~10
    degrees of an axis rotation (the usual case), its own box is permuted instead, so a small ICP
    tilt does not inflate the box."""
    r = m[:3, :3]
    perm = np.abs(r).argmax(axis=1)
    if len(set(perm)) == 3 and np.all(np.abs(r[np.arange(3), perm]) > np.cos(np.radians(10))):
        return cand.size[perm]
    return cand.transformed(m).size


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def subdivided(mesh: Mesh, max_edge: float, max_tris: int = 40_000) -> Mesh:
    """Split each triangle across its longest edge until no edge is longer than max_edge (for
    per-triangle coloring). Bisection keeps long slivers linear in count; max_edge is raised
    until the result stays under max_tris."""
    while True:
        tri, done, n = mesh.triangles, [], 0
        while len(tri):
            e = np.stack([np.linalg.norm(tri[:, (i + 1) % 3] - tri[:, i], axis=1) for i in range(3)], axis=1)
            big = e.max(axis=1) > max_edge
            done.append(tri[~big])
            n += int((~big).sum())
            t, k = tri[big], e[big].argmax(axis=1)
            if n + 2 * len(t) > max_tris * 4:  # hopeless at this size: give up early
                break
            # rotate so the longest edge is (p0, p1), then split it at its midpoint
            idx = (np.arange(3)[None, :] + k[:, None]) % 3
            t = np.take_along_axis(t, idx[:, :, None], axis=1)
            mid = (t[:, 0] + t[:, 1]) / 2
            tri = np.concatenate([np.stack([t[:, 0], mid, t[:, 2]], axis=1), np.stack([mid, t[:, 1], t[:, 2]], axis=1)])
        if not len(tri) and n <= max_tris:
            t = np.concatenate(done)
            return Mesh(t.reshape(-1, 3), np.arange(3 * len(t)).reshape(-1, 3), mesh.source)
        max_edge *= 1.5


def deviation_colors(ref: Mesh, cand_aligned: Mesh, scale_mm: float) -> np.ndarray:
    """Per-triangle RGB for the reference: green on the candidate's surface -> red at scale_mm or more."""
    d = Surface(cand_aligned).closest(ref.triangles.mean(axis=1))[0]
    x = np.clip(d / max(scale_mm, 1e-9), 0, 1)[:, None]
    return (1 - x) * np.array([0.2, 0.7, 0.3]) + x * np.array([0.85, 0.15, 0.15])


def render_comparison(reference, candidate, comparison: Comparison, path: str | Path, title: str = "") -> Path:
    """Six views of the reference colored by distance to the aligned candidate (green = within
    tol_mm .. red = 4 x tol_mm or more), plus the candidate in grey where the reference has no surface."""
    from .render import render

    ref, cand = as_mesh(reference), as_mesh(candidate)
    moved = cand.transformed(np.array(comparison.transform))
    edge = float(np.linalg.norm(ref.size)) / 40
    ref_f, moved_f = subdivided(ref, edge), subdivided(moved, edge)
    tol = comparison.metrics["tol_mm"]
    colors = deviation_colors(ref_f, moved, 4 * tol)
    extra = Surface(ref).closest(moved_f.triangles.mean(axis=1))[0] > tol
    items = [(ref_f, colors, "reference (green = matches, red = off by >= %g mm)" % (4 * tol))]
    if extra.any():
        items.append((Mesh(moved_f.verts, moved_f.tris[extra]), "#999999", "candidate only"))
    return render(items, path, title or f"deviation: score {comparison.score:.1f}")
