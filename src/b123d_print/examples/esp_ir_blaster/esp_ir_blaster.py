"""Box for the HiLetgo ESP8285 ESP-01M IR transceiver (IR TX on IO4, RX on IO14).

Board measured with calipers + photos (reference photos not included). Positions marked photo estimate
are +-1 mm.

Layout (assembled, Z up = the face that points at the equipment):
- Base: floor + 4 walls, board on two standoffs at its diagonal holes (M2.5). 5 V / GND wires
  come in through a hole in the -X wall next to the header corner, soldered to the header.
- Lid: screws on with 4 M3 screws into corner posts, so it can be reprinted if the LED or
  receiver positions move. The IR LED points up through a cone in the lid; the cone is wide so
  the beam is not clipped, and its narrow end holds the LED tip.
- IR receiver: lens at the +Y board edge, facing the +Y wall, behind a window.
- In use the floor (back) mounts flat to a wall with the lid facing the equipment. Two screw
  tabs stick out past the ±X walls, flush with the floor.
- Board: M3 screws into two flared standoffs at its diagonal holes, two small flared pads under
  the other corners (optional L-shaped locating lips, off by default).

Print: base on its floor; lid outer face down.
"""

from dataclasses import dataclass
from math import radians, tan

from build123d import (
    Align,
    Axis,
    Box,
    Cone,
    Cylinder,
    Mode,
    Part,
    Pos,
    RectangleRounded,
    Rot,
    chamfer,
    extrude,
    fillet,
    offset,
)

from b123d_print import View, Wall, hole_comp

