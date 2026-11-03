"""Absorb splinters from the editor: a lasso, then Shift+E, proposes every
chain of small rings it picks absorbed into the line of its level; Enter
takes it as one step, Ctrl+Z puts them back.

In the fixture's blank square to the north: a valley running east, its 30 m
line turning at a tip, and three 30 m rings up the valley from it."""

import math

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.ogr')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from danu.core.square import Node, SquareName, Way
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
LB, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
RINGS = (-7011, -7012, -7013)
_ids = iter(range(-9000, -5001))


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def way(sq, wid, ele, pts):
    refs = []
    for x, y in pts:
        nid = next(_ids)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    if pts[0] == pts[-1]:
        del sq.nodes[refs[-1]]
        refs[-1] = refs[0]
    sq.ways[wid] = Way(id=wid, refs=refs, tags={'contour': 'elevation', 'ele': f'{ele:g}'})
    return sq.ways[wid]


def ring(cx, cy, rx, ry, n=8):
    pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def tip(x, half, far=-1500, spread=0.1):
    north = [(px, half + spread * (x - px)) for px in range(far, int(x) + 1, 100)]
    return north + [(x + half, 0.0)] + [(px, -y) for px, y in reversed(north)]


@pytest.fixture
def valley(window):
    w = window
    sq = w.working_set.squares[NORTH]
    way(sq, -7020, 20, tip(-400, 30))
    way(sq, -7030, 30, tip(0, 20))
    way(sq, -7040, 40, tip(800, 90))
    for wid, cx in zip(RINGS, (60, 180, 300), strict=True):
        way(sq, wid, 30, ring(cx, 0, 40, 25))
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    w.edit_actions['tool.select'].trigger()
    w.map.set_zoom(16)
    w.map.center_on_lonlat(*deg(150, 0))
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
    drag(w, [(-100, -80), (400, -80), (400, 80), (-100, 80), (-100, -75)])


def test_shift_e_after_a_lasso_proposes_the_splinters_absorbed_and_enter_takes_it(valley):
    w, sq = valley
    lasso(w)
    assert w.editor.picked and w.editor.lasso, 'the lasso not kept'
    w.edit_actions['edit.absorb_splinters'].trigger()
    p = w.editor.proposal
    assert p is not None and p.acceptable, w.statusBar().currentMessage()
    assert '3 splinters absorbed, in 1 chain, into 1 line' in p.summary, p.summary
    assert p.removed and p.added and p.outline
    assert all(i in sq.ways for i in RINGS), 'applied before Enter'
    assert w.editor.accept_proposal()
    assert not [i for i in RINGS if i in sq.ways]
    w.editor.undo()
    assert all(i in sq.ways for i in RINGS), 'Ctrl+Z did not put them back'


def test_the_lasso_is_drawn_while_it_is_worked_out(valley):
    w, sq = valley
    jobs = []
    w.editor.runner = jobs.append
    lasso(w)
    w.editor.absorb_splinters()
    assert w.editor.fit_cue and w.editor.proposal is None
    jobs[0].run()
    assert w.editor.fit_cue is None and w.editor.proposal is not None


def test_nothing_picked_says_what_to_pick(window):
    window.editor.set_picked({})
    window.editor.absorb_splinters()
    assert 'lasso the splinters' in window.statusBar().currentMessage()
    assert window.editor.proposal is None


def test_no_splinter_picked_says_so(valley):
    w, sq = valley
    w.editor.set_picked({NORTH: {sq.ways[-7040].refs[0]}})
    w.editor.absorb_splinters()
    assert w.editor.proposal is None
    assert w.statusBar().currentMessage().startswith('no splinters absorbed'), w.statusBar().currentMessage()


def test_shift_e_is_the_key(window):
    # on the Edit menu: test_menus, which reaches the menus as PySide 6.8 allows
    assert window.edit_actions['edit.absorb_splinters'].shortcut().toString() == 'Shift+E'


def test_the_reach_asks_the_lasso_again(valley):
    w, sq = valley
    lasso(w)
    w.editor.absorb_splinters()
    p = w.editor.proposal
    assert p.kind == 'splinters' and p.pull_back_m == 200
    w.editor.set_picked({})                 # the panel's Reach asks the same picks, whatever is picked now
    w.editor.absorb_splinters(reach_m=25)
    q = w.editor.proposal
    assert q is not p and q.pull_back_m == 25
    # the rings 120 m apart, their edges 40: at 25 m only the one touching the tip goes
    assert q.summary.startswith('1 splinter absorbed, in 1 chain') and '2 chains not absorbed' in q.summary, q.summary
    assert len(q.issues) == 2


def test_a_second_shift_e_asks_the_new_lasso_at_the_reach_set(valley):
    """The key twice, on two lassos: the second is of its own picks, at the
    reach the first left - the action's checked=False is no reach."""
    w, sq = valley
    drag(w, [(-100, -80), (130, -80), (130, 80), (-100, 80), (-100, -75)])     # the first ring only
    w.edit_actions['edit.absorb_splinters'].trigger()
    assert w.editor.proposal.summary.startswith('1 splinter absorbed'), w.editor.proposal.summary
    w.editor.proposal = None
    lasso(w)
    w.edit_actions['edit.absorb_splinters'].trigger()
    p = w.editor.proposal
    assert p is not None and p.pull_back_m == 200, w.statusBar().currentMessage()
    assert p.summary.startswith('3 splinters absorbed'), p.summary
