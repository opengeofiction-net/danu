"""Importing the main map's spot heights from the editor - G9, R41.

The fetch is a canned Overpass answer and the job runs where it is asked for,
as the water import's tests do: none of them reach the network.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way

NORTH = SquareName(125, -23)


def answer(*nodes) -> bytes:
    out = ['<osm version="0.6">']
    for i, lon, lat, tags in nodes:
        out.append(f'<node id="{i}" lat="{lat}" lon="{lon}">'
                   + ''.join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()) + '</node>')
    out.append('</osm>')
    return '\n'.join(out).encode()


def contoured(w, name=NORTH, wid=-7001):
    """A 100 m ring round the peaks below, in one of the fixture's blank
    squares: a spot height is imported only where there are contours."""
    sq = w.working_set.squares[name]
    if wid in sq.ways:
        return
    dx = name.lon - NORTH.lon
    corners = ((125.45, -22.55), (125.75, -22.55), (125.75, -22.25), (125.45, -22.25))
    refs = []
    for i, (lon, lat) in enumerate(corners):
        nid = wid * 10 - i
        sq.nodes[nid] = Node(id=nid, lon=lon + dx, lat=lat)
        refs.append(nid)
    sq.ways[wid] = Way(id=wid, refs=[*refs, refs[0]], tags={'ele': '100'})


def importing(w, payload):
    contoured(w)
    w.heights._fetch = lambda bounds: payload
    w.heights._runner = lambda job: job.run()
    w.edit_actions['edit.import_heights'].trigger()


PEAKS = answer((501, 125.5, -22.5, {'natural': 'peak', 'name': 'Welfare Peak', 'ele': '430'}),
               (502, 125.6, -22.4, {'natural': 'saddle', 'ele': '8,635 Ft'}),
               (503, 125.7, -22.3, {'natural': 'peak', 'ele': 'high'}))


def test_the_import_brings_peaks_and_saddles_in_as_spot_heights_one_step(window):
    w = window
    sq = w.working_set.squares[NORTH]
    contoured(w)
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


def test_one_beyond_the_contours_is_not_imported_and_is_counted(window):
    w = window
    sq = w.working_set.squares[NORTH]
    importing(w, answer((501, 125.5, -22.5, {'natural': 'peak', 'ele': '430'}),
                        (504, 125.9, -22.9, {'natural': 'peak', 'name': 'Far Peak', 'ele': '300'})))
    assert 501 in sq.nodes and 504 not in sq.nodes
    said = w.statusBar().currentMessage()
    assert 'imported 1 spot height' in said and '1 beyond the contours, not imported' in said
    assert w.gone_from_upstream == [], 'one beyond the contours is not gone from upstream'


def differs_rows(dock):
    out = []
    for i in range(dock.tree.topLevelItemCount()):
        head = dock.tree.topLevelItem(i)
        if head.text(0).startswith('Height differs'):
            out = [head.child(j) for j in range(head.childCount())]
    return out


def test_a_height_the_main_map_gives_otherwise_is_listed_and_taken_with_a_button(window):
    """Colonie Hill: imported at 698, set to 286 on the main map and synced.
    The import keeps the square's and lists it; the button takes 286, Ctrl+Z
    puts 698 back, and the row follows."""
    w = window
    sq = w.working_set.squares[NORTH]
    east = w.working_set.squares[SquareName(126, -23)]
    contoured(w, SquareName(126, -23), wid=-7002)
    importing(w, answer((501, 125.5, -22.5, {'natural': 'peak', 'name': 'Colonie Hill', 'ele': '698'}),
                        (502, 125.6, -22.4, {'natural': 'saddle', 'ele': '300'}),
                        (505, 126.5, -22.5, {'natural': 'peak', 'ele': '200'})))
    importing(w, answer((501, 125.5, -22.5, {'natural': 'peak', 'name': 'Colonie Hill', 'ele': '286'}),
                        (502, 125.6, -22.4, {'natural': 'saddle', 'ele': '310'}),
                        (505, 126.5, -22.5, {'natural': 'peak', 'ele': '210'})))
    assert sq.nodes[501].tags['ele'] == '698' and sq.nodes[502].tags['ele'] == '300'
    assert east.nodes[505].tags['ele'] == '200'
    assert "3 the main map gives another height, the square's kept" in w.statusBar().currentMessage()
    dock = w.gone_dock
    assert dock.isVisible()
    rows = differs_rows(dock)
    assert [r.text(0) for r in rows] == ['peak "Colonie Hill" - 698 m here, 286 m on the main map',
                                         'saddle 502 - 300 m here, 310 m on the main map',
                                         'peak 505 - 200 m here, 210 m on the main map']
    assert not dock.take_btn.isEnabled() and dock.take_all_btn.text() == "Take the main map's for all 3"
    dock.tree.setCurrentItem(rows[0])
    assert w.editor.selection.node == 501 and "the button takes the main map's" in w.statusBar().currentMessage()
    dock.take_btn.click()
    assert sq.nodes[501].tags['ele'] == '286' and sq.nodes[502].tags['ele'] == '300'
    assert rows[0].font(0).strikeOut() and dock.take_all_btn.text() == "Take the main map's for all 2"
    w.editor.undo()
    assert sq.nodes[501].tags['ele'] == '698' and not rows[0].font(0).strikeOut()
    dock.take_all_btn.click()
    assert (sq.nodes[501].tags['ele'], sq.nodes[502].tags['ele'], east.nodes[505].tags['ele']) == \
        ('286', '310', '210')
    assert not dock.take_all_btn.isEnabled()
    w.editor.undo()
    assert (sq.nodes[501].tags['ele'], sq.nodes[502].tags['ele'], east.nodes[505].tags['ele']) == \
        ('698', '300', '200'), 'all of them, across squares, one step'
