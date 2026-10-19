"""Joint helpers and split() (joints.py) on known shapes: the female is the male grown by exactly
the clearance, the pieces are valid single solids, and the volume adds up."""

import pytest
from build123d import Align, Box, Keep, Location, Plane, Pos, Rot

from b123d_print import checks as ck
from b123d_print.joints import INSERTS, Bowtie, Dovetail, Dowel, Insert, Lap, split

BED = (Align.CENTER, Align.CENTER, Align.MIN)
C = 0.2
TOL = 1e-3


def bar():
    """200 x 30 x 12 on the bed; Plane.YZ cuts it in the middle, joints at (y, z)."""
    return Box(200, 30, 12, align=BED)


def size(p):
    s = p.bounding_box().size
    return s.X, s.Y, s.Z


def inside(male, female):
    """The male lies wholly inside the female (what is left of it outside is ~0)."""
    return (male - female).volume < 1e-6


@pytest.mark.parametrize("square", [False, True])
@pytest.mark.parametrize("c", [0.0, 0.1, 0.2, 0.35])
def test_dowel_socket_is_two_clearances_bigger(square, c):
    p = Dowel(6.0, 20.0, square=square).pair(c)
    (mx, my, mz), (fx, fy, fz) = size(p.male), size(p.female)
    assert fx - mx == pytest.approx(2 * c, abs=TOL) and fy - my == pytest.approx(2 * c, abs=TOL)
    assert fz - mz == pytest.approx(2 * c, abs=TOL)  # end gap at each end too
    assert inside(p.male, p.female) and p.loose


def test_round_socket_gets_hole_comp_square_does_not():
    assert size(Dowel(6.0, 20.0).pair(C, hole_comp=0.3).female)[0] == pytest.approx(6.0 + 2 * C + 0.3, abs=TOL)
    assert size(Dowel(6.0, 20.0, square=True).pair(C, hole_comp=0.3).female)[0] == pytest.approx(6.0 + 2 * C, abs=TOL)


def test_joint_clearance_overrides_the_split_one():
    p = Dowel(6.0, 20.0, clearance=0.05).pair(C)
    assert size(p.female)[0] - size(p.male)[0] == pytest.approx(0.1, abs=TOL)


def test_bowtie_recess_is_two_clearances_bigger():
    k = Bowtie(30.0, 16.0, 8.0, 4.0)
    p = k.pair(C)
    (mx, my, mz), (fx, fy, fz) = size(p.male), size(p.female)
    assert (my, mz) == pytest.approx((4.0, 30.0), abs=TOL)  # (X is a little under 16: the corners are rounded)
    assert fx - mx == pytest.approx(2 * C, abs=TOL) and fz - mz == pytest.approx(2 * C, abs=TOL)
    assert fy - my == pytest.approx(C + 0.01, abs=TOL)  # the floor gap, plus the opening above the surface
    assert inside(p.male, p.female)
    # the outline grows by C everywhere: its area grows by C x perimeter (+ pi C^2 for the round corners)
    a0, a1 = k.outline().area, k.outline(C).area
    assert a1 - a0 == pytest.approx(C * k.outline().outer_wire().length + 3.14159 * C * C, rel=0.02)


def test_dovetail_slot_is_two_clearances_bigger():
    t = Dovetail(12.0, 10.0, 15.0, height=8.0)
    p = t.pair(C)
    (mx, my, mz), (fx, fy, fz) = size(p.male), size(p.female)
    assert fx - mx == pytest.approx(2 * C, abs=TOL) and fz - mz == pytest.approx(2 * C, abs=TOL)
    assert fy - my == pytest.approx(2 * C, abs=TOL)
    assert t.tip_width > t.width and inside(p.male, p.female)


def test_lap_rebate_has_the_clearance_on_the_step_and_the_end():
    p = Lap(15.0).pair(C)
    assert p.female.bounding_box().max.Z - p.male.bounding_box().max.Z == pytest.approx(C, abs=TOL)  # the end
    assert p.female.bounding_box().max.Y - p.male.bounding_box().max.Y == pytest.approx(C, abs=TOL)


