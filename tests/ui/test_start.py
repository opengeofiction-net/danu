"""The start page (J5a): a card over the map while nothing is open."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QPushButton

from danu.core.square import SquareName
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.settings import Settings
from danu.ui.territory import TerritoryFetcher


def new_window(qtbot, tmp_path, territory_files):
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                   territory_fetcher=fetcher)
    w.prompt_on_close = False
    qtbot.addWidget(w)
    # the map as wide as the window: on Windows' CI the window cannot be made
    # as big as asked, and the map between the docks was 68 px
    for d in w.docks():
        d.hide()
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def bare(qtbot, tmp_path, territory_files):
    """A window with nothing open, as a first run has it, told so as main tells it."""
    w = new_window(qtbot, tmp_path, territory_files)
    w._drop_runner = lambda job: job.run()          # the drop asked in place: not reached, here
    w.update_start()
    return w


def buttons(w):
    return {b.text(): b for b in w.start.findChildren(QPushButton) if b.isVisibleTo(w.start)}


def test_with_nothing_open_the_start_page_is_over_the_middle_of_the_map(bare):
    assert bare.start.isVisible()
    vp = bare.map.viewport().geometry()
    card = bare.start.geometry()
    assert vp.contains(card)
    assert abs(card.center().x() - vp.center().x()) <= 1 and abs(card.center().y() - vp.center().y()) <= 1
    assert list(buttons(bare)) == ['Sign in…', 'Zones map', 'Import…', 'Open…', 'New…']


def test_each_step_is_the_file_menus_own_action(bare):
    fired = []
    for a in (bare.account_action, bare.import_action, bare.open_action, bare.new_square_action):
        a.triggered.disconnect()
        a.triggered.connect(lambda _=False, a=a: fired.append(a))
    for b in buttons(bare).values():
        b.click()
    assert fired == [bare.account_action, bare.import_action, bare.open_action, bare.new_square_action]


def test_signed_in_it_says_as_whom_and_offers_no_sign_in(bare):
    assert 'Sign in to OGF' in bare.start.account.text()
    bare._signed_in('wangi', 'tok-1', [])
    assert 'Signed in to OGF as <b>wangi</b>' in bare.start.account.text()
    assert list(buttons(bare)) == ['Zones map', 'Import…', 'Open…', 'New…']
    bare.sign_out()
    assert list(buttons(bare)) == ['Sign in…', 'Zones map', 'Import…', 'Open…', 'New…']


def test_it_goes_while_a_square_is_read_and_stays_gone_once_it_is_open(bare, zone, qtbot):
    assert bare.start.isVisible()
    with qtbot.waitSignal(bare.loader.finished, timeout=15000):
        assert bare.open_working_set(zone, SquareName(125, -24))
        assert not bare.start.isVisible(), 'shown over a square being read'
    qtbot.waitUntil(lambda: bare.working_set is not None, timeout=5000)
    assert not bare.start.isVisible()


def test_a_square_that_cannot_be_read_brings_it_back(bare, tmp_path, monkeypatch):
    monkeypatch.setattr('danu.ui.app.QMessageBox.warning', lambda *a: None)
    bare._pending = (tmp_path / 'nowhere', SquareName(125, -24), 3)       # as open_working_set leaves it
    bare.update_start()
    assert not bare.start.isVisible()
    bare._load_failed('no such zone')
    assert bare.start.isVisible()


def test_it_follows_the_map_when_the_window_is_resized(bare, qtbot):
    bare.resize(bare.width() + 300, bare.height() + 200)
    qtbot.waitUntil(lambda: abs(bare.start.geometry().center().x()
                                - bare.map.viewport().geometry().center().x()) <= 1, timeout=2000)
    assert bare.map.viewport().geometry().contains(bare.start.geometry())


def test_on_a_narrow_map_it_narrows_to_fit(bare, qtbot):
    side = bare.width() - bare.map.viewport().width()
    bare.resize(side + 330, bare.height())
    qtbot.waitUntil(lambda: bare.map.viewport().width() <= 340, timeout=2000)
    qtbot.waitUntil(lambda: bare.map.viewport().geometry().contains(bare.start.geometry()), timeout=2000)
    assert bare.start.width() < 420


def test_a_window_with_a_square_open_has_no_start_page(window):
    assert not window.start.isVisible()
    window.update_start()
    assert not window.start.isVisible()


def test_a_new_window_waits_to_be_told_nothing_is_opening(qtbot, tmp_path, territory_files):
    """Not shown by the window itself: at start the session is put back
    after the window is made, and a card shown first would flash over it."""
    w = new_window(qtbot, tmp_path, territory_files)
    assert not w.start.isVisible()


# ------------------------------------------------------------------ J5c
def test_with_nothing_open_a_new_square_asks_the_zone_and_is_the_one_mid_map(bare, tmp_path, qtbot,
                                                                             monkeypatch):
    zone = tmp_path / 'newzone'
    zone.mkdir()
    monkeypatch.setattr('danu.ui.app.QFileDialog.getExistingDirectory', lambda *a: str(zone))
    offered = []
    bare.ask_text = lambda title, label, text: (offered.append(text), ('', False))[1]
    bare.map.center_on_lonlat(20.6, -33.2)
    bare.new_blank_square()
    assert offered == ['S34E020']
    assert not list(zone.iterdir()), 'written though cancelled'

    bare.ask_text = lambda title, label, text: (text, True)
    with qtbot.waitSignal(bare.loader.finished, timeout=15000):
        bare.new_blank_square()
    assert (zone / 'S34E020.osm.xz').exists()
    assert bare.zone_dir == zone and bare.working_set.centre == SquareName(20, -34)
    assert not bare.start.isVisible()


def test_a_square_the_zone_has_already_is_refused(bare, zone, monkeypatch):
    monkeypatch.setattr('danu.ui.app.QFileDialog.getExistingDirectory', lambda *a: str(zone))
    said = []
    monkeypatch.setattr('danu.ui.app.QMessageBox.warning', lambda *a: said.append(a[2]))
    before = sorted(p.name for p in zone.iterdir())
    bare.ask_text = lambda title, label, text: ('S24E125', True)
    bare.new_blank_square()
    assert said and 'already exists' in said[0]
    assert sorted(p.name for p in zone.iterdir()) == before


def test_asked_for_it_is_over_the_squares_with_a_close(window):
    assert not window.start.isVisible()
    window.start_action.trigger()
    assert window.start.isVisible() and window.start.close_.isVisible()
    window.start.close_.click()
    assert not window.start.isVisible()


def test_with_nothing_open_it_has_no_close(bare):
    assert not bare.start.close_.isVisible()


def test_opening_other_squares_closes_it(window, zone, qtbot):
    window.show_start()
    with qtbot.waitSignal(window.loader.finished, timeout=15000):
        window.open_working_set(zone, SquareName(125, -24))
    assert not window.start.isVisible()


def test_an_appimage_is_offered_the_menu_once(qtbot, tmp_path, territory_files, monkeypatch):
    from danu.ui import desktop
    image = tmp_path / 'Danu.AppImage'
    image.write_bytes(b'')
    monkeypatch.setenv('APPIMAGE', str(image))
    w = new_window(qtbot, tmp_path, territory_files)
    w.update_start()
    assert w.start.offer.isVisible()
    w.start.offer_add.click()
    assert desktop.installed() == image and not w.start.offer.isVisible()
    assert w.settings.menu_offered

    desktop.remove()                                     # taken out by hand: not asked again
    again = new_window(qtbot, tmp_path, territory_files)
    again.update_start()
    assert not again.start.offer.isVisible()


def test_declined_it_is_not_offered_again_and_nothing_is_written(qtbot, tmp_path, territory_files,
                                                                 monkeypatch):
    from danu.ui import desktop
    monkeypatch.setenv('APPIMAGE', str(tmp_path / 'Danu.AppImage'))
    w = new_window(qtbot, tmp_path, territory_files)
    w.update_start()
    w.start.offer_no.click()
    assert desktop.installed() is None and w.settings.menu_offered
    assert not w.start.offer.isVisible()


def test_not_an_appimage_it_offers_nothing(bare):
    assert not bare.start.offer.isVisible()


def test_shown_at_every_start_is_a_preference(window):
    from danu.ui.preferences import PreferencesDialog
    dlg = PreferencesDialog(window.settings, window.action_labels(), window)
    assert not dlg.start_always.isChecked()
    dlg.start_always.setChecked(True)
    dlg.accept()
    assert window.settings.start_always


# ------------------------------------------------------------------ #226: a new square, into its zone

@pytest.fixture
def drop(bare, tmp_path, monkeypatch):
    """The real drop in-process: gobras's squares N20E086-N20E089, Gobras City held there."""
    pytest.importorskip('fcntl', reason='the data drop is the server\'s: no fcntl here')
    from danu.core import dropclient
    from danu.drop import app as A
    from tests.test_drop import FakeTerritories, fake_users, osm
    from tests.test_dropclient import API, InProcess
    base = tmp_path / 'server'
    (base / 'osm-squares' / 'gobras').mkdir(parents=True)
    (base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(1))
    (base / 'zones').write_text('gobras          N20E086-N20E089\n')
    opener = InProcess(A.DropApp(A.Config(base, tmp_path / 'publish'), fake_users, FakeTerritories()))
    real = dropclient.square_info
    monkeypatch.setattr(dropclient, 'square_info', lambda api, sq, token='': real(api, sq, token, opener=opener))
    bare.settings.set_url('drop/url', API)
    bare.settings.import_root = tmp_path / 'Documents' / 'danu' / 'osm-squares'
    bare.importer.runner = lambda job: job.run()
    bare.importer.opener = opener
    asked = []
    monkeypatch.setattr('danu.ui.app.QFileDialog.getExistingDirectory', lambda *a: (asked.append(a[2]), '')[1])
    bare.asked_dirs = asked
    return bare


