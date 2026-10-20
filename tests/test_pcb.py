"""PCB fixtures exercise the existing fit, wall and template checks; no physical print claim."""

import math

import pytest
from bd_warehouse.fastener import SocketHeadCapScrew
from build123d import Align, Box, Pos

from b123d_print import checks as ck
from b123d_print.config import Settings
from b123d_print.fit import Mates
from b123d_print.pcb import PCB_PATTERNS
from b123d_print.recipes import box_shell, get, index, pcb_board, pcb_mounting_pattern, pcb_standoff
from b123d_print.templates import slice_template

BED = (Align.CENTER, Align.CENTER, Align.MIN)
HOLES = ((-13.0, -7.0), (12.0, -7.0), (-10.0, 8.0))  # intentionally asymmetric


def test_standoff_pilot_depth_floor_and_compensation():
    post = pcb_standoff(8, 8, 2.5, 5, hole_comp=0.2)
    assert post.is_valid
    bb = post.bounding_box()
    assert (bb.size.X, bb.size.Y, bb.size.Z, bb.min.Z) == pytest.approx((8, 8, 8, 0))
    assert post.volume == pytest.approx(math.pi * (4 ** 2 * 8 - 1.35 ** 2 * 5))
    (hole,) = ck.holes(post)
    assert hole['d'] == pytest.approx(2.7)
    # The central floor extends to Z=3, the axis above it is empty.
    assert (post & Pos(0, 0, 0) * Box(1, 1, 3, align=BED)).volume == pytest.approx(3)
    assert (post & Pos(0, 0, 3) * Box(1, 1, 5, align=BED)).volume == pytest.approx(0)
    flare = pcb_standoff(8, 8, 2.5, 5, flare=2, flare_h=2)
    assert flare.is_valid and flare.bounding_box().size.X == pytest.approx(12)
    # A negative calibration is valid when the resulting hole still has positive diameter.
    assert ck.holes(pcb_standoff(8, 8, 2.5, 5, hole_comp=-0.1))[0]['d'] == pytest.approx(2.4)


def test_clearance_spacer_reuses_bd_warehouse_size():
    screw = SocketHeadCapScrew('M2-0.4', 10, 'iso4762', simple=True)
    diameter = screw.clearance_hole_diameters['Normal']
    post = pcb_standoff(5, 7, diameter, 5, hole_comp=0.15)
    assert post.volume == pytest.approx(math.pi * (3.5 ** 2 - ((diameter + 0.15) / 2) ** 2) * 5)
    assert ck.holes(post)[0]['d'] == pytest.approx(diameter + 0.15)


@pytest.mark.parametrize('kwargs', [
    {'height': 0}, {'outside_d': -1}, {'pilot_d': 0}, {'pilot_depth': 0},
    {'pilot_depth': 9}, {'hole_comp': -2.5}, {'hole_comp': 6}, {'flare': -1},
    {'flare': 1}, {'flare_h': 1}, {'flare': 1, 'flare_h': 9}, {'height': math.nan},
    {'pilot_d': math.inf}, {'hole_comp': math.nan},
])
def test_invalid_standoff_dimensions(kwargs):
    args = dict(height=8, outside_d=8, pilot_d=2.5, pilot_depth=5)
    args.update(kwargs)
    with pytest.raises(ValueError, match='pcb_standoff'):
        pcb_standoff(**args)


def test_board_has_exact_asymmetric_pattern_without_compensation():
    board = pcb_board(34, 24, 1.6, HOLES, 3.4)
    assert board.is_valid and board.bounding_box().min.Z == pytest.approx(0)
    assert board.volume == pytest.approx(34 * 24 * 1.6 - len(HOLES) * math.pi * 1.7 ** 2 * 1.6)
    got = ck.holes(board)
    assert sorted(tuple(h['center'][:2]) for h in got) == sorted(HOLES)
    assert all(h['d'] == pytest.approx(3.4) for h in got)
    assert pcb_board(34, 24, 1.6, (), 3.4).volume == pytest.approx(34 * 24 * 1.6)


@pytest.mark.parametrize('kwargs', [
    {'width': 0}, {'length': -1}, {'thickness': math.inf}, {'hole_d': 0},
    {'holes': ((16, 0),)}, {'holes': ((0, 12),)}, {'holes': ((0, math.nan),)},
    {'holes': ((1, 2, 3),)}, {'holes': ((0, 0), (1, 0))},
])
def test_invalid_board_dimensions(kwargs):
    args = dict(width=34, length=24, thickness=1.6, holes=HOLES, hole_d=3.4)
    args.update(kwargs)
    with pytest.raises(ValueError, match='pcb_board'):
        pcb_board(**args)


def fixture(misplaced=False):
    base = box_shell(48, 36, 12, wall=2, floor=2)
    for i, (x, y) in enumerate(HOLES):
        if misplaced and i == 0:
            x, y = 0, 0  # collides with the measured underside envelope
        base += Pos(x, y, 2) * pcb_standoff(5, 7, 2.5, 4, flare=1, flare_h=1)
    board = Pos(0, 0, 7) * pcb_board(34, 24, 1.6, HOLES, 3.4)
    underside = Pos(0, 0, 4) * Box(8, 6, 3, align=BED)
    return base, [(base, None, 'base'), (board, None, 'board (stand-in)'),
                  (underside, None, 'underside component (stand-in)')]


