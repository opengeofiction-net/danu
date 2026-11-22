"""The landforms the contours contradict, and those with no height - #191.

A slope rising to the north: contours at 200 m and 225 m running east, 100 m
apart, and a cliff between them. Drawn west to east its right is the south,
the low side, as a cliff's should be; drawn east to west, backwards.
"""

from danu.checks import landforms as lc
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way

LAT = -23.5
D = 0.0009                     # some 100 m


def slope(cliff_east=True, cliff_tags=None):
    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def way(pts, tags):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids, pts, tags).apply(sq)
        return wid

    way([(125.40 + 0.01 * i, LAT - D / 2) for i in range(21)], {'ele': '200'})
    way([(125.40 + 0.01 * i, LAT + D / 2) for i in range(21)], {'ele': '225'})
    pts = [(125.45 + 0.01 * i, LAT) for i in range(6)]
    cid = way(pts if cliff_east else pts[::-1], cliff_tags or {'natural': 'cliff'})
    return sq, cid


def kinds(sq):
    return sorted((f.kind, f.way or f.node or f.relation) for f in lc.find_in(sq))


def test_a_cliff_drawn_with_its_low_side_on_its_right_is_not_listed():
    sq, _ = slope()
    assert kinds(sq) == []


def test_a_cliff_with_its_high_side_on_its_right_is_backwards():
    sq, cid = slope(cliff_east=False)
    (f,) = lc.find_in(sq)
    assert (f.kind, f.way) == ('cliff_back', cid)
    assert 'R reverses it' in f.explain()
    edits.ReverseWay(cid, 'cliff').apply(sq)
    assert kinds(sq) == []


def test_a_cliff_with_no_ele_across_contours_is_listed_with_its_count():
    sq, cid = slope()
    way = sq.ways[cid]
    # turned north-south through both contours, and a third crossing back
    for k, r in enumerate(way.refs):
        n = sq.nodes[r]
        n.lon, n.lat = 125.5 + (0.0005 if k % 2 else 0), LAT - D + k * D / 2.5
    got = {f.kind: f for f in lc.find_in(sq)}
    assert 'cliff_cross' in got and got['cliff_cross'].way == cid
    assert 'crosses 2 contours' in got['cliff_cross'].text
    way.tags['ele'] = '210'                     # a contour now: R16's crossing row, not this
    assert 'cliff_cross' not in {f.kind for f in lc.find_in(sq)}


def test_landforms_with_no_height_are_listed_and_go_when_given_one():
    sq, _ = slope()
    sq.nodes[-9001] = Node(id=-9001, lon=125.42, lat=LAT, tags={'natural': 'peak', 'name': 'Bare'})
    sq.nodes[-9002] = Node(id=-9002, lon=125.43, lat=LAT, tags={'natural': 'peak', 'ele': '300'})
    sq.nodes[-9003] = Node(id=-9003, lon=125.41, lat=LAT + 0.01)
    sq.nodes[-9004] = Node(id=-9004, lon=125.42, lat=LAT + 0.01)
    sq.ways[-9010] = Way(id=-9010, refs=[-9003, -9004], tags={'natural': 'ridge'})
    got = {(f.kind, f.node or f.way) for f in lc.find_in(sq)}
    assert got == {('no_height', -9001), ('no_height', -9010)}
    sq.nodes[-9004].tags['ele'] = '240'          # one level on the ridge is enough
    sq.nodes[-9001].tags['ele'] = '310'
    assert lc.find_in(sq) == []


def test_the_index_follows_an_edit_of_the_cliff_and_of_a_contour_near_it():
    from danu.core.square import WorkingSet
    sq, cid = slope(cliff_east=False)
    ws = WorkingSet(centre=sq.name, size=1, squares={sq.name: sq})
    idx = lc.Index(ws)
    assert [f.kind for f in idx.findings()] == ['cliff_back']
    cmd = edits.ReverseWay(cid, 'cliff')
    cmd.apply(sq)
    idx.update(sq, cmd.ways(sq))
    assert idx.findings() == []
    # the contours swapped: the 200 m now to the north, and the cliff backwards again
    low, high = (w for w in sq.ways.values() if w.ele is not None)
    low.tags['ele'], high.tags['ele'] = '225', '200'
    idx.update(sq, {low.id, high.id})
    assert [(f.kind, f.way) for f in idx.findings()] == [('cliff_back', cid)]
    sq.nodes[-9001] = Node(id=-9001, lon=125.42, lat=LAT, tags={'natural': 'saddle'})
    idx.update(sq, (), {-9001})
    assert ('no_height', -9001) in {(f.kind, f.node) for f in idx.findings()}
