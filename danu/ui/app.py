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

from PySide6.QtCore import QStandardPaths, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox

from ..checks import crossings, loops, spots, touches
from ..core import make_square, save, territory
from ..core.square import Square, SquareName, WorkingSet
from ..water import flatten, peaks
from ..water.gone import gone
from . import config
from . import mercator as m
from .background import Job
from .checks_dock import ChecksDock
from .contours import ContourLayer
from .elevation import PICK_PX, ElevationControl, ElevationPanel
from .gone_dock import GoneDock
from .layers_panel import LayersPanel
from .legend import Legend
from .loader import WorkingSetLoader
from .mapcontrols import MapControls
from .mapview import MapView
from .messages import install as quieten_qt
from .open_dialog import OpenDialog
from .overlays import EnvelopeItem, UnreachedLayer
from .selection_panel import SelectionPanel
from .settings import Settings
from .squares import SquaresItem
from .surface import SurfaceBuilder, SurfaceLayer, SurfacePanel
from .territory import TerritoryFetcher
from .tiles import TileFetcher, TileLayer
from .tools import EditController, Selection
from .water import WaterImporter, fetch_heights, height_commands, heights_held, heights_work
from .water import commands as water_commands

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


# the nearest the map goes to show something a grade found - G6d-3
SHOW_ZOOM = 16


def user_config_dir() -> Path:
    """~/.config/danu on Linux, the equivalent elsewhere, from Qt. Needs the
    application name set and no organisation name - see APP_NAME."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation))


def user_cache_dir() -> Path:
    """~/.cache/danu on Linux; tiles and, later, Overpass live under it."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation))


