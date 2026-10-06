"""Moving a contour whole - shift and drag (G8b).

A contour whose shape is right and whose place is not - the checks panel
finds them crossing their neighbours - is carried to where it belongs as one
step. In the fixture's blank square to the north, with real mouse events.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
SHIFT = Qt.KeyboardModifier.ShiftModifier


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return sq.ways[wid]


def at(w, lon, lat) -> QPointF:
    return QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat))))


def drag(w, frm, to, mods=SHIFT, steps=4):
    """Press at one (lon, lat), move in steps, release at another."""
    a, b = at(w, *frm), at(w, *to)
    vp = w.map.viewport()

    def ev(kind, pos, button, buttons):
        return QMouseEvent(kind, pos, vp.mapToGlobal(pos.toPoint()), button, buttons, mods)
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton,
                             Qt.MouseButton.LeftButton))
    seen = []
    for k in range(1, steps + 1):
        p = a + (b - a) * (k / steps)
        w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton,
                                Qt.MouseButton.LeftButton))
        seen.append(w.editor.ghost is not None)
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton,
                               Qt.MouseButton.NoButton))
    return seen


def place(sq, way):
    return [(round(sq.nodes[r].lon, 4), round(sq.nodes[r].lat, 4)) for r in way.refs]


@pytest.fixture
def board(window):
    """Two north-south contours, and a rogue running east-west across both."""
    a = draw(window, [(125.30, -22.75), (125.30, -22.65)], 100)
    b = draw(window, [(125.34, -22.75), (125.34, -22.65)], 125)
    rogue = draw(window, [(125.28, -22.70), (125.36, -22.70)], 425)
    window.map.set_zoom(13)
    window.map.center_on_lonlat(125.32, -22.70)
    return window, window.working_set.squares[NORTH], a, b, rogue


def test_shift_and_a_drag_carries_a_contour_clear_and_ctrl_z_puts_it_back(board):
    w, sq, a, b, rogue = board
    before = edits.snapshot(sq)
    seen = drag(w, (125.32, -22.70), (125.32, -22.60))          # north, clear of both
    assert any(seen), 'nothing showed where it would go'
    assert w.editor.ghost is None, 'the ghost stayed after the drop'
    assert place(sq, rogue) == [(125.28, -22.60), (125.36, -22.60)]
    assert 'crosses nothing now' in w.statusBar().currentMessage()
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not put it back'


def test_a_move_that_would_cross_a_contour_it_does_not_cross_now_is_refused(board):
    w, sq, a, b, rogue = board
    c = draw(w, [(125.38, -22.75), (125.38, -22.65)], 150)
    was = place(sq, rogue)
    drag(w, (125.32, -22.70), (125.36, -22.70))                  # east, across the 150 m
    assert place(sq, rogue) == was
    assert 'not moved' in w.statusBar().currentMessage() and '150 m' in w.statusBar().currentMessage()
    assert c.id in sq.ways


def test_a_move_that_leaves_a_crossing_it_already_had_is_done_and_says_so(board):
    w, sq, a, b, rogue = board
    drag(w, (125.32, -22.70), (125.30, -22.70))                  # west: clears the 125 m, still on the 100 m
    (west, _), (east, _) = place(sq, rogue)
    assert west == pytest.approx(125.26, abs=2e-4) and east == pytest.approx(125.34, abs=2e-4)
    assert 'still crosses 1 contour' in w.statusBar().currentMessage()


def test_a_contour_comes_away_from_a_node_it_shares(board):
    w, sq, a, b, rogue = board
    rogue.refs[0] = a.refs[0]                                     # snapped to the 100 m's end
    shared = sq.nodes[a.refs[0]]
    where = (shared.lon, shared.lat)
    w.contours.set_working_set(w.working_set)
    # its line runs from that node now: pressed half way along it
    drag(w, (125.33, -22.725), (125.33, -22.625))
    assert (shared.lon, shared.lat) == where, 'the other contour was dragged along'
    assert rogue.refs[0] != a.refs[0]
    assert 'came away from 1 node it shared' in w.statusBar().currentMessage()


def test_without_shift_a_drag_still_moves_one_node(board):
    w, sq, a, b, rogue = board
    end = sq.nodes[rogue.refs[-1]]
    drag(w, (end.lon, end.lat), (125.37, -22.60), mods=Qt.KeyboardModifier.NoModifier)
    assert place(sq, rogue)[0] == (125.28, -22.70), 'the whole contour moved'


def test_the_checks_panel_follows_a_contour_carried_clear(board, qtbot):
    w, sq, a, b, rogue = board
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.crossing_index is not None, timeout=5000)
    assert len(w.crossing_index.crossings()) == 2
    drag(w, (125.32, -22.70), (125.32, -22.60))
    qtbot.waitUntil(lambda: 'No contour crosses another' in w.checks_dock.summary.text(), timeout=2000)


def test_the_contour_selected_is_carried_though_another_runs_nearer(board):
    """Chosen in the checks panel, then shift-dragged: in a massif a press is
    near several contours, and the selected one is the one meant."""
    w, sq, a, b, rogue = board
    from danu.ui.tools import Selection
    w.editor.selection = Selection(sq, rogue)
    # pressed on the 100 m, some 3 px off the rogue: the 100 m is the
    # nearer, and the rogue is still under the press
    drag(w, (125.30, -22.6995), (125.30, -22.5995))
    lats = [lat for _, lat in place(sq, rogue)]
    assert lats == pytest.approx([-22.60, -22.60], abs=2e-4), 'the rogue was not the one carried'
    assert place(sq, a) == [(125.30, -22.75), (125.30, -22.65)]
