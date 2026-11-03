"""Fit contours to the coast from the editor: Shift+K on a coastline
proposes its island's low contours laid again inside it; Enter takes it as
one step, Ctrl+Z puts them back.

In the fixture's blank square to the north: an island whose 10 and 20 m
run out over its coast, and 30 m keeps inside."""

import math

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.gdal')

from danu.checks import crossings
from danu.core.square import Node, SquareName, Way
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
_ids = iter(range(-9000, -5001))


def ring(sq, r, tags, wobble=0.0, wid=None, n=72):
    refs = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r + wobble * math.sin(7 * a)
        nid = next(_ids)
        sq.nodes[nid] = Node(id=nid, lon=125.5 + rr * math.cos(a) / KX, lat=LAT + rr * math.sin(a) / KY)
        refs.append(nid)
    wid = next(_ids) if wid is None else wid
    sq.ways[wid] = Way(id=wid, refs=refs + [refs[0]], tags=dict(tags))
    return sq.ways[wid]


@pytest.fixture
def island(window):
    w = window
    sq = w.working_set.squares[NORTH]
    shore = ring(sq, 800, {'natural': 'coastline', 'ele': '0'}, wid=4015, n=96)
    ring(sq, 860, {'contour': 'elevation', 'ele': '10'}, wobble=80)
    ring(sq, 760, {'contour': 'elevation', 'ele': '20'}, wobble=120)
    ring(sq, 500, {'contour': 'elevation', 'ele': '30'})
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    return w, sq, shore


def crossing_coast(w):
    return [c for c in crossings.find(w.working_set) if 4015 in (c.a[1], c.b[1])]


def test_shift_k_on_a_coastline_proposes_its_island_fitted_and_enter_takes_it(island):
    w, sq, shore = island
    assert crossing_coast(w)
    w.editor.selection = Selection(sq, shore)
    w.edit_actions['edit.fit_coast'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'fit' and p.acceptable, w.statusBar().currentMessage()
    assert '1 island fitted to the coast: 2 contours crossing it or at sea replaced' in p.summary
    assert p.removed and p.added
    assert w.editor.accept_proposal()
    assert not crossing_coast(w), 'still crossing'
    w.editor.undo()
    assert crossing_coast(w), 'Ctrl+Z did not put them back'


def test_nodes_picked_on_a_coastline_choose_it(island):
    w, sq, shore = island
    w.editor.selection = None
    w.editor.set_picked({NORTH: {shore.refs[3]}})
    w.editor.fit_coast()
    assert w.editor.proposal is not None and w.editor.proposal.kind == 'fit'


def test_nothing_chosen_says_what_to_choose(window):
    w = window
    w.editor.selection = None
    w.editor.fit_coast()
    assert 'choose a coastline' in w.statusBar().currentMessage()
    assert w.editor.proposal is None


def test_an_island_nothing_crosses_says_so(window):
    w = window
    sq = w.working_set.squares[NORTH]
    shore = ring(sq, 800, {'natural': 'coastline', 'ele': '0'}, wid=4016, n=96)
    ring(sq, 600, {'contour': 'elevation', 'ele': '10'})
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    w.editor.selection = Selection(sq, shore)
    w.editor.fit_coast()
    assert w.editor.proposal is None
    assert w.statusBar().currentMessage() == 'nothing to fit: no contour crosses the coast chosen'


# ------------------------------------------------------------ in a lasso

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from danu.ui import mercator as m  # noqa: E402

LB, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def line(sq, tags, pts, wid=None):
    refs = []
    for x, y in pts:
        nid = next(_ids)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    wid = next(_ids) if wid is None else wid
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


def wave(base, amp):
    return [(x, base + amp * math.sin(2 * math.pi * x / 400)) for x in range(-1500, 1501, 20)]


@pytest.fixture
def mainland(window):
    """A coast running east, land to the north - open, the mainland's - and
    10-30 m waving across it, 40 m keeping off."""
    w = window
    sq = w.working_set.squares[NORTH]
    line(sq, {'natural': 'coastline', 'ele': '0'}, [(x, 0.0) for x in range(-1500, 1501, 25)], wid=4017)
    for ele, base, amp in ((10, 30, 50), (20, 70, 80), (30, 110, 115)):
        line(sq, {'contour': 'elevation', 'ele': str(ele)}, wave(base, amp))
    line(sq, {'contour': 'elevation', 'ele': '40'}, [(x, 280.0) for x in range(-1500, 1501, 50)])
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    w.edit_actions['tool.select'].trigger()
    w.map.set_zoom(15)
    w.map.center_on_lonlat(*deg(0, 100))
    return w, sq


def drag(w, pts, mods=Qt.KeyboardModifier.NoModifier):
    vp = w.map.viewport()

    def ev(kind, p, button, buttons):
        return QMouseEvent(kind, p, vp.mapToGlobal(p.toPoint()), button, buttons, mods)
    ps = [QPointF(w.map.mapFromScene(QPointF(*m.lonlat_to_scene(*deg(x, y))))) for x, y in pts]
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonPress, ps[0], LB, LB))
    for a, b in zip(ps, ps[1:], strict=False):
        for k in range(1, 6):
            QApplication.sendEvent(vp, ev(QEvent.Type.MouseMove, a + (b - a) * (k / 5), NB, LB))
    QApplication.sendEvent(vp, ev(QEvent.Type.MouseButtonRelease, ps[-1], LB, NB))


def round_box(w, x0, y0, x1, y1, mods=Qt.KeyboardModifier.NoModifier):
    drag(w, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0 + 5)], mods)


def in_lasso(c):
    (x0, y0), (x1, y1) = deg(-600, -150), deg(600, 320)
    return x0 <= c.lon <= x1 and y0 <= c.lat <= y1


def test_shift_k_after_a_lasso_fits_the_coast_inside_it(mainland):
    w, sq = mainland
    assert [c for c in crossings.find(w.working_set) if in_lasso(c)]
    round_box(w, -600, -150, 600, 320)
    assert w.editor.picked and w.editor.lasso, 'the lasso not kept'
    w.edit_actions['edit.fit_coast'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'fit' and p.acceptable, w.statusBar().currentMessage()
    assert 'fitted to the coast in the lasso, under 40 m: 3 contours replaced' in p.summary, p.summary
    assert p.outline and len(p.outline) >= 2, 'the lasso and its area not shown'
    assert w.editor.accept_proposal()
    assert not [c for c in crossings.find(w.working_set) if in_lasso(c)], 'still crossing in the lasso'
    w.editor.undo()
    assert [c for c in crossings.find(w.working_set) if in_lasso(c)], 'Ctrl+Z did not put them back'


def test_the_lasso_is_drawn_while_the_fit_is_worked_out(mainland):
    w, sq = mainland
    jobs = []
    w.editor.runner = jobs.append
    round_box(w, -600, -150, 600, 320)
    w.editor.fit_coast()
    assert w.editor.fit_cue and len(w.editor.fit_cue) == len(w.editor.lasso)
    assert w.editor.overlay.extent() is not None and w.editor.proposal is None
    jobs[0].run()
    assert w.editor.fit_cue is None and w.editor.proposal is not None


def test_adding_to_a_lasso_leaves_no_one_shape(mainland):
    w, sq = mainland
    round_box(w, -600, -150, 600, 320)
    assert w.editor.lasso
    round_box(w, 700, -150, 900, 320, Qt.KeyboardModifier.ShiftModifier)
    assert w.editor.picked and w.editor.lasso is None
    w.editor.fit_coast()
    assert w.editor.proposal is None
    assert 'does not close' in w.statusBar().currentMessage()
