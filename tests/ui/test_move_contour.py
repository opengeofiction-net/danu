"""Moving a contour whole - shift and drag (G8b).

A contour whose shape is right and whose place is not - the Validation panel
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


def test_a_contour_that_crosses_nothing_may_not_be_moved_into_a_crossing(board):
    """That is good data, and the refusal says what it would cross and rings
    where."""
    w, sq, a, b, rogue = board
    clean = draw(w, [(125.38, -22.75), (125.38, -22.65)], 150)
    was = place(sq, clean)
    drag(w, (125.38, -22.66), (125.33, -22.66))                  # west, across the rogue
    assert place(sq, clean) == was
    said = w.statusBar().currentMessage()
    assert 'not moved' in said and 'crosses nothing now' in said and f'way {rogue.id}' in said
    assert len(w.editor.marks_focus) == 1, 'where it would cross is not ringed'


def test_a_contour_already_crossing_others_moves_even_into_a_new_crossing(board):
    """It is in breach of R16 already, and the mapper is repairing it: on
    gobras the 425 m rogue crossed three or four new contours 50 m any way,
    and refusing those left it nowhere to go."""
    w, sq, a, b, rogue = board
    draw(w, [(125.39, -22.75), (125.39, -22.65)], 150)
    drag(w, (125.32, -22.70), (125.36, -22.70))                  # east: off the 100 m, across the 150 m
    (west, _), (east, _) = place(sq, rogue)
    assert west == pytest.approx(125.32, abs=2e-4) and east == pytest.approx(125.40, abs=2e-4)
    assert 'it still crosses 2 contours' in w.statusBar().currentMessage()


def test_a_move_that_leaves_a_crossing_it_already_had_is_done_and_says_so(board):
    w, sq, a, b, rogue = board
    drag(w, (125.32, -22.70), (125.30, -22.70))                  # west: clears the 125 m, still on the 100 m
    (west, _), (east, _) = place(sq, rogue)
    assert west == pytest.approx(125.26, abs=2e-4) and east == pytest.approx(125.34, abs=2e-4)
    assert 'it crosses 1 contour, was 2' in w.statusBar().currentMessage()


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
    qtbot.waitUntil(lambda: w.checks_dock.node('crossings').text(0) == 'Crossing contours (0)', timeout=2000)


def test_the_contour_selected_is_carried_though_another_runs_nearer(board):
    """Chosen in the Validation panel, then shift-dragged: in a massif a press is
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


CTRL, ALT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier


def test_shift_and_ctrl_turns_a_contour_about_its_middle(board):
    """As a drag of what is picked: shift is already the line, so ctrl
    added turns it - here a quarter, from across both neighbours to
    between them."""
    w, sq, a, b, rogue = board
    mid = w.editor.layer.node_xy(sq, rogue.refs[0])[0] / 2 + w.editor.layer.node_xy(sq, rogue.refs[-1])[0] / 2
    x0, y0 = w.editor.layer.node_xy(sq, rogue.refs[-1])
    r = (x0 - mid) / 2
    drag(w, m.scene_to_lonlat(mid + r, y0), m.scene_to_lonlat(mid, y0 + r), mods=SHIFT | CTRL)
    ends = [w.editor.layer.node_xy(sq, i) for i in rogue.refs]
    assert [x for x, _ in ends] == pytest.approx([mid, mid], abs=0.02 * r)
    assert sorted(y for _, y in ends) == pytest.approx([y0 - 2 * r, y0 + 2 * r], abs=0.02 * r)
    said = w.statusBar().currentMessage()
    assert said.startswith('turned the 425 m contour 90° clockwise') and 'crosses nothing now' in said, said
    w.editor.undo()
    assert place(sq, rogue) == [(125.28, -22.70), (125.36, -22.70)]


def test_shift_ctrl_and_alt_scales_a_contour_about_its_middle(board):
    w, sq, a, b, rogue = board
    drag(w, (125.35, -22.70), (125.3275, -22.70), mods=SHIFT | CTRL | ALT)    # a quarter as far from the middle
    (west, _), (east, _) = place(sq, rogue)
    assert west == pytest.approx(125.31, abs=2e-4) and east == pytest.approx(125.33, abs=2e-4)
    said = w.statusBar().currentMessage()
    assert said.startswith('scaled the 425 m contour ×0.25') and 'crosses nothing now' in said, said


def test_the_keys_change_a_carry_mid_drag(board):
    """Moved, then turned about where it is then, as one step."""
    w, sq, a, b, rogue = board
    vp = w.map.viewport()

    def ev(kind, lonlat, button, buttons, mods):
        pos = at(w, *lonlat)
        return QMouseEvent(kind, pos, vp.mapToGlobal(pos.toPoint()), button, buttons, mods)
    L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, (125.35, -22.70), L, L, SHIFT))
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (125.35, -22.60), NB, L, SHIFT))        # north
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (125.35, -22.60), NB, L, SHIFT | CTRL))
    assert w.editor.pointer == 'rotate'
    x, y = m.lonlat_to_scene(125.32, -22.60)                                              # its middle, there
    to = m.scene_to_lonlat(x, y + (m.lonlat_to_scene(125.35, -22.60)[0] - x))
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, to, NB, L, SHIFT | CTRL))
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, to, L, NB, SHIFT | CTRL))
    lons = [lon for lon, _ in place(sq, rogue)]
    lats = sorted(lat for _, lat in place(sq, rogue))
    assert lons == pytest.approx([125.32, 125.32], abs=2e-4)
    assert lats[0] < -22.60 < lats[1]
    assert w.statusBar().currentMessage().startswith('moved and turned the 425 m contour')
    w.editor.undo()
    assert place(sq, rogue) == [(125.28, -22.70), (125.36, -22.70)], 'not one step'


def test_a_contour_that_crosses_nothing_may_not_be_turned_into_a_crossing(board):
    w, sq, a, b, rogue = board
    clean = draw(w, [(125.38, -22.72), (125.38, -22.64)], 150)    # east of the rogue's end
    was = place(sq, clean)
    mx, my = m.lonlat_to_scene(125.38, -22.68)
    r = (my - m.lonlat_to_scene(125.38, -22.64)[1]) / 2
    # a quarter turn: lying east-west, it would cross the 125 m
    drag(w, m.scene_to_lonlat(mx, my - r), m.scene_to_lonlat(mx + r, my), mods=SHIFT | CTRL)
    assert place(sq, clean) == was
    said = w.statusBar().currentMessage()
    assert said.startswith('not turned') and f'way {b.id}' in said, said
    assert w.editor.marks_focus, 'where it would cross is not ringed'
