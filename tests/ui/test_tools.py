"""The drawing tools: draw, continue, snap, refuse a crossing, select, move, insert, delete, undo."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt              # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent                     # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

from danu.core.square import SquareName                              # noqa: E402
from danu.ui import mercator as m                                    # noqa: E402

from .conftest import cursor_to                                      # noqa: E402

TEN = SquareName(126, -24)          # the square with five east-west lines, 10..50 m, at lat -23.9..-23.5


def mouse(w, kind, pos, button=Qt.MouseButton.LeftButton, buttons=None):
    buttons = button if buttons is None else buttons
    return QMouseEvent(kind, QPointF(pos), w.map.viewport().mapToGlobal(pos), button, buttons,
                       Qt.KeyboardModifier.NoModifier)


def at(w, lon, lat) -> QPoint:
    """Put the point at the viewport's centre and return that position."""
    w.map.center_on_lonlat(lon, lat)
    return w.map.viewport().rect().center()


def click(w, lon, lat, button=Qt.MouseButton.LeftButton):
    pos = at(w, lon, lat)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos, button))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos, button, Qt.MouseButton.NoButton))


def double_click(w, lon, lat):
    pos = at(w, lon, lat)
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos, buttons=Qt.MouseButton.NoButton))
    w.map.mouseDoubleClickEvent(mouse(w, QEvent.Type.MouseButtonDblClick, pos))


def drag(w, lon, lat, dx_px, dy_px):
    pos = at(w, lon, lat)
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    for f in (0.5, 1.0):
        p = pos + QPoint(round(dx_px * f), round(dy_px * f))
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    p = pos + QPoint(dx_px, dy_px)
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, p, buttons=Qt.MouseButton.NoButton))


def key(w, k):
    w.map.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def ways_at(square, ele):
    return [way for way in square.contours() if way.ele == ele]


@pytest.fixture
def w(window):
    window.map.set_zoom(13)
    return window


# ----------------------------------------------------------------- draw

def test_a_contour_is_drawn_click_by_click_at_the_active_elevation_and_undone_node_by_node(w):
    square = w.working_set.squares[TEN]
    ed = w.editor
    ed.set_tool('draw')
    w.elevation.set(123)
    click(w, 126.3, -23.85); click(w, 126.4, -23.86); click(w, 126.5, -23.85)
    key(w, Qt.Key.Key_Return)
    (way,) = ways_at(square, 123)
    assert way.tags == {'ele': '123'} and len(way.refs) == 3 and way.id < min(TEN and square.ways) + 1
    lons = [square.nodes[r].lon for r in way.refs]
    assert lons == pytest.approx([126.3, 126.4, 126.5], abs=0.002)
    assert 123.0 in w.contours.paths and w.windowTitle().endswith('*') and ed.dirty()
    assert w.edit_actions['edit.undo'].text().startswith('&Undo ')
    ed.undo()
    assert len(way.refs) == 2
    ed.undo()
    assert not ways_at(square, 123) and all(r not in square.nodes for r in way.refs)
    assert 123.0 not in w.contours.paths and not ed.dirty() and not w.windowTitle().endswith('*')
    ed.redo(); ed.redo()
    assert len(ways_at(square, 123)[0].refs) == 3


def test_a_click_on_the_end_of_a_contour_at_this_elevation_continues_it(w):
    square = w.working_set.squares[TEN]
    (ten,) = ways_at(square, 10)
    end = square.nodes[ten.refs[-1]]
    w.elevation.set(10)
    w.editor.set_tool('draw')
    click(w, end.lon, end.lat)
    assert w.editor.drawing == (square, ten.id, True) and 'continuing' in w.statusBar().currentMessage()
    click(w, end.lon + 0.05, end.lat - 0.02)
    click(w, end.lon + 0.1, end.lat - 0.02)
    assert len(ten.refs) == 4 and square.nodes[ten.refs[-1]].lon == pytest.approx(end.lon + 0.1, abs=0.002)
    # from the start end, the other way
    key(w, Qt.Key.Key_Return)
    start = square.nodes[ten.refs[0]]
    click(w, start.lon, start.lat)
    assert w.editor.drawing == (square, ten.id, False)
    click(w, start.lon - 0.05, start.lat)
    assert len(ten.refs) == 5 and square.nodes[ten.refs[0]].lon == pytest.approx(start.lon - 0.05, abs=0.002)
    assert len(ways_at(square, 10)) == 1