def test_insert_pocket_is_the_makers_hole_plus_hole_comp():
    hole, length = INSERTS["M3"][:2]
    pocket = Insert("M3").pair(C, hole_comp=0.2).female
    below = pocket & Box(100, 100, 100, align=(Align.CENTER, Align.CENTER, Align.MAX))
    assert size(below)[0] == pytest.approx(hole + 0.2, abs=TOL)
    assert size(below)[2] == pytest.approx(length + 1.0, abs=TOL)  # blind hole: length + 1 mm (BP-T3)
    assert Insert("M3").min_wall == 1.6
    assert Insert("M3", hole=4.2, length=4.0).dims[:2] == (4.2, 4.0)
    with pytest.raises(ValueError, match="no size"):
        Insert("M7").dims


JOINT_SETS = {
    "none": [],
    "dowels": [Dowel(6, 16, square=True, at=(-8, 6)), Dowel(5, 16, at=(8, 6), angle=45)],
    "plug": [Dowel(5, 10, plug=True, at=(0, 6))],
    "bowtie": [Bowtie(30, 14, 7, 4, at=(0, 12))],
    "bowtie_under": [Bowtie(30, 14, 7, 4, at=(0, 0), angle=180)],
    "dovetail": [Dovetail(10, 8, 15)],
    "lap": [Lap(15, at=(0, 6))],
    "insert": [Insert("M3", at=(0, 6))],
    "flipped": [Dowel(6, 10, plug=True, at=(0, 6), flip=True)],
}


@pytest.mark.parametrize("name", JOINT_SETS)
def test_split_pieces_are_valid_and_volume_is_conserved(name):
    """a + b = the part, minus every female cut, plus every attached male, each inside the part."""
    part, plane = bar(), Plane.YZ
    joints = JOINT_SETS[name]
    s = split(part, plane, joints, clearance=C)
    for piece in (s.a, s.b):
        assert piece.is_valid and len(piece.solids()) == 1
    assert s.a.bounding_box().max.X <= 0.01 + 15 and s.b.bounding_box().min.X >= -0.01 - 15
    expected = part.volume
    lower, upper = part.split(plane, keep=Keep.BOTTOM), part.split(plane, keep=Keep.TOP)
    for j in joints:
        p = j.pair(C)
        at = Location(plane) * Pos(*j.at, 0) * Rot(0, 0, j.angle) * (Rot(180, 0, 0) if j.flip else Rot())
        female = at * p.female
        male = at * p.male if p.male is not None else None
        other = lower if j.flip else upper  # the piece that gets the female
        if p.loose or isinstance(j, Insert):
            expected -= (female & part).volume
        else:
            expected += (male & part & other).volume - (female & other).volume
    assert s.a.volume + s.b.volume == pytest.approx(expected, rel=1e-6)
    loose = [j for j in joints if j.pair(C).loose]
    assert len(s.loose) == len(s.placed) == len(loose)
    for n, p in s.loose.items():
        assert p.bounding_box().min.Z == pytest.approx(0, abs=1e-6), f"{n} lies on the bed"
        if n.startswith("key"):
            assert p.volume == pytest.approx(s.placed[n].volume, rel=1e-6)


def test_loose_pieces_fit_their_recesses():
    """The Gap check measures exactly the clearance between a key or a pin and the pieces."""
    s = split(bar(), Plane.YZ, [Bowtie(30, 14, 7, 4, at=(0, 12)), Dowel(4, 16, square=True, at=(10, 6))], clearance=C)
    parts = {"a": s.a, "b": s.b, **s.placed}
    for loose in ("key1", "pin1"):
        for piece in ("a", "b"):
            (f,) = ck.Gap(loose, piece, min=C - 0.01, max=C + 0.01).run(parts, None, None)
            assert f.level == ck.OK, f.message


def test_split_errors():
    with pytest.raises(ValueError, match="clearance"):
        split(bar(), Plane.YZ, [Dowel()])
    with pytest.raises(ValueError, match="misses the part"):
        split(bar(), Plane.YZ.offset(500))
    with pytest.raises(ValueError, match="separate bodies"):  # a key wider than the bar, cut through it
        split(bar(), Plane.YZ, [Bowtie(30, 40, 7, 12.5, at=(0, 12))], clearance=C)
    with pytest.raises(TypeError, match="not a joint"):
        split(bar(), Plane.YZ, ["dowel"], clearance=C)
