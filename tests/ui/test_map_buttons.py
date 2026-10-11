"""The map's buttons (H6b): the layers from a popup, the tool in use filled
with the highlight, and undo, redo, delete, split and unglue as buttons -
greyed while they have nothing to do. In the fixture's blank square to the
north."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication, QDockWidget

from danu.core import edits
from danu.core.square import SquareName
from danu.ui.layers import LayersChooser
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)
LAT = -22.70


@pytest.fixture
def board(window):
    """A 100 m line, and a 125 m V whose tip is the line's second node."""
    w = window
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    line, v = alloc.take(), alloc.take()
    w.editor.do(sq, edits.AddWay(line, [alloc.take() for _ in range(4)],
                                 [(125.30, LAT), (125.31, LAT), (125.32, LAT), (125.33, LAT)], {'ele': '100'}))
    w.editor.do(sq, edits.AddWay(v, [alloc.take() for _ in range(2)],
                                 [(125.300, LAT + 0.01), (125.305, LAT + 0.005)], {'ele': '125'}))
    w.editor.do(sq, edits.ExtendWayWithExisting(v, True, sq.ways[line].refs[1]))     # glued to the line
    w.editor.do(sq, edits.ExtendWay(v, True, alloc.take(), (125.315, LAT + 0.005)))
    w.editor.selection = None
    return w, sq, sq.ways[line]


def enabled(w):
    c = w.controls
    return {n for n, b in c.edits.items() if b.isEnabled()}


def test_the_layers_are_a_popup_on_the_map_not_a_panel(window):
    c = window.controls
    assert c.layers is not None and c.layers.menu() is not None
    held = c.layers.menu().actions()[0].defaultWidget()
    assert isinstance(held, LayersChooser) and held is window.layer_chooser
    assert not any(d.windowTitle() == 'Layers' for d in window.findChildren(QDockWidget))


def test_the_layers_popup_chooses_the_layer(window):
    c = window.layer_chooser
    c.radios[1].click()
    assert [i.isVisible() for i in window.tile_items] == [False, True, False]


def test_the_tool_in_use_is_filled_with_the_highlight(window):
    c = window.controls
    window.editor.set_tool('draw')
    QApplication.processEvents()
    hi = c.palette().color(QPalette.ColorRole.Highlight)
    img = c.draw.grab().toImage()
    assert img.pixelColor(4, img.height() // 2) == hi
    img = c.select.grab().toImage()
    assert img.pixelColor(4, img.height() // 2) != hi


def test_a_checked_tool_draws_its_icon_in_the_highlights_text_colour(window):
    c = window.controls
    lit = c.palette().color(QPalette.ColorRole.HighlightedText)
    for b in (c.select, c.draw, c.spot, c.measure, c.magnify):
        on = b.icon().pixmap(QSize(18, 18), QIcon.Mode.Normal, QIcon.State.On).toImage()
        off = b.icon().pixmap(QSize(18, 18), QIcon.Mode.Normal, QIcon.State.Off).toImage()
        assert on != off
        assert any(on.pixelColor(x, y).rgb() == lit.rgb() and on.pixelColor(x, y).alpha() == 255
                   for x in range(18) for y in range(18))


def test_nothing_selected_greys_delete_split_and_unglue(board):
    w, _sq, _line = board
    assert not enabled(w) & {'edit.delete', 'edit.split', 'edit.unglue'}


def test_the_line_alone_can_be_deleted_but_not_split_or_unglued(board):
    w, sq, line = board
    w.editor.selection = Selection(sq, line)
    assert enabled(w) >= {'edit.delete'} and not enabled(w) & {'edit.split', 'edit.unglue'}


def test_an_end_of_the_line_cannot_be_split(board):
    w, sq, line = board
    w.editor.selection = Selection(sq, line, line.refs[0])
    assert 'edit.split' not in enabled(w) and 'edit.unglue' not in enabled(w)
    w.editor.selection = Selection(sq, line, line.refs[2])
    assert 'edit.split' in enabled(w) and 'edit.unglue' not in enabled(w)


def test_a_shared_node_can_be_unglued_and_the_button_does_it(board):
    w, sq, line = board
    shared = line.refs[1]
    w.editor.selection = Selection(sq, line, shared)
    assert {'edit.split', 'edit.unglue'} <= enabled(w)
    w.controls.unglue.click()
    assert sum(shared in wy.refs for wy in sq.ways.values()) == 1
    assert 'edit.unglue' not in enabled(w), 'nothing left to unglue: the edit greys it'


def test_undo_and_redo_follow_the_history_and_the_buttons_do_them(board):
    w, sq, _line = board
    c = w.controls
    assert c.undo.isEnabled() and not c.redo.isEnabled()
    before = edits.snapshot(sq)
    c.undo.click()
    assert edits.snapshot(sq) != before and c.redo.isEnabled()
    c.redo.click()
    assert edits.snapshot(sq) == before and not c.redo.isEnabled()


def test_a_button_is_the_action_so_the_log_has_it_by_name(board):
    w, sq, line = board
    fired = []
    w.edit_actions['edit.delete'].triggered.connect(lambda: fired.append('edit.delete'))
    w.editor.selection = Selection(sq, line)
    w.controls.delete.click()
    assert fired == ['edit.delete'] and line.id not in sq.ways


def test_a_flattened_lake_is_not_split(board):
    """Its outline has an ele, the level it was flattened at, but P splits
    contours."""
    w, sq, _line = board
    alloc = w.editor.history.alloc(sq)
    lake = alloc.take()
    ring = [alloc.take() for _ in range(3)]
    w.editor.do(sq, edits.AddWay(lake, ring, [(125.30, LAT - 0.01), (125.31, LAT - 0.01), (125.31, LAT - 0.02)],
                                 {'ele': '90', 'natural': 'water'}))
    w.editor.do(sq, edits.ExtendWayWithExisting(lake, True, ring[0]))
    w.editor.selection = Selection(sq, sq.ways[lake], ring[1])
    assert sq.ways[lake].ele is not None and (sq.name, lake) in w.contours.water
    assert 'edit.split' not in enabled(w)


def test_a_spot_height_can_be_deleted_and_nothing_else(board):
    w, sq, _line = board
    alloc = w.editor.history.alloc(sq)
    spot = alloc.take()
    w.editor.do(sq, edits.AddNode(spot, (125.31, LAT - 0.01), {'ele': '140'}))
    w.editor.selection = Selection(sq, None, spot)
    assert enabled(w) & {'edit.delete', 'edit.split', 'edit.unglue'} == {'edit.delete'}


def test_a_coastline_is_not_split(board):
    """No ele: P splits contours."""
    w, sq, _line = board
    alloc = w.editor.history.alloc(sq)
    coast = alloc.take()
    w.editor.do(sq, edits.AddWay(coast, [alloc.take() for _ in range(3)],
                                 [(125.30, LAT - 0.02), (125.31, LAT - 0.02), (125.32, LAT - 0.02)],
                                 {'natural': 'coastline'}))
    w.editor.selection = Selection(sq, sq.ways[coast], sq.ways[coast].refs[1])
    assert 'edit.split' not in enabled(w)


def test_with_nothing_done_undo_and_redo_are_greyed(window):
    assert not window.controls.undo.isEnabled() and not window.controls.redo.isEnabled()


def test_an_action_applies_does_not_know_is_an_error(window):
    with pytest.raises(KeyError):
        window.editor.applies('edit.nothing')
