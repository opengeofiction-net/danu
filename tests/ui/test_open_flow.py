"""Opening a square: settings, the loader on a worker, the outlines, the
dialog, and the window doing all of it."""

import lzma
import shutil
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter               # noqa: E402

from danu.core.square import SquareName, WorkingSet               # noqa: E402
from danu.ui import mercator as m                                 # noqa: E402
from danu.ui.app import MainWindow                                # noqa: E402
from danu.ui.config import load_layers                            # noqa: E402
from danu.ui.loader import WorkingSetLoader                       # noqa: E402
from danu.ui.mapview import MapView                               # noqa: E402
from danu.ui.open_dialog import OpenDialog, zones_under           # noqa: E402
from danu.ui.settings import Settings                             # noqa: E402
from danu.ui.squares import SquaresItem                           # noqa: E402

GOLDEN = Path(__file__).parents[1] / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


@pytest.fixture
def root(tmp_path):
    """An osm-squares mirror: one real zone, one empty directory, a file."""
    from danu.core.make_square import write_square
    z = tmp_path / 'squares' / 'pizarrales'
    z.mkdir(parents=True)
    shutil.copy(GOLDEN, z / GOLDEN.name)
    write_square(z / 'S24E126.osm.xz', 126, -24, 'frame')
    with lzma.open(z / 'EMPTY.osm.xz', 'wt') as f:
        f.write("<osm version='0.6' upload='never'></osm>")
    (tmp_path / 'squares' / 'notazone').mkdir()
    (tmp_path / 'squares' / 'README').write_text('x')
    return tmp_path / 'squares'


# ---------------------------------------------------------------- settings

def test_settings_round_trip_and_recent_is_most_recent_first_without_repeats(tmp_path):
    s = Settings(tmp_path / 'danu.ini')
    assert s.squares_root is None and s.size == 3 and s.recent() == []
    s.squares_root = Path('/srv/squares')
    s.size = 5
    s.remember(Path('/z/a'), SquareName(1, 2), 3)
    s.remember(Path('/z/b'), SquareName(3, 4), 1)
    s.remember(Path('/z/a'), SquareName(1, 2), 3)          # again: moves to the front, once
    again = Settings(tmp_path / 'danu.ini')
    assert again.squares_root == Path('/srv/squares') and again.size == 5
    assert again.recent() == [(Path('/z/a'), SquareName(1, 2), 3), (Path('/z/b'), SquareName(3, 4), 1)]


def test_the_default_settings_file_is_in_the_config_dir_the_spec_names(qapp):
    qapp.setApplicationName('danu')
    f = Settings().file
    assert f.parent.name == 'danu' and f.name == 'danu.ini' and 'Unknown' not in str(f)


# ------------------------------------------------------------------ loader

def test_the_loader_reads_on_a_worker_and_signals_the_set(qtbot, root):
    loader = WorkingSetLoader()
    with qtbot.waitSignal(loader.finished, timeout=15000) as got:
        assert loader.load(root / 'pizarrales', SquareName(125, -24), 3)
    ws = got.args[0]
    assert isinstance(ws, WorkingSet) and len(ws.squares) == 9 and not loader.busy


def test_the_loader_refuses_a_second_read_while_busy_and_reports_failure(qtbot, root):
    loader = WorkingSetLoader()
    with qtbot.waitSignal(loader.failed, timeout=15000) as got:
        assert loader.load(root / 'nowhere', SquareName(0, 0), 3)
        assert loader.busy and not loader.load(root / 'pizarrales', SquareName(125, -24), 3)
    assert 'FileNotFoundError' in got.args[0] or 'NotADirectory' in got.args[0] or 'nowhere' in got.args[0]
    assert not loader.busy


# ----------------------------------------------------------------- squares

@pytest.fixture
def view(qtbot):
    v = MapView()
    v.resize(900, 700)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    return v


def render(view) -> QImage:
    img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    p = QPainter(img)
    view.render(p)
    p.end()
    return img


