"""Zoom and the tools, on the map."""

import pytest

pytest.importorskip('PySide6')

from danu.ui import mercator as m


def test_the_buttons_zoom_and_switch_tools_and_follow_the_state(window):
    w = window
    c = w.controls
    assert c.parentWidget() is w.map                      # the view, not its viewport
    vp = w.map.viewport().geometry()
    assert vp.contains(c.geometry()) and c.geometry().left() < vp.left() + 40
    w.map.set_zoom(10)
    c.zoom_in.click()
    assert w.map.zoom == 11
    c.zoom_out.click()
    assert w.map.zoom == 10
    assert c.select.isChecked() and not c.draw.isChecked()
    c.draw.click()
    assert w.editor.tool == 'draw' and c.draw.isChecked() and not c.select.isChecked()
    c.spot.click()
    assert w.editor.tool == 'spot' and c.spot.isChecked() and not c.draw.isChecked()
    w.editor.set_tool('select')                           # and the other way round
    assert c.select.isChecked() and not c.draw.isChecked() and not c.spot.isChecked()


def test_the_zoom_buttons_stop_at_the_ends(window):
    w = window
    c = w.controls
    w.map.set_zoom(0)
    assert not c.zoom_out.isEnabled() and c.zoom_in.isEnabled()
    w.map.set_zoom(m.MAX_ZOOM)
    assert not c.zoom_in.isEnabled() and c.zoom_out.isEnabled()


def test_the_buttons_follow_the_window_as_it_is_resized(window):
    from PySide6.QtWidgets import QApplication
    w = window
    for size in ((1200, 800), (620, 480)):
        w.resize(*size)
        QApplication.processEvents()
        vp = w.map.viewport().geometry()
        assert vp.contains(w.controls.geometry()), (size, w.controls.geometry(), vp)


def test_the_buttons_do_not_take_the_keys_from_the_map(window):
    w = window
    for b in (w.controls.zoom_in, w.controls.zoom_out, w.controls.select,
              w.controls.draw, w.controls.spot):
        assert b.focusPolicy().name == 'NoFocus'


def test_the_tools_are_drawn_not_named(window):
    """A small icon and a tooltip, as the review asked: 'Sel' and 'Draw' had
    to be read, and 'Draw' did not fit in a square button anyway."""
    w = window
    for b, word in ((w.controls.select, 'Select'), (w.controls.draw, 'Draw'),
                    (w.controls.spot, 'Place a spot height')):
        assert b.text() == '' and not b.icon().isNull()
        assert b.toolTip().startswith(word) and '(' in b.toolTip()      # and says its key
        assert b.icon().pixmap(18, 18).size().width() == 18
    # drawn in the palette's ink, so a dark desktop does not get a dark mark
    from PySide6.QtGui import QColor
    ink = w.controls.palette().color(w.controls.palette().ColorRole.ButtonText)
    for button in (w.controls.draw, w.controls.spot):
        img = button.icon().pixmap(18, 18).toImage()
        marks = [QColor(img.pixel(x, y)) for x in range(18) for y in range(18)
                 if QColor(img.pixel(x, y)).alpha() > 128]
        assert marks, 'the icon is blank'
        assert min(abs(c.lightness() - ink.lightness()) for c in marks) < 40
    assert w.controls.zoom_in.text() == '+'                             # these read as symbols


def test_the_import_is_a_button_and_not_a_tool(window):
    """The one action in the column. It must not join the tool group: checking
    it would uncheck the tool the mapper is using, and leave it unchecked when
    the import finished."""
    w = window
    assert not w.controls.water.isCheckable()
    assert w.controls.water not in w.controls.modes.buttons()
    assert w.controls.water.text() == '' and not w.controls.water.icon().isNull()
    assert w.controls.water.toolTip().startswith('Import water')
    assert 'Ctrl+I' in w.controls.water.toolTip()

    asked = []
    w.water.request = lambda ws: asked.append(ws) or 1
    w.controls.water.click()
    assert asked == [w.working_set], 'the button did not ask for the import'
