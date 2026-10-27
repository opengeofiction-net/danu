"""Contours that touch or lie on one another - G8e, R16's other half and the
spec's duplicate coincident contours. No Qt."""

import pytest

from danu.checks import touches
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540
_ids = iter(range(1000, 10**6))


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


def way(sq, refs, ele):
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=list(refs), tags={'ele': str(ele)})
    return sq.ways[i]


def test_a_node_two_levels_share_is_found_and_one_level_sharing_is_not():
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    x = way(sq, [a, b, c], 100)
    y = way(sq, [*nodes(sq, [(125.305, LAT + 0.01)]), b, *nodes(sq, [(125.315, LAT + 0.01)])], 125)
    way(sq, [c, *nodes(sq, [(125.33, LAT)])], 100)                  # the 100 m going on: a join
    (t,) = touches.find(w)
    assert t.kind == 'shared' and t.node == b
    assert {t.a[1], t.b[1]} == {x.id, y.id}
    assert 'share node' in t.describe() and 'U unglues it' in t.explain()


def test_two_levels_running_together_are_one_coincident_stretch():
    """The 125 m runs on top of the 100 m, 30 cm off it, for 2 km - the
    edge stack's shape - with no node shared."""
    w, sq = ws()
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT) for j in range(5)]), 100)
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT + 0.3 * M_LAT) for j in range(5)]), 125)
    (t,) = touches.find(w)
    assert t.kind == 'coincident' and t.segments == 4
    assert t.metres == pytest.approx(0.02 * 111320 * 0.9227, rel=0.01)
    assert 'on top of' in t.describe() and 'two levels in one place' in t.explain()


def test_one_level_running_together_is_a_duplicate():
    w, sq = ws()
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT) for j in range(3)]), 100)
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT) for j in range(3)]), 100)
    (t,) = touches.find(w)
    assert 'a duplicate of' in t.describe() and 'delete the copy' in t.explain()


def test_a_node_shared_inside_a_stretch_is_said_once_as_the_stretch():
    w, sq = ws()
    run = nodes(sq, [(125.30 + 0.005 * j, LAT) for j in range(3)])
    way(sq, run, 100)
    other = nodes(sq, [(125.30, LAT + 0.3 * M_LAT), (125.31, LAT + 0.3 * M_LAT)])
    way(sq, [other[0], run[1], other[1]], 125)                     # through the 100 m's middle node
    found = touches.find(w)
    assert [t.kind for t in found] == ['coincident']


def test_crossing_contours_are_not_touches():
    w, sq = ws()
    way(sq, nodes(sq, [(125.30, LAT), (125.32, LAT)]), 100)
    way(sq, nodes(sq, [(125.31, LAT - 0.01), (125.31, LAT + 0.01)]), 125)
    assert touches.find(w) == []


def test_the_index_follows_an_edit():
    from danu.core import edits
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    way(sq, [a, b, c], 100)
    y = way(sq, [*nodes(sq, [(125.305, LAT + 0.01)]), b, *nodes(sq, [(125.315, LAT + 0.01)])], 125)
    index = touches.Index(w)
    assert len(index.touches()) == 1
    cmd = edits.unglue_node(sq, next(iter(sq.ways)), b, edits.IdAllocator(sq))
    cmd.apply(sq)
    index.update(sq, cmd.ways(sq))
    assert index.touches() == []
    cmd.undo(sq)
    index.update(sq, {y.id})
    assert len(index.touches()) == 1


def edge_stack(sq):
    """The N21E086 shape: 25, 50 and 75 m running 30 cm apart, and sharing
    one node all three."""
    common = nodes(sq, [(125.31, LAT)])[0]
    out = []
    for n, ele in enumerate((25, 50, 75)):
        off = n * 0.3 * M_LAT
        run = nodes(sq, [(125.30, LAT + off), (125.305, LAT + off)]) + [common] + \
            nodes(sq, [(125.315, LAT + off), (125.32, LAT + off)])
        out.append(way(sq, run, ele))
    return out, common


