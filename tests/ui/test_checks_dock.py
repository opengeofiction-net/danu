"""The checks panel, its first check - contours that cross (G8a, R16).

In the fixture's blank square to the north: a rogue contour drawn across
three others, through the editor so the panel follows the edits as it would
a mapper's.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m

from .conftest import menu

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
    return [r.text(0) for r in dock.rows('crossings')]


def test_opening_the_panel_lists_the_contour_that_crosses_most_first(crossed):
    w, rogue = crossed
    rows = top_rows(w.checks_dock)
    assert rows[0].startswith(f'425 m contour, way {rogue}') and 'crosses 3 contours' in rows[0]
    assert len(rows) == 4
    node = w.checks_dock.node('crossings')
    assert node.text(0) == 'Crossing contours (4)' and '3 crossings among 4 contours' in node.toolTip(0)


def test_the_map_marks_crossings_only_while_the_panel_is_open(crossed):
    w, _ = crossed
    # the 3 crossings, the touches the golden square holds (G8e), and what its file says (H1a)
    assert len(w.editor.marks) == 3 + len(w.touch_index.touches()) + len(w.file_index.findings())
    w.checks_dock.hide()
    assert w.editor.marks == []


def test_centre_square_only_keeps_the_centre_squares_findings(crossed):
    """The rogue's crossings are in the square to the north: listed and
    marked for the set, neither for its centre alone - and the choice kept."""
    w, _ = crossed
    dock = w.checks_dock
    assert w.working_set.centre != NORTH and len(dock.rows('crossings')) == 4
    west, south, east, north = w.working_set.centre.bounds
    x0, y0 = m.lonlat_to_scene(west, north)
    x1, y1 = m.lonlat_to_scene(east, south)
    marks = list(w.editor.marks)
    # the projection keeps order, so in the scene is in the square: _shown's own test
    inside = [(x, y) for x, y in marks if x0 <= x <= x1 and y0 <= y <= y1]
    assert len(inside) <= len(marks) - 3                     # the rogue's three are outside
    dock.centre_only.setChecked(True)
    assert dock.rows('crossings') == [] and dock.node('crossings').text(0) == 'Crossing contours (0)'
    assert sorted(w.editor.marks) == sorted(inside) and w.settings.checks_centre_only
    dock.centre_only.setChecked(False)
    assert len(dock.rows('crossings')) == 4 and w.editor.marks == marks
    assert not w.settings.checks_centre_only


def test_choosing_a_row_selects_the_contour_and_rings_its_crossings(crossed):
    w, rogue = crossed
    dock = w.checks_dock
    dock.tree.setCurrentItem(dock.rows('crossings')[0])
    assert w.editor.selection is not None and w.editor.selection.way.id == rogue
    assert len(w.editor.marks_focus) == 3
    assert 'delete it or redraw over it' in w.statusBar().currentMessage()
    child = dock.rows('crossings')[0].child(0)
    dock.tree.setCurrentItem(child)
    assert len(w.editor.marks_focus) == 1, 'a partner row rings only the crossings with it'


def test_the_panel_follows_an_edit_and_its_undo(crossed, qtbot):
    w, rogue = crossed
    sq = w.working_set.squares[NORTH]
    draw(w, [(125.15, -22.8), (125.15, -22.6)], 75)              # a fourth crossing
    qtbot.waitUntil(lambda: 'crosses 4 contours' in top_rows(w.checks_dock)[0], timeout=2000)
    w.editor.do(sq, edits.DeleteWay(rogue))
    qtbot.waitUntil(lambda: top_rows(w.checks_dock) == [], timeout=2000)
    assert w.checks_dock.node('crossings').text(0) == 'Crossing contours (0)'
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


def test_the_panel_is_in_the_view_menu(window):
    assert window.checks_dock.toggleViewAction() in menu(window.menuBar(), 'View').actions()
