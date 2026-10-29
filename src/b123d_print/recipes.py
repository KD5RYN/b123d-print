"""Recipes: small, tested build123d functions for common printable features.

    from b123d_print.recipes import teardrop_hole, screw_hole, nut_trap
    part -= Pos(0, 0, 8) * teardrop_hole(d.HOLE_D + d.HOLE_COMP_H, 30)

Every recipe is a plain function of named parameters (mm) that returns a Part: a cutter to
subtract (holes, pockets, slots, text to deboss) or a body to add or print (snap arm, hinge,
lid, gusset). Cutters are placed with the surface they open on at Z=0 and point into -Z, or
are centered on their axis; the docstring says which. Hole diameters are the *printed* size:
pass the user's hole compensation as `hole_comp` (HOLE_COMP from the script), never a number
from somewhere else.

Each recipe has a demo part (`demo_<name>`) that the tests build and run through `check`; the
MCP resource b123d-print://recipes/<name> and the `recipe` tool show the code, the printing
notes and the sources (BP-* ids are the sourced rules in docs/BEST_PRACTICES.md).
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field

from build123d import (Align, Axis, Bezier, Box, Circle, Compound, Cone, Cylinder, Edge, Face, FontStyle, GeomType, Keep,
                       Part, Plane, Polygon, Pos, Rectangle, RegularPolygon, Rot, Shell, Sketch, Solid, Sphere, Spline, Text,
                       Vector, Vertex, Wire, extrude, fillet, loft, make_face, offset, scale, section, split, sweep)

from .pcb import pcb_board, pcb_mounting_pattern, pcb_standoff

BED = (Align.CENTER, Align.CENTER, Align.MIN)
TOP = (Align.CENTER, Align.CENTER, Align.MAX)  # cutters that open on Z=0 and go down

# ISO 273 medium clearance holes; ISO 4762 socket head (head d, head height); ISO 10642 / ISO 7046
# countersunk head d; ISO 4032 hex nut (across flats, thickness). mm. screw_hole reads the screw
# sizes from bd_warehouse's tables when it has them (_screw); these are the fallback.
SCREW = {
    "M2": {"clearance": 2.4, "head_d": 3.8, "head_h": 2.0, "csk_d": 3.8, "nut_af": 4.0, "nut_h": 1.6},
    "M2.5": {"clearance": 2.9, "head_d": 4.5, "head_h": 2.5, "csk_d": 4.7, "nut_af": 5.0, "nut_h": 2.0},
    "M3": {"clearance": 3.4, "head_d": 5.5, "head_h": 3.0, "csk_d": 6.72, "nut_af": 5.5, "nut_h": 2.4},
    "M4": {"clearance": 4.5, "head_d": 7.0, "head_h": 4.0, "csk_d": 8.96, "nut_af": 7.0, "nut_h": 3.2},
    "M5": {"clearance": 5.5, "head_d": 8.5, "head_h": 5.0, "csk_d": 11.2, "nut_af": 8.0, "nut_h": 4.7},
    "M6": {"clearance": 6.6, "head_d": 10.0, "head_h": 6.0, "csk_d": 13.44, "nut_af": 10.0, "nut_h": 5.2},
}
# Allowable strain for snap arms printed flat (BP-N4, provisional: one source, Fictiv). Halve it
# for an arm along Z (BP-N1).
SNAP_STRAIN = {"pla": (0.04, 0.08), "abs": (0.07, 0.07), "nylon": (0.04, 0.15)}


COARSE = {"M2": "M2-0.4", "M2.5": "M2.5-0.45", "M3": "M3-0.5", "M4": "M4-0.7", "M5": "M5-0.8", "M6": "M6-1"}


def _screw(size: str) -> dict:
    """The SCREW row for a size, with the clearance hole and the head sizes read from bd_warehouse's
    fastener tables (ISO 4762 socket head, ISO 10642 countersunk) where it has them."""
    key = size.upper()
    if key not in SCREW:
        raise ValueError(f"screw size {size!r}: one of {', '.join(SCREW)}")
    row = dict(SCREW[key])
    try:
        from bd_warehouse.fastener import CounterSunkScrew, SocketHeadCapScrew

        shc = SocketHeadCapScrew(COARSE[key], 10, "iso4762", simple=True)
        row.update(clearance=shc.clearance_hole_diameters["Normal"], head_d=round(shc.head_diameter, 2),
                   head_h=round(shc.head_height, 2))
        csk = CounterSunkScrew(COARSE[key], 10, "iso10642", simple=True)
        row.update(csk_d=round(csk.head_diameter, 2))
    except Exception:  # noqa: BLE001 - no bd_warehouse, or a size its tables lack: the table above
        pass
    return row


# ---------------------------------------------------------------------------------------------
# Holes


def teardrop_hole(d: float, length: float, roof: str = "teardrop", angle: float = 45.0) -> Part:
    """A horizontal hole along Y, centered on the origin, that prints without support: a circle
    with a pointed roof whose sides are `angle` from vertical (roof="teardrop"), or the same
    roof cut flat at the top of the circle (roof="flat", a short bridge). d: printed diameter
    (add HOLE_COMP_H). The roof points +Z: keep the part's print orientation."""
    r = d / 2
    a = math.radians(angle)
    s, c = math.sin(a), math.cos(a)  # roof tangent to the circle at (+-r c, r s); tip at r / s
    tri = Polygon((-r * c, r * s), (0, r / s), (r * c, r * s), (0, 0), align=None)
    if roof == "flat":
        tri = tri & Rectangle(2 * r, r, align=(Align.CENTER, Align.MIN))
    elif roof != "teardrop":
        raise ValueError("roof: 'teardrop' or 'flat'")
    prof = Rot(90, 0, 0) * extrude(tri, length / 2, both=True)
    return Rot(90, 0, 0) * Cylinder(r, length) + prof


def demo_teardrop_hole() -> Part:
    p = Box(30, 12, 16, align=BED)
    p -= Pos(-7, 0, 8) * teardrop_hole(5.0, 20)
    p -= Pos(7, 0, 8) * teardrop_hole(5.0, 20, roof="flat")
    return p


def screw_hole(size: str = "M3", depth: float = 10.0, head: str = "counterbore", hole_comp: float = 0.0,
               head_depth: float | None = None) -> Part:
    """A vertical screw clearance hole (ISO 273 normal) with a counterbore for a socket head
    (ISO 4762; head d + 1 mm, head height + 0.4 mm deep) or a 90-degree countersink (ISO 10642),
    sized from bd_warehouse's fastener tables (the SCREW table without it).
    Opens on Z=0, goes down `depth`. head: "counterbore", "countersink" or "none". Open the head
    side upward in print orientation; on the bed side the counterbore floor is a ceiling (print a
    sacrificial bridge, BP-O5, or turn the part)."""
    s = _screw(size)
    hole = Cylinder((s["clearance"] + hole_comp) / 2, depth, align=TOP)
    if head == "counterbore":
        hd = head_depth if head_depth is not None else s["head_h"] + 0.4
        hole += Cylinder((s["head_d"] + 1.0 + hole_comp) / 2, hd, align=TOP)
    elif head == "countersink":
        r_top = (s["csk_d"] + 0.4 + hole_comp) / 2
        r_bot = (s["clearance"] + hole_comp) / 2
        hole += _cone(r_top, r_bot)
    elif head != "none":
        raise ValueError("head: 'counterbore', 'countersink' or 'none'")
    return hole


def _cone(r_top: float, r_bot: float) -> Part:
    """A 90-degree countersink cone from Z=0 (radius r_top) down to radius r_bot."""
    h = r_top - r_bot
    return Pos(0, 0, -h) * Cone(r_bot, r_top, h, align=BED)


def demo_screw_hole() -> Part:
    p = Box(36, 16, 10, align=BED)
    p -= Pos(-9, 0, 10) * screw_hole("M3", 12, "counterbore")
    p -= Pos(9, 0, 10) * screw_hole("M3", 12, "countersink")
    return p


