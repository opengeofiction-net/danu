"""Fit contours to the valley from the editor: a lasso along a river with
the range filter on its levels, then Shift+E, proposes them laid again off
the river; Enter takes it as one step, Ctrl+Z puts them back.

In the fixture's blank square to the north: a valley rising east along a
river, its 20 and 30 m stopping short of two rings each further up."""

import math

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.ogr')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from danu.checks import crossings
from danu.core.square import Node, SquareName, Way
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
LB, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
RINGS = (-7021, -7022, -7031, -7032)
_ids = iter(range(-9000, -5001))


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def way(sq, wid, tags, pts):
    refs = []
    for x, y in pts:
        nid = next(_ids)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    if pts[0] == pts[-1]:
        del sq.nodes[refs[-1]]
        refs[-1] = refs[0]
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


def ring(cx, cy, rx, ry, n=10):
    pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def tongue(tip, half=40.0, spread=0.12, far=-1500):
    north = [(x, half + spread * (tip - x)) for x in range(far, int(tip) + 1, 100)]
    return north + [(tip + half, 0.0)] + [(x, -y) for x, y in reversed(north)]


@pytest.fixture
def valley(window):
    w = window
    sq = w.working_set.squares[NORTH]
    way(sq, -7000, {'waterway': 'river', 'name': 'Test'}, [(x, 0.0) for x in range(-1500, 1501, 50)])
    for ele, tip in ((20, 0), (30, 500), (40, 1000)):
        way(sq, -7000 - ele, {'contour': 'elevation', 'ele': str(ele)}, tongue(tip))
    for wid, ele, cx in ((-7021, 20, 180), (-7022, 20, 340), (-7031, 30, 680), (-7032, 30, 840)):
        way(sq, wid, {'contour': 'elevation', 'ele': str(ele)}, ring(cx, 0, 50, 22))
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    w.edit_actions['tool.select'].trigger()
    w.editor.pick_filter = ('range', 20.0, 30.0)
    w.map.set_zoom(15)
    w.map.center_on_lonlat(*deg(300, 0))
    return w, sq


def drag(w, pts):
    vp = w.map.viewport()

    def ev(kind, p, button, buttons):
        return QMouseEvent(kind, p, vp.mapToGlobal(p.toPoint()), button, buttons, Qt.KeyboardModifier.NoModifier)
    ps = [QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*deg(x, y))))) for x, y in pts]
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, ps[0], LB, LB))
    for a, b in zip(ps, ps[1:], strict=False):
        for k in range(1, 6):
            QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, a + (b - a) * (k / 5), NB, LB))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, ps[-1], LB, NB))


def lasso(w):
    drag(w, [(-400, -300), (1000, -300), (1000, 300), (-400, 300), (-400, -295)])


def test_shift_e_after_a_lasso_proposes_the_valley_fitted_and_enter_takes_it(valley):
    w, sq = valley
    lasso(w)
    assert w.editor.picked and w.editor.lasso, 'the lasso not kept'
    w.edit_actions['edit.fit_valley'].trigger()
    p = w.editor.proposal
    assert p is not None and p.acceptable, w.statusBar().currentMessage()
    assert p.summary.startswith('20, 30 m laid again along Test') and '4 splinters gone' in p.summary, p.summary
    assert p.removed and p.added and p.outline and len(p.outline) >= 2, 'the lasso and its corridor not shown'
    assert all(i in sq.ways for i in RINGS), 'applied before Enter'
    assert w.editor.accept_proposal()
    assert not [i for i in RINGS if i in sq.ways]
    assert not crossings.find(w.working_set)
    w.editor.undo()
    assert all(i in sq.ways for i in RINGS), 'Ctrl+Z did not put them back'


def test_the_lasso_is_drawn_while_the_valley_is_worked_out(valley):
    w, sq = valley
    jobs = []
    w.editor.runner = jobs.append
    lasso(w)
    w.editor.fit_valley()
    assert w.editor.fit_cue and w.editor.proposal is None
    jobs[0].run()
    assert w.editor.fit_cue is None and w.editor.proposal is not None


def test_nothing_lassoed_says_what_to_lasso(window):
    window.editor.set_picked({})
    window.editor.fit_valley()
    assert 'lasso a valley with its river' in window.statusBar().currentMessage()
    assert window.editor.proposal is None


def test_a_lasso_with_no_river_says_so(valley):
    w, sq = valley
    del sq.ways[-7000]
    w.contours.set_working_set(w.working_set)
    lasso(w)
    w.editor.fit_valley()
    assert w.editor.proposal is None
    assert 'no river in the lasso' in w.statusBar().currentMessage(), w.statusBar().currentMessage()


def test_shift_e_is_the_key(window):
    # on the Edit menu: test_menus, which reaches the menus as PySide 6.8 allows
    assert window.edit_actions['edit.fit_valley'].shortcut().toString() == 'Shift+E'


def test_an_unnamed_river_is_a_stream(valley):
    w, sq = valley
    del sq.ways[-7000].tags['name']
    w.contours.set_working_set(w.working_set)
    lasso(w)
    w.edit_actions['edit.fit_valley'].trigger()
    p = w.editor.proposal
    assert p is not None and 'laid again along a stream:' in p.summary, w.statusBar().currentMessage()


def test_a_lasso_too_big_says_so(valley):
    w, sq = valley
    w.map.set_zoom(11)
    drag(w, [(-3000, -3000), (3000, -3000), (3000, 3000), (-3000, 3000), (-3000, -2990)])
    w.editor.fit_valley()
    assert w.editor.proposal is None
    assert 'not fitted: the lasso is' in w.statusBar().currentMessage(), w.statusBar().currentMessage()