MIN = Align.MIN
CEN = Align.CENTER


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm. Board positions are relative to the PCB center."""

    # --- Board (calipers unless marked; photo positions are +-1 mm) ---
    # X: plain edge (-X) -> module edge (+X).  Y: header edge (-Y) -> receiver edge (+Y).
    PCB_X: float = 23.1  # caliper
    PCB_Y: float = 23.2  # caliper
    PCB_T: float = 1.6  # NOMINAL (standard)
    MODULE_H: float = 15.0  # ESP-01M top above the PCB top (16.6 from the PCB bottom)
    MODULE_BELOW: float = 1.2  # module hangs this far below the PCB bottom; it does not reach the
    # corner standoff (print 1), so the standoff needs no notch - only the 4 mm height matters
    MODULE_W: float = 19.0  # along Y, photo estimate
    MODULE_Y: float = 0.6  # photo estimate
    MODULE_T: float = 4.0  # standing slab incl. pins, at the +X edge, photo estimate
    LED_X: float = -0.35  # caliper: LED side 8.7 from the plain edge -> center 11.2
    LED_Y: float = 0.6  # caliper: LED side 9.7 from the header edge -> center 12.2
    LED_D: float = 5.0  # 5 mm IR LED
    LED_TOP: float = 8.3  # dome top above the PCB top (9.9 from the PCB bottom, caliper)
    RX_X: float = 1.0  # photo: receiver center 12.6 from the plain edge
    RX_DEPTH: float = 4.5  # receiver body, lens flush with the receiver edge (leaned in by hand)
    RX_W: float = 6.5
    RX_TOP: float = 8.5  # photo estimate
    RX_LENS_Z: float = 5.3  # lens center above the PCB top, photo estimate
    HEADER_H: float = 6.6  # pin tips above the PCB top, photo estimate
    HOLE_EDGE: float = 2.0  # mounting hole centers in from both edges (caliper)
    PCB_HOLE_D: float = 2.7  # caliper; M3 screws fit (first print)
    PCB_SCREW_PILOT_D: float = 2.5  # M3 into the standoffs, same as the lid posts (target printed size)
    PCB_SCREW_FLOOR_LEFT: float = 1.0  # pilot runs down into the floor, leaving this much (M3 x 6 fits)

    # --- Box ---
    WALL: float = 3.0
    FLOOR_T: float = 3.0
    LID_T: float = 4.0
    INNER: float = 38.0  # square inside: board + room for wiring + corner posts
    OUTER_CORNER_R: float = 4.0
    LID_EDGE_FILLET: float = 1.5
    STANDOFF_H: float = 4.0  # board underside above the floor; module hangs 1.2 below
    STANDOFF_D: float = 6.5
    STANDOFF_FLARE: float = 2.0  # extra radius at the floor, tapering up (more meat)
    STANDOFF_FLARE_H: float = 2.0
    PAD_D: float = 3.5  # small support pads under the two corners without screws
    PAD_FLARE: float = 1.5
    PADS: tuple = ((6.0, 10.3), (-10.0, -7.0))  # clear of the module overhang, receiver and header leads
    CORNER_LIPS: bool = False  # L-lips at the plain-edge corners; off: too much (print 2)
    LIP_CLEAR: float = 0.3  # board locating lips: gap to the board edge
    CORNER_LIP_T: float = 1.5
    CORNER_LIP_ARM: float = 5.0  # arm length along each edge, from the corner
    CORNER_LIP_ABOVE: float = 1.5  # how far the lips rise above the PCB top
    TOP_CLEAR: float = 1.5  # above the module / header
    HOLE_COMP: float = hole_comp(__file__)  # your printer's, from b123d_print config
    FIT_CLEARANCE: float = 0.2  # lid lip in the walls, LED holder (per side)
    PART_CLEAR: float = 0.5  # pockets around board parts the box would otherwise touch

    # --- Lid screws (M3 into the base's corner posts) ---
    POST_D: float = 6.0
    POST_INSET: float = 3.0  # post center from the inside walls
    PILOT_D: float = 2.5
    SCREW_CLEAR_D: float = 3.4
    CBORE_D: float = 6.5  # pan heads below the lid face
    CBORE_DEPTH: float = 2.5
    LIP_H: float = 2.0
    LIP_W: float = 1.6

    # --- IR openings ---
    LED_HOLD: float = 2.0  # straight section that holds the LED tip
    LED_POS_TOL: float = 0.3  # extra per side: the LED position was hard to measure
    LED_INTO_HOLE: float = 1.0  # LED dome reaches this far into the holder
    LED_CONE_HALF_ANGLE: float = 25.0  # deg; typical 5 mm IR LED beam is +-15..20 deg
    CONE_WALL: float = 1.6
    RX_WINDOW_W: float = 9.0  # along X
    RX_WINDOW_H: float = 8.0  # along Z
    RX_WINDOW_R: float = 2.0

    # --- Power wires ---
    WIRE_HOLE_D: float = 4.5  # 2-core cable; NOMINAL
    WIRE_HOLE_Y: float = -8.0  # in the -X wall, near the header corner
    WIRE_HOLE_Z: float = 12.0  # above the floor's top

    # --- Screw tabs (wall mount): flush with the floor, sticking out past the ±X walls ---
    TABS: bool = True
    TAB_LEN: float = 10.0  # how far past the wall
    TAB_T: float = 3.5  # thickness (Z)
    TAB_W: float = 16.0  # width (Y)
    TAB_HOLE_D: float = 4.0  # #6 / M3.5 wood screw or M3 (target printed size)
    TAB_CORNER_R: float = 3.0

    # --- Derived ---
    @property
    def PCB_Z(self):  # PCB underside
        return self.FLOOR_T + self.STANDOFF_H

    @property
    def PCB_TOP(self):
        return self.PCB_Z + self.PCB_T

    @property
    def LID_INNER_Z(self):
        return self.PCB_TOP + max(self.MODULE_H, self.HEADER_H, self.RX_TOP) + self.TOP_CLEAR

    @property
    def LID_OUTER_Z(self):
        return self.LID_INNER_Z + self.LID_T

    @property
    def OUTER(self):
        return self.INNER + 2 * self.WALL

    @property
    def HOLES(self):  # header/module corner and receiver/plain corner
        hx, hy = self.PCB_X / 2 - self.HOLE_EDGE, self.PCB_Y / 2 - self.HOLE_EDGE
        return ((hx, -hy), (-hx, hy))

    @property
    def RX_Y(self):
        return self.PCB_Y / 2 - self.RX_DEPTH / 2

    @property
    def POSTS(self):
        c = self.INNER / 2 - self.POST_INSET
        return [(sx * c, sy * c) for sx in (-1, 1) for sy in (-1, 1)]

    @property
    def LED_HOLD_D(self):
        return self.LED_D + 2 * (self.FIT_CLEARANCE + self.LED_POS_TOL) + self.HOLE_COMP

    @property
    def LED_HOLD_Z0(self):  # bottom of the LED holder
        return self.PCB_TOP + self.LED_TOP - self.LED_INTO_HOLE

    @property
    def CONE_Z0(self):
        return self.LED_HOLD_Z0 + self.LED_HOLD

    @property
    def CONE_TOP_D(self):
        return self.LED_HOLD_D + 2 * (self.LID_OUTER_Z - self.CONE_Z0) * tan(radians(self.LED_CONE_HALF_ANGLE))


VARIANTS = {"": {}}


def base(d: Dims) -> Part:
    b = extrude(RectangleRounded(d.OUTER, d.OUTER, d.OUTER_CORNER_R), d.LID_INNER_Z)
    b = chamfer(b.edges().group_by(Axis.Z)[0], length=0.6)
    b -= Pos(0, 0, d.FLOOR_T) * extrude(
        RectangleRounded(d.INNER, d.INNER, max(d.OUTER_CORNER_R - d.WALL, 0.5)), d.LID_INNER_Z
    )
    post_h = d.LID_INNER_Z - d.FLOOR_T
    for x, y in d.POSTS:  # lid screw posts, filled solid back into the corner
        b += Pos(x, y, d.FLOOR_T) * Cylinder(d.POST_D / 2, post_h, align=(CEN, CEN, MIN))
        fill = d.INNER / 2 - abs(x) + 0.5  # post center to the inside wall, into the wall a bit
        b += Pos(x, y, d.FLOOR_T) * Box(
            fill, fill, post_h, align=(MIN if x > 0 else Align.MAX, MIN if y > 0 else Align.MAX, MIN)
        )
        b -= Pos(x, y, d.LID_INNER_Z) * Cylinder(
            (d.PILOT_D + d.HOLE_COMP) / 2, 10, align=(CEN, CEN, Align.MAX), mode=Mode.PRIVATE
        )
    def flared(x, y, dia, flare):  # post with a tapered skirt at the floor
        r = dia / 2
        return Pos(x, y, d.FLOOR_T) * Cylinder(r, d.STANDOFF_H, align=(CEN, CEN, MIN)) + Pos(
            x, y, d.FLOOR_T
        ) * Cone(r + flare, r, d.STANDOFF_FLARE_H, align=(CEN, CEN, MIN))

    for x, y in d.HOLES:  # board standoffs, M3
        b += flared(x, y, d.STANDOFF_D, d.STANDOFF_FLARE)
        b -= Pos(x, y, d.PCB_SCREW_FLOOR_LEFT) * Cylinder(
            (d.PCB_SCREW_PILOT_D + d.HOLE_COMP) / 2, 50, align=(CEN, CEN, MIN), mode=Mode.PRIVATE
        )
    for x, y in d.PADS:  # support pads, no screws
        b += flared(x, y, d.PAD_D, d.PAD_FLARE)

    # L-shaped lips at the two plain-edge (-X) corners, just outside the board, to locate it
    lip_h = d.PCB_TOP + d.CORNER_LIP_ABOVE - d.FLOOR_T
    x_in = -d.PCB_X / 2 - d.LIP_CLEAR  # inside face of the lips
    for sy in (-1, 1) if d.CORNER_LIPS else ():
        y_in = sy * (d.PCB_Y / 2 + d.LIP_CLEAR)
        ya = Align.MAX if sy < 0 else MIN
        yb = MIN if sy < 0 else Align.MAX
        # arm along the -X edge
        b += Pos(x_in, y_in + sy * d.CORNER_LIP_T, d.FLOOR_T) * Box(
            d.CORNER_LIP_T, d.CORNER_LIP_ARM + d.CORNER_LIP_T, lip_h, align=(Align.MAX, yb, MIN)
        )
        # arm along the ±Y edge
        b += Pos(x_in - d.CORNER_LIP_T, y_in, d.FLOOR_T) * Box(
            d.CORNER_LIP_ARM + d.CORNER_LIP_T, d.CORNER_LIP_T, lip_h, align=(MIN, ya, MIN)
        )
    # IR receiver window in the +Y wall, in front of the lens
    b -= Pos(d.RX_X, d.OUTER / 2, d.PCB_TOP + d.RX_LENS_Z) * Rot(90, 0, 0) * extrude(
        RectangleRounded(d.RX_WINDOW_W, d.RX_WINDOW_H, d.RX_WINDOW_R), d.WALL * 2, both=True
    )
    # Screw tabs flush with the floor (wall mount)
    if d.TABS:
        for sx in (-1, 1):
            tab = Pos(sx * (d.OUTER / 2 - 1 + (d.TAB_LEN + 1) / 2), 0, 0) * Box(
                d.TAB_LEN + 1, d.TAB_W, d.TAB_T, align=(CEN, CEN, MIN)
            )
            outer_edges = tab.edges().filter_by(Axis.Z).filter_by(
                lambda e, sx=sx: sx * e.center().X > d.OUTER / 2 + d.TAB_LEN / 2
            )
            tab = fillet(outer_edges, radius=d.TAB_CORNER_R)
            b += tab
            b -= Pos(sx * (d.OUTER / 2 + d.TAB_LEN / 2), 0, 0) * Cylinder(
                (d.TAB_HOLE_D + d.HOLE_COMP) / 2, d.TAB_T * 3, mode=Mode.PRIVATE
            )

    # Power wire hole in the -X wall
    b -= Pos(-d.OUTER / 2, d.WIRE_HOLE_Y, d.FLOOR_T + d.WIRE_HOLE_Z) * Rot(0, 90, 0) * Cylinder(
        (d.WIRE_HOLE_D + d.HOLE_COMP) / 2, d.WALL * 3, mode=Mode.PRIVATE
    )
    return b


def lid(d: Dims) -> Part:
    """Lid in assembled position."""
    z0 = d.LID_INNER_Z
    l = Pos(0, 0, z0) * extrude(RectangleRounded(d.OUTER, d.OUTER, d.OUTER_CORNER_R), d.LID_T)
    l = fillet(l.edges().group_by(Axis.Z)[-1], radius=d.LID_EDGE_FILLET)
    # Locating lip inside the walls, notched at the posts
    lip_out = RectangleRounded(
        d.INNER - 2 * d.FIT_CLEARANCE, d.INNER - 2 * d.FIT_CLEARANCE, max(d.OUTER_CORNER_R - d.WALL - d.FIT_CLEARANCE, 0.5)
    )
    lip = Pos(0, 0, z0 - d.LIP_H) * extrude(lip_out - offset(lip_out, -d.LIP_W), d.LIP_H)
    for x, y in d.POSTS:
        lip -= Pos(x, y, 0) * Cylinder(d.POST_D / 2 + d.FIT_CLEARANCE + 1.2, 100, mode=Mode.PRIVATE)
    l += lip

    # LED cone: a boss hangs from the lid down to the LED tip, cone through it
    lx, ly = d.LED_X, d.LED_Y
    hold_r = d.LED_HOLD_D / 2
    top_r = d.CONE_TOP_D / 2
    boss_h = z0 - d.LED_HOLD_Z0
    l += Pos(lx, ly, d.LED_HOLD_Z0) * Cone(
        hold_r + d.CONE_WALL,
        hold_r + d.CONE_WALL + (top_r - hold_r) * boss_h / (d.LID_OUTER_Z - d.LED_HOLD_Z0),
        boss_h,
        align=(CEN, CEN, MIN),
    )
    l -= Pos(lx, ly, d.LED_HOLD_Z0 - 0.01) * Cylinder(hold_r, d.LED_HOLD + 0.02, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)
    l -= Pos(lx, ly, d.CONE_Z0) * Cone(hold_r, top_r, d.LID_OUTER_Z - d.CONE_Z0 + 0.01, align=(CEN, CEN, MIN), mode=Mode.PRIVATE)

    # Keep the cone housing off the receiver
    l -= Pos(d.RX_X, d.RX_Y, d.PCB_TOP) * Box(
        d.RX_W + 2 * d.PART_CLEAR,
        d.RX_DEPTH + 2 * d.PART_CLEAR,
        d.RX_TOP + d.PART_CLEAR,
        align=(CEN, CEN, MIN),
        mode=Mode.PRIVATE,
    )

    # Lid screws, counterbored for pan heads
    for x, y in d.POSTS:
        l -= Pos(x, y, 0) * Cylinder((d.SCREW_CLEAR_D + d.HOLE_COMP) / 2, 100, mode=Mode.PRIVATE)
        l -= Pos(x, y, d.LID_OUTER_Z) * Cylinder(
            (d.CBORE_D + d.HOLE_COMP) / 2, d.CBORE_DEPTH, align=(CEN, CEN, Align.MAX), mode=Mode.PRIVATE
        )
    return l


def board_dummy(d: Dims) -> list[tuple[Part, str, str]]:
    """Stand-ins for the board's parts, for the section views and interference check only."""
    pcb = Pos(0, 0, d.PCB_Z) * Box(d.PCB_X, d.PCB_Y, d.PCB_T, align=(CEN, CEN, MIN))
    # Module above the board only: its overhang below is clear of the standoffs (print 1)
    module = Pos(d.PCB_X / 2 - d.MODULE_T / 2 + 1.0, d.MODULE_Y, d.PCB_TOP) * Box(
        d.MODULE_T, d.MODULE_W, d.MODULE_H, align=(CEN, CEN, MIN)
    )
    led = Pos(d.LED_X, d.LED_Y, d.PCB_TOP) * Cylinder(d.LED_D / 2, d.LED_TOP, align=(CEN, CEN, MIN))
    rx = Pos(d.RX_X, d.RX_Y, d.PCB_TOP) * Box(d.RX_W, d.RX_DEPTH, d.RX_TOP, align=(CEN, CEN, MIN))
    header = Pos(-4.0, -d.PCB_Y / 2 + 1.3, d.PCB_TOP) * Box(15.0, 2.5, d.HEADER_H, align=(CEN, CEN, MIN))
    return [
        (pcb + module + header, "#2a9d4b", "board, ESP-01M, header (stand-in)"),
        (led, "#cc4444", "IR LED (stand-in)"),
        (rx, "#7a3fb0", "IR receiver (stand-in)"),
    ]


