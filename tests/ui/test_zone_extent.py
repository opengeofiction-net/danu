"""Imports keep to the zone: where its extent is kept, a feature's home is
one of the zone's squares, never a neighbour of the set beyond its edge -
which can't be uploaded from here, and is not in the zone's build. One held
out there moves in; one wholly out there is not imported."""

import pytest

pytest.importorskip('PySide6')

from danu.core import mirror
from danu.core.square import SquareName
from danu.ui.water import Snapshot, coast_work, copies_by, heights_held, heights_work, held_by, water_work

HERE, WEST = SquareName(125, -24), SquareName(124, -24)      # the set is S25E124-S23E126


def zoned(zone):
    """pizarrales without its western column: S24E124 is the set's, not the zone's."""
    mirror.write_manifest(zone, {})
    mirror.write_extent(zone, zone.name, ['S25E125-S23E126'])


def line(wid, pts, tags):
    nodes = ''.join(f'<node id="{wid * 10 + i}" lat="{lat}" lon="{lon}"/>' for i, (lon, lat) in enumerate(pts))
    refs = ''.join(f'<nd ref="{wid * 10 + i}"/>' for i in range(len(pts)))
    tag = ''.join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
    return f'<?xml version="1.0"?><osm version="0.6">{nodes}<way id="{wid}">{refs}{tag}</way></osm>'.encode()


# mostly in WEST, a node over the line into HERE; and one wholly in WEST
RIVER = [(124.2, -23.5), (124.5, -23.5), (124.8, -23.5), (125.1, -23.5)]
AWAY = [(124.2, -23.6), (124.5, -23.6)]


def water(w, payload):
    ws = w.working_set
    answer = water_work(payload, ws, Snapshot(held_by(ws), w.zone_dir, copies_by(ws), mirror.extent(w.zone_dir)))
    w._water_imported(answer, ws)
    return answer


def coastline(w, payload):
    ws = w.working_set
    answer = coast_work(payload, ws, Snapshot(held_by(ws), within=mirror.extent(w.zone_dir)))
    w._coast_imported(answer, ws)
    return answer


def test_without_an_extent_a_river_is_held_where_most_of_it_lies(window):
    w = window
    water(w, line(501, RIVER, {'waterway': 'river'}))
    assert 501 in w.working_set.squares[WEST].ways, 'nothing is known of the zone: as before'


def test_a_river_mostly_outside_the_zone_is_held_in_the_zone(window, zone):
    zoned(zone)
    w = window
    water(w, line(501, RIVER, {'waterway': 'river'}))
    ws = w.working_set
    assert 501 in ws.squares[HERE].ways and 501 not in ws.squares[WEST].ways
    assert all(ws.squares[HERE].nodes[r] for r in ws.squares[HERE].ways[501].refs), 'its nodes go with it'


def test_a_river_wholly_outside_the_zone_is_not_imported(window, zone):
    zoned(zone)
    w = window
    water(w, line(502, AWAY, {'waterway': 'river'}))
    assert not any(502 in sq.ways for sq in w.working_set.squares.values())


def test_a_river_held_outside_the_zone_moves_into_it(window, zone):
    w = window
    water(w, line(501, RIVER, {'waterway': 'river'}))           # imported before the extent was kept
    ws = w.working_set
    assert 501 in ws.squares[WEST].ways
    zoned(zone)
    water(w, line(501, RIVER, {'waterway': 'river'}))
    assert 501 in ws.squares[HERE].ways and 501 not in ws.squares[WEST].ways, 'held twice, or left out there'
    w.editor.undo()
    assert 501 in ws.squares[WEST].ways and 501 not in ws.squares[HERE].ways, 'one step back'


def test_a_coastline_held_outside_the_zone_moves_into_it_and_is_said(window, zone):
    w = window
    coastline(w, line(601, RIVER, {'natural': 'coastline'}))
    ws = w.working_set
    assert 601 in ws.squares[WEST].ways
    zoned(zone)
    coastline(w, line(601, RIVER, {'natural': 'coastline'}))
    assert 601 in ws.squares[HERE].ways and 601 not in ws.squares[WEST].ways
    assert [ws.squares[HERE].nodes[r].lon for r in ws.squares[HERE].ways[601].refs] == [p[0] for p in RIVER], \
        'its direction is the coastline\'s'
    assert 'moved into the zone out of S24E124' in w.statusBar().currentMessage()


def test_a_coastline_held_in_the_zone_is_never_moved(window, zone):
    zoned(zone)
    w = window
    # most of it in S24E126, held in HERE: the coastline import moves nothing
    pts = [(125.9, -23.4), (126.2, -23.4), (126.5, -23.4)]
    ws = w.working_set
    coastline(w, line(602, pts[:1] + [(125.8, -23.4)], {'natural': 'coastline'}))
    assert 602 in ws.squares[HERE].ways
    coastline(w, line(602, pts, {'natural': 'coastline'}))
    assert 602 in ws.squares[HERE].ways and 602 not in ws.squares[SquareName(126, -24)].ways


def test_a_new_spot_height_outside_the_zone_is_not_imported_and_is_said(window, zone):
    from danu.core import edits
    w = window
    ws = w.working_set
    west = ws.squares[WEST]
    alloc = w.editor.history.alloc(west)
    w.editor.do(west, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()],
                                   [(124.1, -23.9), (124.9, -23.1)], {'ele': '100'}))
    zoned(zone)
    payload = ('<?xml version="1.0"?><osm version="0.6"><node id="77" lat="-23.5" lon="124.5">'
               '<tag k="natural" v="peak"/><tag k="ele" v="150"/></node></osm>').encode()
    answer = heights_work(payload, ws, heights_held(ws, mirror.extent(w.zone_dir)))
    assert answer.outside == 1 and not answer.placed
    w._heights_imported(answer, ws)
    assert '1 outside the zone, not imported' in w.statusBar().currentMessage()
    # without the extent, it is imported as before
    answer = heights_work(payload, ws, heights_held(ws))
    assert 77 in answer.placed[WEST]