def _mount_sizes(shaft_d, head_d, plate_t, travel, head_depth, clearance, hole_comp, size, min_lip):
    """Resolve mount diameters and reject a cutter that cannot retain the specified head."""
    if shaft_d is None or head_d is None:
        if size is None:
            raise ValueError("supply shaft_d and head_d, or a supported screw size")
        screw = _screw(size)
        shaft_d = screw["clearance"] if shaft_d is None else shaft_d
        head_d = screw["head_d"] if head_d is None else head_d
    values = (shaft_d, head_d, plate_t, travel, head_depth, clearance, hole_comp, min_lip)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("mount dimensions must be finite")
    if min(shaft_d, head_d, plate_t) <= 0 or travel < 0:
        raise ValueError("diameters and plate_t must be positive; travel must be nonnegative")
    if min(head_depth, clearance, min_lip) < 0:
        raise ValueError("head_depth, clearance and min_lip must be nonnegative")
    shaft = shaft_d + 2 * clearance + hole_comp
    head = head_d + 2 * clearance + hole_comp
    if shaft <= 0 or head <= 0 or head_d <= shaft:
        raise ValueError("head_d must exceed the compensated shaft opening to retain the head")
    if head < head_d:
        raise ValueError("compensated entry/recess must still admit head_d")
    if head_depth >= plate_t or plate_t - head_depth < min_lip:
        raise ValueError("head_depth leaves insufficient retaining lip; increase plate_t or reduce head_depth")
    return shaft, head


def _mount_capsule(diameter: float, travel: float, depth: float) -> Part:
    """A round-ended cutter from Y=0 to Y=travel, opening on Z=0 into -Z."""
    cutter = Cylinder(diameter / 2, depth, align=TOP)
    if travel:
        cutter += Pos(0, travel, 0) * Cylinder(diameter / 2, depth, align=TOP)
        cutter += Pos(0, travel / 2, 0) * Box(diameter, travel, depth, align=TOP)
    return cutter


def mounting_slot(shaft_d: float | None = None, head_d: float | None = None, plate_t: float = 5.0,
                  travel: float = 10.0, head_depth: float = 0.0, clearance: float = 0.2,
                  hole_comp: float = 0.0, size: str | None = "M3", min_lip: float = 0.0) -> Part:
    """An adjustable screw slot: shaft centers travel from (0, 0) to (0, travel) along +Y.
    Subtract at the insertion face Z=0; the cutter ends at -plate_t. Diameters gain
    2 x clearance (per side) and hole_comp (total) once. Omitted diameters use the size's
    ISO 273 normal clearance and ISO 4762 head via _screw, already fitted before this extra
    allowance. Explicit shaft_d is a base opening diameter; head_d is the actual head diameter.
    head_depth=0 leaves the head proud beyond -plate_t. Otherwise a head-sized cavity opens
    on the OPPOSITE face (-plate_t), leaving plate_t-head_depth of lip at the insertion face.
    Set min_lip to the project's required thickness; zero only rejects a vanished lip and
    implies no strength rating. Insert this screw axially before tightening; no head entry."""
    shaft, head = _mount_sizes(shaft_d, head_d, plate_t, travel, head_depth, clearance,
                              hole_comp, size, min_lip)
    cutter = _mount_capsule(shaft, travel, plate_t)
    if head_depth:
        cutter += Pos(0, 0, -plate_t + head_depth) * _mount_capsule(head, travel, head_depth)
    return cutter


def keyhole_mount(shaft_d: float | None = None, head_d: float | None = None, plate_t: float = 5.0,
                  travel: float = 10.0, head_depth: float = 0.0, clearance: float = 0.2,
                  hole_comp: float = 0.0, size: str | None = "M3", min_lip: float = 0.0) -> Part:
    """A keyhole cutter with head entry at (0, 0) and retained shaft center at (0, travel).
    Opens on Z=0 through -plate_t; screw moves +Y relative to the plate after insertion.
    Dimensions, allowances and opposite-face head recess follow mounting_slot. The recess
    spans the ENTIRE head travel, not only its retained endpoint. Travel must separate the
    retained head from the entry; the recipe checks that a full head cannot pass there.
    Rotate around Z to choose the sliding direction; a hanging plate moves opposite the
    screw's relative travel. Flat plates/light enclosure mounts only; no load rating."""
    shaft, head = _mount_sizes(shaft_d, head_d, plate_t, travel, head_depth, clearance,
                              hole_comp, size, min_lip)
    actual_head = _screw(size)["head_d"] if head_d is None else head_d
    # Compare the head/entry arcs where they meet the narrow slot sides. A head can
    # still escape if the entry plus the narrow slot exposes its entire cross-section.
    escape_travel = math.sqrt((head / 2) ** 2 - (shaft / 2) ** 2) - math.sqrt(
        (actual_head / 2) ** 2 - (shaft / 2) ** 2)
    if travel <= escape_travel:
        raise ValueError("travel must move the head clear of the entry to retain it")
    cutter = mounting_slot(shaft_d, head_d, plate_t, travel, head_depth, clearance,
                           hole_comp, size, min_lip)
    return cutter + Cylinder(head / 2, plate_t, align=TOP)


def demo_mounting_slot() -> Part:
    # Computational fixture, not a physically validated bundled example.
    return Box(18, 26, 5, align=BED) - Pos(0, -5, 5) * mounting_slot()


def demo_keyhole_mount() -> Part:
    # Two-hole fit coupon; 30 mm spacing is recipe-defined, not a fastener standard.
    plate = Box(50, 30, 5, align=BED)
    for x in (-15, 15):
        plate -= Pos(x, -5, 5) * keyhole_mount(head_depth=3.4, min_lip=1.6)
    return plate


def nut_trap(size: str = "M3", depth: float | None = None, screw_depth: float = 10.0, clearance: float = 0.1,
             hole_comp: float = 0.0) -> Part:
    """A captive hex nut pocket (ISO 4032 across flats + 2 x clearance; 0.1 per side, BP-T7) with
    the screw clearance hole below it. Opens on Z=0 and goes down: the nut drops in from the top.
    depth: default nut height + 0.3. Flats are parallel to X."""
    s = _screw(size)
    depth = depth if depth is not None else s["nut_h"] + 0.3
    hexagon = RegularPolygon((s["nut_af"] + 2 * clearance + hole_comp) / 2, 6, major_radius=False)
    pocket = Pos(0, 0, -depth) * extrude(hexagon, depth)
    return pocket + Cylinder((s["clearance"] + hole_comp) / 2, depth + screw_depth, align=TOP)


def demo_nut_trap() -> Part:
    p = Box(16, 16, 10, align=BED)
    return p - Pos(0, 0, 10) * nut_trap("M3", screw_depth=12)


def magnet_pocket(d: float, h: float, fit: float = 0.05, hole_comp: float = 0.0, extra_depth: float = 0.1) -> Part:
    """A round magnet pocket: diameter d + 2 x fit (per side; the user's press_fit, BP-F1) plus
    HOLE_COMP, depth h + extra_depth so the magnet sits flush or just below. Opens on Z=0, goes
    down. A press fit holds without glue; with glue use the clearance fit instead."""
    return Cylinder((d + 2 * fit + hole_comp) / 2, h + extra_depth, align=TOP)


def demo_magnet_pocket() -> Part:
    return Box(20, 20, 6, align=BED) - Pos(0, 0, 6) * magnet_pocket(10, 3)


def demo_pcb_standoff() -> Part:
    # Digital geometry fixture, based on the already printed esp_ir_blaster workflow.
    # Board measurements here are illustrative, not a physically validated new example.
    base = box_shell(48, 36, 12, wall=2, floor=2)
    for x, y in ((-13, -7), (12, -7), (-10, 8)):
        base += Pos(x, y, 2) * pcb_standoff(5, 7, 2.5, 4, flare=1, flare_h=1)
    return base


# ---------------------------------------------------------------------------------------------
# Snap fits and hinges


