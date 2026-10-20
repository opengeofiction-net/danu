"""The zones on the map and their editing (#190, N6), against the real drop
in-process: anyone sees them, an administrator paints squares onto a zone,
makes one, and sets it inactive and active again."""

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('fcntl', reason='the data drop is the server\'s: no fcntl here')

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from danu.core import zones as Z
from danu.core.square import SquareName as S
from danu.drop import app as A
from danu.ui import mercator as m
from tests.test_drop import FakeTerritories, fake_users
from tests.test_dropclient import API, InProcess


@pytest.fixture
def w(window, tmp_path):
    base = tmp_path / 'server'
    (base / 'osm-squares').mkdir(parents=True)
    (base / 'zones').write_text('# kept\ngobras          N18E086-N21E089   # a note\n'
                                'pizarrales      S24E124-S23E126\n')
    (base / 'inactive').write_text('# hand comments\n')
    z = window.zone_editor
    z.runner = lambda job: job.run()
    z.opener = InProcess(A.DropApp(A.Config(base, tmp_path / 'publish'), fake_users, FakeTerritories()))
    z.ask_name = lambda: 'tekan'
    z.ask_inactive = lambda zone: ('wip', 'being drawn')
    window.settings.set_url('drop/url', API)
    window.server_base = base
    # open from the first run, the panel read the zones as the window was made,
    # from nowhere: read again from this drop
    z.load()
    return window


def admin(w):
    w.settings.user, w.settings.token, w.settings.roles = 'Admin', 't-admin', ['administrator']
    w.zone_editor.update_buttons()


def at(lon, lat):
    return QPointF(*m.lonlat_to_scene(lon, lat))


def click(painter, lon0, lat0, lon1=None, lat1=None, ctrl=False):
    """A press at one place, a drag to another, a release - as the map hands them on."""
    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(), QPointF(), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, mods)
    lon1, lat1 = (lon0, lat0) if lon1 is None else (lon1, lat1)
    assert painter.mouse_press(ev, at(lon0, lat0))
    painter.mouse_move(ev, at(lon1, lat1))
    assert painter.mouse_release(ev, at(lon1, lat1))


def zones_file(w):
    return Z.Zones((w.server_base / 'zones').read_text())


def test_anyone_sees_the_zones_from_view(w):
    w.zones_dock.show()
    z = w.zone_editor
    assert z.item.isVisible() and [x['name'] for x in z.zones] == ['gobras', 'pizarrales']
    assert z.dock.list.count() == 2 and 'gobras - 16 squares' == z.dock.list.item(0).text()
    assert z.item.here == 'pizarrales', 'the open square\'s zone'
    assert not z.dock.edit.isVisible() and not z.dock.new.isVisibleTo(z.dock), 'not an administrator'


def test_an_administrator_paints_squares_onto_a_zone(w):
    admin(w)
    z = w.zone_editor
    w.zones_dock.show()
    z.dock.list.setCurrentRow(0)                                       # gobras
    editor_tool = w.map.tool
    z.dock.edit.click()
    assert w.map.tool is z.painter and z.dock.save.isEnabled() and not z.dock.list.isEnabled()
    assert not z.dock.reload.isEnabled(), 'the squares refused are as editing began'
    click(z.painter, 90.5, 18.5, 91.5, 21.5)                           # two columns east
    click(z.painter, 86.5, 21.5, ctrl=True)                            # one square away
    click(z.painter, 124.5, -23.5)                                     # pizarrales': refused
    assert S(124, -24) not in z.painter.cells
    z.dock.save.click()
    assert w.map.tool is editor_tool, 'the editor\'s tool back'
    g = zones_file(w).zones['gobras']
    assert g.cells() == {S(lon, lat) for lon in range(86, 92) for lat in range(18, 22)} - {S(86, 21)}
    assert (w.server_base / 'zones').read_text().startswith('# kept\ngobras          '), 'the file\'s comments kept'
    assert '# a note' in (w.server_base / 'zones').read_text()
    assert 'gobras saved' in z.dock.status.text()


