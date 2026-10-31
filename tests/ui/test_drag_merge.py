"""Ctrl and a drag of a node onto another contour's line at its level: the two
made one, each run on through the other where the node was - one step with
the drag. With real mouse events,
in the fixture's blank square to the north."""

import math

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from danu.checks import loops
from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
CTRL = Qt.KeyboardModifier.ControlModifier


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def add(w, pts, ele, ring=False):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, ids, [deg(*p) for p in pts], {'ele': str(ele)}))
    if ring:
        w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, ids[0]))
    return sq.ways[wid]


def drag(w, frm, to, mods=CTRL, steps=4):
    """Press at one (x, y) in metres, move in steps, release at another."""
    vp = w.map.viewport()
    a, b = (QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*deg(*p))))) for p in (frm, to))

    def ev(kind, pos, button, buttons):
        return QMouseEvent(kind, pos, vp.mapToGlobal(pos.toPoint()), button, buttons, mods)
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    for k in range(1, steps + 1):
        w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, a + (b - a) * (k / steps), Qt.MouseButton.NoButton,
                                Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton,
                               Qt.MouseButton.NoButton))


@pytest.fixture
def board(window):
    """A 30 m line east-west, and a 30 m ring 40 m north of it."""
    line = add(window, [(-500, 0), (500, 0)], 30)
    ring = add(window, [(0, 40), (20, 60), (0, 80), (-20, 60)], 30, ring=True)
    window.map.set_zoom(16)
    window.map.center_on_lonlat(*deg(0, 40))
    return window, window.working_set.squares[NORTH], line, ring


def test_a_rings_node_dragged_onto_a_line_merges_them_in_one_step(board):
    w, sq, line, ring = board
    before = edits.snapshot(sq)
    drag(w, (0, 40), (0, 0))
    assert ring.id not in sq.ways, 'the ring is still there'
    lats = [sq.nodes[r].lat for r in sq.ways[line.id].refs]
    assert max(lats) == pytest.approx(deg(0, 80)[1], abs=5 / KY), 'the line does not run round the ring'
    said = w.statusBar().currentMessage()
    assert said.startswith(f'merged way {ring.id} into the 30 m contour'), said
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not put both back'


def test_a_lines_node_dragged_onto_a_ring_keeps_the_line(window):
    """The other way about: the open line is the one kept, whichever was
    dragged."""
    w = window
    sq = w.working_set.squares[NORTH]
    line = add(w, [(-500, -30), (-60, -30), (500, -30)], 30)
    ring = add(w, [(0, 40), (60, 100), (0, 160), (-60, 100)], 30, ring=True)
    w.map.set_zoom(16)
    w.map.center_on_lonlat(*deg(-30, 30))
    drag(w, (-60, -30), (-30, 70))                                # onto the ring's south-west side, between nodes
    assert ring.id not in sq.ways and line.id in sq.ways, w.statusBar().currentMessage()


def test_two_open_lines_are_not_merged_and_the_node_goes_back(board):
    w, sq, line, ring = board
    other = add(w, [(-30, 120), (30, 120)], 30)
    end = sq.nodes[other.refs[0]]
    was = (end.lon, end.lat)
    drag(w, (-30, 120), (-30, 0))
    assert (end.lon, end.lat) == was
    assert other.id in sq.ways and line.id in sq.ways
    assert 'both open lines' in w.statusBar().currentMessage()


def test_without_ctrl_a_node_onto_a_line_is_a_move(board):
    w, sq, line, ring = board
    drag(w, (0, 40), (0, 2), mods=Qt.KeyboardModifier.NoModifier)    # onto it, all but
    assert ring.id in sq.ways and not w.statusBar().currentMessage().startswith('merged'), \
        w.statusBar().currentMessage()


def test_a_line_at_another_level_is_not_merged(board):
    w, sq, line, ring = board
    add(w, [(-500, -100), (500, -100)], 25)
    drag(w, (0, 40), (0, -100))
    # an ordinary move, then, across the 30 m line: refused by R16
    assert ring.id in sq.ways and w.statusBar().currentMessage().startswith('not moved'), \
        w.statusBar().currentMessage()


