"""Built-in print checks.

- overlap:  intersection volume between parts in their assembled position (incl. stand-ins).
- overhang: downward-facing surfaces in print orientation, angle measured from vertical
            (vertical wall = 0 deg, flat ceiling/bridge = 90 deg). The bed face is ignored.
- wall:     thinnest material in a cross-section, optionally only around a point (a hole, a
            counterbore, a dimple). Use it wherever a cut goes deeper than the wall it starts
            in: `is_valid` and hole-diameter checks do not catch a 0.05 mm skin.

Part scripts declare checks with the spec classes `Overlap`, `Overhang` and `Wall` from a
`checks(d)` function; `b123d-print check` runs them (see b123d_print.project).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import numpy as np
from build123d import Part

from .render import AXES, section_faces

FAIL, WARN, OK = "fail", "warn", "ok"
CORNER = 4.0  # see wall_thickness


@dataclass
class Finding:
    level: str  # "ok" | "warn" | "fail"
    check: str  # "overlap" | "overhang" | "wall" | "valid" | "error"
    target: str  # part name(s)
    message: str
    data: dict = field(default_factory=dict)

    def line(self) -> str:
        return f"[{self.level.upper():4}] {self.check:8} {self.target}: {self.message}"


# ---------------------------------------------------------------------------------------------
# Overlap


def overlap(parts: list[tuple[Part, str]], tol: float = 0.01, ignore=()) -> list[Finding]:
    """Pairwise intersection volume (mm^3) of [(part, label)]; > tol is a failure.
    ignore: label pairs that are meant to overlap (e.g. a screw stand-in in its hole)."""
    skip = {frozenset(p) for p in ignore}
    out = []
    for (a, an), (b, bn) in combinations(parts, 2):
        if frozenset((an, bn)) in skip:
            continue
        if not _bbox_overlap(a, b):
            v = 0.0
        else:
            v = (a & b).volume
        level = FAIL if v > tol else OK
        msg = f"intersect {v:.3f} mm^3" if v > tol else "no overlap"
        out.append(Finding(level, "overlap", f"{an} / {bn}", msg, {"volume": round(v, 4)}))
    return out


def _bbox_overlap(a: Part, b: Part) -> bool:
    ba, bb = a.bounding_box(), b.bounding_box()
    amin, amax, bmin, bmax = (tuple(v) for v in (ba.min, ba.max, bb.min, bb.max))
    return all(amin[i] <= bmax[i] and bmin[i] <= amax[i] for i in range(3))


# ---------------------------------------------------------------------------------------------
# Overhang


def overhang_faces(part: Part, max_angle: float = 45.0, bed_tol: float = 0.05, tol: float = 0.05, angle_tol: float = 0.5,
                   ignore_below: float = 0.0) -> dict:
    """Downward faces steeper than max_angle from vertical, part in print orientation (bed at min Z).

    Returns {"faces": [...], "area": total flagged mm^2, "max_angle": deg}. Each face entry has
    its flagged area, max angle, Z range and center. Faces lying on the bed are ignored.
    angle_tol absorbs tessellation noise on surfaces designed at exactly max_angle.
    ignore_below: skip triangles lying entirely within this height above the bed."""
    zmin = part.bounding_box().min.Z
    found = []
    for face in part.faces():
        verts, tris = face.tessellate(tol, 0.1)
        if not tris:
            continue
        v = np.array([[p.X, p.Y, p.Z] for p in verts])
        t = np.array(tris)
        tri = v[t]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(n, axis=1) / 2
        keep = area > 1e-9
        if not keep.any():
            continue
        tri, n, area = tri[keep], n[keep], area[keep]
        n = n / (2 * area[:, None])
        # orient the triangles with the face (tessellation winding is not guaranteed outward)
        c = tri[0].mean(0)
        fn = face.normal_at(face.center()) if face.geom_type.name == "PLANE" else face.normal_at(_vec(c))
        if np.dot(n[0], [fn.X, fn.Y, fn.Z]) < 0:
            n = -n
        nz = np.clip(n[:, 2], -1, 1)
        ang = np.degrees(np.arcsin(np.clip(-nz, 0, 1)))  # 0 = vertical wall, 90 = ceiling
        down = nz < 0
        on_bed = (tri[:, :, 2].max(1) < zmin + bed_tol) & (nz < -0.99)
        low = tri[:, :, 2].max(1) < zmin + ignore_below
        flag = down & ~on_bed & ~low & (ang > max_angle + angle_tol)
        if not flag.any():
            continue
        fz = tri[flag][:, :, 2]
        fa = area[flag]
        centers = tri[flag].mean(1)
        ctr = (centers * fa[:, None]).sum(0) / fa.sum()
        found.append(
            {
                "area": round(float(fa.sum()), 2),
                "max_angle": round(float(ang[flag].max()), 1),
                "z": [round(float(fz.min()), 2), round(float(fz.max()), 2)],
                "center": [round(float(x), 2) for x in ctr],
                "kind": "bridge" if ang[flag].min() > 89 else face.geom_type.name.lower(),
            }
        )
    found.sort(key=lambda f: -f["area"])
    return {
        "faces": found,
        "area": round(sum(f["area"] for f in found), 2),
        "max_angle": max((f["max_angle"] for f in found), default=0.0),
    }


def _vec(c):
    from build123d import Vector

    return Vector(*map(float, c))


# ---------------------------------------------------------------------------------------------
# Wall thickness


def _loops(face, plane: str, step: float) -> list[np.ndarray]:
    """Face boundary loops as 2D polylines with material on the LEFT of each segment."""
    axis = AXES[plane]
    keep = [i for i in range(3) if i != axis]
    loops = []
    wires = [face.outer_wire(), *face.inner_wires()]
    for wi, w in enumerate(wires):
        pts = []
        for e in w.order_edges():
            n = max(2, int(np.ceil(e.length / step)) + 1)
            ps = e.positions(list(np.linspace(0, 1, n)))
            xy = [((p.X, p.Y, p.Z)[keep[0]], (p.X, p.Y, p.Z)[keep[1]]) for p in ps]
            if pts and np.hypot(xy[0][0] - pts[-1][0], xy[0][1] - pts[-1][1]) > np.hypot(xy[-1][0] - pts[-1][0], xy[-1][1] - pts[-1][1]):
                xy.reverse()  # edge stored against the wire direction
            pts.extend(xy if not pts else xy[1:])
        p = np.array(pts)
        if len(p) < 3:
            continue
        x, y = p[:, 0], p[:, 1]
        signed = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
        outer = wi == 0
        if (signed < 0) == outer:  # outer must be CCW, holes CW -> material on the left
            p = p[::-1]
        loops.append(p)
    return loops


def wall_thickness(part: Part, plane: str, at: float, near=None, radius: float | None = None, step: float = 0.1) -> dict | None:
    """Thinnest material in the cross-section of `part` on `plane` at `at`.

    near: (u, v) in the section's own 2D axes (XY -> (x, y), XZ -> (x, z), YZ -> (y, z)); with
    radius, only material within that distance of `near` is measured (e.g. around one hole).
    Thickness at each boundary point is the distance along the inward normal to the next
    boundary; also the closest approach between different boundary loops (hole to outside).
    Returns {"min": mm, "at": [u, v], "plane":..., ...} or None when the plane misses the region."""
    plane = plane.upper()
    best = None
    for face in section_faces(part, plane, at):
        loops = _loops(face, plane, step)
        if not loops:
            continue
        segs, loop_id, arc, perim = [], [], [], []
        for li, lp in enumerate(loops):
            sg = np.stack([lp, np.roll(lp, -1, axis=0)], 1)
            ln = np.linalg.norm(sg[:, 1] - sg[:, 0], axis=1)
            segs.append(sg)
            loop_id.append(np.full(len(sg), li))
            arc.append(np.cumsum(ln) - ln / 2)  # arc length at each segment's midpoint
            perim.append(np.full(len(sg), ln.sum()))
        segs, loop_id, arc, perim = (np.concatenate(x) for x in (segs, loop_id, arc, perim))
        a, b = segs[:, 0], segs[:, 1]
        d = b - a
        length = np.linalg.norm(d, axis=1)
        ok = length > 1e-9
        a, b, d, length, loop_id, arc, perim = a[ok], b[ok], d[ok], length[ok], loop_id[ok], arc[ok], perim[ok]
        mid = (a + b) / 2
        normal = np.c_[-d[:, 1], d[:, 0]] / length[:, None]  # left = into the material
        sel = np.ones(len(mid), bool)
        if near is not None and radius is not None:
            sel = np.hypot(mid[:, 0] - near[0], mid[:, 1] - near[1]) <= radius
        if not sel.any():
            continue
        o, r = mid[sel], normal[sel]
        o_loop, o_arc = loop_id[sel], arc[sel]
        # Ray (o + t r) vs segment (a + s d), in chunks. A hit a short way along the same boundary
        # (< CORNER * t) on a face that does not face back at the ray (normals > 30 deg from
        # opposite) is the other side of a corner, not of a wall: ignore it. Otherwise every
        # 60 deg corner would read as a 0.0x mm wall right at its tip.
        tmin = np.full(len(o), np.inf)
        traw = 0.0
        for i in range(0, len(o), 512):
            oo, rr = o[i : i + 512, None, :], r[i : i + 512, None, :]
            denom = rr[..., 0] * d[None, :, 1] - rr[..., 1] * d[None, :, 0]
            w = a[None] - oo
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (w[..., 0] * d[None, :, 1] - w[..., 1] * d[None, :, 0]) / denom
                s = (w[..., 0] * rr[..., 1] - w[..., 1] * rr[..., 0]) / denom
            hit = (np.abs(denom) > 1e-12) & (t > 1e-6) & (s >= -1e-9) & (s <= 1 + 1e-9)
            along = np.abs(o_arc[i : i + 512, None] - arc[None, :])
            along = np.minimum(along, perim[None, :] - along)
            facing = (rr[..., 0] * normal[None, :, 0] + rr[..., 1] * normal[None, :, 1]) < -0.866
            corner = (o_loop[i : i + 512, None] == loop_id[None, :]) & (along < CORNER * t) & ~facing
            traw = max(traw, float(np.where(hit, t, 0).max(initial=0)))
            t = np.where(hit & ~corner, t, np.inf)
            tmin[i : i + 512] = t.min(1)
        k = int(np.argmin(tmin))
        if np.isfinite(tmin[k]):
            cand = {"min": float(tmin[k]), "at": o[k].tolist(), "how": "across the wall"}
        else:  # only corner hits: a compact blob with no walls, as thick as it is wide
            cand = {"min": traw, "at": o[k].tolist(), "how": "no thin walls (compact section)"}
        # closest approach between different loops (a hole close to the outside or another hole)
        if len(loops) > 1:
            for (i, p), (j, q) in combinations(enumerate(loops), 2):
                if near is not None and radius is not None:
                    p = p[np.hypot(p[:, 0] - near[0], p[:, 1] - near[1]) <= radius]
                    q = q[np.hypot(q[:, 0] - near[0], q[:, 1] - near[1]) <= radius]
                if not len(p) or not len(q):
                    continue
                for c0 in range(0, len(p), 1024):
                    dd = np.hypot(p[c0 : c0 + 1024, None, 0] - q[None, :, 0], p[c0 : c0 + 1024, None, 1] - q[None, :, 1])
                    m = np.unravel_index(np.argmin(dd), dd.shape)
                    if dd[m] < cand["min"]:
                        cand = {"min": float(dd[m]), "at": ((p[c0 + m[0]] + q[m[1]]) / 2).tolist(), "how": "between two boundaries"}
        if best is None or cand["min"] < best["min"]:
            best = cand
    if best is None or not np.isfinite(best["min"]):
        return None
    best["min"] = round(best["min"], 3)
    best["at"] = [round(x, 2) for x in best["at"]]
    best["plane"] = plane
    best["section_at"] = at
    return best


# ---------------------------------------------------------------------------------------------
# Specs declared by part scripts


def _get(parts: dict, name):
    """Part by name (a single unnamed part is "part" or ""), or a Part passed directly."""
    if isinstance(name, Part):
        return name
    key = name or "part"
    if key not in parts:
        raise KeyError(f"no part named {name!r}; parts: {sorted(parts)}")
    return parts[key]


@dataclass
class Overlap:
    """Fail if any two assembly parts intersect by more than `tol` mm^3."""

    ignore: tuple = ()  # label pairs allowed to overlap
    tol: float = 0.01

    def run(self, parts, assembly, settings) -> list[Finding]:
        if not assembly:
            return []
        return overlap([(p, label) for p, _, label in assembly], self.tol, self.ignore)


@dataclass
class Overhang:
    """Report downward faces steeper than max_angle (default from settings, 45 deg).
    fail=True turns the report into a failure: use it for parts meant to print without supports."""

    part: str
    max_angle: float | None = None
    fail: bool = False
    min_area: float = 1.0  # mm^2; smaller flagged areas are reported but not counted
    ignore_below: float = 0.0  # mm above the bed; e.g. 1.0 to accept a small fillet on a bed edge
    bridges_ok: bool = True  # flat horizontal ceilings are listed but never fail: a bridge spanning
    #                          two walls prints fine; one hanging off a single wall does not, so
    #                          look at a section before trusting it

    def run(self, parts, assembly, settings) -> list[Finding]:
        lim = self.max_angle if self.max_angle is not None else settings.max_overhang
        r = overhang_faces(_get(parts, self.part), lim, ignore_below=self.ignore_below)
        big = [f for f in r["faces"] if f["area"] >= self.min_area]
        if not big:
            small = f" ({len(r['faces'])} tiny face(s), {r['area']} mm^2, ignored)" if r["faces"] else ""
            return [Finding(OK, "overhang", self.part or "part", f"nothing steeper than {lim:g} deg{small}", r)]
        area = sum(f["area"] for f in big)
        hard = [f for f in big if not (self.bridges_ok and f["kind"] == "bridge")]
        groups: dict = {}
        for f in big:
            k = (round(f["area"]), f["max_angle"], tuple(f["z"]), f["kind"])
            groups[k] = groups.get(k, 0) + 1
        items = sorted(groups.items(), key=lambda kv: -kv[0][0] * kv[1])
        top = "; ".join(
            f"{'%d x ' % n if n > 1 else ''}{a} mm^2 at {ang:.0f} deg, z {z[0]:g}..{z[1]:g} ({kind})"
            for (a, ang, z, kind), n in items[:4]
        )
        more = f" (+{len(items) - 4} more groups)" if len(items) > 4 else ""
        return [
            Finding(
                FAIL if self.fail and hard else WARN,
                "overhang",
                self.part or "part",
                f"{len(big)} face(s), {area:.0f} mm^2 steeper than {lim:g} deg: {top}{more}",
                r,
            )
        ]


@dataclass
class Wall:
    """Thinnest wall in a section (around `near` within `radius`); fail below `min`."""

    part: str
    plane: str
    at: float
    near: tuple | None = None
    radius: float | None = None
    min: float | None = None  # default: settings.min_wall
    label: str = ""

    def run(self, parts, assembly, settings) -> list[Finding]:
        lim = self.min if self.min is not None else settings.min_wall
        where = f"{self.plane} @ {self.at:g}" + (f" near {tuple(round(x, 2) for x in self.near)}" if self.near else "")
        name = self.part or "part"
        tgt = f"{name} ({self.label})" if self.label else name
        r = wall_thickness(_get(parts, self.part), self.plane, self.at, self.near, self.radius)
        if r is None:
            return [Finding(FAIL, "wall", tgt, f"section {where} misses the part (check the position)")]
        level = FAIL if r["min"] < lim else OK
        return [Finding(level, "wall", tgt, f"min wall {r['min']:.2f} mm (limit {lim:g}) at {r['at']}, {where}", r)]


@dataclass
class Probe:
    """Material must be present (expect="solid") or absent (expect="empty") in a small box.
    For design intent the other checks cannot see: "the roof is closed over the sensor",
    "nothing blocks the cable channel". part: a name from build() or a Part (e.g. assembled)."""

    part: object
    center: tuple
    size: tuple
    expect: str = "solid"
    fill: float = 0.98  # fraction of the box that counts as solid / at most this much counts as empty
    label: str = ""

    def run(self, parts, assembly, settings) -> list[Finding]:
        from build123d import Box, Pos

        box = Pos(*self.center) * Box(*self.size)
        frac = (_get(parts, self.part) & box).volume / box.volume
        tgt = self.label or (self.part if isinstance(self.part, str) else "part")
        good = frac >= self.fill if self.expect == "solid" else frac <= 1 - self.fill
        msg = f"{frac:.0%} solid at {tuple(round(c, 2) for c in self.center)} (expected {self.expect})"
        return [Finding(OK if good else FAIL, "probe", tgt, msg, {"fraction": round(frac, 4)})]


@dataclass
class Fit:
    """The part must fit the active printer's build volume in print orientation (added
    automatically when a printer profile is set; nothing to check in generic mode)."""

    part: str
    margin: float = 0.0  # mm kept free at each bed edge

    def run(self, parts, assembly, settings) -> list[Finding]:
        if not settings.printer:
            return []
        from .profiles import fits, load_printer

        pr = load_printer(settings.printer)
        size = _get(parts, self.part).bounding_box().size
        ok, why = fits(pr, (size.X, size.Y, size.Z), self.margin)
        level = OK if ok else FAIL
        if ok and "turned" in why:
            level = WARN
        return [Finding(level, "fit", self.part or "part", f"{pr.label or pr.name}: {why}")]
