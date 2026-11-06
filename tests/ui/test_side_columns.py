"""The side panels narrow enough to leave the map most of the window: the
actions drawn, not named, their keys in the tooltips (the left column was
as wide as "Grade the river network (Shift+G)", the right as a row of five
named zone buttons)."""

import sys

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QPushButton, QTabBar, QWidget

from danu.ui.icons import PaintedButton


@pytest.mark.skipif(sys.platform == 'win32', reason="offscreen text there lays out about twice as wide")
def test_the_columns_leave_the_map_most_of_the_window(window):
    w = window
    for d in (w.elevation_panel, w.selection_panel, w.surface_panel, w.zones_dock):
        assert d.minimumSizeHint().width() <= 220, d.windowTitle()
    assert w.map.viewport().width() >= 0.6 * QWidget.width(w)


def test_the_actions_are_drawn_their_keys_in_the_tooltip(window):
    p, z = window.selection_panel, window.zones_dock
    assert not p.findChildren(QPushButton) and not z.findChildren(QPushButton)
    for b in (*p.action_btns, p.accept_btn, p.drop_btn, z.reload, z.new, z.edit, z.split, z.active):
        assert isinstance(b, PaintedButton) and not b.icon().isNull() and not b.text() and b.toolTip()
    assert p.grade_btn.toolTip() == 'Grade from the contours (G)'
    assert p.network_btn.toolTip() == 'Grade the river network (Shift+G)'


def test_a_key_rebound_is_said_in_the_tooltip(window):
    window.settings.set_key('edit.flatten', 'Ctrl+L')
    window.apply_settings()
    assert window.selection_panel.flatten_btn.toolTip() == 'Flatten the lake (Ctrl+L)'


def test_an_icon_is_drawn_again_in_a_palette_changed(window):
    b = window.selection_panel.reverse_btn
    pal = QPalette(b.palette())
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(255, 0, 0))
    b.setPalette(pal)
    img = b.icon().pixmap(18, 18).toImage()
    reds = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())
            if img.pixelColor(x, y).alpha() == 255]
    assert reds and all(c.red() == 255 and c.green() == 0 for c in reds)


def test_reset_panels_narrows_the_columns_again(window, qtbot):
    w = window
    narrow = w.map.viewport().width()
    w.resizeDocks([w.surface_panel], [500], Qt.Orientation.Horizontal)
    qtbot.waitUntil(lambda: w.map.viewport().width() < narrow - 100, timeout=2000)
    w.reset_panels()
    qtbot.waitUntil(lambda: w.map.viewport().width() >= narrow - 2, timeout=2000)


def test_the_tabs_are_the_panels_icons_their_names_the_tooltips(window, qtbot):
    w = window
    w.gone_dock.show()
    w.checks_dock.show()
    qtbot.wait(50)
    bars = [b for b in w.findChildren(QTabBar) if b.isVisible()]
    assert bars
    for bar in bars:
        for i in range(bar.count()):
            assert not bar.tabIcon(i).isNull() and bar.tabToolTip(i) == bar.tabText(i)
        # no room made for a name: "Gone from upstream" as wide as "Zones"
        assert len({bar.tabRect(i).width() for i in range(bar.count())}) == 1


@pytest.mark.skipif(sys.platform == 'win32', reason="offscreen text there lays out about twice as wide")
def test_gone_from_upstream_with_its_buttons_is_as_narrow_as_the_rest(window):
    g = window.gone_dock
    g.stack.setCurrentWidget(g.listed)
    for b in (g.take_btn, g.take_all_btn):
        b.setVisible(True)
    g.take_all_btn.setText('Take all 128')
    assert g.minimumSizeHint().width() <= 220


def test_a_short_column_scrolls_the_surface_panel_its_status_line_whole(window, qtbot):
    w = window
    st = w.surface_panel.status
    st.setText('no surface built for this set yet, and a second line of it to wrap onto')
    w.resize(QWidget.width(w), 520)
    qtbot.waitUntil(lambda: QWidget.height(w) <= 540, timeout=2000)
    qtbot.waitUntil(lambda: st.height() >= st.heightForWidth(st.width()), timeout=2000)
