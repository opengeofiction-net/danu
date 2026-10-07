"""A river level a contour beside it contradicts, listed with what a grade
found - G7c. In the fixture's blank square to the north: a river imported as
a mapper would, graded from the contours it crosses, and one contour that
runs beside it far above its level."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way
from danu.ui.tools import Selection
from danu.ui.water import Answer
from danu.water import overpass

NORTH = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return sq.ways[wid]


@pytest.fixture
def beside(window):
    water = overpass.Water()
    for k in range(41):
        water.nodes[k + 1] = Node(id=k + 1, lon=125.30 + 0.0025 * k + 0.0001, lat=LAT)
    water.ways[100] = Way(id=100, refs=list(range(1, 42)), tags={'waterway': 'river', 'name': 'Merta'})
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways), frozenset()), window.working_set)
    # the 50 m within the grade's 5 km of the 75 m, so the stretch between is graded
    for lon, ele in ((125.31, 100), (125.33, 75), (125.37, 50)):
        draw(window, [(lon, LAT - 0.02), (lon, LAT + 0.02)], ele)
    # 10 m north of the river, from 125.35 to 125.36, where it is graded 56 to 63 m
    cliff = draw(window, [(125.35, LAT + 10 * M_LAT), (125.36, LAT + 10 * M_LAT)], 125)
    sq = window.working_set.squares[NORTH]
    window.editor.selection = Selection(sq, sq.ways[100])
    return window, sq, cliff


def steep(w):
    return [i for i in w.editor.proposal.issues if i.kind == 'steep']


def test_g_lists_a_contour_beside_the_river_far_above_its_level(beside):
    w, sq, cliff = beside
    w.editor.grade()
    p = w.editor.proposal
    (issue,) = steep(w)
    assert 'Merta: the 125 m contour comes 10 m from it' in issue.text and 'above its level' in issue.text
    assert issue.span is not None, 'not shown on the profile'
    assert '1 place where a contour within 30 m is over 25 m off its level' in p.summary
    assert p.acceptable, 'the grade itself still goes'


def test_shift_g_lists_it_too(beside):
    w, sq, cliff = beside
    w.editor.grade_network()
    assert len(steep(w)) == 1
    assert '1 place where a contour within 30 m' in w.editor.proposal.summary


def test_moved_clear_it_is_not_listed(beside):
    w, sq, cliff = beside
    for r in cliff.refs:
        n = sq.nodes[r]
        w.editor.do(sq, edits.MoveNode(r, (n.lon, n.lat), (n.lon, LAT + 60 * M_LAT)))
    w.editor.selection = Selection(sq, sq.ways[100])
    w.editor.grade()
    assert steep(w) == []