def test_board_fits_supports_and_misplaced_support_reports_component_interference():
    base, assembly = fixture()
    found = Mates().run({'base': base}, assembly, Settings())
    assert not [f.line() for f in found if f.level != ck.OK]
    assert len([f for f in found if f.check == 'align']) == len(HOLES)
    base, assembly = fixture(misplaced=True)
    found = Mates().run({'base': base}, assembly, Settings())
    collision = next(f for f in found if f.level == ck.FAIL and 'underside component' in f.target)
    assert collision.check == 'mate' and collision.data['volume'] > 0


def test_existing_wall_and_template_tools_on_supports():
    base, assembly = fixture()
    found = ck.Wall('base', 'XY', 4, near=HOLES[0], radius=4, min=1.6,
                    frame='assembly', label='PCB pilot').run({'base': base}, assembly, Settings())
    assert found and all(f.level == ck.OK for f in found), [f.line() for f in found]
    assert found[0].data['min'] == pytest.approx(2.25, abs=0.1)
    template = slice_template(base, 'XY', 6, label=None)
    assert template.part.is_valid and len(template.part.solids()) == 1
    # Three supports plus the enclosing wall ring are joined by the thin base.
    assert template.info['pieces'] == len(HOLES) + 1 and template.info['base']['thickness'] > 0
    got = ck.holes(template.part)
    assert len(got) == len(HOLES) and all(h['d'] == pytest.approx(2.5) for h in got)
    # Templates may recenter the asymmetric bounding box; pairwise distances must survive.
    def spacings(points):
        return sorted(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:])
    assert spacings([h['center'][:2] for h in got]) == pytest.approx(spacings(HOLES))


def test_exact_board_patterns_and_recipe_lookup():
    assert set(PCB_PATTERNS) == {'raspberry_pi_zero_v1_2', 'raspberry_pi_pico_rev3'}
    zero = pcb_mounting_pattern('raspberry_pi_zero_v1_2')
    assert (zero.width, zero.length, zero.hole_d) == (65, 30, 2.75)
    assert zero.holes == ((-29, -11.5), (29, -11.5), (-29, 11.5), (29, 11.5))
    pico = pcb_mounting_pattern('raspberry_pi_pico_rev3')
    assert (pico.width, pico.length, pico.hole_d) == (21, 51, 2.1)
    assert pico.holes == ((-5.7, -23.5), (5.7, -23.5), (-5.7, 23.5), (5.7, 23.5))
    for pattern in PCB_PATTERNS.values():
        assert pattern.datum and pattern.source.startswith('https://datasheets.raspberrypi.com/')
        assert pcb_board(pattern.width, pattern.length, 1.6, pattern.holes, pattern.hole_d).is_valid
    with pytest.raises(ValueError, match='PCB model'):
        pcb_mounting_pattern('esp32')
    assert get('pcb-board').name == 'pcb_standoff'
    assert get('pcb_mounting_pattern').name == 'pcb_standoff'
    assert '`pcb_standoff`' in index()


def test_pcb_recipe_available_through_existing_cli_tool_and_resource(capsys):
    from b123d_print.cli import main
    from b123d_print.mcp_server import recipe, recipe_text

    assert main(['recipes', 'pcb_standoff']) == 0
    assert 'pcb_mounting_pattern' in capsys.readouterr().out
    assert '`pcb_standoff`' in recipe()
    assert recipe('pcb_board') == recipe_text('pcb_standoff') == get('pcb_standoff').text()


def test_documented_enclosure_fixture_builds_checks_and_makes_template(tmp_path):
    import re
    from pathlib import Path
    from b123d_print.project import load, run_checks

    docs = (Path(__file__).parents[1] / 'docs/using/recipes.md').read_text(encoding='utf-8')
    snippet = next(code for code in re.findall(r'```python\n(.*?)```', docs, re.S)
                   if 'class Dims:' in code)
    script = tmp_path / 'pcb_fixture.py'
    script.write_text(snippet, encoding='utf-8')
    mod = load(script)
    findings = run_checks(mod, '', Settings(), nudge=False)
    assert not [f.line() for f in findings if f.level == ck.FAIL]
    d = mod.Dims()
    spec, = mod.templates(d)
    template = slice_template(mod.base(d), spec.plane, spec.at, thickness=spec.thickness, label=None)
    assert template.part.is_valid and len(ck.holes(template.part)) == len(d.HOLES)


def test_copied_recipe_code_and_example_run_without_hidden_globals():
    import re

    text = get('pcb_standoff').text()
    code = re.search(r'## Code.*?```python\n(.*?)```', text, re.S).group(1)
    demo = re.search(r'## Example.*?```python\n(.*?)```', text, re.S).group(1)
    namespace = {}
    exec(code, namespace)
    exec(demo, namespace)
    assert namespace['demo_pcb_standoff']().is_valid
    post = namespace['pcb_standoff'](5, 7, 2.5, 4)
    assert post.is_valid
    pattern = namespace['pcb_mounting_pattern']('raspberry_pi_pico_rev3')
    assert namespace['pcb_board'](pattern.width, pattern.length, 1.6, pattern.holes, pattern.hole_d).is_valid
