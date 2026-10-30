"""Many nodes picked at once (#201, M2): a lasso drawn on nothing, or with
alt a rectangle, picks the nodes inside it - contours', water's and spot
heights' - shift adding to them, ctrl taking away; Delete deletes them, but a
river's points, which are upstream's."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui.selection_panel import describe_picked

NORTH = SquareName(125, -23)
LAT = -22.70
L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
NONE = Qt.KeyboardModifier.NoModifier
SHIFT, CTRL, ALT = (Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier,
                    Qt.KeyboardModifier.AltModifier)


def at(w, lon, lat) -> QPointF:
    return QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat))))


def gesture(w, pts, mods=NONE):
    """A press at the first point, the button held through the rest, let go
    at the last - each (lon, lat)."""
    vp = w.map.viewport()

    def ev(kind, p, button, buttons):
        return QMouseEvent(kind, p, vp.mapToGlobal(p.toPoint()), button, buttons, mods)
    ps = [at(w, *p) for p in pts]
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, ps[0], L, L))
    for a, b in zip(ps, ps[1:], strict=False):
        for k in range(1, 6):                            # the cursor's way between
            QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, a + (b - a) * (k / 5), NB, L))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, ps[-1], L, NB))


def lasso(w, west, south, east, north, mods=NONE):
    """A lasso round a box, drawn as a ring of points."""
    gesture(w, [(west, south), (east, south), (east, north), (west, north), (west, south + 0.0001)], mods)


def way(w, pts, tags):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    nodes = [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, nodes, pts, tags))
    return sq, wid, nodes


@pytest.fixture
def w(window):
    window.edit_actions['tool.select'].trigger()
    window.map.set_zoom(14)
    window.map.center_on_lonlat(125.31, LAT)
    return window


def picked(w) -> set:
    return w.editor.picked.get(NORTH, set())


def test_a_lasso_on_nothing_picks_the_nodes_inside_it_and_does_not_move_the_map(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, b, bn = way(w, [(125.300 + 0.004 * k, LAT + 0.004) for k in range(6)], {'ele': '125'})
    centre = w.map.center_lonlat()
    lasso(w, 125.303, LAT - 0.002, 125.313, LAT + 0.006)      # round nodes 1-3 of both
    assert picked(w) == {an[1], an[2], an[3], bn[1], bn[2], bn[3]}
    assert w.map.center_lonlat() == pytest.approx(centre), 'the left button moved the map'
    from danu.ui.mapview import MapView
    for tool in ('select', 'draw', 'select'):                # nor would it, a press no tool takes
        w.editor.set_tool(tool)
        assert w.map.dragMode() == MapView.DragMode.NoDrag
    assert w.editor.selection is None
    assert '6 nodes picked' in w.statusBar().currentMessage()


def test_alt_draws_a_rectangle(w):
    _, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    gesture(w, [(125.303, LAT - 0.002), (125.309, LAT + 0.002)], ALT)     # corner to corner
    assert picked(w) == {an[1], an[2]}


def test_shift_adds_and_ctrl_takes_away(w):
    _, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.002, 125.305, LAT + 0.002)                  # 0, 1
    assert picked(w) == {an[0], an[1]}
    lasso(w, 125.311, LAT - 0.002, 125.317, LAT + 0.002, SHIFT)          # and 3, 4
    assert picked(w) == {an[0], an[1], an[3], an[4]}
    gesture(w, [(125.303, LAT - 0.002), (125.313, LAT + 0.002)], CTRL | ALT)   # less 1 and 3
    assert picked(w) == {an[0], an[4]}
    lasso(w, 125.299, LAT - 0.002, 125.305, LAT + 0.002)                  # plain: instead
    assert picked(w) == {an[0], an[1]}


def test_water_and_spot_heights_are_picked_too(w):
    sq, s, sn = way(w, [(125.300 + 0.004 * k, LAT) for k in range(4)], {'waterway': 'stream'})
    alloc = w.editor.history.alloc(sq)
    spot = alloc.take()
    w.editor.do(sq, edits.AddNode(spot, (125.306, LAT + 0.002), {'ele': '150', 'natural': 'peak'}))
    lasso(w, 125.299, LAT - 0.002, 125.313, LAT + 0.004)
    assert picked(w) >= {sn[0], sn[1], sn[2], sn[3], spot}


def test_a_click_on_nothing_clears_and_one_with_shift_keeps(w):
    _, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.002, 125.309, LAT + 0.002)
    assert picked(w)
    gesture(w, [(125.310, LAT + 0.010), (125.310, LAT + 0.010)], SHIFT)
    assert picked(w), 'a shift click on nothing cleared what was picked'
    gesture(w, [(125.310, LAT + 0.010), (125.310, LAT + 0.010)])
    assert not w.editor.picked


def test_picking_and_selecting_are_one_or_the_other(w):
    from danu.ui.tools import Selection
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.002, 125.309, LAT + 0.002)
    w.editor.selection = Selection(sq, sq.ways[a])
    assert not w.editor.picked
    lasso(w, 125.299, LAT - 0.002, 125.309, LAT + 0.002)
    assert w.editor.selection is None and picked(w)


def test_delete_deletes_what_is_picked_in_one_step_but_a_rivers_points(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, s, sn = way(w, [(125.300 + 0.004 * k, LAT + 0.004) for k in range(6)], {'waterway': 'river'})
    lasso(w, 125.303, LAT - 0.002, 125.313, LAT + 0.006)                  # 1-3 of each
    w.edit_actions['edit.delete'].trigger()
    assert sq.ways[a].refs == [an[0], an[4], an[5]]
    assert sq.ways[s].refs == sn, "a river's points were deleted"
    said = w.statusBar().currentMessage()
    assert 'deleted 3 nodes' in said and '3 on rivers kept' in said
    assert not w.editor.picked
    w.editor.undo()                                                       # one step
    assert sq.ways[a].refs == an


def test_undo_takes_away_what_it_took_away_from_the_picked(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.002, 125.321, LAT + 0.002)
    assert len(picked(w)) == 6
    w.editor.undo()                                                       # the way itself
    assert not w.editor.picked


def test_escape_lets_go_of_what_is_picked(w):
    way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.002, 125.309, LAT + 0.002)
    w.map.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NONE))
    assert not w.editor.picked


def test_the_panel_says_how_many_and_on_what(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, b, bn = way(w, [(125.300 + 0.004 * k, LAT + 0.004) for k in range(6)], {'ele': '125'})
    _, s, sn = way(w, [(125.300 + 0.004 * k, LAT + 0.008) for k in range(6)], {'waterway': 'stream'})
    lasso(w, 125.303, LAT - 0.002, 125.313, LAT + 0.010)
    info = describe_picked(w.editor.picked, w.working_set, w.editor.layer)
    assert info.kind == '9 nodes picked'
    assert info.where == 'on 2 contours, 100-125 m; 1 water way'
    assert w.selection_panel.kind.text() == '9 nodes picked'


def test_a_lasso_drawn_over_itself_picks_what_it_went_round_once():
    import numpy as np

    from danu.ui.tools import _inside
    bow = np.array([(0, 0), (4, 4), (4, 0), (0, 4)], dtype=float)        # a bow tie
    pts = np.array([(1, 2), (3, 2), (2, 0.5), (2, 3.5), (5, 2)], dtype=float)
    assert list(_inside(pts, bow)) == [True, True, False, False, False]


# ---------------------------------------- moving what is picked (#201, M3)
PX = 1.5e-4                     # a gesture lands on whole pixels: at zoom 14, 8.6e-5 degrees each


def xy(w, sq, nid):
    return w.editor.layer.node_xy(sq, nid)


def lonlat(sq, nid):
    n = sq.nodes[nid]
    return (n.lon, n.lat)


def flat(where: dict) -> list:
    """Points by id as one list of numbers, for ``pytest.approx`` - which
    since 9.2 takes no tuples in a dict."""
    return [v for k in sorted(where) for v in where[k]]


def test_a_drag_from_a_picked_node_moves_what_is_picked_in_one_step(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.303, LAT - 0.002, 125.313, LAT + 0.002)                  # 1-3
    before = {i: lonlat(sq, i) for i in an}
    gesture(w, [lonlat(sq, an[2]), (lonlat(sq, an[2])[0], LAT + 0.002)])  # north
    for k, i in enumerate(an):
        lon, lat = lonlat(sq, i)
        assert lon == pytest.approx(before[i][0], abs=1e-6)
        assert lat == pytest.approx(before[i][1] + (0.002 if k in (1, 2, 3) else 0), abs=PX)
    assert picked(w) == {an[1], an[2], an[3]}, 'what was moved is still picked'
    assert w.statusBar().currentMessage().startswith('moved 3 nodes')
    w.editor.undo()
    assert flat({i: lonlat(sq, i) for i in an}) == pytest.approx(flat(before))


def test_the_picked_are_shown_where_they_would_go_while_the_button_is_held(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    lasso(w, 125.303, LAT - 0.002, 125.313, LAT + 0.002)
    vp = w.map.viewport()
    p0 = at(w, *lonlat(sq, an[2])); p1 = at(w, lonlat(sq, an[2])[0], LAT + 0.002)
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseButtonPress, p0, vp.mapToGlobal(p0.toPoint()), L, L, NONE))
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseMove, p1, vp.mapToGlobal(p1.toPoint()), NB, L, NONE))
    ghost = w.editor.transform_ghost
    assert ghost is not None and set(ghost) == {(NORTH, an[1]), (NORTH, an[2]), (NORTH, an[3])}
    assert lonlat(sq, an[2])[1] == pytest.approx(LAT), 'moved before the button was let go'
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseButtonRelease, p1, vp.mapToGlobal(p1.toPoint()), L, NB, NONE))
    assert w.editor.transform_ghost is None


def test_two_contours_moved_together_do_not_cross_where_the_other_was(w):
    """The 100 m moved north over where the 125 m was: but the 125 m moves too."""
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, b, bn = way(w, [(125.300 + 0.004 * k, LAT + 0.002) for k in range(6)], {'ele': '125'})
    lasso(w, 125.299, LAT - 0.001, 125.321, LAT + 0.003)                  # both, whole
    gesture(w, [lonlat(sq, an[2]), (lonlat(sq, an[2])[0], LAT + 0.003)])
    assert lonlat(sq, an[2])[1] == pytest.approx(LAT + 0.003, abs=PX), w.statusBar().currentMessage()
    assert 'cross nothing now' in w.statusBar().currentMessage()


def test_contours_that_crossed_nothing_may_not_be_put_down_crossing(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, c, cn = way(w, [(125.310, LAT + 0.001), (125.310, LAT + 0.005)], {'ele': '150'})   # a wall north
    lasso(w, 125.303, LAT - 0.002, 125.309, LAT + 0.0008)                 # 1, 2: west of the wall
    before = {i: lonlat(sq, i) for i in an}
    gesture(w, [lonlat(sq, an[2]), (lonlat(sq, an[2])[0] + 0.006, LAT + 0.003)])   # over it
    assert flat({i: lonlat(sq, i) for i in an}) == pytest.approx(flat(before)), 'moved into a crossing'
    assert w.statusBar().currentMessage().startswith('not moved'), w.statusBar().currentMessage()
    assert w.editor.marks_focus, 'the crossing ringed'


def test_contours_already_crossing_move_freely_and_it_is_said(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    way(w, [(125.310, LAT - 0.003), (125.310, LAT + 0.003)], {'ele': '150'})      # through it already
    lasso(w, 125.299, LAT - 0.001, 125.321, LAT + 0.001)
    gesture(w, [lonlat(sq, an[2]), (lonlat(sq, an[2])[0], LAT + 0.001)])
    assert lonlat(sq, an[2])[1] == pytest.approx(LAT + 0.001, abs=PX)
    assert 'they still cross 1 contour' in w.statusBar().currentMessage()


def test_shift_ctrl_turns_what_is_picked_about_its_middle(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})   # 0-4
    lasso(w, 125.299, LAT - 0.001, 125.317, LAT + 0.001)
    mid = xy(w, sq, an[2])
    end = xy(w, sq, an[4])
    r = end[0] - mid[0]
    # from the east end round a quarter, to straight below the middle
    target = m.scene_to_lonlat(mid[0], mid[1] + r)
    gesture(w, [lonlat(sq, an[4]), target], SHIFT | CTRL)
    nx, ny = xy(w, sq, an[4])
    assert nx == pytest.approx(mid[0], abs=r * 0.02) and ny == pytest.approx(mid[1] + r, abs=r * 0.02)
    assert xy(w, sq, an[2]) == pytest.approx(mid, abs=r * 0.01), 'the middle moved'
    assert 'turned 5 nodes 90° clockwise' in w.statusBar().currentMessage(), w.statusBar().currentMessage()


def test_ctrl_alt_scales_what_is_picked_about_its_middle(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.317, LAT + 0.001)
    mid = xy(w, sq, an[2])
    end = xy(w, sq, an[4])
    r = end[0] - mid[0]
    gesture(w, [lonlat(sq, an[4]), m.scene_to_lonlat(mid[0] + 2 * r, mid[1])], CTRL | ALT)
    assert xy(w, sq, an[4])[0] - mid[0] == pytest.approx(2 * r, rel=0.02)
    assert xy(w, sq, an[3])[0] - mid[0] == pytest.approx(r, rel=0.02)     # was r/2
    assert '×2.00' in w.statusBar().currentMessage()


def test_other_keys_on_a_picked_node_are_not_a_transform(w):
    """Shift on a contour is the whole contour, as ever."""
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.317, LAT + 0.001)
    gesture(w, [lonlat(sq, an[2]), lonlat(sq, an[2])], SHIFT)
    assert w.editor.selection is not None and w.editor.selection.way.id == a
    assert not w.editor.picked


def test_rivers_and_spot_heights_go_with_the_rest(w):
    sq, s, sn = way(w, [(125.300 + 0.004 * k, LAT) for k in range(4)], {'waterway': 'stream'})
    alloc = w.editor.history.alloc(sq)
    spot = alloc.take()
    w.editor.do(sq, edits.AddNode(spot, (125.306, LAT + 0.002), {'ele': '150', 'natural': 'peak'}))
    lasso(w, 125.299, LAT - 0.001, 125.313, LAT + 0.003)
    gesture(w, [lonlat(sq, sn[1]), (lonlat(sq, sn[1])[0] + 0.001, LAT)])
    assert lonlat(sq, sn[1])[0] == pytest.approx(125.305, abs=PX)
    assert lonlat(sq, spot)[0] == pytest.approx(125.307, abs=PX)


def test_two_moving_contours_put_down_crossing_each_other_are_refused(w):
    """Both moving, so the layer's check skips both: only measuring them
    against each other, where they will be, sees the 100 m's middle pushed
    up through the 125 m's unpicked east."""
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(6)], {'ele': '100'})
    _, b, bn = way(w, [(125.300 + 0.004 * k, LAT + 0.002) for k in range(6)], {'ele': '125'})
    lasso(w, 125.307, LAT - 0.001, 125.313, LAT + 0.001)                  # the 100 m's 2, 3
    lasso(w, 125.299, LAT + 0.001, 125.305, LAT + 0.003, SHIFT)          # and the 125 m's 0, 1
    assert picked(w) == {an[2], an[3], bn[0], bn[1]}
    before = {i: lonlat(sq, i) for i in an + bn}
    gesture(w, [lonlat(sq, an[2]), (lonlat(sq, an[2])[0], LAT + 0.004)])
    assert flat({i: lonlat(sq, i) for i in an + bn}) == pytest.approx(flat(before)), w.statusBar().currentMessage()
    assert w.statusBar().currentMessage().startswith('not moved')