def test_the_drag_shows_what_it_would_take_and_refuse(w):
    admin(w)
    z = w.zone_editor
    w.zones_dock.show()
    z.dock.list.setCurrentRow(0)
    z.dock.edit.click()
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(), QPointF(), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    z.painter.mouse_press(ev, at(122.5, -23.5))
    z.painter.mouse_move(ev, at(125.5, -23.5))
    assert z.item.refused == {S(124, -24), S(125, -24)} and S(123, -24) in z.item.editing
    z.dock.cancel.click()
    assert z.item.editing is None and zones_file(w).zones['gobras'].cells() == Z.Rect.parse('N18E086-N21E089').cells()


def test_a_new_zone(w):
    admin(w)
    z = w.zone_editor
    w.zones_dock.show()
    z.dock.new.click()
    assert z.editing == 'tekan'
    click(z.painter, 128.5, 17.5, 130.5, 21.5)
    z.dock.save.click()
    assert [str(r) for r in zones_file(w).zones['tekan'].rects] == ['N17E128-N21E130']
    assert (w.server_base / 'osm-squares' / 'tekan').is_dir()
    assert [x['name'] for x in z.zones] == ['gobras', 'pizarrales', 'tekan']


def test_a_new_zone_left_empty_is_dropped(w):
    admin(w)
    z = w.zone_editor
    z.set_zones([])
    assert not z.dock.new.isEnabled(), 'no zones read: no overlap to judge by'
    z.load()
    z.dock.new.click()
    z.dock.save.click()
    assert 'at least one square' in z.dock.status.text()
    z.dock.cancel.click()
    assert [x['name'] for x in z.zones] == ['gobras', 'pizarrales'] and 'tekan' not in zones_file(w).zones


def test_inactive_and_active_again(w):
    admin(w)
    z = w.zone_editor
    w.zones_dock.show()
    z.dock.list.setCurrentRow(0)
    z.dock.inactive.click()
    assert 'gobras      wip        # being drawn' in (w.server_base / 'inactive').read_text()
    assert z.zones[0]['inactive'] == 'wip' and 'inactive: wip' in z.dock.list.item(0).text()
    assert z.dock.active.isEnabled() and not z.dock.inactive.isEnabled()
    z.dock.active.click()
    assert (w.server_base / 'inactive').read_text() == '# hand comments\n'


def test_the_server_refuses_one_it_does_not_take_for_an_administrator(w):
    # the roles here say administrator; the server's answer for the token does not
    w.settings.user, w.settings.token, w.settings.roles = 'wangi', 't-wangi', ['administrator']
    z = w.zone_editor
    z.update_buttons()
    w.zones_dock.show()
    z.dock.list.setCurrentRow(0)
    z.dock.edit.click()
    click(z.painter, 90.5, 18.5)
    z.dock.save.click()
    assert 'not saved' in z.dock.status.text() and 'administrator' in z.dock.status.text()
    assert z.editing == 'gobras', 'still editing: nothing lost'


def test_one_zones_in_view_the_panel_and_the_outlines_with_it(w):
    from .conftest import menu
    view = [a.text().replace('&', '') for a in menu(w.menuBar(), 'View').actions()]
    assert view.count('Zones') == 1
    z = w.zone_editor
    assert w.zones_dock.isVisible() and z.item.isVisible() and z.zones, 'open from the first run'
    w.zones_dock.toggleViewAction().trigger()
    assert not z.item.isVisible() and w.map.browse is None
    w.zones_dock.toggleViewAction().trigger()
    assert z.item.isVisible() and w.map.browse is z.browser


# ------------------------------------------------------------------ the zones map as the way in

def on_map(w, lon, lat):
    """Where a place is on the map's viewport, the map framed to show it and the open set."""
    from PySide6.QtCore import QPoint
    p = w.map.mapFromScene(at(lon, lat))
    return QPoint(p.x(), p.y())


@pytest.fixture
def way_in(w, tmp_path):
    """The server holds Gobras City in gobras; the map framed on gobras and the open set."""
    from tests.test_drop import osm
    (w.server_base / 'osm-squares' / 'gobras').mkdir()
    (w.server_base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(1))
    w.settings.import_root = tmp_path / 'imports'
    w.importer.runner = lambda job: job.run()
    w.importer.opener = w.zone_editor.opener
    w.zones_dock.show()
    w.map.fit_bounds(80.0, -30.0, 130.0, 25.0)
    return w


