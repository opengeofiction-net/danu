"""Burning a river into the terrain, through the contours - G7b, R25.
No Qt, no GDAL.

A river running east, crossing north-south contours at known places, so the
climb, the contour that makes it and what the burn does with it can each be
read off by hand.
"""

import pytest

from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet
from danu.water import burn

A = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540                      # a metre north
_ids = iter(range(1000, 10**6))
RIVER = [(125.30 + 0.0025 * k, LAT) for k in range(41)]      # 125.30 .. 125.40, every ~250 m


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def way(sq, pts, ele, closed=False):
    refs = []
    for lon, lat in pts:
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
        refs.append(i)
    if closed:
        refs.append(refs[0])
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags={'ele': str(ele)})
    return sq.ways[i]


def ns(sq, lon, ele):
    """A contour running north-south across the river."""
    return way(sq, [(lon, LAT - 0.02), (lon, LAT + 0.02)], ele)


def descent(sq):
    """100 m, 75 m and 50 m crossing it in order: the river runs east and down."""
    ns(sq, 125.31, 100)
    ns(sq, 125.33, 75)
    ns(sq, 125.39, 50)


def run(w, sq, **kw):
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s), **kw)
    for s, cmd in p.steps:
        cmd.apply(s)
    return p


def lats_of(sq, w_):
    return [sq.nodes[r].lat for r in w_.refs]


def test_a_fingers_tip_the_river_cuts_across_becomes_its_own_closed_contour():
    """A ridge's 100 m finger reaching south across the river between the 75 m
    and the 50 m: the river climbs onto it. The finger is cut at the river and
    each piece closed along its own bank, 50 m back."""
    w, sq = ws()
    descent(sq)
    finger = way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.355, LAT - 0.01),
                      (125.355, LAT + 0.02)], 100)
    p = run(w, sq)
    assert p.burned == 1 and p.skipped == []
    pieces = [x for x in sq.ways.values() if x.tags['ele'] == '100' and
              min(sq.nodes[r].lon for r in x.refs) > 125.34]
    assert len(pieces) == 2, [x.refs for x in pieces]
    main = next(x for x in pieces if x.refs[0] != x.refs[-1])
    tip = next(x for x in pieces if x.refs[0] == x.refs[-1])
    assert main.id == finger.id, 'the main line should keep the way'
    # the main line now stays 50 m north of the river, the tip 50 m south
    assert min(lats_of(sq, main)) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    assert max(lats_of(sq, tip)) == pytest.approx(LAT - 50 * M_LAT, abs=1e-6)
    assert min(lats_of(sq, tip)) == pytest.approx(LAT - 0.01)
    # and neither crosses the river now
    p2 = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    assert p2.burned == 0


def test_a_hill_the_river_runs_into_and_out_of_is_cut_in_two():
    w, sq = ws()
    descent(sq)
    hill = way(sq, [(125.345, LAT - 0.02), (125.355, LAT - 0.02), (125.355, LAT + 0.02),
                    (125.345, LAT + 0.02)], 100, closed=True)
    p = run(w, sq)
    assert p.burned == 1
    rings = [x for x in sq.ways.values() if x.tags['ele'] == '100' and x.refs[0] == x.refs[-1]]
    assert len(rings) == 2, 'the hill was not cut in two'
    north = next(x for x in rings if min(lats_of(sq, x)) > LAT)
    south = next(x for x in rings if max(lats_of(sq, x)) < LAT)
    assert min(lats_of(sq, north)) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    assert max(lats_of(sq, south)) == pytest.approx(LAT - 50 * M_LAT, abs=1e-6)
    assert hill.id in {north.id, south.id}