def ring_of(w, cx, cy, r, ele, n=12):
    import math
    sq, wid, ids = way(w, [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
                           for k in range(n)], {'ele': str(ele)})
    w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, ids[0]))
    return sq, wid, ids


@pytest.mark.parametrize('north', [True, False])
def test_a_moving_contour_may_go_where_another_moving_one_was(w, north):
    """Two rings one above the other, moved together a ring's height: one goes
    through where the other was, which has gone too - measured against every
    moving way, not one of them."""
    sq, a, an = ring_of(w, 125.310, LAT, 0.001, 100)
    _, b, bn = ring_of(w, 125.310, LAT + 0.003, 0.001, 125)
    lasso(w, 125.308, LAT - 0.0015, 125.312, LAT + 0.0045)
    assert picked(w) == set(an) | set(bn)
    d = 0.0025 if north else -0.0025
    start = lonlat(sq, an[3])
    gesture(w, [start, (start[0], start[1] + d)])
    assert lonlat(sq, an[3])[1] == pytest.approx(start[1] + d, abs=PX), w.statusBar().currentMessage()
    assert 'cross nothing now' in w.statusBar().currentMessage()


# ------------------------------- the keys change a drag as it goes, as JOSM's
def send(w, kind, lonlat_or_pos, buttons, mods=NONE, button=NB):
    vp = w.map.viewport()
    p = lonlat_or_pos if isinstance(lonlat_or_pos, QPointF) else at(w, *lonlat_or_pos)
    QApplication.sendEvent(vp, QMouseEvent(kind, p, vp.mapToGlobal(p.toPoint()), button, buttons, mods))


