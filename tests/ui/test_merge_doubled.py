"""Nodes at one place made one when the set opens, and the rings that leaves
no line removed; water relations without a type given ``multipolygon`` - the
duplicated nodes, self-crossing ways and relations without type JOSM listed
in roantra's N44E026. Each one step, said in the status bar, and the save
keeps it."""

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
    """The conftest's zone, its Tenmetre square holding a line with a
    segment of no length, a 20 m knoll collapsed to two places, and a lake
    whose relation has no type."""
    d = tmp_path / 'pizarrales'
    d.mkdir()
    shutil.copy(GOLDEN, d / GOLDEN.name)
    sq = Square(name=TEN, present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    pts = [(126.1, -23.5), (126.3, -23.5), (126.3, -23.5), (126.9, -23.5)]
    edits.AddWay(alloc.take(), [alloc.take() for _ in pts], pts, {'ele': '10'}).apply(sq)
    knoll = alloc.take()
    ids = [alloc.take() for _ in range(4)]
    edits.AddWay(knoll, ids + [ids[0]], [(126.6, -23.6), (126.6, -23.6000001)] * 2 + [(126.6, -23.6)],
                 {'ele': '20'}).apply(sq)
    ids = [alloc.take() for _ in LAKE[:-1]]
    ring = alloc.take()
    edits.AddWay(ring, ids + [ids[0]], LAKE, {}).apply(sq)
    sq.relations[7] = Relation(id=7, members=[Member('way', ring, 'outer')], tags={'natural': 'water', 'ele': '5'})
    write_square(sq, d / 'S24E126_Tenmetre.osm.xz')
    return d


def test_doubled_nodes_are_merged_and_relations_typed_when_the_set_opens(window, zone):
    sq = window.working_set.squares[TEN]
    assert edits.tidy_contours(sq) is None
    assert [len(w.refs) for w in sq.ways.values() if w.tags.get('ele') == '10'] == [3]
    assert not [w for w in sq.ways.values() if w.tags.get('ele') == '20'], 'the knoll that was no line is gone'
    assert sq.relations[7].tags['type'] == 'multipolygon'
    assert window.editor.dirty()
    said = window.statusBar().toolTip() + window.statusBar().currentMessage()
    # and not Los Pizarrales beside it, whose 39 contours copied node on node are duplicates, not one line
    assert 'merged 3 nodes doubled at one place, removed 1 contour that left no line, in S24E126 -' in said
    assert 'given type=multipolygon' in said
    window.editor.undo()
    assert 'type' not in sq.relations[7].tags
    window.editor.redo()
    assert window.save_all()
    (f,) = zone.glob('S24E126*')
    saved = read_square(f)
    assert edits.tidy_contours(saved) is None and saved.relations[7].tags['type'] == 'multipolygon'


def test_the_checks_are_found_once_after_the_tidy(qtbot, zone, tmp_path, territory_files, monkeypatch):
    """With autosave on, the tidy is the recovery's last step, a moment after
    the set is drawn. The checks' scan began before it, then found the tidy -
    more than WIDE_EDIT ways across roantra - and found everything again: the
    checks twice at every start. It begins after it now, once."""
    from danu.core.square import SquareName as Name
    from danu.ui import app as app_module
    from danu.ui.app import MainWindow
    from danu.ui.config import load_layers
    from danu.ui.settings import Settings
    from danu.ui.territory import TerritoryFetcher
    scans = []
    real = app_module.find_checks

    def counted(ws, **kw):
        scans.append(edits.tidy_contours(ws.squares[TEN]) is None)
        return real(ws, **kw)
    monkeypatch.setattr(app_module, 'find_checks', counted)
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                   territory_fetcher=fetcher, data_dir=tmp_path / 'data')
    w.prompt_on_close = False
    w._checks_runner = lambda job: job.run()
    qtbot.addWidget(w)
    w.show()
    w.checks_dock.show()
    assert w.autosave is not None
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, Name(125, -24))
    qtbot.waitUntil(lambda: bool(scans), timeout=5000)
    qtbot.wait(300)
    assert scans == [True], 'the scan began before the tidy, or ran twice'
    assert w.editor.history.describe_undo() is not None