def test_a_new_square_in_a_zone_goes_where_import_puts_the_zone(drop, qtbot):
    drop.ask_text = lambda title, label, text: ('N20E087', True)
    with qtbot.waitSignal(drop.loader.finished, timeout=15000):
        drop.new_blank_square()
    zone = drop.settings.import_root / 'gobras'
    assert (zone / 'N20E087.osm.xz').exists() and drop.zone_dir == zone and not drop.asked_dirs


def test_a_new_square_held_there_already_imports_the_zone_and_opens_it(drop, qtbot):
    drop.ask_text = lambda title, label, text: ('N20E086', True)
    with qtbot.waitSignal(drop.loader.finished, timeout=15000):
        drop.new_blank_square()
    zone = drop.settings.import_root / 'gobras'
    assert sorted(p.name for p in zone.glob('*.osm.xz')) == ['N20E086_Gobras_City.osm.xz'], 'no blank over it'
    assert drop.working_set.centre == SquareName(86, 20)


def test_a_new_square_in_no_zone_asks_the_directory_from_the_import_root_made_first(drop):
    """#226: the dialog started somewhere of the system's, the root not there yet."""
    drop.ask_text = lambda title, label, text: ('N40E010', True)
    assert not drop.settings.import_root.exists()
    drop.new_blank_square()
    assert drop.asked_dirs == [str(drop.settings.import_root)] and drop.settings.import_root.is_dir()
    assert 'in no zone' in drop.statusBar().currentMessage()


def test_the_zones_map_is_the_way_in_the_card_put_away(bare):
    """#190: step 2 puts the card away, brings the Zones panel in front, and
    the card does not come back over the map the mapper is looking at."""
    framed = []
    bare.zone_editor.frame_all = lambda: framed.append(True)
    buttons(bare)['Zones map'].click()
    assert not bare.start.isVisible() and framed
    bare.update_start()
    assert not bare.start.isVisible(), 'browsing: not put back over the map'
    bare.show_start()
    assert bare.start.isVisible(), 'Help › Start page brings it back'
