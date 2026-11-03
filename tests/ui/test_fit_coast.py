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


def test_ctrl_shift_k_proposes_every_island_of_the_square_fitted(island):
    w, sq, shore = island
    # the island is in the blank square to the north: that the set's centre,
    # the square Ctrl+Shift+K fits
    w.working_set.centre = NORTH
    w.editor.selection = None
    w.edit_actions['edit.fit_square'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'fit', w.statusBar().currentMessage()
    assert '1 island fitted to the coast' in p.summary
    assert w.editor.accept_proposal()
    assert not crossing_coast(w)


def test_ctrl_shift_k_with_nothing_to_fit_says_so(window):
    w = window
    w.editor.runner = lambda job: job.run()
    w.editor.fit_square()
    assert w.editor.proposal is None
    assert w.statusBar().currentMessage().startswith('nothing to fit: no contour crosses an island')


def test_shift_k_on_the_mainland_says_why_not(window):
    w = window
    sq = w.working_set.squares[NORTH]
    ids = []
    for x in (-3000, 3000):
        nid = next(_ids)
        sq.nodes[nid] = Node(id=nid, lon=125.5 + x / KX, lat=LAT)
        ids.append(nid)
    main = Way(id=4017, refs=ids, tags={'natural': 'coastline', 'ele': '0'})
    sq.ways[4017] = main
    w.contours.set_working_set(w.working_set)
    w.editor.runner = lambda job: job.run()
    w.editor.selection = Selection(sq, main)
    w.editor.fit_coast()
    assert w.editor.proposal is None
    assert w.statusBar().currentMessage() == ('nothing to fit: its coastline does not close in the open set - '
                                              'the mainland, or an island running out of it')
