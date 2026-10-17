"""Outdoor case for a Tuya PIR motion sensor (LQ-Y09, battery), reset end down.

A back plate stays on the wall; a hooded cover slides down over it.
- The plate's side edges are dovetails: the cover can only slide up/down, not pull forward.
  The plate stands proud of the wall so the cover's sides stop short of it.
- Detents: a small bump on each dovetail face clicks into a dimple in the cover when it is fully
  down. Pull up firmly to remove (print 1: gravity alone is not enough).
- The cover has a floor; the sensor stands on it. A foot on the plate's bottom sits in a notch in
  that floor (square in square), so the bottom cannot swing out or sideways.
- One slot in the floor under the sensor's two vents (also reaches the reset button) drains water.
- Battery door slides off the sensor's back: slide the cover up (the sensor comes with it), take
  the sensor out.
- The PIR dome pokes through a chamfered hole; the cover's top runs forward as a rain brim.

Status: "arch" cover + straight back plate printed and in use (support-free, fits well);
flat-top cover also printed and good; tilt15 back plate in test.

Variants: straight (flat on the wall) and tilt15 (a wedge behind the plate tips it 15 deg down).
Wall screws always go in square to the wall.

Axes (plate coordinates): X across the sensor, Y out from the plate's back (Y=0), Z up.
Print: back plate on its wall face; cover upside down on its top (brim on the bed). PETG.
"""

from dataclasses import dataclass
from math import cos, radians, sin, tan

from build123d import (
    Align,
    Axis,
    Box,
    Cone,
    Cylinder,
    Mode,
    Part,
    Plane,
    Polygon,
    Pos,
    Rot,
    Sphere,
    extrude,
    fillet,
)

from b123d_print import Overhang, Probe, View, Wall, hole_comp

