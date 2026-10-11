"""Phase 6's exit: every row of the validation table a row in the panel,
each a place to go to. The table's rows by the panel's checks, and a row of
each chosen: what it is about selected, and the place brought into view.

The rows the other tests choose through the panel - crossings, loops,
touches, spot heights, a file's off-ladder value, a lake, sea level - are
chosen there; here every finding the panel's findingChosen carries, of
every kind, is put through the window as a choice is."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QPointF

from danu.checks.files import Finding
from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui.checks_dock import CHECKS

NORTH = SquareName(125, -23)

# the spec's validation table, row by row, and the panel's check that lists it
TABLE = {'ways over 2,000 nodes': 'long', 'ways over 10,000 nodes': 'long', 'non-numeric `ele`': 'ele',
         'crossing contours': 'crossings', 'duplicate coincident contours': 'touches',
         'rivers which climb': 'climb', 'sea level off the coastline': 'sea',
         'body spanning contours': 'lake', 'off-ladder `ele`, used once or twice': 'ladder',
         'unreachable ground': 'unreached'}


def test_every_row_of_the_table_is_a_check_in_the_panel():
    from pathlib import Path
    spec = (Path(__file__).parents[2] / 'docs' / 'spec.md').read_text()
    table = spec[spec.index('## Validation'):spec.index('## Ownership and handoff')]
    rows = [line.split('|')[1].strip() for line in table.splitlines()
            if line.startswith('| ') and not line.startswith('| check') and not line.startswith('|---')]
    assert rows and set(rows) == set(TABLE), 'the table and this test disagree'
    assert set(TABLE.values()) <= set(CHECKS)


@pytest.fixture
def placed(window):
    w = window
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in range(3)],
                                 [(125.40, -22.40), (125.45, -22.40), (125.50, -22.40)], {'ele': '100'}))
    w.map.set_zoom(10)
    w.map.center_on_lonlat(125.0, -23.9)               # well away from it
    return w, sq, wid


def in_view(w, lon, lat) -> bool:
    vp = w.map.viewport().rect()
    p = w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat)))
    return vp.contains(p)


@pytest.mark.parametrize('kind', ['long', 'ele', 'ladder', 'lake', 'bare', 'climb', 'backwards'])
def test_a_row_about_a_way_selects_it_and_shows_it(placed, kind):
    w, sq, wid = placed
    f = Finding(NORTH, kind, 'a row', 'why', 125.45, -22.40, (125.40, -22.41, 125.50, -22.39), way=wid)
    assert not in_view(w, 125.45, -22.40)
    w._choose_finding(f)
    assert w.editor.selection is not None and w.editor.selection.way.id == wid
    assert in_view(w, 125.45, -22.40)


@pytest.mark.parametrize('kind', ['sea', 'unreached'])
def test_a_row_about_a_place_shows_the_place(placed, kind):
    w, _sq, _wid = placed
    f = Finding(NORTH, kind, 'a row', 'why', 125.7, -22.6, (125.6, -22.7, 125.8, -22.5))
    w._choose_finding(f)
    assert in_view(w, 125.7, -22.6) and w.editor.marks_focus == [m.lonlat_to_scene(125.7, -22.6)]
