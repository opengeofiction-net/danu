"""The selection panel - what is selected, and its elevation, editable.

Only `ele` is editable. A contour can be re-levelled at last; a spot height's
value changed without deleting it; water levelled by the rules L follows.
Each edit is one step on the history, and the panel follows undo and redo.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from danu.core import edits
from danu.core.square import Member, Node, Relation, SquareName, Way
from danu.ui.tools import Selection
from danu.ui.water import Answer
from danu.water import overpass

HERE = SquareName(125, -24)
NORTH = SquareName(125, -23)


@pytest.fixture
def w(window):
    """The window with water in the blank square to the north: a river, a
    lake as a relation, and a river area."""
    water = overpass.Water()
    for i, lon in enumerate((125.30, 125.32, 125.34), 1):
        water.nodes[i] = Node(id=i, lon=lon, lat=-22.70)
    water.ways[100] = Way(id=100, refs=[1, 2, 3], tags={'waterway': 'river', 'name': 'Bosco'})
    for base, lon in ((10, 125.50), (30, 125.70)):
        for k, (dx, dy) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
            water.nodes[base + k] = Node(id=base + k, lon=lon + dx * 0.03, lat=-22.5 + dy * 0.03)
    water.ways[200] = Way(id=200, refs=[10, 11, 12, 13, 10])
    water.relations[300] = Relation(id=300, tags={'natural': 'water', 'water': 'lake',
                                                  'name': 'Kinser', 'source': 'survey'},
                                    members=[Member('way', 200, 'outer')])
    water.ways[500] = Way(id=500, refs=[30, 31, 32, 33, 30], tags={'waterway': 'riverbank'})
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways),
                                  frozenset(water.relations)), window.working_set)
    return window


def contour(w):
    sq = w.working_set.squares[HERE]
    way = next(x for x in sq.ways.values() if x.ele is not None)
    return sq, way


def type_in(w, text):
    """As a mapper does: focus, select what is there, type, Enter."""
    f = w.selection_panel.ele
    f.setFocus()
    f.selectAll()
    QTest.keyClick(f, Qt.Key.Key_Backspace)     # selecting is not clearing
    QTest.keyClicks(f, text)
    QTest.keyClick(f, Qt.Key.Key_Return)


# ------------------------------------------------------------------ showing

def test_nothing_selected(w):
    w.editor.selection = None
    p = w.selection_panel
    assert p.kind.text() == 'Nothing selected' and not p.ele.isEnabled()


def test_a_click_on_the_map_reaches_the_panel(w):
    """Through the selection's own signal - every one of the places that set
    the selection says so, without each remembering to."""
    sq, way = contour(w)
    n = sq.nodes[way.refs[len(way.refs) // 2]]
    w.map.set_zoom(15)
    w.map.center_on_lonlat(n.lon, n.lat)
    pos = w.map.viewport().rect().center()
    ev = lambda t, b: QMouseEvent(t, QPointF(pos), w.map.viewport().mapToGlobal(pos),  # noqa: E731
                                  Qt.MouseButton.LeftButton, b, Qt.KeyboardModifier.ShiftModifier)
    w.map.mousePressEvent(ev(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))
    assert w.editor.selection is not None and w.editor.selection.way is way
    assert w.selection_panel.kind.text() == 'contour'
    assert w.selection_panel.ele.text() == f'{way.ele:g}'


def test_name_and_tags_are_shown_and_not_editable(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, None, relation=sq.relations[300])
    p = w.selection_panel
    assert p.name.text() == 'Kinser' and 'source=survey' in p.tags.text()
    assert isinstance(p.name, QLabel) and isinstance(p.tags, QLabel), 'only ele is editable'
    assert 'name=' not in p.tags.text() and 'ele=' not in p.tags.text()


# ---------------------------------------------------------- contours, at last

def test_a_contour_is_re_levelled_and_ctrl_z_takes_it_back(w):
    """The edit there was no way to make before."""
    sq, way = contour(w)
    was = way.tags['ele']
    w.editor.selection = Selection(sq, way)
    type_in(w, '123')
    assert sq.ways[way.id].tags['ele'] == '123'
    assert w.selection_panel.ele.text() == '123'
    w.editor.undo()
    assert sq.ways[way.id].tags['ele'] == was
    assert w.selection_panel.ele.text() == f'{float(was):g}', 'the panel did not follow the undo'


def test_a_node_of_a_contour_is_the_contour(w):
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way, way.refs[1])
    assert w.selection_panel.kind.text() == 'contour'
    assert f'node {way.refs[1]}' in w.selection_panel.where.text()
    type_in(w, '321')
    assert sq.ways[way.id].tags['ele'] == '321'
    assert 'ele' not in sq.nodes[way.refs[1]].tags, 'the level went on the node, not the contour'


def test_a_contour_cannot_be_left_without_an_elevation(w):
    sq, way = contour(w)
    was = way.tags['ele']
    w.editor.selection = Selection(sq, way)
    type_in(w, '')
    assert sq.ways[way.id].tags['ele'] == was
    assert 'not a contour' in w.statusBar().currentMessage()


# --------------------------------------------------------------- spot heights

def test_a_spot_heights_value_changes_without_deleting_it(w):
    sq = w.working_set.squares[HERE]
    nid = w.editor.history.alloc(sq).take()
    w.editor.do(sq, edits.AddNode(nid, (125.5, -23.5), {'ele': '400'}))
    w.editor.selection = Selection(sq, None, nid)
    assert w.selection_panel.kind.text() == 'spot height'
    type_in(w, '412.5')
    assert sq.nodes[nid].tags['ele'] == '412.5'
    type_in(w, '')
    assert sq.nodes[nid].tags['ele'] == '412.5', 'a spot height was left with no value'


# ----------------------------------------------------------------------- water

def test_a_rivers_point_is_levelled_and_cleared(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[100], 2)
    assert w.selection_panel.kind.text() == 'point on a river'
    type_in(w, '42')
    assert sq.nodes[2].tags.get('ele') == '42'
    type_in(w, '')
    assert 'ele' not in sq.nodes[2].tags


def test_a_river_whole_cannot_take_one_level_and_says_why(w):
    sq = w.working_set.squares[NORTH]
    sq.nodes[2].tags['ele'] = '40'
    w.editor.selection = Selection(sq, sq.ways[100])
    p = w.selection_panel
    assert not p.ele.isEnabled()
    assert 'descends' in p.why.text() and p.why.isVisible(), 'the reason was not said'
    assert 'levels at 1 of 3 points' in p.where.text()


def test_a_lakes_level_and_a_river_area_refused(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, None, relation=sq.relations[300])
    type_in(w, '120')
    assert sq.relations[300].tags.get('ele') == '120'
    w.editor.selection = Selection(sq, sq.ways[500])
    assert not w.selection_panel.ele.isEnabled(), 'a river area offered one level'
    assert 'R27' in w.selection_panel.why.text()
    w.editor.selection = Selection(sq, None, relation=sq.relations[300])
    assert not w.selection_panel.why.isVisible(), 'a reason was shown for an editable lake'


# -------------------------------------------------------------------- the field

def test_not_a_number_is_refused_and_the_field_put_back(w):
    sq, way = contour(w)
    was = way.tags['ele']
    w.editor.selection = Selection(sq, way)
    type_in(w, 'abc')
    assert sq.ways[way.id].tags['ele'] == was
    assert w.selection_panel.ele.text() == f'{float(was):g}'
    assert 'not an elevation' in w.statusBar().currentMessage()


def test_the_same_value_again_is_no_step(w):
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    before = w.editor.history.describe_undo()
    depth = len(w.editor.history._done)
    type_in(w, f'{way.ele:g}')
    assert len(w.editor.history._done) == depth, 'an unchanged value went on the history'
    assert w.editor.history.describe_undo() == before


def test_escape_puts_the_field_back_and_hands_the_keys_to_the_map(w):
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    f = w.selection_panel.ele
    f.setFocus()
    f.selectAll()
    QTest.keyClicks(f, '999')
    QTest.keyClick(f, Qt.Key.Key_Escape)
    assert f.text() == f'{way.ele:g}'
    assert sq.ways[way.id].tags['ele'] != '999'
    assert not f.hasFocus(), 'the field kept the keys'


def test_enter_hands_the_keys_back_to_the_map(w):
    """The tools are keys. A mapper who typed a level should not then find
    Q typed into the field."""
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    type_in(w, '250')
    assert not w.selection_panel.ele.hasFocus()


def test_l_still_sets_only_water(w):
    """The panel re-levels a contour; L, as its menu says, is for water."""
    sq, way = contour(w)
    was = way.tags['ele']
    w.editor.selection = Selection(sq, way)
    w.elevation.set(777.0)
    w.editor.set_level()
    assert sq.ways[way.id].tags['ele'] == was
    assert 'for water' in w.statusBar().currentMessage()


def test_a_spot_height_gone_since_it_was_selected_says_so(w):
    """The panel can be showing a spot height whose node an edit elsewhere has
    since removed; Enter then says so rather than raising."""
    sq = w.working_set.squares[HERE]
    nid = w.editor.history.alloc(sq).take()
    w.editor.do(sq, edits.AddNode(nid, (125.5, -23.5), {'ele': '400'}))
    w.editor.selection = Selection(sq, None, nid)
    del sq.nodes[nid]
    assert w.editor.set_ele(410.0) is False
    assert 'already gone' in w.statusBar().currentMessage()
    assert w.editor.selection is None


def test_l_at_the_level_a_lake_already_has_is_no_step(w):
    """L at a lake already at the active elevation used to push a step that
    changed nothing, and Ctrl+Z then undid nothing visible."""
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, None, relation=sq.relations[300])
    w.elevation.set(120.0)
    w.editor.set_level()
    depth = len(w.editor.history._done)
    w.editor.set_level()
    assert len(w.editor.history._done) == depth, 'the same level again went on the history'
    assert 'already' in w.statusBar().currentMessage()


# ------------------------------------------------------------ copying, H6c

def copied():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.clipboard().text()


def right_click(label):
    """The actions a right click on ``label`` offers, by their text."""
    assert label.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu
    return {a.text(): a for a in label.actions()}


def test_the_name_is_copied_from_a_right_click(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[100])
    menu = right_click(w.selection_panel.name)
    assert list(menu) == ['Copy name'] and menu['Copy name'].isEnabled()
    menu['Copy name'].trigger()
    assert copied() == 'Bosco'


def test_no_name_nothing_to_copy(w):
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    assert not right_click(w.selection_panel.name)['Copy name'].isEnabled()


def test_an_upstream_way_is_copied_as_its_id_or_its_page(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[100])
    menu = right_click(w.selection_panel.where)
    assert list(menu) == ['Copy ID', 'Copy URL'] and all(a.isEnabled() for a in menu.values())
    menu['Copy ID'].trigger()
    assert copied() == 'w100'
    menu['Copy URL'].trigger()
    assert copied() == 'https://opengeofiction.net/way/100'


def test_a_ring_of_a_lake_copies_the_lake(w):
    """The relation ahead of the way: the lake is what a mapper means."""
    sq = w.working_set.squares[NORTH]
    for sel in (Selection(sq, sq.ways[200]), Selection(sq, None, relation=sq.relations[300])):
        w.editor.selection = sel
        assert w.selection_panel.info.osm == ('relation', 300)
    right_click(w.selection_panel.where)['Copy ID'].trigger()
    assert copied() == 'r300'


def test_a_point_on_a_river_copies_the_node(w):
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, sq.ways[100], 2)
    assert w.selection_panel.info.osm == ('node', 2)


def test_a_spot_height_copies_its_node(w):
    sq = w.working_set.squares[NORTH]
    sq.nodes[7] = Node(id=7, lon=125.6, lat=-22.6, tags={'ele': '300'})
    w.editor.selection = Selection(sq, None, 7)
    assert w.selection_panel.info.osm == ('node', 7)


def test_a_local_contours_id_is_copied_but_has_no_page(w):
    """For a message or an issue: w-49942840 names it, though it has no
    page on the server."""
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    assert way.id < 0 and w.selection_panel.info.osm == ('way', way.id)
    menu = right_click(w.selection_panel.where)
    assert menu['Copy ID'].isEnabled() and not menu['Copy URL'].isEnabled()
    menu['Copy ID'].trigger()
    assert copied() == f'w{way.id}'


def test_a_contours_node_chosen_copies_the_node_and_the_line_the_way(w):
    """Where names the node last: Copy ID gives it, not the way it is on."""
    sq, way = contour(w)
    sq.ways[4242] = Way(id=4242, refs=list(way.refs), tags=dict(way.tags))
    w.editor.selection = Selection(sq, sq.ways[4242], way.refs[1])
    assert w.selection_panel.info.osm == ('node', way.refs[1])
    assert f'node {way.refs[1]}' in w.selection_panel.info.where
    menu = right_click(w.selection_panel.where)
    menu['Copy ID'].trigger()
    assert copied() == f'n{way.refs[1]}'
    w.editor.selection = Selection(sq, sq.ways[4242])
    assert w.selection_panel.info.osm == ('way', 4242)


def test_the_server_is_the_inis(w, tmp_path):
    from danu.ui.selection_panel import osm_ids
    from danu.ui.settings import Settings
    s = Settings(tmp_path / 'other.ini')
    assert s.server_url == 'https://opengeofiction.net'
    s.q.setValue('ogf/server', 'https://test.example/')
    assert osm_ids(('way', 5), s.server_url) == ['w5', 'https://test.example/way/5']


def test_the_elevation_has_its_unit_beside_it_not_in_it(w):
    p = w.selection_panel
    assert p.ele.parentWidget().unit.text() == 'm'
    assert p.pull_back.suffix() == '' and p.pull_back.parentWidget().unit.text() == 'm'


def test_only_a_water_relation_holding_the_way_comes_first(w):
    """A route through a river is not the river; and a node of the
    relation's that has the way's number is not the way."""
    sq = w.working_set.squares[NORTH]
    sq.relations[600] = Relation(id=600, tags={'type': 'route', 'route': 'canoe'},
                                 members=[Member('way', 100)])
    sq.relations[700] = Relation(id=700, tags={'natural': 'water', 'water': 'river'},
                                 members=[Member('node', 100)])
    w.editor.selection = Selection(sq, sq.ways[100])
    assert w.selection_panel.info.osm == ('way', 100)



def test_choosing_does_not_move_the_map(w):
    """The panel is as wide from the start as a lake's buttons make it."""
    from PySide6.QtWidgets import QApplication
    sq = w.working_set.squares[NORTH]
    QApplication.processEvents()
    widths = set()
    for sel in (None, Selection(sq, None, relation=sq.relations[300]), Selection(sq, sq.ways[100]),
                Selection(sq, sq.ways[100], 2), contour(w) and Selection(*contour(w)), None):
        w.editor.selection = sel
        QApplication.processEvents()
        widths.add(w.map.viewport().width())
        p = w.selection_panel
        room = p.widget().viewport().width()
        for b in (p.grade_btn, p.network_btn, p.flatten_btn):
            if b.isVisible():
                assert b.mapTo(p.widget().widget(), b.rect().topRight()).x() < room, 'a button cut off'
    assert len(widths) == 1, widths


