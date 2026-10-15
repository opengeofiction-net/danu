"""The theme (J5c): the desktop's, light or dark, and what is drawn in it."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from danu.ui import theme
from danu.ui.mapcontrols import ICON
from danu.ui.preferences import PreferencesDialog
from danu.ui.settings import Settings

WINDOW = QPalette.ColorRole.Window


@pytest.fixture
def app(qapp):
    """The application, its palette put back after: it is the whole suite's."""
    yield qapp
    theme.apply(qapp, 'auto')


def ink(drawn) -> str:
    """The colour an icon or a pixmap is drawn in: its most opaque pixel's."""
    img = (drawn.pixmap(ICON, ICON) if hasattr(drawn, 'availableSizes') else drawn).toImage()
    best = max(((img.pixelColor(x, y)) for x in range(img.width()) for y in range(img.height())),
               key=lambda c: c.alpha())
    return best.name()


def test_dark_and_light_whatever_the_platform_will_do(app):
    desktop = app.palette().color(WINDOW).name()
    theme.apply(app, 'dark')
    assert app.palette().color(WINDOW).name() == '#353535'
    assert app.palette().color(QPalette.ColorRole.WindowText).name() == '#f0f0f0'
    theme.apply(app, 'light')
    assert app.palette().color(WINDOW).name() == '#efefef'
    theme.apply(app, 'auto')
    assert app.palette().color(WINDOW).name() == desktop


def test_where_the_platform_gives_the_scheme_no_palette_is_set(app, monkeypatch):
    """As GNOME's theme does: Qt's own palette, the request honoured."""
    hints = app.styleHints()
    asked = []
    monkeypatch.setattr(type(hints), 'setColorScheme', lambda self, s: asked.append(s))
    monkeypatch.setattr(type(hints), 'colorScheme', lambda self: asked[-1])
    set_ = []
    monkeypatch.setattr(QApplication, 'setPalette', staticmethod(lambda p: set_.append(p)))
    assert theme.apply(app, 'dark') is True
    assert asked == [theme.SCHEMES['dark']]
    assert [p.resolveMask() for p in set_] == [0], 'a palette set over what Qt gave'


def test_the_dark_palette_has_every_role_qt_draws_with():
    p = theme.palette('dark')
    for role in QPalette.ColorRole:
        if role in (QPalette.ColorRole.NColorRoles, QPalette.ColorRole.NoRole):
            continue
        assert p.isBrushSet(QPalette.ColorGroup.Active, role), role
        assert p.isBrushSet(QPalette.ColorGroup.Disabled, role), role


def test_a_theme_the_ini_does_not_know_is_the_desktops(tmp_path):
    s = Settings(tmp_path / 'danu.ini')
    assert s.theme == 'auto'
    s.q.setValue('appearance/theme', 'purple')
    assert s.theme == 'auto'
    s.theme = 'dark'
    assert Settings(tmp_path / 'danu.ini').theme == 'dark'


def test_chosen_in_the_preferences_it_holds_at_once_icons_and_all(window, app, qtbot):
    assert window.settings.theme == 'auto'
    before = ink(window.controls.draw.icon())
    dlg = PreferencesDialog(window.settings, window.action_labels(), window)
    dlg.theme.setCurrentIndex(dlg.theme.findData('dark'))
    dlg.accept()
    window.apply_settings()
    assert window.settings.theme == 'dark'
    assert app.palette().color(WINDOW).name() == '#353535'
    # the widgets told of it as the event loop runs
    qtbot.waitUntil(lambda: ink(window.controls.draw.icon()) == '#f0f0f0', timeout=2000)
    assert before != '#f0f0f0'
    assert ink(window.controls.layers.icon()) == '#f0f0f0'
    # the elevation panel's "i", drawn in the text colour too
    assert ink(window.elevation_panel.keys.pixmap()) == '#f0f0f0'


def test_the_preferences_offer_the_three(window):
    dlg = PreferencesDialog(window.settings, window.action_labels(), window)
    assert [dlg.theme.itemText(i) for i in range(dlg.theme.count())] == \
        ['Follow the desktop', 'Light', 'Dark']
    assert dlg.theme.currentData() == 'auto'
