"""The checks panel, its first check - contours that cross (G8a, R16).

In the fixture's blank square to the north: a rogue contour drawn across
three others, through the editor so the panel follows the edits as it would
a mapper's.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import SquareName

NORTH = SquareName(125, -23)


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return wid


def open_panel(w):
    """As a mapper does, from the Edit menu - which raises the tab, where
    showing a tabbed dock alone leaves it behind the surface panel."""
    w.checks_dock.toggleViewAction().trigger()


@pytest.fixture
def crossed(window, qtbot):
    for k in range(3):
        draw(window, [(125.2 + 0.1 * k, -22.8), (125.2 + 0.1 * k, -22.6)], 100 + 25 * k)
    rogue = draw(window, [(125.1, -22.7), (125.6, -22.7)], 425)
    open_panel(window)
    qtbot.waitUntil(lambda: window.crossing_index is not None, timeout=5000)
    return window, rogue


def top_rows(dock):
    return [dock.tree.topLevelItem(i).text(0) for i in range(dock.tree.topLevelItemCount())]


def test_opening_the_panel_lists_the_contour_that_crosses_most_first(crossed):
    w, rogue = crossed
    rows = top_rows(w.checks_dock)
    assert rows[0].startswith(f'425 m contour, way {rogue}') and 'crosses 3 contours' in rows[0]
    assert len(rows) == 4
    assert '3 crossings between contours' in w.checks_dock.summary.text()


def test_the_map_marks_crossings_only_while_the_panel_is_open(crossed):
    w, _ = crossed
    # the 3 crossings, and the touches the golden square holds (G8e)
    assert len(w.editor.marks) == 3 + len(w.touch_index.touches())
    w.checks_dock.hide()
    assert w.editor.marks == []


def test_choosing_a_row_selects_the_contour_and_rings_its_crossings(crossed):
    w, rogue = crossed
    dock = w.checks_dock
    dock.tree.setCurrentItem(dock.tree.topLevelItem(0))
    assert w.editor.selection is not None and w.editor.selection.way.id == rogue
    assert len(w.editor.marks_focus) == 3
    assert 'delete it or redraw over it' in w.statusBar().currentMessage()
    child = dock.tree.topLevelItem(0).child(0)
    dock.tree.setCurrentItem(child)
    assert len(w.editor.marks_focus) == 1, 'a partner row rings only the crossings with it'


def test_the_panel_follows_an_edit_and_its_undo(crossed, qtbot):
    w, rogue = crossed
    sq = w.working_set.squares[NORTH]
    draw(w, [(125.15, -22.8), (125.15, -22.6)], 75)              # a fourth crossing
    qtbot.waitUntil(lambda: 'crosses 4 contours' in top_rows(w.checks_dock)[0], timeout=2000)
    w.editor.do(sq, edits.DeleteWay(rogue))
    qtbot.waitUntil(lambda: top_rows(w.checks_dock) == [], timeout=2000)
    assert 'No contour crosses another' in w.checks_dock.summary.text()
    w.editor.undo()
    qtbot.waitUntil(lambda: len(top_rows(w.checks_dock)) == 5, timeout=2000)


def test_nothing_is_built_until_the_panel_is_opened(window):
    """Opening a working set does not pay for a check nobody is looking at:
    3.6 s on gobras."""
    assert window.crossing_index is None
    draw(window, [(125.1, -22.7), (125.6, -22.7)], 425)
    assert window.crossing_index is None
    open_panel(window)
    assert window.crossing_index is not None and window.crossing_index.crossings() == []


def test_the_panel_is_in_the_edit_menu(window):
    assert window.checks_dock.toggleViewAction() in window.menuBar().actions()[1].menu().actions()
