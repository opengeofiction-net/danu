"""The drawing tools: draw, continue, snap, refuse a crossing, select, move, insert, delete, undo."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt              # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent                     # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

from danu.core import edits                                          # noqa: E402
from danu.core.square import SquareName                              # noqa: E402
from danu.ui import mercator as m                                    # noqa: E402

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
    lowest = min([*square.ways, *square.nodes])
    click(w, 126.3, -23.85); click(w, 126.4, -23.86); click(w, 126.5, -23.85)
    key(w, Qt.Key.Key_Return)
    (way,) = ways_at(square, 123)
    assert way.tags == {'ele': '123'} and len(way.refs) == 3
    assert way.id < lowest and all(r < lowest for r in way.refs)     # fresh ids, below what the file held
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
    nodes_before = len(square.nodes)
    click(w, 126.3, -23.75)                                  # fresh
    click(w, a.lon, a.lat)                                   # snapped onto the 20 m line's start node
    (new,) = [x for x in ways_at(square, 20) if x is not twenty]
    assert new.refs[-1] == twenty.refs[0] and len(square.nodes) == nodes_before + 1   # one fresh node, one shared
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


def test_a_contour_may_not_cross_itself(w):
    square = w.working_set.squares[TEN]
    w.elevation.set(45)
    w.editor.set_tool('draw')
    click(w, 126.3, -23.56); click(w, 126.5, -23.56); click(w, 126.5, -23.58)    # east, then south
    (way,) = ways_at(square, 45)
    assert len(way.refs) == 3 and not w.editor.crossing          # its own last segment is met, not crossed
    click(w, 126.4, -23.54)                                      # back north-west, across the first segment
    assert len(way.refs) == 3 and 'crosses the 45 m contour' in w.statusBar().currentMessage()
    click(w, 126.6, -23.58)                                      # clear of itself
    assert len(way.refs) == 4
    # and a node dragged so its segments cross the way's own other segment is put back
    key(w, Qt.Key.Key_Return); w.editor.set_tool('select')
    n = square.nodes[way.refs[0]]
    before = (n.lon, n.lat)
    pos = at(w, n.lon, n.lat)
    target = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(126.55, -23.59)))
    drag(w, n.lon, n.lat, target.x() - pos.x(), target.y() - pos.y())
    assert (n.lon, n.lat) == before and w.statusBar().currentMessage().startswith('not moved')


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
    two_px = 2 * 360.0 / (256 * 2 ** w.map.zoom)             # the press lands within a pixel of the node
    assert n.lat < before[1] - 0.001 and n.lon == pytest.approx(before[0], abs=two_px)   # straight south
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
    assert 10.0 not in w.contours.paths and w.contours.pick(x, y, 1.0) is None     # nothing left within a unit
    w.editor.undo()
    assert 10.0 in w.contours.paths and w.contours.pick(x, y, 1.0)[1] is ten


# ------------------------------------------------------------- E7 review

def test_selecting_a_contour_picks_up_its_elevation(w):
    square = w.working_set.squares[TEN]
    (thirty,) = ways_at(square, 30)
    w.elevation.set(777)
    click(w, 126.5, -23.7)                                   # the 30 m line, mid-way
    assert w.editor.selection.way is thirty and w.elevation.value == 30
    w.elevation.set(777)
    n = square.nodes[thirty.refs[0]]
    click(w, n.lon, n.lat)                                   # one of its nodes
    assert w.editor.selection.node == thirty.refs[0] and w.elevation.value == 30


def test_a_held_button_draws_a_stroke_simplified_on_release_as_one_step(w):
    square = w.working_set.squares[TEN]
    w.elevation.set(66)
    w.editor.set_tool('draw')
    pos = at(w, 126.3, -23.75)
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    # a stroke: east 200 px in 2 px steps with a wobble, then a sharp turn south 100 px
    path = [QPoint(pos.x() + i, pos.y() + (1 if i % 4 == 0 else 0)) for i in range(0, 201, 2)]
    path += [QPoint(pos.x() + 200, pos.y() + j) for j in range(0, 101, 2)]
    for p in path:
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, path[-1], buttons=Qt.MouseButton.NoButton))
    (way,) = ways_at(square, 66)
    assert 3 <= len(way.refs) <= 4, len(way.refs)            # the press, the corner, the end - a wobble at most
    xs = [w.map.mapFromScene(QPointF(*m.lonlat_to_scene(square.nodes[r].lon, square.nodes[r].lat))).x() for r in way.refs]
    assert xs[0] == pytest.approx(pos.x(), abs=2) and xs[-1] == pytest.approx(pos.x() + 200, abs=2)
    assert w.editor.drawing == (square, way.id, True) and 'from a stroke' in w.statusBar().currentMessage()
    w.editor.undo()
    assert not ways_at(square, 66)                           # one step
    w.editor.redo()
    (way,) = ways_at(square, 66)                             # redo makes a fresh Way object
    # continuing with another stroke from the end
    pos2 = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(square.nodes[way.refs[-1]].lon, square.nodes[way.refs[-1]].lat)))
    n_before = len(way.refs)
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos2))
    for j in range(0, 61, 3):
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos2 + QPoint(-j, j), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos2 + QPoint(-60, 60), buttons=Qt.MouseButton.NoButton))
    assert len(way.refs) == n_before + 1, w.statusBar().currentMessage()   # a straight stroke is one node
    # a plain click is still a click
    click(w, 126.4, -23.76)                                  # between the 20 m and 30 m lines, nothing to cross
    assert len(way.refs) == n_before + 2, w.statusBar().currentMessage()


def test_a_stroke_that_crosses_a_contour_is_dropped_whole(w):
    square = w.working_set.squares[TEN]
    w.elevation.set(15)
    w.editor.set_tool('draw')
    pos = at(w, 126.3, -23.78)                               # north of the 20 m line
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    target = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(126.3, -23.83)))    # south of it
    for f in range(1, 21):
        p = pos + (target - pos) * f / 20
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, target, buttons=Qt.MouseButton.NoButton))
    assert not ways_at(square, 15) and w.statusBar().currentMessage().startswith('stroke not drawn')
    assert w.editor.pending is not None                      # the press stands; the mapper can go another way
    # continuing a way: a dropped stroke takes the press's node back too
    key(w, Qt.Key.Key_Escape)
    (twenty,) = ways_at(square, 20)
    end = square.nodes[twenty.refs[-1]]
    w.elevation.set(20)
    click(w, end.lon, end.lat)                               # continuing the 20 m line from its end
    n = len(twenty.refs)
    pos = at(w, end.lon - 0.05, end.lat + 0.03)              # the press adds a node north-west, over the lines' span
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    assert len(twenty.refs) == n + 1
    target = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(end.lon - 0.05, end.lat + 0.12)))   # across the 30 m line
    for f in range(1, 21):
        p = pos + (target - pos) * f / 20
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, target, buttons=Qt.MouseButton.NoButton))
    assert len(twenty.refs) == n and 'stroke not drawn' in w.statusBar().currentMessage()


def test_a_whole_contour_is_deleted_though_a_node_was_clicked(w):
    """A contour's nodes are closer together than the snap radius at any zoom
    that shows the whole line, so a click selects a node and Delete took one
    node of it. Shift+Delete - and the menu - take the line."""
    square = w.working_set.squares[TEN]
    (thirty,) = ways_at(square, 30)
    n = square.nodes[thirty.refs[0]]
    click(w, n.lon, n.lat)
    assert w.editor.selection.node == thirty.refs[0]             # a node, as ever
    w.edit_actions['edit.delete_way'].trigger()
    assert thirty.id not in square.ways and not ways_at(square, 30)
    assert all(r not in square.nodes for r in thirty.refs)       # and its nodes with it
    assert w.editor.selection is None and '2 nodes' in w.statusBar().currentMessage()
    assert 30.0 not in w.contours.paths
    w.editor.undo()
    assert 30.0 in w.contours.paths and len(ways_at(square, 30)) == 1
    # nothing selected, and a way already gone
    w.editor.selection = None
    w.editor.delete_way()
    assert w.statusBar().currentMessage() == 'nothing selected'


def test_shift_click_selects_the_line_rather_than_a_node(w):
    square = w.working_set.squares[TEN]
    (forty,) = ways_at(square, 40)
    n = square.nodes[forty.refs[0]]
    pos = at(w, n.lon, n.lat)
    w.map.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos), w.map.viewport().mapToGlobal(pos),
                                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                      Qt.KeyboardModifier.ShiftModifier))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos, buttons=Qt.MouseButton.NoButton))
    sel = w.editor.selection
    assert sel is not None and sel.way is forty and sel.node is None     # the line, right on a node
    assert w.elevation.value == 40                                        # and its elevation, as ever
    w.edit_actions['edit.delete'].trigger()                               # plain Delete now takes the way
    assert forty.id not in square.ways


# ------------------------------------------- redrawing a stretch of a contour

def contour(w, square, ele, points) -> int:
    """Put a contour into a square through the history, as the tools would."""
    alloc = w.editor.history.alloc(square)
    ids = [alloc.take() for _ in points]
    wid = alloc.take()
    w.editor.do(square, edits.AddWay(wid, ids, list(points), {'ele': str(ele)}))
    return wid


def ring(w, square, ele, centre, radius, n=8) -> int:
    import math
    cx, cy = centre
    pts = [(cx + radius * math.cos(2 * math.pi * k / n), cy + radius * math.sin(2 * math.pi * k / n))
           for k in range(n)]
    wid = contour(w, square, ele, pts)
    w.editor.do(square, edits.ExtendWayWithExisting(wid, True, square.ways[wid].refs[0]))
    return wid


def test_a_line_drawn_from_a_contour_back_to_it_redraws_that_stretch(w):
    square = w.working_set.squares[TEN]
    wid = contour(w, square, 70, [(126.2 + 0.1 * i, -23.45) for i in range(6)])
    way = square.ways[wid]
    ids = list(way.refs)
    ways_before = set(square.ways)
    w.elevation.set(70)
    w.editor.set_tool('draw')
    click(w, square.nodes[ids[1]].lon, square.nodes[ids[1]].lat)      # begun on the contour
    click(w, 126.35, -23.40)                                          # a detour north of it
    click(w, 126.45, -23.40)
    click(w, square.nodes[ids[4]].lon, square.nodes[ids[4]].lat)      # and back onto it
    key(w, Qt.Key.Key_Return)                                         # which ends the line
    assert set(square.ways) == ways_before                            # no second way beside it
    assert way.id == wid and way.tags == {'ele': '70'}                # the same contour
    assert [way.refs[0], way.refs[-1]] == [ids[0], ids[5]] and len(way.refs) == 6
    assert way.refs[1] == ids[1] and way.refs[4] == ids[4]            # the two ends it was drawn between
    assert square.nodes[way.refs[2]].lat == pytest.approx(-23.40, abs=0.002)
    assert ids[2] not in square.nodes and ids[3] not in square.nodes  # what it replaced is gone
    assert 'redrew 2 nodes of the 70 m contour as 2' in w.statusBar().currentMessage()
    assert w.editor.drawing is None and w.editor.selection.way is way
    w.editor.undo()                                                   # one step
    assert square.ways[wid].refs == ids and ids[2] in square.nodes


def test_a_stretch_is_redrawn_only_at_the_contours_own_value(w):
    square = w.working_set.squares[TEN]
    wid = contour(w, square, 70, [(126.2 + 0.1 * i, -23.45) for i in range(6)])
    ids = list(square.ways[wid].refs)
    w.elevation.set(75)                                               # a different level
    w.editor.set_tool('draw')
    click(w, square.nodes[ids[1]].lon, square.nodes[ids[1]].lat)
    click(w, 126.35, -23.40)
    click(w, square.nodes[ids[4]].lon, square.nodes[ids[4]].lat)      # touching another level: refused
    assert square.ways[wid].refs == ids
    assert 'meets the 70 m contour' in w.statusBar().currentMessage()


def test_a_ring_is_redrawn_round_the_way_it_was_drawn_over(w):
    """Two stretches run between any two nodes of a ring. The one under what
    was drawn is the one meant, whether or not it straddles the ring's join."""
    square = w.working_set.squares[TEN]
    wid = ring(w, square, 80, (126.5, -23.2), 0.1)
    ids = list(square.ways[wid].refs)                                 # n0..n7, n0
    w.elevation.set(80)
    w.editor.set_tool('draw')
    # over the short stretch: from n1 to n3, drawn just outside n2
    import math
    a, b = square.nodes[ids[1]], square.nodes[ids[3]]
    click(w, a.lon, a.lat)
    click(w, 126.5 + 0.13 * math.cos(math.pi / 2), -23.2 + 0.13 * math.sin(math.pi / 2))
    click(w, b.lon, b.lat); key(w, Qt.Key.Key_Return)
    way = square.ways[wid]
    assert way.closed and len(way.refs) == 9                          # n2 gone, one drawn in its place
    assert ids[2] not in square.nodes and ids[5] in square.nodes      # the far side untouched
    assert 'redrew 1 nodes' in w.statusBar().currentMessage()
    w.editor.undo()
    assert square.ways[wid].refs == ids


