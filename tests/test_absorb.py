"""danu.core.absorb: a contour and the pieces of it beside it made one line -
a valley's tip and the rings up the river from it. No Qt."""

import math

import pytest

ogr = pytest.importorskip('osgeo.ogr')

from danu.core import absorb, edits  # noqa: E402
from danu.core.square import Node, Square, SquareName, Way  # noqa: E402

A = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y):
    """Metres east and north of (125.5, -22.5), as degrees."""
    return 125.5 + x / KX, LAT + y / KY


def way(sq, pts, ele, ids):
    refs = []
    for x, y in pts:
        i = next(ids)
        sq.nodes[i] = Node(id=i, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(i)
    w = Way(id=next(ids), refs=refs, tags={'contour': 'elevation', 'ele': str(ele)})
    sq.ways[w.id] = w
    return w


def valley(gap=30.0, piece_ele=30):
    """A 30 m contour up a valley to a tip at x = 0, the tip the shared edge
    of the first piece; a second piece ``gap`` m on, a third tip to tip with
    it - each ring closed onto its first node."""
    sq = Square(name=A, present=True, attrs={})
    ids = iter(range(-1, -10_000, -1))
    main = way(sq, [(-2000, 300), (-1000, 150), (0, 20), (0, -20), (-1000, -150), (-2000, -300)], 30, ids)
    pieces = []
    for pts in ([(0, 20), (50, 40), (100, 0), (50, -40), (0, -20)],
                [(100 + gap, 0), (150 + gap, 40), (200 + gap, 0), (150 + gap, -40)],
                [(200 + gap, 0), (250 + gap, 40), (300 + gap, 0), (250 + gap, -40)]):
        w = way(sq, pts, piece_ele, ids)
        w.refs.append(w.refs[0])
        pieces.append(w)
    return sq, main, pieces


def polygon(sq, refs):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    pts = [(sq.nodes[r].lon * KX, sq.nodes[r].lat * KY) for r in refs]
    for x, y in [*pts, pts[0]]:
        ring.AddPoint_2D(x, y)
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    return p


def test_the_pieces_are_absorbed_into_one_line_round_them_all():
    sq, main, pieces = valley()
    nodes, ways = dict(sq.nodes), {i: list(w.refs) for i, w in sq.ways.items()}
    got = absorb.absorb(sq, main.id, [p.id for p in pieces], edits.IdAllocator(sq))
    assert not isinstance(got, str), got
    cmd, coords = got
    cmd.apply(sq)
    assert [i for i in sq.ways] == [main.id]                     # the pieces gone, the contour kept
    refs = sq.ways[main.id].refs
    assert refs[0] == ways[main.id][0] and refs[-1] == ways[main.id][-1]
    assert [(sq.nodes[r].lon, sq.nodes[r].lat) for r in refs] == coords
    # the contour, closed across its open ends, holds every piece - to the metre
    region = polygon(sq, refs).Buffer(1.0)
    for p in pieces:
        for r in p.refs:
            pt = ogr.Geometry(ogr.wkbPoint)
            pt.AddPoint_2D(nodes[r].lon * KX, nodes[r].lat * KY)
            assert region.Contains(pt)
    # and runs past the last piece, up the valley
    assert max(sq.nodes[r].lon for r in refs) >= deg(329, 0)[0]
    assert len(refs) < len(ways[main.id]) + 12, 'the outline is drawn simply'
    cmd.undo(sq)
    assert {i: list(w.refs) for i, w in sq.ways.items()} == ways and sq.nodes == nodes


@pytest.mark.parametrize('gap, piece_ele, why', [
    (150.0, 30, 'apart'),
    (30.0, 40, 'not all at 30 m'),
])
def test_it_is_refused_when_the_pieces_are_not_one_valleys(gap, piece_ele, why):
    sq, main, pieces = valley(gap=gap, piece_ele=30)
    pieces[-1].tags['ele'] = str(piece_ele)
    got = absorb.absorb(sq, main.id, [p.id for p in pieces], edits.IdAllocator(sq))
    assert isinstance(got, str) and why in got, got


def test_pieces_short_of_the_contour_are_bridged_to_it():
    """The first piece gone, the second is 130 m from the tip; at 100 m no,
    with a longer reach the contour is bridged out to it."""
    sq, main, pieces = valley()
    del sq.ways[pieces[0].id]
    rest = [p.id for p in pieces[1:]]
    assert 'from the contour' in absorb.absorb(sq, main.id, rest, edits.IdAllocator(sq))
    cmd, _ = absorb.absorb(sq, main.id, rest, edits.IdAllocator(sq), gap_m=150)
    cmd.apply(sq)
    assert list(sq.ways) == [main.id]


def test_where_the_line_meets_the_outline_on_its_own_node_that_node_is_kept():
    """The tip's two nodes lie on the first piece's edge: both kept, the
    outline run between them, none drawn again at their place."""
    sq, main, pieces = valley()
    tip = main.refs[2:4]
    cmd, _ = absorb.absorb(sq, main.id, [p.id for p in pieces], edits.IdAllocator(sq))
    cmd.apply(sq)
    refs = sq.ways[main.id].refs
    assert tip[0] in refs and tip[1] in refs
    at = [(round(sq.nodes[r].lon, 9), round(sq.nodes[r].lat, 9)) for r in refs]
    assert len(at) == len(set(at)), 'a node drawn twice at one place'
