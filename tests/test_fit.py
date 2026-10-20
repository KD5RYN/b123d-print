"""Fit between pieces: interference and hole alignment on simple assemblies."""

import dataclasses
import types

import pytest
from build123d import Align, Box, Color, Cylinder, Pos, Rot

from b123d_print import align_axis, checks as ck, place_on
from b123d_print.config import Settings
from b123d_print.fit import Mates, bores, hole_kinds, is_standin, joint_pairs, run_fit, screw_pair
from b123d_print.measure import distance

BED = (Align.CENTER, Align.CENTER, Align.MIN)
CORNERS = [(-25, -15), (-25, 15), (25, -15), (25, 15)]


def box():
    """A 60 x 40 x 20 box with four posts holding M3 heat-set insert holes (4.0 mm)."""
    b = Box(60, 40, 20, align=BED) - Pos(0, 0, 2) * Box(56, 36, 20, align=BED)
    for x, y in CORNERS:
        b += Pos(x, y, 0) * Cylinder(3.5, 20, align=BED)
        b -= Pos(x, y, 10) * Cylinder(2.0, 10.01, align=BED)
    return b


def lid(z=20.0, shift=0.0, hole_d=3.4):
    """A 3 mm lid on top with four M3 clearance holes; the first one moved `shift` mm in X."""
    p = Pos(0, 0, z) * Box(60, 40, 3, align=BED)
    for i, (x, y) in enumerate(CORNERS):
        p -= Pos(x + (shift if i == 0 else 0), y, z) * Cylinder(hole_d / 2, 3, align=BED)
    return p


def run(asm, spec=None, settings=None):
    return (spec or Mates()).run({"box": None, "lid": None}, asm, settings or Settings())


def bad(found):
    return [f for f in found if f.level != ck.OK]


def test_lid_on_box_with_four_screws_fits():
    found = run([(box(), None, "box"), (lid(), None, "lid")])
    assert not bad(found)
    aligned = [f for f in found if f.check == "align"]
    assert len(aligned) == 4 and all("M3: clearance + insert" in f.message for f in aligned)
    assert any(f.check == "mate" and "touch" in f.message for f in found)


def test_one_hole_off_by_half_a_millimetre_fails():
    found = run([(box(), None, "box"), (lid(shift=0.5), None, "lid")])
    fails = [f for f in found if f.level == ck.FAIL]
    assert len(fails) == 1 and fails[0].check == "align"
    assert fails[0].data["offset"] == pytest.approx(0.5, abs=0.01)
    assert fails[0].data["where"][:2] == pytest.approx([-24.75, -15.0], abs=0.01)
    assert "0.50 mm off-axis" in fails[0].message
    # within the tolerance it passes
    assert not bad(run([(box(), None, "box"), (lid(shift=0.5), None, "lid")], Mates(hole_tol=0.6)))


def test_two_pieces_overlapping_by_a_tenth_fail_with_volume_and_place():
    found = run([(box(), None, "box"), (lid(z=19.9), None, "lid")])
    f = next(f for f in found if f.check == "mate" and f.level == ck.FAIL)
    assert f.target == "box / lid"
    # the box's rim (60 x 40 minus the 56 x 36 inside, plus the four posts) is 0.1 mm into the lid
    assert f.data["volume"] == pytest.approx(0.1 * (60 * 40 - 56 * 36 + 4 * 3.14159 * (3.5 ** 2 - 2 ** 2)), rel=0.03)
    assert f.data["where"][2] == pytest.approx(19.95, abs=0.01) and f.data["extent"][2] == pytest.approx(0.1, abs=1e-3)


def test_gap_under_the_clearance_warns_and_stand_ins_are_obstacles():
    found = run([(box(), None, "box"), (lid(z=20.1), None, "lid")])
    w = [f for f in found if f.level == ck.WARN]
    assert len(w) == 1 and w[0].data["gap"] == pytest.approx(0.1, abs=1e-3) and "under the clearance" in w[0].message
    board = Pos(0, 0, 1.9) * Box(20, 20, 5, align=BED)  # sunk 0.1 mm into the floor
    found = run([(box(), None, "box"), (lid(), None, "lid"), (board, None, "board (stand-in)")])
    f = next(f for f in found if f.level == ck.FAIL)
    assert f.target == "box / board (stand-in)"
    # two stand-ins are never paired
    found = run([(board, None, "a (stand-in)"), (board, None, "b (stand-in)")])
    assert not bad(found)


def test_mismatched_and_unpartnered_holes():
    found = run([(box(), None, "box"), (lid(hole_d=2.6), None, "lid")])  # a pilot over an insert hole
    w = [f for f in found if f.level == ck.WARN]
    assert len(w) == 4 and all("match no one screw" in f.message for f in w)
    plain = Box(60, 40, 20, align=BED)  # no holes under the lid's holes
    found = run([(plain, None, "box"), (lid(), None, "lid")])
    w = [f for f in found if f.level == ck.WARN]
    assert len(w) == 4 and all("no partner" in f.message and "runs into solid box" in f.message for f in w)


