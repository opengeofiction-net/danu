"""Fixtures the UI tests share: a zone with two ladders and a blank, and the window open on it."""

import gc
import json
import os
import shutil
from pathlib import Path

import pytest

# Offscreen unless the caller has said otherwise. CI sets this in the job's
# environment and this suite is written for it - the legend's pan test says so
# in as many words - but nothing set it for a developer running pytest, so the
# tests opened real windows: they flash past on screen, and the window manager
# takes the focus back from whichever one is mid-keystroke, which is why
# test_elevation, test_legend, test_mapview and test_tools failed locally and
# passed on CI. Set before PySide6 is imported, because that is when Qt reads
# it. QT_QPA_PLATFORM=xcb still gets you the windows if you want to watch.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool           # noqa: E402
from PySide6.QtGui import QMouseEvent                                # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

from danu.core import edits                                          # noqa: E402
from danu.core.square import Square, SquareName, write_square        # noqa: E402
from danu.ui.app import MainWindow                                   # noqa: E402
from danu.ui.config import load_layers                               # noqa: E402
from danu.ui.settings import Settings                                # noqa: E402
from danu.ui.territory import TerritoryFetcher                       # noqa: E402
from danu.ui import territory as _territory, tiles as _tiles         # noqa: E402

# Nothing in this suite reaches the network, and it is stopped here at import
# rather than in a fixture. A window built in one test goes on painting during
# later ones - asking its fetcher for every visible tile - and a fixture's
# patch is undone between tests, which is exactly when those paints were
# getting out. Measured before this: 809 requests to OGF's own tile servers
# and the wiki in one run of this suite, on every push, for imagery and
# polygons no test looks at; and a reply outliving the window that asked for
# it segfaulted the Linux job on whatever test was running when it landed.
#
# A test that wants territory data hands its window a fetcher pointed at the
# fixtures below. TileFetcher._send is the one place a tile request leaves,
# and the tile tests replace it in their own subclass, which this leaves alone.
_territory.GEOMETRY_URL = 'file:///nonexistent/territory.json'
_territory.ATTRIBUTES_URL = 'file:///nonexistent/territory-admin.json'
_tiles.TileFetcher._send = lambda self, req: None

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


# territories over the test squares, in the published files' own shapes: the
# geometry [lat, lon], one entry a bare ring and one a list of rings
GEOMETRY = {
    '101': [[-24.5, 124.5], [-24.5, 126.5], [-22.5, 126.5], [-22.5, 124.5]],          # over S24E125 and the west half of S24E126
    '102': [[[-24.5, 126.5], [-24.5, 127.5], [-22.5, 127.5], [-22.5, 126.5]]],        # the east half of S24E126
    '103': [[[-21.5, 124.5], [-21.5, 125.5], [-20.5, 125.5], [-20.5, 124.5]]],        # no attribute record
}
ATTRIBUTES = [
    {'ogfId': 'AR031', 'name': 'Pizarrales', 'rel': 101, 'status': 'owned', 'owner': 'Luciano'},
    {'ogfId': 'AR032', 'name': 'Tenmetre', 'rel': 102, 'status': 'collaborative', 'owner': 'admin'},
]


@pytest.fixture
def territory_files(tmp_path):
    d = tmp_path / 'published'
    d.mkdir()
    (d / 'territory.json').write_text(json.dumps(GEOMETRY))
    (d / 'admin.json').write_text(json.dumps(ATTRIBUTES))
    return d


@pytest.fixture(autouse=True)
def collected_on_the_main_thread():
    """A Qt object is destroyed wherever Python happens to collect it, and a
    test that leaves a window behind leaves it for whoever next triggers a
    collection. The loader parses a square on a pool thread and triggers
    plenty, so the crash - reproducible here about one run in three, and
    seen on the Linux CI job - is that thread deleting a QGraphicsItem while
    the main thread is painting it:

        Thread (pooled):  Garbage-collecting / ElementTree.feed /
                          read_square / loader.run
        main:             SquaresItem._name / SquaresItem.paint

    So each test waits for its workers and collects here, on the main
    thread, leaving the pool nothing of ours to free.
    """
    yield
    QThreadPool.globalInstance().waitForDone(10000)
    gc.collect()


@pytest.fixture
def window(qtbot, zone, tmp_path, territory_files):
    settings = Settings(tmp_path / 'danu.ini')
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    w = MainWindow(load_layers(), cache_dir=None, settings=settings, territory_fetcher=fetcher)
    w.prompt_on_close = False
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


