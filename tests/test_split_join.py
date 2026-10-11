"""Splitting a contour at a node, and joining two at their ends - G8d. No Qt."""

import math

import pytest

from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way

A = SquareName(125, -23)
LAT = -22.70
_ids = iter(range(1000, 10**6))


def sq_():
    return Square(name=A, present=True, attrs={})


def way(sq, pts, ele=100, closed=False):
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


def metres(sq, a, b):
    p, q = sq.nodes[a], sq.nodes[b]
    return math.hypot((q.lon - p.lon) * 111320 * math.cos(math.radians(LAT)), (q.lat - p.lat) * 110540)


def line(sq):
    return way(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT), (125.33, LAT)])


def test_split_makes_two_ways_their_ends_unglued_and_drawn_back():
    sq = sq_()
    w = line(sq)
    a, b, c, d = w.refs
    before = edits.snapshot(sq)
    cmd = edits.split_way(sq, w.id, b, edits.IdAllocator(sq))
    cmd.apply(sq)
    first = sq.ways[w.id]
    (second,) = [x for x in sq.ways.values() if x.id != w.id]
    assert first.refs[0] == a and second.refs[-2:] == [c, d]
    e1, e2 = first.refs[-1], second.refs[0]
    assert e1 != e2 and b not in sq.nodes, 'the node was kept, or shared'
    assert metres(sq, e1, e2) == pytest.approx(2 * edits.SPLIT_GAP_M, abs=0.01)
    assert sq.nodes[e1].lon < 125.31 < sq.nodes[e2].lon, 'each end along its own line'
    assert second.tags == first.tags
    cmd.undo(sq)
    assert edits.snapshot(sq) == before


def test_a_closed_contour_split_opens_into_one_line():
    sq = sq_()
    w = way(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01), (125.30, LAT + 0.01)], closed=True)
    p, q, r, s, _ = w.refs
    edits.split_way(sq, w.id, r, edits.IdAllocator(sq)).apply(sq)
    (only,) = sq.ways.values()
    assert only.id == w.id and only.refs[0] != only.refs[-1]
    assert only.refs[1:-1] == [s, p, q], 'not opened from the node round to it'
    # at a corner: each 5 m along its own side, so 5 m times root 2 apart
    assert metres(sq, only.refs[0], only.refs[-1]) == pytest.approx(edits.SPLIT_GAP_M * math.sqrt(2), abs=0.01)


def test_an_end_or_a_short_segment():
    sq = sq_()
    w = line(sq)
    assert 'an end already' in edits.split_way(sq, w.id, w.refs[0], edits.IdAllocator(sq))
    near = way(sq, [(125.30, LAT + 0.05), (125.30001, LAT + 0.05), (125.31, LAT + 0.05)])
    edits.split_way(sq, near.id, near.refs[1], edits.IdAllocator(sq)).apply(sq)
    # 1 m to the first node: drawn back a third of it, not past it
    assert sq.nodes[sq.ways[near.id].refs[-1]].lon > 125.30


def test_a_node_another_way_holds_stays_for_it():
    sq = sq_()
    w = line(sq)
    b = w.refs[1]
    other = Way(id=next(_ids), refs=[b, *way(sq, [(125.31, LAT + 0.01)]).refs], tags={'ele': '100'})
    sq.ways[other.id] = other
    edits.split_way(sq, w.id, b, edits.IdAllocator(sq)).apply(sq)
    assert b in sq.nodes


def test_join_puts_one_end_onto_the_other_and_makes_one_way():
    sq = sq_()
    w1 = way(sq, [(125.30, LAT), (125.31, LAT)])
    w2 = way(sq, [(125.32, LAT + 0.01), (125.311, LAT)])               # its end near w1's
    before = edits.snapshot(sq)
    cmd = edits.join_ways(sq, w1.id, w1.refs[-1], w2.id, w2.refs[-1])
    cmd.apply(sq)
    (one,) = sq.ways.values()
    assert one.id == w1.id and one.refs == [w1.refs[0], w2.refs[1], w2.refs[0]]
    assert w1.refs[-1] not in sq.nodes, 'the dragged end was left behind'
    cmd.undo(sq)
    assert edits.snapshot(sq) == before


def test_join_onto_its_own_other_end_closes_it():
    sq = sq_()
    w = way(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01), (125.30, LAT + 0.0001)])
    edits.join_ways(sq, w.id, w.refs[-1], w.id, w.refs[0]).apply(sq)
    refs = sq.ways[w.id].refs
    assert refs[0] == refs[-1] and len(refs) == 4


def test_join_refuses_other_levels_middles_and_rings():
    sq = sq_()
    w1 = line(sq)
    w2 = way(sq, [(125.34, LAT), (125.35, LAT)], ele=125)
    assert 'levels differ' in edits.join_ways(sq, w1.id, w1.refs[-1], w2.id, w2.refs[0])
    w3 = line(sq)
    assert 'only an end' in edits.join_ways(sq, w1.id, w1.refs[-1], w3.id, w3.refs[1])
    ring = way(sq, [(125.30, LAT + 0.1), (125.31, LAT + 0.1), (125.31, LAT + 0.11)], closed=True)
    assert 'closed contour' in edits.join_ways(sq, w1.id, w1.refs[-1], ring.id, ring.refs[0])


def test_join_keeps_both_tags_and_refuses_a_disagreement():
    sq = sq_()
    w1 = way(sq, [(125.30, LAT), (125.31, LAT)])
    w2 = way(sq, [(125.32, LAT), (125.311, LAT)])
    w2.tags['source'] = 'survey'
    before = edits.snapshot(sq)
    cmd = edits.join_ways(sq, w1.id, w1.refs[-1], w2.id, w2.refs[-1])
    cmd.apply(sq)
    assert sq.ways[w1.id].tags == {'ele': '100', 'source': 'survey'}, 'the other way\'s tags were lost'
    cmd.undo(sq)
    assert edits.snapshot(sq) == before
    w1.tags['source'] = 'sketch'
    assert 'tags differ - source' in edits.join_ways(sq, w1.id, w1.refs[-1], w2.id, w2.refs[-1])