def test_where_a_drop_would_merge_is_shown_while_the_button_is_held(board):
    """The line haloed and the pointer a link's over a line it would merge
    with; nothing over empty ground, or without ctrl; gone on letting go."""
    w, sq, line, ring = board
    vp = w.map.viewport()

    def at(p):
        return QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*deg(*p)))))

    def ev(kind, p, button, buttons, mods=CTRL):
        pos = at(p)
        return QMouseEvent(kind, pos, vp.mapToGlobal(pos.toPoint()), button, buttons, mods)
    L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, (0, 40), L, L))
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (0, 20), NB, L))
    assert w.editor.drop_target is None, 'shown over empty ground'
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (0, 0), NB, L))
    assert w.editor.drop_target == (sq, line.id, None) and w.editor.pointer == 'join'
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (0, 0), NB, L, Qt.KeyboardModifier.NoModifier))
    assert w.editor.drop_target is None, 'shown without ctrl'
    w.map.mouseMoveEvent(ev(QEvent.Type.MouseMove, (0, 0), NB, L))
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, (0, 0), L, NB))
    assert w.editor.drop_target is None and w.editor.pointer is None
    assert ring.id not in sq.ways


def test_where_a_drop_would_join_an_end_is_shown(board):
    w, sq, line, ring = board
    other = add(w, [(600, 0), (700, 0)], 30)
    vp = w.map.viewport()
    w.map.center_on_lonlat(*deg(550, 0))
    a, b = (QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*deg(*p))))) for p in ((600, 0), (500, 0)))
    L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    w.map.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, a, vp.mapToGlobal(a.toPoint()), L, L, CTRL))
    w.map.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, b, vp.mapToGlobal(b.toPoint()), NB, L, CTRL))
    assert w.editor.drop_target == (sq, line.id, line.refs[-1])
    w.map.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, b, vp.mapToGlobal(b.toPoint()), L, NB, CTRL))
    # join_ways keeps the dragged end's way
    assert other.id in sq.ways and line.id not in sq.ways, w.statusBar().currentMessage()
    assert len(sq.ways[other.id].refs) == 3 and w.statusBar().currentMessage().startswith('joined')


@pytest.fixture
def hung(window):
    """A 30 m line, and a 30 m triangle hung on it at one of its nodes - as
    the tidy leaves a loop it made a ring of (N44E026, w-49971357 on
    w-49970141)."""
    w = window
    sq = w.working_set.squares[NORTH]
    line = add(w, [(-100, 10), (-20, 35), (0, 0), (-50, -50)], 30)
    x = line.refs[2]
    alloc = w.editor.history.alloc(sq)
    tri, ids = alloc.take(), [alloc.take(), alloc.take()]
    w.editor.do(sq, edits.AddWay(tri, ids, [deg(20, 40), deg(-15, 40)], {'ele': '30'}))
    w.editor.do(sq, edits.ExtendWayWithExisting(tri, True, x))
    w.editor.do(sq, edits.ExtendWayWithExisting(tri, False, x))
    w.map.set_zoom(18)
    w.map.center_on_lonlat(*deg(-30, 20))
    return w, sq, line, sq.ways[tri], x


def test_a_ring_hung_on_the_line_merges_through_its_node_once(hung):
    """Its free nodes laid in, not the node it hangs by again: that ran the
    line through it twice, which the loops check then listed."""
    w, sq, line, tri, x = hung
    drag(w, (-15, 40), (-10, 17.5))                               # onto the segment beside the node it hangs by
    assert tri.id not in sq.ways, w.statusBar().currentMessage()
    refs = sq.ways[line.id].refs
    assert refs.count(x) == 1 and tri.refs[1] in refs and len(refs) == 5, refs


def test_a_merge_that_would_cross_the_contour_over_itself_is_laid_in_beside(hung):
    """Its free node laid into the segment dropped on - beyond the one beside
    the node it hangs by - ran the line out to it and back across its own
    segment. Not refused, the mapper tidying: laid into the segment beside,
    where it does not cross, and said."""
    w, sq, line, tri, x = hung
    drag(w, (-15, 40), (-60, 22.5))
    said = w.statusBar().currentMessage()
    assert tri.id not in sq.ways and 'laid in beside' in said, said
    refs = sq.ways[line.id].refs
    assert refs.count(x) == 1 and refs.index(tri.refs[1]) == refs.index(x) - 1, refs
    assert not loops.find_in(sq, sq.ways[line.id])
