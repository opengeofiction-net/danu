"""File's Upload, Rename and Delete square (#190, N5b), against the real
drop in-process: the window imports pizarrales from it, then sends the open
square back - and, refused, keeps the mapper's copy and draws it."""

import json
import shutil

import pytest

pytest.importorskip('PySide6')
pytest.importorskip('fcntl', reason='the data drop is the server\'s: no fcntl here')

from danu.core import mirror, territory
from danu.drop import app as A
from tests.test_drop import fake_users, osm, sha
from tests.test_dropclient import API, InProcess

from .conftest import ATTRIBUTES, GEOMETRY

GOLDEN = 'S24E125_Los_Pizarrales.osm.xz'


class Territories:
    def __init__(self):
        self.idx = territory.TerritoryIndex(territory.parse_geometry(json.dumps(GEOMETRY)),
                                            territory.parse_attributes(json.dumps(ATTRIBUTES)))

    def index(self):
        return self.idx


@pytest.fixture
def w(window, zone, tmp_path, qtbot):
    """The server holds the golden square in pizarrales; the window imports
    it from there, signed in as Luciano, whose ground it is."""
    base = tmp_path / 'server'
    there = base / 'osm-squares' / zone.name
    there.mkdir(parents=True)
    shutil.copy(zone / GOLDEN, there / GOLDEN)
    (base / 'zones').write_text(f'{zone.name}   S24E124-S23E127\n')
    opener = InProcess(A.DropApp(A.Config(base, tmp_path / 'publish'), fake_users, Territories()))
    window.settings.set_url('drop/url', API)
    window.settings.import_root = zone.parent
    window.settings.user, window.settings.token = 'Luciano', 't-luciano'
    for who in (window.importer, window.sender):
        who.runner = lambda job: job.run()
        who.opener = opener
    window.importer.choose = lambda zones, current: current
    window.sender.confirm = lambda title, text: True
    window.import_action.trigger()
    assert GOLDEN in mirror.read_manifest(zone)
    window.there = there
    window.messages = []
    window.sender.message.connect(window.messages.append)
    return window


def reopened(w, qtbot, fn):
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        fn()


def test_upload_sends_the_open_square(w, zone):
    (zone / GOLDEN).write_bytes(osm(2))
    w.drop_actions['drop.upload'].trigger()
    assert (w.there / GOLDEN).read_bytes() == osm(2)
    assert 'uploaded' in w.messages[-1] and mirror.read_manifest(zone)[GOLDEN]['sha256'] == sha(osm(2))


def test_refused_the_copy_is_kept_theirs_imported_and_drawn(w, zone, qtbot):
    (w.there / GOLDEN).write_bytes(osm(4))                   # somebody else's went up first
    (zone / GOLDEN).write_bytes(osm(2))                      # and the mapper's edits, saved
    mine = osm(2)
    reopened(w, qtbot, w.drop_actions['drop.upload'].trigger)
    kept = zone / 'S24E125_Los_Pizarrales.mine.osm.xz'
    assert kept.read_bytes() == mine and (zone / GOLDEN).read_bytes() == osm(4)
    assert 'changed on the server' in ' '.join(w.messages)
    qtbot.waitUntil(lambda: w.reference.square is not None, timeout=10000)
    assert len(w.reference.square.nodes) == 2 and w.drop_actions['drop.discard'].isEnabled(), 'the mapper\'s copy'
    w.view_actions['view.refused'].setChecked(False)
    assert not w.reference.shown()
    w.view_actions['view.refused'].setChecked(True)
    # opened again later: drawn again
    reopened(w, qtbot, lambda: w.open_working_set(zone, w.working_set.centre))
    qtbot.waitUntil(lambda: w.reference.square is not None, timeout=10000)
    w.drop_actions['drop.discard'].trigger()
    assert not kept.exists() and w.reference.square is None and not w.drop_actions['drop.discard'].isEnabled()


