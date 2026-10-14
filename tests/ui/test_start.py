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
    w.show()
    qtbot.waitExposed(w)
    return w


@pytest.fixture
def bare(qtbot, tmp_path, territory_files):
    """A window with nothing open, as a first run has it, told so as main tells it."""
    w = new_window(qtbot, tmp_path, territory_files)
    w.update_start()
    return w


def buttons(w):
    return {b.text(): b for b in w.start.findChildren(QPushButton) if not b.isHidden()}


def test_with_nothing_open_the_start_page_is_over_the_middle_of_the_map(bare):
    assert bare.start.isVisible()
    vp = bare.map.viewport().geometry()
    card = bare.start.geometry()
    assert vp.contains(card)
    assert abs(card.center().x() - vp.center().x()) <= 1 and abs(card.center().y() - vp.center().y()) <= 1
    assert list(buttons(bare)) == ['Sign in…', 'Import…', 'Open…']


def test_each_step_is_the_file_menus_own_action(bare):
    fired = []
    for a in (bare.account_action, bare.import_action, bare.open_action):
        a.triggered.disconnect()
        a.triggered.connect(lambda _=False, a=a: fired.append(a))
    for b in buttons(bare).values():
        b.click()
    assert fired == [bare.account_action, bare.import_action, bare.open_action]


def test_signed_in_it_says_as_whom_and_offers_no_sign_in(bare):
    assert 'Sign in to OGF' in bare.start.account.text()
    bare._signed_in('wangi', 'tok-1', [])
    assert 'Signed in to OGF as <b>wangi</b>' in bare.start.account.text()
    assert list(buttons(bare)) == ['Import…', 'Open…']
    bare.sign_out()
    assert list(buttons(bare)) == ['Sign in…', 'Import…', 'Open…']


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


def test_a_window_with_a_square_open_has_no_start_page(window):
    assert not window.start.isVisible()
    window.update_start()
    assert not window.start.isVisible()


def test_a_new_window_waits_to_be_told_nothing_is_opening(qtbot, tmp_path, territory_files):
    """Not shown by the window itself: at start the session is put back
    after the window is made, and a card shown first would flash over it."""
    w = new_window(qtbot, tmp_path, territory_files)
    assert not w.start.isVisible()
