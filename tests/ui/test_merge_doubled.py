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
