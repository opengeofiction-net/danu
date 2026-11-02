"""An edit redraws the map round what changed, not the whole of it - and
what is on screen after is what a whole redraw would show.

What is on screen is read with ``QScreen.grabWindow``, which the offscreen
platform answers from the window's buffer as last painted; ``QWidget.grab``
paints afresh, and would show a part left unpainted as painted."""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from danu.core import edits
from danu.core.square import SquareName

HERE = SquareName(125, -24)


class Regions(QObject):
    """The regions the map's viewport is painted over."""

    def __init__(self, widget):
        super().__init__()
        self.seen = []
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Paint:
            self.seen.append(ev.region().boundingRect())
        return False


def settle(qtbot, ms=50):
    qtbot.wait(ms)
    QApplication.processEvents()


def on_screen(w) -> QImage:
    img = QApplication.primaryScreen().grabWindow(w.winId()).toImage()
    return img.convertToFormat(QImage.Format.Format_RGB32)


def a_contour(w):
    """A contour of the open square wholly in view and small in it, and a
    node near its middle."""
    sq = w.working_set.squares[HERE]
    vp = w.map.viewport().rect().adjusted(60, 60, -60, -60)
    for way in sorted(sq.contours(), key=lambda x: x.id):
        if len(way.refs) < 6:
            continue
        pts = [w.map.mapFromScene(*w.contours.node_xy(sq, r)) for r in way.refs if r in sq.nodes]
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        if (all(vp.contains(p) for p in pts) and (max(xs) - min(xs)) < vp.width() / 3
                and (max(ys) - min(ys)) < vp.height() / 3):
            return sq, way, way.refs[len(way.refs) // 2]
    raise AssertionError('no small contour in view')


@pytest.fixture
def shown(window, qtbot):
    w = window
    w.map.set_zoom(14)
    sq = w.working_set.squares[HERE]
    # over a small contour, with others round it to be left alone
    way = min((x for x in sq.contours() if len(x.refs) >= 6),
              key=lambda x: (max(sq.nodes[r].lon for r in x.refs) - min(sq.nodes[r].lon for r in x.refs), x.id))
    n = sq.nodes[way.refs[len(way.refs) // 2]]
    w.map.center_on_lonlat(n.lon, n.lat)
    settle(qtbot, 200)
    return w


def test_a_node_moved_redraws_round_its_contour_and_the_map_is_as_a_whole_redraw_shows(shown, qtbot):
    w = shown
    sq, way, nid = a_contour(w)
    n = sq.nodes[nid]
    regions = Regions(w.map.viewport())
    w.editor.do(sq, edits.MoveNode(nid, (n.lon, n.lat), (n.lon + 0.002, n.lat + 0.001)))
    settle(qtbot, 400)                                     # the checks' due timer included
    vp = w.map.viewport().rect()
    assert regions.seen, 'not redrawn at all'
    assert all(r.width() * r.height() < vp.width() * vp.height() / 2 for r in regions.seen), \
        f'the whole map redrawn: {regions.seen} of {vp}'
    after = on_screen(w)
    w.map.viewport().repaint()
    settle(qtbot)
    assert after == on_screen(w), 'the part redrawn left the map other than a whole redraw draws it'


def test_undo_redraws_round_what_it_puts_back(shown, qtbot):
    w = shown
    sq, way, nid = a_contour(w)
    n = sq.nodes[nid]
    w.editor.do(sq, edits.MoveNode(nid, (n.lon, n.lat), (n.lon + 0.002, n.lat)))
    settle(qtbot, 400)
    regions = Regions(w.map.viewport())
    w.editor.undo()
    settle(qtbot, 400)
    vp = w.map.viewport().rect()
    assert regions.seen and all(r.width() * r.height() < vp.width() * vp.height() / 2 for r in regions.seen)
    after = on_screen(w)
    w.map.viewport().repaint()
    settle(qtbot)
    assert after == on_screen(w)


def test_a_selection_moved_redraws_round_its_halo_and_leaves_none_behind(shown, qtbot):
    from danu.ui.tools import Selection
    w = shown
    sq, way, nid = a_contour(w)
    w.editor.selection = Selection(sq, way)
    w.editor.overlay.update()
    settle(qtbot)
    regions = Regions(w.map.viewport())
    other = next(x for x in sorted(sq.contours(), key=lambda x: x.id) if x.id != way.id and len(x.refs) > 3)
    w.editor.selection = Selection(sq, other)
    w.editor.overlay.update()
    settle(qtbot)
    assert regions.seen
    after = on_screen(w)
    w.map.viewport().repaint()
    settle(qtbot)
    assert after == on_screen(w), 'the old halo left on the map'


def test_marks_unchanged_by_an_edit_redraw_nothing(window, qtbot):
    w = window
    w.checks_dock.show()
    w._checks_shown(True)
    qtbot.waitUntil(lambda: w.crossing_index is not None, timeout=10000)
    settle(qtbot, 400)
    regions = Regions(w.map.viewport())
    w._refresh_marks()
    settle(qtbot)
    assert not regions.seen, 'the marks are as they were: nothing to redraw'


def test_the_loupe_follows_the_scene_only_while_it_is_on(window):
    loupe = window.loupe
    assert not loupe._watching, 'connected with the loupe off, the map redraws whole for every update'
    loupe.set_on(True)
    assert loupe._watching
    loupe.set_on(False)
    assert not loupe._watching


def test_a_node_of_a_contour_across_the_view_redraws_round_the_node_not_the_contour(window, qtbot):
    w = window
    w.map.set_zoom(16)
    sq = w.working_set.squares[HERE]
    way = max(sq.contours(), key=lambda x: len(x.refs))
    # a node of it in the middle of the view
    nid = way.refs[len(way.refs) // 2]
    n = sq.nodes[nid]
    w.map.center_on_lonlat(n.lon, n.lat)
    settle(qtbot, 200)
    vp = w.map.viewport().rect()
    pts = [w.map.mapFromScene(*w.contours.node_xy(sq, r)) for r in way.refs if r in sq.nodes]
    xs = [p.x() for p in pts]
    assert max(xs) - min(xs) > vp.width() / 2, 'the contour does not cross the view: no test'
    w.editor.do(sq, edits.MoveNode(nid, (n.lon, n.lat), (n.lon + 1e-4, n.lat)))      # its square marked *
    settle(qtbot, 400)
    regions = Regions(w.map.viewport())
    w.editor.do(sq, edits.MoveNode(nid, (n.lon + 1e-4, n.lat), (n.lon + 2e-4, n.lat + 1e-4)))
    settle(qtbot, 400)
    assert regions.seen and all(r.width() * r.height() < vp.width() * vp.height() / 4 for r in regions.seen), \
        regions.seen
    after = on_screen(w)
    w.map.viewport().repaint()
    settle(qtbot)
    assert after == on_screen(w)