def keyev(w, kind, key, mods):
    ev = QKeyEvent(kind, key, mods)
    (w.map.keyPressEvent if kind == QEvent.Type.KeyPress else w.map.keyReleaseEvent)(ev)


def test_a_move_turned_into_a_turn_mid_drag_is_one_step_from_where_it_began(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.317, LAT + 0.001)
    before = {i: lonlat(sq, i) for i in an}
    end = lonlat(sq, an[4])
    send(w, QEvent.Type.MouseButtonPress, end, L, button=L)
    north = (end[0], end[1] + 0.003)
    send(w, QEvent.Type.MouseMove, north, L)                     # a move, north
    assert w.editor.pointer == 'move'
    moved = {k: v for k, v in w.editor.transform_ghost.items()}
    # shift and ctrl, still dragging: from here it turns, about where it now is
    send(w, QEvent.Type.MouseMove, north, L, SHIFT | CTRL)
    assert w.editor.pointer == 'rotate'
    mid = moved[(NORTH, an[2])]
    r = moved[(NORTH, an[4])][0] - mid[0]
    send(w, QEvent.Type.MouseMove, QPointF(w.map.mapFromScene(QPointF(mid[0], mid[1] + r))), L, SHIFT | CTRL)
    send(w, QEvent.Type.MouseButtonRelease, QPointF(w.map.mapFromScene(QPointF(mid[0], mid[1] + r))), NB,
         SHIFT | CTRL, button=L)
    nx, ny = xy(w, sq, an[4])
    assert nx == pytest.approx(mid[0], abs=r * 0.03) and ny == pytest.approx(mid[1] + r, abs=r * 0.03)
    assert w.statusBar().currentMessage().startswith('moved and turned 5 nodes'), w.statusBar().currentMessage()
    w.editor.undo()                                              # the whole drag, one step
    assert flat({i: lonlat(sq, i) for i in an}) == pytest.approx(flat(before))


