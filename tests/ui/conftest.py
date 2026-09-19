"""Fixtures the UI tests share: a zone with two ladders and a blank, and the window open on it."""

import shutil
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt                       # noqa: E402
from PySide6.QtGui import QMouseEvent                                # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

from danu.core import edits                                          # noqa: E402
from danu.core.square import Square, SquareName, write_square        # noqa: E402
from danu.ui.app import MainWindow                                   # noqa: E402
from danu.ui.config import load_layers                               # noqa: E402
from danu.ui.settings import Settings                                # noqa: E402

GOLDEN = Path(__file__).parents[1] / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


@pytest.fixture
def zone(tmp_path):
    """The golden square (a 50 m ladder on phase 1) and, east of it, a square
    drawn at 10 m - two ladders side by side, and a blank to the north."""
    d = tmp_path / 'pizarrales'
    d.mkdir()
    shutil.copy(GOLDEN, d / GOLDEN.name)
    sq = Square(name=SquareName(126, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for i, ele in enumerate(range(10, 60, 10)):
        lat = -23.9 + i * 0.1
        edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, lat), (126.9, lat)], {'ele': str(ele)}).apply(sq)
    write_square(sq, d / 'S24E126_Tenmetre.osm.xz')
    return d


@pytest.fixture
def window(qtbot, zone, tmp_path):
    settings = Settings(tmp_path / 'danu.ini')
    w = MainWindow(load_layers(), cache_dir=None, settings=settings)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
    w.map.set_zoom(12)
    w.activateWindow()
    return w


def cursor_to(w, lon, lat):
    """Put the cursor over a point: centre the map there and move the mouse
    onto the viewport's centre."""
    w.map.center_on_lonlat(lon, lat)
    c = w.map.viewport().rect().center()
    QTest.mouseMove(w.map.viewport(), c)
    w.map.mouseMoveEvent(_move(w, c))


def _move(w, pos):
    return QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), w.map.viewport().mapToGlobal(pos),
                       Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)


