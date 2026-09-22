"""Zoom and the tools, on the map."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent                                     # noqa: E402

from danu.ui import mercator as m                                     # noqa: E402


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
    w.editor.set_tool('select')                           # and the other way round
    assert c.select.isChecked() and not c.draw.isChecked()


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
    for b in (w.controls.zoom_in, w.controls.zoom_out, w.controls.select, w.controls.draw):
        assert b.focusPolicy().name == 'NoFocus'
