"""The window. Presentation only: it holds a MapView and tells you where the
cursor is. Everything it will grow - layers, squares, contours, editing -
arrives in later phases, and none of it lives in this file.

Run with ``python -m danu.ui``. There is no console script yet: one would land
in the server package, which has no PySide6 and no business with an editor.
That comes with the desktop packaging.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from ..core.square import SquareName, WorkingSet
from . import config
from .contours import ContourLayer
from .layers_panel import LayersPanel
from .mapview import MapView
from .tiles import TileFetcher, TileLayer

APP_NAME = 'danu'
# No organisation name, deliberately. Qt puts an organisation into the paths -
# ~/.config/OpenGeofiction/danu rather than the ~/.config/danu the spec and
# the layer file's comment promise - and a user sent to the wrong file by our
# own documentation is worse than a bare application name in a directory
# listing. Measured on Qt 6.11: with no organisation set, AppConfigLocation is
# ~/.config/danu and CacheLocation ~/.cache/danu, which is what was written

# somewhere in the middle of the drawn world, so the first view is not the
# whole planet at zoom 2 and not the Atlantic either
HOME = (87.0, 20.5, 5)


def user_config_dir() -> Path:
    """~/.config/danu on Linux, the equivalent elsewhere, from Qt. Needs the
    application name set and no organisation name - see APP_NAME."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation))


def user_cache_dir() -> Path:
    """~/.cache/danu on Linux; tiles and, later, Overpass live under it."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation))


class MainWindow(QMainWindow):
    def __init__(self, layers: list[config.Layer], cache_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle('Danu')
        self.layers = layers
        self.map = MapView(self)
        self.setCentralWidget(self.map)
        self.fetcher = TileFetcher(cache_dir, parent=self)
        # in config order, first at the bottom; the graticule sits above all
        self.tile_items = []
        for i, layer in enumerate(layers):
            item = TileLayer(layer, self.fetcher)
            item.setZValue(i)
            self.map.scene().addItem(item)
            self.tile_items.append(item)
        self.panel = LayersPanel(self.tile_items, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
        self.contours = ContourLayer()
        self.map.scene().addItem(self.contours)
        self.working_set: WorkingSet | None = None
        self._status = QLabel()
        self.statusBar().addPermanentWidget(self._status)
        self.map.cursorMoved.connect(self._cursor)
        self.map.zoomChanged.connect(lambda _: self._cursor(*self.map.center_lonlat()))
        self.resize(1100, 750)
        self.map.set_zoom(HOME[2])
        self.map.center_on_lonlat(HOME[0], HOME[1])
        self._cursor(HOME[0], HOME[1])

    def _cursor(self, lon: float, lat: float):
        self._status.setText(f'{lat:9.5f}  {lon:10.5f}   z{self.map.zoom}')

    def open_working_set(self, zone_dir: Path, centre: SquareName, size: int = 3) -> WorkingSet:
        """Read the grid and show it. Synchronous for now: the read blocks the
        window for as long as it takes, which for a large square is seconds.
        The worker the spec asks for comes with the open dialog (phase 1, D),
        which is where a mapper will wait on it."""
        ws = WorkingSet.open(zone_dir, centre, size)
        self.working_set = ws
        self.contours.set_working_set(ws)
        w, s, e, n = centre.bounds
        self.map.fit_bounds(w, s, e, n)
        present = sum(1 for _ in ws.present())
        rng = ws.elevation_range()
        self.statusBar().showMessage(
            f'{centre}: {present} of {len(ws.squares)} squares present, '
            f'{len(ws.elevations())} levels'
            + (f', {rng[0]:g}-{rng[1]:g} m' if rng else ''))
        return ws


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    ap = argparse.ArgumentParser(prog='danu', description='the OpenGeofiction contour editor')
    ap.add_argument('zone_dir', nargs='?', type=Path,
                    help="a zone's osm-squares directory to open a square from")
    ap.add_argument('square', nargs='?', help='the square, e.g. N20E087')
    ap.add_argument('--size', type=int, default=3, help='working set side, odd (default 3)')
    args = ap.parse_args(argv[1:])
    if bool(args.zone_dir) != bool(args.square):
        ap.error('give both a zone directory and a square, or neither')

    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    layers = config.load_layers(user_config_dir() / config.USER_FILE)
    win = MainWindow(layers, cache_dir=user_cache_dir() / 'tiles')
    win.show()
    if args.zone_dir:
        win.open_working_set(args.zone_dir, SquareName.parse(args.square), args.size)
    return app.exec()