def test_a_ring_redrawn_over_the_stretch_that_straddles_its_join(w):
    square = w.working_set.squares[TEN]
    wid = ring(w, square, 90, (126.5, -23.2), 0.1)
    ids = list(square.ways[wid].refs)
    w.elevation.set(90)
    w.editor.set_tool('draw')
    import math
    a, b = square.nodes[ids[6]], square.nodes[ids[0]]                 # the stretch between them holds n7 only
    click(w, a.lon, a.lat)
    click(w, 126.5 + 0.13 * math.cos(-math.pi / 4), -23.2 + 0.13 * math.sin(-math.pi / 4))   # outside n7
    click(w, b.lon, b.lat); key(w, Qt.Key.Key_Return)
    way = square.ways[wid]
    assert way.closed and len(way.refs) == 9                          # eight nodes, one of them new
    assert ids[7] not in square.nodes                                 # the stretch over the join went
    assert all(ids[k] in square.nodes for k in (1, 2, 3, 4, 5))       # and the long way round stayed
    assert 'redrew 1 nodes' in w.statusBar().currentMessage()
    w.editor.undo()
    assert set(square.ways[wid].refs) == set(ids) and square.ways[wid].closed


def test_a_stroke_from_a_contour_back_to_it_redraws_the_stretch_too(w):
    """The gesture a mapper reaches for: hold the button down on the contour,
    sweep the new shape, let go on the contour again."""
    square = w.working_set.squares[TEN]
    wid = contour(w, square, 60, [(126.2 + 0.1 * i, -23.35) for i in range(6)])
    way = square.ways[wid]
    ids = list(way.refs)
    ways_before = set(square.ways)
    w.elevation.set(60)
    w.editor.set_tool('draw')
    start, end = square.nodes[ids[1]], square.nodes[ids[4]]
    pos = at(w, start.lon, start.lat)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    target = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(end.lon, end.lat)))
    for f in range(1, 21):                                   # a sweep north, released on the far node
        p = pos + (target - pos) * f / 20 + QPoint(0, -30 if 4 < f < 17 else 0)
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, target, buttons=Qt.MouseButton.NoButton))
    assert set(square.ways) == ways_before and 'redrew 2 nodes' in w.statusBar().currentMessage()
    assert [way.refs[0], way.refs[-1]] == [ids[0], ids[5]]
    assert way.refs[1] == ids[1] and way.refs[-2] == ids[4]
    assert ids[2] not in square.nodes and ids[3] not in square.nodes
    assert square.nodes[way.refs[2]].lat > -23.35             # the sweep went north of the old line
    assert w.editor.drawing is None
    w.editor.undo(); w.editor.undo()                          # the stroke, then the redraw
    assert square.ways[wid].refs == ids