def snap_strain(deflection: float, thickness: float, length: float, taper: float = 0.5) -> float:
    """Peak strain of a rectangular cantilever snap arm deflected `deflection` at the tip (Bayer
    snap-fit guide): 1.5 y h / L^2 for a constant section, 1.09 y h / L^2 tapered to half the
    root thickness at the tip; linear in between. The formula holds for L/h > ~5-10. An estimate."""
    k = 1.09 + (1.5 - 1.09) * (taper - 0.5) / 0.5
    return k * deflection * thickness / length ** 2


def snap_length(deflection: float, thickness: float, strain: float, taper: float = 0.5) -> float:
    """The shortest arm whose strain stays at `strain` (snap_strain solved for L)."""
    k = 1.09 + (1.5 - 1.09) * (taper - 0.5) / 0.5
    return math.sqrt(k * deflection * thickness / strain)


def snap_arm(length: float = 14.0, thickness: float = 1.6, width: float = 6.0, hook: float = 1.0,
             taper: float = 0.5, lead_in: float = 30.0, base: float = 4.0) -> Part:
    """A cantilever snap arm lying flat (it bends in XY, along the layers, BP-N1), tapered from
    `thickness` at the root to taper x thickness at the tip (BP-N3), with a hook of height
    `hook` (= the deflection) on +Y, a lead-in ramp at `lead_in` degrees and a square catch, and
    a root fillet of 0.5 x thickness (BP-N2) into a base block `base` long. Root at X=0, arm
    along +X, `width` tall in Z from the bed. Size it with snap_strain/snap_length."""
    t, tt = thickness, thickness * taper
    hook_len = max(hook / math.tan(math.radians(lead_in)) + 0.8, 1.5)
    x_catch = length - hook_len
    ty = tt + (t - tt) * (1 - x_catch / length)  # arm thickness at the catch
    pts = [(-base, -t * 1.5), (0, -t * 1.5), (0, -t / 2), (length, -tt / 2), (length, tt / 2),
           (x_catch + 0.8, tt / 2 + hook), (x_catch, ty / 2 + hook), (x_catch, ty / 2), (0, t / 2), (0, t * 1.5),
           (-base, t * 1.5)]
    face = make_face(Polygon(*pts, align=None).edges())
    roots = [v for v in face.vertices() if abs(v.X) < 1e-6 and abs(abs(v.Y) - t / 2) < 1e-6]
    face = fillet(roots, 0.5 * t)
    return extrude(face, width)


def demo_snap_arm() -> Part:
    return snap_arm()


def living_hinge(leaf: float = 15.0, leaf_t: float = 2.0, gap: float = 3.0, thickness: float = 0.5,
                 width: float = 12.0) -> tuple[Part, tuple]:
    """Two leaves joined by a thin web `thickness` thick (0.4-0.6 mm, at least two lines, BP-N7)
    and `gap` long. Built standing: the hinge width runs along Z so the extrusion lines run across
    the web (BP-N9). Returns (part, ignore box) where the box is for ThinFeature(ignore=[box]):
    the web is thin on purpose. Print it in PP, nylon or TPU (BP-N8); not PLA or ABS."""
    a = Pos(-(gap / 2 + leaf / 2), 0, 0) * Box(leaf, leaf_t, width, align=BED)
    b = Pos(gap / 2 + leaf / 2, 0, 0) * Box(leaf, leaf_t, width, align=BED)
    web = Pos(0, -leaf_t / 2 + thickness / 2, 0) * Box(gap + 0.2, thickness, width, align=BED)
    box = ((0.0, -leaf_t / 2 + thickness / 2, width / 2), (gap + 1.0, leaf_t, width + 1.0))
    return a + b + web, box


def demo_living_hinge() -> Part:
    return living_hinge()[0]


def pip_hinge(length: float = 30.0, knuckle_d: float = 10.0, pin_d: float = 3.0, leaf: float = 12.0,
              leaf_t: float = 2.0, knuckles: int = 3, clearance: float = 0.3) -> Part:
    """A print-in-place hinge lying flat: two leaves (-Y and +Y) on the bed, knuckles along X
    alternating between them, the axis horizontal at the knuckle center. Every gap is at least
    `clearance` (the user's pip_clearance, 0.3 default, BP-F3). The pin (on leaf A) has a 45-degree
    pointed underside and the bore in leaf B's knuckles a 45-degree pointed roof, so nothing
    overhangs; the bore is round at the pin's swept radius, so the pin still turns. Knuckles are
    flat-bottomed (D-shaped) so they stand on the bed. Opens about 90 degrees up from flat."""
    rk, rp, c = knuckle_d / 2, pin_d / 2, clearance
    roof = rk - (rp * math.sqrt(2) + c) * math.sqrt(2)  # material over the bore's pointed roof
    if roof < 1.2:
        raise ValueError(f"pip_hinge: {roof:.2f} mm over the bore; make knuckle_d at least "
                         f"{2 * ((rp * math.sqrt(2) + c) * math.sqrt(2) + 1.2):.1f} or pin_d smaller")
    seg = (length - (knuckles - 1) * c) / knuckles
    zc = rk  # axis height: the knuckles' flat bottoms on the bed
    xs = [-length / 2 + i * (seg + c) for i in range(knuckles)]

    def knuckle(x0):  # D-shaped: round top, flat bottom
        return (Pos(x0 + seg / 2, 0, zc) * Rot(0, 90, 0) * Cylinder(rk, seg)
                + Pos(x0 + seg / 2, 0, 0) * Box(seg, 2 * rk, zc, align=BED))

    def tie(x0, side):  # joins a knuckle to its leaf across the leaf's gap
        return Pos(x0 + seg / 2, side * (rk + c) / 2, 0) * Box(seg, rk + c + 0.02, leaf_t, align=BED)

    a = Pos(0, -(rk + c + leaf / 2), 0) * Box(length, leaf, leaf_t, align=BED)
    b = Pos(0, rk + c + leaf / 2, 0) * Box(length, leaf, leaf_t, align=BED)
    for i, x0 in enumerate(xs):
        if i % 2 == 0:
            a += knuckle(x0) + tie(x0, -1)
        else:
            b += knuckle(x0) + tie(x0, 1)
    # the pin (leaf A): round, with a 45-degree point downward; it sweeps a circle of rp * sqrt(2)
    k = rp / math.sqrt(2)
    point = Plane.YZ * make_face(Polygon((-k, -k), (0, -rp * math.sqrt(2)), (k, -k), (0, 0), align=None).edges())
    pin = Pos(0, 0, zc) * (Rot(0, 90, 0) * Cylinder(rp, length) + extrude(point, length / 2, both=True))
    bore = Pos(0, 0, zc) * Rot(0, 0, 90) * teardrop_hole(2 * (rp * math.sqrt(2) + c), length + 2)
    return Part(Compound([*(a + pin).solids(), *(b - bore).solids()]).wrapped)


def demo_pip_hinge() -> Part:
    return pip_hinge()


# ---------------------------------------------------------------------------------------------
# Boxes and lids


def lid_with_lip(outer_w: float, outer_l: float, wall: float = 2.0, top_t: float = 2.0, lip_h: float = 4.0,
                 clearance: float = 0.2, lip_t: float | None = None, corner_r: float = 0.0) -> Part:
    """A lid for a box `outer_w` x `outer_l` with walls `wall` thick: a plate top_t thick and a
    lip lip_h tall that fits inside the walls with `clearance` per side (the user's clearance:
    sliding fit, BP-F1, F4). Printed top face down: the plate on the bed, the lip pointing up.
    corner_r: the box's inside corner radius (the lip follows it)."""
    lip_t = lip_t if lip_t is not None else wall
    p = Box(outer_w, outer_l, top_t, align=BED)
    iw, il = outer_w - 2 * (wall + clearance), outer_l - 2 * (wall + clearance)
    lip = Box(iw, il, lip_h, align=BED) - Box(iw - 2 * lip_t, il - 2 * lip_t, lip_h, align=BED)
    if corner_r > clearance:
        lip = fillet(lip.edges().filter_by(Axis.Z), corner_r - clearance) if corner_r - clearance < lip_t else lip
    return p + Pos(0, 0, top_t) * lip


