"""Export (STEP/STL) and matplotlib previews: 6-view render, cross-sections."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.collections  # noqa: E402
import matplotlib.patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from build123d import Part, Plane, Vector, export_step, export_stl, section as _section  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

# (title, elevation, azimuth, axis whose ticks are hidden) for orthographic views
VIEWS = [
    ("Iso", 30, -60, None),
    ("Top (XY)", 90, -90, "z"),
    ("Front (XZ)", 0, -90, "y"),
    ("Right (YZ)", 0, 0, "x"),
    ("Iso from below", -30, -60, None),
    ("Bottom (XY, from below)", -90, -90, "z"),
]

PALETTE = ["#4c8cd9", "#e0a030", "#2a9d4b", "#cc4444", "#7a3fb0", "#888888"]

AXES = {"XY": 2, "XZ": 1, "YZ": 0}  # plane -> index of the axis normal to it


def report(part: Part) -> dict:
    """Bounding box (mm), volume (mm^3) and validity."""
    bb = part.bounding_box()
    return {
        "x": round(bb.size.X, 3),
        "y": round(bb.size.Y, 3),
        "z": round(bb.size.Z, 3),
        "min": [round(v, 3) for v in (bb.min.X, bb.min.Y, bb.min.Z)],
        "max": [round(v, 3) for v in (bb.max.X, bb.max.Y, bb.max.Z)],
        "volume": round(part.volume, 2),
        "solids": len(part.solids()),
        "valid": bool(part.is_valid),
    }


def _as_list(parts) -> list[tuple[Part, str, str]]:
    """Part | [(part, color, label)] | {label: part} -> [(part, color, label)]."""
    if isinstance(parts, dict):
        parts = list(parts.items())
        return [(p, PALETTE[i % len(PALETTE)], str(k)) for i, (k, p) in enumerate(parts)]
    if isinstance(parts, (list, tuple)):
        out = []
        for i, item in enumerate(parts):
            if isinstance(item, (list, tuple)):
                p, color, label = (list(item) + [None, None])[:3]
                out.append((p, color or PALETTE[i % len(PALETTE)], label or f"part {i}"))
            else:
                out.append((item, PALETTE[i % len(PALETTE)], f"part {i}"))
        return out
    return [(parts, PALETTE[0], "")]


def render(parts, path: str | Path, title: str, tol: float = 0.02) -> Path:
    """Six orthographic/iso views of one part, or several as [(part, color, label)]."""
    items = _as_list(parts)
    all_faces, all_colors = [], []
    light = np.array([0.4, -0.6, 0.8])
    light /= np.linalg.norm(light)
    for part, color, _ in items:
        verts, tris = part.tessellate(tol, 0.2)
        if not tris:
            continue
        v = np.array([[p.X, p.Y, p.Z] for p in verts])
        faces = v[np.array(tris)]
        n = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.35 + 0.65 * np.abs(n @ light)  # two-sided
        rgb = np.array(matplotlib.colors.to_rgb(color))
        all_faces.append(faces)
        all_colors.append(np.c_[shade[:, None] * rgb, np.ones_like(shade)])
    if not all_faces:
        raise ValueError("nothing to render (empty part)")
    faces = np.concatenate(all_faces)
    colors = np.concatenate(all_colors)
    pts = faces.reshape(-1, 3)
    lo, hi = pts.min(0), pts.max(0)
    ctr, r = (lo + hi) / 2, (hi - lo).max() / 2 * 1.05
    size = hi - lo

    fig = plt.figure(figsize=(18, 10))
    fig.suptitle(f"{title}   —   {size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f} mm (X×Y×Z)", fontsize=14)
    for i, (name, elev, azim, hidden) in enumerate(VIEWS):
        ax = fig.add_subplot(2, 3, i + 1, projection="3d")
        ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors=colors, linewidths=0.3))
        ax.set_proj_type("ortho")
        ax.view_init(elev, azim)
        for setlim, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), ctr):
            setlim(c - r, c + r)
        ax.set_box_aspect((1, 1, 1))
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        if hidden:
            getattr(ax, f"set_{hidden}ticks")([])
            getattr(ax, f"set_{hidden}label")("")
        ax.set_title(name)
    if len(items) > 1:
        fig.legend(
            handles=[matplotlib.patches.Patch(color=c, label=lbl) for _, c, lbl in items],
            loc="lower center", ncol=len(items),
        )
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def section_plane(plane: str, at: float) -> Plane:
    """Cutting plane: 'XY' at Z=at, 'XZ' at Y=at, 'YZ' at X=at."""
    axis = AXES[plane.upper()]
    origin = [0.0, 0.0, 0.0]
    origin[axis] = at
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    x_dir = (0, 1, 0) if axis == 0 else (1, 0, 0)
    return Plane(origin=Vector(*origin), x_dir=Vector(*x_dir), z_dir=Vector(*normal))


def section_faces(part: Part, plane: str, at: float):
    """Faces of the cross-section of `part`; empty list if the plane misses it."""
    try:
        s = _section(part, section_by=section_plane(plane, at))
    except Exception:
        return []
    return list(s.faces()) if s is not None else []


def section_view(parts, plane: str, at: float, path: str | Path, title: str) -> Path:
    """Colored cross-section of one or several parts. plane: 'XY' (at=Z), 'XZ' (at=Y), 'YZ' (at=X).
    parts: a Part, {label: part} or [(part, color, label)]. Clearer than the 3D render for ribs,
    walls and how parts fit together."""
    plane = plane.upper()
    axis = AXES[plane]
    keep = [i for i in range(3) if i != axis]
    fig, ax = plt.subplots(figsize=(11, 8))
    handles = []
    for part, color, label in _as_list(parts):
        drew = False
        for face in section_faces(part, plane, at):
            v, t = face.tessellate(0.02)
            if not t:
                continue
            v = np.array([[(p.X, p.Y, p.Z)[keep[0]], (p.X, p.Y, p.Z)[keep[1]]] for p in v])
            ax.add_collection(
                matplotlib.collections.PolyCollection(v[np.array(t)], facecolors=color, edgecolors=color, linewidths=0.2)
            )
            drew = True
        if drew and label:
            handles.append(matplotlib.patches.Patch(color=color, label=label))
    names = "XYZ"
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.set_xlabel(names[keep[0]] + " (mm)")
    ax.set_ylabel(names[keep[1]] + " (mm)")
    if handles:
        ax.legend(handles=handles, loc="upper right", fontsize=9)
    if not ax.collections:
        ax.text(0.5, 0.5, "plane misses every part", transform=ax.transAxes, ha="center")
    ax.set_title(f"{title}: {plane} section at {names[axis]}={round(at, 3):g} mm")
    path = Path(path)
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def section(part: Part, z: float, path: str | Path, title: str) -> Path:
    """XY cross-section at height z (kept for scripts written against the original helper)."""
    return section_view([(part, "#4c8cd9", "")], "XY", z, path, title)


def export_files(part: Part, out: Path, name: str, png: bool = True) -> list[Path]:
    """Write <name>.step, <name>.stl (and <name>.png) into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    files = [out / f"{name}.step", out / f"{name}.stl"]
    export_step(part, files[0])
    export_stl(part, files[1], tolerance=0.005, angular_tolerance=0.1)
    if png:
        files.append(render(part, out / f"{name}.png", name))
    return files


def export(part: Part, script_file: str, name: str | None = None, sections: tuple[float, ...] = ()) -> dict:
    """Write out/<name>.{step,stl,png} next to the script (plus <name>_z<Z>.png per section height)
    and print the bounding box. `name` defaults to the script's folder name."""
    here = Path(script_file).resolve().parent
    name = name or here.name
    out = here / "out"
    export_files(part, out, name)
    for z in sections:
        section(part, z, out / f"{name}_z{round(z, 3):g}.png", name)
    d = report(part)
    print(f"{name}: {d['x']:.2f} x {d['y']:.2f} x {d['z']:.2f} mm, volume {d['volume']:.1f} mm^3, valid={d['valid']}")
    print(f"  -> {out}/{name}.{{step,stl,png}}")
    return d
