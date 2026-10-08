"""Importing the main map's spot heights from the editor - G9, R41.

The fetch is a canned Overpass answer and the job runs where it is asked for,
as the water import's tests do: none of them reach the network.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName

NORTH = SquareName(125, -23)


def answer(*nodes) -> bytes:
    out = ['<osm version="0.6">']
    for i, lon, lat, tags in nodes:
        out.append(f'<node id="{i}" lat="{lat}" lon="{lon}">'
                   + ''.join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()) + '</node>')
    out.append('</osm>')
    return '\n'.join(out).encode()


def importing(w, payload):
    w.heights._fetch = lambda bounds: payload
    w.heights._runner = lambda job: job.run()
    w.edit_actions['edit.import_heights'].trigger()


PEAKS = answer((501, 125.5, -22.5, {'natural': 'peak', 'name': 'Welfare Peak', 'ele': '430'}),
               (502, 125.6, -22.4, {'natural': 'saddle', 'ele': '8,635 Ft'}),
               (503, 125.7, -22.3, {'natural': 'peak', 'ele': 'high'}))


def test_the_import_brings_peaks_and_saddles_in_as_spot_heights_one_step(window):
    w = window
    sq = w.working_set.squares[NORTH]
    before = edits.snapshot(sq)
    importing(w, PEAKS)
    assert sq.nodes[501].tags == {'natural': 'peak', 'name': 'Welfare Peak', 'ele': '430'}
    assert sq.nodes[502].tags['ele'] == '2632'
    assert 503 not in sq.nodes
    said = w.statusBar().currentMessage()
    assert 'imported 2 spot heights - peak 1, saddle 1' in said and '1 skipped' in said
    assert (NORTH, 501) in w.contours.spots, 'not drawn as a spot height'
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not take the import back'


def test_a_second_import_keeps_a_height_set_here(window):
    w = window
    sq = w.working_set.squares[NORTH]
    importing(w, PEAKS)
    n = sq.nodes[501]
    sq.nodes[501] = Node(id=501, lon=n.lon, lat=n.lat, tags={**n.tags, 'ele': '436'})
    importing(w, PEAKS)
    assert sq.nodes[501].tags['ele'] == '436'


def test_one_upstream_no_longer_answers_is_reported_kept_and_chosen_from_the_report(window):
    w = window
    sq = w.working_set.squares[NORTH]
    importing(w, PEAKS)
    importing(w, answer((502, 125.6, -22.4, {'natural': 'saddle', 'ele': '8,635 Ft'})))
    assert 501 in sq.nodes, 'deleted rather than reported'
    assert '1 held no longer upstream, kept' in w.statusBar().currentMessage()
    (g,) = w.gone_from_upstream
    assert (g.kind, g.id, g.what) == ('node', 501, 'peak')
    w._choose_gone(g)
    sel = w.editor.selection
    assert sel.way is None and sel.node == 501
    assert 'removes it, doing nothing keeps it' in w.statusBar().currentMessage()


def test_the_key_and_the_button(window):
    assert window.edit_actions['edit.import_heights'].shortcut().toString() == 'Ctrl+Shift+I'
    window.heights._runner = lambda job: None          # asked for, not run
    window.controls.heights.click()
    assert window.heights.busy
