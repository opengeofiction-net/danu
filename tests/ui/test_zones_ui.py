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
