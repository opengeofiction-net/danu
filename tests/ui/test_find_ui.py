"""Edit › Find element: an id typed, the element selected and brought into view."""

import pytest

pytest.importorskip('PySide6')

from danu.core.square import Member, Node, Relation, Way

# from the square's south-west corner: in it, and far from where the window opened
AT = (0.9, 0.9)


def place(w):
    """A contour, a spot height and a lake relation, far from where the
    window opened, in the first open square."""
    sq = w.working_set.squares[sorted(w.working_set.squares, key=str)[0]]
    lon, lat = sq.name.lon + AT[0], sq.name.lat + AT[1]
    for i, (dx, dy) in enumerate(((0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01))):
        sq.nodes[-8100 - i] = Node(id=-8100 - i, lon=lon + dx, lat=lat + dy)
    sq.ways[-8001] = Way(id=-8001, refs=[-8100, -8101, -8102, -8103, -8100], tags={'ele': '40'})
    sq.nodes[-8200] = Node(id=-8200, lon=lon - 0.02, lat=lat - 0.02, tags={'ele': '55'})
    sq.relations[-8300] = Relation(id=-8300, members=[Member('way', -8001, 'outer')],
                                   tags={'natural': 'water', 'type': 'multipolygon'})
    return sq


def finding(w, text):
    w.ask_text = lambda title, label, given: (text, True)
    w.edit_actions['edit.find'].trigger()
    return w.statusBar().currentMessage()


def test_a_way_is_selected_and_shown(window):
    w = window
    sq = place(w)
    said = finding(w, 'w-8001')
    assert said.startswith(f'found way -8001 in {sq.name}'), said
    sel = w.editor.selection
    assert sel.square is sq and sel.way is sq.ways[-8001] and sel.node is None
    lon, lat = w.map.center_lonlat()
    want = (sq.name.lon + AT[0] + 0.005, sq.name.lat + AT[1] + 0.005)
    assert abs(lon - want[0]) < 0.01 and abs(lat - want[1]) < 0.01, f'not brought into view: {lon, lat}'


def test_a_vertex_comes_with_its_way_and_a_spot_height_with_none(window):
    w = window
    sq = place(w)
    finding(w, 'n-8102')
    sel = w.editor.selection
    assert sel.way is sq.ways[-8001] and sel.node == -8102
    assert 'a node of way -8001' in w.statusBar().currentMessage()
    finding(w, 'node/-8200')
    sel = w.editor.selection
    assert sel.way is None and sel.node == -8200 and sel.spot


def test_a_relation_is_selected_as_itself(window):
    w = window
    sq = place(w)
    finding(w, 'r-8300')
    sel = w.editor.selection
    assert sel.relation is sq.relations[-8300] and sel.way is None


def test_what_is_not_there_or_not_an_id_is_said_and_changes_nothing(window):
    w = window
    place(w)
    finding(w, 'w-8001')
    before = w.editor.selection
    assert finding(w, 'w424242') == 'way 424242 is not in the open squares'
    assert 'not an element' in finding(w, 'hello')
    assert w.editor.selection is before


def test_the_key_and_the_last_id_offered_again(window):
    w = window
    place(w)
    assert w.edit_actions['edit.find'].shortcut().toString() == 'Ctrl+F'
    finding(w, 'w-8001')
    offered = []
    w.ask_text = lambda title, label, given: (offered.append(given), ('', False))[1]
    w.edit_actions['edit.find'].trigger()
    assert offered == ['w-8001']