def test_a_redraw_may_cross_the_stretch_it_replaces(w):
    """The point of redrawing is often to cut across a wiggle, so a crossing
    with the contour the line began on does not refuse the click - R16 is
    answered on what results, which no longer has the wiggle in it."""
    square = w.working_set.squares[TEN]
    zigzag = [(126.2, -23.30), (126.3, -23.25), (126.35, -23.35), (126.4, -23.25),
              (126.45, -23.35), (126.5, -23.25), (126.6, -23.30)]
    wid = contour(w, square, 110, zigzag)
    way = square.ways[wid]
    ids = list(way.refs)
    w.elevation.set(110)
    w.editor.set_tool('draw')
    click(w, *zigzag[1])
    click(w, 126.4, -23.30)                                  # straight through the zigzag
    assert w.editor.drawing is not None, w.statusBar().currentMessage()
    click(w, *zigzag[5]); key(w, Qt.Key.Key_Return)
    assert 'redrew 3 nodes of the 110 m contour as 1' in w.statusBar().currentMessage()
    assert len(way.refs) == 5 and all(ids[k] not in square.nodes for k in (2, 3, 4))
    w.editor.undo()
    assert square.ways[wid].refs == ids


def test_a_redraw_that_would_leave_a_crossing_is_refused_and_taken_back(w):
    """The other side of it: what results must not cross, and the only way to
    reach that check is a line crossing the part of its own contour that
    stays - crossings with the rest are refused as they always were."""
    square = w.working_set.squares[TEN]
    hook = [(126.2, -23.30), (126.3, -23.30), (126.4, -23.30), (126.5, -23.30),
            (126.5, -23.25), (126.35, -23.25)]              # east, then back west above
    wid = contour(w, square, 140, hook)
    ids = list(square.ways[wid].refs)
    w.elevation.set(140)
    w.editor.set_tool('draw')
    click(w, *hook[1])
    click(w, 126.45, -23.20)                                 # up over the returning arm, twice
    assert w.editor.drawing is not None, w.statusBar().currentMessage()
    click(w, *hook[2]); key(w, Qt.Key.Key_Return)
    assert w.statusBar().currentMessage().startswith('not redrawn'), w.statusBar().currentMessage()
    assert square.ways[wid].refs == ids and all(i in square.nodes for i in ids)
    assert w.editor.drawing is None                          # and the line is over