def test_counterbore_and_clearance_are_one_bore():
    from b123d_print.recipes import screw_hole

    p = Box(20, 20, 6, align=BED) - Pos(0, 0, 6) * screw_hole("M3", 10)
    (b,) = bores(p)
    assert b["d"] == pytest.approx(3.4) and sorted(b["ds"]) == pytest.approx([3.4, 6.68], abs=0.05)


def test_joint_pairs_use_their_own_clearance():
    sock = Box(20, 20, 10, align=BED) - Pos(0, 0, 2) * Box(10.2, 10.2, 10, align=BED)
    peg = Pos(0, 0, 2) * Box(10.0, 10.0, 12, align=BED)  # 0.1 per side, resting on the floor
    asm = [(sock, None, "socket"), (peg, None, "peg")]
    # a plain pair touching the floor: contact, fine
    assert not bad(Mates(align=False).run({"socket": 0, "peg": 0}, asm, Settings()))
    peg = Pos(0, 0, 2.5) * Box(10.0, 10.0, 12, align=BED)  # lifted: the side gap (0.1) is the closest
    asm = [(sock, None, "socket"), (peg, None, "peg")]
    assert bad(Mates(align=False).run({"socket": 0, "peg": 0}, asm, Settings()))[0].level == ck.WARN
    ok = Mates(align=False, joints=[("peg", "socket", 0.1)]).run({"socket": 0, "peg": 0}, asm, Settings())
    assert not bad(ok) and any("(joint)" in f.target for f in ok)
    tight = Mates(align=False, joints=[{"male": "peg", "female": "socket", "clearance": 0.2}])
    f = bad(tight.run({"socket": 0, "peg": 0}, asm, Settings()))
    assert f[0].level == ck.FAIL and "will not go together" in f[0].message

    class Joint:  # the joints module's pairs are read by attribute
        male, female, clearance = "peg", "socket", 0.1

    assert joint_pairs([Joint()]) == {frozenset(("peg", "socket")): {"male": "peg", "female": "socket", "clearance": 0.1}}


def test_screw_tables_and_stand_in_labels():
    assert ("M3", "clearance") in hole_kinds(3.4) and ("M3", "insert") in hole_kinds(4.0) and ("M3", "pilot") in hole_kinds(2.7)
    assert screw_pair(3.4, 4.0).startswith("M3: clearance + insert")
    assert screw_pair(3.4, 3.4).startswith("M3: clearance + clearance")
    assert screw_pair(2.6, 4.0) is None  # an M3 pilot over an M3 insert hole: nothing lets the screw through
    printed = {"base", "backplate"}
    assert is_standin("IR LED (stand-in)", printed) and is_standin("sensor dummy", printed)
    assert not is_standin("back plate", printed) and is_standin("wall", printed)


def test_run_fit_reads_the_script_and_its_joints(tmp_path):
    mod = types.ModuleType("asm")
    mod.__file__ = str(tmp_path / "asm.py")

    @dataclasses.dataclass(frozen=True)
    class Dims:
        SHIFT: float = 0.5

    mod.Dims = Dims
    mod.build = lambda d: {"box": box(), "lid": Pos(0, 0, -20) * lid()}
    mod.assembly = lambda d: [(box(), "gray", "box"), (lid(shift=d.SHIFT), "orange", "lid")]
    r = run_fit(mod, "", Settings())
    assert r["items"] == [["box", False], ["lid", False]]
    assert [f.level for f in r["findings"] if f.check == "align"].count(ck.FAIL) == 1
    mod.checks = lambda d: [Mates(hole_tol=1.0)]
    assert not bad(run_fit(mod, "", Settings())["findings"])


def test_bundled_examples_fit():
    """The examples with an assembly pass the fit check (no false alarms on real parts)."""
    from pathlib import Path

    from b123d_print.project import load

    ex = Path(__file__).resolve().parents[1] / "src/b123d_print/examples"
    for name in ("esp_ir_blaster", "tuya_motion_sensor_outdoor_case"):
        mod = load(ex / name / f"{name}.py")
        r = run_fit(mod, "", Settings())
        assert not bad(r["findings"]), (name, [f.line() for f in bad(r["findings"])])


