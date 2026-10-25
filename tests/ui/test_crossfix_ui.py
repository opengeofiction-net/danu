"""Shift+P: the open square's contours straying over the line at the next
level pushed back off it - proposed on a worker, then Enter takes it as one
step."""

import math

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.ogr')               # the push is GDAL's geometry; the ui job has none

from danu.core import edits
from danu.core.square import SquareName

CENTRE = SquareName(125, -24)
LAT = -23.98                                    # the golden square's northern edge, clear of its contours
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y):
    return 125.02 + x / KX, LAT + y / KY


def add(w, wid_tags, pts):
    sq = w.working_set.squares[CENTRE]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, ids, [deg(*p) for p in pts], wid_tags))
    return wid


def test_shift_p_proposes_and_enter_pushes_back_as_one_step(window):
    w = window
    sq = w.working_set.squares[CENTRE]
    coast = add(w, {'natural': 'coastline', 'ele': '0'}, [(0, -1000), (2000, -1000)])
    # a main-map way: what an import would bring - a positive id
    sq.ways[4015] = sq.ways.pop(coast)
    sq.ways[4015].id = 4015
    c = add(w, {'contour': 'elevation', 'ele': '10'},
            [(100, -980), (800, -980), (900, -1030), (1000, -980), (1900, -980)])
    w.editor.selection = None
    w.edit_actions['edit.push_crossings'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'push', w.statusBar().currentMessage()
    assert '1 contour pushed back off the next level' in p.summary and p.added
    before = list(sq.ways[c].refs)
    w.editor.accept_proposal()
    assert all(sq.nodes[r].lat > deg(0, -1000)[1] for r in sq.ways[c].refs), 'still out at sea'
    w.editor.undo()
    assert sq.ways[c].refs == before


def test_nothing_to_push_says_so(window):
    window.edit_actions['edit.push_crossings'].trigger()
    assert window.editor.proposal is None
    assert 'no crossing' in window.statusBar().currentMessage()