def test_a_bump_too_thin_for_the_setback_is_dropped_and_said():
    """A stream along a contour, a bump of it 30 m across the water: set back
    50 m, nothing of the bump is left."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 30 * M_LAT), (125.355, LAT - 30 * M_LAT),
             (125.355, LAT + 0.02)], 100)
    p = run(w, sq)
    assert p.burned == 1 and len(p.dropped) == 1
    pieces = [x for x in sq.ways.values() if x.tags['ele'] == '100' and
              min(sq.nodes[r].lon for r in x.refs) > 125.34]
    assert len(pieces) == 1 and pieces[0].refs[0] != pieces[0].refs[-1]
    assert min(lats_of(sq, pieces[0])) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)


def test_a_contour_that_crosses_the_river_only_once_is_not_burned_and_said():
    w, sq = ws()
    descent(sq)
    ns(sq, 125.35, 100)                                  # a spur: once, in the wrong place
    p = run(w, sq)
    assert p.burned == 0 and p.steps == []
    assert any('only here' in why for why, _, _ in p.skipped)


def test_a_cut_that_would_cross_another_contour_is_left_and_said():
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.355, LAT - 0.01),
             (125.355, LAT + 0.02)], 100)
    way(sq, [(125.35, LAT + 30 * M_LAT), (125.35, LAT + 0.005)], 90)   # where the north bank line goes
    p = run(w, sq)
    assert p.burned == 0
    assert any('would cross the 90 m contour' in why for why, _, _ in p.skipped)


def test_the_setback_is_the_strength():
    w, sq = ws()
    descent(sq)
    finger = way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.355, LAT - 0.01),
                      (125.355, LAT + 0.02)], 100)
    run(w, sq, setback_m=200)
    assert min(lats_of(sq, sq.ways[finger.id])) == pytest.approx(LAT + 200 * M_LAT, abs=1e-6)


def test_only_burns_the_one_climb_asked_for():
    w, sq = ws()
    descent(sq)
    # two 100 m fingers with a 75 m between: the river climbs onto each
    fingers = [way(sq, [(lon, LAT + 0.02), (lon, LAT - 0.01), (lon + 0.004, LAT - 0.01),
                        (lon + 0.004, LAT + 0.02)], 100) for lon in (125.335, 125.351)]
    ns(sq, 125.3455, 75)
    places = burn.climbs(w, RIVER)
    assert len(places) == 2, 'two climbs expected'
    for place, (asked, other) in zip(places, (fingers, fingers[::-1]), strict=True):
        one = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s), only=place)
        cut = {c.way_id for _, compound in one.steps for c in compound.commands}
        assert one.burned == 1 and asked.id in cut and other.id not in cut


def test_a_burn_and_its_undo_leave_the_square_as_it_was():
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.355, LAT - 0.01),
             (125.355, LAT + 0.02)], 100)
    before = edits.snapshot(sq)
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    for s, cmd in p.steps:
        cmd.apply(s)
    assert edits.snapshot(sq) != before
    for s, cmd in reversed(p.steps):
        cmd.undo(s)
    assert edits.snapshot(sq) == before


def test_a_finger_drawn_the_other_way_round_is_cut_the_same():
    """Which bank is which is judged against the bank line, which runs from
    one crossing to the other in the contour's order - not the river's."""
    w, sq = ws()
    descent(sq)
    finger = way(sq, [(125.355, LAT + 0.02), (125.355, LAT - 0.01), (125.345, LAT - 0.01),
                      (125.345, LAT + 0.02)], 100)
    run(w, sq)
    assert min(lats_of(sq, sq.ways[finger.id])) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    tip = next(x for x in sq.ways.values() if x.refs[0] == x.refs[-1] and x.tags['ele'] == '100')
    assert max(lats_of(sq, tip)) == pytest.approx(LAT - 50 * M_LAT, abs=1e-6)


# ------------------------------------------------------------- a whole spur

def spur(sq):
    """A ridge's spur reaching south across the river: the 100 m finger, and
    the 125 m inside it - the river runs over both."""
    outer = way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
                     (125.365, LAT + 0.02)], 100)
    inner = way(sq, [(125.3505, LAT + 0.02), (125.3505, LAT - 0.005), (125.3595, LAT - 0.005),
                     (125.3595, LAT + 0.02)], 125)
    return outer, inner


def test_a_spur_is_cut_whole_each_contour_set_back_a_step_further():
    """Cutting only the outer finger cannot work: its bank line would cross
    the 125 m inside it. Each is cut, the 100 m set back d and the 125 m 2d -
    a notch through the spur, its sides one contour every d."""
    w, sq = ws()
    descent(sq)
    outer, inner = spur(sq)
    p = run(w, sq)
    assert p.burned == 1 and p.contours_cut == 2, p.skipped
    assert min(lats_of(sq, sq.ways[outer.id])) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    assert min(lats_of(sq, sq.ways[inner.id])) == pytest.approx(LAT + 100 * M_LAT, abs=1e-6)
    tips = [x for x in sq.ways.values() if x.refs[0] == x.refs[-1]]
    assert sorted(x.tags['ele'] for x in tips) == ['100', '125']
    tip125 = next(x for x in tips if x.tags['ele'] == '125')
    assert max(lats_of(sq, tip125)) == pytest.approx(LAT - 100 * M_LAT, abs=1e-6)


def test_the_setback_is_metres_per_contour_step():
    w, sq = ws()
    descent(sq)
    outer, inner = spur(sq)
    run(w, sq, setback_m=80)
    assert min(lats_of(sq, sq.ways[outer.id])) == pytest.approx(LAT + 80 * M_LAT, abs=1e-6)
    assert min(lats_of(sq, sq.ways[inner.id])) == pytest.approx(LAT + 160 * M_LAT, abs=1e-6)


def test_a_lower_contour_inside_the_stretch_is_another_climb_burned_first():
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
             (125.365, LAT + 0.02)], 100)
    way(sq, [(125.352, LAT + 0.02), (125.352, LAT - 0.005), (125.358, LAT - 0.005),
             (125.358, LAT + 0.02)], 75)                      # lower, inside it
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    assert any('another climb' in why for why, _, _ in p.skipped)


def test_a_higher_contour_near_the_river_is_pushed_back_to_its_setback():
    """The 125 m runs 30 m north of the river without crossing it: the 100 m
    finger's cut line, 50 m back, would run into it. It is pushed back to
    100 m - its own setback, a step further."""
    w, sq = ws()
    descent(sq)
    finger = way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
                      (125.365, LAT + 0.02)], 100)
    near = way(sq, [(125.351, LAT + 0.02), (125.351, LAT + 30 * M_LAT), (125.359, LAT + 30 * M_LAT),
                    (125.359, LAT + 0.02)], 125)
    p = run(w, sq)
    assert p.burned == 1 and p.pushed == 1, p.skipped
    assert min(lats_of(sq, sq.ways[near.id])) == pytest.approx(LAT + 100 * M_LAT, abs=1e-6)
    assert min(lats_of(sq, sq.ways[finger.id])) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)


def test_a_spurs_inner_contour_wholly_inside_the_notch_is_cut_away():
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
             (125.365, LAT + 0.02)], 100)
    knoll = way(sq, [(125.354, LAT - 40 * M_LAT), (125.356, LAT - 40 * M_LAT), (125.356, LAT + 40 * M_LAT),
                     (125.354, LAT + 40 * M_LAT)], 125, closed=True)        # a knoll the river runs over
    p = run(w, sq)
    assert p.burned == 1, p.skipped
    assert knoll.id not in sq.ways and len(p.dropped) >= 1


# ------------------------------------------------- contacts, PR 108's review

def test_a_contour_snapped_along_the_river_is_one_crossing_and_a_touch_none():
    """It shares three of the river's nodes in a row and goes over: one
    crossing. Another touches one node and turns back: none. Counted node by
    node, the first crossed three times and the burn refused its spur."""
    w, sq = ws()
    snapped = way(sq, [(125.3475, LAT + 0.01), *[(125.30 + 0.0025 * k, LAT) for k in (19, 20, 21)],
                       (125.3525, LAT - 0.01)], 100)
    touch = way(sq, [(125.36, LAT + 0.01), (125.3625, LAT), (125.365, LAT + 0.01)], 75)
    _, _, _, crossings, _ = burn._crossings(w, RIVER, 0)
    assert [c.key[1] for c in crossings] == [snapped.id], [(c.key[1], round(c.r)) for c in crossings]
    assert touch.id not in {c.key[1] for c in crossings}


def test_a_vertex_on_the_river_is_skipped_and_the_rest_still_pushed():
    import numpy as np
    bank = np.array([[0.0, 0.0], [100.0, 0.0]])
    P = np.array([[10.0, 0.0], [20.0, 10.0], [30.0, 80.0]])          # on it, near it, clear of it
    push = burn._push(bank, P, 50.0)
    assert push is not None and set(push) == {1}, push
    assert push[1][1] == pytest.approx(50.0)


def test_a_hills_strike_through_is_what_is_replaced_not_half_the_ring():
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT - 0.02), (125.355, LAT - 0.02), (125.355, LAT + 0.02),
             (125.345, LAT + 0.02)], 100, closed=True)
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    assert len(p.removed) == 2
    for run_ in p.removed:
        lons = {round(lon, 4) for lon, _ in run_}
        assert len(lons) == 1, f'a strike-through runs across the hill: {run_}'


def test_the_strike_through_takes_in_the_vertices_the_setback_drops():
    """Vertices 20 m either side of the river are within the 50 m setback and
    go; the strike-through reaches out to the first kept on either side."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT - 0.02), (125.355, LAT - 0.02), (125.355, LAT - 20 * M_LAT),
             (125.355, LAT + 20 * M_LAT), (125.355, LAT + 0.02), (125.345, LAT + 0.02)], 100, closed=True)
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    east = next(r for r in p.removed if all(round(lon, 4) == 125.355 for lon, _ in r))
    lats = sorted(lat for _, lat in east)
    assert lats[0] == pytest.approx(LAT - 0.02) and lats[-1] == pytest.approx(LAT + 0.02), lats