def test_place_on_stacks_flips_and_mounts_on_any_flat_face():
    b = box()
    raw_lid = lid(z=0.0)
    raw_lid.label = "lid"
    raw_lid.color = Color("orange")

    # bottom (-Z) of lid onto top (+Z) of box: touching, all 4 holes line up, metadata kept
    placed = place_on(raw_lid, "bottom", b, "top")
    assert placed.label == "lid" and placed.color is not None
    assert placed.bounding_box().min.Z == pytest.approx(20.0, abs=1e-4)
    assert not bad(run([(b, None, "box"), (placed, None, "lid")]))

    # lid modeled upside-down for printing (mating inner face is +Z): flipped 180 deg onto box top
    upside_down = Pos(12, -7, 3) * Rot(180, 0, 0) * lid(z=0.0)
    flipped = place_on(upside_down, "top", b, "top")
    assert flipped.bounding_box().min.Z == pytest.approx(20.0, abs=1e-4)
    assert not bad(run([(b, None, "box"), (flipped, None, "lid")]))

    # offset along the target normal, spin in the plane, and in-plane shift
    gapped = place_on(raw_lid, "bottom", b, "top", offset=0.25, spin=180)
    assert not bad(run([(b, None, "box"), (gapped, None, "lid")]))
    assert distance(gapped, b)["distance"] == pytest.approx(0.25, abs=1e-3)

    shifted = place_on(raw_lid, "bottom", b, "top", shift=(2.0, -1.5))
    assert shifted.bounding_box().center().X == pytest.approx(2.0, abs=1e-3)
    assert shifted.bounding_box().center().Y == pytest.approx(-1.5, abs=1e-3)

    # side wall (+X) and tilted face contact
    bracket = Box(4, 16, 12, align=BED)
    on_side = place_on(bracket, "-X", b, "+X")
    assert on_side.bounding_box().min.X == pytest.approx(30.0, abs=1e-4)
    assert distance(on_side, b)["touching"] and not distance(on_side, b)["overlap"]

    wedge = Rot(0, 25, 0) * Box(30, 30, 10, align=BED)
    top_face = max(wedge.faces(), key=lambda f: f.center().Z)
    plate = Box(15, 15, 2, align=BED)
    on_wedge = place_on(plate, "bottom", wedge, top_face)
    d = distance(on_wedge, wedge)
    assert d["touching"] and not d["overlap"]


def test_align_axis_lines_up_holes_and_clocks_second_hole():
    # Box with a side lip merged into the rim so its top face center is shifted in X from the hole pattern
    b = (box() + Pos(30, 0, 18) * Box(6, 40, 2, align=BED)).clean()
    placed = place_on(lid(z=0.0), "bottom", b, "top")
    # Before align_axis, the lid centered on the wider top face has its holes off-axis
    assert any(f.level != ck.OK and f.check == "align" for f in run([(b, None, "box"), (placed, None, "lid")]))

    # Slide in the contact plane to line up the (-25, -15) hole while keeping Z=20 contact
    aligned = align_axis(placed, (-25, -15), b)
    assert aligned.bounding_box().min.Z == pytest.approx(20.0, abs=1e-4)
    assert not bad(run([(b, None, "box"), (aligned, None, "lid")]))

    # Skewed lid (spun 15 deg and shifted): align_axis with clock= snaps both position and angle
    skewed = place_on(lid(z=0.0), "bottom", b, "top", spin=15, shift=(3.0, -2.0))
    clocked = align_axis(skewed, (-25, -15, 21.5), b, (-25, -15, 15.0), clock=((25, 15, 21.5), (25, 15, 15.0)))
    assert clocked.bounding_box().min.Z == pytest.approx(20.0, abs=1e-4)
    assert not bad(run([(b, None, "box"), (clocked, None, "lid")]))

    # Loose horizontal pin turned and placed into a vertical hole (by 3D point, Face, dict, Axis, id)
    pin = Rot(0, 90, 0) * Cylinder(1.9, 10)
    pin.label = "dowel"
    pin_placed = align_axis(pin, None, b, (25, 15, 15), offset=1.0)
    assert pin_placed.label == "dowel"
    bb = pin_placed.bounding_box()
    assert bb.center().X == pytest.approx(25.0, abs=1e-3) and bb.center().Y == pytest.approx(15.0, abs=1e-3)
    assert bb.size.Z == pytest.approx(10.0, abs=1e-3)
    assert bb.center().Z == pytest.approx(16.0, abs=1e-3)

    cyl_face = next(f for f in pin.faces() if f.geom_type.name == "CYLINDER")
    bore_dict = next(h for h in bores(b) if h["center"][:2] == [25.0, 15.0])
    by_face = align_axis(pin, cyl_face, b, bore_dict, flip=True)
    assert by_face.bounding_box().center().X == pytest.approx(25.0, abs=1e-3)
    by_tuple = align_axis(pin, ((0, 0, 0), (1, 0, 0)), b, 1)
    assert by_tuple.bounding_box().size.Z == pytest.approx(10.0, abs=1e-3)

    with pytest.raises(ValueError, match="not parallel"):
        align_axis(pin, None, b, (25, 15, 15), keep_contact=True)
    with pytest.raises(ValueError, match="coaxial"):
        align_axis(aligned, (-25, -15), b, (-25, -15), clock=((-25, -15), (-25, -15)))
    with pytest.raises(ValueError, match="no cylindrical"):
        align_axis(Box(10, 10, 10), None, b, (25, 15, 15))
