"""danu.core.ladder: the ladder a square describes, and the elevation it drives."""

import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from danu.core import edits, ladder as L
from danu.core.square import Square, SquareName, read_square

GOLDEN = Path(__file__).parent / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'
GOBRAS = Path(__file__).parent / 'fixtures' / 'N20E086_ele_census.json'   # ways per ele; the square is 20 MB


def square_with(elevations, name=SquareName(10, 10)) -> Square:
    """A square with one straight contour per value given (repeats allowed:
    each is another way at that elevation)."""
    sq = Square(name=name, present=True, attrs={})
    alloc = edits.IdAllocator(sq)
    for i, ele in enumerate(elevations):
        lat = 10.01 + i * 0.001
        edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(10.1, lat), (10.2, lat)], {'ele': L.format_ele(ele)}).apply(sq)
    return sq


# ------------------------------------------------------------ inference

def test_the_fixture_is_a_50_m_ladder_on_the_1_phase_with_an_irregular_tail():
    lad = L.infer(read_square(GOLDEN))
    assert lad.interval == 50 and lad.phase == 1 and lad.source == 'inferred' and lad.square == 'S24E125'
    assert all(v in lad.notches for v in (101, 145, 149, 151, 153, 155, 951))   # what exists is a notch
    assert lad.high == 951 + 4 * 50                                             # continued above
    assert lad.low == 0 and 1 in lad.notches and 51 in lad.notches              # and down to sea level
    assert lad.regular(301) and not lad.regular(300) and not lad.regular(145)


def test_gobras_reads_as_the_spec_describes_it():
    census = json.loads(GOBRAS.read_text())['ways']
    sq = square_with([float(e) for e, n in census.items() for _ in range(n)], SquareName(86, 20))
    assert len(list(sq.contours())) == 2807 and sq.elevations()[-1] == 1075
    lad = L.infer(sq)
    assert lad.interval == 25 and lad.phase == 0
    below = [n for n in lad.notches if n < 100]
    assert below == [0, 3, 5, 7, 9, 10, 12, 13, 15, 20, 25, 30, 35, 40, 43, 50, 55, 60, 70, 75, 85, 87, 90, 91, 93, 95]
    assert [n for n in lad.notches if 100 <= n <= 1075 and lad.regular(n)] == list(range(100, 1100, 25))
    assert lad.high == 1075 + 4 * 25
    advice = {a.value: a for a in L.off_ladder(sq, lad)}
    assert advice[113].describe() == '113 m used once between 110 and 115'
    assert advice[135].describe() == '135 m used once between 125 and 150'
    assert {43, 55, 87, 91} <= set(advice)
    assert 100 not in advice and 110 not in advice                # on the ladder, or well used


def test_holes_in_the_regular_run_are_filled_and_the_tail_is_followed():
    lad = L.infer(square_with([100, 125, 175, 200, 3, 7]))       # 150 missing
    assert lad.interval == 25 and 150 in lad.notches
    assert [n for n in lad.notches if n < 100] == [0, 3, 7, 25, 50, 75]


def test_a_tie_between_gaps_goes_to_the_better_used_then_the_wider():
    # gaps 10 and 20 twice each; the 20s carry more contours
    sq = square_with([0, 10, 20, 40, 60] + [40, 60, 60])
    assert L.infer(sq).interval == 20
    assert L.infer(square_with([0, 10, 20, 40, 60])).interval == 20


def test_fewer_than_two_values_infers_nothing():
    assert L.infer(square_with([])) is None
    assert L.infer(square_with([100, 100])) is None


@settings(max_examples=200, deadline=None)
@given(interval=st.integers(1, 100), base=st.integers(0, 99), count=st.integers(3, 30),
       start=st.integers(0, 20))
def test_a_synthetic_ladder_reads_back_as_itself(interval, base, count, start):
    """The spec's property: ladder inference on a synthetic ladder returns that ladder."""
    values = [base + (start + i) * interval for i in range(count)]
    lad = L.infer(square_with(values))
    assert lad.interval == interval
    assert all(lad.regular(v) for v in values)
    rungs = [n for n in lad.notches if n >= values[0]]
    assert rungs[:count] == [float(v) for v in values]                       # notch for notch
    assert rungs[count:] == [float(values[-1] + k * interval) for k in range(1, L.EXTEND_ABOVE + 1)]
    assert lad.low == 0 and all(lad.regular(n) or n == 0 for n in lad.notches)


# -------------------------------------------------------------- ladder

