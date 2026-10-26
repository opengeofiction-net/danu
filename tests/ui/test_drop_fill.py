"""Fill lines taken out when the set opens - ``danu:fill``, drawn across a
lake by flattening to hold it flat until the build held a lake at its level
itself (#191): one step, said in the status bar, and the save keeps it."""

import shutil

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Member, Relation, Square, SquareName, read_square, write_square

from .conftest import GOLDEN

TEN = SquareName(126, -24)
LAKE = [(126.4, -23.95), (126.5, -23.95), (126.5, -23.85), (126.4, -23.85), (126.4, -23.95)]


@pytest.fixture
def zone(tmp_path):
    """The conftest's zone, its Tenmetre square holding a lake flattened at
    5 m with three fill lines across it."""
    d = tmp_path / 'pizarrales'
    d.mkdir()
    shutil.copy(GOLDEN, d / GOLDEN.name)
    sq = Square(name=TEN, present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for i, ele in enumerate(range(10, 60, 10)):
        lat = -23.8 + i * 0.1
        edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, lat), (126.9, lat)], {'ele': str(ele)}).apply(sq)
    ids = [alloc.take() for _ in LAKE[:-1]]
    ring = alloc.take()
    edits.AddWay(ring, ids + [ids[0]], LAKE, {'ele': '5'}).apply(sq)
    sq.relations[7] = Relation(id=7, members=[Member('way', ring, 'outer')], tags={'natural': 'water', 'ele': '5'})
    for lat in (-23.93, -23.9, -23.87):
        edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.4, lat), (126.5, lat)],
                     {'ele': '5', 'danu:fill': 'relation/7'}).apply(sq)
    write_square(sq, d / 'S24E126_Tenmetre.osm.xz')
    return d


def fill_lines(sq):
    return [x for x in sq.ways.values() if 'danu:fill' in x.tags]


def test_fill_lines_are_taken_out_when_the_set_opens(window, zone):
    sq = window.working_set.squares[TEN]
    assert fill_lines(sq) == []
    # said, and the drop's word over it a moment later: the undo names it
    assert window.editor.dirty() and window.editor.history.describe_undo() == 'remove 3 fill lines'
    window.editor.undo()
    assert len(fill_lines(window.working_set.squares[TEN])) == 3
    window.editor.redo()
    assert window.save_all()
    (f,) = zone.glob('S24E126*')
    saved = read_square(f)
    assert fill_lines(saved) == [] and saved.relations[7].tags['ele'] == '5'
