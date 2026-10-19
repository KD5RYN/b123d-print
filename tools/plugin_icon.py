"""Draw the plugin's directory icon: plugin/.claude-plugin/icon.png (1024 x 1024).

A printed L-bracket, shaded in filament orange, on a dark rounded square with a faint print-bed
grid. Run: uv run python tools/plugin_icon.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from build123d import Align, Axis, Box, Cylinder, Location, Pos
from matplotlib.collections import PolyCollection
from matplotlib.patches import FancyBboxPatch

from b123d_print.render import tessellate

OUT = Path(__file__).resolve().parent.parent / "plugin" / ".claude-plugin" / "icon.png"
SIZE = 1024
BG_TOP, BG_BOTTOM = np.array([0x1F, 0x2A, 0x3C]) / 255, np.array([0x0E, 0x14, 0x1F]) / 255
FACING = -1  # the viewer looks along +z, so faces toward it have normal z < 0
ORANGE = np.array([0xF2, 0x8C, 0x28]) / 255


def bracket():
    base = Box(60, 40, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    wall = Pos(-26, 0, 0) * Box(8, 40, 48, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = base + wall
    for x in (6, 20):
        for y in (-10, 10):
            part -= Location((x, y, 0)) * Cylinder(3.4, 8, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for y in (-10, 10):
        part -= Location((-26, y, 32), (0, 90, 0)) * Cylinder(3.4, 20)
    return part.fillet(1.2, part.edges().filter_by(Axis.Z).group_by(Axis.X)[-1])


def project(verts):
    az, el = np.radians(-50), np.radians(28)
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    v = verts @ rz.T
    v = v[:, [0, 2, 1]] * [1, 1, -1]  # x right, z up, y into the screen
    return v @ np.array([[1, 0, 0], [0, np.cos(el), np.sin(el)], [0, -np.sin(el), np.cos(el)]]).T


def main():
    verts, tris = tessellate(bracket(), 0.05)
    p = project(verts)
    faces = p[tris]
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    light = np.array([-0.4, 0.7, -0.6])
    light /= np.linalg.norm(light)
    shade = np.clip(np.abs(normals @ light), 0, 1)
    colors = np.clip(ORANGE * (0.45 + 0.6 * shade[:, None]), 0, 1)
    front = np.flatnonzero(normals[:, 2] * FACING > 0)  # back faces culled
    order = front[np.argsort(faces[front, :, 2].mean(axis=1) * FACING)]  # far first

    fig = plt.figure(figsize=(SIZE / 100, SIZE / 100), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, 1), ax.set_ylim(0, 1), ax.axis("off")
    fig.patch.set_alpha(0)
    grad = np.linspace(0, 1, 256)[:, None, None] * (BG_BOTTOM - BG_TOP) + BG_TOP
    img = ax.imshow(grad, extent=(0, 1, 0, 1), aspect="auto", zorder=0)
    box = FancyBboxPatch((0.02, 0.02), 0.96, 0.96, boxstyle="round,pad=0,rounding_size=0.18",
                         transform=ax.transAxes, facecolor="none", edgecolor="none")
    ax.add_patch(box)
    img.set_clip_path(box)
    for g in np.linspace(0.1, 0.9, 9):  # print-bed grid
        for xs, ys in (([g, g], [0, 1]), ([0, 1], [g, g])):
            ax.plot(xs, ys, color="white", alpha=0.05, lw=2, zorder=1, clip_path=box)

    xy = faces[:, :, :2]
    lo, hi = xy.reshape(-1, 2).min(0), xy.reshape(-1, 2).max(0)
    scale = 0.66 / (hi - lo).max()
    xy = (xy - (lo + hi) / 2) * scale + [0.5, 0.48]
    ax.add_collection(PolyCollection(xy[order], facecolors=colors[order], edgecolors=colors[order],
                                     linewidths=1.2, zorder=2))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=100, transparent=True)
    print(OUT)


if __name__ == "__main__":
    main()
