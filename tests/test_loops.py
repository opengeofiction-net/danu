"""Contours that cross themselves - G8c, R16 asked of one contour. No Qt.

Shapes drawn in metres-ish degrees near the equator, so a loop's length
can be read off by hand.
"""

import pytest

from danu.checks import loops
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
LAT = -22.70
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


def way(sq, refs, ele=100, closed=False):
    if closed:
        refs = [*refs, refs[0]]
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=list(refs), tags={'ele': str(ele)})
    return sq.ways[i]


def alloc(s):
    return edits.IdAllocator(s)


def apply(sq, w, loop):
    c = loops.cut(sq, w, loop, alloc)
    assert not isinstance(c, str), c
    c.command.apply(sq)
    return c


def test_a_line_crossing_itself_is_found_where_it_crosses():
    """East, then north, west across its own first stretch, and south: a
    figure of eight's crossing at (125.305, LAT)."""
    w, sq = ws()
    x = way(sq, nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01), (125.305, LAT + 0.01),
                           (125.305, LAT - 0.01)]))
    (lp,) = loops.find(w)
    assert lp.kind == 'crossing' and (lp.i, lp.j) == (0, 3)
    assert (lp.lon, lp.lat) == pytest.approx((125.305, LAT))
    assert lp.contour == (A, x.id, 100.0)


def test_cutting_a_crossing_out_puts_a_node_where_it_crossed_and_drops_the_loop():
    w, sq = ws()
    refs = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01), (125.305, LAT + 0.01),
                      (125.305, LAT - 0.01)])
    x = way(sq, refs)
    before = edits.snapshot(sq)
    (lp,) = loops.find(w)
    c = apply(sq, x, lp)
    kept = sq.ways[x.id].refs
    assert kept[0] == refs[0] and kept[-1] == refs[-1] and len(kept) == 3
    mid = sq.nodes[kept[1]]
    assert (mid.lon, mid.lat) == pytest.approx((125.305, LAT))
    assert refs[2] not in sq.nodes and refs[3] not in sq.nodes, 'the loop\'s nodes were left behind'
    assert c.nodes == 3 and loops.find(w) == []
    c.command.undo(sq)
    assert edits.snapshot(sq) == before


def test_a_pinch_is_a_node_held_twice_and_cutting_it_keeps_the_node_once():
    w, sq = ws()
    a, b, c_, d, e = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01),
                                (125.32, LAT + 0.01), (125.30, LAT - 0.01)])
    x = way(sq, [a, b, c_, d, b, e])                    # out from b, round and back to it
    (lp,) = loops.find(w)
    assert lp.kind == 'pinch' and lp.node == b and (lp.i, lp.j) == (1, 4)
    apply(sq, x, lp)
    assert sq.ways[x.id].refs == [a, b, e]


def test_a_node_twice_in_a_row_is_said_so_and_one_cut_takes_every_such_in_the_way():
    """w-65047261 in Gobras City: a ring drawn with a double at four clicks.
    No loop to cut - a segment of no length - and four rows of the panel to
    mend one at a time; the one cut holds every node once."""
    w, sq = ws()
    a, b, c_, d = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01), (125.30, LAT + 0.01)])
    x = way(sq, [a, b, b, c_, c_, d, d], closed=True)
    found = loops.find(w)
    assert [lp.node for lp in found] == [b, c_, d] and all(lp.doubled for lp in found)
    assert found[0].describe().endswith(f'through node {b} twice in a row')
    c = apply(sq, x, found[1])
    assert sq.ways[x.id].refs == [a, b, c_, d, a] and c.doubles == 3 and c.nodes == 0
    assert loops.find(w) == [] and all(n in sq.nodes for n in (a, b, c_, d))


def test_a_pinch_with_a_loop_is_not_said_to_be_in_a_row():
    w, sq = ws()
    a, b, c_, d, e = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01),
                                (125.32, LAT + 0.01), (125.30, LAT - 0.01)])
    way(sq, [a, b, c_, d, b, e])
    (lp,) = loops.find(w)
    assert not lp.doubled and lp.describe().endswith(f'through node {b} twice')


