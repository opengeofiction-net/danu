"""The session (H4b): Danu reopened as it was left - the set, the view, the
panels, the choices - and written as it goes, not only on closing."""

import json

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt

from danu.core.square import SquareName
from danu.ui import session
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.settings import Settings
from danu.ui.territory import TerritoryFetcher


@pytest.fixture
def make(qtbot, tmp_path, territory_files):
    """A Danu with a data directory; called again, the next run."""
    def start():
        fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                                   attributes_url=(territory_files / 'admin.json').as_uri())
        w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                       territory_fetcher=fetcher, data_dir=tmp_path / 'data')
        w.prompt_on_close = False
        qtbot.addWidget(w)
        return w
    return start


@pytest.fixture
def left(make, zone, qtbot):
    """A run that opened the zone, looked about and chose things."""
    w = make()
    w.show()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    w.map.set_zoom(11)
    w.map.center_on_lonlat(126.4, -23.6)
    w.surface_panel.mode.setCurrentText('slope')
    w.layer_chooser.radios[1].setChecked(True)
    w.layer_chooser.slider.setValue(60)
    w.edit_actions['tool.measure'].trigger()
    w.edit_actions['view.magnify'].trigger()
    w.elevation.set(35)
    w.checks_dock.show()
    w.profile_dock.hide()
    return w


def test_written_as_it_goes_not_only_on_closing(left, qtbot):
    assert left._session_timer.isActive()
    qtbot.waitUntil(lambda: left.session_path.exists(), timeout=3000)
    data = json.loads(left.session_path.read_text())
    assert data['set']['centre'] == 'S24E125' and data['view']['zoom'] == 11
    assert data['surface']['mode'] == 'slope' and data['tool'] == 'measure' and data['magnify']


def test_reopened_as_it_was_left(left, make, qtbot):
    want_lonlat = left.map.center_lonlat()
    left.close()
    data = session.read(left.session_path)
    assert data is not None
    w = make()
    session.restore_window(w, data)
    w.show()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert session.restore(w, data)
    qtbot.wait(10)
    assert w.working_set.centre == SquareName(125, -24) and w.working_set.size == 3
    assert w.map.zoom == 11
    lon, lat = w.map.center_lonlat()
    assert abs(lon - want_lonlat[0]) < 1e-3 and abs(lat - want_lonlat[1]) < 1e-3
    assert w.surface_panel.mode.currentText() == 'slope'
    assert w.layer_chooser.active is w.layer_chooser.items[1] and w.layer_chooser.slider.value() == 60
    assert w.editor.tool == 'measure' and w.loupe.on and w.controls.magnify.isChecked()
    assert w.elevation.value == 35
    assert w.checks_dock.isVisibleTo(w) and not w.profile_dock.isVisibleTo(w)


def test_a_surface_built_is_built_again_at_its_resolution(make, zone, qtbot, monkeypatch):
    w = make()
    w.show()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    data = session.capture(w)
    assert data['surface']['built'] is None, 'nothing built, nothing to build'
    data['surface']['built'] = 3.0
    asked = []
    w2 = make()
    monkeypatch.setattr(w2, 'rebuild_surface', lambda arcsec=None: asked.append(arcsec))
    with qtbot.waitSignal(w2.loader.finished, timeout=15000):
        assert session.restore(w2, data)
    assert asked == [3.0]


def test_a_session_in_a_zone_that_is_gone_opens_nothing_and_says_so(make, tmp_path):
    w = make()
    data = {'version': session.VERSION, 'set': {'zone': str(tmp_path / 'gone'), 'centre': 'S24E125', 'size': 3}}
    assert not session.restore(w, data)
    assert 'not there' in w.statusBar().currentMessage()


def test_a_file_from_another_version_or_none_is_no_session(tmp_path):
    p = tmp_path / 'session.json'
    assert session.read(p) is None and session.read(None) is None
    p.write_text('{"version": 99}')
    assert session.read(p) is None
    p.write_text('not json')
    assert session.read(p) is None


def test_without_a_data_directory_nothing_is_written(window):
    assert window.session_path is None
    window.write_session()                           # and asking is harmless


def test_the_dock_layout_comes_back(left, make):
    left.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left.surface_panel)
    data = session.capture(left)
    w = make()
    session.restore_window(w, data)
    assert w.dockWidgetArea(w.surface_panel) == Qt.DockWidgetArea.LeftDockWidgetArea