def test_moves_along_the_notches():
    lad = L.regular_ladder(25, 0, 100)
    assert lad.notches == (0, 25, 50, 75, 100)
    assert lad.above(30) == 50 and lad.below(30) == 25 and lad.above(100) is None and lad.below(0) is None
    assert lad.above(25) == 50 and lad.below(25) == 0
    assert lad.nearest(37) == 25 and lad.nearest(38) == 50 and lad.index(75) == 3 and lad.index(76) is None


def test_covering_extends_along_the_spacing_and_keeps_bare_values_bare():
    lad = L.regular_ladder(25, 0, 100)
    assert lad.covering(160).notches == (0, 25, 50, 75, 100, 125, 150, 160)
    assert lad.covering(-30).notches == (-30, -25, 0, 25, 50, 75, 100)
    assert lad.covering(50) is lad
    bare = L.Ladder((10, 20, 30))
    assert bare.covering(55).notches == (10, 20, 30, 55) and not bare.regular(55) and bare.regular(20)


def test_a_regular_ladder_starts_below_sea_level_when_its_phase_is_not_zero():
    assert L.regular_ladder(50, 1, 151).notches == (-49, 1, 51, 101, 151)
    with pytest.raises(ValueError):
        L.regular_ladder(0)
    with pytest.raises(ValueError):
        L.Ladder((3, 2))


def test_format_ele():
    assert L.format_ele(125.0) == '125' and L.format_ele(12.5) == '12.5' and L.format_ele(-3) == '-3'
    assert L.format_ele(0.1 + 0.2) == '0.3' and L.format_ele(1e-05) == '0'


# ----------------------------------------------------------- overrides

TOML = '''
[zone."gobras"]
interval = 25
top = 500

[square."gobras/N20E086"]
values = [0, 5, 10, 25]
'''


def test_overrides_read_and_round_trip(tmp_path):
    ov = L.Overrides.loads(TOML)
    assert ov.for_zone('gobras').notches == tuple(range(0, 501, 25)) and ov.for_zone('gobras').source == 'zone'
    assert ov.for_square('gobras', 'N20E086').notches == (0, 5, 10, 25)
    assert ov.for_square('gobras', 'N21E086') is None and ov.for_zone('roantra') is None
    path = tmp_path / 'ladders.toml'
    ov.save(path)
    again = L.Overrides.load(path)
    assert again == ov
    assert L.Overrides.load(tmp_path / 'missing.toml') == L.Overrides()


def test_a_spec_is_an_interval_or_values_not_both():
    with pytest.raises(ValueError):
        L.LadderSpec()
    with pytest.raises(ValueError):
        L.LadderSpec(interval=10, values=(1, 2))
    with pytest.raises(ValueError, match=r'\[zone."gobras"\]'):        # a typo names its table
        L.Overrides.loads('[zone."gobras"]\nintervall = 25\n')


def test_the_order_is_square_override_then_inference_then_zone_then_default():
    ov = L.Overrides.loads(TOML)
    full = square_with([100, 125, 150], SquareName(86, 20))
    assert L.ladder_for(full, 'gobras', ov).source == 'square'
    assert L.ladder_for(full, 'roantra', ov).source == 'inferred'
    blank = square_with([], SquareName(87, 20))
    assert L.ladder_for(blank, 'gobras', ov).source == 'zone'
    default = L.ladder_for(blank, 'roantra', ov)
    assert default.source == 'default' and default.interval == 10 and default.high == 200
    assert L.ladder_for(blank, 'roantra').square == 'N20E087'


# ----------------------------------------------------------- elevation

def test_keys_step_in_metres_and_the_notches_are_separate():
    ev = L.Elevation(L.regular_ladder(25, 0, 100), small=10, big=50)
    seen = []
    ev.listen(seen.append)
    assert ev.value == 0
    ev.step(); ev.step(big=True); ev.step(down=True); ev.nudge(); ev.nudge(down=True); ev.nudge(down=True)
    assert seen == [10, 60, 50, 51, 50, 49]
    ev.next_notch(); assert ev.value == 50
    ev.prev_notch(); assert ev.value == 25
    ev.sea_level(); assert ev.value == 0
    ev.prev_notch(); assert ev.value == 0                     # nothing below
    ev.pick_up(None); assert ev.value == 0
    ev.pick_up(137.0); assert ev.value == 137 and ev.tag == '137'
    assert ev.ladder.notches[-2:] == (125, 137)               # the slider can still show it


def test_a_new_ladder_keeps_the_value():
    ev = L.Elevation(L.regular_ladder(25, 0, 100), value=60)
    ev.set_ladder(L.regular_ladder(10, 0, 50))
    assert ev.value == 60 and ev.ladder.high == 60 and ev.ladder.interval == 10