def box_shell(outer_w: float, outer_l: float, height: float, wall: float = 2.0, floor: float = 2.0) -> Part:
    """An open box for lid_with_lip (the matching base), floor on the bed."""
    return Box(outer_w, outer_l, height, align=BED) - Pos(0, 0, floor) * Box(outer_w - 2 * wall, outer_l - 2 * wall, height, align=BED)


def demo_lid_with_lip() -> Part:
    return lid_with_lip(50, 35)


# ---------------------------------------------------------------------------------------------
# Text


def text_label(text: str, size: float = 6.0, depth: float = 0.6, font: str = "", bold: bool = True) -> Part:
    """Text as a solid from Z=0 up `depth`, centered on the origin. Emboss: part += Pos(x, y, top)
    * text_label(...). Deboss: part -= Pos(x, y, top - depth) * text_label(..., depth=depth + 1).
    Minimums (BP-X1..X3): characters >= 5 mm (3.5 possible), strokes >= 2 line widths (~0.9 mm at
    0.4 mm nozzle: a bold sans-serif at 5 mm and up has that), depth >= 0.5 mm and a multiple of
    the layer height (0.6 = 3 x 0.2). Put text on top (XY) faces. font: a system font name;
    "" uses build123d's default."""
    kw = {"font": font} if font else {}
    sk = Text(text, size, font_style=FontStyle.BOLD if bold else FontStyle.REGULAR, align=(Align.CENTER, Align.CENTER), **kw)
    return extrude(sk, depth)


def demo_text_label() -> Part:
    p = Box(40, 26, 4, align=BED)
    p += Pos(0, 6, 4) * text_label("UP", size=8, depth=0.6)
    p -= Pos(0, -6, 4 - 0.6) * text_label("OK", size=8, depth=1.6)
    return p


# ---------------------------------------------------------------------------------------------
# Bed edges


def bed_chamfer(part: Part, size: float = 0.5) -> Part:
    """Chamfer every edge on the bed (Z=0) by `size` at 45 degrees, holes included, by cutting a
    ring rather than chamfering edges: it works after fillets and on any outline (an edge chamfer
    fails where a fillet meets the bed). The flare of the first layer (elephant's foot) hides in
    the chamfer instead of growing the part (BP-O2, B1; 0.4-0.6 mm typical, B2, provisional)."""
    bottom = [f for f in part.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z) < 1e-6
              and f.normal_at().Z < -0.99]
    if not bottom:
        raise ValueError("bed_chamfer: the part has no flat face on Z=0")
    out = part
    for f in bottom:
        f = Face(f.wrapped)
        inset = offset(f, -size)
        keep = extrude(inset, size, taper=-45)
        ring = extrude(f, size) - keep
        out = out - ring
    return out


def demo_bed_chamfer() -> Part:
    p = Box(30, 20, 8, align=BED)
    p = fillet(p.edges().filter_by(Axis.Z), 3)
    p -= Cylinder(3, 20)
    return bed_chamfer(p, 0.5)


# ---------------------------------------------------------------------------------------------
# Cables and zip ties


def zip_tie_slot(length: float, tie_w: float = 4.8, tie_t: float = 1.4, clearance: float = 0.4) -> Part:
    """A rectangular tunnel along X for a zip tie (width tie_w, thickness tie_t, + clearance per
    side), centered on the origin, with a flat bridged roof: keep tie_w + 2 x clearance under
    max_bridge (10 mm, BP-O3) and leave >= 1.2 mm of roof above it (BP-W2). Sink it below the top
    face of a boss; the tie goes in one end and out the other."""
    return Box(length, tie_w + 2 * clearance, tie_t + 2 * clearance)


def cable_slot(d: float, length: float, clearance: float = 0.3) -> Part:
    """An open-top channel along X for a cable of diameter d: round bottom, straight sides, opens
    on Z=0 and goes down d + clearance. Upward-facing, so it prints without support."""
    r = d / 2 + clearance
    return (Pos(0, 0, -r) * Rot(0, 90, 0) * Cylinder(r, length)) + Box(length, 2 * r, r, align=TOP)


def demo_zip_tie_slot() -> Part:
    p = Box(30, 16, 10, align=BED)
    p -= Pos(0, 0, 10 - 1.6 - 1.1) * zip_tie_slot(40)
    p += Pos(0, 0, 10) * Box(30, 10, 6, align=BED)  # a ridge on top for the cable channel
    p -= Pos(0, 0, 16) * cable_slot(4, 40)
    return p


# ---------------------------------------------------------------------------------------------
# Ribs and gussets


def gusset(height: float, depth: float, thickness: float = 2.0) -> Part:
    """A triangular gusset in the XZ plane for an inside corner between a floor (Z=0, extending to
    +X) and a wall (X=0, extending up): legs `depth` along X and `height` along Z, `thickness`
    along Y, centered on Y=0. As thick as the walls it joins, >= 1.5 mm (BP-R4)."""
    tri = Polygon((0, 0), (depth, 0), (0, height), align=None)
    return Plane.XZ * extrude(tri, thickness / 2, both=True)


def ribs(span: float, height: float, count: int = 3, thickness: float = 2.0, pitch: float | None = None) -> Part:
    """`count` parallel ribs along X, `span` long and `height` tall from Z=0, spaced `pitch`
    apart in Y (default 10 x thickness), centered. To stiffen a large flat wall or plate and
    against warping (BP-R5); as thick as the wall (BP-R4)."""
    pitch = pitch if pitch is not None else 10 * thickness
    out = Part()
    for i in range(count):
        out += Pos(0, (i - (count - 1) / 2) * pitch, 0) * Box(span, thickness, height, align=BED)
    return out


def demo_gusset() -> Part:
    t = 3.0
    p = Pos(15, 0, 0) * Box(30, 20, t, align=BED)  # floor
    p += Pos(t / 2, 0, 0) * Box(t, 20, 30, align=BED)  # wall
    for y in (-6, 6):
        p += Pos(t, y, t) * gusset(15, 15, 2.0)
    p += Pos(15 + t / 2, 0, t) * ribs(30 - t, 2.0, count=2, thickness=2.0, pitch=16) & Box(60, 60, 60, align=BED)
    return p


# ---------------------------------------------------------------------------------------------
# Organic shapes: sections along a curve, blends, a flat base


def _frames(path: Edge | Wire, us, x_dir=(0, 0, 1), samples: int = 64) -> list[Plane]:
    """Planes perpendicular to `path` at the length fractions `us` (0 = start, 1 = end). Their x
    axes are carried along the path without twisting (parallel transport), starting from x_dir
    (made perpendicular to the path's start; Z by default, X when the path starts along Z)."""
    t = (path % 0).normalized()
    x = Vector(x_dir)
    if abs(x.normalized().dot(t)) > 0.95:
        x = Vector(1, 0, 0) if abs(t.X) < 0.95 else Vector(0, 1, 0)
    x = (x - t * x.dot(t)).normalized()
    out = {}
    for u in sorted({i / samples for i in range(samples + 1)} | {float(u) for u in us}):
        t = (path % u).normalized()
        x = (x - t * x.dot(t)).normalized()  # short steps: projecting the last x keeps it twist-free
        out[u] = Plane(origin=path @ u, x_dir=x, z_dir=t)
    return [out[float(u)] for u in us]


def _sections(sections) -> list[tuple[float, Face | Sketch]]:
    """(length fraction, profile) pairs from what spine_loft and tapered_sweep take: (u, profile)
    pairs, or bare profiles spread evenly from 0 to 1. A number is a circle of that diameter; 0 is a
    point (None), allowed first or last."""
    items = list(sections)
    if len(items) < 2:
        raise ValueError("give at least two sections")
    if not all(isinstance(s, tuple) for s in items):
        items = [(i / (len(items) - 1), s) for i, s in enumerate(items)]
    out = []
    for u, s in items:
        if not 0 <= u <= 1:
            raise ValueError(f"section position {u}: a fraction of the spine's length, 0 to 1")
        out.append((float(u), (Circle(s / 2) if s > 0 else None) if isinstance(s, (int, float)) else s))
    out.sort(key=lambda p: p[0])
    if any(s is None for _, s in out[1:-1]):
        raise ValueError("a point (0) can only be the first or the last section")
    return out