def test_snapping_shares_the_node_and_backspace_takes_the_last_one_back(w):
    square = w.working_set.squares[TEN]
    (twenty,) = ways_at(square, 20)
    a = square.nodes[twenty.refs[0]]
    w.elevation.set(20)
    w.editor.set_tool('draw')
    click(w, 126.3, -23.75)                                  # fresh
    click(w, a.lon, a.lat)                                   # snapped onto the 20 m line's start node
    (new,) = [x for x in ways_at(square, 20) if x is not twenty]
    assert new.refs[-1] == twenty.refs[0] and len(square.nodes) == len(square.nodes)
    click(w, 126.3, -23.72)
    assert len(new.refs) == 3
    key(w, Qt.Key.Key_Backspace)
    assert len(new.refs) == 2 and w.editor.drawing == (square, new.id, True)
    key(w, Qt.Key.Key_Backspace)
    assert new.id not in square.ways and w.editor.drawing is None


def test_a_crossing_is_warned_live_and_refused_on_the_click(w):
    square = w.working_set.squares[TEN]
    (twenty,) = ways_at(square, 20)
    w.elevation.set(15)
    w.editor.set_tool('draw')
    click(w, 126.3, -23.78)                                  # south of the 20 m line at -23.8? no: north of -23.8
    pos = at(w, 126.3, -23.83)                               # across it
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    assert w.editor.crossing and w.editor.crossing[0][1] is twenty and w.editor.crossing[0][2] is True   # crossed outright
    assert 'crosses the 20 m contour' in w.statusBar().currentMessage()
    click(w, 126.3, -23.83)
    assert w.statusBar().currentMessage().startswith('not drawn') and not ways_at(square, 15)
    click(w, 126.35, -23.78)                                 # beside it: fine
    (new,) = ways_at(square, 15)
    # touching a contour at another elevation is refused too: snap onto a 20 m node
    n = square.nodes[twenty.refs[1]]
    click(w, n.lon, n.lat)
    assert len(new.refs) == 2 and 'meets the 20 m contour' in w.statusBar().currentMessage()
    # and at the same elevation a crossing is a crossing
    key(w, Qt.Key.Key_Return)
    w.elevation.set(20)
    click(w, 126.5, -23.78); click(w, 126.5, -23.83)
    assert 'crosses the 20 m contour' in w.statusBar().currentMessage() and len(ways_at(square, 20)) == 1


def test_a_first_click_outside_the_set_or_in_a_blank_square(w):
    ws = w.working_set
    w.editor.set_tool('draw')
    w.elevation.set(30)
    click(w, 130.5, -23.5)
    assert 'outside' in w.statusBar().currentMessage() and w.editor.pending is None
    blank = ws.squares[SquareName(125, -23)]
    assert not blank.present
    click(w, 125.5, -22.5); click(w, 125.6, -22.5)
    assert len(ways_at(blank, 30)) == 1                      # drawn into the blank, in memory


def test_escape_ends_the_line_then_returns_to_select_and_the_keys_switch_tools(w):
    w.editor.set_tool('draw')
    click(w, 126.3, -23.75)
    assert w.editor.pending is not None
    key(w, Qt.Key.Key_Escape)
    assert w.editor.pending is None and w.editor.tool == 'draw'
    key(w, Qt.Key.Key_Escape)
    assert w.editor.tool == 'select' and w.edit_actions['tool.select'].isChecked()
    w.map.setFocus()
    QTest.keyClick(w, 'a')
    assert w.editor.tool == 'draw' and w.edit_actions['tool.draw'].isChecked()
    QTest.keyClick(w, 'q')
    assert w.editor.tool == 'select'