@pytest.mark.parametrize('what,first,last,drawn,replaced', [
    ('a bulge over a short stretch', 2, 5, [3, 4], [3, 4]),
    ('the long way round', 1, 10, [3, 5, 7], list(range(2, 10))),
    # the review's case: any two nodes side by side in the file have nothing
    # between them, and measuring from the contour to the drawing called that
    # a perfect match - so this replaced nothing and left the original alone
    ('two neighbours, drawn the long way', 0, 1, [10, 8, 6, 4, 2], list(range(2, 12))),
])
def test_the_stretch_replaced_is_the_one_the_line_was_drawn_along(w, what, first, last, drawn, replaced):
    import math
    square = w.working_set.squares[TEN]
    cx, cy, r, n = 126.5, -23.2, 0.1, 12
    on_ring = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    wid = contour(w, square, 130, on_ring)
    ids = list(square.ways[wid].refs)
    w.editor.do(square, edits.ExtendWayWithExisting(wid, True, ids[0]))
    w.elevation.set(130)
    w.editor.set_tool('draw')
    click(w, *on_ring[first])
    for k in drawn:                                          # drawn outside the ring, over one stretch
        a = 2 * math.pi * k / n
        click(w, cx + r * 1.3 * math.cos(a), cy + r * 1.3 * math.sin(a))
    click(w, *on_ring[last]); key(w, Qt.Key.Key_Return)
    gone = [k for k in range(n) if ids[k] not in square.nodes]
    assert gone == replaced, f'{what}: {w.statusBar().currentMessage()}'
    assert square.ways[wid].closed and len(square.ways[wid].refs) == n + 1 - len(replaced) + len(drawn)


