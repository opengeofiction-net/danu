"""What lies inside a ring - H1b: water spanning contours (R33), and rings
with nothing inside them (R39). No Qt."""

import random

from danu.checks import inside
from danu.core import edits
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
_ids = iter(range(1000, 10**7))


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def nodes(sq, pts):
    out = []
    for lon, lat in pts:
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
        out.append(i)
    return out


def square_ring(cx, cy, r):
    return [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]


def ring(sq, cx, cy, r, tags):
    refs = nodes(sq, square_ring(cx, cy, r))
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[*refs, refs[0]], tags=tags)
    return sq.ways[i]


def line(sq, pts, ele):
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=nodes(sq, pts), tags={'ele': str(ele)})
    return sq.ways[i]


def kinds(w, kind):
    return [f for f in inside.find(w) if f.kind == kind]


def test_a_lake_with_a_contour_at_another_level_inside_it_is_listed():
    w, sq = ws()
    lake = ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'name': 'Kinser'})
    line(sq, [(125.45, -22.5), (125.55, -22.5)], 125)                 # through it
    line(sq, [(125.45, -22.51), (125.55, -22.51)], 150)
    (f,) = kinds(w, 'lake')
    assert f.way == lake.id and f.describe() == 'lake "Kinser" - 2 contour levels inside it, 125 to 150 m'


def test_one_at_its_own_level_or_snapped_to_its_shore_or_on_an_island_is_not():
    w, sq = ws()
    lake = ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'ele': '125'})
    line(sq, [(125.45, -22.5), (125.55, -22.5)], 125)                 # at its level: flatten leaves these
    shore = lake.refs[0]
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[shore, *nodes(sq, [(125.4, -22.6)])], tags={'ele': '150'})   # snapped
    assert kinds(w, 'lake') == []
    # a multipolygon with an island: a contour round the island's hill is not in the water
    outer = ring(sq, 125.2, -22.2, 0.05, {})
    island = ring(sq, 125.2, -22.2, 0.02, {})
    sq.relations[-5] = Relation(id=-5, members=[Member('way', outer.id, 'outer'), Member('way', island.id, 'inner')],
                                tags={'natural': 'water', 'type': 'multipolygon'})
    line(sq, square_ring(125.2, -22.2, 0.01), 200)
    assert kinds(w, 'lake') == []
    line(sq, [(125.16, -22.2), (125.165, -22.2)], 175)                # in the water, between the rings
    (f,) = kinds(w, 'lake')
    assert f.relation == -5 and 'the 175 m' in f.describe()


def test_flowing_water_spans_contours_and_is_not_a_body():
    w, sq = ws()
    ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'water': 'river'})
    line(sq, [(125.45, -22.5), (125.55, -22.5)], 125)
    assert kinds(w, 'lake') == []


def test_a_ring_under_the_threshold_is_not_reported():
    """A knoll 40 m across, 0.16 ha: a ring all the same, but nothing a spot
    height would add to. At a threshold under its area it is reported."""
    w, sq = ws()
    knoll = ring(sq, 125.5, -22.5, 0.0002, {'ele': '220'})
    assert kinds(w, 'bare') == []
    (f,) = [f for f in inside.find(w, bare_min=1000) if f.kind == 'bare']
    assert f.way == knoll.id and '0 ha' in f.describe()
    big = ring(sq, 125.2, -22.2, 0.002, {'ele': '220'})                 # 412 m by 442 m, 18.2 ha
    (f,) = kinds(w, 'bare')
    assert f.way == big.id and f.describe() == f'the 220 m ring, way {big.id} - 18 ha, nothing inside it'


def test_a_ring_with_nothing_inside_is_reported_and_one_holding_anything_is_not():
    w, sq = ws()
    top = ring(sq, 125.5, -22.5, 0.01, {'ele': '450'})
    held = ring(sq, 125.2, -22.2, 0.01, {'ele': '300'})
    sq.nodes[-9] = Node(id=-9, lon=125.2, lat=-22.2, tags={'ele': '312'})       # a spot height
    outer = ring(sq, 125.5, -22.5, 0.03, {'ele': '425'})                         # round the 450
    ended = ring(sq, 125.8, -22.8, 0.01, {'ele': '200'})
    line(sq, [(125.8, -22.8), (125.9, -22.9)], 225)                             # an open one ends inside
    crossed = ring(sq, 125.1, -22.8, 0.01, {'ele': '200'})
    line(sq, [(125.05, -22.8), (125.15, -22.8)], 225)                           # one across, no vertex in
    (f,) = kinds(w, 'bare')
    assert f.way == top.id and f.describe().endswith('ha, nothing inside it')
    assert {held.id, outer.id, ended.id, crossed.id}.isdisjoint({x.way for x in kinds(w, 'bare')})