def spine_loft(spine: Edge | Wire, sections, x_dir=(0, 0, 1)) -> Part:
    """A body lofted through cross-sections placed perpendicular to a curved `spine` (a Spline or
    Bezier through the middle of the shape): fruit, bodies, limbs, handles that bulge. sections:
    (u, profile) pairs, u the fraction of the spine's length (0 = start, 1 = end); a profile is a
    Face or Sketch drawn on XY around the origin (its +X lands on the section's x axis, which
    follows x_dir down the spine without twisting), or a number: a circle of that diameter. The
    surface passes through every section and is smooth between them: give each section a
    different size or shape so the body varies along its length. A 0 first or last closes the
    end to a point; a few small sections close together before it make a blunt, rounded end (a
    fruit's tip) instead of a flat cap with a sharp rim. Sections closer than their own size on
    a tight bend make the loft fold: space them out or ease the bend."""
    items = _sections(sections)
    planes = _frames(spine, [u for u, _ in items], x_dir)
    return loft([Vertex(pl.origin) if s is None else pl * s for pl, (_, s) in zip(planes, items)])


def tapered_sweep(path: Edge | Wire, sections, x_dir=(0, 0, 1)) -> Part:
    """A profile swept along `path` while it changes size or shape (build123d's
    sweep(multisection=True)): stems, tentacles, horns, tails, curled handles. Unlike spine_loft
    the body follows the path exactly, so use it for long thin shapes with few sections. sections
    as in spine_loft: (u, profile) pairs or bare profiles spread evenly; a number is a circle of
    that diameter. Give the first and last at u = 0 and 1. A tip should keep a little size (a
    0.8 mm end is two lines wide and prints; a point does not)."""
    items = _sections(sections)
    if items[0][0] != 0 or items[-1][0] != 1:
        raise ValueError("tapered_sweep: the first section at u = 0 and the last at u = 1")
    if items[0][1] is None or items[-1][1] is None:
        raise ValueError("tapered_sweep: a sweep cannot end in a point; give the tip a small size, or use spine_loft")
    planes = _frames(path, [u for u, _ in items], x_dir)
    return sweep([pl * s for pl, (_, s) in zip(planes, items)], path=path, multisection=True)


def _outline(face: Face, plane: Plane, n: int) -> list[Vector]:
    """n points evenly spaced along the outer outline of `face`, in `plane`'s local coordinates,
    counter-clockwise, starting at the outline's own start (its seam, where a loft joins it)."""
    w = face.outer_wire()
    pts = [plane.to_local_coords(w @ (i / (4 * n))) for i in range(4 * n)]
    area = sum(a.X * b.Y - b.X * a.Y for a, b in zip(pts, pts[1:] + pts[:1]))
    if area < 0:
        pts = pts[:1] + pts[:0:-1]
    # resample by length so both ends of a blend pair up point for point
    seg = [(b - a).length for a, b in zip(pts, pts[1:] + pts[:1])]
    total, out, acc, j = sum(seg), [], 0.0, 0
    for i in range(n):
        target = total * i / n
        while acc + seg[j] < target:
            acc += seg[j]
            j += 1
        f = (target - acc) / seg[j] if seg[j] else 0.0
        a, b = pts[j], pts[(j + 1) % len(pts)]
        out.append(a + (b - a) * f)
    return out


def _cut_face(body: Part, plane: Plane) -> Face:
    """The face a split left on `plane` (the largest, if the plane cut the body in several places)."""
    on = [f for f in body.faces() if f.geom_type == GeomType.PLANE and abs(f.normal_at().dot(plane.z_dir)) > 0.999
          and abs((f.center() - plane.origin).dot(plane.z_dir)) < 1e-4]
    if not on:
        raise ValueError(f"organic_blend: the plane at {tuple(round(v, 2) for v in plane.origin)} misses the body")
    return max(on, key=lambda f: f.area)


def organic_blend(a: Part, b: Part, at_a: Plane, at_b: Plane, bulge: float = 0.0, steps: int = 4,
                  points: int = 48) -> Part:
    """Join two bodies with a smooth lofted collar instead of a fillet (OpenCascade fillets on
    curved bodies often fail): a body to a stem, a head to a neck, a limb to a torso. at_a and
    at_b are planes across each body where the collar starts; each one's +Z points out of its
    body, towards the other. Each body is cut there (the part beyond its plane is dropped), and a
    loft through `steps` sections joins the two cuts. The collar leaves each cut along its plane's
    +Z and goes on tapering or swelling as the body did there, so the join has no crease. bulge:
    how much the middle of the collar swells (0.2 = 20 %; negative pinches it, like a neck).
    Returns one solid. The cut outlines should be roughly convex (round or soft-cornered)."""
    a_cut = split(a, at_a, keep=Keep.BOTTOM)
    b_cut = split(b, at_b, keep=Keep.BOTTOM)
    p0, p1 = at_a.origin, at_b.origin
    gap = (p1 - p0).length
    if gap < 1e-6:
        raise ValueError("organic_blend: at_a and at_b are at the same point")
    t0, t1 = at_a.z_dir * gap, -at_b.z_dir * gap  # Hermite end tangents: leave a, enter b
    path = Bezier(p0, p0 + t0 / 3, p1 - t1 / 3, p1)
    us = [i / (steps + 1) for i in range(steps + 2)]
    planes = _frames(path, us, at_a.x_dir)
    start, end = planes[0], planes[-1]
    fa, fb = _cut_face(a_cut, at_a), _cut_face(b_cut, at_b)
    pa, pb = _outline(fa, start, points), _outline(fb, end, points)
    # how each body's outline changes per mm towards the collar, from a section `h` behind its cut,
    # scaled to the collar's length: the Hermite tangents of the outline
    h = min(1.0, gap / 4)
    back_a = section(a_cut, Plane(origin=p0 - at_a.z_dir * h, x_dir=start.x_dir, z_dir=start.z_dir)).faces()
    back_b = section(b_cut, Plane(origin=p1 - at_b.z_dir * h, x_dir=end.x_dir, z_dir=end.z_dir)).faces()
    ma = mb = [Vector(0, 0, 0)] * points
    if back_a:
        qa = _outline(max(back_a, key=lambda f: f.area), Plane(origin=start.origin - start.z_dir * h, x_dir=start.x_dir,
                                                               z_dir=start.z_dir), points)
        ma = [(p - q) * (path.length / h) for p, q in zip(pa, qa)]
    if back_b:
        qb = _outline(max(back_b, key=lambda f: f.area), Plane(origin=end.origin + end.z_dir * h, x_dir=end.x_dir,
                                                               z_dir=end.z_dir), points)
        mb = [(q - p) * (path.length / h) for p, q in zip(pb, qb)]
    faces = [fa]
    for u, pl in zip(us[1:-1], planes[1:-1]):
        h00, h10, h01, h11 = 2 * u**3 - 3 * u**2 + 1, u**3 - 2 * u**2 + u, 3 * u**2 - 2 * u**3, u**3 - u**2
        s = 1 + bulge * math.sin(math.pi * u)
        pts = [p * h00 + m * h10 + q * h01 + n * h11 for p, m, q, n in zip(pa, ma, pb, mb)]
        cx, cy = sum(p.X for p in pts) / points, sum(p.Y for p in pts) / points
        loc = [pl.from_local_coords(((p.X - cx) * s + cx, (p.Y - cy) * s + cy, 0)) for p in pts]
        faces.append(Face(Wire([Spline(*loc, periodic=True)])))
    collar = loft(faces + [fb])
    # The collar meets each body tangentially along the cut's edge: a boolean fuse spends tens of
    # seconds on that near-tangent intersection. The collar was lofted from the cuts' own edges,
    # so sewing the faces into one shell (dropping the cut faces) joins them exactly, at once.
    caps = [_cut_face(collar, at_a), _cut_face(collar, Plane(origin=p1, z_dir=-at_b.z_dir))]
    skin = [f for f in a_cut.faces() if not f.is_same(fa)] + [f for f in b_cut.faces() if not f.is_same(fb)]
    skin += [f for f in collar.faces() if not any(f.is_same(c) for c in caps)]
    try:
        out = Solid(Shell(skin))
        if out.is_valid and out.volume > 0 and abs(out.volume - (a_cut.volume + collar.volume + b_cut.volume)) < 1e-3 * out.volume:
            return Part(Compound([out]).wrapped)
    except Exception:  # noqa: BLE001 - the faces did not close into one solid: fuse them instead
        pass
    return a_cut + collar + b_cut