def test_clicks_on_the_contour_being_redrawn_do_not_end_the_redraw(w):
    """The review's bug. Drawing a new section means drawing alongside the old
    one, whose nodes are eighty metres apart in Gobras, so click after click
    landed on one - and each ended the redraw there and then, over a sliver
    of contour, leaving the rest of the gesture to start a fresh line. Those
    clicks are ordinary points now, and the line ends when the mapper ends
    it."""
    square = w.working_set.squares[TEN]
    pts = [(126.2 + 0.08 * k, -23.30) for k in range(8)]
    wid = contour(w, square, 150, pts)
    ids = list(square.ways[wid].refs)
    w.elevation.set(150)
    w.editor.set_tool('draw')
    click(w, *pts[1])
    assert 'redrawing the 150 m contour' in w.statusBar().currentMessage()
    for k in (2, 3, 4, 5):                                   # straight over its own nodes
        click(w, *pts[k])
        assert w.editor.drawing is not None, f'ended at {k}: {w.statusBar().currentMessage()}'
        assert 'redrew' not in w.statusBar().currentMessage()
    click(w, *pts[6])
    key(w, Qt.Key.Key_Return)
    assert 'redrew 4 nodes of the 150 m contour as 4' in w.statusBar().currentMessage()
    way = square.ways[wid]
    assert len(way.refs) == 8 and [way.refs[0], way.refs[-1]] == [ids[0], ids[7]]
    assert all(ids[k] not in square.nodes for k in (2, 3, 4, 5))    # the old stretch went
    assert not [n for n in square.nodes if not any(n in y.refs for y in square.ways.values())]   # and left nothing
    w.editor.undo()
    assert square.ways[wid].refs == ids


