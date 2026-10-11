"""The preferences (H6e): the steps, the threshold, a key each action, and
the servers - written to the INI on OK, and put to use by the window."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QKeySequence

from danu.ui import app as app_module
from danu.ui.preferences import PreferencesDialog
from danu.ui.settings import DEFAULT_KEYS, default_url


@pytest.fixture
def dlg(window):
    return PreferencesDialog(window.settings, window.action_labels(), window)


def ok(window, dlg):
    dlg.accept()
    if dlg.result():
        window.apply_settings()
    return dlg.result()


def test_every_rebindable_action_is_named_as_the_menus_have_it(window):
    labels = window.action_labels()
    assert set(window.keyed_actions()) == set(DEFAULT_KEYS) == set(labels)
    assert labels['edit.grade'] == 'Edit › Water › Grade'
    assert labels['view.josm_surface'] == 'Surface › Show in JOSM'
    assert labels['elevation.small_up'] == 'Elevation › Small step up'


def test_the_preferences_are_in_the_file_menu(window):
    file = window.menuBar().actions()[0].menu()
    assert window.preferences_action in file.actions()


def test_a_key_changed_holds_at_once_on_the_action_and_the_map_button(window, dlg):
    dlg.edits['tool.draw'].setKeySequence(QKeySequence('D'))
    assert ok(window, dlg)
    assert window.settings.key('tool.draw') == 'D'
    assert window.edit_actions['tool.draw'].shortcut().toString() == 'D'
    assert window.controls.draw.toolTip().endswith('(D)')


def test_a_key_two_actions_would_share_is_refused_and_said(window, dlg):
    dlg.edits['tool.draw'].setKeySequence(QKeySequence('Q'))         # select's
    assert not ok(window, dlg)
    assert 'Q is both' in dlg.clash.text() and dlg.clash.isVisibleTo(dlg)
    assert window.settings.key('tool.draw') == 'A', 'written though refused'


def test_a_key_open_quit_or_rebuild_has_is_refused(window, dlg):
    dlg.edits['edit.grade'].setKeySequence(QKeySequence('Ctrl+R'))
    assert not ok(window, dlg)
    assert 'Rebuild surface' in dlg.clash.text()


def test_an_unbound_action_takes_no_key_and_clashes_with_nothing(window, dlg):
    dlg.edits['edit.grade'].clear()
    dlg.edits['edit.flatten'].clear()
    assert ok(window, dlg)
    assert window.edit_actions['edit.grade'].shortcut().isEmpty()


def test_defaults_put_every_key_back_and_the_ini_holds_none(window, dlg):
    dlg.edits['tool.draw'].setKeySequence(QKeySequence('D'))
    assert ok(window, dlg)
    again = PreferencesDialog(window.settings, window.action_labels(), window)
    assert again.edits['tool.draw'].keySequence().toString() == 'D'
    again.default_keys()
    assert ok(window, again)
    assert window.settings.q.value('keys/tool.draw') is None
    assert window.edit_actions['tool.draw'].shortcut().toString() == 'A'


def test_a_server_set_is_used_and_its_default_left_empty(window, dlg):
    dlg.urls['josm/url'].setText('http://127.0.0.1:8112')
    dlg.urls['ogf/server'].setText(default_url('ogf/server'))
    assert ok(window, dlg)
    assert window.josm.base == 'http://127.0.0.1:8112'
    assert window.settings.q.value('ogf/server') == '', 'the default written out'


def test_overpass_is_asked_at_the_address_set(window, dlg, monkeypatch):
    asked = []
    monkeypatch.setattr(app_module.overpass, 'fetch', lambda bounds, url, **kw: asked.append(url) or b'')
    dlg.urls['overpass/url'].setText('https://overpass.example/api/interpreter')
    assert ok(window, dlg)
    window.water._fetch((0, 0, 1, 1))
    window.heights._fetch((0, 0, 1, 1))
    assert asked == ['https://overpass.example/api/interpreter'] * 2


def test_the_territory_and_published_addresses_follow(window, dlg):
    dlg.urls['territory/owners'].setText('https://wiki.example/owners')
    dlg.urls['published/dem'].setText('https://data.example/{zone}.tif')
    assert ok(window, dlg)
    assert window.territory.urls['attributes'] == 'https://wiki.example/owners'
    assert window.published.url == 'https://data.example/{zone}.tif'


def test_the_selected_panel_copies_with_the_server_set(window, dlg):
    dlg.urls['ogf/server'].setText('https://test.example/')
    assert ok(window, dlg)
    assert window.selection_panel.server == 'https://test.example'


def test_the_steps_reach_the_elevation_panel(window, dlg):
    dlg.small.setValue(5)
    dlg.big.setValue(25)
    assert ok(window, dlg)
    assert window.elevation.model.small == 5 and window.elevation_panel.big.value() == 25


def test_the_wms_port_is_written(window, dlg):
    dlg.wms_port.setValue(9115)
    assert ok(window, dlg)
    assert window.settings.wms_port == 9115


def test_a_new_bare_ring_threshold_finds_the_checks_again(window, dlg, qtbot):
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.inside_index is not None, timeout=5000)
    before = window.inside_index
    dlg.bare.setValue(1000)
    assert ok(window, dlg)
    qtbot.waitUntil(lambda: window.inside_index is not before and window.inside_index is not None, timeout=5000)
    assert window.checks_dock.bare_min_ha == 1000 and '1000 ha' in window.checks_dock.node('bare').toolTip(0)


def test_the_keys_are_listed_in_the_menus_order(window, dlg):
    rows = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
    assert rows[0] == 'File › Save' and rows.index('Edit › Undo') < rows.index('Edit › Water › Grade') \
        < rows.index('Elevation › Big step up') < rows.index('Surface › Pinch ramp on active elevation')


def test_every_address_the_dialog_lists_has_a_default():
    from danu.ui.settings import URLS
    assert all(default_url(k).startswith('http') or default_url(k).startswith('file:') for k in URLS)


def test_every_keyed_map_button_is_told_again(window):
    c = window.controls
    keyed = {b for b, _what, _action in c._tipped}
    assert keyed == {c.select, c.draw, c.spot, c.measure, c.undo, c.redo, c.delete, c.split, c.unglue,
                     c.magnify, c.water, c.heights}
