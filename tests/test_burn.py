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
    assert any('crosses the river only once' in why for why, _, _ in p.skipped)


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
    assert p.burned == 2 and p.contours_cut == 2, p.skipped          # the climbs onto each, one run
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


def test_a_lower_contour_inside_the_finger_is_refused():
    """The 75 m inside the 100 m finger: the river is back down to 75 m
    before the finger's second crossing - nothing a cut can mend."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
             (125.365, LAT + 0.02)], 100)
    way(sq, [(125.352, LAT + 0.02), (125.352, LAT - 0.005), (125.358, LAT - 0.005),
             (125.358, LAT + 0.02)], 75)                      # lower, inside it
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    assert p.burned == 0
    assert any('100 m contour crosses the river only once before it is back down to 75 m' in why
               for why, _, _ in p.skipped)


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
    assert p.burned == 2, p.skipped
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
    go; the strike-through runs from rim to rim, 50 m either side, through
    them."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT - 0.02), (125.355, LAT - 0.02), (125.355, LAT - 20 * M_LAT),
             (125.355, LAT + 20 * M_LAT), (125.355, LAT + 0.02), (125.345, LAT + 0.02)], 100, closed=True)
    p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s))
    east = next(r for r in p.removed if all(round(lon, 4) == 125.355 for lon, _ in r))
    lats = sorted(lat for _, lat in east)
    assert len(lats) == 4, lats
    assert lats[0] == pytest.approx(LAT - 50 * M_LAT, abs=1e-6)
    assert lats[-1] == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)


def test_a_contour_crossing_on_its_first_segment_is_a_crossing_and_one_ending_on_the_river_not():
    """In metres, exactly: the river along y = 0 with a vertex at (10, 0); a
    contour whose first segment passes through that vertex a tenth of the way
    along goes over there. Half a segment back from it is before the contour
    starts, which once dropped it as a contour ending on the river."""
    import numpy as np
    R = np.array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]])
    dist = burn._along(R)
    over = np.array([[9.0, 1.0], [19.0, -9.0], [19.0, -30.0]])
    ((r, s_),) = burn._contacts(R, dist, over)
    assert r == pytest.approx(10.0) and s_ == pytest.approx(0.1)
    ends = np.array([[5.0, 20.0], [10.0, 0.0]])                     # stops on the river
    assert burn._contacts(R, dist, ends) == []


# ------------------------------------------------- a run burned whole, #110

def test_any_climb_of_a_run_burns_the_whole_run():
    """The river climbs onto the 100 m and on onto the 125 m inside it: two
    climbs, one run. Either asked for burns both - burned one at a time,
    the first's cut ran into the other."""
    w, sq = ws()
    descent(sq)
    spur(sq)
    places = burn.climbs(w, RIVER)
    assert len(places) == 2
    for place in places:
        p = burn.plan(w, RIVER, lambda s: edits.IdAllocator(s), only=place)
        assert p.burned == 2 and p.contours_cut == 2, p.skipped


def crosses_between(w, lon0, lon1):
    """The contours crossing the river between two longitudes."""
    proj, R, _, crossings, dist = burn._crossings(w, RIVER, 0)
    return [c for c in crossings if lon0 < proj.back(burn._at(R, dist, c.r))[0] < lon1]