def test_the_outlines_hatch_the_absent_squares_and_name_them_at_low_zoom(view, root):
    ws = WorkingSet.open(root / 'pizarrales', SquareName(125, -24))
    item = SquaresItem()
    item.set_working_set(ws)
    view.scene().addItem(item)
    view.fit_bounds(*ws.bounds)                      # the whole 3x3
    img = render(view)
    assert item.drawn_names == 9
    # an absent square's middle is hatched: some pixels are grey, not all white
    absent = ws.squares[SquareName(124, -25)]
    r = item.square_rect(ws, absent.name)
    c = view.mapFromScene(r.center())
    greys = sum(1 for dx in range(-12, 13) for dy in range(-12, 13)
                if img.pixelColor(c.x() + dx, c.y() + dy).red() < 245)
    assert greys > 20
    view.set_zoom(3)                                  # a degree is 5 px: no names
    render(view)
    assert item.drawn_names == 0


def test_a_square_across_the_seam_is_drawn_beside_its_neighbours(root):
    ws = WorkingSet.open(root / 'pizarrales', SquareName(179, 0))
    item = SquaresItem()
    item.set_working_set(ws)
    centre = item.square_rect(ws, SquareName(179, 0))
    east = item.square_rect(ws, SquareName(-180, 0))       # the seam is its west edge
    assert abs(east.left() - centre.right()) < 1e-6           # adjacent, not a world apart
    assert east.left() > centre.left()
    xs = sorted(item.square_rect(ws, n).left() for n in ws.squares)
    assert xs[-1] - xs[0] < 3 * m.WORLD / 360 + 1e-6            # the whole set spans three degrees


# ------------------------------------------------------------------ dialog

def test_zones_are_the_directories_that_hold_a_square(root):
    assert [d.name for d in zones_under(root)] == ['pizarrales']
    assert zones_under(root / 'missing') == []


def test_the_dialog_lists_zones_and_squares_and_returns_the_choice(qtbot, root):
    dlg = OpenDialog(root, 3)
    qtbot.addWidget(dlg)
    assert [dlg.zone.itemText(i) for i in range(dlg.zone.count())] == ['pizarrales']
    texts = [dlg.squares.item(i).text() for i in range(dlg.squares.count())]
    assert texts == ['S24E125   Los Pizarrales', 'S24E126']
    assert dlg.open_button.isEnabled()
    dlg.squares.setCurrentRow(1)
    dlg.size.setCurrentIndex(2)
    zone_dir, name, size = dlg.selection()
    assert zone_dir == root / 'pizarrales' and name == SquareName(126, -24) and size == 5


def test_the_dialog_with_no_zones_says_so_and_cannot_open(qtbot, tmp_path):
    dlg = OpenDialog(tmp_path, 3)
    qtbot.addWidget(dlg)
    assert dlg.zone.count() == 0 and not dlg.open_button.isEnabled()
    assert 'osm-squares' in dlg.hint.text()
    dlg.accept()
    assert dlg.result_ is None and dlg.result() != dlg.DialogCode.Accepted


# ------------------------------------------------------------------ window

def test_the_window_opens_on_a_worker_frames_the_square_and_remembers_it(qtbot, root, tmp_path):
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'))
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert not w.recent_menu.isEnabled()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(root / 'pizarrales', SquareName(125, -24))
        assert not w.open_action.isEnabled() and 'reading' in w.statusBar().currentMessage()
    qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
    assert w.open_action.isEnabled()
    assert len(w.contours.paths) == 22 and w.squares.working_set is w.working_set
    lon, lat = w.map.center_lonlat()
    assert abs(lon - 125.5) < 0.02 and abs(lat + 23.5) < 0.02
    assert '2 of 9 squares present' in w.statusBar().currentMessage()
    assert w.windowTitle() == 'Danu - S24E125'
    assert w.recent_menu.isEnabled() and len(w.recent_menu.actions()) == 1
    assert w.settings.recent()[0] == (root / 'pizarrales', SquareName(125, -24), 3)


def test_a_failed_read_is_reported_and_the_window_recovers(qtbot, root, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: shown.append(a[2]))
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'))
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    with qtbot.waitSignal(w.loader.failed, timeout=15000):
        w.open_working_set(root / 'nowhere', SquareName(0, 0))
    qtbot.waitUntil(lambda: w.open_action.isEnabled(), timeout=5000)
    assert shown and 'could not be read' in shown[0]
    assert w.working_set is None and w.settings.recent() == []