def test_what_is_said_does_not_hang_on_the_order_the_square_holds_its_ways():
    """Two stretches of a pair, one each way round, and a node they share:
    the first version said whichever the square held first, and an undo,
    which puts a way back at the end, changed the list."""
    import random
    w, sq = ws()
    edge_stack(sq)
    first = set(touches.find(w))
    for seed in range(4):
        items = list(sq.ways.items())
        random.Random(seed).shuffle(items)
        sq.ways = dict(items)
        assert set(touches.find(w)) == first


def test_an_edit_to_one_of_three_sharing_a_node_leaves_the_other_two_as_they_were():
    """The 25 m changed: the 50 and 75 m pair, which it shares a node with,
    is asked again in nothing - its stretch is not, so neither is its node."""
    from danu.core import edits
    w, sq = ws()
    (low, mid, high), common = edge_stack(sq)
    index = touches.Index(w)
    n = sq.nodes[low.refs[1]]
    cmd = edits.MoveNode(low.refs[1], (n.lon, n.lat), (n.lon, n.lat - 5 * M_LAT))
    cmd.apply(sq)
    index.update(sq, cmd.ways(sq))
    assert set(index.touches()) == set(touches.find(w))


def test_contours_5_m_apart_are_neighbours_not_coincident():
    w, sq = ws()
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT) for j in range(3)]), 100)
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT + 5 * M_LAT) for j in range(3)]), 125)
    assert touches.find(w) == []


def test_a_doubled_vertex_on_another_contour_is_not_a_stretch():
    """Two of its vertices on one spot, that spot on the 100 m: no length."""
    w, sq = ws()
    way(sq, nodes(sq, [(125.30, LAT), (125.32, LAT)]), 100)
    way(sq, nodes(sq, [(125.31, LAT - 0.01), (125.31, LAT + 0.3 * M_LAT), (125.31, LAT + 0.3 * M_LAT),
                       (125.315, LAT + 0.01)]), 125)
    assert touches.find(w) == []


def test_a_stretch_round_a_rings_closing_node_is_one():
    """A ring that starts half way along its bottom, which lies along the
    100 m: one stretch the bottom's width, not two halves."""
    w, sq = ws()
    ring = nodes(sq, [(125.31, LAT), (125.32, LAT), (125.32, LAT + 0.01), (125.30, LAT + 0.01), (125.30, LAT)])
    way(sq, [*ring, ring[0]], 125)
    way(sq, nodes(sq, [(125.299, LAT - 0.3 * M_LAT), (125.321, LAT - 0.3 * M_LAT)]), 100)
    (t,) = touches.find(w)
    assert t.metres == pytest.approx(0.02 * 111320 * 0.9227, rel=0.01)


def test_a_deleted_contour_is_not_found_again_by_its_neighbours_next_edit():
    from danu.core import edits
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    line = way(sq, [a, b, c], 100)
    v = way(sq, [*nodes(sq, [(125.305, LAT + 0.01)]), b, *nodes(sq, [(125.315, LAT + 0.01)])], 125)
    index = touches.Index(w)
    gone = edits.DeleteWay(v.id)
    gone.apply(sq)
    index.update(sq, {v.id})
    n = sq.nodes[a]
    move = edits.MoveNode(a, (n.lon, n.lat), (n.lon, n.lat + 1e-6))
    move.apply(sq)
    index.update(sq, move.ways(sq))
    assert index.touches() == []
    assert line.id in sq.ways


# --------------------------------------------------------------- forks (#201)
def test_a_contour_that_forks_is_found():
    """A line begun partway along the 200 m and not brought back to it, left
    hanging off its node: three branches of one level at one node."""
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    main = way(sq, [a, b, c], 200)
    branch = way(sq, [b, *nodes(sq, [(125.31, LAT + 0.01)])], 200)
    (t,) = touches.find(w)
    assert t.kind == 'fork' and t.node == b
    assert {t.a[1], t.b[1]} == {main.id, branch.id}
    assert 'fork at node' in t.describe() and 'one line' in t.explain()


def test_three_ends_at_a_node_fork_and_two_do_not():
    w, sq = ws()
    hub = nodes(sq, [(125.31, LAT)])[0]
    way(sq, [*nodes(sq, [(125.30, LAT)]), hub], 200)
    way(sq, [hub, *nodes(sq, [(125.32, LAT)])], 200)
    assert touches.find(w) == [], 'two ways of one contour, joined'
    way(sq, [hub, *nodes(sq, [(125.31, LAT - 0.01)])], 200)
    assert [t.kind for t in touches.find(w)] == ['fork']