def test_a_contour_moved_into_a_bare_ring_and_a_spot_height_put_in_one_take_them_off():
    """Neither edit names the ring: the index asks the rings round what
    moved, not only the ways the edit touched."""
    w, sq = ws()
    a = ring(sq, 125.3, -22.5, 0.01, {'ele': '400'})
    b = ring(sq, 125.7, -22.5, 0.01, {'ele': '400'})
    far = line(sq, [(125.5, -22.9), (125.6, -22.9), (125.65, -22.9)], 425)
    index = inside.Index(w)
    assert {f.way for f in index.findings('bare')} >= {a.id, b.id}
    n = sq.nodes[far.refs[2]]
    move = edits.MoveNode(far.refs[2], (n.lon, n.lat), (125.7, -22.5))           # its end into b
    move.apply(sq)
    index.update(sq, move.ways(sq))
    alloc = edits.IdAllocator(sq)
    put = edits.AddNode(alloc.take(), (125.3, -22.5), {'ele': '412'})          # a summit in a
    put.apply(sq)
    index.update(sq, put.ways(sq), put.spots(sq))
    assert {f.way for f in index.findings('bare')}.isdisjoint({a.id, b.id})


def test_a_lakes_shore_moved_out_over_a_contour_lists_it():
    w, sq = ws()
    lake = ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'name': 'Kinser'})
    line(sq, [(125.56, -22.6), (125.56, -22.4)], 150)                       # east of it
    index = inside.Index(w)
    assert index.findings('lake') == []
    corner = lake.refs[1]                                                    # its south-east corner
    n = sq.nodes[corner]
    move = edits.MoveNode(corner, (n.lon, n.lat), (125.6, n.lat))
    move.apply(sq)
    index.update(sq, move.ways(sq))
    assert [f.way for f in index.findings('lake')] == [lake.id]


def test_the_index_follows_edits_and_agrees_with_a_fresh_scan():
    """Random moves, additions and deletions of contours, spot heights and a
    lake's outline: after each, the index kept says what a fresh scan says."""
    w, sq = ws()
    rnd = random.Random(7)
    for k in range(12):
        ring(sq, 125.1 + 0.07 * (k % 4), -22.9 + 0.1 * (k // 4), 0.01 + 0.004 * (k % 3), {'ele': str(100 + 25 * k)})
    ring(sq, 125.5, -22.5, 0.05, {'natural': 'water', 'ele': '100'})
    index = inside.Index(w)
    alloc = edits.IdAllocator(sq)
    for step in range(200):
        r = rnd.random()
        if r < 0.5:
            nid = rnd.choice([i for i in sq.nodes if sq.nodes[i].tags.get('ele') is None and any(i in x.refs for x in sq.ways.values())])
            n = sq.nodes[nid]
            cmd = edits.MoveNode(nid, (n.lon, n.lat), (n.lon + rnd.uniform(-0.03, 0.03), n.lat + rnd.uniform(-0.03, 0.03)))
        elif r < 0.75:
            x, y = rnd.uniform(125.08, 125.35), rnd.uniform(-22.92, -22.68)
            cmd = edits.AddNode(alloc.take(), (x, y), {'ele': str(rnd.randint(100, 500))})
        elif r < 0.9:
            x, y = rnd.uniform(125.08, 125.35), rnd.uniform(-22.92, -22.68)
            cmd = edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(x, y), (x + 0.02, y)], {'ele': str(rnd.choice((100, 150, 175)))})
        else:
            victims = [i for i, x in sq.ways.items() if 'ele' in x.tags and 'natural' not in x.tags]
            cmd = edits.DeleteWay(rnd.choice(victims))
        cmd.apply(sq)
        index.update(sq, cmd.ways(sq), cmd.spots(sq))
        assert sorted(f.text for f in index.findings()) == sorted(f.text for f in inside.find(w)), f'step {step}'
