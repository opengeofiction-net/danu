"""An import that lays a main-map way over a negative copy of it at its level
removes the copy, as a step of its own after the import's."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way
from danu.ui.water import Answer
from danu.water import overpass

NORTH = SquareName(125, -23)
SHORE = [(125.50, -22.50), (125.51, -22.50), (125.51, -22.49), (125.50, -22.49)]


def test_the_import_removes_the_copy_under_the_lake_it_brings(window):
    sq = window.working_set.squares[NORTH]
    alloc = window.editor.history.alloc(sq)
    copy, ids = alloc.take(), [alloc.take() for _ in SHORE]
    window.editor.do(sq, edits.AddWay(copy, [*ids, ids[0]], [*SHORE, SHORE[0]], {'natural': 'water', 'ele': '40'}))
    water = overpass.Water()
    for k, (lon, lat) in enumerate(SHORE, 1):
        water.nodes[k] = Node(id=k, lon=lon, lat=lat)
    water.ways[200] = Way(id=200, refs=[1, 2, 3, 4, 1], tags={'natural': 'water', 'ele': '40'})
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways), frozenset()), window.working_set)
    said = window.statusBar().currentMessage()
    assert 200 in sq.ways and copy not in sq.ways, said
    assert "1 contour doubled under them removed, the main map's kept" in said
    window.editor.undo()
    assert 200 in sq.ways and copy in sq.ways, 'the first undo puts the copy back'
    window.editor.undo()
    assert 200 not in sq.ways and copy in sq.ways