def test_a_key_pressed_mid_drag_changes_it_without_the_mouse_moving(w):
    from danu.ui.tools import _cursor
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.317, LAT + 0.001)
    end = lonlat(sq, an[4])
    send(w, QEvent.Type.MouseMove, end, NB)
    send(w, QEvent.Type.MouseButtonPress, end, L, button=L)
    send(w, QEvent.Type.MouseMove, (end[0], end[1] + 0.002), L)
    keyev(w, QEvent.Type.KeyPress, Qt.Key.Key_Control, NONE)
    keyev(w, QEvent.Type.KeyPress, Qt.Key.Key_Alt, CTRL)
    assert w.editor.pointer == 'scale'
    assert w.map.viewport().cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    keyev(w, QEvent.Type.KeyRelease, Qt.Key.Key_Alt, CTRL | ALT)            # ctrl alone says nothing
    assert w.editor.pointer == 'scale', 'ctrl alone is no transform: it should stay as it was'
    keyev(w, QEvent.Type.KeyRelease, Qt.Key.Key_Control, CTRL)              # nothing held: a move
    assert w.editor.pointer == 'move'
    assert w.map.viewport().cursor().shape() == Qt.CursorShape.SizeAllCursor
    keyev(w, QEvent.Type.KeyPress, Qt.Key.Key_Shift, NONE)
    keyev(w, QEvent.Type.KeyPress, Qt.Key.Key_Control, SHIFT)
    assert w.editor.pointer == 'rotate'
    assert w.map.viewport().cursor().shape() == _cursor('rotate').shape() == Qt.CursorShape.BitmapCursor
    send(w, QEvent.Type.MouseButtonRelease, (end[0], end[1] + 0.002), NB, SHIFT | CTRL, button=L)


