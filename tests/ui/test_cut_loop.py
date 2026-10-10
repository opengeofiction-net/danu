"""The checks panel's second check - a contour crossing itself - and cutting
the loop out (G8c, R16).

In the fixture's blank square to the north: a figure of eight's crossing,
drawn through the editor so the panel follows the edits.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import SquareName

NORTH = SquareName(125, -23)
LAT = -22.70


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return sq.ways[wid]


@pytest.fixture
def looped(window, qtbot):
    """East, north, west back across itself, and south: it crosses itself
    at (125.31, LAT)."""
    way = draw(window, [(125.30, LAT), (125.32, LAT), (125.32, LAT + 0.02), (125.31, LAT + 0.02),
                        (125.31, LAT - 0.02)], 150)
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.loop_index is not None, timeout=5000)
    return window, window.working_set.squares[NORTH], way


def rows(dock):
    return [dock.loops_tree.topLevelItem(i).text(0) for i in range(dock.loops_tree.topLevelItemCount())]


def choose(w):
    w.checks_dock.loops_tree.setCurrentItem(w.checks_dock.loops_tree.topLevelItem(0))


def test_the_panel_lists_a_contour_crossing_itself(looped):
    w, sq, way = looped
    assert rows(w.checks_dock) == [f'150 m contour, way {way.id} - crosses itself']
    assert '1 place where a contour crosses itself' in w.checks_dock.loops_summary.text()
    assert not w.checks_dock.cut_btn.isEnabled(), 'the button before a loop is chosen'


def test_choosing_it_selects_the_contour_and_rings_the_place(looped):
    w, sq, way = looped
    choose(w)
    assert w.editor.selection.way.id == way.id
    assert len(w.editor.marks_focus) == 1
    assert 'O proposes the loop cut out' in w.statusBar().currentMessage()
    assert w.checks_dock.cut_btn.isEnabled()


def test_o_proposes_the_cut_enter_does_it_and_the_panel_follows(looped, qtbot):
    w, sq, way = looped
    before = edits.snapshot(sq)
    choose(w)
    w.edit_actions['edit.cut_loop'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'loop' and p.acceptable
    assert p.summary.startswith('cut out the loop:') and 'of the 150 m contour and 3 nodes go' in p.summary
    assert p.removed, 'what goes is not shown'
    assert edits.snapshot(sq) == before, 'proposing changed the square'
    w.editor.accept_proposal()
    assert len(sq.ways[way.id].refs) == 3
    assert w.editor.selection.way is sq.ways[way.id], 'the selection is the contour as it was'
    qtbot.waitUntil(lambda: rows(w.checks_dock) == [], timeout=2000)
    assert 'No contour crosses itself' in w.checks_dock.loops_summary.text()
    assert w.checks_dock.loops_tree.isHidden(), 'an empty list still takes the panel'
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not put the loop back'
    qtbot.waitUntil(lambda: len(rows(w.checks_dock)) == 1, timeout=2000)


def test_the_button_proposes_it_too(looped):
    w, sq, way = looped
    choose(w)
    w.checks_dock.cut_btn.click()
    assert w.editor.proposal is not None and w.editor.proposal.kind == 'loop'


def test_o_with_nothing_chosen_says_how(looped):
    w, sq, way = looped
    w.edit_actions['edit.cut_loop'].trigger()
    assert w.editor.proposal is None
    assert 'O cuts out the loop' in w.statusBar().currentMessage()


def test_o_is_the_key(window):
    assert window.edit_actions['edit.cut_loop'].shortcut().toString() == 'O'


def test_a_contour_with_nodes_twice_in_a_row_is_mended_in_one_cut(window, qtbot):
    """Two rows for the one contour; O on either holds both nodes once."""
    sq = window.working_set.squares[NORTH]
    alloc = window.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in range(4)]
    pts = [(125.40, LAT), (125.41, LAT), (125.42, LAT), (125.43, LAT)]
    window.editor.do(sq, edits.AddWay(wid, ids, pts, {'ele': '160'}))
    window.editor.do(sq, edits.ReplaceWay(wid, [(wid, [ids[0], ids[1], ids[1], ids[2], ids[2], ids[3]])], {}))
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.loop_index is not None, timeout=5000)
    assert rows(window.checks_dock) == [f'160 m contour, way {wid} - through node {n} twice in a row'
                                        for n in ids[1:3]]
    choose(window)
    window.edit_actions['edit.cut_loop'].trigger()
    p = window.editor.proposal
    assert p is not None and p.summary == '2 nodes of the 160 m contour held twice in a row, held once'
    window.editor.accept_proposal()
    assert sq.ways[wid].refs == ids
    qtbot.waitUntil(lambda: rows(window.checks_dock) == [], timeout=2000)
