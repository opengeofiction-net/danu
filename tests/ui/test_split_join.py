"""Splitting a contour (P) and joining two by their ends (ctrl and a drag) -
G8d. In the fixture's blank square to the north, with real mouse events."""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)
CTRL = Qt.KeyboardModifier.ControlModifier
LAT = -22.70


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return sq.ways[wid]


def at(w, lon, lat) -> QPointF:
    return QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat))))


def drag(w, frm, to, mods=CTRL, steps=4):
    a, b = at(w, *frm), at(w, *to)
    vp = w.map.viewport()

    def ev(kind, pos, button, buttons):
        return QMouseEvent(kind, pos, vp.mapToGlobal(pos.toPoint()), button, buttons, mods)
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton,
                             Qt.MouseButton.LeftButton))
    for k in range(1, steps + 1):
        w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, a + (b - a) * (k / steps), Qt.MouseButton.NoButton,
                                Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton,
                               Qt.MouseButton.NoButton))


@pytest.fixture
def board(window):
    window.map.set_zoom(16)
    window.map.center_on_lonlat(125.305, LAT)
    return window, window.working_set.squares[NORTH]


def lonlat(sq, nid):
    n = sq.nodes[nid]
    return n.lon, n.lat


def test_p_splits_the_contour_at_the_node_and_ctrl_z_puts_it_back(board):
    w, sq = board
    way = draw(w, [(125.30, LAT), (125.305, LAT), (125.31, LAT)], 100)
    before = edits.snapshot(sq)
    w.editor.selection = Selection(sq, way, way.refs[1])
    w.edit_actions['edit.split'].trigger()
    assert len(list(sq.contours())) == 2
    assert 'split the 100 m contour in two' in w.statusBar().currentMessage()
    w.editor.undo()
    assert edits.snapshot(sq) == before


def test_p_with_no_node_chosen_says_how(board):
    w, sq = board
    way = draw(w, [(125.30, LAT), (125.31, LAT)], 100)
    w.editor.selection = Selection(sq, way)
    w.edit_actions['edit.split'].trigger()
    assert 'choose a node of a contour' in w.statusBar().currentMessage()


def test_ctrl_and_a_drag_of_an_end_onto_another_joins_them(board):
    w, sq = board
    a = draw(w, [(125.300, LAT), (125.304, LAT)], 100)
    b = draw(w, [(125.306, LAT), (125.310, LAT)], 100)
    before = edits.snapshot(sq)
    drag(w, (125.304, LAT), (125.306, LAT))
    assert b.id not in sq.ways and len(sq.ways[a.id].refs) == 3
    assert lonlat(sq, sq.ways[a.id].refs[1]) == pytest.approx((125.306, LAT))
    assert 'joined the 100 m contour' in w.statusBar().currentMessage()
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not undo the join'


def test_a_split_and_a_join_back_close_the_ring_again(board):
    w, sq = board
    pts = [(125.300, LAT), (125.304, LAT), (125.304, LAT + 0.004), (125.300, LAT + 0.004)]
    ring = draw(w, [*pts, pts[0]], 100)
    sq.ways[ring.id].refs[-1] = sq.ways[ring.id].refs[0]          # closed on its first node
    w.contours.set_working_set(w.working_set)
    w.editor.selection = Selection(sq, sq.ways[ring.id], sq.ways[ring.id].refs[1])
    w.editor.split()
    opened = sq.ways[ring.id]
    assert opened.refs[0] != opened.refs[-1]
    drag(w, lonlat(sq, opened.refs[-1]), lonlat(sq, opened.refs[0]))
    refs = sq.ways[ring.id].refs
    assert refs[0] == refs[-1], w.statusBar().currentMessage()
    assert 'closed the 100 m contour' in w.statusBar().currentMessage()


def test_a_join_across_levels_is_refused_and_the_end_put_back(board):
    w, sq = board
    a = draw(w, [(125.300, LAT), (125.304, LAT)], 100)
    draw(w, [(125.306, LAT), (125.310, LAT)], 125)
    was = lonlat(sq, a.refs[-1])
    drag(w, (125.304, LAT), (125.306, LAT))
    assert lonlat(sq, a.refs[-1]) == was
    assert 'not joined: the levels differ' in w.statusBar().currentMessage()


def test_without_ctrl_the_drop_is_a_move_not_a_join(board):
    """Dropped onto another end without ctrl, the node goes there and the
    ways stay two - as a drag always did."""
    w, sq = board
    a = draw(w, [(125.300, LAT), (125.304, LAT)], 100)
    b = draw(w, [(125.306, LAT), (125.310, LAT)], 100)
    drag(w, (125.304, LAT), (125.306, LAT), mods=Qt.KeyboardModifier.NoModifier)
    assert a.id in sq.ways and b.id in sq.ways and len(sq.ways[a.id].refs) == 2


def test_the_keys(window):
    assert window.edit_actions['edit.split'].shortcut().toString() == 'P'
    assert window.pinch_action.shortcut().toString() == 'C'


def test_a_join_that_would_cross_a_contour_is_refused(board):
    """A 125 m runs north-south between the two ends: the joining segment
    would cross it (R16)."""
    w, sq = board
    a = draw(w, [(125.300, LAT), (125.304, LAT)], 100)
    draw(w, [(125.306, LAT), (125.310, LAT)], 100)
    draw(w, [(125.305, LAT - 0.002), (125.305, LAT + 0.002)], 125)
    drag(w, (125.304, LAT), (125.306, LAT))
    assert len(sq.ways[a.id].refs) == 2
    assert 'not joined' in w.statusBar().currentMessage()