def find_checks(ws, tries: int = 5):
    """The four checks' indexes over a working set - on a worker, while the
    set goes on being edited on the UI thread. An edit that changes a dict
    under the scan stops it, and it starts again; one that changes a way it
    has read is put to the indexes when they land, so what was read of that
    way is asked again."""
    for attempt in range(tries):
        try:
            return (crossings.Index(ws), loops.Index(ws), touches.Index(ws), spots.Index(ws))
        except RuntimeError:                   # changed size during iteration
            if attempt == tries - 1:
                raise


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
        # composing a whole raster goes to a worker from here on: it is 21.7 s
        # at 1 arcsecond and a window manager offers to kill an application
        # that has not drawn for a fraction of that. The layer's own default is
        # to compose on the calling thread, which is what a test wants and what
        # a small raster does not notice.
        self.surface.set_runner(QThreadPool.globalInstance().start)
        self.map.scene().addItem(self.surface)
        self.unreached = UnreachedLayer()
        self.map.scene().addItem(self.unreached)
        self.envelope = EnvelopeItem()
        self.map.scene().addItem(self.envelope)
        self.surface_panel = SurfacePanel(self.surface, self, unreached=self.unreached, envelope=self.envelope)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.surface_panel)
        # R40's report, as a tab beside the surface panel: hidden until an
        # import has something in it, and then raised - see _water_imported
        self.gone_dock = GoneDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.gone_dock)
        self.tabifyDockWidget(self.surface_panel, self.gone_dock)
        self.gone_dock.hide()
        # the validation panel (G8a): crossing contours, kept as edited
        self.checks_dock = ChecksDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.checks_dock)
        self.tabifyDockWidget(self.surface_panel, self.checks_dock)
        self.checks_dock.hide()
        self.crossing_index = None
        self.loop_index = None                  # contours crossing themselves (G8c)
        self.touch_index = None                 # touching or lying on one another (G8e)
        self.spot_index = None                  # spot heights the rings contradict (R38)
        # the first scan over a set runs on a worker - 9.3 s on gobras - and
        # the edits made while it runs are put to it when it lands
        self._checks_runner = QThreadPool.globalInstance().start
        self._checks_job = None
        self._checks_missed: list = []
        # saves compress and write on a thread of their own, one at a time and
        # in the order asked, so two saves of one square land in that order
        self._write_pool = QThreadPool(self)
        self._write_pool.setMaxThreadCount(1)
        self._write_runner = self._write_pool.start
        self._writes: list = []                 # jobs out, kept until they answer
        self._written: list = []                # reports of a save still landing
        self._asking = False
        self._checks_due = QTimer(self)
        self._checks_due.setSingleShot(True)
        self._checks_due.setInterval(250)
        self._checks_due.timeout.connect(self._refresh_checks)
        self.checks_dock.chosen.connect(self._choose_crossing)
        self.checks_dock.loopChosen.connect(self._choose_loop)
        self.checks_dock.touchChosen.connect(self._choose_touch)
        self.checks_dock.spotChosen.connect(self._choose_spot)
        # the editor is made below: looked up when the button is pressed
        self.checks_dock.cutLoop.connect(lambda loop: self.editor.cut_loop(loop))
        self.checks_dock.visibilityChanged.connect(self._checks_shown)
        # opened from the menu, it comes to the front of the tabs it shares:
        # shown alone it stayed behind the surface panel, and was never seen
        self.checks_dock.toggleViewAction().toggled.connect(self._checks_opened)
        self.builder = SurfaceBuilder(self)
        from .preview import PreviewDriver
        self.preview = PreviewDriver(self)
        # the solve goes to a worker from here on. At 1 arcsecond its first
        # pass alone is 1.7 to 2.2 s over a 604 by 604 window, on the thread
        # that draws. A trace of a real session has one whole preview at 5,643
        # ms, which is what "python3 is not responding" was.
        self.preview.set_runner(QThreadPool.globalInstance().start)
        self.preview.patched.connect(self._surface_previewed)
        self.preview.exact_wanted.connect(self._rebuild_after_idle)
        self.preview.unavailable.connect(self._preview_unavailable)
        self.preview.classesStale.connect(self.unreached.set_stale)
        self.preview.skipped.connect(self._preview_skipped)
        self.preview.freshGround.connect(self._preview_on_fresh_ground)
        self.builder.started.connect(self._surface_starting)
        self.builder.finished.connect(self._surface_built)
        self.builder.failed.connect(self._surface_failed)
        self.water = WaterImporter(self)
        # what the last import found held and no longer upstream - R40's
        # "reported rather than deleted". G5c gives it a dock
        self.gone_from_upstream: list = []
        self.reshaped: list = []             # flattened lakes the last import reshaped
        self.water.started.connect(self._water_starting)
        self.water.finished.connect(self._water_imported)
        self.water.failed.connect(self._water_failed)
        # the main map's spot heights, on the same footing (G9)
        self.heights = WaterImporter(self, fetch=fetch_heights, work=heights_work, held=heights_held)
        self.heights.started.connect(lambda ws: self.statusBar().showMessage(
            'importing spot heights from Overpass…'))
        self.heights.finished.connect(self._heights_imported)
        self.heights.failed.connect(
            lambda why: self.statusBar().showMessage(f'spot-height import failed: {why.splitlines()[0]}'))
        self.gone_dock.chosen.connect(self._choose_gone)
        self.surface_panel.rebuild.connect(self.rebuild_surface)
        self._arcsec = 0.0
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
        # the status line, not the cursor: feeding the last position back through
        # _cursor let a ladder change re-read the ladder from wherever the
        # cursor had been, so opening a square named a neighbour
        self.elevation.changed.connect(lambda _v: self._refresh_status())
        self.editor = EditController(self.map, self.contours, self.elevation, self)
        self.editor.editedWays.connect(self.preview.edited)
        self.editor.editedWays.connect(self._checks_edited)
        self.editor.edited.connect(self._edited)
        self.editor.edited.connect(lambda: self.gone_dock.mark_deleted(self.working_set))
        self.editor.edited.connect(self.elevation_panel.refresh_advice)
        self.editor.message.connect(lambda t: self.statusBar().showMessage(t))
        self.editor.toolChanged.connect(self._tool_changed)
        self.editor.placeAsked.connect(self._show_place)
        self.editor.flattened.connect(lambda sq, f: self.gone_dock.mark_flattened(sq.name, f))
        # what is selected, under the elevation panel: the active elevation is
        # what the tools will use, and this is what the selection already has
        self.selection_panel = SelectionPanel(self.editor, self)
        self.splitDockWidget(self.elevation_panel, self.selection_panel, Qt.Orientation.Vertical)
        self.legend = Legend(self.map, self.surface, self.surface_panel, self.elevation)
        self.controls = MapControls(self.map, self.editor, self.settings)
        self.controls.importWater.connect(self.import_water)
        self.controls.importHeights.connect(self.import_heights)
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
        """The cursor is here: remember it, let the ladder follow the square
        it is over, and say so."""
        self._last_cursor = (lon, lat)
        self.elevation.cursor_at(lon, lat)
        self._refresh_status()

    def _refresh_status(self):
        lon, lat = self._last_cursor
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
        Returns False if a save was declined, so a close can stop. The files
        are written off the UI thread; each square is clean once its own has
        landed, and the status line says so when the last does."""
        dirty = self.editor.history.dirty_squares()
        if not dirty:
            self.statusBar().showMessage('nothing to save')
            return True
        self._asking = True                      # the report waits for the last of these
        try:
            for sq in dirty:
                path = sq.path if sq.path is not None else self._ask_path(sq)
                if path is None:
                    return False
                self._save(sq, path)
        finally:
            self._asking = False
            self._saved()
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
            self._save(sq, path)
            self._saved()

    def _save(self, sq: Square, path: Path) -> None:
        """The square's text taken here, its file written on the writer."""
        pending = save.prepare(sq, self.editor.history, path, self.elevation.model.ladder
                               if self.elevation.square is sq else None)
        if pending.report.framed or pending.report.split:
            self.contours.refresh(sq, set(sq.ways))      # a frame or a split changed what is drawn
        job = None

        def done(_path):
            self._writes.remove(job)
            self._written.append(save.finish(pending, self.editor.history))
            self.squares.set_working_set(self.working_set)   # a blank square is present now
            self._edited()
            self._saved()

        def failed(why):
            self._writes.remove(job)
            first = why.splitlines()[0]
            self.statusBar().showMessage(f'{pending.path.name} not saved: {first}')
            QMessageBox.warning(self, 'Danu', f'{pending.path} was not saved - it is unchanged on disk, '
                                f'and {sq.name} still has its edits:\n\n{first}')

        job = Job(lambda: save.write(pending), done, failed)
        self._writes.append(job)
        self._write_runner(job)

    def _saved(self) -> None:
        """The status line: what is still being written, or, once the last
        has landed, what each save did."""
        if self._asking:
            return
        if self._writes:
            n = len(self._writes)
            self.statusBar().showMessage(f'saving {n} square{"s" * (n != 1)}…')
        elif self._written:
            self.statusBar().showMessage('; '.join(r.describe() for r in self._written))
            self._written = []

    def wait_for_writes(self) -> None:
        """Every save asked for landed, and its answer taken - before a read
        of the files, or a close."""
        if not self._writes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            self._write_pool.waitForDone()
            QApplication.processEvents()                 # the answers, queued to this thread
        finally:
            QApplication.restoreOverrideCursor()

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
        self.wait_for_writes()
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
            self.wait_for_writes()
            if answer == QMessageBox.StandardButton.Save and self.editor.dirty():
                event.ignore()                           # a write failed, and said so
                return
        self.territory.abort()
        self.fetcher.abort()
        # before the builder: the idle timer asks for builds by itself, and one
        # started during teardown would be writing into the directory cleanup
        # is about to remove
        if not self.preview.cleanup():
            self.statusBar().showMessage('a preview was still running')
        self.preview.forget()
        # before the signal object it emits into goes with the window
        if not self.surface.cleanup():
            self.statusBar().showMessage('a recolour was still running')
        if not self.builder.cleanup():
            self.statusBar().showMessage('a build was still running; its working files are left behind')
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
                ('edit.delete_way', 'Delete whole &contour', ed.delete_way),
                ('tool.select', '&Select', lambda: ed.set_tool('select')),
                ('tool.draw', 'Dr&aw contour', lambda: ed.set_tool('draw')),
                ('tool.spot', 'Place spot &height', lambda: ed.set_tool('spot')),
                ('edit.import_water', '&Import water', self.import_water),
                ('edit.import_heights', 'Import spot &heights', self.import_heights),
                ('edit.set_level', 'Set the &level of the water', ed.set_level),
                ('edit.grade', '&Grade from the contours', ed.grade),
                ('edit.grade_network', 'Grade the river &network', ed.grade_network),
                # a lambda, not the method: triggered passes checked=False, which
                # flatten took for a pull-back of 0 m - F flattened with none
                ('edit.flatten', '&Flatten the lake', lambda: ed.flatten()),
                ('edit.burn', '&Burn the climb chosen', lambda: ed.burn()),
                ('edit.burn_all', 'Burn every climb the grade &found', lambda: ed.burn(every=True)),
                ('edit.split', 'S&plit the contour at the node', ed.split),
                ('edit.unglue', '&Unglue the node from the other contours', ed.unglue),
                ('edit.cut_loop', 'Cut &out the loop chosen',
                 lambda: ed.cut_loop(self.checks_dock.current_loop()))):
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
        edit.addAction(self.edit_actions['edit.delete_way'])
        edit.addAction(self.edit_actions['edit.split'])
        edit.addAction(self.edit_actions['edit.unglue'])
        edit.addSeparator()
        edit.addAction(self.edit_actions['tool.select'])
        edit.addAction(self.edit_actions['tool.draw'])
        edit.addAction(self.edit_actions['tool.spot'])
        edit.addSeparator()
        edit.addAction(self.edit_actions['edit.import_water'])
        edit.addAction(self.edit_actions['edit.import_heights'])
        edit.addAction(self.edit_actions['edit.set_level'])
        edit.addAction(self.edit_actions['edit.grade'])
        edit.addAction(self.edit_actions['edit.grade_network'])
        edit.addAction(self.edit_actions['edit.flatten'])
        edit.addAction(self.edit_actions['edit.burn'])
        edit.addAction(self.edit_actions['edit.burn_all'])
        edit.addAction(self.edit_actions['edit.cut_loop'])
        edit.addAction(self.gone_dock.toggleViewAction())
        edit.addAction(self.checks_dock.toggleViewAction())
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
        self.wait_for_writes()                           # what is read is what was saved
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
        # the report names squares of the set it was made against
        self.gone_from_upstream = []
        self.reshaped = []
        self.gone_dock.show_report([], imported=False)
        # the crossing check's index waits for the panel to be opened: 3.6 s on
        # gobras, which opening a working set should not pay for if the
        # checks are not looked at (G8a)
        self.crossing_index = None
        self.loop_index = None
        self.touch_index = None
        self.spot_index = None
        if self.checks_dock.isVisible():
            self._checks_shown(True)
        self.squares.set_working_set(ws)
        self.contours.set_working_set(ws)
        self.elevation.set_working_set(ws, self.zone_dir.name if self.zone_dir else '')
        self.editor.set_working_set(ws)
        w, s, e, n = ws.centre.bounds
        self.map.fit_bounds(w, s, e, n)
        # the view has moved to the square that was opened; the cursor is over
        # it now, whatever it was over before
        self._cursor(*self.map.center_lonlat())
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
        try:
            p = self._loaded_params()
        except (KeyError, OSError) as e:
            self._surface_failed(str(e))
            return False
        if arcsec is not None:
            p = p.with_arcsec(arcsec)
        # before the request, not after: request() starts the build there and
        # then when nothing is running, and the build's own started signal
        # reads this. Setting it afterwards had the status line report the
        # previous build's resolution, which on the first build of a session
        # is the 0 it was initialised to - "building at 0″".
        self._arcsec = p.arcsec
        if not self.surface_panel.show_resolution(p.arcsec):
            # --surface 0.5 builds at 0.5 and the combo has no such entry, so
            # it would go on naming one the build is not using - the very
            # disagreement show_resolution exists to end
            self.statusBar().showMessage(
                f'building at {p.arcsec:g}″, which the resolution list does not offer')
        queued = self.builder.busy
        self.builder.request(self.working_set, p, self.editor.history.dirty_squares())
        if queued:
            # the running build is already superseded; it finishes and is shown
            # as stale while this one runs
            self.surface_panel.building(f'queued at {p.arcsec:g}″…')
            self.statusBar().showMessage('queued behind the build already running')
        return True

    @staticmethod
    def _loaded_params(fallback: float | None = None):
        from ..surface import params as surface_params
        p = surface_params.load()
        # `is not None`, not truthiness: 0.0 is falsy and would silently take
        # elevation.toml's own arcsec, which is 1 - the 77-second build L1 was
        # about, reached by conflating unset with zero all over again
        return p.with_arcsec(fallback) if fallback is not None else p

    def _surface_starting(self):
        self.surface_panel.building(f'building at {self._arcsec:g}″…')
        self.statusBar().showMessage(
            f'building the surface at {self._arcsec:g}″ - the same stages the server runs')

    # --------------------------------------------------------------- water
    def import_water(self) -> bool:
        """R23: the working set's rivers, streams and water bodies, into the
        squares. Asked for by the mapper rather than on opening a set - it
        reaches the network, and what it writes is theirs to undo."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return False
        queued = self.water.busy
        self.water.request(self.working_set)
        if queued:
            self.statusBar().showMessage('already importing; the newer request wins')
        return True

    def import_heights(self) -> bool:
        """R41: the main map's peaks, volcanoes and saddles with a height,
        into the squares as spot heights (G9) - asked for, as water is."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return False
        queued = self.heights.busy
        self.heights.request(self.working_set)
        if queued:
            self.statusBar().showMessage('already importing; the newer request wins')
        return True

    def _heights_imported(self, answer, working_set):
        """One spot-height import, one step on the history, reconciled as
        water is: the height set here kept, a held one upstream no longer
        answers reported and kept."""
        if working_set is not self.working_set:
            self.statusBar().showMessage(
                'the working set changed while the spot heights were fetched - import again')
            return
        self.gone_from_upstream = peaks.gone(working_set, answer.nodes)
        steps = height_commands(answer.placed, working_set)
        if steps:
            self.editor.do_across(steps)
        self.gone_dock.show_report(self.gone_from_upstream, reshaped=[])
        if self.gone_from_upstream:
            self.gone_dock.show()
            self.gone_dock.raise_()
        n = sum(len(v) for v in answer.placed.values())
        kinds = {}
        for v in answer.placed.values():
            for node in v.values():
                kinds[node.tags['natural']] = kinds.get(node.tags['natural'], 0) + 1
        if n:
            said = (f'imported {n} spot height{"s" * (n != 1)} - '
                    + ', '.join(f'{k} {kinds[k]}' for k in peaks.KINDS if k in kinds))
        else:
            said = ('no spot height imported' if answer.beyond
                    else 'no peak or saddle with a height in this working set')
        if answer.beyond:
            said += (f'; {answer.beyond} beyond the contours, not imported - an import once '
                     'they are drawn out to brings them')
        if answer.skipped:
            said += (f'; {len(answer.skipped)} skipped, a height that reads as neither metres nor '
                     'feet')
        if self.gone_from_upstream:
            said += f'; {len(self.gone_from_upstream)} held no longer upstream, kept'
        self.statusBar().showMessage(said + ('. Ctrl+Z takes them all back' if n else ''))

    def _water_starting(self, working_set):
        # the set the fetch is for, which is not always the one open: a queued
        # request starts when the one before it answers, and the mapper can
        # have moved in between
        w, s, e, n = working_set.bounds
        self.statusBar().showMessage(
            f'importing water for {w:g}..{e:g} by {s:g}..{n:g} from Overpass…')

    def _water_imported(self, answer, working_set):
        """One import, one step on the history - R40 - however many squares it
        landed in.

        Against the set it was asked for, not the one open now. The squares
        were chosen by that set's names; if the mapper has opened another
        while the fetch was out, the names may still match and the ``Square``
        objects behind them will not, so the features would land in squares
        nobody asked about. Importing again is a second and a half.
        """
        if working_set is not self.working_set:
            self.statusBar().showMessage(
                'the working set changed while the water was fetched - import again')
            return
        placed = answer.placed
        # compared before the import is applied, while a held lake relation
        # still names the ring upstream has since replaced - see water/gone.py
        self.gone_from_upstream = gone(working_set, answer.ways, answer.relations)
        # and the lakes flattened here, as they stand, to see which the
        # import reshapes - their fill lines and clipped contours were laid
        # against the old outline (G7a-bis)
        was_flat = flatten.flattened(working_set)
        kept = (f'; {len(self.gone_from_upstream)} held no longer upstream, kept'
                if self.gone_from_upstream else '')
        steps = water_commands(placed, working_set)
        if steps:
            # the editor's own path, not a copy of it: see EditController.do_across
            self.editor.do_across(steps)
        self.reshaped = flatten.reshaped(was_flat, working_set)
        self.gone_dock.show_report(self.gone_from_upstream, reshaped=self.reshaped)
        if self.gone_from_upstream or self.reshaped:
            self.gone_dock.show()
            self.gone_dock.raise_()
        if self.reshaped:
            kept += (f'; {len(self.reshaped)} flattened lake{"s" * (len(self.reshaped) != 1)} '
                     'reshaped, to flatten again')
        if not steps:
            self.statusBar().showMessage(f'no water in this working set{kept}')
            return
        features = sum(len(w) for w in placed.values())
        # named per square because the share is not even: on the gobras 3x3
        # one square takes seventy per cent of them
        where = ', '.join(f'{name} {len(placed[name])}' for name in sorted(placed, key=str))
        self.statusBar().showMessage(
            f'imported {features} water features - {where}{kept}. '
            f'Ctrl+Z takes them all back')

    def _choose_gone(self, g):
        """A row of the report chosen: select the feature as the map would,
        and bring it into view. What follows is the editor's own - Shift+Delete
        takes it away, a lake with its untagged rings; doing nothing keeps it."""
        ws = self.working_set
        square = ws.squares.get(g.square) if ws is not None else None
        holder = ({'relation': square.relations, 'node': square.nodes}.get(g.kind, square.ways)
                  if square else {})
        feature = holder.get(g.id)
        if feature is None:
            self.statusBar().showMessage(f'{g.describe()}: deleted here since the import')
            return
        if g.kind == 'node':
            # a spot height (G9): selected as a click on it would, and Delete takes it
            self.editor.set_tool('select')
            self.editor.selection = Selection(square, None, g.id)
            self.editor.overlay.update()
            self._show_place(feature.lon, feature.lat, feature.lon, feature.lat)
            key = self.settings.key('edit.delete') or 'Delete'
            self.statusBar().showMessage(f'{g.describe()} - {key} removes it, doing nothing keeps it')
            return
        if g.kind == 'relation':
            ways = [square.ways[mem.ref] for mem in feature.members
                    if mem.type == 'way' and mem.ref in square.ways]
            selection = Selection(square, None, relation=feature)
        else:
            ways, selection = [feature], Selection(square, feature)
        self.editor.set_tool('select')
        self.editor.selection = selection
        self.editor.overlay.update()
        pts = [square.nodes[r] for w in ways for r in w.refs if r in square.nodes]
        if pts:
            lons, lats = [n.lon for n in pts], [n.lat for n in pts]
            w, e, s, n = min(lons), max(lons), min(lats), max(lats)
            # a margin, so the feature is seen against what is round it
            pad = max(e - w, n - s) * 0.15 or 0.005
            self.map.fit_bounds(w - pad, s - pad, e + pad, n + pad)
        if isinstance(g, flatten.Reshaped):
            key = self.settings.key('edit.flatten') or 'F'
            self.statusBar().showMessage(f'{g.describe()} - {key} flattens it again')
            return
        key = self.settings.key('edit.delete_way') or 'Shift+Delete'
        self.statusBar().showMessage(f'{g.describe()} - {key} removes it, doing nothing keeps it')

    def _checks_opened(self, on: bool) -> None:
        """Opened from the menu: brought to the front of the tabs it shares,
        once Qt has shown it - raised in the same call it is not yet there to
        raise - and its crossings found."""
        if on:
            QTimer.singleShot(0, self.checks_dock.raise_)
            self._checks_shown(True)

    def _checks_shown(self, visible: bool) -> None:
        """The panel opened: the working set's checks found, once, on a
        worker - after that an edit keeps them."""
        if visible and self.working_set is not None and self._checks_job is None and (
                self.crossing_index is None or self.crossing_index.working_set is not self.working_set):
            ws = self.working_set
            self._checks_missed = []
            self.checks_dock.finding()
            job = None

            def done(indexes):
                self._checks_job = None
                if ws is not self.working_set:
                    self._checks_shown(self.checks_dock.isVisible())   # a set opened meanwhile
                    return
                self.crossing_index, self.loop_index, self.touch_index, self.spot_index = indexes
                missed, self._checks_missed = self._checks_missed, []
                for square, ways, spot_ids in missed:
                    self._checks_edited(square, ways, spot_ids)
                self._refresh_checks()

            def failed(why):
                self._checks_job = None
                first = why.splitlines()[0]
                self.statusBar().showMessage(f'the checks failed: {first}')
                self.checks_dock.summary.setText(f'The checks could not be found: {first}. '
                                                 'Close the panel and open it again to try again.')

            job = Job(lambda: find_checks(ws), done, failed)
            self._checks_job = job
            self._checks_runner(job)
            return
        self._refresh_marks()

    def _checks_edited(self, square, ways, spot_ids) -> None:
        """An edit's ways asked again at once - milliseconds a way - and the
        panel redrawn a moment later, once a drag has stopped. One made while
        the first scan runs is kept for it."""
        if self._checks_job is not None:
            self._checks_missed.append((square, set(ways or ()), set(spot_ids or ())))
            return
        if self.spot_index is not None and (ways or spot_ids):
            # a spot height moved or re-levelled, or a ring round one changed
            self.spot_index.update(square, ways or (), spot_ids or ())
            self._checks_due.start()
        if self.crossing_index is not None and ways:
            self.crossing_index.update(square, ways)
            if self.loop_index is not None:
                self.loop_index.update(square, ways)
            if self.touch_index is not None:
                self.touch_index.update(square, ways)
            self._checks_due.start()

    def _refresh_checks(self) -> None:
        found = self.crossing_index.crossings() if self.crossing_index is not None else []
        self.checks_dock.show_crossings(found)
        self.checks_dock.show_loops(self.loop_index.loops() if self.loop_index is not None else [])
        self.checks_dock.show_touches(self.touch_index.touches() if self.touch_index is not None else [])
        self.checks_dock.show_spots(self.spot_index.contradictions() if self.spot_index is not None else [])
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        """The crossings marked on the map while the panel is open, and not
        otherwise: 6,714 red crosses over gobras are what the panel is for,
        not what drawing a contour is."""
        on = self.checks_dock.isVisible() and self.crossing_index is not None
        self.editor.marks = ([m.lonlat_to_scene(c.lon, c.lat) for c in self.crossing_index.crossings()]
                             + [m.lonlat_to_scene(lp.lon, lp.lat)
                                for lp in (self.loop_index.loops() if self.loop_index is not None else [])]
                             + [m.lonlat_to_scene(t.lon, t.lat)
                                for t in (self.touch_index.touches() if self.touch_index is not None else [])]
                             + [m.lonlat_to_scene(c.lon, c.lat)
                                for c in (self.spot_index.contradictions() if self.spot_index is not None else [])]
                             if on else [])
        if not on:
            self.editor.marks_focus = []
        self.editor.overlay.update()

    def _choose_crossing(self, key, found) -> None:
        """A row of the checks panel chosen: its contour selected, its
        crossings ringed and brought into view."""
        ws = self.working_set
        square = ws.squares.get(key[0]) if ws is not None else None
        way = square.ways.get(key[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {key[1]} is no longer in {key[0]}')
            return
        self.editor.set_tool('select')
        self.editor.selection = Selection(square, way)
        self.editor.marks_focus = [m.lonlat_to_scene(c.lon, c.lat) for c in found]
        lons, lats = [c.lon for c in found], [c.lat for c in found]
        self._show_place(min(lons), min(lats), max(lons), max(lats))
        self.editor.overlay.update()
        n = len(found)
        self.statusBar().showMessage(
            f'the {key[2]:g} m contour, way {key[1]} - {n} crossing{"s" * (n != 1)} ringed; '
            'delete it or redraw over it, whichever of the two is wrong')

    def _choose_loop(self, loop) -> None:
        """A contour crossing itself, chosen in the checks panel: it
        selected, the place ringed and brought into view - G8c."""
        ws = self.working_set
        square = ws.squares.get(loop.contour[0]) if ws is not None else None
        way = square.ways.get(loop.contour[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {loop.contour[1]} is no longer in {loop.contour[0]}')
            return
        self.editor.set_tool('select')
        self.editor.selection = Selection(square, way)
        self.editor.marks_focus = [m.lonlat_to_scene(loop.lon, loop.lat)]
        self._show_place(loop.lon, loop.lat, loop.lon, loop.lat)
        self.editor.overlay.update()
        key = self.settings.key('edit.cut_loop') or 'O'
        self.statusBar().showMessage(f'{loop.explain()} - ringed; {key} proposes the loop cut out')

    def _choose_touch(self, touch) -> None:
        """Contours that touch, chosen in the checks panel: the first of
        them selected - at the node, for one two levels share, so U unglues
        it - the place ringed and brought into view (G8e)."""
        ws = self.working_set
        square = ws.squares.get(touch.a[0]) if ws is not None else None
        way = square.ways.get(touch.a[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {touch.a[1]} is no longer in {touch.a[0]}')
            return
        self.editor.set_tool('select')
        node = touch.node if touch.kind == 'shared' and touch.node in way.refs else None
        self.editor.selection = Selection(square, way, node)
        self.editor.marks_focus = [m.lonlat_to_scene(touch.lon, touch.lat)]
        self._show_place(touch.lon, touch.lat, touch.lon, touch.lat)
        self.editor.overlay.update()
        self.statusBar().showMessage(f'{touch.explain()} - ringed')

    def _choose_spot(self, c) -> None:
        """A spot height the rings round it contradict, chosen: it selected,
        as a click on it would - its height in the panel to set - and ringed
        and brought into view (R38)."""
        ws = self.working_set
        square = ws.squares.get(c.square) if ws is not None else None
        if square is None or c.node not in square.nodes:
            self.statusBar().showMessage(f'that spot height is no longer in {c.square}')
            return
        self.editor.set_tool('select')
        self.editor.selection = Selection(square, None, c.node)
        self.editor.marks_focus = [m.lonlat_to_scene(c.lon, c.lat)]
        self._show_place(c.lon, c.lat, c.lon, c.lat)
        self.editor.overlay.update()
        self.statusBar().showMessage(f'{c.explain()} - ringed')

    def _show_place(self, w: float, s: float, e: float, n: float):
        """The map to something a grade found - G6d-3. A margin round a span,
        so it is seen against what is round it, and never nearer than z16: a
        climb of a few hundred metres went to z19 and a gap to z18, too close
        to see where on the river they are. A zoom and not a margin, since
        the zoom a margin comes to depends on the size of the window."""
        pad = max((e - w) * 0.15, (n - s) * 0.15)
        if pad:
            self.map.fit_bounds(w - pad, s - pad, e + pad, n + pad)
        if not pad or self.map.zoom > SHOW_ZOOM:
            self.map.set_zoom(SHOW_ZOOM)
            self.map.center_on_lonlat((w + e) / 2, (s + n) / 2)

    def _water_failed(self, why: str):
        self.statusBar().showMessage(f'water import failed: {why.splitlines()[0]}')

    def _preview_unavailable(self, why: str):
        """Said in the status bar, not over the panel's own line.

        adopt() runs after the panel has reported the build, and the panel's
        status label is its only build feedback - so writing there replaced
        "surface built in N s" with the preview note on every 1″ build."""
        self.statusBar().showMessage(why)

    def _preview_on_fresh_ground(self, ways):
        """A contour drawn beyond the drawn envelope shows nothing until a
        rebuild, so say that rather than let it look like a surface that
        declined to move."""
        self.statusBar().showMessage(
            f'{len(ways)} contour{"" if len(ways) == 1 else "s"} on ground the '
            f'surface does not cover yet - rebuilding to reach it')

    def _preview_skipped(self, edits: int):
        """A gesture too broken up to preview between keystrokes.

        Nothing was drawn, so nothing is claimed: the surface on screen is
        still the exact one and the provisional rim stays off. Saying "preview:
        0 cells" and drawing the rim anyway would have the at-a-glance
        distinction R19 asks for saying the opposite of the truth.
        """
        self.statusBar().showMessage(
            f'{edits} separate edits - too many to preview together; '
            f'rebuilding exactly on idle')

    def _surface_previewed(self, rects, seconds):
        """A patch went into the arrays the layer draws; recolour what moved.

        The rectangles, not the whole surface. I had written that compose() was
        "the UI thread's cheap end" and that splitting it to a rectangle "would
        buy a few milliseconds of the fifty", and asserted both without
        measuring either. On the gobras 3x3 at 3 arcseconds a whole recolour is
        1,472 ms in shaded relief - twenty-four times the solve it follows. A
        preview worth 62 ms was spending a second and a half being shown.
        """
        painted = 0
        for y0, x0, rows, cols in rects:
            if self.surface.recolour_box(y0, x0, rows, cols):
                painted += rows * cols
        # not unreached: its classes are the build's and a preview does not
        # bring them back, so recomposing it would only redraw the same stale
        # overlay. It is told it is stale instead - see classesStale
        self.surface.set_preview(True)
        self.surface_panel.previewed(seconds)
        self.statusBar().showMessage(
            f'preview: {painted:,} cells in {seconds * 1000:.0f} ms - exact on idle')

    def _rebuild_after_idle(self):
        """The drawing stopped, so settle the preview's approximations."""
        if self.working_set is None or not self.editor.history.dirty_squares():
            return
        if not self._arcsec:
            # nothing has been built, so there is no surface to settle. Passing
            # None here took elevation.toml's default, which is 1 arcsecond:
            # open a square, draw a contour, wait, and a 77-second build nobody
            # asked for starts - the surprise c478fa8 exists to prevent,
            # through a different door.
            return
        # the resolution this surface is at, not whatever the combo says: they
        # are the same now that a build moves the combo, and an idle rebuild is
        # the wrong moment to discover they are not
        self.rebuild_surface(self._arcsec)

    def _surface_built(self, built, stale=False, seconds=0.0):
        # seconds comes from the builder: once builds overlap, how long one
        # took is not something a single attribute here can hold
        self.surface.set_shaded(built.shaded)
        self.legend.refresh()
        self.unreached.set_shaded(built.shaded)
        self.envelope.set_rings(built.envelope_rings)
        self.surface_panel.built(built.shaded, seconds)
        self.surface.set_preview(stale)     # a superseded build is provisional too
        # Both, for every build, stale or not.
        #
        # The driver must point at the Shaded the layer is drawing, because the
        # layer takes every build: a driver that skipped the stale ones went on
        # splicing into the array of the build before, which nobody draws, and
        # previews quietly stopped appearing.
        #
        # And it must work from that build's grids for the same reason, which
        # took a trace to see. Adopting only the builds that are not stale was
        # meant to keep the approximations restarting from an exact answer
        # rather than compounding. At 1 arcsecond it does the opposite: a build
        # takes a hundred seconds, an edit lands inside every one of them, so
        # every build is stale and none is ever adopted. A traced session has
        # five builds and one adopt - the preview working from the first
        # build's surface all the way through, splicing patches derived from it
        # over the exact ground each later build had just put on screen. That
        # is the surface being lost.
        #
        # A stale build's grids are not the newest edits, but they are the
        # newest exact answer there is, and strictly closer than the one five
        # builds back. What the preview owes each edit it re-burns from
        # `contours`, which has every edit in it either way.
        self.preview.follow(built.shaded)
        self.preview.adopt(built, built.params or
                           self._loaded_params(fallback=self._arcsec))
        if stale:
            self.statusBar().showMessage(
                f'surface built in {seconds:.0f} s, already out of date - rebuilding')
        else:
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

    quieten_qt()          # before the first request; see danu.ui.messages
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
