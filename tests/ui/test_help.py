"""Help (J5b): getting started, the keys as they are set, the layers, the wiki."""

import re

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QUrl

from danu.ui import help as help_ui
from danu.ui.settings import DEFAULT_KEYS, REBUILD_KEY

from .conftest import menu


@pytest.fixture
def opened(window):
    out = []
    window.open_url = out.append
    return out


def test_help_has_the_three_pages_the_wiki_and_about(window):
    texts = [a.text().replace('&', '') for a in menu(window.menuBar(), 'Help').actions() if not a.isSeparator()]
    assert texts == ['Getting started', 'Keys', 'Layers', 'Start page', 'Danu on the OGF wiki', 'About Danu']


@pytest.mark.parametrize('name', ['getting-started', 'layers'])
def test_each_written_page_ships_with_the_package_and_opens(window, name):
    assert help_ui.page(name).startswith('# ')
    window.help_actions[name].trigger()
    w = window.help_window
    assert w.isVisible() and w.current == name
    assert help_ui.page(name).splitlines()[0][2:] in w.text.toPlainText()


def test_the_pages_link_to_each_other_and_out_to_the_wiki(window, opened):
    window.show_help('getting-started')
    w = window.help_window
    w._link(QUrl('help:layers'))
    assert w.current == 'layers'
    w._link(QUrl('help:keys'))
    assert w.current == 'keys'
    w._link(QUrl(help_ui.WIKI))
    assert opened == [help_ui.WIKI] and w.current == 'keys'


def test_the_wiki_page_is_opengeofictions_danu(window, opened):
    window.wiki_action.trigger()
    assert opened == ['https://wiki.opengeofiction.net/index.php/Help:Danu']


def test_the_keys_are_the_bindings_as_they_are_now(window):
    window.show_help('keys')
    text = window.help_window.text.toPlainText()
    assert 'Edit › Water › Grade' in text and 'Elevation › Big step up' in text
    window.settings.set_key('edit.grade', 'Ctrl+Alt+G')
    window.show_help('keys')
    # as the platform writes it: Ctrl+Alt+G, and on macOS ⌥⌘G
    shown = help_ui._key('Ctrl+Alt+G')
    assert re.search(r'Edit › Water › Grade\s+' + re.escape(shown), window.help_window.text.toPlainText())


def test_every_binding_is_on_the_keys_page():
    page = help_ui.keys({}, DEFAULT_KEYS.get)
    for name in DEFAULT_KEYS:
        assert f'| {name} |' in page, name
    assert help_ui._key(REBUILD_KEY) in page            # Ctrl+R, and on macOS ⌘R


# the keys getting-started names, and the bindings they must be
NAMED = {'A': 'tool.draw', 'Q': 'tool.select', 'Z': 'tool.spot', 'M': 'tool.measure',
         'W': 'elevation.small_up', 'S': 'elevation.small_down', '2': 'elevation.big_up',
         'X': 'elevation.big_down', 'Space': 'elevation.pick_up', 'Ctrl+S': 'file.save'}


def test_getting_started_names_the_keys_danu_ships_with():
    text = help_ui.page('getting-started')
    named = set(re.findall(r'\*\*([^*]+)\*\*', text))
    for key, action in NAMED.items():
        assert key in named, f'getting started no longer says {key}'
        assert DEFAULT_KEYS[action] == key, f'{action} is {DEFAULT_KEYS[action]} now, not {key}'
    assert 'Ctrl+R' in named and REBUILD_KEY == 'Ctrl+R'


def test_the_layers_page_names_every_way_the_surface_is_shown_and_every_base_map():
    from danu.ui.config import load_layers
    from danu.ui.surface import MODES
    text = help_ui.page('layers')
    for mode in MODES:
        assert f'**{mode}**' in text, mode
    for layer in load_layers():
        assert f'**{layer.title}**' in text, layer.title


# ------------------------------------------------------------- macOS (#194)
def test_on_macos_the_mouse_is_written_as_it_writes_it_and_the_trackpad_is_there():
    rows = dict(help_ui.mouse(mac=True))
    assert rows['⌘Wheel'] and rows['⇧⌘Wheel'] and rows['⌥Wheel'] and rows['⇧Wheel']
    assert rows['Two-finger scroll'] == 'move the map' and 'Pinch' in rows
    assert 'Two-finger scroll' not in dict(help_ui.mouse(mac=False))
    assert dict(help_ui.mouse(mac=False))['Ctrl+Shift+Wheel']


def test_a_pages_keys_are_written_as_the_platform_writes_them(monkeypatch):
    text = '**Ctrl+S** saves; **Ctrl+R** builds; **Shift+Wheel** is the mouse; Ctrl+X is prose'
    assert help_ui.native(text) == text.replace('**Ctrl+S**', f'**{help_ui._key("Ctrl+S")}**') \
        .replace('**Ctrl+R**', f'**{help_ui._key("Ctrl+R")}**')
    monkeypatch.setattr(help_ui, '_key', lambda seq: {'Ctrl+S': '⌘S', 'Ctrl+R': '⌘R'}.get(seq, seq))
    assert help_ui.native(text).startswith('**⌘S** saves; **⌘R** builds')
    assert 'Ctrl+X is prose' in help_ui.native(text)


def test_preferences_and_quit_are_where_macos_looks_for_them(window):
    from PySide6.QtGui import QAction
    assert window.preferences_action.menuRole() == QAction.MenuRole.PreferencesRole
    quit_ = next(a for a in menu(window.menuBar(), 'File').actions() if a.text() == '&Quit')
    assert quit_.menuRole() == QAction.MenuRole.QuitRole
    assert window.about_action.menuRole() == QAction.MenuRole.AboutRole