# --------------------------------------------------------------- select

def test_select_a_way_or_a_node_and_delete_them(w):
    square = w.working_set.squares[TEN]
    (thirty,) = ways_at(square, 30)
    click(w, 126.5, -23.7)                                   # mid-line
    sel = w.editor.selection
    assert sel and sel.way is thirty and sel.node is None
    w.edit_actions['edit.delete'].trigger()
    assert thirty.id not in square.ways and not ways_at(square, 30) and w.editor.selection is None
    assert all(r not in square.nodes for r in thirty.refs)
    w.editor.undo()
    assert thirty.id in square.ways
    # a node
    (forty,) = ways_at(square, 40)
    n = square.nodes[forty.refs[0]]
    click(w, n.lon, n.lat)
    sel = w.editor.selection
    assert sel and sel.way is forty and sel.node == forty.refs[0]
    w.editor.delete_selected()
    assert forty.id not in square.ways                       # two nodes less one is not a line
    w.editor.undo()
    assert forty.id in square.ways and len(forty.refs) == 2
    click(w, 126.5, -23.2)                                   # nothing there: cleared, and the view pans
    assert w.editor.selection is None


def test_a_node_is_dragged_and_the_move_is_one_undo_step(w):
    square = w.working_set.squares[TEN]
    (fifty,) = ways_at(square, 50)
    nid = fifty.refs[1]
    n = square.nodes[nid]
    before = (n.lon, n.lat)
    drag(w, n.lon, n.lat, 0, 40)                             # 40 px south
    assert n.lat < before[1] - 0.001 and n.lon == pytest.approx(before[0], abs=1e-4)   # straight south, to a pixel
    assert w.editor.history.describe_undo() and w.editor.dirty()
    w.editor.undo()
    assert (n.lon, n.lat) == before
    w.editor.redo()
    assert n.lat < before[1] - 0.001


def test_a_drag_that_would_cross_another_contour_is_put_back(w):
    square = w.working_set.squares[TEN]
    (forty,) = ways_at(square, 40)
    (thirty,) = ways_at(square, 30)
    nid = forty.refs[1]
    n = square.nodes[nid]
    before = (n.lon, n.lat)
    y_thirty = square.nodes[thirty.refs[0]].lat
    px_per_deg = abs(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(n.lon, n.lat))).y()
                     - w.map.mapFromScene(QPointF(*m.lonlat_to_scene(n.lon, y_thirty))).y()) / abs(n.lat - y_thirty)
    drag(w, n.lon, n.lat, 0, round(px_per_deg * 0.15))       # past the 30 m line, 0.1° south
    assert (n.lon, n.lat) == before and w.statusBar().currentMessage().startswith('not moved')
    assert not w.editor.history.can_undo


def test_a_double_click_on_a_segment_inserts_a_node_there(w):
    square = w.working_set.squares[TEN]
    (ten,) = ways_at(square, 10)
    assert len(ten.refs) == 2
    double_click(w, 126.5, -23.9)
    assert len(ten.refs) == 3
    mid = square.nodes[ten.refs[1]]
    assert mid.lon == pytest.approx(126.5, abs=0.002) and mid.lat == pytest.approx(-23.9, abs=1e-6)
    assert w.editor.selection.node == ten.refs[1]
    w.editor.undo()
    assert len(ten.refs) == 2


def test_the_layer_follows_the_edits(w):
    square = w.working_set.squares[TEN]
    (ten,) = ways_at(square, 10)
    x, y = m.lonlat_to_scene(126.5, -23.9)
    assert w.contours.pick(x, y, 1.0)[1] is ten
    click(w, 126.5, -23.9)
    w.editor.delete_selected()
    assert w.contours.pick(x, y, 1e5) is None or w.contours.pick(x, y, 1e5)[1] is not ten
    assert 10.0 not in w.contours.paths
    w.editor.undo()
    assert 10.0 in w.contours.paths and w.contours.pick(x, y, 1.0)[1] is ten