def test_a_spike_out_and_back_along_a_segment_is_a_pinch_cut_the_same():
    w, sq = ws()
    a, b, c_, d = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.003), (125.32, LAT)])
    x = way(sq, [a, b, c_, b, d])
    (lp,) = loops.find(w)
    apply(sq, x, lp)
    assert sq.ways[x.id].refs == [a, b, d]


def test_a_closed_contour_loses_the_shorter_side():
    """A ring pinched at one node into a big lobe and a small one: the small
    one goes, whichever side of the start it is."""
    w, sq = ws()
    p, q, r, s, t, u = nodes(sq, [(125.30, LAT), (125.32, LAT), (125.32, LAT + 0.02),
                                  (125.30, LAT + 0.02), (125.29, LAT - 0.001), (125.29, LAT + 0.001)])
    x = way(sq, [p, t, u, p, q, r, s], closed=True)     # small lobe first, then the big one
    (lp,) = loops.find(w)
    c = apply(sq, x, lp)
    assert sq.ways[x.id].refs == [p, q, r, s, p]
    assert c.nodes == 2
    # and the big lobe first, then the small one
    p2, q2, r2, s2, t2, u2 = nodes(sq, [(125.40, LAT), (125.42, LAT), (125.42, LAT + 0.02),
                                        (125.40, LAT + 0.02), (125.39, LAT - 0.001), (125.39, LAT + 0.001)])
    y = way(sq, [p2, q2, r2, s2, p2, t2, u2], closed=True)
    (lp,) = [lp for lp in loops.find(w) if lp.contour[1] == y.id]
    apply(sq, y, lp)
    assert sq.ways[y.id].refs == [p2, q2, r2, s2, p2]


def test_a_run_out_and_back_over_the_same_nodes_goes_with_its_outer_pinch():
    """Along a straight edge and back over the same nodes - the shape at the
    edge of the contour area on gobras: a pinch at each node of the run, one
    inside the other. The outer one cut takes the whole run; the inner one
    first leaves the outer still to cut."""
    for first in (0, 1):
        w, sq = ws()
        a, b, c_, d, e = nodes(sq, [(125.30, LAT - 0.01), (125.31, LAT), (125.31, LAT + 0.01),
                                    (125.31, LAT + 0.02), (125.32, LAT - 0.01)])
        x = way(sq, [a, b, c_, d, c_, b, e])
        found = loops.find(w)
        assert [lp.node for lp in found] == [b, c_]
        apply(sq, x, found[first])
        if first:
            (lp,) = loops.find(w)
            apply(sq, x, lp)
        assert sq.ways[x.id].refs == [a, b, e] and loops.find(w) == []


def test_a_loop_already_gone_is_not_cut():
    w, sq = ws()
    a, b, c_, d = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.003), (125.32, LAT)])
    x = way(sq, [a, b, c_, b, d])
    (lp,) = loops.find(w)
    apply(sq, x, lp)
    assert 'no longer there' in loops.cut(sq, x, lp, alloc)


def test_the_index_follows_an_edit():
    w, sq = ws()
    a, b, c_, d = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.003), (125.32, LAT)])
    x = way(sq, [a, b, c_, b, d])
    index = loops.Index(w)
    (lp,) = index.loops()
    c = apply(sq, x, lp)
    index.update(sq, {x.id})
    assert index.loops() == []
    c.command.undo(sq)
    index.update(sq, {x.id})
    assert index.loops() == [lp]


def test_a_contour_meeting_itself_only_at_its_closing_node_is_not_a_loop():
    w, sq = ws()
    way(sq, nodes(sq, [(125.30, LAT), (125.31, LAT), (125.31, LAT + 0.01)]), closed=True)
    assert loops.find(w) == []
