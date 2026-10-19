"""Gear pair: a 12-tooth pinion and a 30-tooth gear, module 1.5, made with py_gearworks.

Shows gears that print (Threads, fasteners and gears in the docs):
- Module 1.5, the size sources give for a 0.4 mm nozzle (module 1 is the lower limit for light
  duty). Face width 10 x module.
- The pinion has fewer than 17 teeth, so at a 20 deg pressure angle its tooth roots would be
  undercut: a positive profile shift (x = (17 - z) / 17, KHK) thickens them, and py_gearworks's
  `mesh_to` moves the gears apart to suit.
- Backlash: each gear's flanks are thinned (py_gearworks `backlash`, a coefficient of the module
  along the line of action), BACKLASH in total. The assembly's Gap check measures what is left
  between the teeth.
- Both bores are free fits on 5 mm pins, with HOLE_COMP.

Print orientation: each gear flat on the bed (Z=0), so the teeth lie in the layers and bend along
them. No supports. Slicer: 4-6 walls so the teeth are solid perimeters. In use the gears turn on
fixed 5 mm pins (stand-ins in the assembly) at CENTER_DISTANCE apart. An example: not printed yet.
"""

from dataclasses import dataclass
from functools import cached_property

import py_gearworks as gw
from build123d import Align, Cylinder, GeomType, Part, Pos, chamfer

from b123d_print import Gap, ThinFeature, View, hole_comp, load_settings

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    """All dimensions in mm (an example, not measured)."""

    MODULE: float = 1.5  # 1.5-2 for a 0.4 mm nozzle; below 1 the teeth are a few lines wide
    PINION_TEETH: int = 12
    GEAR_TEETH: int = 30
    PRESSURE_ANGLE: float = 20.0  # deg, the standard
    FACE_W: float = 15.0  # 10 x module
    BACKLASH: float = 0.3  # mm in total along the line of action, 0.15 per gear (sources: 0.2-0.4)
    PIN_D: float = 5.0  # the pins the gears turn on
    BORE_FIT: float = load_settings(__file__).free_fit  # per side: turns freely (BP-F1)
    HOLE_COMP: float = hole_comp(__file__)  # the bores are vertical
    EDGE_CHAMFER: float = 0.4  # the bore's top edge

    @property
    def pinion_shift(self) -> float:  # profile shift that just avoids undercut (KHK)
        return max(0.0, (17 - self.PINION_TEETH) / 17)

    @cached_property
    def gears(self) -> tuple:
        """(pinion, gear) as py_gearworks objects, the pinion meshed to the gear's +X side."""
        per_gear = self.BACKLASH / 2 / self.MODULE  # py_gearworks: a coefficient of the module
        common = dict(module=self.MODULE, height=self.FACE_W, backlash=per_gear,
                      pressure_angle=self.PRESSURE_ANGLE * 3.141592653589793 / 180)
        gear = gw.SpurGear(number_of_teeth=self.GEAR_TEETH, **common)
        pinion = gw.SpurGear(number_of_teeth=self.PINION_TEETH, profile_shift=self.pinion_shift, **common)
        pinion.mesh_to(gear, target_dir=gw.RIGHT)
        return pinion, gear

    @property
    def center_distance(self) -> float:
        return float(self.gears[0].center[0])


VARIANTS = {"": {}}


def bored(gear: Part, d: Dims) -> Part:
    """A gear at the origin with its bore cut and the bore's top edge chamfered (a chamfer at the
    bed would widen the hole downward: an overhang)."""
    p = gear - Cylinder((d.PIN_D + 2 * d.BORE_FIT + d.HOLE_COMP) / 2, d.FACE_W, align=BED)
    top = [e for e in p.edges() if e.geom_type == GeomType.CIRCLE and e.radius < d.PIN_D and e.center().Z > 1]
    return chamfer(top, d.EDGE_CHAMFER)


def meshed(d: Dims) -> tuple[Part, Part]:
    """(pinion, gear) in assembled position: the gear at the origin, the pinion at +X."""
    pinion, gear = d.gears
    c = d.center_distance
    return Pos(c, 0, 0) * bored(Pos(-c, 0, 0) * pinion.build_part(), d), bored(gear.build_part(), d)


def build(d: Dims) -> dict[str, Part]:
    pinion, gear = meshed(d)
    return {"pinion": Pos(-d.center_distance, 0, 0) * pinion, "gear": gear}


def assembly(d: Dims):
    pinion, gear = meshed(d)
    pin = Cylinder(d.PIN_D / 2, d.FACE_W + 10, align=BED)
    return [(pinion, "#3a6ea5", "pinion"), (gear, "#e0a030", "gear"),
            (Pos(d.center_distance, 0, -5) * pin, "#888888", "pinion pin (stand-in)"),
            (Pos(0, 0, -5) * pin, "#888888", "gear pin (stand-in)")]


def views(d: Dims):
    return [View("XY", d.FACE_W / 2, "the teeth in mesh")]


def checks(d: Dims):
    # a spur gear is a 2D profile extruded along Z, so the XY sections see every wall; XZ and YZ
    # sections only graze the tooth tips and read them as knife edges
    thin = [ThinFeature(n, planes=("XY",)) for n in ("pinion", "gear")]
    # the teeth must not touch: the backlash, measured where they mesh (half of it each side)
    return thin + [Gap("pinion", "gear", min=0.05, max=d.BACKLASH,
                within=((d.center_distance - d.PINION_TEETH * d.MODULE / 2, 0, d.FACE_W / 2), (8, 12, d.FACE_W)),
                label="backlash between the teeth")]


if __name__ == "__main__":
    from b123d_print import run

    run(__file__)