def flat_base(part: Part, depth: float) -> Part:
    """Cut a flat underside `depth` mm above the part's lowest point and put it on Z=0, so a
    rounded part stands and sticks to the bed. A deeper cut gives more bed contact and less
    overhang around it; about a quarter of the section's height is a good start on a round body.
    Check the contact with section(Z=0.1): a strip under ~5 mm wide may need a brim."""
    if depth <= 0:
        raise ValueError("flat_base: depth must be > 0")
    from b123d_print.render import bbox  # the true lowest point: OCCT's box of a cut lofted body can be lower

    z = bbox(part).min.Z + depth
    kept = split(part, Plane.XY.offset(z), keep=Keep.TOP)
    return Pos(0, 0, -z) * kept


def demo_spine_loft() -> Part:
    """An eggplant lying on its side: five sections of different sizes along a spine that bends
    up at the stem end, cut flat underneath so it stands."""
    spine = Spline((0, 0, 0), (40, 0, -3), (70, 0, 8), tangents=((1, 0, -0.1), (1, 0, 0.6)))
    body = spine_loft(spine, [(0, 10), (0.2, 26), (0.5, 30), (0.85, 18), (1, 8)])
    return flat_base(body, 4)


def demo_tapered_sweep() -> Part:
    """A horn standing on its base, curling over: 18 mm across at the bed, 2 mm at the tip."""
    path = Spline((0, 0, 0), (4, 0, 20), (18, 0, 36), tangents=((0, 0, 1), (1, 0, 0.6)))
    return tapered_sweep(path, [(0, 18), (0.6, 9), (1, 2)])


def demo_organic_blend() -> Part:
    """A stem joined to a round body by a collar that flows into both: no fillet, no corner."""
    body = flat_base(scale(Sphere(15), (1.0, 1.0, 0.8)), 3)
    stem = Pos(0, 0, 30) * Cylinder(3, 14)
    top = body.bounding_box().max.Z
    return organic_blend(body, stem, Plane.XY.offset(top - 3), Plane(origin=(0, 0, 26), z_dir=(0, 0, -1)), bulge=0.1)


def demo_flat_base() -> Part:
    """An egg on its side, cut flat 2.5 mm up so it stands."""
    return flat_base(scale(Sphere(15), (1.3, 1.0, 1.0)), 2.5)


# ---------------------------------------------------------------------------------------------
# Registry


@dataclass
class Recipe:
    name: str
    title: str
    functions: list
    demo: object
    notes: str
    sources: list = field(default_factory=list)
    helpers: list = field(default_factory=list)
    imports: str = ""

    def summary(self) -> str:
        return inspect.getdoc(self.functions[0]).split("\n")[0]

    def text(self) -> str:
        """The recipe as Markdown: what, how to use it, the code, the printing notes, sources."""
        sig = "\n".join(f"{f.__name__}{inspect.signature(f)}" for f in self.functions)
        code = "\n\n\n".join(inspect.getsource(f) for f in self.helpers + self.functions)
        if self.imports:
            code = self.imports + "\n\n" + code
        demo = inspect.getsource(self.demo)
        src = "\n".join(f"- {s}" for s in self.sources)
        return (f"# {self.title} (`{self.name}`)\n\n{self.summary()}\n\n"
                f"```python\nfrom b123d_print.recipes import {', '.join(f.__name__ for f in self.functions)}\n\n{sig}\n```\n\n"
                f"## Example (tested: built and checked in the test suite)\n\n```python\n{demo}```\n\n"
                f"## Printing notes\n\n{self.notes.strip()}\n\n## Sources\n\n{src}\n\n"
                f"## Code\n\nImport it, or copy it into the part script and keep its numbers as named Dims fields.\n\n"
                f"```python\n{code}```\n")


_MOUNT_IMPORTS = ("import math\nfrom build123d import Align, Box, Cylinder, Part, Pos\n"
                  "from b123d_print.recipes import _screw\n\n"
                  "TOP = (Align.CENTER, Align.CENTER, Align.MAX)\n"
                  "BED = (Align.CENTER, Align.CENTER, Align.MIN)")


