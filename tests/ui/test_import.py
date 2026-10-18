"""File › Import… (H6g) in the window: a zone mirrored into the import root,
the question asked of squares changed here, and the open set left alone
while it has unsaved edits - or opened again from its new squares. The
server is test_mirror's stand-in; the fixture's zone, pizarrales, is under
the import root."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits, mirror
from danu.core.square import SquareName, read_square, write_square
from danu.ui import app as app_module
from tests.test_mirror import BASE, Server

from .conftest import menu

TEN = SquareName(126, -24)
TEN_FILE = 'S24E126_Tenmetre.osm.xz'


def variant(zone_dir, tmp_path) -> bytes:
    """Tenmetre as the server has it: a 60 m contour more."""
    sq = read_square(zone_dir / TEN_FILE)
    alloc = edits.IdAllocator(sq)
    edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, -23.4), (126.9, -23.4)],
                 {'ele': '60'}).apply(sq)
    (tmp_path / 'server').mkdir()
    return write_square(sq, tmp_path / 'server' / TEN_FILE).read_bytes()


@pytest.fixture
def w(window, zone, tmp_path):
    files = {p.name: p.read_bytes() for p in zone.glob('*.osm.xz')}
    files[TEN_FILE] = variant(zone, tmp_path)
    server = Server({zone.name: files, 'alved': {'N10E010_Somewhere.osm.xz': b'not a square'}})
    window.settings.set_url('squares/mirror', BASE)
    window.settings.import_root = zone.parent
    imp = window.importer
    imp.runner = lambda job: job.run()
    imp.opener = server
    imp.choose = lambda zones, current: current
    imp.asked = []
    imp.ask = lambda zone_name, names: (imp.asked.append(names), set(names))[1]
    window.server = server
    return window


def ways_at(sq, ele):
    return [wy for wy in sq.ways.values() if wy.tags.get('ele') == ele]


def test_import_is_in_the_file_menu(window):
    assert window.import_action in menu(window.menuBar(), 'File').actions()


def test_a_zone_is_offered_from_the_servers_list_the_open_one_first(w):
    offered = []
    w.importer.choose = lambda zones, current: (offered.append((zones, current)), None)[1]
    w.import_action.trigger()
    assert offered == [(['alved', 'pizarrales'], 'pizarrales')]


def test_a_square_changed_here_is_asked_about_and_the_set_opened_again(w, qtbot):
    """No manifest yet, and Tenmetre differs: asked. Overwritten, and the
    set had no unsaved edits, so it is read again - the 60 m contour in."""
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.import_action.trigger()
    assert w.importer.asked == [[TEN_FILE]]
    assert ways_at(w.working_set.squares[TEN], '60'), 'the set not opened again from the new square'
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert w.statusBar().currentMessage().startswith('imported pizarrales: 1 overwritten, 1 up to date')
    assert w.statusBar().currentMessage().endswith('the set opened again from them')


def test_squares_kept_are_left_as_they_are(w):
    before = (w.zone_dir / TEN_FILE).read_bytes()
    w.importer.ask = lambda zone_name, names: set()
    w.import_action.trigger()
    assert (w.zone_dir / TEN_FILE).read_bytes() == before
    assert '1 kept as here' in w.statusBar().currentMessage()


def test_called_off_nothing_changes_and_nothing_is_left(w):
    before = (w.zone_dir / TEN_FILE).read_bytes()
    w.importer.ask = lambda zone_name, names: None
    w.import_action.trigger()
    assert (w.zone_dir / TEN_FILE).read_bytes() == before
    assert not list(w.zone_dir.glob(mirror.PART + '*'))
    assert 'called off' in w.statusBar().currentMessage()


def test_the_open_set_with_unsaved_edits_is_kept_whatever_the_server_has(w):
    sq = w.working_set.squares[TEN]
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()],
                                 [(126.2, -23.45), (126.8, -23.45)], {'ele': '55'}))
    before = (w.zone_dir / TEN_FILE).read_bytes()
    w.import_action.trigger()
    assert w.importer.asked == [], 'asked about a square the set holds edits over'
    assert (w.zone_dir / TEN_FILE).read_bytes() == before
    assert '1 held back' in w.statusBar().currentMessage()
    assert 'the open squares held back, having unsaved edits' in w.statusBar().currentMessage()
    assert ways_at(w.working_set.squares[TEN], '55'), 'the edits lost'


def test_another_zone_is_mirrored_beside_it_and_the_set_left_open(w):
    ws = w.working_set
    w.importer.choose = lambda zones, current: 'alved'
    w.import_action.trigger()
    assert (w.settings.import_root / 'alved' / 'N10E010_Somewhere.osm.xz').read_bytes() == b'not a square'
    assert w.working_set is ws
    assert 'imported alved: 1 new' in w.statusBar().currentMessage()


def test_the_server_not_reached_says_so(w):
    def down(req, timeout=None):
        raise OSError('no route to host')
    w.importer.opener = down
    w.import_action.trigger()
    assert 'import failed: OSError: no route to host' in w.statusBar().currentMessage()
    assert not w.importer.busy


def test_open_starts_at_the_import_root_when_none_has_been_opened(w, monkeypatch):
    seen = []

    class Stub:
        def __init__(self, root, size, parent):
            seen.append(root)

        def exec(self):
            return False
    monkeypatch.setattr(app_module, 'OpenDialog', Stub)
    w.settings.squares_root = None
    w.open_dialog()
    assert seen == [w.settings.import_root]


def test_the_import_root_defaults_under_documents(tmp_path):
    from danu.ui.settings import Settings
    s = Settings(tmp_path / 'x.ini')
    assert s.import_root.parts[-2:] == ('danu', 'osm-squares')
    s.import_root = tmp_path / 'elsewhere'
    assert s.import_root == tmp_path / 'elsewhere'


def test_from_the_drop_a_square_renamed_there_is_imported_under_its_new_name(w, zone):
    """The drop's API answering (#190, N5a): its working copy, the square
    renamed there replacing the old name here."""
    from tests.test_mirror import API, Drop
    drop = Drop(w.server.zones)
    w.importer.opener = drop
    w.settings.set_url('drop/url', API)
    files = drop.zones[zone.name]
    files['S24E126_Tenmetre_Hills.osm.xz'] = files.pop(TEN_FILE)
    messages = []
    w.importer.message.connect(messages.append)
    w.import_action.trigger()
    assert f'{API}/zones' in drop.asked
    assert (zone / 'S24E126_Tenmetre_Hills.osm.xz').exists() and not (zone / TEN_FILE).exists()
    assert 'renamed' in messages[-1]