def test_over_a_picked_node_the_pointer_says_what_a_drag_would_do(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.309, LAT + 0.001)                  # 0-2
    on = lonlat(sq, an[1])
    send(w, QEvent.Type.MouseMove, on, NB)
    assert w.editor.pointer == 'move'
    send(w, QEvent.Type.MouseMove, on, NB, CTRL | ALT)
    assert w.editor.pointer == 'scale'
    keyev(w, QEvent.Type.KeyRelease, Qt.Key.Key_Alt, CTRL | ALT)
    assert w.editor.pointer is None, 'ctrl alone over it: no transform, the plain pointer'
    send(w, QEvent.Type.MouseMove, lonlat(sq, an[4]), NB)                 # not picked
    assert w.editor.pointer is None
    assert w.map.viewport().cursor().shape() == Qt.CursorShape.ArrowCursor


def test_other_tools_keep_their_own_pointer(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(5)], {'ele': '100'})
    lasso(w, 125.299, LAT - 0.001, 125.309, LAT + 0.001)
    send(w, QEvent.Type.MouseMove, lonlat(sq, an[1]), NB)
    w.editor.set_tool('draw')
    assert w.editor.pointer is None
    keyev(w, QEvent.Type.KeyPress, Qt.Key.Key_Alt, CTRL)          # ctrl and alt: a scale, in select
    assert w.editor.pointer is None
    assert w.map.viewport().cursor().shape() == Qt.CursorShape.CrossCursor


