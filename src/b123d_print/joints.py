"""Joints for parts split into pieces: matching male and female geometry with the clearance applied.

A part too big for the bed (or one that prints better in pieces) is cut at a plane, and the two
pieces get joint features: male on one side, female on the other, the female grown by the
clearance on every side (docs/using/splitting.md, BEST_PRACTICES J1-J9):

    from b123d_print.joints import Bowtie, Dovetail, Dowel, Insert, Lap, split

    s = split(part, Plane.YZ.offset(d.CUT_X), [Dowel(6, 20, square=True, at=(0, 5)),
                                               Bowtie(30, 16, 8, 4, at=(0, d.H))],
              clearance=d.CLEARANCE)
    s.a, s.b      # the two pieces, in the part's coordinates (turn them for printing yourself)
    s.loose       # separate printed pieces (pins, keys), each laid flat on Z=0 at the origin
    s.placed      # the same pins and keys where they sit when assembled

**The joint frame.** Each joint is placed on the cut plane by `at=(u, v)` (the plane's own x and y
coordinates; for `Plane.YZ` that is (Y, Z)) and `angle` (degrees, about the plane's normal). In
the joint frame Z is the plane's normal: piece **a** is below the plane (-Z, `Keep.BOTTOM`) and
piece **b** above it. Features attached to a piece (a plug, a dovetail tail, a lap tongue) go on
**a** and the matching socket into **b**; `flip=True` swaps them.

| joint | in the frame | male | female |
| --- | --- | --- | --- |
| `Dowel` | an axis along Z through (0, 0) | a pin, loose or a plug on a | sockets in both pieces (only in b for a plug) |
| `Bowtie` | lies in the XZ plane, sunk into -Y from a surface at y = 0 | a loose key | a recess across the seam |
| `Dovetail` | a tail widening along +Z, through the part along Y | a tail on a | a slot in b; slides together along Y |
| `Lap` | a tongue of a below y = 0, over z = 0..LENGTH, across the whole part | the tongue on a | the rebate in b |
| `Insert` | an axis along Z through (0, 0) | (the bought insert) | the insert pocket in a, the screw hole and head access in b |

Every joint also works on its own: `joint.pair(clearance)` returns `Pair(male, female)` in the
joint frame (male: the solid, female: the solid to cut away), so a script can place them itself.

**Fit.** The female is the male grown by `clearance` on every side: across a pin, a key, a tail
or a tongue, the female is exactly 2 x clearance bigger (BP-F1, BP-J3); its ends get the same
gap. Round sockets and insert pockets also get `hole_comp` on the diameter, like every hole
(BP-H1); square sockets do not (hole compensation is measured on round holes). A joint's own
`clearance` (e.g. `Dowel(..., clearance=d.PRESS_FIT)`) overrides the one passed to `split`.

**Print notes.** Loose pins and keys come back laid flat, so the load across the seam runs along
their layers (BP-S4): a square pin flat on a side, a round pin on its side on a 45-degree flat
(no overhang past 45 degrees, BP-O1), a key flat on its face. A round socket that lies on its
side in the piece's print orientation is a round horizontal hole (the holes check warns, BP-H3):
use a square pin there. Profiles are rounded at the corners (`r`, BP-R1); the female's corners
follow at exactly `clearance` away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from build123d import (Align, Box, Compound, Cylinder, Face, Keep, Kind, Location, Part, Plane, Polygon, Pos, Rot, chamfer,
                       extrude, fillet, offset)

SPAN = 2000.0  # mm: "through the part" for dovetails, laps and head access; then clipped to the part
EPS = 0.01  # mm: overlap so a feature fuses with its piece, and a cutter opens a surface cleanly


@dataclass(frozen=True)
class Pair:
    """A joint's matching geometry in its frame: `male` (the pin, key, tail or tongue as printed)
    and `female` (what to cut away for it, `clearance` bigger on every side)."""

    male: Part | None
    female: Part
    loose: bool  # the male is a separate print (a pin or a key), not part of a piece


# --- the joints ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Dowel:
    """A pin across the cut: `d` across (diameter, or the side of a square pin) and `length` in
    all (half in each piece). `square=True` stops twisting and prints flat without overhangs.
    `plug=True` prints the pin on piece a (a plug, PrusaSlicer's name) instead of loose: no
    separate part, but it stands across the layers when a's cut face lies on the bed."""

    d: float = 6.0
    length: float = 20.0
    square: bool = False
    plug: bool = False
    at: tuple = (0.0, 0.0)
    angle: float = 0.0
    chamfer: float = 0.5  # lead-in at the pin's ends
    clearance: float | None = None
    flip: bool = False

    def pair(self, clearance: float, hole_comp: float = 0.0) -> Pair:
        c = _c(self, clearance)
        half = self.length / 2
        grow = 2 * c + (0 if self.square else hole_comp)
        if self.plug:  # on a's face (overlapping it a little, to fuse), a socket in b only
            pin = _chamfer_ends(_prism(self.d, half + EPS, self.square, -EPS), self.chamfer, top_only=True)
            return Pair(pin, _prism(self.d + grow, half + c + EPS, self.square, -EPS), loose=False)
        pin = _chamfer_ends(_prism(self.d, self.length, self.square, -half), self.chamfer)
        return Pair(pin, _prism(self.d + grow, self.length + 2 * c, self.square, -half - c), loose=True)

    def printed(self, male: Part) -> Part:
        """The loose pin laid flat: a square pin on a side, a round one on a 45-degree flat."""
        flat = Rot(0, 90, 0) * male  # axis along X
        if not self.square:
            r = self.d / 2
            flat = flat - Pos(0, 0, -r) * Box(SPAN, SPAN, 2 * r * (1 - math.sqrt(0.5)))
        return _to_bed(flat)


@dataclass(frozen=True)
class Bowtie:
    """A bowtie (butterfly) key across the seam, sunk into a surface: `length` across the cut,
    `width` at its ends, `waist` at the seam, `depth` into the surface (the key's thickness).
    `at` is a point on the surface at the seam; the recess goes into -Y of the joint frame, so
    turn it with `angle` (180 for a surface facing -Y). The key prints flat on its face, so the
    pull across the seam runs along its layers."""

    length: float = 30.0
    width: float = 16.0
    waist: float = 8.0
    depth: float = 4.0
    at: tuple = (0.0, 0.0)
    angle: float = 0.0
    r: float = 1.0  # corner radius of the key (the recess's corners are r + clearance)
    clearance: float | None = None
    flip: bool = False

    def outline(self, grow: float = 0.0) -> Face:
        """The key's outline in XY (x across the key, y across the seam), grown by `grow`."""
        w, n, h = self.width / 2, self.waist / 2, self.length / 2
        f = fillet(Polygon((-w, -h), (w, -h), (n, 0), (w, h), (-w, h), (-n, 0), align=None).vertices(), self.r)
        return offset(f, grow, kind=Kind.ARC).face() if grow else f.face()

    def pair(self, clearance: float, hole_comp: float = 0.0) -> Pair:
        c = _c(self, clearance)
        key = extrude(self.outline(), self.depth)  # in XY, Z = 0..depth
        recess = extrude(self.outline(c), self.depth + c + EPS)
        to_frame = Rot(-90, 0, 0)  # the key's Y (across the seam) -> frame Z, its thickness -> -Y
        return Pair(to_frame * Pos(0, 0, -self.depth) * key, to_frame * Pos(0, 0, -self.depth - c) * recess,
                    loose=True)

    def printed(self, male: Part) -> Part:
        return _to_bed(extrude(self.outline(), self.depth))


@dataclass(frozen=True)
class Dovetail:
    """A dovetail tail on piece a that fits a slot in piece b: `width` at the root (on the cut),
    `length` into b, `taper` of its sides (degrees from the cut normal), `height` along the
    frame's Y (None: through the part). Locks against pulling apart along the normal; the pieces
    slide together along Y, so a glued or screwed dovetail still needs something to stop that."""

    width: float = 12.0
    length: float = 10.0
    taper: float = 15.0
    height: float | None = None
    at: tuple = (0.0, 0.0)
    angle: float = 0.0  # turns the joint about the normal (the slide direction with it)
    r: float = 0.5  # corner radius of the tail
    clearance: float | None = None
    flip: bool = False

    @property
    def tip_width(self) -> float:
        return self.width + 2 * self.length * math.tan(math.radians(self.taper))

    def outline(self, grow: float = 0.0) -> Face:
        """The tail in the frame's XZ plane (x across, z along the normal), drawn in XY here."""
        w0, w1, ln = self.width / 2, self.tip_width / 2, self.length
        root = 2 * self.r + 1.0  # a strip of a under the tail, so the root corners are filleted too
        f = Polygon((-w0 - root, -root), (w0 + root, -root), (w0 + root, 0), (w0, 0), (w1, ln), (-w1, ln),
                    (-w0, 0), (-w0 - root, 0), align=None)
        f = fillet(f.vertices(), self.r)
        return offset(f, grow, kind=Kind.ARC).face() if grow else f.face()

    def pair(self, clearance: float, hole_comp: float = 0.0) -> Pair:
        c = _c(self, clearance)
        h = self.height or SPAN
        to_frame = Rot(90, 0, 0)  # drawn in XY: its Y -> frame Z, the extrusion -> frame Y
        tail = to_frame * extrude(self.outline(), h / 2, both=True)
        slot = to_frame * extrude(self.outline(c), h / 2 + (c if self.height else 0), both=True)
        return Pair(tail, slot, loose=False)


@dataclass(frozen=True)
class Lap:
    """A lap (rebate) joint: piece a keeps a tongue below y = 0 of the joint frame (so `at=(0, v)`
    puts the step at height v) reaching `length` into b, across the whole part; b has the
    matching rebate. Doubles the glue area and hides the seam's straight line through the part."""

    length: float = 15.0
    at: tuple = (0.0, 0.0)
    angle: float = 0.0
    clearance: float | None = None
    flip: bool = False

    def pair(self, clearance: float, hole_comp: float = 0.0) -> Pair:
        c = _c(self, clearance)
        tongue = Pos(0, -SPAN / 2, (self.length - EPS) / 2) * Box(SPAN, SPAN, self.length + EPS)
        rebate = Pos(0, (c - SPAN) / 2, (self.length + c) / 2) * Box(SPAN, SPAN + c, self.length + c)
        return Pair(tongue, rebate, loose=False)


# CNC Kitchen standard heat-set inserts (BP-T2, T3, T4; the maker's table, as listed by 3DJAKE,
# the same numbers as bd_warehouse's CNCKitchen rows): hole diameter, insert length, minimum wall
# around it. Hole depth = length + 1 mm (BP-T3). Then ISO 273 medium screw clearance and the
# DIN 974-1 counterbore for an ISO 4762 socket head.
INSERTS = {
    #       hole  length wall  screw  head
    "M2": (3.2, 3.0, 1.3, 2.4, 4.3),
    "M2.5": (4.0, 4.0, 1.6, 2.9, 5.0),
    "M3": (4.0, 5.7, 1.6, 3.4, 6.5),
    "M4": (5.6, 8.1, 2.1, 4.5, 8.0),
    "M5": (6.4, 9.5, 2.6, 5.5, 10.0),
    "M6": (8.0, 12.7, 3.3, 6.6, 11.0),
}


@dataclass(frozen=True)
class Insert:
    """A heat-set insert pocket in piece a, on the cut face along the normal, and in piece b the
    screw's clearance hole over `grip` (the material the screw clamps) and head access from there
    on through the rest of b along the normal: put it on a flange or a boss, where b is thin.
    Bolts the pieces together and comes apart again (BP-T5). Sizes: `INSERTS` (CNC Kitchen); for
    another maker's insert pass its datasheet's `hole`, `length` and `wall` (BP-T2)."""

    size: str = "M3"
    grip: float = 5.0
    at: tuple = (0.0, 0.0)
    angle: float = 0.0
    hole: float | None = None  # the maker's hole diameter (default: INSERTS)
    length: float | None = None  # the insert's length (a short insert: 3.0 for CNC Kitchen's M3 short)
    wall: float | None = None  # the maker's minimum wall
    flip: bool = False

    @property
    def dims(self) -> tuple:
        """(hole, length, wall, screw clearance, head counterbore) in mm."""
        if self.size not in INSERTS:
            raise ValueError(f"Insert: no size {self.size!r}; sizes: {sorted(INSERTS)}")
        hole, length, wall, screw, head = INSERTS[self.size]
        return (self.hole or hole, self.length or length, self.wall or wall, screw, head)

    @property
    def min_wall(self) -> float:
        """The maker's minimum wall around the pocket (add a Wall check with it, BP-T4)."""
        return self.dims[2]

    def pair(self, clearance: float, hole_comp: float = 0.0) -> Pair:
        hole, length, _, screw, head = self.dims
        pocket = Pos(0, 0, -(length + 1)) * Cylinder((hole + hole_comp) / 2, length + 1 + EPS, align=_BED)
        through = Cylinder((screw + hole_comp) / 2, self.grip + EPS, align=_BED)
        access = Pos(0, 0, self.grip) * Cylinder((head + hole_comp) / 2, SPAN, align=_BED)
        return Pair(None, pocket + through + access, loose=False)


JOINTS = (Dowel, Bowtie, Dovetail, Lap, Insert)


# --- cutting a part ------------------------------------------------------------------------------


@dataclass
class Split:
    """The two pieces of a cut part, in the part's coordinates, and the loose pieces (pins and
    keys) laid flat for printing, named pin1, pin2, ..., key1, ...; `placed` has the same loose
    pieces where they sit when assembled (for assembly(d) and its Overlap and Gap checks)."""

    a: Part
    b: Part
    loose: dict = field(default_factory=dict)
    placed: dict = field(default_factory=dict)
    plane: Plane | None = None

    def parts(self, a: str = "a", b: str = "b") -> dict:
        """{a: piece a, b: piece b, "pin1": ..., "key1": ...} for build(d)."""
        return {a: self.a, b: self.b, **self.loose}


def split(part: Part, plane: Plane, joints: list = (), clearance: float | None = None,
          hole_comp: float = 0.0) -> Split:
    """Cut `part` at `plane` into a (below the plane) and b (above), with `joints` on the cut.

    `clearance` (per side) is the script's `CLEARANCE` (`clearance(__file__)`, BP-F1); required
    when there are joints. `hole_comp` goes onto round sockets and insert pockets (use
    `HOLE_COMP_H` when they lie on their side in print). Attached features (plugs, tails,
    tongues) are clipped to the original part, so nothing sticks out of its outline."""
    if joints and clearance is None:
        raise ValueError("split: pass clearance=d.CLEARANCE (per side) when there are joints")
    a = _solid(part.split(plane, keep=Keep.BOTTOM), "below the plane")
    b = _solid(part.split(plane, keep=Keep.TOP), "above the plane")
    loose, placed, n = {}, {}, {"pin": 0, "key": 0}
    for j in joints:
        if not isinstance(j, JOINTS):
            raise TypeError(f"split: {j!r} is not a joint ({', '.join(t.__name__ for t in JOINTS)})")
        p = j.pair(clearance, hole_comp)
        at = Location(plane) * Pos(j.at[0], j.at[1], 0) * Rot(0, 0, j.angle)
        if j.flip:
            at = at * Rot(180, 0, 0)  # the normal reversed: b is now below
        male, female = (at * p.male if p.male is not None else None), at * p.female
        top, bottom = (a, b) if j.flip else (b, a)  # bottom gets the attached male
        if p.loose:
            kind = "pin" if isinstance(j, Dowel) else "key"
            n[kind] += 1
            loose[f"{kind}{n[kind]}"] = j.printed(p.male)
            placed[f"{kind}{n[kind]}"] = male
            bottom, top = bottom - female, top - female
        else:
            if male is not None:
                bottom = bottom + (male & part)
            top = top - female
            if isinstance(j, Insert):
                bottom = bottom - female
        a, b = (top, bottom) if j.flip else (bottom, top)
        a, b = _solid(a, "a"), _solid(b, "b")
    return Split(a, b, loose, placed, plane)


# --- helpers --------------------------------------------------------------------------------------

_BED = (Align.CENTER, Align.CENTER, Align.MIN)


def _c(joint, clearance: float | None) -> float:
    c = joint.clearance if joint.clearance is not None else clearance
    if c is None:
        raise ValueError(f"{type(joint).__name__}: no clearance (pass clearance=d.CLEARANCE)")
    if c < 0:
        raise ValueError(f"{type(joint).__name__}: clearance {c} < 0")
    return c


def _prism(w: float, length: float, square: bool, z0: float) -> Part:
    shape = Box(w, w, length, align=_BED) if square else Cylinder(w / 2, length, align=_BED)
    return Pos(0, 0, z0) * shape


def _chamfer_ends(pin: Part, size: float, top_only: bool = False) -> Part:
    if size <= 0:
        return pin
    faces = pin.faces().sort_by(lambda f: f.center().Z)
    ends = [faces[-1]] if top_only else [faces[0], faces[-1]]
    return chamfer([e for f in ends for e in f.edges()], length=size)


def _to_bed(p: Part) -> Part:
    bb = p.bounding_box()
    return Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * p


def _solid(shape, what: str) -> Part:
    """One valid solid (a cut that leaves several bodies on one side is an error: say where)."""
    solids = shape.solids() if shape is not None else []
    if not solids:
        raise ValueError(f"split: nothing {what}: the plane misses the part")
    if len(solids) > 1:
        vols = ", ".join(f"{s.volume:.0f}" for s in solids)
        raise ValueError(f"split: {len(solids)} separate bodies {what} (volumes {vols} mm^3): a joint cuts "
                         "a piece apart, or the plane crosses the part twice")
    s = solids[0]
    if not s.is_valid:
        raise ValueError(f"split: piece {what} is not a valid solid")
    return Part(Compound([s]).wrapped)  # (Part(<a TopoDS_Solid>) reports volume 0)
