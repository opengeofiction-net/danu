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
