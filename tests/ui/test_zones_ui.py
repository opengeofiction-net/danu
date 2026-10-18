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
    w.view_actions['view.zones'].setChecked(True)
    z = w.zone_editor
    assert z.item.isVisible() and [x['name'] for x in z.zones] == ['gobras', 'pizarrales']
    assert z.dock.list.count() == 2 and 'gobras - 16 squares' == z.dock.list.item(0).text()
    assert z.item.here == 'pizarrales', 'the open square\'s zone'
    assert not z.dock.edit.isVisible() and not z.dock.new.isVisibleTo(z.dock), 'not an administrator'


def test_an_administrator_paints_squares_onto_a_zone(w):
    admin(w)
    z = w.zone_editor
    w.view_actions['view.zones'].setChecked(True)
    z.dock.list.setCurrentRow(0)                                       # gobras
    editor_tool = w.map.tool
    z.dock.edit.click()
    assert w.map.tool is z.painter and z.dock.save.isEnabled() and not z.dock.list.isEnabled()
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
    w.view_actions['view.zones'].setChecked(True)
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
    w.view_actions['view.zones'].setChecked(True)
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
    assert not z.dock.new.isEnabled(), 'no zones read: no overlap to judge by'
    w.view_actions['view.zones'].setChecked(True)
    z.dock.new.click()
    z.dock.save.click()
    assert 'at least one square' in z.dock.status.text()
    z.dock.cancel.click()
    assert [x['name'] for x in z.zones] == ['gobras', 'pizarrales'] and 'tekan' not in zones_file(w).zones


def test_inactive_and_active_again(w):
    admin(w)
    z = w.zone_editor
    w.view_actions['view.zones'].setChecked(True)
    z.dock.list.setCurrentRow(0)
    z.dock.inactive.click()
    assert 'gobras      wip        # being drawn' in (w.server_base / 'inactive').read_text()
    assert z.zones[0]['inactive'] == 'wip' and 'inactive: wip' in z.dock.list.item(0).text()
    assert z.dock.active.isEnabled() and not z.dock.inactive.isEnabled()
    z.dock.active.click()
    assert (w.server_base / 'inactive').read_text() == '# hand comments\n'


def test_not_an_administrator_the_server_says_no(w):
    w.settings.user, w.settings.token, w.settings.roles = 'wangi', 't-wangi', ['administrator']   # says so here
    z = w.zone_editor
    z.update_buttons()
    w.view_actions['view.zones'].setChecked(True)
    z.dock.list.setCurrentRow(0)
    z.dock.edit.click()
    click(z.painter, 90.5, 18.5)
    z.dock.save.click()
    assert 'not saved' in z.dock.status.text() and 'administrator' in z.dock.status.text()
    assert z.editing == 'gobras', 'still editing: nothing lost'