def test_a_ring_through_the_node_twice_is_not_split_there():
    sq = sq_()
    w = way(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01)])
    p, q, r = w.refs
    w.refs = [p, q, r, q, p]                         # through q twice, closed on p
    assert 'twice' in edits.split_way(sq, w.id, q, edits.IdAllocator(sq))


# ------------------------------------------------------- unglue, G8e

def test_unglue_gives_the_other_contour_its_own_node_drawn_into_its_bend():
    """A 125 m V whose tip is on the 100 m line, sharing its node: the 100 m
    keeps the node, the V's tip comes 5 m back toward its own arms."""
    sq = sq_()
    line = way(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)], 100)
    tip = line.refs[1]
    v = way(sq, [(125.305, LAT + 0.01), (125.31, LAT), (125.315, LAT + 0.01)], 125)
    del sq.nodes[v.refs[1]]
    v.refs[1] = tip
    before = edits.snapshot(sq)
    cmd = edits.unglue_node(sq, line.id, tip, edits.IdAllocator(sq))
    cmd.apply(sq)
    assert sq.ways[line.id].refs[1] == tip and tip not in sq.ways[v.id].refs
    new = sq.nodes[sq.ways[v.id].refs[1]]
    assert new.lat > LAT, 'not drawn into its own bend'
    assert metres(sq, tip, new.id) == pytest.approx(edits.SPLIT_GAP_M, abs=0.01)
    cmd.undo(sq)
    assert edits.snapshot(sq) == before


def test_unglue_moves_one_straight_through_square_to_its_line_away_from_the_kept():
    sq = sq_()
    v = way(sq, [(125.30, LAT + 0.01), (125.31, LAT + 0.0001), (125.32, LAT + 0.02)], 100)    # the kept, a V above
    node = v.refs[1]
    straight = way(sq, [(125.30, LAT + 0.0001), (125.32, LAT + 0.0001)], 125)
    straight.refs.insert(1, node)
    edits.unglue_node(sq, v.id, node, edits.IdAllocator(sq)).apply(sq)
    new = sq.nodes[sq.ways[straight.id].refs[1]]
    assert new.lat < LAT + 0.0001, 'moved toward the way it came off'
    # and the mirror: the kept below, so away is up
    sq = sq_()
    v = way(sq, [(125.30, LAT - 0.01), (125.31, LAT - 0.0001), (125.32, LAT - 0.02)], 100)
    node = v.refs[1]
    straight = way(sq, [(125.30, LAT - 0.0001), (125.32, LAT - 0.0001)], 125)
    straight.refs.insert(1, node)
    edits.unglue_node(sq, v.id, node, edits.IdAllocator(sq)).apply(sq)
    new = sq.nodes[sq.ways[straight.id].refs[1]]
    assert new.lat > LAT - 0.0001, 'moved toward the way it came off'


def test_unglue_a_node_nobody_else_holds_says_so():
    sq = sq_()
    w = line(sq)
    assert 'no other way' in edits.unglue_node(sq, w.id, w.refs[1], edits.IdAllocator(sq))


# --------------------------------------- what the map's buttons ask, H6b

def board_():
    """An open line, a ring, a line through one node twice, and a V sharing
    a node with the line - every way a split or an unglue answers."""
    sq = sq_()
    open_ = line(sq)
    way(sq, [(125.30, LAT + 0.01), (125.31, LAT + 0.01), (125.31, LAT + 0.02)], closed=True)
    twice = way(sq, [(125.30, LAT - 0.01), (125.31, LAT - 0.01), (125.31, LAT - 0.02), (125.305, LAT - 0.02)])
    twice.refs.append(twice.refs[1])
    v = way(sq, [(125.305, LAT + 0.005), (125.31, LAT), (125.315, LAT + 0.005)], 125)
    del sq.nodes[v.refs[1]]
    v.refs[1] = open_.refs[1]
    return sq


def test_a_refusal_is_said_exactly_when_the_edit_refuses():
    """The button greys by the same test the edit makes - every node of
    every way, and a node of no way."""
    sq = board_()
    asked = 0
    for wid, w in list(sq.ways.items()):
        for nid in [*dict.fromkeys(w.refs), next(iter(set(sq.nodes) - set(w.refs)))]:
            for refusal, edit in ((edits.split_refusal, edits.split_way), (edits.unglue_refusal, edits.unglue_node)):
                why = refusal(sq, wid, nid)
                cmd = edit(sq, wid, nid, edits.IdAllocator(sq))
                assert (why is None) == (not isinstance(cmd, str)), (edit.__name__, wid, nid, why, cmd)
                assert why is None or why == cmd
                asked += why is None
    assert asked >= 8, 'some of each answer'
    assert edits.split_refusal(sq, -1, 1) == 'that way is no longer there'


def test_a_ring_splits_at_its_first_node_and_a_node_off_the_way_is_not_unglued():
    sq = board_()
    ring = next(w for w in sq.ways.values() if w.closed)
    assert edits.split_refusal(sq, ring.id, ring.refs[0]) is None
    open_ = next(w for w in sq.ways.values() if w.ele == 100 and not w.closed and len(set(w.refs)) == len(w.refs))
    v = next(w for w in sq.ways.values() if w.ele == 125)
    off = v.refs[0]                                     # the V's, not the line's
    assert edits.unglue_refusal(sq, open_.id, off) == 'that node is not on the way selected'
