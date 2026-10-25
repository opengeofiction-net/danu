"""A water feature held where most of it lies, among the zone's squares, open
or not - the sea, r470432, whose home is two squares from N46E030 - and moved
there when it grows, its level and fill lines with it."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, read_square, write_square
from danu.ui.water import Snapshot, copies_by, held_by, water_work
from danu.water.flatten import FILL

HERE, FAR = SquareName(125, -24), SquareName(128, -24)       # FAR is in the zone, outside the 3x3


def sea(lon0=127.5):
    """A sea's ring from ``lon0`` east to 128.9: by default one node in the
    set (at 125.9), the rest in FAR."""
    pts = [(125.9, -23.5), (lon0, -23.2), (128.5, -23.2), (128.9, -23.5), (128.5, -23.8), (lon0, -23.8)]
    nodes = ''.join(f'<node id="{900 + i}" lat="{lat}" lon="{lon}"/>' for i, (lon, lat) in enumerate(pts))
    refs = ''.join(f'<nd ref="{900 + i}"/>' for i in range(len(pts))) + '<nd ref="900"/>'
    return (f'<?xml version="1.0"?><osm version="0.6">{nodes}<way id="37901776">{refs}</way>'
            '<relation id="470432"><member type="way" ref="37901776" role="outer"/>'
            '<tag k="natural" v="water"/><tag k="type" v="multipolygon"/></relation></osm>').encode()


@pytest.fixture
def zoned(window, zone):
    """The fixture's zone with a square further east, outside the open set."""
    write_square(Square(name=FAR, present=True, attrs={'version': '0.6', 'upload': 'never'}),
                 zone / 'S24E128.osm.xz')
    return window, zone


def imported(w, payload):
    ws = w.working_set
    answer = water_work(payload, ws, Snapshot(held_by(ws), w.zone_dir, copies_by(ws)))
    w._water_imported(answer, ws)
    return answer


def test_a_relation_mostly_outside_the_set_is_held_in_its_zone_square_and_saved(zoned):
    w, zone = zoned
    answer = imported(w, sea())
    ws = w.working_set
    assert FAR in ws.extra and 470432 in ws.extra[FAR].relations, w.statusBar().currentMessage()
    assert all(470432 not in sq.relations and 37901776 not in sq.ways for sq in ws.squares.values()), \
        'brought in bare, or twice'
    assert 'held in S24E128, outside the set' in w.statusBar().currentMessage()
    assert answer.loaded and not answer.moved
    w.save_all()
    assert 470432 in read_square(zone / 'S24E128.osm.xz').relations, 'not saved with the set'


def test_a_relation_that_grew_out_of_the_set_moves_with_its_level_and_fill_lines(zoned):
    w, _ = zoned
    ws = w.working_set
    here = ws.squares[HERE]
    # held here, flattened at 0 m: its ring and relation carry the level, a fill line says whose
    alloc = w.editor.history.alloc(here)
    ids = [alloc.take() for _ in range(4)]
    coords = [(125.5, -23.5), (125.9, -23.5), (125.9, -23.8), (125.5, -23.8)]
    for i, (lon, lat) in zip(ids, coords, strict=True):
        here.nodes[i] = Node(id=i, lon=lon, lat=lat)
    here.ways[37901776] = Way(id=37901776, refs=[*ids, ids[0]], tags={'ele': '0'})
    here.relations[470432] = Relation(id=470432, members=[Member('way', 37901776, 'outer')],
                                      tags={'natural': 'water', 'type': 'multipolygon', 'ele': '0'})
    fill_ids = [alloc.take() for _ in range(3)]
    w.editor.do(here, edits.AddWay(fill_ids[0], fill_ids[1:], [(125.6, -23.6), (125.8, -23.6)],
                                   {'ele': '0', FILL: 'relation/470432'}))
    imported(w, sea())                                            # it has grown east, into FAR
    far = ws.extra[FAR]
    assert 470432 in far.relations and 470432 not in here.relations
    assert far.relations[470432].tags.get('ele') == '0', 'its level was left behind'
    assert far.ways[37901776].tags.get('ele') == '0'
    assert [x for x in far.ways.values() if x.tags.get(FILL) == 'relation/470432'], 'its fill line was left behind'
    assert not [x for x in here.ways.values() if x.tags.get(FILL) == 'relation/470432']
    assert 'moved to where most of it now lies' in w.statusBar().currentMessage()
    w.editor.undo()
    assert 470432 in here.relations and 470432 not in far.relations, 'one Ctrl+Z did not take the move back'


def test_a_feature_whose_home_is_open_stays_in_the_set(zoned):
    """Most of it in the set: the zone's other square is not read."""
    w, _ = zoned
    imported(w, sea(lon0=125.6).replace(b'lon="128.5"', b'lon="125.7"').replace(b'lon="128.9"', b'lon="125.8"'))
    ws = w.working_set
    assert 470432 in ws.squares[HERE].relations and not ws.extra


def test_a_copy_left_in_the_set_goes_when_the_home_is_read_alongside(zoned):
    """Imports before #278 left the estuary's ways in N46E029 as well as in
    N46E028, its home. With the home read alongside before the import, the
    import saw the feature held at home and left the copy: every copy that
    is not the home's now goes."""
    w, zone = zoned
    far = Square(name=FAR, present=True, attrs={'version': '0.6', 'upload': 'never'})
    write_square(far, zone / 'S24E128.osm.xz')
    imported(w, sea())                               # held in FAR, read alongside
    ws = w.working_set
    w.save_all()
    here = ws.squares[HERE]
    ring = ws.extra[FAR].ways[37901776]
    for r in ring.refs:                              # a stale copy of the ring, left in the set
        here.nodes[r] = ws.extra[FAR].nodes[r]
    here.ways[37901776] = Way(id=37901776, refs=list(ring.refs), tags={})
    imported(w, sea())
    assert 37901776 not in here.ways, 'the copy left in the set stayed'
    assert 37901776 in ws.extra[FAR].ways and 470432 in ws.extra[FAR].relations
