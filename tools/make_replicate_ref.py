"""Write the reference drawing of the plate_2gang_to_1gang example: the injection-molded original.

    uv run python tools/make_replicate_ref.py

The example replicates a molded 2-gang to 1-gang adapter plate (#165). Its input is what a user
hands over for a physical part: photos and a dimensioned drawing, not a mesh. This draws that
drawing from the original's measurements (the values in the example's MEASURE.md), so it can be
committed without anyone's photos. Front view, section A-A and the back's molded features.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Rectangle  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src/b123d_print/examples/plate_2gang_to_1gang/ref/original_drawing.png"

W = H = 125.0  # caliper
DEPTH, FACE_T, RIM_IN = 6.5, 2.4, 120.3  # rim depth, face, inside of the rim
OPEN_W, OPEN_H = 52.5, 73.8
NOTCH_W, NOTCH_D = 6.0, 1.3
GANG_X, BOX_Y, DEV_Y = 46.0, 83.3, 83.3
HOLE, CBORE, CBORE_D, CENTER = 3.7, 7.3, 2.5, 2.8
BOSS_H = 4.3

INK, DIM, HID = "#1d3557", "#c0392b", "#7f8c8d"
LINE = dict(fill=False, lw=1.6, ec=INK)
THIN = dict(fill=False, lw=1.0, ec=INK)


def dim(ax, p1, p2, off, text, vertical=False):
    (x1, y1), (x2, y2) = p1, p2
    if vertical:
        xa = x1 + off
        ax.annotate("", (xa, y1), (xa, y2), arrowprops=dict(arrowstyle="<->", lw=0.8, color=DIM))
        ax.plot([x1, xa], [y1, y1], lw=0.5, color=DIM)
        ax.plot([x2, xa], [y2, y2], lw=0.5, color=DIM)
        ax.text(xa + (2.5 if off > 0 else -2.5), (y1 + y2) / 2, text, rotation=90, ha="center", va="center",
                fontsize=9, color=DIM, backgroundcolor="white")
    else:
        ya = y1 + off
        ax.annotate("", (x1, ya), (x2, ya), arrowprops=dict(arrowstyle="<->", lw=0.8, color=DIM))
        ax.plot([x1, x1], [y1, ya], lw=0.5, color=DIM)
        ax.plot([x2, x2], [y2, ya], lw=0.5, color=DIM)
        ax.text((x1 + x2) / 2, ya + (2.5 if off > 0 else -3.0), text, ha="center", va="center", fontsize=9,
                color=DIM, backgroundcolor="white")


fig, axes = plt.subplots(1, 2, figsize=(16, 8.2), gridspec_kw=dict(width_ratios=[1.25, 1.0]))
fig.suptitle("Original: 2-gang to 1-gang adapter plate, injection molded  —  mm, measured with calipers",
             fontsize=13, fontweight="bold")

# --- Front view (the face seen on the wall) ---
ax = axes[0]
ax.set_title("Front (seen on the wall)")
ax.add_patch(FancyBboxPatch((-W / 2 + 3, -H / 2 + 3), W - 6, H - 6, boxstyle="round,pad=3", **LINE))
ax.add_patch(Rectangle((-OPEN_W / 2, -OPEN_H / 2), OPEN_W, OPEN_H, **LINE))
for sy in (-1, 1):  # arc notches at the top and bottom of the opening
    ax.add_patch(Arc((0, sy * OPEN_H / 2), NOTCH_W, 2 * NOTCH_D, theta1=0 if sy > 0 else 180,
                     theta2=180 if sy > 0 else 360, lw=1.2, color=INK))
for sx in (-1, 1):
    for sy in (-1, 1):
        ax.add_patch(Circle((sx * GANG_X / 2, sy * BOX_Y / 2), HOLE / 2, **THIN))
        ax.add_patch(Circle((sx * GANG_X / 2, sy * BOX_Y / 2), CBORE / 2, **THIN))
for sy in (-1, 1):
    ax.add_patch(Circle((0, sy * DEV_Y / 2), CENTER / 2, **THIN))
ax.add_patch(Rectangle((-W / 2, -H / 2), 0.01, 0.01, fill=False, lw=0))
dim(ax, (-W / 2, -H / 2), (W / 2, -H / 2), -10, "125.0")
dim(ax, (W / 2, -H / 2), (W / 2, H / 2), 9, "125.0", vertical=True)
dim(ax, (-OPEN_W / 2, -OPEN_H / 2), (OPEN_W / 2, -OPEN_H / 2), -4, "52.5 opening")
dim(ax, (-OPEN_W / 2, -OPEN_H / 2), (-OPEN_W / 2, OPEN_H / 2), -4, "73.8 opening", vertical=True)
dim(ax, (-GANG_X / 2, BOX_Y / 2), (GANG_X / 2, BOX_Y / 2), 11, "46.0 (1-13/16 in)")
dim(ax, (-GANG_X / 2, -BOX_Y / 2), (-GANG_X / 2, BOX_Y / 2), -14, "83.3 box screws (3-9/32 in)", vertical=True)
dim(ax, (0, -DEV_Y / 2), (0, DEV_Y / 2), 33, "83.3 device screws", vertical=True)
ax.annotate("4 x Ø3.7 thru, counterbore Ø7.3 x 2.5 deep\n(#6-32 pan heads sit below the face)",
            (GANG_X / 2 + 2.6, BOX_Y / 2 + 2.6), (30, 54), fontsize=8.5, color=DIM,
            arrowprops=dict(arrowstyle="-", lw=0.6, color=DIM))
ax.annotate("2 x Ø2.8 (6-32 screws\nthread into the plastic)", (-1.0, DEV_Y / 2 + 1.0), (-60, 50), fontsize=8.5,
            color=DIM, arrowprops=dict(arrowstyle="-", lw=0.6, color=DIM))
ax.annotate("arc notch: 1.3 deep past the opening edge,\n~6 wide (read from a photo)", (-2.5, -OPEN_H / 2 - 1.0),
            (-58, -56), fontsize=8.5, color=DIM, arrowprops=dict(arrowstyle="-", lw=0.6, color=DIM))
ax.text(W / 2 - 40, -H / 2 + 4, "corners R ~3 (not gauged)", fontsize=8.5, color=DIM)
ax.plot([-W / 2 - 6, W / 2 + 6], [0, 0], lw=0.6, color=HID, ls="-.")
ax.text(-W / 2 - 6, 1.5, "A", fontsize=11, fontweight="bold", color=INK)
ax.text(W / 2 + 4, 1.5, "A", fontsize=11, fontweight="bold", color=INK)
ax.set_xlim(-W / 2 - 22, W / 2 + 22)
ax.set_ylim(-H / 2 - 20, H / 2 + 20)

# --- Section A-A and the back ---
ax = axes[1]
ax.set_title("Section A-A (face down, back up) and the molded back")
Z = 4.0  # depth drawn 4x: the section is 6.5 deep and 125 wide
prof = [(W / 2, 0), (W / 2, DEPTH), (RIM_IN / 2, DEPTH), (RIM_IN / 2, FACE_T),
        (OPEN_W / 2 + 1.5, FACE_T), (OPEN_W / 2 + 1.5, BOSS_H), (OPEN_W / 2, BOSS_H), (OPEN_W / 2, 0)]
for sign in (1, -1):
    pts = [(sign * x, Z * y) for x, y in prof]
    xs, ys = zip(*pts)
    ax.fill(xs, ys, color="#dfe6ee", ec=INK, lw=1.2)
dim(ax, (W / 2, 0), (W / 2, Z * DEPTH), 6, "6.5 rim", vertical=True)
dim(ax, (RIM_IN / 2 - 10, 0), (RIM_IN / 2 - 10, Z * FACE_T), -5, "2.4 face", vertical=True)
dim(ax, (-OPEN_W / 2 - 1.5, 0), (-OPEN_W / 2 - 1.5, Z * BOSS_H), -6, "4.3", vertical=True)
dim(ax, (-RIM_IN / 2, Z * DEPTH), (RIM_IN / 2, Z * DEPTH), 9, "120.3 inside the rim")
ax.annotate("inner frame rim and bosses:\n4.3 from the face", (-OPEN_W / 2 - 0.8, Z * BOSS_H), (-40, 44),
            fontsize=8.5, color=DIM, arrowprops=dict(arrowstyle="-", lw=0.6, color=DIM))
ax.text(W / 2, -5, "depth drawn 4x", fontsize=8, color=HID, ha="right")
ax.set_aspect("equal")
notes = (
    "The back (photos):\n"
    "  - thin uniform face (2.4) with a perimeter rim (6.5): cored, no solid sections\n"
    "  - an inner frame rim around the opening, with a row of small screw bosses for\n"
    "    other box and device patterns (not dimensioned: this copy does not use them)\n"
    "  - rim walls: draft not measured (outside measured at the face)\n"
    "  - a molded logo on the front and lettering on the back: cosmetic\n"
    "Material: unknown (glossy white molded plastic). Screws: #6-32 pan head (box),\n"
    "6-32 (device, threads into the plate). Must fit: a 2-gang box, a 1-gang smart switch."
)
ax.text(-W / 2, -12, notes, fontsize=8.8, va="top", family="monospace", color=INK)
ax.set_xlim(-W / 2 - 12, W / 2 + 14)
ax.set_ylim(-70, 56)

for a in axes:
    a.set_aspect("equal")
    a.axis("off")
fig.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT, dpi=110)
print(f"{OUT} ({OUT.stat().st_size} bytes)")