# ------------------------------------------- picking by level (#201, the filter)
def three_levels(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(4)], {'ele': '100'})
    _, b, bn = way(w, [(125.300 + 0.004 * k, LAT + 0.002) for k in range(4)], {'ele': '125'})
    _, c, cn = way(w, [(125.300 + 0.004 * k, LAT + 0.004) for k in range(4)], {'ele': '150'})
    _, r, rn = way(w, [(125.302 + 0.004 * k, LAT + 0.001) for k in range(3)], {'waterway': 'stream'})
    alloc = w.editor.history.alloc(sq)
    spot = alloc.take()
    w.editor.do(sq, edits.AddNode(spot, (125.306, LAT + 0.003), {'ele': '125', 'natural': 'peak'}))
    return sq, an, bn, cn, rn, spot


def everything(w, mods=NONE):
    lasso(w, 125.299, LAT - 0.001, 125.313, LAT + 0.005, mods)


def test_at_the_active_elevation_only_that_contours_nodes_and_its_spot_heights(w):
    sq, an, bn, cn, rn, spot = three_levels(w)
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    w.elevation.set(125)
    everything(w)
    assert picked(w) == set(bn) | {spot}, 'water, other levels, or the spot height wrongly'
    assert w.statusBar().currentMessage() == '5 nodes picked, at 125 m'