# ---------------------------------------------------------------- coastlines

def sea_level(w):
    """A 0 m line in the fixture's square, drawn through the history."""
    sq = w.working_set.squares[HERE]
    alloc = w.editor.history.alloc(sq)
    ids = [alloc.take() for _ in range(3)]
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, ids, [(125.2 + 0.05 * i, -23.9) for i in range(3)], {'ele': '0'}))
    return sq, sq.ways[wid]


def test_a_sea_level_line_is_made_the_coastline_from_the_panel_and_turned_round(w):
    p = w.selection_panel
    sq, way = contour(w)
    w.editor.selection = Selection(sq, way)
    assert way.ele != 0 and p.coast_btn.isHidden(), 'offered on a line that is not at sea level'
    sq, way = sea_level(w)
    refs = list(way.refs)
    w.editor.selection = Selection(sq, way)
    assert not p.coast_btn.isHidden() and not p.coast_btn.isChecked() and p.reverse_btn.isHidden()
    p.coast_btn.click()
    assert way.tags == {'ele': '0', 'natural': 'coastline'}
    assert p.kind.text() == 'coastline' and p.coast_btn.isChecked() and not p.reverse_btn.isHidden()
    assert (HERE, way.id) in w.contours.coasts, 'its direction is not drawn'
    p.reverse_btn.click()
    assert sq.ways[way.id].refs == refs[::-1]
    w.edit_actions['edit.reverse_coastline'].trigger()          # R, from the menu
    assert sq.ways[way.id].refs == refs
    p.coast_btn.click()                                           # and a plain 0 m contour again
    assert way.tags == {'ele': '0'} and p.kind.text() == 'contour' and (HERE, way.id) not in w.contours.coasts
    w.editor.undo()
    assert way.tags['natural'] == 'coastline', 'one step each'


def test_reverse_on_anything_but_a_coastline_says_why(w):
    sq, way = sea_level(w)
    w.editor.selection = Selection(sq, way)
    refs = list(way.refs)
    w.edit_actions['edit.reverse_coastline'].trigger()
    assert way.refs == refs
    assert 'only a coastline has a direction that matters' in w.statusBar().currentMessage()


def test_mark_in_the_menu_makes_the_line_selected_a_coastline_and_takes_it_off_again(w):
    sq, way = sea_level(w)
    w.editor.selection = Selection(sq, way)
    mark = w.edit_actions['edit.mark_coastline']
    mark.trigger()
    assert way.tags == {'ele': '0', 'natural': 'coastline'} and w.selection_panel.coast_btn.isChecked()
    mark.trigger()
    assert way.tags == {'ele': '0'} and not w.selection_panel.coast_btn.isChecked()
    sq, contour_ = contour(w)
    w.editor.selection = Selection(sq, contour_)
    mark.trigger()
    assert 'natural' not in contour_.tags
    assert 'only a sea-level line' in w.statusBar().currentMessage()
    w.editor.selection = None
    mark.trigger()
    assert 'choose a 0 m line' in w.statusBar().currentMessage()
