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
    assert f.way == lake.id and f.describe() == 'lake "Kinser" - 2 contour levels inside, 125 to 150 m'


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
    assert f.relation == -5 and '175 m' in f.describe()


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
    assert f.way == big.id and f.describe() == f'220 m ring, way {big.id} - 18 ha, nothing inside'


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
    assert f.way == top.id and f.describe().endswith('ha, nothing inside')
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


def wiggly(cx, cy, r, n, rnd):
    """A ring of n nodes round a point, its radius wandering - a shore of
    many chunks, each with a box of its own."""
    import math
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        rr = r * (1 + 0.3 * math.sin(7 * a) + 0.1 * rnd.uniform(-1, 1))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def test_inside_and_crosses_by_chunks_agree_with_every_edge_asked():
    """A ring's edges asked a chunk at a time, by the chunk's box, give what
    asking every edge of it gives: points in and out, lines across or not."""
    import numpy as np
    rnd = random.Random(3)
    rings = []
    for cx, cy, r in ((0.0, 0.0, 1.0), (0.2, 0.1, 0.25), (2.5, 0.0, 0.5)):    # a lake, an island, another
        pts = wiggly(cx, cy, r, 400, rnd)
        X = np.array([p[0] for p in pts] + [pts[0][0]]); Y = np.array([p[1] for p in pts] + [pts[0][1]])
        rings.append((X, Y))

    def odd(x, y):                                      # every edge of every ring, one point at a time
        c = False
        for X, Y in rings:
            for ax, ay, bx, by in zip(X[:-1], Y[:-1], X[1:], Y[1:], strict=True):
                if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                    c = not c
        return c
    px = np.array([rnd.uniform(-1.5, 3.2) for _ in range(400)]); py = np.array([rnd.uniform(-1.5, 1.5) for _ in range(400)])
    assert list(inside.inside(px, py, rings)) == [odd(x, y) for x, y in zip(px, py, strict=True)]
    box = (min(X.min() for X, _ in rings), min(Y.min() for _, Y in rings),
           max(X.max() for X, _ in rings), max(Y.max() for _, Y in rings))
    hits = 0
    for _ in range(300):
        x0, y0 = rnd.uniform(-1.5, 3.2), rnd.uniform(-1.5, 1.5)
        X = np.array([x0, x0 + rnd.uniform(-0.4, 0.4)]); Y = np.array([y0, y0 + rnd.uniform(-0.4, 0.4)])
        whole = inside.crosses(X, Y, rings, box, boxes=[(-9, -9, 9, 9)] * 3,
                               chunks=[np.array([[-9, -9, 9, 9]] * -(-(len(R) - 1) // inside.CHUNK)) for R, _ in rings])
        assert inside.crosses(X, Y, rings, box) == whole
        hits += whole
    assert 30 < hits < 270, 'both answers asked'


def test_a_sea_of_many_rings_asks_only_those_near_and_says_what_asking_all_does():
    """A sea of hundreds of islands, each ring asked only when its box is near
    the points or the line: the same answers as every ring asked - and the
    shore's nodes found among it as np.isin finds them."""
    import numpy as np
    rnd = random.Random(5)
    rings = []
    for cx, cy, r in [(0.0, 0.0, 3.0)] + [(rnd.uniform(-2, 2), rnd.uniform(-2, 2), 0.05) for _ in range(300)]:
        pts = wiggly(cx, cy, r, 40, rnd)
        X = np.array([p[0] for p in pts] + [pts[0][0]]); Y = np.array([p[1] for p in pts] + [pts[0][1]])
        rings.append((X, Y))
    boxes = np.array([inside._box(X, Y) for X, Y in rings])
    chunks = [inside._chunks(X, Y) for X, Y in rings]
    box = tuple(boxes[0])
    for _ in range(200):
        x0, y0 = rnd.uniform(-3.2, 3.2), rnd.uniform(-3.2, 3.2)
        X = np.array([x0, x0 + rnd.uniform(-0.2, 0.2), x0 + rnd.uniform(-0.2, 0.2)])
        Y = np.array([y0, y0 + rnd.uniform(-0.2, 0.2), y0 + rnd.uniform(-0.2, 0.2)])
        assert list(inside.inside(X, Y, rings, boxes, chunks)) == list(inside.inside(X, Y, rings))
        assert inside.crosses(X, Y, rings, box, boxes, chunks) == inside.crosses(X, Y, rings, box)
    assert not inside.inside([], [], rings, boxes, chunks).size
    assert len(inside._near(boxes, len(rings), -0.1, -0.1, 0.1, 0.1)) < 20, 'the islands far off are asked'
    on = np.unique(np.array([rnd.randrange(10**6) for _ in range(5000)], dtype=np.int64))
    ids = np.array([rnd.randrange(10**6) for _ in range(3000)] + list(on[:50]) + [-1, 10**7], dtype=np.int64)
    assert (inside._among(ids, on) == np.isin(ids, on)).all()
    assert not inside._among(ids, on[:0]).any()


def test_a_lake_of_many_rings_kept_as_edited_agrees_with_a_fresh_scan():
    """The lines a lake holds kept, and only those an edit changed asked
    again: random edits through a two-ring lake of many chunks - its own
    outline moved too - and after each the index says what a fresh scan
    says."""
    w, sq = ws()
    rnd = random.Random(11)
    outer = Way(id=next(_ids), refs=[], tags={})
    outer.refs = [*(r := nodes(sq, wiggly(125.5, -22.5, 0.2, 300, rnd))), r[0]]
    island = Way(id=next(_ids), refs=[], tags={})
    island.refs = [*(r := nodes(sq, wiggly(125.55, -22.45, 0.04, 80, rnd))), r[0]]
    sq.ways[outer.id], sq.ways[island.id] = outer, island
    sq.relations[-7] = Relation(id=-7, members=[Member('way', outer.id, 'outer'), Member('way', island.id, 'inner')],
                                tags={'natural': 'water', 'ele': '0'})
    for _ in range(40):
        x, y = rnd.uniform(125.2, 125.8), rnd.uniform(-22.8, -22.2)
        line(sq, [(x, y), (x + rnd.uniform(-0.05, 0.05), y + rnd.uniform(-0.05, 0.05)), (x + 0.02, y + 0.03)],
             rnd.choice((0, 10, 20, 50)))
    index = inside.Index(w)
    shore = [*outer.refs[:-1], *island.refs[:-1]]
    for step in range(150):
        contours = [i for i in sq.nodes if i not in shore and any(i in x.refs for x in sq.ways.values())]
        nid = rnd.choice(shore if rnd.random() < 0.15 else contours)
        n = sq.nodes[nid]
        cmd = edits.MoveNode(nid, (n.lon, n.lat), (n.lon + rnd.uniform(-0.05, 0.05), n.lat + rnd.uniform(-0.05, 0.05)))
        cmd.apply(sq)
        index.update(sq, cmd.ways(sq), cmd.spots(sq))
        assert sorted(f.text for f in index.findings()) == sorted(f.text for f in inside.find(w)), f'step {step}'


def test_a_segment_moved_across_a_lake_its_ends_outside_its_box_is_seen():
    """A node moved so that its segment crosses a lake, neither end within
    the lake's box: the lake is asked again all the same, as a fresh scan
    would find it."""
    w, sq = ws()
    ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'ele': '0'})
    way = line(sq, [(125.40, -22.5), (125.45, -22.6)], 50)
    index = inside.Index(w)
    assert [f.kind for f in index.findings()] == []
    end = way.refs[-1]
    n = sq.nodes[end]
    cmd = edits.MoveNode(end, (n.lon, n.lat), (125.60, -22.5))     # straight through it
    cmd.apply(sq)
    index.update(sq, cmd.ways(sq), cmd.spots(sq))
    assert [f.kind for f in inside.find(w)] == ['lake']
    assert [f.kind for f in index.findings()] == ['lake']
