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
