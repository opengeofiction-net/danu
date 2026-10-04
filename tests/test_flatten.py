"""Flattening a lake through the contours - G7a, R26. No Qt, no GDAL.

A square lake four kilometres across, laid out by hand, and contours placed
inside it, across it, at its level and away from it, so every cut and every
pull-back is one the test can measure.
"""

import math

import pytest

from danu.core import edits
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, WorkingSet
from danu.water import flatten

A = SquareName(125, -23)
LAT = -22.48                                 # the lake's middle
KX = 111320 * math.cos(math.radians(LAT))
_ids = iter(range(1000, 100000))


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def node(sq, lon, lat):
    i = next(_ids)
    sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
    return i


def way(sq, pts, tags, closed=False):
    refs = [node(sq, lon, lat) for lon, lat in pts]
    if closed:
        refs.append(refs[0])
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags=dict(tags))
    return sq.ways[i]


def box(lon0, lat0, d):
    return [(lon0, lat0), (lon0 + d, lat0), (lon0 + d, lat0 + d), (lon0, lat0 + d)]


def lake(sq, level='100'):
    """Closed way, 125.50..125.54 by -22.50..-22.46."""
    tags = {'natural': 'water'} | ({'ele': level} if level is not None else {})
    return way(sq, box(125.50, -22.50, 0.04), tags, closed=True)


def contour(sq, pts, ele, closed=False):
    return way(sq, pts, {'ele': str(ele)}, closed=closed)


def allocator(square):
    alloc = {}

    def get(sq):
        return alloc.setdefault(sq.name, edits.IdAllocator(sq))
    return get


def run(w, sq, feature, **kw):
    p = flatten.plan(w, sq, feature, allocator(sq), **kw)
    for s, cmd in p.steps:
        cmd.apply(s)
    return p


def ends(sq, wid):
    w = sq.ways[wid]
    return sq.nodes[w.refs[0]], sq.nodes[w.refs[-1]]


def contours(sq, ele):
    return [w for w in sq.ways.values() if w.tags.get('ele') == str(ele) and 'natural' not in w.tags
            and flatten.FILL not in w.tags]


# ------------------------------------------------------------------ contours

def test_a_contour_inside_the_water_is_deleted():
    w, sq = ws()
    lk = lake(sq)
    inner = contour(sq, box(125.51, -22.49, 0.01), 90, closed=True)
    p = run(w, sq, lk)
    assert inner.id not in sq.ways and p.deleted == 1
    assert not any(r in sq.nodes for r in inner.refs), 'its nodes were left behind'


def test_a_contour_crossing_at_another_level_is_clipped_and_drawn_back():
    w, sq = ws()
    lk = lake(sq)
    c = contour(sq, [(125.45, LAT), (125.59, LAT)], 120)
    p = run(w, sq, lk, pull_back_m=100)
    pieces = contours(sq, 120)
    assert len(pieces) == 2 and p.pulled == 1
    west = min(pieces, key=lambda x: sq.nodes[x.refs[0]].lon)
    east = max(pieces, key=lambda x: sq.nodes[x.refs[0]].lon)
    # each end 100 m short of the shore, measured along the contour
    gap_w = (125.50 - max(n.lon for n in ends(sq, west.id))) * KX
    gap_e = (min(n.lon for n in ends(sq, east.id)) - 125.54) * KX
    assert gap_w == pytest.approx(100, abs=0.5) and gap_e == pytest.approx(100, abs=0.5)
    assert c.id in sq.ways, 'the first piece should keep the way'


def test_a_contour_at_the_lakes_level_is_clipped_at_the_shore_and_left_touching_it():
    w, sq = ws()
    lk = lake(sq)
    contour(sq, [(125.45, LAT), (125.59, LAT)], 100)
    p = run(w, sq, lk, pull_back_m=100)
    pieces = contours(sq, 100)
    assert len(pieces) == 2 and p.clipped == 1 and p.pulled == 0
    lons = sorted(n.lon for x in pieces for n in ends(sq, x.id))
    assert lons[1] == pytest.approx(125.50, abs=1e-9) and lons[2] == pytest.approx(125.54, abs=1e-9)


def test_a_contour_away_from_the_water_is_untouched():
    w, sq = ws()
    lk = lake(sq)
    far = contour(sq, [(125.70, -22.70), (125.80, -22.70)], 150)
    before = list(far.refs)
    p = run(w, sq, lk)
    assert sq.ways[far.id].refs == before
    assert not any(far.id in cmd.ways(s) for s, cmd in p.steps)


def test_a_piece_shorter_than_the_pull_back_goes():
    """Across a corner of the lake: what is left outside between the two
    crossings and the end is under 100 m."""
    w, sq = ws()
    lk = lake(sq)
    contour(sq, [(125.4995, -22.49), (125.51, -22.49)], 120)
    p = run(w, sq, lk, pull_back_m=100)
    assert contours(sq, 120) == [] and p.deleted == 1


