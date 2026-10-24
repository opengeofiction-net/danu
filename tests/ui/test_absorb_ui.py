"""E, Absorb: the contour selected, its pieces Shift-lassoed, one line - one
step - and refused when it would make a contour that crossed nothing cross."""

import math

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.ogr')               # the absorb is GDAL's geometry; the ui job has none
from PySide6.QtCore import QPointF

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def add(w, pts, ele, ring=False):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, ids, [deg(*p) for p in pts], {'ele': str(ele)}))
    if ring:
        w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, ids[0]))
    return wid


@pytest.fixture
def valley(window):
    main = add(window, [(-2000, 300), (-1000, 150), (0, 20), (0, -20), (-1000, -150), (-2000, -300)], 30)
    pieces = [add(window, pts, 30, ring=True) for pts in (
        [(0, 20), (50, 40), (100, 0), (50, -40), (0, -20)],
        [(130, 0), (180, 40), (230, 0), (180, -40)],
        [(230, 0), (280, 40), (330, 0), (280, -40)])]
    return window, main, pieces


def lasso_pieces(w):
    """Shift and a lasso round the pieces, the contour selected."""
    pts = [QPointF(*m.lonlat_to_scene(*deg(x, y))) for x, y in ((-10, -60), (350, -60), (350, 60), (-10, 60))]
    w.editor._pick_within('lasso', 'add', pts)


def contours(w, ele):
    return [x for x in w.working_set.squares[NORTH].ways.values() if x.ele == ele]


def test_the_contour_selected_and_its_pieces_lassoed_are_one_line(valley):
    w, main, pieces = valley
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[main])
    lasso_pieces(w)
    assert main in {x.id for x in contours(w, 30) if set(x.refs) & w.editor.picked[NORTH]}
    w.edit_actions['edit.absorb'].trigger()
    assert [x.id for x in contours(w, 30)] == [main], w.statusBar().currentMessage()
    assert 'absorbed 3 pieces into the 30 m contour' in w.statusBar().currentMessage()
    assert w.editor.selection.way.id == main
    w.editor.undo()
    assert sorted(x.id for x in contours(w, 30)) == sorted([main, *pieces])


def test_it_is_refused_when_a_contour_that_crossed_nothing_would_cross(valley):
    w, main, _ = valley
    add(w, [(315, -200), (315, 200)], 50)                    # through the last piece, up the valley
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[main])
    lasso_pieces(w)
    w.edit_actions['edit.absorb'].trigger()
    said = w.statusBar().currentMessage()
    assert said.startswith('not absorbed') and 'would cross 1 contour' in said, said
    assert len(contours(w, 30)) == 4


def test_two_open_contours_picked_is_refused(valley):
    """Absorbing keeps one and deletes the rest: a second open contour
    picked is a mistake, not a piece."""
    w, main, _ = valley
    add(w, [(100, -500), (200, -30)], 30)                     # open, its end in the lasso
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[main])
    lasso_pieces(w)
    w.edit_actions['edit.absorb'].trigger()
    assert '2 open contours picked' in w.statusBar().currentMessage()
    assert len(contours(w, 30)) == 5


def test_nothing_picked_says_how(window):
    window.edit_actions['edit.absorb'].trigger()
    assert 'Shift-lasso' in window.statusBar().currentMessage()


def test_rings_only_the_largest_is_kept(window):
    """No open contour among the picks: the largest ring is the one kept, and
    runs round the rest."""
    hill = add(window, [(0, 20), (-200, 120), (-400, 0), (-200, -120), (0, -20)], 30, ring=True)
    pieces = [add(window, pts, 30, ring=True) for pts in (
        [(0, 20), (50, 40), (100, 0), (50, -40), (0, -20)],
        [(130, 0), (180, 40), (230, 0), (180, -40)])]
    sq = window.working_set.squares[NORTH]
    window.editor.selection = Selection(sq, sq.ways[pieces[0]])      # a piece selected, not the hill
    pts = [QPointF(*m.lonlat_to_scene(*deg(x, y))) for x, y in ((-450, -150), (250, -150), (250, 150), (-450, 150))]
    window.editor._pick_within('lasso', 'add', pts)
    window.edit_actions['edit.absorb'].trigger()
    said = window.statusBar().currentMessage()
    assert [x.id for x in contours(window, 30)] == [hill], said
    assert contours(window, 30)[0].closed