def test_a_straight_stroke_onto_a_node_while_already_drawing(w):
    """A stroke simplifies to its two ends, and landing the release on a node
    takes one of them, which leaves nothing drawn - the branch for that read
    the elevation before it had been looked up, and the gesture crashed."""
    square = w.working_set.squares[TEN]
    pts = [(126.2 + 0.08 * k, -23.30) for k in range(8)]
    wid = contour(w, square, 160, pts)
    ids = list(square.ways[wid].refs)
    w.elevation.set(160)
    w.editor.set_tool('draw')
    click(w, *pts[1])                                        # the redraw begins
    click(w, 126.30, -23.26)                                 # and is under way
    start = at(w, 126.30, -23.26)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, start, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, start))
    target = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*pts[4])))
    for f in range(1, 11):                                   # straight, released on one of its nodes
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, start + (target - start) * f / 10,
                                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, target, buttons=Qt.MouseButton.NoButton))
    assert 'redrew 2 nodes of the 160 m contour as 1' in w.statusBar().currentMessage()
    assert all(ids[k] not in square.nodes for k in (2, 3))
    refs = square.ways[wid].refs
    assert all(a != b for a, b in zip(refs, refs[1:]))       # and no node twice over
    assert w.editor.drawing is None
    w.editor.undo()
    assert square.ways[wid].refs == ids


def test_a_line_looping_back_to_where_it_began_closes_rather_than_redrawing(w):
    """There is no stretch between a node and itself, so this is not a redraw:
    what was drawn is a contour of its own, closed, sharing the node it left
    from - which is what was drawn."""
    square = w.working_set.squares[TEN]
    pts = [(126.2 + 0.08 * k, -23.30) for k in range(8)]
    wid = contour(w, square, 170, pts)
    ids = list(square.ways[wid].refs)
    w.elevation.set(170)
    w.editor.set_tool('draw')
    click(w, *pts[3])
    click(w, 126.40, -23.24)
    click(w, 126.48, -23.24)
    click(w, *pts[3])                                        # back to where it began
    key(w, Qt.Key.Key_Return)
    assert 'closed the 170 m contour' in w.statusBar().currentMessage()
    assert square.ways[wid].refs == ids                      # the contour itself is untouched
    drawn = [y for i, y in square.ways.items() if i != wid and y.ele == 170]
    assert len(drawn) == 1 and drawn[0].closed
    assert drawn[0].refs[0] == ids[3] and drawn[0].refs[-1] == ids[3]     # hung off the node it left
