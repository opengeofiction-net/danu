"""Contours that cross, as a check of what the squares hold - R16, G8a.
No Qt, no GDAL."""

import random

import pytest

from danu.checks import crossings
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, WorkingSet

A, B = SquareName(125, -24), SquareName(126, -24)
_ids = iter(range(1, 10**6))


def ws():
    squares = {n: Square(name=n, present=True, attrs={}) for n in (A, B)}
    return WorkingSet(centre=A, size=1, squares=squares)


def line(sq, pts, ele, tags=None):
    refs = []
    for lon, lat in pts:
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags={'ele': str(ele), **(tags or {})})
    return sq.ways[i]


def keys(found):
    return sorted((tuple(sorted((c.a[1], c.b[1]))), round(c.lon, 6), round(c.lat, 6)) for c in found)


def test_two_contours_that_cross_are_one_crossing_where_they_cross():
    w = ws(); sq = w.squares[A]
    a = line(sq, [(125.1, -23.5), (125.3, -23.5)], 100)
    b = line(sq, [(125.2, -23.6), (125.2, -23.4)], 125)
    (c,) = crossings.find(w)
    assert {c.a[1], c.b[1]} == {a.id, b.id}
    assert c.lon == pytest.approx(125.2) and c.lat == pytest.approx(-23.5)


def test_contours_that_touch_at_a_node_or_run_apart_do_not_cross():
    w = ws(); sq = w.squares[A]
    a = line(sq, [(125.1, -23.5), (125.3, -23.5)], 100)
    b = line(sq, [(125.1, -23.6), (125.3, -23.6)], 125)
    c = line(sq, [(125.1, -23.7), (125.1, -23.6)], 150)
    c.refs[-1] = b.refs[0]                                     # ends on b's first node
    t = line(sq, [(125.4, -23.6), (125.3, -23.5)], 75)
    t.refs[-1] = a.refs[-1]                                    # snapped to a's end
    assert crossings.find(w) == []


def test_a_crossing_across_two_squares_is_found():
    w = ws()
    line(w.squares[A], [(125.9, -23.5), (126.1, -23.5)], 100)   # overhangs into B's ground
    line(w.squares[B], [(126.0, -23.6), (126.0, -23.4)], 125)
    assert len(crossings.find(w)) == 1


def test_a_lakes_outline_and_its_fill_lines_are_not_contours_here():
    w = ws(); sq = w.squares[A]
    line(sq, [(125.1, -23.5), (125.3, -23.5)], 100)
    line(sq, [(125.2, -23.6), (125.2, -23.4)], 100, {'danu:fill': 'way/1'})
    ring = line(sq, [(125.15, -23.6), (125.25, -23.6), (125.25, -23.4), (125.15, -23.4)], 100)
    ring.refs.append(ring.refs[0])
    sq.relations[1] = Relation(id=1, tags={'natural': 'water', 'ele': '100'},
                               members=[Member('way', ring.id, 'outer')])
    assert crossings.find(w) == []


def test_the_contour_that_crosses_the_most_others_comes_first():
    w = ws(); sq = w.squares[A]
    rogue = line(sq, [(125.0, -23.5), (125.9, -23.5)], 425)
    for k in range(3):
        line(sq, [(125.1 + 0.2 * k, -23.6), (125.1 + 0.2 * k, -23.4)], 100 + 25 * k)
    line(sq, [(125.05, -23.7), (125.05, -23.3)], 50)
    groups = crossings.by_contour(crossings.find(w))
    assert groups[0].contour[1] == rogue.id and len(groups[0].partners) == 4
    assert groups[0].describe().startswith('425 m contour, way') and 'crosses 4 contours' in groups[0].describe()


def test_a_contour_that_crosses_another_twice_says_how_many_times():
    w = ws(); sq = w.squares[A]
    line(sq, [(125.1, -23.5), (125.3, -23.5)], 100)
    line(sq, [(125.15, -23.6), (125.2, -23.4), (125.25, -23.6)], 125)
    (g, _) = crossings.by_contour(crossings.find(w))
    assert g.describe().endswith('crosses 1 contour, 2 times')


# ------------------------------------------------------------- kept as edited

def scene():
    """A grid of contours, some crossing, in two squares."""
    w = ws()
    rng = random.Random(4)
    for sq, lon0 in ((w.squares[A], 125.0), (w.squares[B], 126.0)):
        for _ in range(12):
            pts = [(lon0 + rng.random(), -24 + rng.random()) for _ in range(rng.randint(2, 6))]
            line(sq, pts, 25 * rng.randint(1, 8))
    return w


def test_the_index_after_each_kind_of_edit_is_what_a_full_scan_finds():
    w = scene()
    idx = crossings.Index(w)
    assert keys(idx.crossings()) == keys(crossings.find(w))
    sq = w.squares[A]
    ways = list(sq.ways.values())
    # a node moved
    n = sq.nodes[ways[0].refs[0]]
    n.lon, n.lat = n.lon + 0.3, n.lat - 0.2
    idx.update(sq, {ways[0].id})
    assert keys(idx.crossings()) == keys(crossings.find(w)), 'a node moved'
    # a way deleted
    del sq.ways[ways[1].id]
    idx.update(sq, {ways[1].id})
    assert keys(idx.crossings()) == keys(crossings.find(w)), 'a way deleted'
    # a way drawn across everything
    new = line(sq, [(125.0, -23.5), (125.99, -23.5)], 600)
    idx.update(sq, {new.id})
    assert keys(idx.crossings()) == keys(crossings.find(w)), 'a way drawn'
    # a way no longer a contour
    del ways[2].tags['ele']
    idx.update(sq, {ways[2].id})
    assert keys(idx.crossings()) == keys(crossings.find(w)), 'an ele taken off'
    # re-levelled: the crossing is the same, its level is not
    ways[3].tags['ele'] = '999'
    idx.update(sq, {ways[3].id})
    assert {c.a[2] for c in idx.crossings() if c.a[1] == ways[3].id} | \
           {c.b[2] for c in idx.crossings() if c.b[1] == ways[3].id} <= {999.0}
    assert keys(idx.crossings()) == keys(crossings.find(w))


def test_the_index_on_a_working_set_with_no_contours_is_empty():
    assert crossings.Index(ws()).crossings() == []


def test_a_long_straight_is_found_crossing_wherever_along_it():
    """A segment tens of kilometres long - a straight along a square's edge,
    a degree drawn across - is put in the cells along its line, not its box;
    every crossing on it is still found."""
    w = ws(); sq = w.squares[A]
    line(sq, [(125.0, -24.0), (125.9, -23.1)], 600)              # one segment, 125 km
    for k in range(1, 9):
        x = 125.0 + 0.1 * k
        line(sq, [(x - 0.002, x - 125.0 - 24.0 + 0.002), (x + 0.002, x - 125.0 - 24.0 - 0.002)], 100)
    assert len(crossings.find(w)) == 8
    idx = crossings.Index(w)
    assert len(idx.crossings()) == 8


def test_a_contour_crossing_itself_is_not_this_checks():
    """Crossings between contours. One that loops over itself is broken in
    its own way, and another check's."""
    w = ws(); sq = w.squares[A]
    line(sq, [(125.1, -23.5), (125.3, -23.5), (125.3, -23.4), (125.2, -23.6)], 100)
    line(sq, [(125.251, -23.501), (125.252, -23.501)], 75)        # in its cell, so the cell is tested
    assert crossings.find(w) == []