def test_a_closed_contour_cut_open_is_one_piece_across_its_closing_vertex():
    """A ring that dips into the lake: the two runs either side of where the
    way closes are one stretch of ground, and one way afterwards."""
    w, sq = ws()
    lk = lake(sq)
    # closes at its south-west corner, outside; its east side runs through the water
    contour(sq, [(125.45, -22.52), (125.52, -22.52), (125.52, -22.44), (125.45, -22.44)], 120, closed=True)
    run(w, sq, lk, pull_back_m=100)
    pieces = contours(sq, 120)
    assert len(pieces) == 1, [p.refs for p in pieces]
    a, b = ends(sq, pieces[0].id)
    # both ends on its east side, 100 m beyond the lake's north and south shores
    assert a.lon == pytest.approx(125.52) and b.lon == pytest.approx(125.52)
    lats = sorted((a.lat, b.lat))
    assert lats[0] == pytest.approx(-22.50 - 100 / 110540, abs=1e-6)
    assert lats[1] == pytest.approx(-22.46 + 100 / 110540, abs=1e-6)


def test_a_contour_sharing_a_node_with_the_shore_is_cut_there_once():
    w, sq = ws()
    lk = lake(sq)
    corner = lk.refs[0]                                  # 125.50, -22.50
    c = contour(sq, [(125.48, -22.52), (125.50, -22.50)], 100)
    c.refs[-1] = corner                                  # snapped to the shore
    run(w, sq, lk)
    assert sq.ways[c.id].refs[-1] == corner, 'a contour at the level that met the shore was cut back'


# ------------------------------------------------------------------ outline

def test_the_level_goes_on_a_relations_member_ways_and_an_island_keeps_its_ground():
    w, sq = ws()
    outer = way(sq, box(125.50, -22.50, 0.04), {}, closed=True)
    inner = way(sq, box(125.51, -22.49, 0.02), {}, closed=True)
    sq.relations[1] = Relation(id=1, tags={'natural': 'water', 'type': 'multipolygon', 'ele': '100'},
                               members=[Member('way', outer.id, 'outer'), Member('way', inner.id, 'inner')])
    hill = contour(sq, box(125.515, -22.485, 0.01), 130, closed=True)   # on the island
    bed = contour(sq, [(125.501, -22.499), (125.505, -22.499)], 90)      # in the water
    p = run(w, sq, sq.relations[1])
    assert sq.ways[outer.id].tags['ele'] == '100' and sq.ways[inner.id].tags['ele'] == '100'
    assert hill.id in sq.ways and sq.ways[hill.id].refs == hill.refs, 'the island lost its hill'
    assert bed.id not in sq.ways
    assert p.outline_ways == 2


def test_a_ring_split_over_several_ways_is_joined():
    w, sq = ws()
    pts = box(125.50, -22.50, 0.04)
    ids = [node(sq, lon, lat) for lon, lat in pts]
    a, b = next(_ids), next(_ids)
    sq.ways[a] = Way(id=a, refs=[ids[0], ids[1], ids[2]], tags={})
    sq.ways[b] = Way(id=b, refs=[ids[0], ids[3], ids[2]], tags={})        # drawn the other way
    sq.relations[2] = Relation(id=2, tags={'natural': 'water', 'ele': '100'},
                               members=[Member('way', a, 'outer'), Member('way', b, 'outer')])
    rings, _ = flatten.rings(sq, sq.relations[2])
    assert len(rings) == 1 and rings[0][0] == rings[0][-1] and len(rings[0]) == 5


def test_refused_without_a_level_for_flowing_water_and_for_a_shared_bank():
    w, sq = ws()
    with pytest.raises(flatten.Refused, match='no level'):
        flatten.plan(w, sq, lake(sq, level=None), allocator(sq))
    river = way(sq, box(125.60, -22.50, 0.01), {'natural': 'water', 'water': 'river', 'ele': '50'}, closed=True)
    with pytest.raises(flatten.Refused, match='flowing'):
        flatten.plan(w, sq, river, allocator(sq))
    ring = way(sq, box(125.70, -22.50, 0.01), {}, closed=True)
    sq.relations[3] = Relation(id=3, tags={'natural': 'water', 'ele': '80'}, members=[Member('way', ring.id, 'outer')])
    sq.relations[4] = Relation(id=4, tags={'natural': 'water', 'water': 'river'}, members=[Member('way', ring.id, 'outer')])
    with pytest.raises(flatten.Refused, match='flowing water'):
        flatten.plan(w, sq, sq.relations[3], allocator(sq))


