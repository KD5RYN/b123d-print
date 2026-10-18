"""Write the reference mesh of the remix_bracket example: an L bracket as a "downloaded" STL.

    uv run python tools/make_remix_ref.py

It stands in for a model someone downloaded (made here, so its license is clear: CC0). Binary STL,
float32, holes faceted the way a slicer-bound export leaves them.
"""

from pathlib import Path

from build123d import Align, Box, Cylinder, Pos, Rot, export_stl

OUT = Path(__file__).resolve().parents[1] / "src/b123d_print/examples/remix_bracket/ref/l_bracket.stl"
MIN = (Align.CENTER, Align.CENTER, Align.MIN)

base = Box(50, 30, 4, align=MIN)
upright = Pos(0, 13, 0) * Box(50, 4, 30, align=MIN)
part = base + upright
part -= Pos(-10, -4, 0) * Cylinder(2.25, 10)  # two 4.5 mm mounting holes in the base
part -= Pos(10, -4, 0) * Cylinder(2.25, 10)
part -= Pos(0, 13, 20) * Rot(90, 0, 0) * Cylinder(3, 10)  # a 6 mm horizontal hole in the upright

OUT.parent.mkdir(parents=True, exist_ok=True)
export_stl(part, OUT, tolerance=0.02, angular_tolerance=0.3)
print(f"{OUT} ({OUT.stat().st_size} bytes)")