def test_a_click_outside_the_set_picks_the_zone(way_in, qtbot):
    from PySide6.QtTest import QTest
    w = way_in
    assert w.map.browse is w.zone_editor.browser
    QTest.mouseClick(w.map.viewport(), Qt.MouseButton.LeftButton, pos=on_map(w, 87.5, 19.5))
    assert w.zone_editor.chosen() == 'gobras' and w.zone_editor.dock.import_.isEnabled()


def test_a_double_click_imports_the_zone_and_opens_the_square(way_in, qtbot):
    from PySide6.QtTest import QTest
    w = way_in
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        QTest.mouseDClick(w.map.viewport(), Qt.MouseButton.LeftButton, pos=on_map(w, 86.5, 20.5))
    zone = w.settings.import_root / 'gobras'
    assert (zone / 'N20E086_Gobras_City.osm.xz').exists()
    assert w.zone_dir == zone and w.working_set.centre == S(86, 20)


def test_a_square_here_already_opens_without_an_import(way_in, qtbot):
    w = way_in
    zone = w.settings.import_root / 'gobras'
    zone.mkdir(parents=True)
    from tests.test_drop import osm
    (zone / 'N21E087_Hope_Island.osm.xz').write_bytes(osm(1))
    w.importer.import_zone = w.importer.refresh = lambda *a: pytest.fail('imported')
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.zone_editor.open_square(S(87, 21))
    assert w.working_set.centre == S(87, 21)


def test_inside_the_open_set_the_map_is_the_editors(way_in):
    w = way_in
    opened = []
    w.zone_editor.open_square = lambda cell: opened.append(cell) or True
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonDblClick, QPointF(), QPointF(), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    assert not w.zone_editor.browser.double_click(ev, at(125.5, -23.5)), 'the open square: the editor\'s'
    assert w.zone_editor.browser.double_click(ev, at(86.5, 20.5)) and opened == [S(86, 20)]


def test_a_drag_is_never_a_pick(way_in):
    w = way_in
    b = w.zone_editor.browser
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(60, 10), QPointF(60, 10),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    b.press(press)
    b.click(release, at(87.5, 19.5))
    assert w.zone_editor.chosen() is None


def test_import_imports_the_zone_chosen(way_in):
    w = way_in
    w.zone_editor.dock.list.setCurrentRow(0)
    w.zone_editor.dock.import_.click()
    assert (w.settings.import_root / 'gobras' / 'N20E086_Gobras_City.osm.xz').exists()


def test_closed_or_painting_the_map_is_not_the_zones(way_in):
    w = way_in
    admin(w)
    w.zone_editor.dock.list.setCurrentRow(0)
    w.zone_editor.start_edit('gobras')
    assert w.map.browse is None, 'painting squares: the painter\'s'
    w.zone_editor.stop_edit()
    assert w.map.browse is w.zone_editor.browser
    w.zones_dock.toggleViewAction().trigger()
    assert w.map.browse is None


def test_a_closed_window_is_freed_though_it_read_the_zones(qtbot, tmp_path, territory_files):
    """The pool kept the jobs that read the zones, and they held the window:
    every test's window stayed, and the suite ran three times as long (#229)."""
    import gc
    import weakref

    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication

    from danu.ui.app import MainWindow
    from danu.ui.config import load_layers
    from danu.ui.settings import Settings
    from danu.ui.territory import TerritoryFetcher
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'), territory_fetcher=fetcher)
    w.prompt_on_close = False
    w.show()
    qtbot.waitExposed(w)
    assert w.zone_editor._jobs, 'the zones read as the window opened'
    QThreadPool.globalInstance().waitForDone(10000)
    QApplication.processEvents()
    gone = weakref.ref(w)
    w.close()
    w.deleteLater()
    del w, fetcher
    QApplication.processEvents()
    qtbot.wait(50)
    gc.collect()
    assert gone() is None


# ------------------------------------------------------------------ splits, and the squares' classes