MIN = Align.MIN
MAX = Align.MAX
CEN = Align.CENTER


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm."""

    # --- Sensor (calipers) ---
    SENSOR_L: float = 69.6  # Z, reset end down
    SENSOR_W: float = 24.5  # X
    SENSOR_D: float = 19.1  # Y, back to front, without the dome
    DOME_D: float = 18.6
    DOME_OUT: float = 8.0  # dome sticks out of the front face
    DOME_Z: float = 35.5  # dome hole center above the floor; print 3 (34.5) sat ~1 mm high both
    #                       ways round, so moved up 1.0 to match the printed part
    SENSOR_CLEAR: float = 0.6  # per side, width and depth (print 2: 0.4 was just barely)
    SENSOR_L_CLEAR: float = 1.0  # total, on the length (print 2: 0.4 was too tight)

    # --- Back plate (dovetail) ---
    PLATE_T: float = 5.0
    RAIL: float = 2.5  # plate's front face reaches this far past the sensor cavity each side
    DOVETAIL_ANGLE: float = 30.0  # deg from square; also the print overhang angle
    GROOVE_CLEAR: float = 0.2  # per face (print 2: 0.25 a hair loose)
    PROUD: float = 1.0  # cover's sides stop this far short of the wall
    FOOT_D: float = 6.0  # foot at the plate's bottom, out from the plate face (Y)
    FOOT_W: float = 16.0  # (X)
    FOOT_CLEAR: float = 0.25
    MOUNT_HOLE_D: float = 4.0  # #6 / M3.5 wood screw (target printed size)
    MOUNT_CSK_D: float = 8.5  # countersink, head flush under the sensor
    MOUNT_HOLES_Z: tuple = (14.0, 60.0)  # above the plate bottom
    MOUNT_HEAD_SINK: float = 0.3
    HOLE_COMP: float = hole_comp(__file__)  # your printer's, from b123d_print config
    TILT: float = 0.0  # deg the case tips down from the wall (wedge behind the plate)
    WEDGE_LIP_T: float = 1.0  # tilt: flat top of the dam bump along the wedge top's front edge
    #                           (keeps water out of the cover joint); height = TOP_T, flush with the
    #                           flat cover; back face slopes 45 deg (no overhang when printed)
    WEDGE_SIDE_SLOPE: float = 5.0  # deg, wedge top falls to both sides so water runs off the ends

    # --- Detents ---
    DETENT_R: float = 2.0  # bump sphere radius
    DETENT_H: float = 0.75  # bump height off the dovetail face (interference = H - GROOVE_CLEAR);
    #                         detent test print: 0.75 about right (0.5 did little)
    DETENT_ZS: tuple = (20.0, 52.0)  # bumps per side, above the plate bottom
    DIMPLE_CLEAR: float = 0.15

    # --- Cover ---
    WALL: float = 2.5  # front wall
    FLOOR_T: float = 3.0
    SIDE_OUTSIDE_GROOVE: float = 2.0
    TOP_T: float = 3.0
    ROOF: str = "flat"  # "flat": flat top + brim, prints top-down with supports under the floor
    #                     "arch": side-to-side arch roof + hood, prints on its floor, no supports
    ROOF_T: float = 2.5  # arch: roof thickness at the peak
    BRIM: float = 12.0
    EDGE_FILLET: float = 2.0
    DOME_HOLE_CLEAR: float = 0.6  # per side
    DOME_CHAMFER: float = 2.0
    VENT_SLOT_W: float = 18.0  # X, under both vents (and the reset button)
    VENT_SLOT_Y0: float = 9.5  # from the sensor's back face
    VENT_SLOT_Y1: float = 15.5

    # --- Derived ---
    @property
    def IN_W(self):  # cavity width at the sensor
        return self.SENSOR_W + 2 * self.SENSOR_CLEAR

    @property
    def PLATE_WF(self):  # plate width at its front face
        return self.IN_W + 2 * self.RAIL

    @property
    def DT_UNDERCUT(self):
        return self.PLATE_T * tan(radians(self.DOVETAIL_ANGLE))

    @property
    def PLATE_WB(self):  # plate width at its back face
        return self.PLATE_WF - 2 * self.DT_UNDERCUT

    @property
    def SENSOR_Y0(self):
        return self.PLATE_T

    @property
    def FRONT_IN_Y(self):
        return self.PLATE_T + self.SENSOR_D + 2 * self.SENSOR_CLEAR

    @property
    def FRONT_OUT_Y(self):
        return self.FRONT_IN_Y + self.WALL

    @property
    def SENSOR_Z0(self):
        return self.FLOOR_T

    @property
    def PLATE_H(self):  # plate top = where the cover stops
        return self.FLOOR_T + self.SENSOR_L + self.SENSOR_L_CLEAR

    @property
    def OUT_W(self):
        return self.PLATE_WF + 2 * (self.GROOVE_CLEAR + self.SIDE_OUTSIDE_GROOVE)

    @property
    def COVER_H(self):
        return self.PLATE_H + self.TOP_T


VARIANTS = {
    "": {},  # straight
    "tilt15": dict(TILT=15.0),
    # Support-free cover: printed on its floor the floor is a true 3.0 (print 3 measured 3.2 over
    # supports), so the dome hole comes down 0.2 to stay centered.
    "arch": dict(ROOF="arch", DOME_Z=35.3),
}


def dovetail(d: Dims, grow: float, h: float) -> Part:
    """Plate cross-section (trapezoid, wide at the front) grown by `grow` per face, extruded in Z.
    The slanted faces are extended 2 mm behind the plate so the cut runs clean."""
    ta = tan(radians(d.DOVETAIL_ANGLE))
    g = grow / cos(radians(d.DOVETAIL_ANGLE))  # horizontal offset that moves a slanted face `grow`
    y0, y1 = -2.0, d.PLATE_T + grow

    def x(y):  # right-hand slanted face, grown
        return d.PLATE_WB / 2 + y * ta + g

    sec = Polygon((-x(y0), y0), (x(y0), y0), (x(y1), y1), (-x(y1), y1), align=None)
    return extrude(Plane.XY * sec, h)


def detent_points(d: Dims):
    """Bump centers and outward normals on the two slanted faces (plate coordinates)."""
    a = radians(d.DOVETAIL_ANGLE)
    out = []
    for sx in (-1, 1):
        xm = sx * (d.PLATE_WB + d.PLATE_WF) / 4
        n = (sx * cos(a), -sin(a))  # outward normal of that face (out and toward the wall)
        out.append(((xm, d.PLATE_T / 2), n))
    return out


def detents(d: Dims, zs, extra_r: float = 0.0) -> Part:
    """Detent spheres on both slanted faces at each Z (bumps; extra_r > 0 for dimples)."""
    c = d.DETENT_R - d.DETENT_H
    s = None
    for z in zs:
        for (x, y), (nx, ny) in detent_points(d):
            # Rot keeps the sphere's seam off the face (OCC boolean is invalid otherwise)
            b = Pos(x - nx * c, y - ny * c, z) * Rot(0, 90, 0) * Sphere(d.DETENT_R + extra_r)
            s = b if s is None else s + b
    return s


def back_plate(d: Dims) -> Part:
    """Plate in plate coordinates."""
    wb, wf, t = d.PLATE_WB / 2, d.PLATE_WF / 2, d.PLATE_T
    p = extrude(Plane.XY * Polygon((-wb, 0), (wb, 0), (wf, t), (-wf, t), align=None), d.PLATE_H)
    p += Pos(0, t, 0) * Box(d.FOOT_W, d.FOOT_D, d.FLOOR_T, align=(CEN, MIN, MIN))  # foot
    p += detents(d, d.DETENT_ZS)  # bumps
    p = p & Box(200, t + d.FOOT_D, 300, align=(CEN, MIN, MIN))  # bumps stay off the wall
    if d.TILT > 0:  # wedge behind the plate, full cover width, thin at the bottom
        h = d.PLATE_H
        depth = h * tan(radians(d.TILT))
        wedge = Polygon((0, 0), (0, h), (-depth, h), align=None)
        p += extrude(Plane.YZ * wedge, amount=d.OUT_W / 2, both=True)
        # top falls to both sides (low ridge down the middle, wall to plate)
        half = d.OUT_W / 2
        drop = half * tan(radians(d.WEDGE_SIDE_SLOPE))
        for sx in (-1, 1):
            cut = [(sx * 0.0, h + 0.01), (sx * (half + 1), h - drop - drop / half), (sx * (half + 1), h + 5), (0, h + 5)]
            p -= prism_y(cut, -depth - 1, 0)
        # dam bump along the front edge, flush with the flat cover's top. Back face slopes 45 deg
        # so it prints without overhang (printed on the wall face; ~30 deg from vertical there)
        lip_top = h + (d.COVER_H - d.PLATE_H)
        z0 = h - drop - 0.5
        t = d.WEDGE_LIP_T  # flat on top
        bump = Polygon((0, z0), (0, lip_top), (-t, lip_top), (-t - (lip_top - z0), z0), align=None)
        p += extrude(Plane.YZ * bump, amount=d.OUT_W / 2, both=True)
    return p


def arch_profile(half_w: float, z0: float, rise: float, below: float = 1.0, n: int = 32) -> list:
    """Rounded arch in XZ from (-half_w, z0) to (half_w, z0) through (0, z0 + rise): circular arc."""
    r = (half_w**2 + rise**2) / (2 * rise)
    zc = z0 + rise - r
    pts = [(-half_w, z0 - below)]
    from math import asin
    a0 = asin(half_w / r)
    for i in range(n + 1):
        a = -a0 + 2 * a0 * i / n
        pts.append((r * sin(a), zc + r * cos(a)))
    pts.append((half_w, z0 - below))
    return pts


def prism_y(pts: list, y_from: float, y_to: float) -> Part:
    """Extrude an XZ profile (x, z points) along +Y from y_from to y_to, whatever its winding."""
    face = Plane.XZ * Polygon(*pts, align=None)
    return Pos(0, y_from, 0) * extrude(face, amount=y_to - y_from, dir=(0, 1, 0))


def gable_profile(half_w: float, z0: float, below: float = 0.5) -> list:
    """Pointed arch at 45 deg (rise = half width): steepest-free shape that prints without support."""
    return [(-half_w, z0 - below), (half_w, z0 - below), (half_w, z0), (0, z0 + half_w), (-half_w, z0)]


def cover(d: Dims) -> Part:
    """Cover in plate coordinates (assembled position)."""
    y0 = d.PROUD
    if d.ROOF == "arch":
        # Side-to-side arch: water runs off both sides. Inside is a 45 deg pointed arch (prints with
        # no bridge or support); outside is a rounded arch ROOF_T above its peak. The roof runs on
        # past the front wall as a hood whose underside is the same pointed arch.
        c = Pos(0, y0, 0) * Box(d.OUT_W, d.FRONT_OUT_Y - y0, d.PLATE_H, align=(CEN, MIN, MIN))
        c = fillet(c.edges().filter_by(Axis.Z).filter_by(lambda e: e.center().Y > y0 + 1), radius=d.EDGE_FILLET)
        y_end = d.FRONT_OUT_Y + d.BRIM
        outer = arch_profile(d.OUT_W / 2, d.PLATE_H, d.IN_W / 2 + d.ROOF_T)
        c += prism_y(outer, y0, y_end)
        # hood underside: pointed tunnel past the front wall...
        c -= prism_y(gable_profile(d.IN_W / 2, d.PLATE_H, below=2), d.FRONT_OUT_Y, y_end + 1)
        # ...and its side legs trimmed at 45 deg from the front wall's top edge (no flat underside)
        f = d.FRONT_OUT_Y
        trim = Polygon((f, d.PLATE_H - 2), (y_end + 1, d.PLATE_H - 2), (y_end + 1, d.PLATE_H + y_end + 1 - f), (f, d.PLATE_H), align=None)
        c -= extrude(Plane.YZ * trim, amount=d.OUT_W, both=True)
    else:
        c = Pos(0, y0, 0) * Box(d.OUT_W, d.FRONT_OUT_Y - y0, d.COVER_H, align=(CEN, MIN, MIN))
        c = fillet(c.edges().filter_by(Axis.Z).filter_by(lambda e: e.center().Y > y0 + 1), radius=d.EDGE_FILLET)
        brim = Pos(0, d.FRONT_OUT_Y - 1, d.COVER_H) * Box(d.OUT_W, d.BRIM + 1, d.TOP_T, align=(CEN, MIN, MAX))
        brim = fillet(brim.edges().filter_by(Axis.Z).filter_by(lambda e: e.center().Y > d.FRONT_OUT_Y + 1), radius=3.0)
        c += brim
    # Sensor cavity above the floor
    c -= Pos(0, d.PLATE_T - 1, d.FLOOR_T) * Box(
        d.IN_W, d.FRONT_IN_Y - d.PLATE_T + 1, d.PLATE_H - d.FLOOR_T, align=(CEN, MIN, MIN)
    )  # stops under the top
    if d.ROOF == "arch":  # pointed ceiling over the sensor only; solid over the groove (plate stop)
        c -= prism_y(gable_profile(d.IN_W / 2, d.PLATE_H), d.PLATE_T, d.FRONT_IN_Y)

    # Dovetail groove, open at the bottom, closed at the top
    c -= Pos(0, 0, -1) * dovetail(d, d.GROOVE_CLEAR, d.PLATE_H + 1)
    # Foot notch through the floor (square in square)
    c -= Pos(0, d.PLATE_T - 1, -1) * Box(
        d.FOOT_W + 2 * d.FOOT_CLEAR, d.FOOT_D + d.FOOT_CLEAR + 1, d.FLOOR_T + 2, align=(CEN, MIN, MIN)
    )
    # Vent / drain slot
    c -= Pos(0, d.SENSOR_Y0 + d.SENSOR_CLEAR + d.VENT_SLOT_Y0, -1) * Box(
        d.VENT_SLOT_W, d.VENT_SLOT_Y1 - d.VENT_SLOT_Y0, d.FLOOR_T + 2, align=(CEN, MIN, MIN)
    )
    # Detent dimples (bump + a little clearance)
    c -= detents(d, d.DETENT_ZS, d.DIMPLE_CLEAR)
    # Dome hole, chamfered outward
    zd = d.SENSOR_Z0 + d.DOME_Z
    rh = d.DOME_D / 2 + d.DOME_HOLE_CLEAR
    c -= Pos(0, d.FRONT_IN_Y - 1, zd) * Rot(-90, 0, 0) * Cylinder(rh, d.WALL + 2, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)
    c -= Pos(0, d.FRONT_OUT_Y - d.DOME_CHAMFER, zd) * Rot(-90, 0, 0) * Cone(
        rh, rh + d.DOME_CHAMFER + 0.5, d.DOME_CHAMFER + 0.5, align=(CEN, CEN, MIN), mode=Mode.PRIVATE
    )
    return c


def to_wall(d: Dims, part: Part) -> Part:
    """Plate coordinates -> wall coordinates (wall at Y=0, tipped down by TILT)."""
    return Rot(-d.TILT, 0, 0) * part


def back_plate_on_wall(d: Dims) -> Part:
    """Back plate in wall coordinates, with wall-screw holes square to the wall."""
    p = to_wall(d, back_plate(d))
    th = radians(d.TILT)
    r = (d.MOUNT_HOLE_D + d.HOLE_COMP) / 2
    rc = (d.MOUNT_CSK_D + d.HOLE_COMP) / 2
    for z in d.MOUNT_HOLES_Z:
        yf = d.PLATE_T * cos(th) + z * sin(th)  # plate face at the hole, out from the wall
        zw = -d.PLATE_T * sin(th) + z * cos(th)
        y_cone = yf - d.MOUNT_HEAD_SINK - rc * tan(th)
        p -= Pos(0, -1, zw) * Rot(-90, 0, 0) * Cylinder(r, yf + 2, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)
        p -= Pos(0, y_cone, zw) * Rot(90, 0, 0) * Cone(rc, r, rc - r, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)
        p -= Pos(0, y_cone, zw) * Rot(-90, 0, 0) * Cylinder(rc, 30, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)
    return p


def sensor_dummy(d: Dims) -> Part:
    s = Pos(0, d.SENSOR_Y0 + d.SENSOR_CLEAR, d.SENSOR_Z0) * Box(
        d.SENSOR_W, d.SENSOR_D, d.SENSOR_L, align=(CEN, MIN, MIN)
    )
    y_face = d.SENSOR_Y0 + d.SENSOR_CLEAR + d.SENSOR_D
    s += Pos(0, y_face, d.SENSOR_Z0 + d.DOME_Z) * Rot(-90, 0, 0) * Cylinder(
        d.DOME_D / 2, d.DOME_OUT, align=(CEN, CEN, MIN)
    )
    return s


def cover_print(d: Dims) -> Part:
    if d.ROOF == "arch":
        return cover(d)  # on its floor, no supports
    return Pos(0, 0, d.COVER_H) * Rot(180, 0, 0) * cover(d)  # top down, brim on the bed


def build(d: Dims) -> dict[str, Part]:
    return {"backplate": Rot(90, 0, 0) * back_plate_on_wall(d), "cover": cover_print(d)}  # plate: wall face down


def assembly(d: Dims):
    return [
        (back_plate_on_wall(d), "#e0a030", "back plate"),
        (to_wall(d, cover(d)), "#3a6ea5", "cover"),
        (to_wall(d, sensor_dummy(d)), "#bbbbbb", "sensor (stand-in)"),
    ]


def views(d: Dims):
    v = [View("YZ", 0.0, "side section")]
    if d.TILT == 0:
        v += [View("XY", d.DETENT_ZS[0], "through the detents"), View("XY", d.FLOOR_T / 2, "through the floor")]
    return v


def checks(d: Dims):
    c = cover(d)  # plate coordinates, for the probes
    if d.ROOF == "arch":
        top = (0, (d.PLATE_T + d.FRONT_IN_Y) / 2, d.PLATE_H + d.IN_W / 2 + 1.0)  # above the inner peak
    else:
        top = (0, d.PLATE_T + 2, d.PLATE_H + (d.COVER_H - d.PLATE_H) / 2)
    # detent dimple in the groove's side wall, in the cover's print orientation
    (x, y), _ = detent_points(d)[1]
    z = d.DETENT_ZS[0]
    near = (x, y) if d.ROOF == "arch" else (x, -y)
    at = z if d.ROOF == "arch" else d.COVER_H - z
    return [
        Probe(c, top, (1, 1, 0.5), label="cover roof closed over the sensor"),
        Probe(c, (0, (d.PROUD + d.PLATE_T) / 2, d.PLATE_H + 0.3), (d.PLATE_WF * 0.6, 1, 0.5),
              label="cover stops on the plate's top edge"),
        # Wall around the dimple. Known and accepted: the dimple nearly breaks out through the
        # cover's back face (Y = PROUD), leaving a ~0.35 mm sliver that tapers to a feather edge
        # the slicer drops. It printed fine; the explicit limit keeps it from getting any worse.
        Wall("cover", "XY", at, near=near, radius=1.2, min=0.3, label="wall around the detent dimple"),
        # The arch cover must print without supports. Its flat ceilings are bridges (allowed);
        # min_area lets the 8 mm^2 top arc of the dome hole through, like any small round hole.
        Overhang("cover", fail=d.ROOF == "arch", min_area=10.0),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