def test_flatten_and_its_undo_leave_the_square_as_it_was():
    w, sq = ws()
    lk = lake(sq)
    contour(sq, box(125.51, -22.49, 0.01), 90, closed=True)
    contour(sq, [(125.45, LAT), (125.59, LAT)], 120)
    contour(sq, [(125.45, -22.47), (125.59, -22.47)], 100)
    before = edits.snapshot(sq)
    p = flatten.plan(w, sq, lk, allocator(sq))
    for s, cmd in p.steps:
        cmd.apply(s)
    assert edits.snapshot(sq) != before
    for s, cmd in reversed(p.steps):
        cmd.undo(s)
    assert edits.snapshot(sq) == before


# --------------------------------------------------------------- fill lines

def fill_lines(sq):
    return [w for w in sq.ways.values() if flatten.FILL in w.tags]


def test_fill_lines_cross_the_water_at_its_level_every_120_m():
    w, sq = ws()
    lk = lake(sq)
    run(w, sq, lk)
    lines = fill_lines(sq)
    # 4.4 km of lake north to south, a line every 120 m from 60 m in
    assert len(lines) == 37
    assert all(x.tags == {'ele': '100', flatten.FILL: f'way/{lk.id}'} for x in lines)
    for x in lines:
        a, b = (sq.nodes[r] for r in x.refs)
        assert a.lat == b.lat
        assert sorted((a.lon, b.lon)) == pytest.approx([125.50, 125.54], abs=1e-9), 'not shore to shore'
    lats = sorted(sq.nodes[x.refs[0]].lat for x in lines)
    gaps = [(b - a) * 110540 for a, b in zip(lats, lats[1:], strict=False)]
    assert all(g == pytest.approx(120, abs=0.01) for g in gaps)


def test_fill_lines_leave_an_island_out():
    w, sq = ws()
    outer = way(sq, box(125.50, -22.50, 0.04), {}, closed=True)
    inner = way(sq, box(125.51, -22.49, 0.02), {}, closed=True)
    sq.relations[5] = Relation(id=5, tags={'natural': 'water', 'ele': '100'},
                               members=[Member('way', outer.id, 'outer'), Member('way', inner.id, 'inner')])
    run(w, sq, sq.relations[5])
    for x in fill_lines(sq):
        a, b = (sq.nodes[r] for r in x.refs)
        mid_lon, lat = (a.lon + b.lon) / 2, a.lat
        on_island = 125.51 < mid_lon < 125.53 and -22.49 < lat < -22.47
        assert not on_island, 'a fill line crosses the island'
    assert any(sq.nodes[x.refs[0]].lon == pytest.approx(125.53, abs=1e-9) for x in fill_lines(sq)), \
        'no line starts at the island shore - the island was filled over or the water beside it skipped'


def test_flattening_again_replaces_the_fill_lines_and_at_the_same_level_is_no_change():
    w, sq = ws()
    lk = lake(sq)
    run(w, sq, lk)
    first = {x.id for x in fill_lines(sq)}
    p = flatten.plan(w, sq, lk, allocator(sq))
    assert p.steps == [], 'flattening a flat lake again was a step'
    p = run(w, sq, lk, fill_spacing_m=240)
    assert len(fill_lines(sq)) == 18 and not first & {x.id for x in fill_lines(sq)}


def test_other_lakes_fill_lines_are_not_clipped_as_contours():
    w, sq = ws()
    a = lake(sq)
    run(w, sq, a)
    before = {x.id: list(x.refs) for x in fill_lines(sq)}
    b = way(sq, box(125.52, -22.48, 0.04), {'natural': 'water', 'ele': '90'}, closed=True)   # overlapping
    run(w, sq, b)
    assert all(sq.ways[i].refs == refs for i, refs in before.items()), "a lake's fill lines were clipped"


def test_relevel_carries_a_new_level_to_the_outline_and_fill_and_clearing_takes_them():
    w, sq = ws()
    outer = way(sq, box(125.50, -22.50, 0.04), {}, closed=True)
    rel = Relation(id=6, tags={'natural': 'water', 'ele': '100'}, members=[Member('way', outer.id, 'outer')])
    sq.relations[6] = rel
    run(w, sq, rel)
    for c in flatten.relevel(sq, rel, '110'):
        c.apply(sq)
    assert sq.ways[outer.id].tags['ele'] == '110'
    assert {x.tags['ele'] for x in fill_lines(sq)} == {'110'}
    for c in flatten.relevel(sq, rel, None):
        c.apply(sq)
    assert 'ele' not in sq.ways[outer.id].tags and fill_lines(sq) == []


def test_relevel_of_a_lake_never_flattened_is_nothing():
    w, sq = ws()
    assert flatten.relevel(sq, lake(sq), '50') == []