@pytest.fixture
def held(w):
    """gobras on the server: drawn at N20E086, coastline only at N20E087, blank at N20E088."""
    from tests.test_drop import osm, shore
    d = w.server_base / 'osm-squares' / 'gobras'
    d.mkdir()
    (d / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(1))
    (d / 'N20E087_Artana.osm.xz').write_bytes(shore())
    (d / 'N20E088_Laguna.osm.xz').write_bytes(osm(0))
    w.zone_editor.load()
    return w


def test_the_squares_are_drawn_in_the_wikis_colours_but_not_over_the_open_set(held):
    from danu.core.topo_style import SQUARE, SQUARE_BLANK, SQUARE_COASTLINE
    item = held.zone_editor.item
    assert item.squares == {S(86, 20): SQUARE, S(87, 20): SQUARE_COASTLINE, S(88, 20): SQUARE_BLANK}
    assert S(125, -24) in item.skip, 'the open set\'s own frames draw its squares'


def test_a_split_through_the_panel(held):
    w = held
    admin(w)
    z = w.zone_editor
    z.dock.list.setCurrentRow(0)                                       # gobras
    z.ask_name = lambda: 'artana'
    z.dock.split.click()
    assert z.splitting == 'gobras' and w.map.tool is z.painter
    click(z.painter, 87.5, 20.5, 89.5, 20.5)
    click(z.painter, 90.5, 20.5)                                       # outside gobras: refused
    assert z.painter.cells == {S(87, 20), S(88, 20), S(89, 20)}
    z.dock.save.click()
    zones = zones_file(w)
    assert [str(r) for r in zones.zones['artana'].rects] == ['N20E087-N20E089']
    assert zones.zones['gobras'].cells() == Z.Rect.parse('N18E086-N21E089').cells() - {S(87, 20), S(88, 20), S(89, 20)}
    assert sorted(p.name for p in (w.server_base / 'osm-squares' / 'artana').iterdir()) == \
        ['N20E087_Artana.osm.xz', 'N20E088_Laguna.osm.xz']
    assert 'gobras split' in z.dock.status.text() and '2 squares moved' in z.dock.status.text()
    assert z.splitting is None and w.map.tool is not z.painter


def test_a_resize_that_would_strand_contours_is_refused_and_said(held):
    w = held
    admin(w)
    z = w.zone_editor
    z.dock.list.setCurrentRow(0)
    z.dock.edit.click()
    click(z.painter, 86.5, 18.5, 86.5, 21.5, ctrl=True)               # the 086 column away
    z.dock.save.click()
    assert 'not saved' in z.dock.status.text() and 'N20E086' in z.dock.status.text()
    assert z.editing == 'gobras', 'still editing: nothing lost'


def test_a_resize_says_what_it_retired(held):
    w = held
    admin(w)
    z = w.zone_editor
    z.dock.list.setCurrentRow(0)
    z.dock.edit.click()
    click(z.painter, 88.5, 18.5, 89.5, 21.5, ctrl=True)
    z.dock.save.click()
    assert 'retired: N20E088_Laguna.osm.xz' in z.dock.status.text()


# ------------------------------------------------------------------ moving the open set

def test_ctrl_double_click_on_a_square_of_the_open_set_moves_the_set_onto_it(window, qtbot):
    from PySide6.QtTest import QTest
    w = window
    assert w.working_set.centre == S(125, -24)
    w.map.fit_bounds(124.0, -25.0, 127.0, -22.0)
    p = w.map.mapFromScene(at(126.5, -23.5))
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        QTest.mouseDClick(w.map.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, p)
    assert w.working_set.centre == S(126, -24)


def test_a_plain_double_click_inside_the_set_is_still_the_editors(window):
    w = window
    opened = []
    w.open_square_at = lambda p: opened.append(p)
    w.map.recentre = w.open_square_at
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonDblClick, QPointF(), QPointF(), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w.map.mouseDoubleClickEvent(ev)
    assert opened == []


@pytest.mark.parametrize('name, centre', [('view.set_west', S(124, -24)), ('view.set_east', S(126, -24)),
                                          ('view.set_north', S(125, -23)), ('view.set_south', S(125, -25))])
def test_alt_and_an_arrow_moves_the_set_a_square(window, qtbot, name, centre):
    w = window
    assert w.edit_actions[name].shortcut().toString().startswith('Alt+')
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.edit_actions[name].trigger()
    assert w.working_set.centre == centre
