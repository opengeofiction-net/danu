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
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox

from ..core.square import SquareName, WorkingSet
from . import config
from . import mercator as m
from .contours import ContourLayer
from .elevation import PICK_PX, ElevationControl, ElevationPanel
from .layers_panel import LayersPanel
from .loader import WorkingSetLoader
from .mapview import MapView
from .open_dialog import OpenDialog
from .settings import Settings
from .squares import SquaresItem
from .overlays import EnvelopeItem, UnreachedLayer
from .surface import SurfaceBuilder, SurfaceLayer, SurfacePanel
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
    def __init__(self, layers: list[config.Layer], cache_dir: Path | None = None,
                 settings: Settings | None = None):
        super().__init__()
        self.setWindowTitle('Danu')
        self.layers = layers
        self.settings = settings if settings is not None else Settings()
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
        self.surface = SurfaceLayer()
        self.map.scene().addItem(self.surface)
        self.unreached = UnreachedLayer()
        self.map.scene().addItem(self.unreached)
        self.envelope = EnvelopeItem()
        self.map.scene().addItem(self.envelope)
        self.surface_panel = SurfacePanel(self.surface, self, unreached=self.unreached, envelope=self.envelope)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.surface_panel)
        self.builder = SurfaceBuilder(self)
        self.builder.finished.connect(self._surface_built)
        self.builder.failed.connect(self._surface_failed)
        self.surface_panel.rebuild.connect(self.rebuild_surface)
        self._surface_started = 0.0
        self.squares = SquaresItem()
        self.map.scene().addItem(self.squares)
        self.contours = ContourLayer()
        self.map.scene().addItem(self.contours)
        self.working_set: WorkingSet | None = None
        self.zone_dir: Path | None = None
        self.elevation = ElevationControl(self.settings, self)
        self.elevation_panel = ElevationPanel(self.elevation, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.elevation_panel)
        self.elevation.changed.connect(self.contours.set_active)
        self.elevation.changed.connect(lambda _v: self._cursor(*self._last_cursor))
        self.map.elevationWheel.connect(self.elevation.step)
        self.map.opacityWheel.connect(self._opacity_wheel)
        self._last_cursor = HOME[:2]
        self.loader = WorkingSetLoader(self)
        self.loader.finished.connect(self._loaded)
        self.loader.failed.connect(self._load_failed)
        self._pending: tuple[Path, SquareName, int] | None = None
        self._menus()
        self._status = QLabel()
        self.statusBar().addPermanentWidget(self._status)
        self.map.cursorMoved.connect(self._cursor)
        self.map.setFocus()
        self.map.zoomChanged.connect(lambda _: self._cursor(*self.map.center_lonlat()))
        self.resize(1100, 750)
        self.map.set_zoom(HOME[2])
        self.map.center_on_lonlat(HOME[0], HOME[1])
        self._cursor(HOME[0], HOME[1])

    def _cursor(self, lon: float, lat: float):
        self._last_cursor = (lon, lat)
        self.elevation.cursor_at(lon, lat)
        self._status.setText(f'{self.elevation.model.tag:>5} m   {lat:9.5f}  {lon:10.5f}   z{self.map.zoom}')

    def _opacity_wheel(self, down: bool):
        """Alt and the wheel: the surface's opacity, five points a notch."""
        s = self.surface_panel.opacity
        s.setValue(s.value() + (-5 if down else 5))

    def pick_up(self):
        """Space: the elevation of the contour under the cursor, if one is
        within reach; nothing there changes nothing."""
        x, y = m.lonlat_to_scene(*self._last_cursor)
        hit = self.contours.pick(x, y, PICK_PX / m.scale_for_zoom(self.map.zoom))
        self.elevation.pick_up(hit[1].ele if hit else None)

    # ------------------------------------------------------------- menus
    def _menus(self):
        file = self.menuBar().addMenu('&File')
        self.open_action = QAction('&Open square…', self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_dialog)
        file.addAction(self.open_action)
        self.recent_menu = file.addMenu('Open &recent')
        self._fill_recent()
        elevation = self.menuBar().addMenu('&Elevation')
        self.elevation_actions: dict[str, QAction] = {}
        c = self.elevation
        for name, text, fn in (
                ('elevation.big_up', 'Big step &up', lambda: c.step(True, False)),
                ('elevation.small_up', 'Small step u&p', lambda: c.step(False, False)),
                ('elevation.small_down', 'Small step d&own', lambda: c.step(False, True)),
                ('elevation.big_down', 'Big step do&wn', lambda: c.step(True, True)),
                ('elevation.nudge_up', 'A metre up', lambda: c.nudge(False)),
                ('elevation.nudge_down', 'A metre down', lambda: c.nudge(True)),
                ('elevation.pick_up', 'Pick up the contour under the cursor', self.pick_up),
                ('elevation.sea_level', 'Sea level', c.sea_level)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(self.settings.key(name)))
            a.triggered.connect(fn)
            elevation.addAction(a)
            self.elevation_actions[name] = a
        elevation.addSeparator()
        reload_ladders = QAction('Re-read the ladder overrides', self)
        reload_ladders.triggered.connect(self.elevation.reload_overrides)
        elevation.addAction(reload_ladders)
        surface = self.menuBar().addMenu('&Surface')
        self.rebuild_action = QAction('&Rebuild surface', self)
        self.rebuild_action.setShortcut(QKeySequence('Ctrl+R'))
        self.rebuild_action.triggered.connect(lambda: self.rebuild_surface(float(self.surface_panel.resolution.currentData())))
        surface.addAction(self.rebuild_action)
        file.addSeparator()
        quit_action = QAction('&Quit', self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file.addAction(quit_action)

    def _fill_recent(self):
        self.recent_menu.clear()
        recent = self.settings.recent()
        self.recent_menu.setEnabled(bool(recent))
        for zone_dir, name, size in recent:
            a = QAction(f'{name}  ({zone_dir.name}, {size}×{size})', self)
            a.triggered.connect(lambda _=False, z=zone_dir, n=name, s=size: self.open_working_set(z, n, s))
            self.recent_menu.addAction(a)

    def open_dialog(self):
        dlg = OpenDialog(self.settings.squares_root, self.settings.size, self)
        if dlg.exec() and dlg.result_:
            # remembered in _loaded, once the read has succeeded: a root and a
            # size are worth keeping when they led to a square, not before
            self.open_working_set(*dlg.result_)

    # -------------------------------------------------------------- open
    def open_working_set(self, zone_dir: Path, centre: SquareName, size: int = 3) -> bool:
        """Read the grid on a worker and show it when it arrives. Returns
        False if a read is already running; the status line says so."""
        zone_dir = Path(zone_dir)
        if not self.loader.load(zone_dir, centre, size):
            self.statusBar().showMessage('still reading the last square - a moment')
            return False
        self._pending = (zone_dir, centre, size)
        self.zone_dir = zone_dir
        self.open_action.setEnabled(False)
        self.statusBar().showMessage(f'reading {centre} and its neighbours from {zone_dir.name}…')
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        return True

    def _loaded(self, ws: WorkingSet):
        QApplication.restoreOverrideCursor()
        self.open_action.setEnabled(True)
        self.working_set = ws
        self.squares.set_working_set(ws)
        self.contours.set_working_set(ws)
        self.elevation.set_working_set(ws, self.zone_dir.name if self.zone_dir else '')
        w, s, e, n = ws.centre.bounds
        self.map.fit_bounds(w, s, e, n)
        present = sum(1 for _ in ws.present())
        rng = ws.elevation_range()
        self.statusBar().showMessage(
            f'{ws.centre}: {present} of {len(ws.squares)} squares present, '
            f'{len(ws.elevations())} levels'
            + (f', {rng[0]:g}-{rng[1]:g} m' if rng else ''))
        if self._pending:
            zone_dir, _, size = self._pending
            self.settings.remember(*self._pending)
            self.settings.squares_root = zone_dir.parent
            self.settings.size = size
            self._fill_recent()
        self._pending = None
        self.setWindowTitle(f'Danu - {ws.centre}')
        # a surface is of a set; a new set makes the old one wrong
        self.surface.set_shaded(None)
        self.unreached.set_shaded(None)
        self.envelope.set_rings([])
        self.surface_panel.status.setText('no surface built for this set yet')

    # ----------------------------------------------------------- surface
    def rebuild_surface(self, arcsec: float | None = None) -> bool:
        """Build the working set's DEM on a worker - the same stages the
        server runs - and shade it. Slow and exact; the panel says how long."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return False
        from ..surface import params as surface_params
        try:
            p = surface_params.load()
        except (KeyError, OSError) as e:
            self._surface_failed(str(e))
            return False
        if arcsec is not None:
            p = p.with_arcsec(arcsec)
        if not self.builder.build(self.working_set, p):
            self.statusBar().showMessage('a surface is still building')
            return False
        self._surface_started = time.monotonic()
        self.surface_panel.building(f'building at {p.arcsec:g}″…')
        self.statusBar().showMessage(f'building the surface at {p.arcsec:g}″ - the same stages the server runs')
        return True

    def _surface_built(self, built):
        seconds = time.monotonic() - self._surface_started
        self.surface.set_shaded(built.shaded)
        self.unreached.set_shaded(built.shaded)
        self.envelope.set_rings(built.envelope_rings)
        self.surface_panel.built(built.shaded, seconds)
        self.statusBar().showMessage(f'surface built in {seconds:.0f} s')

    def _surface_failed(self, text: str):
        self.surface_panel.failed(text)
        self.statusBar().showMessage('the surface could not be built')
        QMessageBox.warning(self, 'Danu', f'The surface could not be built.\n\n{text}')

    def closeEvent(self, event):
        self.builder.cleanup()
        super().closeEvent(event)

    def _load_failed(self, text: str):
        QApplication.restoreOverrideCursor()
        self.open_action.setEnabled(True)
        self._pending = None
        self.statusBar().showMessage('the square could not be read')
        QMessageBox.warning(self, 'Danu', f'The square could not be read.\n\n{text}')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    ap = argparse.ArgumentParser(prog='danu', description='the OpenGeofiction contour editor')
    ap.add_argument('zone_dir', nargs='?', type=Path,
                    help="a zone's osm-squares directory to open a square from")
    ap.add_argument('square', nargs='?', help='the square, e.g. N20E087')
    ap.add_argument('--size', type=int, default=3, help='working set side, odd (default 3)')
    ap.add_argument('--surface', type=float, metavar='ARCSEC', nargs='?', const=3.0,
                    help='build and show the surface once the square is open, at this resolution (default 3)')
    args = ap.parse_args(argv[1:])
    if bool(args.zone_dir) != bool(args.square):
        ap.error('give both a zone directory and a square, or neither')

    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    layers = config.load_layers(user_config_dir() / config.USER_FILE)
    win = MainWindow(layers, cache_dir=user_cache_dir() / 'tiles')
    win.show()
    # connected before the open is asked for; the signal is queued to the
    # event loop either way, but the order reads as it runs
    if args.surface is not None:
        win.loader.finished.connect(lambda _ws, a=args.surface: win.rebuild_surface(a))
    if args.zone_dir:
        win.open_working_set(args.zone_dir, SquareName.parse(args.square), args.size)
    elif recent := win.settings.recent():
        win.open_working_set(*recent[0])
    return app.exec()
