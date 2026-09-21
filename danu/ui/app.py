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
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox

from ..core import make_square, save, territory
from ..core.square import Square, SquareName, WorkingSet
from . import config
from . import mercator as m
from .contours import ContourLayer
from .elevation import PICK_PX, ElevationControl, ElevationPanel
from .layers_panel import LayersPanel
from .legend import Legend
from .loader import WorkingSetLoader
from .mapview import MapView
from .open_dialog import OpenDialog
from .settings import Settings
from .squares import SquaresItem
from .overlays import EnvelopeItem, UnreachedLayer
from .surface import SurfaceBuilder, SurfaceLayer, SurfacePanel
from .territory import TerritoryFetcher
from .tiles import TileFetcher, TileLayer
from .tools import EditController

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
                 settings: Settings | None = None, territory_fetcher: TerritoryFetcher | None = None):
        super().__init__()
        self.setWindowTitle('Danu')
        self.layers = layers
        self.settings = settings if settings is not None else Settings()
        self.map = MapView(self)
        self.setCentralWidget(self.map)
        self.fetcher = TileFetcher(cache_dir, parent=self)
        # the tests hand in a fetcher pointed at files; the app fetches the published ones
        self.territory = territory_fetcher or TerritoryFetcher(cache_dir.parent / 'territory' if cache_dir else None, parent=self)
        self.territory.setParent(self)
        self.territory.ready.connect(self._territory_ready)
        self.territory.failed.connect(lambda t: self.statusBar().showMessage(t))
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
        self.prompt_on_close = True          # tests turn it off: a modal box has nobody to answer it
        self._last_cursor = HOME[:2]
        self.elevation = ElevationControl(self.settings, self)
        self.elevation_panel = ElevationPanel(self.elevation, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.elevation_panel)
        self.elevation.changed.connect(self.contours.set_active)
        self.elevation.changed.connect(lambda _v: self._cursor(*self._last_cursor))
        self.editor = EditController(self.map, self.contours, self.elevation, self)
        self.editor.edited.connect(self._edited)
        self.editor.edited.connect(self.elevation_panel.refresh_advice)
        self.editor.message.connect(lambda t: self.statusBar().showMessage(t))
        self.editor.toolChanged.connect(self._tool_changed)
        self.legend = Legend(self.map, self.surface, self.surface_panel, self.elevation)
        self.map.elevationWheel.connect(self.elevation.step)
        self.map.opacityWheel.connect(self._opacity_wheel)
        self.loader = WorkingSetLoader(self)
        self.loader.finished.connect(self._loaded)
        self.loader.failed.connect(self._load_failed)
        self._pending: tuple[Path, SquareName, int] | None = None
        self._menus()
        self._territory = QLabel('')
        self._territory.setToolTip('the territory and owner under the working set, from the wiki and territory.json')
        self.statusBar().addPermanentWidget(self._territory)
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

    def _edited(self):
        h = self.editor.history
        undo, redo = self.edit_actions['edit.undo'], self.edit_actions['edit.redo']
        undo.setEnabled(h.can_undo)
        redo.setEnabled(h.can_redo)
        undo.setText(f'&Undo {h.describe_undo()}' if h.can_undo else '&Undo')
        redo.setText(f'&Redo {h.describe_redo()}' if h.can_redo else '&Redo')
        if self.working_set is not None:
            self.setWindowTitle(f'Danu - {self.working_set.centre}' + (' *' if self.editor.dirty() else ''))

    # --------------------------------------------------------- territory
    def _territory_ready(self, index):
        self.show_territory()

    def show_territory(self):
        """Whose ground the centre square is on. Warns - in the status line
        and in colour - and never blocks: opening it is the mapper's call."""
        if self.working_set is None or self.territory.index is None:
            return
        found = self.territory.index.under(self.working_set.centre.bounds)
        line, warn = territory.describe(found, self.settings.user)
        if not self.territory.complete:
            line += ' (owners not read yet)'
        elif 'attributes' in self.territory.stale:
            # the wiki could not be reached; ownership is as old as the copy on disk
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(self.territory.stale['attributes']))
            line += f' (owners as of {when}, the wiki being unreachable)'
        self._territory.setText(line)
        self._territory.setStyleSheet('color: #b04000; font-weight: bold' if warn else '')
        if warn:
            self.statusBar().showMessage(f'{self.working_set.centre} is {line} - opening it anyway')

    def set_user(self):
        text, ok = QInputDialog.getText(self, 'Your OGF username', 'Username, as the wiki has it:',
                                        text=self.settings.user)
        if ok:
            self.settings.user = text
            self.show_territory()

    # -------------------------------------------------------------- save
    def save_all(self) -> bool:
        """Every dirty square to its file; one with no file yet asks where.
        Returns False if a save was declined, so a close can stop."""
        dirty = self.editor.history.dirty_squares()
        if not dirty:
            self.statusBar().showMessage('nothing to save')
            return True
        reports = []
        for sq in dirty:
            path = sq.path if sq.path is not None else self._ask_path(sq)
            if path is None:
                return False
            reports.append(self._save(sq, path))
        self.statusBar().showMessage('; '.join(r.describe() for r in reports))
        return True

    def save_as(self):
        """The square the ladder reads - the one under the cursor - to a
        file of the mapper's choosing."""
        sq = self.elevation.square
        if sq is None:
            self.statusBar().showMessage('open a square first')
            return
        path = self._ask_path(sq)
        if path is not None:
            self.statusBar().showMessage(self._save(sq, path).describe())

    def _save(self, sq: Square, path: Path) -> save.SaveReport:
        report = save.save_square(sq, self.editor.history, path, self.elevation.model.ladder
                                  if self.elevation.square is sq else None)
        self.contours.refresh(sq, set(sq.ways))          # a frame or a split changed what is drawn
        self.squares.set_working_set(self.working_set)   # a blank square is present now
        self._edited()
        return report

    def _ask_path(self, sq: Square) -> Path | None:
        if sq.path is None and self.zone_dir is None:
            self.statusBar().showMessage(f'{sq.name} has no file and no zone to put one in')
            return None
        suggested = sq.path if sq.path is not None else save.default_path(self.zone_dir, sq.name)
        chosen, _ = QFileDialog.getSaveFileName(self, f'Save {sq.name} as', str(suggested),
                                                'Contour squares (*.osm.xz *.osm)')
        return Path(chosen) if chosen else None

    def new_blank_square(self):
        """R5: a blank square file - frame only - into the zone, for ground
        nobody has drawn. The set is re-read so it shows as present."""
        if self.working_set is None or self.zone_dir is None:
            self.statusBar().showMessage('open a square in the zone first')
            return
        if self.editor.dirty():
            self.statusBar().showMessage('save first: a new square re-reads the set')
            return
        default = next((str(n) for n, s in self.working_set.squares.items() if not s.present), str(self.working_set.centre))
        text, ok = QInputDialog.getText(self, 'New blank square', 'Square (e.g. N20E087):', text=default)
        if not ok or not text.strip():
            return
        try:
            name = SquareName.parse(text.strip())
        except ValueError as e:
            QMessageBox.warning(self, 'Danu', str(e))
            return
        path = save.default_path(self.zone_dir, name)
        if path.exists() or (name in self.working_set.squares and self.working_set.squares[name].present):
            QMessageBox.warning(self, 'Danu', f'{name} already exists in {self.zone_dir.name}')
            return
        make_square.write_square(path, name.lon, name.lat, save.FRAME_NOTE)
        self.statusBar().showMessage(f'wrote {path.name}')
        self.open_working_set(self.zone_dir, self.working_set.centre, self.working_set.size)

    def closeEvent(self, event):
        if self.prompt_on_close and self.editor.dirty():
            names = ', '.join(str(sq.name) for sq in self.editor.history.dirty_squares())
            answer = QMessageBox.question(
                self, 'Danu', f'Save changes to {names}?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel or (
                    answer == QMessageBox.StandardButton.Save and not self.save_all()):
                event.ignore()
                return
        self.territory.abort()
        self.fetcher.abort()
        self.builder.cleanup()
        super().closeEvent(event)

    def _tool_changed(self, name: str):
        for key, a in self.edit_actions.items():
            if key.startswith('tool.'):
                a.setChecked(key == f'tool.{name}')

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
        file.addSeparator()
        self.save_action = QAction('&Save', self)
        self.save_action.setShortcut(QKeySequence(self.settings.key('file.save')))
        self.save_action.triggered.connect(self.save_all)
        file.addAction(self.save_action)
        self.save_as_action = QAction('Save square &as…', self)
        self.save_as_action.setShortcut(QKeySequence(self.settings.key('file.save_as')))
        self.save_as_action.triggered.connect(self.save_as)
        file.addAction(self.save_as_action)
        self.file_actions = {'file.save': self.save_action, 'file.save_as': self.save_as_action}
        self.new_square_action = QAction('&New blank square…', self)
        self.new_square_action.triggered.connect(self.new_blank_square)
        file.addAction(self.new_square_action)
        edit = self.menuBar().addMenu('&Edit')
        ed = self.editor
        self.edit_actions: dict[str, QAction] = {}
        for name, text, fn in (
                ('edit.undo', '&Undo', ed.undo),
                ('edit.redo', '&Redo', ed.redo),
                ('edit.delete', '&Delete selected', ed.delete_selected),
                ('tool.select', '&Select', lambda: ed.set_tool('select')),
                ('tool.draw', 'Dr&aw contour', lambda: ed.set_tool('draw'))):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(self.settings.key(name)))
            a.triggered.connect(fn)
            if name.startswith('tool.'):
                a.setCheckable(True)
            self.edit_actions[name] = a
        edit.addAction(self.edit_actions['edit.undo'])
        edit.addAction(self.edit_actions['edit.redo'])
        edit.addSeparator()
        edit.addAction(self.edit_actions['edit.delete'])
        edit.addSeparator()
        edit.addAction(self.edit_actions['tool.select'])
        edit.addAction(self.edit_actions['tool.draw'])
        self._tool_changed('select')
        self._edited()
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
        self.pinch_action = QAction('&Pinch the ramp on the active elevation', self)
        self.pinch_action.setShortcut(QKeySequence(self.settings.key('surface.pinch')))
        self.pinch_action.triggered.connect(self.legend.pinch_on_active)
        surface.addAction(self.pinch_action)
        self.surface_actions = {'surface.pinch': self.pinch_action}
        file.addSeparator()
        user_action = QAction('Your OGF &username…', self)
        user_action.triggered.connect(self.set_user)
        file.addAction(user_action)
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
        self.editor.set_working_set(ws)
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
        self._territory.setText('territory: looking…')
        self.territory.refresh()
        # a surface is of a set; a new set makes the old one wrong
        self.surface.set_shaded(None)
        self.legend.refresh()
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
        if not self.builder.build(self.working_set, p, self.editor.history.dirty_squares()):
            self.statusBar().showMessage('a surface is still building')
            return False
        self._surface_started = time.monotonic()
        self.surface_panel.building(f'building at {p.arcsec:g}″…')
        self.statusBar().showMessage(f'building the surface at {p.arcsec:g}″ - the same stages the server runs')
        return True

    def _surface_built(self, built):
        seconds = time.monotonic() - self._surface_started
        self.surface.set_shaded(built.shaded)
        self.legend.refresh()
        self.unreached.set_shaded(built.shaded)
        self.envelope.set_rings(built.envelope_rings)
        self.surface_panel.built(built.shaded, seconds)
        self.statusBar().showMessage(f'surface built in {seconds:.0f} s')

    def _surface_failed(self, text: str):
        self.surface_panel.failed(text)
        self.statusBar().showMessage('the surface could not be built')
        QMessageBox.warning(self, 'Danu', f'The surface could not be built.\n\n{text}')

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
