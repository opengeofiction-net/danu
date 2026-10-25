"""danu.core.crossfix: a recovered contour pushed back off the line at the
next level it strays across - roantra's 10 m over the main map's coastline.
GDAL's geometry, which the push is."""

import math

import pytest

ogr = pytest.importorskip('osgeo.ogr')

from danu.checks import crossings  # noqa: E402
from danu.core import crossfix, edits  # noqa: E402
from danu.core.square import Node, Square, SquareName, Way, WorkingSet  # noqa: E402

A = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def way(sq, wid, pts, tags):
    refs = []
    for x, y in pts:
        nid = (max((abs(i) for i in sq.nodes), default=0) + 1) * (1 if wid > 0 else -1)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


def coast(sq):
    """The main map's coastline running east: land to its left, the north."""
    return way(sq, 4015, [(-2000, 0), (2000, 0)], {'natural': 'coastline', 'ele': '0'})


def stepping(sq, wid=-1, ele=10, dip=30):
    """A recovered contour along the coast 20 m inland, stepping out to sea
    ``dip`` m twice."""
    return way(sq, wid, [(-1500, 20), (-600, 20), (-500, -dip), (-400, 20), (300, 20), (400, -dip), (500, 20),
                         (1500, 20)], {'contour': 'elevation', 'ele': str(ele)})


def run(w, sq, **kw):
    p = crossfix.plan(w, lambda s: edits.IdAllocator(s), only={A}, **kw)
    for s, step in p.steps:
        step.apply(s)
    return p


def ys(sq, wid):
    return [(sq.nodes[r].lat - LAT) * KY for r in sq.ways[wid].refs]


def test_a_contour_stepping_over_the_coastline_is_pushed_back_to_the_land_as_one_line():
    w, sq = ws()
    coast(sq)
    c = stepping(sq)
    before = list(c.refs)
    assert len(crossings.find(w)) == 4
    p = run(w, sq)
    assert p.pushed == 1 and p.fixed == 4 and p.left == 0
    assert crossings.find(w) == []
    assert min(ys(sq, c.id)) > 0, 'still out at sea'
    assert sq.ways[c.id].refs[0] == before[0] and sq.ways[c.id].refs[-1] == before[-1]
    assert p.added and p.removed


def test_the_next_contour_up_close_by_brings_the_push_in_between():
    """The 20 m 30 m inland: pushed 50 m it would pass it, so it comes in."""
    w, sq = ws()
    coast(sq)
    c = stepping(sq)
    way(sq, -100, [(-1500, 30), (1500, 30)], {'contour': 'elevation', 'ele': '20'})
    p = run(w, sq)
    assert p.pushed == 1 and crossings.find(w) == []
    assert 0 < min(ys(sq, c.id)) and max(ys(sq, c.id)) < 30


def test_levels_further_apart_and_two_recovered_contours_are_left():
    w, sq = ws()
    coast(sq)
    stepping(sq, ele=20)                                        # 0 against 20, with a 10 m in the set
    way(sq, -200, [(-1500, 400), (1500, 400)], {'contour': 'elevation', 'ele': '10'})
    way(sq, -300, [(-1500, 800), (1500, 800)], {'contour': 'elevation', 'ele': '30'})
    way(sq, -301, [(0, 700), (0, 900)], {'contour': 'elevation', 'ele': '40'})      # two recovered crossing
    p = run(w, sq)
    assert p.pushed == 0 and p.left == 5


def test_a_stretch_with_no_room_is_left_and_the_rest_pushed():
    """The 20 m on the coastline itself round the eastern dip: no room
    there, so that dip stays and the western one goes."""
    w, sq = ws()
    coast(sq)
    c = stepping(sq)
    way(sq, -100, [(200, 3), (600, 3)], {'contour': 'elevation', 'ele': '20'})
    p = run(w, sq)
    assert p.pushed == 1 and p.fixed == 2
    left = crossings.find(w)
    assert {(x.a[1], x.b[1]) for x in left} <= {(4015, c.id), (c.id, 4015), (-100, c.id), (c.id, -100)}
    lons = [(sq.nodes[r].lon - 125.5) * KX for r in sq.ways[c.id].refs if (sq.nodes[r].lat - LAT) * KY < 0]
    assert lons and all(x > 0 for x in lons), 'the west dip still out at sea'


def test_undo_puts_it_back():
    w, sq = ws()
    coast(sq)
    stepping(sq)
    nodes, ways = dict(sq.nodes), {i: list(x.refs) for i, x in sq.ways.items()}
    p = run(w, sq)
    for s, step in reversed(p.steps):
        step.undo(s)
    assert {i: list(x.refs) for i, x in sq.ways.items()} == ways and sq.nodes == nodes


def test_an_islands_ring_begun_by_the_shore_is_pushed_round_as_one_ring():
    """The island's coastline anticlockwise, its land inside; the 10 m ring
    20 m in, stepping out across it - and its first node within reach of
    the shore, where the ring closes."""
    w, sq = ws()
    way(sq, 4016, [(-500, -500), (500, -500), (500, 500), (-500, 500), (-500, -500)],
        {'natural': 'coastline', 'ele': '0'})
    sq.ways[4016].refs[-1] = sq.ways[4016].refs[0]
    c = way(sq, -1, [(-480, 0), (-480, -480), (0, -480), (100, -530), (200, -480), (480, -480), (480, 480),
                     (-480, 480), (-530, 200), (-480, 100), (-480, 0)], {'contour': 'elevation', 'ele': '10'})
    c.refs[-1] = c.refs[0]
    assert len(crossings.find(w)) == 4
    p = run(w, sq)
    assert p.pushed == 1 and crossings.find(w) == []
    refs = sq.ways[c.id].refs
    assert refs[0] == refs[-1]
    xy = [((sq.nodes[r].lon - 125.5) * KX, (sq.nodes[r].lat - LAT) * KY) for r in refs]
    assert all(-500 < x < 500 and -500 < y < 500 for x, y in xy), 'still out at sea'
