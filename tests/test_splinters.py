"""danu.core.splinters: every chain of small rings picked absorbed into the
line of its level beside it - roantra's valleys, a contour's tip and a chain
of hollows at its level up the river from it. No Qt.

The fixture: a valley running east, its 20, 30 and 40 m lines turning at
tips at x = -400, 0, 800 and 1400; three 30 m rings up from the 30 m tip, and a
40 m ring up from the 40 m one."""

import math

import pytest

pytest.importorskip('osgeo.ogr')

from danu.checks import crossings
from danu.core import edits, splinters
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def way(sq, wid, ele, pts):
    refs = []
    for x, y in pts:
        nid = -(len(sq.nodes) + 1)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    if pts[0] == pts[-1]:                      # a ring: closed onto its first node
        del sq.nodes[refs[-1]]
        refs[-1] = refs[0]
    sq.ways[wid] = Way(id=wid, refs=refs, tags={'contour': 'elevation', 'ele': f'{ele:g}'})
    return sq.ways[wid]


def ring(cx, cy, rx, ry, n=8):
    pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def tip(x, half, far=-3000, spread=0.1):
    """A contour coming up the valley from the west to a tip at x, and back."""
    xs = range(far, int(x) + 1, 100)
    north = [(px, half + spread * (x - px)) for px in xs]
    return north + [(x + half, 0.0)] + [(px, -y) for px, y in reversed(north)]


RINGS = (-11, -12, -13)


def valley():
    sq = Square(name=A, present=True, attrs={})
    w = WorkingSet(centre=A, size=1, squares={A: sq})
    way(sq, 20, 20, tip(-400, 30))
    way(sq, 30, 30, tip(0, 20))
    way(sq, 40, 40, tip(800, 90))
    way(sq, 50, 50, tip(1400, 150))
    for wid, cx in zip(RINGS, (60, 180, 300), strict=True):    # 30 m hollows up from the tip
        way(sq, wid, 30, ring(cx, 0, 40, 25))
    way(sq, -14, 40, ring(960, 0, 50, 40))                     # a 40 m one up from its tip
    return w, sq


def everything(sq):
    return {A: set(sq.nodes)}


def fit(w, picked):
    stack = edits.SetUndoStack()
    p = splinters.plan(w, None, picked, stack.alloc)
    for s, step in p.steps:
        step.apply(s)
    return p


def test_each_chain_is_absorbed_into_the_line_of_its_level():
    w, sq = valley()
    p = fit(w, everything(sq))
    assert (p.rings, p.chains, p.lines) == (4, 2, 2), (p.rings, p.chains, p.lines, p.held)
    assert not [i for i in (*RINGS, -14) if i in sq.ways], 'a splinter left'
    # the 30 m line now runs up past the last of its rings
    xs = [(sq.nodes[r].lon - 125.5) * KX for r in sq.ways[30].refs]
    assert max(xs) > 330, max(xs)
    assert not crossings.find(w)


def test_one_step_undoes_it():
    w, sq = valley()
    was = {wid: list(x.refs) for wid, x in sq.ways.items()}
    stack = edits.SetUndoStack()
    p = splinters.plan(w, None, everything(sq), stack.alloc)
    (s, step), = p.steps
    step.apply(s)
    assert {wid: list(x.refs) for wid, x in sq.ways.items()} != was
    step.undo(s)
    assert {wid: list(x.refs) for wid, x in sq.ways.items()} == was


def test_the_plan_leaves_the_square_as_it_was():
    w, sq = valley()
    was = ({wid: list(x.refs) for wid, x in sq.ways.items()}, dict(sq.nodes))
    splinters.plan(w, None, everything(sq), edits.SetUndoStack().alloc)
    assert ({wid: list(x.refs) for wid, x in sq.ways.items()}, dict(sq.nodes)) == was


def test_only_the_rings_picked():
    w, sq = valley()
    picked = {r for wid in (30, *RINGS) for r in sq.ways[wid].refs}
    p = fit(w, {A: picked})
    assert p.rings == 3 and -14 in sq.ways


def test_a_knoll_is_kept():
    """A small 30 m ring with the 20 m round it is a hill, not a hollow."""
    w, sq = valley()
    way(sq, 21, 20, ring(-1500, 600, 120, 90))
    way(sq, -15, 30, ring(-1500, 600, 40, 30))
    way(sq, 31, 30, [(-1700, 700), (-1300, 700)])               # a 30 m line in reach of it
    p = fit(w, everything(sq))
    assert -15 in sq.ways and p.knolls == 1, (p.knolls, p.held)


def test_a_chain_no_line_reaches_is_listed():
    w, sq = valley()
    way(sq, -16, 30, ring(2000, 0, 40, 25))                      # up past the 40 m tip, far from the 30 m
    p = fit(w, everything(sq))
    assert -16 in sq.ways
    assert any('no 30 m line' in why for why, _, _ in p.held), p.held


def test_one_that_would_cross_is_held_back():
    """A 35 m line across the valley between the first ring and the second."""
    w, sq = valley()
    way(sq, 35, 35, [(120, -100), (120, 100)])
    before = len(crossings.find(w))
    p = fit(w, everything(sq))
    assert all(i in sq.ways for i in RINGS), 'absorbed across the 35 m line'
    assert any('would cross' in why for why, _, _ in p.held), p.held
    assert len(crossings.find(w)) == before
