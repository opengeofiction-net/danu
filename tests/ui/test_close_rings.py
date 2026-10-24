"""Rings closed by position only - a last node of their own at their first's
place, as recover_squares wrote them - closed when the set opens: one step,
after any recovery, said in the status bar, and the save keeps it."""

import shutil

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Square, SquareName, read_square, write_square
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.settings import Settings
from danu.ui.territory import TerritoryFetcher

from .conftest import GOLDEN

TEN = SquareName(126, -24)
RING = [(126.4, -23.95), (126.5, -23.95), (126.5, -23.92), (126.4, -23.92), (126.4, -23.95)]


@pytest.fixture
def zone(tmp_path):
    """The conftest's zone, its Tenmetre square holding a 5 m ring that ends
    on a second node at its first's place."""
    d = tmp_path / 'pizarrales'
    d.mkdir()
    shutil.copy(GOLDEN, d / GOLDEN.name)
    sq = Square(name=TEN, present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for i, ele in enumerate(range(10, 60, 10)):
        lat = -23.9 + i * 0.1
        edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, lat), (126.9, lat)], {'ele': str(ele)}).apply(sq)
    edits.AddWay(alloc.take(), [alloc.take() for _ in RING], RING, {'ele': '5'}).apply(sq)
    write_square(sq, d / 'S24E126_Tenmetre.osm.xz')
    return d


def ring_of(w):
    sq = w.working_set.squares[TEN]
    return sq, next(x for x in sq.ways.values() if x.tags.get('ele') == '5')


def test_a_ring_closed_by_position_only_is_closed_when_the_set_opens(window, zone):
    sq, ring = ring_of(window)
    assert ring.refs[0] == ring.refs[-1] and len(ring.refs) == 5 and len(set(ring.refs)) == 4
    # said, and the drop's word over it a moment later: the undo names it
    assert window.editor.dirty() and window.editor.history.describe_undo() == 'close 1 ring'
    window.editor.undo()
    sq, ring = ring_of(window)
    assert ring.refs[0] != ring.refs[-1]
    window.editor.redo()
    assert window.save_all()
    (f,) = zone.glob('S24E126*')
    saved = next(x for x in read_square(f).ways.values() if x.tags.get('ele') == '5')
    assert saved.refs[0] == saved.refs[-1]


def test_with_an_autosave_it_follows_the_recovery(qtbot, zone, tmp_path, territory_files):
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                   territory_fetcher=fetcher, data_dir=tmp_path / 'data')
    w.prompt_on_close = False
    qtbot.addWidget(w)
    w.show()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
    qtbot.waitUntil(lambda: ring_of(w)[1].refs[0] == ring_of(w)[1].refs[-1], timeout=5000)
    assert w.editor.history.describe_undo() == 'close 1 ring'