def lid_print(d: Dims) -> Part:
    """Lid flipped onto its outer face for printing."""
    return Pos(0, 0, d.LID_OUTER_Z) * Rot(180, 0, 0) * lid(d)


def build(d: Dims) -> dict[str, Part]:
    return {"base": base(d), "lid": lid_print(d)}


def assembly(d: Dims):
    # nothing printed may touch the board's parts -> overlap check
    return [(base(d), "#3a6ea5", "base"), (lid(d), "#e0a030", "lid")] + board_dummy(d)


def views(d: Dims):
    return [
        View("XZ", d.LED_Y, "through the LED"),
        View("YZ", d.LED_X, "through the LED"),
        View("YZ", d.RX_X, "through the receiver"),
        View("XY", d.PCB_TOP + 4, "plan 4 mm above the board"),
    ]


def checks(d: Dims):
    (hx, hy), (px, py) = d.HOLES[0], d.POSTS[0]
    # LED holder, measured on the lid where it sits in assembly(d): the lid prints upside down,
    # and assembled coordinates do not change when the print orientation does
    led_z = d.LED_HOLD_Z0 + d.LED_HOLD / 2
    return [
        Wall("base", "XY", d.FLOOR_T + 1.0, near=(hx, hy), radius=d.STANDOFF_D / 2 + 1, label="board standoff pilot"),
        Wall("base", "XY", d.LID_INNER_Z - 2.0, near=(px, py), radius=d.POST_D / 2 + 1, label="lid screw post pilot"),
        Wall("lid", "XZ", d.LED_Y, near=(d.LED_X, led_z), radius=d.LED_HOLD_D / 2 + d.CONE_WALL + 0.5,
             label="LED holder", frame="assembly"),
    ]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