def test_a_contour_weaving_across_the_river_is_cut_at_every_crossing():
    """The 125 m crosses four times inside the run, dipping 40 m north of the
    river between - under its setback. All of it nearer than 100 m goes: the
    line north is set back the whole way, and each lobe south is a ring."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.375, LAT - 0.01),
             (125.375, LAT + 0.02)], 100)
    weave = way(sq, [(125.35, LAT + 0.02), (125.35, LAT - 0.005), (125.355, LAT - 0.005),
                     (125.355, LAT + 40 * M_LAT), (125.36, LAT + 40 * M_LAT), (125.36, LAT - 0.005),
                     (125.37, LAT - 0.005), (125.37, LAT + 0.02)], 125)
    p = run(w, sq)
    assert p.burned >= 1 and p.contours_cut == 2, p.skipped
    assert crosses_between(w, 125.33, 125.39) == []
    pieces = [x for x in sq.ways.values() if x.tags['ele'] == '125']
    rings = [x for x in pieces if x.refs[0] == x.refs[-1]]
    (line,) = [x for x in pieces if x.refs[0] != x.refs[-1]]
    assert line.id == weave.id and len(rings) == 2
    assert min(lats_of(sq, line)) == pytest.approx(LAT + 100 * M_LAT, abs=1e-6)
    assert all(max(lats_of(sq, r)) == pytest.approx(LAT - 100 * M_LAT, abs=1e-6) for r in rings)


def test_a_contour_touching_the_river_without_crossing_it_is_cut_round():
    """The hill's south side comes up to the river in a V and touches it at
    one of its nodes - on gobras the Bosco's 100 m. The V's tip goes, and
    the hill south of the river is two rings either side of it."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT - 0.02), (125.353, LAT - 0.02), (125.355, LAT), (125.357, LAT - 0.02),
             (125.365, LAT - 0.02), (125.365, LAT + 0.02), (125.345, LAT + 0.02)], 100, closed=True)
    p = run(w, sq)
    assert p.burned == 1, p.skipped
    rings = [x for x in sq.ways.values() if x.tags['ele'] == '100' and x.refs[0] == x.refs[-1]]
    assert len(rings) == 3
    assert crosses_between(w, 125.33, 125.39) == []
    north = [r for r in rings if min(lats_of(sq, r)) > LAT]
    assert len(north) == 1 and min(lats_of(sq, north[0])) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    for r in rings:
        if r is not north[0]:
            assert max(lats_of(sq, r)) <= LAT - 50 * M_LAT + 1e-6


def test_the_rim_inside_a_bend_tighter_than_the_setback_does_not_fold_back():
    """Offset 250 m inside a bend of 100 m the line loops back on itself;
    those points are nearer the river than 250 m, and not on the rim."""
    import numpy as np
    stretch = np.array([[0.0, 0.0], [300.0, 0.0], [400.0, 100.0], [400.0, 400.0]])
    rim = burn._Rim(stretch, 250.0)
    left = rim.path(1, rim.L - 1)                   # the stretch turns left: its inside
    assert (burn._distance(stretch, left) >= 250 * 0.995).all()


def test_a_river_that_never_comes_back_down_is_not_burned_and_said():
    w, sq = ws()
    ns(sq, 125.31, 100)
    ns(sq, 125.33, 75)
    ns(sq, 125.35, 100)                                   # and nothing below it after
    p = run(w, sq)
    assert p.burned == 0
    assert any('never comes back down to 75 m' in why for why, _, _ in p.skipped), p.skipped


def test_a_rim_may_cross_a_contour_its_own_contour_crossed_before():
    """A rogue 60 m already crosses the finger; the finger's rim crosses it
    too. Not the burn's to refuse - that pair was crossing before it."""
    w, sq = ws()
    descent(sq)
    way(sq, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.355, LAT - 0.01),
             (125.355, LAT + 0.02)], 100)
    way(sq, [(125.34, LAT + 0.005), (125.35, LAT + 30 * M_LAT)], 60)
    p = run(w, sq)
    assert p.burned == 1, p.skipped


def test_a_rim_that_would_cross_the_river_where_it_comes_back_is_refused():
    """A hairpin: the river comes back west 130 m north of the run. The
    125 m between, set back 160 m, would be closed across it."""
    hairpin = [(125.30 + 0.0025 * k, LAT) for k in range(41)] + \
              [(125.30 + 0.0025 * k, LAT + 130 * M_LAT) for k in range(40, 7, -1)] + [(125.32, LAT + 0.02)]
    w, sq = ws()
    for lon, ele in ((125.31, 100), (125.33, 75), (125.39, 50)):
        way(sq, [(lon, LAT - 0.02), (lon, LAT + 40 * M_LAT)], ele)
    way(sq, [(125.345, LAT - 0.02), (125.345, LAT + 20 * M_LAT), (125.355, LAT + 20 * M_LAT),
             (125.355, LAT - 0.02)], 100)
    way(sq, [(125.30, LAT + 60 * M_LAT), (125.395, LAT + 60 * M_LAT)], 125)
    p = burn.plan(w, hairpin, lambda s: edits.IdAllocator(s), setback_m=80)
    assert p.burned == 0
    assert any('125 m contour would cross the river' in why for why, _, _ in p.skipped), p.skipped