def test_rename_renames_there_and_here(w, zone, qtbot):
    w.sender.ask_label = lambda current: 'Los_Pizarrales_Sur' if current == 'Los_Pizarrales' else None
    reopened(w, qtbot, w.drop_actions['drop.rename'].trigger)
    assert (w.there / 'S24E125_Los_Pizarrales_Sur.osm.xz').exists() and not (w.there / GOLDEN).exists()
    assert (zone / 'S24E125_Los_Pizarrales_Sur.osm.xz').exists() and not (zone / GOLDEN).exists()
    assert w.working_set.squares[w.working_set.centre].path.name == 'S24E125_Los_Pizarrales_Sur.osm.xz'
    w.sender.ask_label = lambda current: 'no.dots'
    w.drop_actions['drop.rename'].trigger()
    assert 'a name is letters' in w.messages[-1]


def test_delete_takes_it_from_the_server_and_leaves_it_here(w, zone):
    w.drop_actions['drop.delete'].trigger()
    assert not (w.there / GOLDEN).exists() and (zone / GOLDEN).exists()
    assert 'deleted from the server' in w.messages[-1]


def test_asked_and_declined_nothing_is_sent(w, zone):
    w.sender.confirm = lambda title, text: False
    (zone / GOLDEN).write_bytes(osm(2))
    w.drop_actions['drop.upload'].trigger()
    w.drop_actions['drop.delete'].trigger()
    assert (w.there / GOLDEN).read_bytes() != osm(2) and (w.there / GOLDEN).exists()


def test_signed_out_says_sign_in(w):
    w.settings.token = ''
    w.drop_actions['drop.upload'].trigger()
    assert w.messages[-1] == 'sign in to OGF first: File › Sign in', 'not sent at all'


def test_unsaved_edits_are_saved_first_then_sent(w, zone, qtbot):
    from danu.core import edits
    sq = w.working_set.squares[w.working_set.centre]
    alloc = edits.IdAllocator(sq)
    w.editor.history.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()],
                                         [(125.2, -23.5), (125.8, -23.5)], {'ele': '999'}))
    assert w.editor.dirty()
    from PySide6.QtCore import QTimer
    w._write_runner = lambda job: QTimer.singleShot(300, job.run)        # a save that lands later
    w.drop_actions['drop.upload'].trigger()
    assert not any('uploaded' in m for m in w.messages), 'waits for the save'
    qtbot.waitUntil(lambda: any('uploaded' in m for m in w.messages), timeout=10000)
    assert not w.editor.dirty()
    assert (w.there / GOLDEN).read_bytes() == (zone / GOLDEN).read_bytes()


def test_a_square_renamed_there_the_same_bytes_opens_the_set_again(w, zone, qtbot):
    """N5a's rename in place: the set's file for it was under the old name."""
    (w.there / GOLDEN).rename(w.there / 'S24E125_Pizarrales.osm.xz')
    reopened(w, qtbot, w.import_action.trigger)
    assert w.working_set.squares[w.working_set.centre].path.name == 'S24E125_Pizarrales.osm.xz'


def test_never_imported_here_asked_then_replaced_and_no_mine(w, zone):
    (zone / '.danu-mirror.json').unlink()
    (zone / GOLDEN).write_bytes(osm(2))
    asked = []
    w.sender.confirm = lambda title, text: (asked.append((title, text)), True)[1]
    w.drop_actions['drop.upload'].trigger()
    assert [t for t, _ in asked] == ['Upload square', 'Replace the server\'s square']
    assert 'before Danu 1.3' in asked[1][1] and 'last changed' in asked[1][1]
    assert (w.there / GOLDEN).read_bytes() == osm(2) and 'uploaded' in w.messages[-1]
    assert not list(zone.glob('*.mine.osm.xz'))


def test_never_imported_here_declined_nothing_changes(w, zone):
    (zone / '.danu-mirror.json').unlink()
    before = (w.there / GOLDEN).read_bytes()
    (zone / GOLDEN).write_bytes(osm(2))
    w.sender.confirm = lambda title, text: title == 'Upload square'
    w.drop_actions['drop.upload'].trigger()
    assert (w.there / GOLDEN).read_bytes() == before and (zone / GOLDEN).read_bytes() == osm(2)
    assert not list(zone.glob('*.mine.osm.xz')) and 'left as it is' in w.messages[-1]
