"""The side panels narrow enough to leave the map most of the window: the
actions drawn, not named, their keys in the tooltips (the left column was
as wide as "Grade the river network (Shift+G)", the right as a row of five
named zone buttons)."""

import sys

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QPushButton, QTabBar, QWidget

from danu.ui.icons import PaintedButton


@pytest.mark.skipif(sys.platform == 'win32', reason="offscreen text there lays out about twice as wide")
def test_the_columns_leave_the_map_most_of_the_window(window):
    w = window
    for d in (w.elevation_panel, w.selection_panel, w.surface_panel, w.zones_dock):
        assert d.minimumSizeHint().width() <= 240, d.windowTitle()      # macOS's fonts: 234
    assert w.map.viewport().width() >= 0.55 * QWidget.width(w)     # 63% on Linux, 59% on macOS


def test_the_actions_are_drawn_their_keys_in_the_tooltip(window):
    p, z = window.selection_panel, window.zones_dock
    assert not p.findChildren(QPushButton) and not z.findChildren(QPushButton)
    for b in (*p.action_btns, p.accept_btn, p.drop_btn, z.reload, z.new, z.edit, z.split, z.active):
        assert isinstance(b, PaintedButton) and not b.icon().isNull() and not b.text() and b.toolTip()
    assert p.grade_btn.toolTip() == 'Grade river from contours (G)'
    assert p.network_btn.toolTip() == 'Grade river network (Shift+G)'


def test_a_key_rebound_is_said_in_the_tooltip(window):
    window.settings.set_key('edit.flatten', 'Ctrl+L')
    window.apply_settings()
    assert window.selection_panel.flatten_btn.toolTip() == 'Flatten lake (Ctrl+L)'


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
    assert bars and sum(b.count() for b in bars) >= 4
    for bar in bars:
        for i in range(bar.count()):
            assert not bar.tabIcon(i).isNull()
            # what the panel is for, beginning with its name
            assert bar.tabToolTip(i).startswith(bar.tabText(i) + ': ')
        # no room made for a name: "Gone from upstream" as wide as "Zones"
        assert len({bar.tabRect(i).width() for i in range(bar.count())}) == 1


@pytest.mark.skipif(sys.platform == 'win32', reason="offscreen text there lays out about twice as wide")
def test_gone_from_upstream_with_its_buttons_is_as_narrow_as_the_rest(window):
    g = window.gone_dock
    g.stack.setCurrentWidget(g.listed)
    for b in (g.take_btn, g.take_all_btn):
        b.setVisible(True)
    g.take_all_btn.setText('Take all 128')
    assert g.minimumSizeHint().width() <= 240


def test_a_short_column_scrolls_the_surface_panel_its_status_line_whole(window, qtbot):
    w = window
    st = w.surface_panel.status
    st.setText('no surface built for this set yet, and a second line of it to wrap onto')
    w.resize(QWidget.width(w), 520)
    qtbot.waitUntil(lambda: QWidget.height(w) <= 540, timeout=2000)
    qtbot.waitUntil(lambda: st.height() >= st.heightForWidth(st.width()), timeout=2000)


def test_a_tab_made_without_its_icon_is_given_it(window, qtbot):
    # as Qt 6.8 makes a tab for a panel shown later: no icon
    w = window
    w.gone_dock.show()
    qtbot.wait(50)
    bars = [b for b in w.findChildren(QTabBar) if b.count()]
    for bar in bars:
        for i in range(bar.count()):
            bar.setTabIcon(i, QIcon())
    w.checks_dock.show()
    qtbot.waitUntil(lambda: all(not b.tabIcon(i).isNull() for b in bars for i in range(b.count())), timeout=2000)


def test_the_tab_shown_is_filled_with_the_highlight(window, qtbot):
    # as the map's tool in use is: the style's own selected tab was a shade
    # off the rest, hard to tell among icons
    w = window
    w.checks_dock.show()
    w.checks_dock.raise_()
    qtbot.wait(50)
    bar = next(b for b in w.findChildren(QTabBar) if b.isVisible() and b.count() > 1)
    hl = bar.palette().color(QPalette.ColorRole.Highlight).rgb()
    img = bar.grab().toImage()

    def lit(i):
        r = bar.tabRect(i)
        return sum(img.pixelColor(x, y).rgb() == hl for x in range(r.left(), r.right())
                   for y in range(r.top(), r.bottom()))

    shown = bar.currentIndex()
    assert lit(shown) > 0.3 * bar.tabRect(shown).width() * bar.tabRect(shown).height()
    assert all(lit(i) == 0 for i in range(bar.count()) if i != shown)


def test_hovering_a_tab_shows_its_tooltip(window, qtbot):
    # the window's tab bar shows one only when it is too narrow for the
    # names, and swallowed the request for tabs drawn as icons
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication, QToolTip
    w = window
    w.checks_dock.show()
    qtbot.wait(50)
    bar = next(b for b in w.findChildren(QTabBar) if b.isVisible() and b.count() > 1)
    p = bar.tabRect(1).center()
    QApplication.sendEvent(bar, QHelpEvent(QEvent.Type.ToolTip, p, bar.mapToGlobal(p)))
    qtbot.waitUntil(lambda: QToolTip.text() == bar.tabToolTip(1), timeout=2000)
    QToolTip.hideText()