RECIPES = {r.name: r for r in [
    Recipe("teardrop_hole", "Teardrop / flat-roof horizontal hole", [teardrop_hole], demo_teardrop_hole, """
- A horizontal round hole sags at the top and prints small; a 45-degree pointed roof prints without
  support, the flat roof is a short bridge (BP-H3). The pointed roof leaves a little extra room above
  a pin or screw, which is harmless.
- Add the user's HOLE_COMP_H (horizontal holes) to `d` (BP-H4).
- Or turn the part so the hole is vertical: vertical holes are the most accurate.
""", ["[BP-H3](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) teardrop roof at 45 degrees",
      "[BP-H4](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) horizontal and vertical holes need separate compensation"]),
    Recipe("screw_hole", "Counterbore and countersink", [screw_hole], demo_screw_hole, """
- Sizes from bd_warehouse's fastener tables (`SocketHeadCapScrew`, `CounterSunkScrew`), else the
  table in the recipe: clearance hole ISO 273 normal (M3: 3.4 mm); counterbore: the ISO 4762 head
  diameter + 1 mm, head height + 0.4 mm deep; countersink: 90 degrees to the ISO 10642 head
  diameter + 0.4 mm. bd_warehouse's own `ClearanceHole` / `CounterBoreHole` take no hole
  compensation; this recipe adds `hole_comp` once.
- Add HOLE_COMP to the diameters (`hole_comp=d.HOLE_COMP`).
- Open the head upward in print orientation. A counterbore opening downward is a ceiling: print it
  over a one-layer sacrificial bridge and drill it out (BP-O5, provisional) or turn the part.
- Screws into plastic: give the boss 3-4 perimeters (BP-T8).
""", ["ISO 273 (clearance holes), ISO 4762 (socket head cap screws), ISO 10642 (countersunk heads), via bd_warehouse.fastener",
      "[BP-O5, BP-T8](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"]),
    Recipe("keyhole_mount", "Keyhole wall mount", [keyhole_mount], demo_keyhole_mount, """
- Entry center is (0, 0), retained center is (0, travel); screw travel is +Y relative to the
  plate, so a hanging plate moves -Y. Rotate the cutter around Z for another direction.
- `clearance` is per side; `hole_comp` is total diameter compensation applied once (BP-F4,
  BP-H1). Omitted diameters use `_screw(size)` ISO socket-head and normal clearance tables;
  this optional clearance is extra to that table's shaft clearance. Measure other screw heads.
- `head_depth` cuts a continuous head cavity on the opposite face at -plate_t, leaving
  plate_t-head_depth of retaining lip by Z=0. Check head height, radial head overlap and outer
  edge walls yourself; min_lip only checks axial lip thickness, not strength (BP-W3).
- Print cavity upward when possible. Facing it down creates a roof/bridge under the lip;
  inspect sections and run overhang/bridge checks (BP-O3). No certified load rating.
- See the recipe guide's two-hole coupon and section images. CAD tests pass, but a maintainer
  must print and try the stated screw before calling the fixture a validated example.
""", ["[ISO 273](https://www.iso.org/standard/4183.html) clearance holes; not keyhole layout",
      "[ISO 4762](https://www.iso.org/standard/34460.html) socket head cap screws via bd_warehouse",
      "[BP-F4, H1, W3, O3](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"],
           helpers=[_mount_sizes, _mount_capsule, mounting_slot], imports=_MOUNT_IMPORTS),
    Recipe("mounting_slot", "Adjustable screw mounting slot", [mounting_slot], demo_mounting_slot, """
- Shaft center moves from (0, 0) to (0, travel), +Y; total length includes the round ends.
  Screw must be inserted axially before tightening: the head cannot enter through this slot.
- Same dimensions and allowances as keyhole_mount: clearance per side, hole_comp total once
  (BP-F4, BP-H1), and optional continuous head cavity on the opposite face (-plate_t).
- Leave a project-appropriate retaining lip, radial head overlap and material to plate edges;
  `min_lip` verifies only the axial remainder. Verify with a section and Wall checks (BP-W3).
- Tightening retains an adjusted position; this is not a captive slide or a load-rated mount.
""", ["[ISO 273](https://www.iso.org/standard/4183.html) clearance holes",
      "[ISO 4762](https://www.iso.org/standard/34460.html) socket head cap screws via bd_warehouse",
      "[BP-F4, H1, W3](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"],
           helpers=[_mount_sizes, _mount_capsule], imports=_MOUNT_IMPORTS),
    Recipe("nut_trap", "Hex nut trap", [nut_trap], demo_nut_trap, """
- Across flats + 0.2 mm total (0.1 per side) holds an ISO 4032 nut captive (BP-T7; up to +0.3 on a
  loose printer). M3 nut: 5.5 mm across flats, 2.4 mm thick.
- The pocket opens upward so the nut drops in. A pocket opening downward needs the sacrificial
  bridge (BP-O5) or a pause to drop the nut in and print over it.
""", ["[BP-T7](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) nut pocket: across flats + 0.2 mm",
      "ISO 4032 (hex nuts)"]),
    Recipe("magnet_pocket", "Magnet pocket", [magnet_pocket], demo_magnet_pocket, """
- Press fit: the user's `press_fit` per side (0.05 default, measured with the fit coupon; BP-F1).
  Glued magnets: use `clearance` instead. Add HOLE_COMP.
- Depth = magnet height + ~0.1 so the magnet sits flush. Mind the polarity when pressing a pair.
- Fully embedded magnets: pause at the layer above the pocket, drop the magnet in, resume; the
  layer above is then a bridge over the magnet.
""", ["[BP-F1](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) clearance ladder: press 0-0.15 per side"]),
    Recipe("pcb_standoff", "PCB standoffs and board stand-ins",
           [pcb_standoff, pcb_board, pcb_mounting_pattern], demo_pcb_standoff, """
- Explicit pilot diameter/depth: no default screw size. Pass `hole_comp=d.HOLE_COMP` once.
  Remaining floor is `height - pilot_depth`; a through spacer uses `pilot_depth=height`.
- Reuse bd_warehouse screw `clearance_hole_diameters["Normal"]` for clearance spacers.
  Metal tap drills are not plastic pilot recommendations. Inserts use their maker's hole size.
- `flare` is extra base radius; `flare_h` is its height. Print base down, pilot upright and open
  at the top; use 3-4 or more perimeters at bosses (BP-T8). Check walls with `Wall`.
- `pcb_board` is a rectangular stand-in: center datum, X=width, Y=length, underside Z=0;
  arbitrary hole centers are (x, y), viewed from +Z. Board holes get no printer compensation.
- `pcb_mounting_pattern` has only `raspberry_pi_zero_v1_2` (65 x 30, 58 x 23 hole spacing,
  diameter 2.75) and `raspberry_pi_pico_rev3` (21 x 51, 11.4 x 47 spacing, diameter 2.1).
  Their records include exact model, datum and manufacturer source; supply measured thickness.
  No universal ESP32 pattern and no inferred component keep-outs or purchased standoff sizes.
- Add board and underside components to `assembly(d)` labelled "(stand-in)"; use existing
  `Mates`/`check_fit`, `Wall` and `Template.slice` tools. Resolve interference explicitly.
- The existing printed esp_ir_blaster is the reference. This recipe's demo is a digital fixture,
  not a new physically validated print. Print a fit-test slice before a full enclosure.
""", ["[BP-H1, H2, T2, T6, T8](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) compensation, pilots and bosses",
      "[Raspberry Pi Zero drawing RPI-ZERO-V1_2](https://datasheets.raspberrypi.com/rpizero/raspberry-pi-zero-mechanical-drawing.pdf)",
      "[Raspberry Pi Pico datasheet, mechanical specification Rev3](https://datasheets.raspberrypi.com/pico/pico-datasheet.pdf)",
      "[Pico product brief, physical specifications](https://datasheets.raspberrypi.com/pico/pico-product-brief.pdf)"],
           imports="import math\nfrom build123d import Align, Box, Cone, Cylinder, Part, Pos\n"
                   "from b123d_print.pcb import PCBPattern, PCB_PATTERNS\n"
                   "from b123d_print.recipes import box_shell\n\n"
                   "BED = (Align.CENTER, Align.CENTER, Align.MIN)"),
    Recipe("snap_arm", "Snap-fit cantilever", [snap_arm, snap_strain, snap_length], demo_snap_arm, """
- Lie the arm flat so it bends along the layers (BP-N1); across the layers the allowable strain
  halves.
- Taper to about half the thickness at the tip (BP-N3); root fillet >= 0.5 x thickness (BP-N2).
- Size it: strain = 1.09 y h / L^2 (tapered to half) or 1.5 y h / L^2 (constant), y = hook height
  (deflection), h = root thickness, L = arm length (Bayer snap-fit guide). Keep it under the
  material's allowable strain: PLA 4-8 %, ABS 7 %, nylon 4-15 % (BP-N4, provisional: one source).
  `snap_length(y, h, 0.04)` gives the shortest arm for PLA at 4 %. Say it is an estimate.
- L/t of ~8-10 for PLA, ~5-8 for PETG (BP-N5, provisional). Mating clearance 0.1-0.5 (BP-N6).
""", ["Bayer MaterialScience, *Snap-Fit Joints for Plastics: A Design Guide* (cantilever strain formulas)",
      "[BP-N1..N6](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) (Fictiv, Hubs, Formlabs, Sovol)"]),
    Recipe("living_hinge", "Living hinge", [living_hinge], demo_living_hinge, """
- Web 0.4-0.6 mm thick, at least two layers or lines (BP-N7). It is thinner than min_wall on
  purpose: pass the returned box to `ThinFeature(part, ignore=[box])`.
- Material: PP (best: thousands of cycles), nylon or TPU (BP-N8). PETG survives tens to hundreds of
  bends when the web runs across the lines; PLA and ABS crack within a few bends, so use a
  pin hinge (pip_hinge) instead.
- Build the hinge width along Z so the lines run across the web (BP-N9); this recipe stands the
  part up that way.
- Flex it a few times while still warm; nylon lasts longer after a boiling-water soak (BP-N10,
  provisional).
""", ["[BP-N7..N10](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) (Hubs, FacFox, 3ERP, MH)"]),
    Recipe("pip_hinge", "Print-in-place hinge", [pip_hinge], demo_pip_hinge, """
- Every gap is the print-in-place clearance: the user's `pip_clearance` (0.3 default, BP-F3; 0.2 on a
  tuned printer). The automatic gap check fails below it.
- The pin's underside and the bore's roof are 45-degree points, so it prints with no support; the
  pin turns inside the bore's swept circle.
- Break it free by flexing the leaves gently after printing; first-layer squish (elephant's foot)
  fuses knuckles that touch the bed: keep the slicer's elephant-foot compensation on.
- Check the swing, not just the flat print: split the two solids in `assembly(d)` and declare
  `Motion("leaf B", axis_point=(0, 0, knuckle_d / 2), axis_dir=(1, 0, 0), start_deg=0,
  end_deg=180, min_clearance=0.2)` in `checks(d)` (the `flip_hinge` example).
""", ["[BP-F3](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) print-in-place: 0.2-0.3 mm per side",
      "[BP-H3, BP-O1](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) 45-degree roofs"]),
    Recipe("lid_with_lip", "Lid with a lip and clearance", [lid_with_lip, box_shell], demo_lid_with_lip, """
- The lip sits inside the box walls with `clearance` per side: the user's `clearance` for a lid
  that slides on, `press_fit` for one that stays (BP-F1, F4). Say per side in the report.
- Print the lid top face down; the lip rises from the plate with no overhang.
- Put the lid and box in `assembly(d)` and run `check_fit`: it reports the lip gap and lines up
  the screw holes, if any.
""", ["[BP-F1, F2, F4](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) clearances, per side"]),
    Recipe("text_label", "Embossed and debossed text", [text_label], demo_text_label, """
- Depth or height >= 0.5 mm and a multiple of the layer height (0.6 = 3 layers at 0.2) (BP-X1).
- Strokes >= 2 line widths (~0.9 mm at a 0.4 mm nozzle; BP-X2): bold sans-serif, characters
  >= 5 mm tall (3.5 mm possible) (BP-X3). The thin-feature check measures the strokes.
- Text on top (XY) faces prints cleanly; on walls it needs bigger characters.
- Fonts: build123d's default font is always there; a named font must exist on the machine that
  builds the part (the server, for a remote server).
""", ["[BP-X1..X3](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"]),
    Recipe("bed_chamfer", "Fillet-safe chamfer on bed edges", [bed_chamfer], demo_bed_chamfer, """
- A chamfer, not a fillet, on edges that touch the bed: a fillet's lowest band is a flat overhang
  that flares (BP-O2). The bed-edge check warns on fillets there.
- 0.4-0.6 mm is typical (BP-B2, provisional); it hides the first-layer flare (elephant's foot)
  so the part's bottom edge stays at size. Keep the CAD nominal otherwise (BP-B1).
- It cuts a 45-degree ring along the bottom outline, so it works on filleted corners and holes,
  where an edge chamfer fails. Apply it last.
""", ["[BP-O2, B1, B2](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"]),
    Recipe("zip_tie_slot", "Cable and zip-tie slots", [zip_tie_slot, cable_slot], demo_zip_tie_slot, """
- Zip tie tunnel: the tie (4.8 x 1.4 mm for a common 4.8 mm tie) + 0.4 mm per side; its flat roof
  is a bridge, so keep the width under max_bridge (BP-O3) and >= 1.2 mm of material above (BP-W2).
- Cable channel: diameter + 0.3 mm per side; open on top, round bottom: no support.
""", ["[BP-O3, BP-W2](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"]),
    Recipe("gusset", "Ribs and gussets", [gusset, ribs], demo_gusset, """
- As thick as the wall they join, >= 1.5 mm (BP-R4): FDM has no sink marks, so the molding habit
  of thinning ribs does not apply.
- Ribs stiffen large flat walls and fight warping (BP-R5); a gusset in the inside corner of a
  bracket takes the bending load off the corner. Fillet the corner too (BP-R1).
- No source gives rib height or spacing for FDM; the defaults here are a starting point.
""", ["[BP-R1, R4, R5](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/)"]),
    Recipe("spine_loft", "Body lofted along a curved spine", [spine_loft], demo_spine_loft, """
- For natural shapes (fruit, bodies, limbs, horns that bulge): model them from cross-sections along
  a curve, not from boxes, cylinders and spheres fused together (DS-O1). Give each section its own
  size and shape so the body changes along its length (DS-O2).
- Five to ten sections are usually enough: each one adds faces and build time, and sections closer
  than their own size on a tight bend fold the loft. A 0 at the start or end closes it to a point;
  a few small sections close together before that make a blunt, rounded tip (DS-O3).
- Lay the long curve along the layers (a long thin part across them breaks on a layer line,
  BP-S4), cut a flat base under it (flat_base) and expect tree supports under the curves that
  overhang past 45 degrees (BP-O1, DS-O5, DS-H2).
""", ["[DS-O1, O2, O3, O5](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/) organic design style",
      "[BP-O1, S4](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) overhangs, strength across the layers",
      "[build123d loft](https://build123d.readthedocs.io/en/latest/operations.html) (OpenCascade BRepOffsetAPI_ThruSections)"],
           helpers=[_frames, _sections]),
    Recipe("tapered_sweep", "Tapered sweep along a path", [tapered_sweep], demo_tapered_sweep, """
- Stems, tentacles, horns, tails, curled handles: one profile changing size or shape along a
  path that the body follows exactly (build123d `sweep(multisection=True)`).
- Keep the tip printable: about 0.8 mm across or more (two lines at a 0.4 mm nozzle, BP-W1); a
  sweep cannot end in a point (spine_loft can). A curl that leans more than 45 deg from vertical
  needs supports (BP-O1), or lay it down (DS-O5). A tall thin horn standing up is weak across the
  layers and wobbles: 5 x its diameter at most (BP-W6), or lay it down.
""", ["[DS-O1, O5](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/) organic design style",
      "[BP-W1, W6, O1](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) thin features, posts, overhangs",
      "[build123d sweep](https://build123d.readthedocs.io/en/latest/operations.html) (OpenCascade BRepOffsetAPI_MakePipeShell)"],
           helpers=[_frames, _sections]),
    Recipe("organic_blend", "Smooth lofted join of two bodies", [organic_blend], demo_organic_blend, """
- Joins a stem to a body, a head to a neck, a limb to a torso with a lofted collar that carries on
  each body's own taper, instead of a fillet: OpenCascade fillets on lofted and swept bodies often
  fail, and a sharp corner where two bodies meet reads as two parts stuck together (DS-O3).
- Put each plane a little way into its body, across it, +Z pointing out towards the other body;
  the collar spans the gap. Wider gaps give gentler joins. `bulge` swells (+) or pinches (-) its
  middle.
- The faces are sewn, not fused, so it is quick; it falls back to a boolean fuse when they do not
  close.
- A thin stem joined to a body is weak across the layers: lay it in the layers where it can
  (BP-S4), and keep the collar at least as thick as the stem.
""", ["[DS-O3](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/) blended joins",
      "[BP-S4](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) strength across the layers",
      "[build123d loft](https://build123d.readthedocs.io/en/latest/operations.html), OpenCascade BRepBuilderAPI_Sewing"],
           helpers=[_frames, _outline, _cut_face]),
    Recipe("flat_base", "Flat base cut under a rounded part", [flat_base], demo_flat_base, """
- A rounded part rests on a point or a line; cut a flat underside so it stands and the first layer
  holds (DS-O5). About a quarter of the section's height is a good start; deeper gives more contact
  and less overhang at the edge of the cut.
- Check the contact with a section at Z = 0.1: a strip under ~5 mm wide may need a brim. The rim of
  the cut is a rounded bed edge (the bed-edge check warns): the slicer's elephant-foot compensation
  helps.
- The part comes back on Z=0. OpenCascade's own bounding box of a cut lofted body still reaches
  under the bed; b123d-print measures it from the faces (render.bbox), so the checks see it on the
  bed.
""", ["[DS-O5](https://kd5ryn.github.io/b123d-print/DESIGN_GUIDE/) print organic parts with a flat base",
      "[BP-B1, B2](https://kd5ryn.github.io/b123d-print/BEST_PRACTICES/) first layer and bed edges"]),
]}


def index() -> str:
    """Markdown list of every recipe."""
    rows = "\n".join(f"| `{r.name}` | {r.title} | {', '.join(f'`{f.__name__}`' for f in r.functions)} |"
                     for r in RECIPES.values())
    return ("# Recipes\n\nTested build123d functions for common printable features. "
            "`from b123d_print.recipes import <function>` in a part script, or read one "
            "(b123d-print://recipes/<name>, or the recipe tool) for its code, notes and sources.\n\n"
            "| Recipe | What | Functions |\n| --- | --- | --- |\n" + rows + "\n")


def get(name: str) -> Recipe:
    key = (name or "").strip().lower().replace("-", "_")
    if key in RECIPES:
        return RECIPES[key]
    for r in RECIPES.values():  # a function name works too
        if key in {f.__name__ for f in r.functions}:
            return r
    raise KeyError(f"no recipe {name!r}; recipes: {', '.join(RECIPES)}")