def test_a_ring_joined_at_its_seam_is_not_a_fork():
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT + 0.01), (125.32, LAT)])
    way(sq, [a, b, c, a], 200)                          # the ring: two branches at a
    way(sq, [a, *nodes(sq, [(125.29, LAT)])], 200)      # a third
    assert [t.kind for t in touches.find(w)] == ['fork']
    sq.ways.popitem()
    assert touches.find(w) == []


def test_an_edit_asks_only_of_its_own_ways():
    w, sq = ws()
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    main = way(sq, [a, b, c], 200)
    branch = way(sq, [b, *nodes(sq, [(125.31, LAT + 0.01)])], 200)
    other = way(sq, nodes(sq, [(125.40, LAT), (125.41, LAT)]), 200)
    assert touches.find_in(sq, only={other.id}) == []
    assert [t.kind for t in touches.find_in(sq, only={branch.id})] == ['fork']
    assert main



def test_an_x_is_a_saddles_level_and_not_a_fork():
    """Four branches at a node: a contour exactly at a saddle's level, or a
    ring hung off a contour's node. A level line meets itself in pairs."""
    w, sq = ws()
    hub = nodes(sq, [(125.31, LAT)])[0]
    way(sq, [*nodes(sq, [(125.30, LAT)]), hub, *nodes(sq, [(125.32, LAT)])], 200)
    way(sq, [*nodes(sq, [(125.31, LAT + 0.01)]), hub, *nodes(sq, [(125.31, LAT - 0.01)])], 200)
    assert touches.find(w) == []
    way(sq, [hub, *nodes(sq, [(125.305, LAT + 0.01)])], 200)       # a fifth: a fork again
    assert [t.kind for t in touches.find(w)] == ['fork']


def test_an_edits_scan_finds_what_the_whole_scan_does_of_its_way():
    """Short contours running on and off each other and sharing nodes, in a
    ring kilometres round and across a long straight: asked of each way as
    an edit asks - each way cut to the box round it, and only its own pairs
    measured in a cell - the touches are the whole scan's of that way."""
    import math
    import random
    rnd = random.Random(11)
    w, sq = ws()
    stem = nodes(sq, [(125.30 + 0.0004 * j, LAT) for j in range(40)])
    way(sq, stem, 100)
    for _ in range(30):
        j = rnd.randrange(30)
        off = rnd.choice((0.3, 0.6, 5.0)) * M_LAT
        run = nodes(sq, [(125.30 + 0.0004 * (j + i), LAT + off) for i in range(rnd.randint(2, 8))])
        if rnd.random() < 0.3:
            run[0] = stem[j]                                        # sharing a node of the stem
        way(sq, run, rnd.choice((100, 125, 150)))
    # round them all, its box far bigger than any of theirs, and one long
    # segment over many cells, through the middle of them
    way(sq, (lambda r: [*r, r[0]])(nodes(sq, [(125.308 + 0.05 * math.cos(a / 50 * math.tau),
                                               LAT + 0.05 * math.sin(a / 50 * math.tau)) for a in range(50)])), 75)
    way(sq, nodes(sq, [(125.25, LAT + 0.3 * M_LAT), (125.36, LAT + 0.3 * M_LAT)]), 150)
    whole = touches.find_in(sq)
    assert {t.kind for t in whole} == {'shared', 'coincident', 'fork'}
    order = lambda t: (t.kind, t.lat, t.lon, t.a, t.b)               # noqa: E731
    for wid, w_ in sq.ways.items():
        asked = touches.find_in(sq, only={wid})
        # a fork names two of its ways, and is the way's when it is at its node
        assert sorted((t for t in asked if t.kind != 'fork'), key=order) == \
            sorted((t for t in whole if t.kind != 'fork' and wid in (t.a[1], t.b[1])), key=order), wid
        assert {t.node for t in asked if t.kind == 'fork'} == \
            {t.node for t in whole if t.kind == 'fork' and t.node in w_.refs}, wid