def test_the_active_elevation_followed_as_it_changes_and_shift_adds_the_next(w):
    sq, an, bn, cn, rn, spot = three_levels(w)
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    w.elevation.set(100)
    everything(w)
    w.elevation.set(150)
    everything(w, SHIFT)
    assert picked(w) == set(an) | set(cn)


def test_a_range_picks_the_levels_in_it_both_ends_included(w):
    sq, an, bn, cn, rn, spot = three_levels(w)
    p = w.selection_panel
    p.pick.setCurrentIndex(p.pick.findData('range'))
    p.pick_from.setValue(125); p.pick_to.setValue(100)                    # either way round
    everything(w)
    assert picked(w) == set(an) | set(bn) | {spot}
    assert w.statusBar().currentMessage().endswith(', 100-125 m')


def test_a_node_shared_with_a_contour_of_another_level_counts_if_either_passes(w):
    sq, a, an = way(w, [(125.300 + 0.004 * k, LAT) for k in range(4)], {'ele': '100'})
    _, b, bn = way(w, [(125.304, LAT + 0.003), (125.306, LAT + 0.002)], {'ele': '150'})
    w.editor.do(sq, edits.ExtendWayWithExisting(b, True, an[1]))         # the 150 m ends on a 100 m node
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    w.elevation.set(150)
    everything(w)
    assert picked(w) == set(bn) | {an[1]}


def test_a_coastline_is_level_0(w):
    sq, c, cn = way(w, [(125.300 + 0.004 * k, LAT) for k in range(4)], {'natural': 'coastline'})
    way(w, [(125.300 + 0.004 * k, LAT + 0.002) for k in range(4)], {'ele': '100'})
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    w.elevation.set(0)
    everything(w)
    assert picked(w) == set(cn)


def test_the_filter_is_remembered_and_the_range_shown_only_for_a_range(w):
    from danu.ui.settings import Settings
    p = w.selection_panel
    assert p.pick.currentData() == 'all' and not p.pick_range.isVisibleTo(p)
    p.pick.setCurrentIndex(p.pick.findData('range'))
    p.pick_from.setValue(200); p.pick_to.setValue(350)
    assert p.pick_range.isVisibleTo(p)
    assert w.editor.pick_filter == ('range', 200.0, 350.0)
    assert Settings(w.settings.q.fileName()).pick_filter == ('range', 200.0, 350.0)


def test_changing_the_filter_leaves_what_is_picked_alone(w):
    sq, an, bn, cn, rn, spot = three_levels(w)
    everything(w)
    before = set(picked(w))
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    assert picked(w) == before



def test_a_lake_flattened_to_a_level_counts_at_it(w):
    """Its shore is a contour at that level in all but name (G7a)."""
    import math
    sq, lake, ln = way(w, [(125.306 + 0.002 * math.cos(2 * math.pi * k / 8), LAT + 0.002 + 0.0015 * math.sin(2 * math.pi * k / 8))
                           for k in range(8)], {'natural': 'water', 'ele': '125'})
    w.editor.do(sq, edits.ExtendWayWithExisting(lake, True, ln[0]))
    _, a, an = way(w, [(125.300 + 0.004 * k, LAT + 0.004) for k in range(4)], {'ele': '150'})
    w.selection_panel.pick.setCurrentIndex(w.selection_panel.pick.findData('active'))
    w.elevation.set(125)
    everything(w)
    assert picked(w) == set(ln)
