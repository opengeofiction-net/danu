"""What a click selects when it could mean several things: a line before an
area's outline, and a click again in the same place for the next thing
there (the review of H6). With real mouse events, in the fixture's blank
square to the north."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
LAT = -22.70
L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton


def at(w, lon, lat) -> QPointF:
    return QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat))))


def press(w, pos: QPointF, release_at: QPointF | None = None):
    vp = w.map.viewport()

    def ev(kind, p, button, buttons):
        return QMouseEvent(kind, p, vp.mapToGlobal(p.toPoint()), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, pos, L, L))
    end = release_at or pos
    if release_at is not None:
        for k in range(1, 5):
            QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, pos + (end - pos) * (k / 4), NB, L))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, end, L, NB))


def way(w, pts, tags):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    nodes = [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, nodes, pts, tags))
    return sq, wid, nodes


def ring(w, pts, tags):
    sq, wid, nodes = way(w, pts, tags)
    w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, nodes[0]))
    return sq, wid


def selected(w):
    sel = w.editor.selection
    return None if sel is None else (sel.way.id if sel.way is not None else ('node', sel.node))


@pytest.fixture
def w(window):
    window.edit_actions['tool.select'].trigger()
    window.map.set_zoom(19)
    window.map.center_on_lonlat(125.31, LAT)
    return window


def test_a_stream_inside_its_river_area_is_the_stream(w):
    """The Water of Meeonoa's case: the outline 1.4 m off, nearer the click
    at z19, and the stream still the one meant."""
    north = LAT + 1.4 / 110540.0
    _sq, stream, _ = way(w, [(125.30, LAT), (125.31, LAT), (125.32, LAT)], {'waterway': 'stream'})
    _sq, area = ring(w, [(125.30, north), (125.32, north), (125.32, north + 0.001), (125.30, north + 0.001)],
                     {'natural': 'water', 'water': 'river'})
    p = at(w, 125.305, LAT) + QPointF(0, -3)        # three pixels toward the outline
    press(w, p)
    assert selected(w) == stream
    press(w, p)
    assert selected(w) == area, 'the outline is the next thing there'
    assert '2 of 2 here' in w.statusBar().currentMessage()


def test_a_contour_before_a_lakes_shore_and_the_lake_next(w):
    sq, lake = ring(w, [(125.30, LAT), (125.32, LAT), (125.32, LAT + 0.002), (125.30, LAT + 0.002)],
                    {'natural': 'water'})
    _sq, contour, _ = way(w, [(125.30, LAT - 2 / 110540.0), (125.32, LAT - 2 / 110540.0)], {'ele': '120'})  # ~6 px off
    p = at(w, 125.305, LAT) + QPointF(0, 1)         # nearer the shore than the contour
    press(w, p)
    assert selected(w) == contour
    press(w, p)
    assert selected(w) == lake


def test_two_contours_side_by_side_cycle_and_come_round(w):
    off = 2 / 110540.0
    _sq, a, _ = way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '100'})
    _sq, b, _ = way(w, [(125.30, LAT + off), (125.32, LAT + off)], {'ele': '125'})
    p = at(w, 125.305, LAT + off / 3)               # nearer a
    seen = []
    for _ in range(3):
        press(w, p)
        seen.append(selected(w))
    assert seen == [a, b, a]
    assert '1 of 2 here - click again for the next' in w.statusBar().currentMessage()


def test_a_click_elsewhere_starts_again(w):
    off = 2 / 110540.0
    _sq, a, _ = way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '100'})
    _sq, b, _ = way(w, [(125.30, LAT + off), (125.32, LAT + off)], {'ele': '125'})
    press(w, at(w, 125.305, LAT + off / 3))
    press(w, at(w, 125.315, LAT + off / 3))         # along the same two, but elsewhere
    assert selected(w) == a


def test_a_drag_between_starts_again(w):
    """A node dragged is not a click to cycle from: the next press there is
    the node again."""
    _sq, a, nodes = way(w, [(125.30, LAT), (125.305, LAT), (125.32, LAT)], {'ele': '100'})
    p = at(w, 125.305, LAT)
    press(w, p, release_at=p + QPointF(20, 0))
    assert selected(w) == a and w.editor.selection.node == nodes[1]
    q = p + QPointF(20, 0)
    press(w, q)
    assert w.editor.selection.node == nodes[1], 'the press after a drag was taken for the next thing'


def test_a_node_dragged_away_and_back_is_the_node_again(w):
    """The press after a drag, even where the last press was, is not the
    next thing there."""
    _sq, _a, nodes = way(w, [(125.30, LAT), (125.305, LAT), (125.32, LAT)], {'ele': '100'})
    p = at(w, 125.305, LAT)
    vp = w.map.viewport()

    def ev(kind, q, button, buttons):
        return QMouseEvent(kind, q, vp.mapToGlobal(q.toPoint()), button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, p, L, L))
    for dx in (5, 10, 20, 10, 5, 0):
        QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, p + QPointF(dx, 0), NB, L))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, p, L, NB))
    press(w, p)
    assert w.editor.selection.node == nodes[1]


def test_what_is_an_outline():
    from danu.core.square import Way
    from danu.ui.contours import is_outline
    assert is_outline(Way(id=1, refs=[1, 2, 3, 1], tags={'natural': 'water'}))
    assert is_outline(Way(id=2, refs=[1, 2, 3], tags={})), "a relation's ring, open and untagged"
    assert is_outline(Way(id=3, refs=[1, 2, 3, 1], tags={'waterway': 'riverbank'}))
    assert is_outline(Way(id=4, refs=[1, 2, 3], tags={'waterway': 'riverbank'})), 'a riverbank split open'
    assert not is_outline(Way(id=5, refs=[1, 2, 3], tags={'waterway': 'stream'}))


def test_a_node_comes_before_its_line(w):
    _sq, a, nodes = way(w, [(125.30, LAT), (125.305, LAT), (125.32, LAT)], {'ele': '100'})
    p = at(w, 125.305, LAT)
    press(w, p)
    assert w.editor.selection.node == nodes[1]
    press(w, p)
    assert selected(w) == a and w.editor.selection.node is None, 'the line itself, next'


def test_one_thing_there_says_nothing_of_cycling(w):
    way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '100'})
    press(w, at(w, 125.305, LAT))
    assert 'click again' not in w.statusBar().currentMessage()


def test_nothing_there_clears_and_pans(w):
    _sq, a, _ = way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '100'})
    press(w, at(w, 125.305, LAT))
    press(w, at(w, 125.305, LAT + 0.0005))
    assert w.editor.selection is None


def test_another_tool_between_starts_again(w):
    off = 2 / 110540.0
    _sq, a, _ = way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '100'})
    way(w, [(125.30, LAT + off), (125.32, LAT + off)], {'ele': '125'})
    p = at(w, 125.305, LAT + off / 3)
    press(w, p)
    w.edit_actions['tool.measure'].trigger()
    w.edit_actions['tool.select'].trigger()
    press(w, p)
    assert selected(w) == a


def test_clicks_drifting_a_few_pixels_still_page_through_what_is_there(w):
    """A recovered 0 m copy on the sea's ring: each click a pixel or three
    from the last reordered the two by distance, and paging started again at
    the first, for ever - only deleting the copy reached the ring."""
    off = 1 / 110540.0
    _sq, a, _ = way(w, [(125.30, LAT), (125.32, LAT)], {'ele': '0'})
    _sq, b, _ = way(w, [(125.30, LAT + off), (125.32, LAT + off)], {'ele': '0', 'note': 'b'})
    p = at(w, 125.305, LAT + off / 4)               # nearer a, every time
    seen = []
    for dx in (0, 4, -3):                           # each a few pixels along from the last
        press(w, p + QPointF(dx, 0))
        seen.append(selected(w))
    assert seen == [a, b, a], f'the clicks did not page through what is there: {seen}'
