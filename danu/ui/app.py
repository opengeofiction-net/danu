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

import numpy as np
from PySide6.QtCore import QByteArray, QRectF, QStandardPaths, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from ..checks import crossings, files, inside, loops, spots, touches
from ..checks import surface as surface_checks
from ..core import edits, make_square, save, territory
from ..core.autosave import Store
from ..core.square import Square, SquareName, WorkingSet
from ..surface import along, shade
from ..surface import difference as surface_difference
from ..water import flatten, overpass, peaks
from ..water.gone import gone
from . import autosave as autosave_ui
from . import config, josm, oauth, session, wms
from . import mercator as m
from .autosave import AutoSaver
from .background import Job
from .checks_dock import ChecksDock
from .contours import ContourLayer
from .elevation import PICK_PX, ElevationControl, ElevationPanel
from .gone_dock import GoneDock
from .josm import JosmRemote
from .layers import LayersChooser
from .legend import Legend
from .loader import WorkingSetLoader
from .loupe import Loupe
from .mapcontrols import MapControls
from .mapview import MapView
from .measure import MeasureTool, ProfileDock
from .messages import install as quieten_qt
from .mirror import Importer
from .open_dialog import OpenDialog
from .overlays import EnvelopeItem, UnreachedLayer
from .published import PublishedDem
from .selection_panel import SelectionPanel
from .settings import REBUILD_KEY, Settings
from .squares import SquaresItem
from .surface import ARCSEC, SurfaceBuilder, SurfaceLayer, SurfacePanel
from .territory import TerritoryFetcher
from .tiles import TileFetcher, TileLayer
from .tools import EditController, Selection
from .usage import UsageLog
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


def user_data_dir() -> Path:
    """~/.local/share/danu on Linux: the autosave and, later, the session."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation))


def user_cache_dir() -> Path:
    """~/.cache/danu on Linux; tiles and, later, Overpass live under it."""
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation))


# the checks' indexes in the order the scan builds them, and what the panel
# calls each while it does
CHECKS = (('crossings', lambda ws, _: crossings.Index(ws)),
          ('contours crossing themselves', lambda ws, _: loops.Index(ws)),
          ('contours touching', lambda ws, _: touches.Index(ws)),
          ('spot heights', lambda ws, _: spots.Index(ws)),
          ('what the files say', lambda ws, _: files.Index(ws)),
          ('what lies inside the rings', lambda ws, bare_min: inside.Index(ws, bare_min)))


def find_checks(ws, tries: int = 5, bare_min: float = inside.BARE_MIN_M2, report=None):
    """The checks' indexes over a working set - on a worker, while the set
    goes on being edited on the UI thread. ``report`` is told (step, of,
    name) before each, so the panel can say how far it has got. An edit
    that changes a dict under the scan stops it, and it starts again; one
    that changes a way it has read is put to the indexes when they land, so
    what was read of that way is asked again."""
    for attempt in range(tries):
        try:
            out = []
            for k, (name, index) in enumerate(CHECKS):
                if report is not None:
                    report((k, len(CHECKS), name))
                out.append(index(ws, bare_min))
            return tuple(out)
        except RuntimeError:                   # changed size during iteration
            if attempt == tries - 1:
                raise


class MainWindow(QMainWindow):
    def __init__(self, layers: list[config.Layer], cache_dir: Path | None = None,
                 settings: Settings | None = None, territory_fetcher: TerritoryFetcher | None = None,
                 data_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle('Danu')
        self.layers = layers
        self.settings = settings if settings is not None else Settings()
        self.map = MapView(self)
        self.setCentralWidget(self.map)
        self.fetcher = TileFetcher(cache_dir, parent=self)
        # the tests hand in a fetcher pointed at files; the app fetches the published ones
        self.territory = territory_fetcher or TerritoryFetcher(
            cache_dir.parent / 'territory' if cache_dir else None, parent=self,
            geometry_url=self.settings.url('territory/geometry'), attributes_url=self.settings.url('territory/owners'))
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
        # the layers, chosen from a button on the map (H6b) - see MapControls
        self.layer_chooser = LayersChooser(self.tile_items)
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
        # slope or elevation: the reading under a still cursor follows the mode
        self.surface_panel.styleChanged.connect(self._cursor_reading_again)
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
        self.file_index = None                  # what the files say: long ways, ele, the ladder (H1a)
        self.inside_index = None                # what lies inside the rings: lakes, bare rings (H1b)
        self.surface_findings = None            # what the last build said (H2), or None
        self._surface_found_at = ''             # when that build landed
        self._surface_stale = False             # edits since it
        self._surface_pending = False           # a build running that will say them
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
        self.checks_dock.findingChosen.connect(self._choose_finding)
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
        # the view at 1 arcsecond, at z15 and closer (I3b); solved on a worker
        # for the same reason the preview is
        from .fine import FineDriver, FineLayer
        self.fine = FineDriver(self)
        self.fine.set_runner(QThreadPool.globalInstance().start)
        self.fine.arrived.connect(self._fine_arrived)
        self.fine.unavailable.connect(lambda why: self.statusBar().showMessage(why))
        # drawn over the surface, as a child of its layer so it fades and
        # hides with it (I3c)
        self.fine_layer = FineLayer(self.surface, self.fine)
        self.fine.arrived.connect(self.fine_layer.arrived)
        self.fine.cleared.connect(self.fine_layer.forget)
        # and what is read off the ground follows what is drawn (I3d): the
        # reading under a still cursor, and a line measured before the tiles
        # came, read again when they come or go
        for sig in (self.fine.arrived, self.fine.cleared):
            sig.connect(self._cursor_reading_again)
            sig.connect(lambda *_: self.measure.surface_changed())
        self.map.zoomChanged.connect(lambda _: self.measure.surface_changed())
        self.map.zoomChanged.connect(self.fine_layer.set_zoom)
        self.fine_layer.set_zoom(self.map.zoom)
        # an edit leaves the tiles it reaches describing ground that has
        # changed: once the preview has the 3 arcsecond surface right, those
        # go and the view is solved again (I4) - and where it could not
        # preview, every tile goes rather than any staying wrong
        self.preview.reached.connect(self.fine.reached)
        for sig in (self.preview.skipped, self.preview.freshGround):
            sig.connect(lambda *_: self.fine.edited())
        self.builder.started.connect(self._surface_starting)
        self.builder.finished.connect(self._surface_built)
        # the surface's checks (H2) ride on a build, while the panel is open
        self.builder.checks_snapshot = (
            lambda ws: surface_checks.snapshot(ws) if self.checks_dock.isVisible() else None)
        self.builder.failed.connect(self._surface_failed)
        self.water = WaterImporter(self, fetch=lambda bounds: overpass.fetch(bounds, url=self.settings.overpass_url))
        # what the last import found held and no longer upstream - R40's
        # "reported rather than deleted". G5c gives it a dock
        self.gone_from_upstream: list = []
        self.reshaped: list = []             # flattened lakes the last import reshaped
        self.water.started.connect(self._water_starting)
        self.water.finished.connect(self._water_imported)
        self.water.failed.connect(self._water_failed)
        # the main map's spot heights, on the same footing (G9)
        self.heights = WaterImporter(self, fetch=lambda bounds: fetch_heights(bounds, self.settings.overpass_url),
                                     work=heights_work, held=heights_held)
        self.heights.started.connect(lambda ws: self.statusBar().showMessage(
            'importing spot heights from Overpass…'))
        self.heights.finished.connect(self._heights_imported)
        self.heights.failed.connect(
            lambda why: self.statusBar().showMessage(f'spot-height import failed: {why.splitlines()[0]}'))
        self.gone_dock.chosen.connect(self._choose_gone)
        self.gone_dock.takeHeights.connect(self._take_heights)
        # JOSM's remote control, for the water and peaks fixed on the main map
        self.josm = JosmRemote(self.settings.josm_url, self)
        self.josm.answered.connect(lambda what: self.statusBar().showMessage(f'JOSM: {what}'))
        self.josm.failed.connect(self.statusBar().showMessage)
        self.checks_dock.josm_btn.clicked.connect(self.show_in_josm)
        self.gone_dock.josm_btn.clicked.connect(self.show_in_josm)
        self.surface_panel.rebuild.connect(self.rebuild_surface)
        self._arcsec = 0.0
        self.squares = SquaresItem()
        self.map.scene().addItem(self.squares)
        self.contours = ContourLayer()
        self.contours.ground = self.surface       # what 'height' burns its colours into
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
        self.editor.message.connect(lambda t: self.statusBar().showMessage(t))
        self.editor.toolChanged.connect(self._tool_changed)
        self.editor.placeAsked.connect(self._show_place)
        self.editor.flattened.connect(lambda sq, f: self.gone_dock.mark_flattened(sq.name, f))
        # measure and profile (H3b): the editor routes the tool's input to it
        self.measure = MeasureTool(self.map, self.contours, self.surface, self)
        self.editor.measure = self.measure
        self.measure.message.connect(lambda t: self.statusBar().showMessage(t))
        self.editor.edited.connect(self.measure.edited)
        self.profile_dock = ProfileDock(self.measure, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profile_dock)
        self.profile_dock.hide()
        self.profile_dock.placeChosen.connect(lambda lon, lat: self._show_place(lon, lat, lon, lat))
        # filled under its line in the map's colours, and again when they change
        self.profile_dock.plot.colourer = self._profile_colours
        # what is selected, under the elevation panel: the active elevation is
        # what the tools will use, and this is what the selection already has
        self.selection_panel = SelectionPanel(self.editor, self)
        self.splitDockWidget(self.elevation_panel, self.selection_panel, Qt.Orientation.Vertical)
        self.legend = Legend(self.map, self.surface, self.surface_panel, self.elevation)
        self.legend.changed.connect(self.profile_dock.plot.update)       # the fill follows the map's colours
        # the difference (H3c): the published DEM fetched when it is first
        # asked for, and the exact build less it worked out on a worker
        self.published = PublishedDem(cache_dir.parent / 'published' if cache_dir else None,
                                      url=self.settings.url('published/dem'), parent=self)
        self.published.ready.connect(self._published_ready)
        self.published.failed.connect(self._published_failed)
        self._difference_runner = QThreadPool.globalInstance().start
        self._difference_job = None
        self._difference_for = None             # the build it is being worked out for
        self.surface_panel.styleChanged.connect(lambda _style: self._difference_wanted())
        self.controls = MapControls(self.map, self.editor, self.settings, layers=self.layer_chooser)
        self.controls.importWater.connect(self.import_water)
        self.controls.importHeights.connect(self.import_heights)
        # magnify (H3d): the map again at the cursor, a few times over
        self.loupe = Loupe(self.map, self.surface)
        self.map.loupe = self.loupe
        # not losing work (H4): each dirty square's change, under the data
        # directory, as the edits pause and once a minute; none without one,
        # which is how the tests make a window that writes nowhere
        self.autosave = AutoSaver(self, Store(data_dir / 'autosave'), self) if data_dir else None
        # and the usage log (H4c): what was done, to replay a bug from
        self.usage = None
        # the surface served to JOSM (H5), started when it is first asked for
        self.wms = None
        if self.autosave is not None:
            self.editor.edited.connect(self.autosave.edited)
            self.autosave.failed.connect(lambda t: self.statusBar().showMessage(t))
        self.map.elevationWheel.connect(self.elevation.step)
        self.map.opacityWheel.connect(self._opacity_wheel)
        self.loader = WorkingSetLoader(self)
        self.loader.finished.connect(self._loaded)
        self.loader.failed.connect(self._load_failed)
        self._pending: tuple[Path, SquareName, int] | None = None
        if data_dir:
            # before the menus, so each action is told to the log before its
            # own slot runs, and the log has it ahead of what it did
            self.usage = UsageLog(self, data_dir / 'usage', self)
            self.editor.stepped.connect(self.usage.stepped)
        self.importer = Importer(self, self)
        self.importer.message.connect(lambda t: self.statusBar().showMessage(t) if t else None)
        self.importer.finished.connect(self._imported)
        self._menus()
        self._docked_only()
        self._default_layout = self.saveState()       # what Reset panels goes back to
        # signing in to OGF (H6f): the tests hand in where the browser goes
        self.signin = None
        self._signin_options: dict = {}
        self._account_nam = None
        self._account_changed()
        self._check_signed_in()
        if self.usage is not None:
            self.editor.toolChanged.connect(lambda name: self.usage.write('tool', name=name))
            self.edit_actions['view.magnify'].toggled.connect(lambda on: self.usage.write('magnify', on=on))
        self._territory = QLabel('')
        self._territory.setToolTip('the territory and owner under the working set, from the wiki and territory.json')
        self.statusBar().addPermanentWidget(self._territory)
        self._status = QLabel()
        self.statusBar().addPermanentWidget(self._status)
        self.map.cursorMoved.connect(self._cursor)
        self.map.setFocus()
        self.map.zoomChanged.connect(lambda _: self._cursor(*self.map.center_lonlat()))
        # the view scaling (H3a): the ramp over the land on screen, told once
        # the map comes to rest rather than on every step of a pan - a recolour
        # is a second and a half at 3 arcseconds
        self._view_settle = QTimer(self)
        self._view_settle.setSingleShot(True)
        self._view_settle.setInterval(400)
        self._view_settle.timeout.connect(self._view_settled)
        # the session (H4b): written a second after anything it holds changes -
        # the view's once it has come to rest, 400 ms on -
        # and on closing, so a Danu killed reopens where it was as well
        self.session_path = data_dir / session.FILE if data_dir else None
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(1000)
        self._session_timer.timeout.connect(self.write_session)
        if self.session_path is not None:
            for sig in (self._view_settle.timeout, self.surface_panel.styleChanged, self.editor.toolChanged,
                        self.loader.finished, self.elevation.changed, self.layer_chooser.group.idToggled,
                        self.layer_chooser.slider.valueChanged, self.edit_actions['view.magnify'].toggled):
                sig.connect(lambda *_: self._session_timer.start())
        self.map.zoomChanged.connect(lambda _: self._view_settle.start())
        self.map.horizontalScrollBar().valueChanged.connect(lambda _: self._view_settle.start())
        self.map.verticalScrollBar().valueChanged.connect(lambda _: self._view_settle.start())
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
        """The active elevation, what the surface reads under the cursor,
        where, and the zoom."""
        lon, lat = self._last_cursor
        reading = self._surface_reading(lon, lat)
        self._status.setText(f'{self.elevation.model.tag:>5} m   {reading}{lat:9.5f}  {lon:10.5f}   z{self.map.zoom}')

    def _surface_reading(self, lon: float, lat: float) -> str:
        """The surface on screen under a point: its elevation, or its slope
        when that is what is shown - from the arrays the layer draws, so a
        preview's patch reads as it looks. Nothing off the surface or with
        none built."""
        if self.surface.shaded is None:
            return ''
        x, y = m.lonlat_to_scene(lon, lat)
        # the 1 arcsecond ground where that is what is drawn here (I3d)
        shaded = self.surface.finest(QRectF(x, y, 0, 0))
        left, top, right, bottom = shaded.scene_rect
        rows, cols = shaded.dem.shape
        # the cell the profile reads too (H3b), by the one function
        z = float(along.sample(shaded.dem, shaded.scene_rect, np.array([[x, y]]))[0])
        if np.isnan(z):
            return ''
        c = int(np.floor((x - left) / (right - left) * cols))
        r = int(np.floor((y - top) / (bottom - top) * rows))
        if self.surface.style.mode == 'difference':
            diff = shaded.difference
            if diff is None:
                return ''
            v = float(diff[r, c]) if 0 <= r < rows and 0 <= c < cols else float('nan')
            if np.isnan(v):
                return 'not published   '
            if abs(v) < surface_difference.UNCHANGED_M:
                return 'unchanged   '
            return f'changed {v:+,.1f} m   '
        if z <= 0:
            return 'sea   '
        if self.surface.style.mode == 'slope':
            a, b = max(r - 1, 0), min(r + 2, rows)
            c0, c1 = max(c - 1, 0), min(c + 2, cols)
            deg = shade.slope_degrees(shaded.dem[a:b, c0:c1],
                                      (0.0, shaded.geotransform[1], 0.0, shaded.geotransform[3], 0.0,
                                       shaded.geotransform[5]), a)
            return f'slope {float(deg[r - a, c - c0]):.1f}°   '
        return f'ground {z:,.0f} m   '

    def _cursor_reading_again(self, *_):
        """The surface or its style changed under a still cursor."""
        self._refresh_status()

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
        line, warn = territory.describe(found, self.settings.user, self.settings.admin and bool(self.settings.token))
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

    # ---------------------------------------------------------- signing in
    def account(self) -> None:
        """File's sign in, or sign out once signed in (H6f)."""
        if self.settings.token:
            self.sign_out()
        else:
            self.sign_in()

    def sign_in(self) -> None:
        if self.signin is not None:
            self.signin.stop()
        self.signin = oauth.SignIn(self.settings.server_url, self, **self._signin_options)
        self.signin.waiting.connect(self.statusBar().showMessage)
        self.signin.failed.connect(lambda why: self.statusBar().showMessage(f'not signed in: {why}'))
        self.signin.signedIn.connect(self._signed_in)
        self.signin.start()

    def _signed_in(self, name: str, token: str, roles: list) -> None:
        self.settings.user, self.settings.token, self.settings.roles = name, token, roles
        self.settings.q.sync()
        oauth.private(self.settings.file)
        self._account_changed()
        self.statusBar().showMessage(f'signed in to OGF as {name}' + (' - an administrator' if self.settings.admin else ''))

    def sign_out(self) -> None:
        token, name = self.settings.token, self.settings.user
        self.settings.token, self.settings.user, self.settings.roles = '', '', []
        if token:
            oauth.revoke(self._nam(), self.settings.server_url, token)
        self._account_changed()
        self.statusBar().showMessage(f'signed out of OGF{f" - {name}" if name else ""}')

    def _check_signed_in(self) -> None:
        """At start: a token kept is asked who it is for. One the server no
        longer takes is forgotten; the server not reached, it is kept."""
        if not self.settings.token:
            return

        def refused(why):
            self.settings.token, self.settings.user, self.settings.roles = '', '', []
            self.statusBar().showMessage(f'signed out of OGF: {why}')
            self._account_changed()

        def ok(name, roles):
            if (name, roles) != (self.settings.user, self.settings.roles):
                self.settings.user, self.settings.roles = name, roles
                self._account_changed()
        oauth.details(self._nam(), self.settings.server_url, self.settings.token, ok,
                      lambda why: self.statusBar().showMessage(f'OGF: {why}'), refused)

    def _nam(self):
        if self._account_nam is None:
            from PySide6.QtNetwork import QNetworkAccessManager
            self._account_nam = QNetworkAccessManager(self)
        return self._account_nam

    def _account_changed(self) -> None:
        user = self.settings.user if self.settings.token else ''
        self.account_action.setText(f'Sign &out ({user})' if user else 'Sign &in to OGF…')
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
        pending = save.prepare(sq, self.editor.history, path)
        if pending.report.framed or pending.report.split:
            self.contours.refresh(sq, set(sq.ways))      # a frame or a split changed what is drawn
        job = None

        def done(_path):
            self._writes.remove(job)
            self._written.append(save.finish(pending, self.editor.history))
            if self.autosave is not None:
                self.autosave.saved(sq)
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
            if answer == QMessageBox.StandardButton.Discard and self.autosave is not None:
                self.autosave.discard()                  # thrown away on purpose, autosave and all
        self.write_session()
        if self.wms is not None:
            self.wms.stop()
            self.wms = None
        if self.usage is not None:
            self.usage.close()
        self.territory.abort()
        self.fetcher.abort()
        # before the builder: the idle timer asks for builds by itself, and one
        # started during teardown would be writing into the directory cleanup
        # is about to remove
        if not self.preview.cleanup():
            self.statusBar().showMessage('a preview was still running')
        self.preview.forget()
        if not self.fine.cleanup():
            self.statusBar().showMessage('a 1" view was still being solved')
        self.fine.forget()
        # before the signal object it emits into goes with the window
        if not self.surface.cleanup():
            self.statusBar().showMessage('a recolour was still running')
        if not self.builder.cleanup():
            self.statusBar().showMessage('a build was still running; its working files are left behind')
        super().closeEvent(event)

    def write_session(self) -> None:
        """The session as it stands, to its file - H4b."""
        self._session_timer.stop()
        if self.session_path is None:
            return
        try:
            session.write(self.session_path, session.capture(self))
        except OSError as e:
            self.statusBar().showMessage(f'the session was not written: {e}')

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
    def _logged(self, action: QAction, name: str) -> None:
        """The usage log told of ``action`` - connected before its own slot,
        so it is written ahead of what it does. A tool and the loupe are
        logged by what they became instead, which their buttons change
        without triggering the action."""
        if self.usage is not None and not name.startswith('tool.') and name != 'view.magnify':
            action.triggered.connect(lambda _=False, n=name: self.usage.action(n))

    def _menus(self):
        ed = self.editor
        self.edit_actions: dict[str, QAction] = {}
        for name, text, fn in (
                ('edit.undo', '&Undo', ed.undo),
                ('edit.redo', '&Redo', ed.redo),
                ('edit.delete', '&Delete', ed.delete_selected),
                ('edit.delete_way', 'Delete &contour', ed.delete_way),
                ('tool.select', '&Select', lambda: ed.set_tool('select')),
                ('tool.draw', 'Dr&aw contour', lambda: ed.set_tool('draw')),
                ('tool.spot', 'Place spot &height', lambda: ed.set_tool('spot')),
                ('tool.measure', '&Measure', lambda: ed.set_tool('measure')),
                ('edit.import_water', '&Import', self.import_water),
                ('edit.import_heights', '&Import', self.import_heights),
                ('edit.set_level', 'Set &level', ed.set_level),
                ('edit.grade', '&Grade', ed.grade),
                ('edit.grade_network', 'Grade river &network', ed.grade_network),
                # a lambda, not the method: triggered passes checked=False, which
                # flatten took for a pull-back of 0 m - F flattened with none
                ('edit.flatten', '&Flatten lake', lambda: ed.flatten()),
                ('edit.burn', '&Burn climb', lambda: ed.burn()),
                ('edit.burn_all', 'Burn &all climbs', lambda: ed.burn(every=True)),
                ('edit.split', 'S&plit', ed.split),
                ('edit.unglue', 'U&nglue', ed.unglue),
                ('edit.cut_loop', 'Cut &out the loop chosen',
                 lambda: ed.cut_loop(self.checks_dock.current_loop())),
                ('view.josm', 'Show in &JOSM', self.show_in_josm),
                ('view.josm_surface', 'Show in &JOSM', self.show_surface_in_josm),
                # toggled turns the loupe on and off, below: the button's toggle reaches it
                # through setChecked, which triggers nothing
                ('view.magnify', '&Magnify', None)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(self.settings.key(name)))
            self._logged(a, name)
            if fn is not None:
                a.triggered.connect(fn)
            if name.startswith('tool.') or name == 'view.magnify':
                a.setCheckable(True)
            self.edit_actions[name] = a
        e = self.edit_actions

        file = self.menuBar().addMenu('&File')
        self.open_action = QAction('&Open square…', self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_dialog)
        file.addAction(self.open_action)
        self.recent_menu = file.addMenu('Open &recent')
        self._fill_recent()
        # a zone's squares from the server (H6g)
        self.import_action = QAction('&Import…', self)
        self.import_action.triggered.connect(self.importer.start)
        file.addAction(self.import_action)
        file.addSeparator()
        self.save_action = QAction('&Save', self)
        self.save_action.setShortcut(QKeySequence(self.settings.key('file.save')))
        self._logged(self.save_action, 'file.save')
        self.save_action.triggered.connect(self.save_all)
        file.addAction(self.save_action)
        self.save_as_action = QAction('Save square &as…', self)
        self.save_as_action.setShortcut(QKeySequence(self.settings.key('file.save_as')))
        self._logged(self.save_as_action, 'file.save_as')
        self.save_as_action.triggered.connect(self.save_as)
        file.addAction(self.save_as_action)
        self.file_actions = {'file.save': self.save_action, 'file.save_as': self.save_as_action}
        self.new_square_action = QAction('&New blank square…', self)
        self.new_square_action.triggered.connect(self.new_blank_square)
        file.addAction(self.new_square_action)
        file.addSeparator()
        self.account_action = QAction(self)
        self.account_action.triggered.connect(self.account)
        file.addAction(self.account_action)
        self.preferences_action = QAction('&Preferences…', self)
        self.preferences_action.setShortcut(QKeySequence.StandardKey.Preferences)
        self.preferences_action.triggered.connect(self.preferences)
        file.addAction(self.preferences_action)
        file.addSeparator()
        quit_action = QAction('&Quit', self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file.addAction(quit_action)

        edit = self.menuBar().addMenu('&Edit')
        for name in ('edit.undo', 'edit.redo', None, 'edit.delete', 'edit.delete_way', 'edit.split', 'edit.unglue',
                     None, 'tool.select', 'tool.draw', 'tool.spot', 'tool.measure', None):
            if name:
                edit.addAction(e[name])
            else:
                edit.addSeparator()
        water = edit.addMenu('&Water')
        for name in ('edit.import_water', 'edit.set_level', 'edit.grade', 'edit.grade_network', 'edit.flatten',
                     'edit.burn', 'edit.burn_all'):
            water.addAction(e[name])
        edit.addMenu('Spot &height').addAction(e['edit.import_heights'])
        edit.addAction(e['edit.cut_loop'])

        view = self.menuBar().addMenu('&View')
        view.addAction(e['view.magnify'])
        view.addAction(e['view.josm'])
        view.addSeparator()
        # the surface panel's three overlays, the same choices as its boxes
        p = self.surface_panel
        self.view_actions: dict[str, QAction] = {}
        for name, text, box in (('view.unknown', '&Unknown ground', p.show_unreached),
                                ('view.single_level', 'Single-&level ground', p.show_one_level),
                                ('view.envelope', '&Envelope', p.show_envelope)):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setChecked(box.isChecked())
            a.toggled.connect(box.setChecked)
            box.toggled.connect(a.setChecked)
            view.addAction(a)
            self.view_actions[name] = a
        # single-level ground is a part of the unknown, and nothing without it
        unknown = self.view_actions['view.unknown']
        unknown.toggled.connect(self.view_actions['view.single_level'].setEnabled)
        view.addSeparator()
        for dock in self.docks():
            view.addAction(dock.toggleViewAction())
        view.addSeparator()
        reset = QAction('&Reset panels', self)
        reset.triggered.connect(self.reset_panels)
        view.addAction(reset)
        self.view_actions['view.reset_panels'] = reset
        magnify = e['view.magnify']
        magnify.toggled.connect(self.controls.magnify.setChecked)
        magnify.toggled.connect(self.loupe.set_on)          # from V, the menu and the button alike
        self.controls.magnify.toggled.connect(magnify.setChecked)
        self.controls.bind(e)
        self.surface_panel.josm_btn.clicked.connect(e['view.josm_surface'].trigger)
        self.surface_panel.contoursStyled.connect(self.contours.set_style)
        self._tool_changed('select')
        self._edited()

        elevation = self.menuBar().addMenu('E&levation')
        self.elevation_actions: dict[str, QAction] = {}
        c = self.elevation
        for name, text, fn in (
                ('elevation.big_up', 'Big step &up', lambda: c.step(True, False)),
                ('elevation.small_up', 'Small step u&p', lambda: c.step(False, False)),
                ('elevation.small_down', 'Small step d&own', lambda: c.step(False, True)),
                ('elevation.big_down', 'Big step do&wn', lambda: c.step(True, True)),
                ('elevation.nudge_up', '&Metre up', lambda: c.nudge(False)),
                ('elevation.nudge_down', 'M&etre down', lambda: c.nudge(True)),
                ('elevation.pick_up', '&Pick under cursor', self.pick_up),
                ('elevation.sea_level', '&Sea level', c.sea_level)):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(self.settings.key(name)))
            self._logged(a, name)
            a.triggered.connect(fn)
            elevation.addAction(a)
            self.elevation_actions[name] = a
        elevation.addSeparator()
        reload_ladders = QAction('Re-read &ladder', self)
        reload_ladders.triggered.connect(self.elevation.reload_overrides)
        elevation.addAction(reload_ladders)

        surface = self.menuBar().addMenu('&Surface')
        self.rebuild_action = QAction('&Rebuild surface', self)
        self.rebuild_action.setShortcut(QKeySequence(REBUILD_KEY))
        self.rebuild_action.triggered.connect(lambda: self.rebuild_surface())
        surface.addAction(self.rebuild_action)
        self.pinch_action = QAction('&Pinch ramp on active elevation', self)
        self.pinch_action.setShortcut(QKeySequence(self.settings.key('surface.pinch')))
        self._logged(self.pinch_action, 'surface.pinch')
        self.pinch_action.triggered.connect(self.legend.pinch_on_active)
        surface.addAction(self.pinch_action)
        surface.addAction(e['view.josm_surface'])
        self.surface_actions = {'surface.pinch': self.pinch_action}

    # ------------------------------------------------------- preferences
    def keyed_actions(self) -> dict[str, QAction]:
        """Every action whose key the INI holds, by its name there."""
        return {**self.file_actions, **self.edit_actions, **self.elevation_actions, **self.surface_actions}

    def action_labels(self) -> dict[str, str]:
        """Each keyed action as the menus name it: 'Edit › Water › Grade'."""
        by_action = {a: n for n, a in self.keyed_actions().items()}
        out: dict[str, str] = {}

        def walk(menu, path):
            for a in menu.actions():
                text = a.text().replace('&', '')
                if a.menu() is not None:
                    walk(a.menu(), [*path, text])
                elif a in by_action:
                    out.setdefault(by_action[a], ' › '.join([*path, text]))
        for top in self.menuBar().actions():
            walk(top.menu(), [top.text().replace('&', '')])
        return out

    def preferences(self) -> bool:
        from .preferences import PreferencesDialog
        dlg = PreferencesDialog(self.settings, self.action_labels(), self)
        if not dlg.exec():
            return False
        self.apply_settings()
        return True

    def apply_settings(self) -> None:
        """The settings put to use, as the preferences left them: keys at
        once, the servers from their next use."""
        s = self.settings
        for name, a in self.keyed_actions().items():
            a.setShortcut(QKeySequence(s.key(name)))
        self.controls.retip()
        self.elevation_panel.show_keys(s)
        # both read first: setting the panel's small step writes its big one
        # back, as the panel had it
        small, big = s.small_step, s.big_step
        self.elevation_panel.small.setValue(small)
        self.elevation_panel.big.setValue(big)
        self.josm.base = s.josm_url
        self.territory.urls = {'geometry': s.url('territory/geometry'), 'attributes': s.url('territory/owners')}
        self.published.url = s.url('published/dem')
        if self.checks_dock.bare_min_ha != s.bare_min_hectares and self.crossing_index is not None:
            # the rings reported from another area: found again. The indexes
            # are found together, and no crossing index is what asks for them
            self.crossing_index = None
            self._checks_shown(self.checks_dock.isVisible())

    # ------------------------------------------------------------ panels
    def docks(self) -> list[QDockWidget]:
        """The panels, in the order the View menu lists them."""
        return [self.surface_panel, self.gone_dock, self.checks_dock, self.elevation_panel,
                self.profile_dock, self.selection_panel]

    def _docked_only(self) -> None:
        """Every panel docked, never floating: under Wayland a floating panel
        cannot be moved again - Qt may not grab the mouse for it."""
        for dock in self.docks():
            dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable
                             | QDockWidget.DockWidgetFeature.DockWidgetMovable)
            dock.setFloating(False)

    def restore_layout(self, state: QByteArray) -> bool:
        """The panels as ``state`` had them - docked, whatever it says."""
        ok = self.restoreState(state)
        self._docked_only()
        return ok

    def reset_panels(self) -> None:
        """The panels back where a new window has them."""
        self.restore_layout(self._default_layout)

    def _fill_recent(self):
        self.recent_menu.clear()
        recent = self.settings.recent()
        self.recent_menu.setEnabled(bool(recent))
        for zone_dir, name, size in recent:
            a = QAction(f'{name}  ({zone_dir.name}, {size}×{size})', self)
            a.triggered.connect(lambda _=False, z=zone_dir, n=name, s=size: self.open_working_set(z, n, s))
            self.recent_menu.addAction(a)

    def _imported(self, answer) -> None:
        """A zone imported: the open set opened again if its squares were
        replaced - having no unsaved edits, or they would have been kept."""
        _zone, zone_dir, done = answer
        ws = self.working_set
        if ws is None or self.zone_dir is None or Path(self.zone_dir) != Path(zone_dir):
            return
        # a file is its square's name and a place: N20E086_Gobras_City.osm.xz
        replaced = {n.split('_')[0].split('.')[0] for n in (*done['new'], *done['updated'], *done['overwritten'])}
        if any(str(name) in replaced for name in ws.squares):
            said = self.statusBar().currentMessage()

            def again(*_):
                self.loader.finished.disconnect(again)
                self.statusBar().showMessage(f'{said} - the set opened again from them')
            self.loader.finished.connect(again)
            self.open_working_set(self.zone_dir, ws.centre, ws.size)

    def open_dialog(self):
        # the import root when no other has been opened from (H6g)
        root = self.settings.squares_root
        if root is None and self.settings.import_root.exists():
            root = self.settings.import_root
        dlg = OpenDialog(root, self.settings.size, self)
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
        if self.autosave is not None and self.editor.dirty():
            # the set being left has edits nobody saved: kept, and offered
            # back the next time it is opened
            self.autosave.flush()
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
        self.file_index = None
        self.inside_index = None
        self.surface_findings = None
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
        self.measure.clear()
        self.legend.refresh()
        self.unreached.set_shaded(None)
        self.envelope.set_rings([])
        self.surface_panel.status.setText('no surface built for this set yet')
        if self.autosave is not None:
            # once the set is on screen, so the offer is made over the squares it is about
            QTimer.singleShot(0, self._offer_recovery)

    def _offer_recovery(self) -> None:
        """What an earlier run autosaved for this set and never saved, offered
        back square by square; what is not taken is set aside, not lost."""
        ws, zone = self.working_set, self.zone_dir
        if ws is None or zone is None:
            return
        store = self.autosave.store
        mine = [e for e in store.entries(zone) if e.square in ws.squares]
        elsewhere = [e for e in store.entries() if e not in mine]
        said = []
        if mine:
            chosen = autosave_ui.offer(mine, self) or []
            steps = autosave_ui.recovery_steps(chosen, ws)
            if steps:
                self.editor.do_across(steps)
                said.append('put back the autosaved edits to ' + ', '.join(str(sq.name) for sq, _ in steps))
            aside = [store.set_aside(e) for e in mine if e not in chosen]
            if aside:
                said.append(f'set aside {len(aside)} in {aside[0].parent}')
            self.autosave.flush()                        # the recovery is the autosave now
        if elsewhere:
            names = ', '.join(f'{e.square} ({e.zone.name})' for e in elsewhere[:4])
            said.append(f'autosaved edits are held for {names}{" and more" if len(elsewhere) > 4 else ""}'
                        ' - open there to recover them')
        if said:
            self.statusBar().showMessage('; '.join(said))

    # ----------------------------------------------------------- surface
    def rebuild_surface(self, arcsec: float | None = None) -> bool:
        """Build the working set's DEM on a worker - the same stages the
        server runs - and shade it. Slow and exact; the panel says how long.

        At 3 arcseconds, or at whatever the surface on screen was built at -
        which is 3 unless the command line's --surface asked for another, and
        then the rebuilds after it keep to that. ``arcsec`` overrides both:
        the command line passes its own, and nothing else passes one."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return False
        try:
            p = self._loaded_params()
        except (KeyError, OSError) as e:
            self._surface_failed(str(e))
            return False
        p = p.with_arcsec(arcsec if arcsec is not None else (self._arcsec or ARCSEC))
        # before the request, not after: request() starts the build there and
        # then when nothing is running, and the build's own started signal
        # reads this. Setting it afterwards had the status line report the
        # previous build's resolution, which on the first build of a session
        # is the 0 it was initialised to - "building at 0″".
        self._arcsec = p.arcsec
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
        if self.builder.checking:
            self._surface_pending = True             # the panel says this build will answer
            self._checks_due.start()
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
        differs = peaks.differ(answer.placed, working_set)
        steps = height_commands(answer.placed, working_set)
        if steps:
            self.editor.do_across(steps)
        self.gone_dock.show_report(self.gone_from_upstream, reshaped=[], differs=differs)
        if self.gone_from_upstream or differs:
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
        if differs:
            said += (f"; {len(differs)} the main map gives another height, the square's kept - "
                     'listed in the report')
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

    def show_in_josm(self) -> str | None:
        """JOSM to the place the map shows, selecting what is selected here
        if it came from the main map - its remote control's ``/zoom``. A row
        of the checks or of the import report, chosen, has already put both
        here. Answers the URL asked, for whoever wants it."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return None
        sel = self.editor.selection
        ids = josm.selected_ids(sel)
        what = 'the place shown here' + (f', selecting {", ".join(ids)}' if ids else '')
        if sel is not None and not ids:
            what += ' - what is selected was drawn here, and is not in JOSM'
        return self.josm.zoom(self._view_bounds(), ids, what)

    def show_surface_in_josm(self) -> str | None:
        """The surface served on the loopback as a WMS, and JOSM asked to add
        it as a layer - so the ground under what is fixed there is the ground
        built here (H5). The server starts the first time, and serves
        whatever the map shows from then on. Answers the URL asked."""
        if self.surface.shaded is None:
            self.statusBar().showMessage('build a surface first - then JOSM can be given it')
            return None
        if self.wms is None:
            surface, fine = self.surface, self.fine_layer
            # the 1 arcsecond tiles too, as the one tuple the layer publishes,
            # and their revision in what an ETag is of (I3d)
            self.wms = wms.SurfaceServer(lambda: (surface.shaded, surface.style, surface.stretch,
                                                  (surface.revision, fine.published[0]),
                                                  fine.published[1]), self.settings.wms_port)
        url = wms.getmap_url(self.wms.base)
        what = f'the surface, served at {self.wms.base}'
        if self.wms.port != self.settings.wms_port and self.settings.wms_port:
            what += (f' - port {self.settings.wms_port} is in use, and a layer JOSM kept from before'
                     ' will not find this one')
        return self.josm.imagery('Danu surface', url, what)

    def _view_settled(self) -> None:
        """The surface's rows and columns on screen, to the panel - which
        recolours only if the scaling reads them. ``scene_rect`` is worked out
        from the DEM's own shape and geotransform, so mapping it onto the
        grid's rows and columns is exact. And the view, to the 1 arcsecond
        driver, which solves it at z15 and closer."""
        self.fine.view(self._view_bounds(), self.map.zoom)
        shaded = self.surface.shaded
        if shaded is None:
            return
        r = self.map.viewport().rect()
        a, b = self.map.mapToScene(r.topLeft()), self.map.mapToScene(r.bottomRight())
        left, top, right, bottom = shaded.scene_rect
        rows, cols = shaded.dem.shape
        c0 = int((a.x() - left) / (right - left) * cols)
        c1 = int((b.x() - left) / (right - left) * cols) + 1
        r0 = int((a.y() - top) / (bottom - top) * rows)
        r1 = int((b.y() - top) / (bottom - top) * rows) + 1
        window = (max(r0, 0), min(r1, rows), max(c0, 0), min(c1, cols))
        if window[1] <= window[0] or window[3] <= window[2]:
            window = None                                 # the surface is off screen
        self.surface_panel.set_view_window(window)

    def _fine_arrived(self, tiles, seconds: float) -> None:
        """Tiles of the view solved at 1 arcsecond, which the fine layer
        draws. The usage log has how long they took, which is the phase's
        measure - a z15 screen within 2 s of the view settling."""
        if self.usage is not None:
            self.usage.write('fine', tiles=len(tiles), seconds=round(seconds, 3))

    def _view_bounds(self) -> tuple[float, float, float, float]:
        """The map's viewport as (west, south, east, north)."""
        r = self.map.viewport().rect()
        a = self.map.mapToScene(r.topLeft())
        b = self.map.mapToScene(r.bottomRight())
        west, north = m.scene_to_lonlat(a.x(), a.y())
        east, south = m.scene_to_lonlat(b.x(), b.y())
        return west, south, east, north

    def _take_heights(self, rows) -> None:
        """The main map's height for each row, one step across the squares;
        a row whose spot height has gone, or whose height already is the
        main map's, is passed over."""
        ws = self.working_set
        by_square: dict = {}
        for d in rows:
            square = ws.squares.get(d.square) if d is not None and ws is not None else None
            node = square.nodes.get(d.id) if square is not None else None
            if node is None or d.settled(node):
                continue
            by_square.setdefault(d.square, (square, []))[1].append(
                edits.SetNodeTags(d.id, dict(node.tags), {**node.tags, 'ele': d.upstream}))
        if not by_square:
            return
        steps = [(square, cmds[0] if len(cmds) == 1 else
                  edits.Compound(cmds, name=f"the main map's heights in {name}"))
                 for name, (square, cmds) in sorted(by_square.items(), key=lambda kv: str(kv[0]))]
        self.editor.do_across(steps)
        n = sum(len(c) for _, c in by_square.values())
        self.statusBar().showMessage(f"took the main map's height for {n} spot height"
                                     f"{'s' * (n != 1)} - Ctrl+Z puts the square's back")

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
        if isinstance(g, peaks.Differs):
            self.editor.set_tool('select')
            self.editor.selection = Selection(square, None, g.id)
            self.editor.overlay.update()
            self._show_place(feature.lon, feature.lat, feature.lon, feature.lat)
            self.statusBar().showMessage(f"{g.describe()} - the button takes the main map's, "
                                         "doing nothing keeps the square's")
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
            self.checks_dock.finding(len(CHECKS))
            self.checks_dock.raise_()
            self.statusBar().showMessage(f'finding the checks over {ws.centre} and its neighbours…')
            started = time.monotonic()
            job = None

            def done(indexes):
                self._checks_job = None
                if ws is not self.working_set:
                    self._checks_shown(self.checks_dock.isVisible())   # a set opened meanwhile
                    return
                (self.crossing_index, self.loop_index, self.touch_index, self.spot_index,
                 self.file_index, self.inside_index) = indexes
                missed, self._checks_missed = self._checks_missed, []
                for square, ways, spot_ids in missed:
                    self._checks_edited(square, ways, spot_ids)
                self._refresh_checks()
                self.statusBar().showMessage(f'checks found in {time.monotonic() - started:.1f} s')

            def failed(why):
                self._checks_job = None
                first = why.splitlines()[0]
                self.statusBar().showMessage(f'the checks failed: {first}')
                self.checks_dock.failed(first)

            self.checks_dock.bare_min_ha = self.settings.bare_min_hectares
            bare_min = self.checks_dock.bare_min_ha * 1e4
            job = Job(lambda: find_checks(ws, bare_min=bare_min, report=job.report), done, failed,
                      on_progress=lambda step: self.checks_dock.finding_step(*step))
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
        if self.file_index is not None and (ways or spot_ids):
            self.file_index.update(square)               # the square asked again, 12 ms at most
            self._checks_due.start()
        if self.surface_findings is not None and (ways or spot_ids) and not self._surface_stale:
            self._surface_stale = True                   # said, not asked again: that is a build
            self._checks_due.start()
        if self.inside_index is not None and (ways or spot_ids):
            # the rings and lakes round what moved, 23 ms at the most measured
            self.inside_index.update(square, ways or (), spot_ids or ())
            self._checks_due.start()
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
        self.checks_dock.show_files(self.file_index.findings() if self.file_index is not None else [])
        self.checks_dock.show_inside(self.inside_index.findings() if self.inside_index is not None else [])
        self.checks_dock.show_surface(self.surface_findings, self._surface_found_at, self._surface_stale,
                                      self._surface_pending)
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
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in (self.file_index.findings() if self.file_index is not None else [])]
                             # the lakes, and not the report: 3,882 rings over gobras would be
                             # crosses over every hill
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in (self.inside_index.findings('lake') if self.inside_index is not None else [])]
                             # a square of unreached ground is a row, not a place to mark
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in (self.surface_findings or []) if f.kind != 'unreached']
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

    def _choose_finding(self, f) -> None:
        """What a file says, chosen (H1a): its way or node selected, as a
        click would, and brought into view."""
        ws = self.working_set
        square = ws.squares.get(f.square) if ws is not None else None
        if f.way is None and f.relation is None and f.node is None:
            # a place and no feature - sea level off the shore, ground unreached
            self.editor.marks_focus = [m.lonlat_to_scene(f.lon, f.lat)]
            self._show_place(*f.box)
            self.editor.overlay.update()
            self.statusBar().showMessage(f.explain())
            return
        held = square is not None and (f.way in square.ways if f.way is not None
                                       else f.relation in square.relations if f.relation is not None
                                       else f.node in square.nodes)
        if not held:
            self.statusBar().showMessage(f'{f.describe()}: no longer in {f.square}')
            return
        self.editor.set_tool('select')
        self.editor.selection = (Selection(square, square.ways[f.way]) if f.way is not None
                                 else Selection(square, None, relation=square.relations[f.relation])
                                 if f.relation is not None else Selection(square, None, f.node))
        self.editor.marks_focus = [m.lonlat_to_scene(f.lon, f.lat)]
        self._show_place(*f.box)
        self.editor.overlay.update()
        self.statusBar().showMessage(f.explain())

    # ---------------------------------------------------------- difference
    def _difference_wanted(self) -> None:
        """Difference shown, and this build's not worked out: fetch the
        published DEM - or find it kept - and work it out."""
        shaded = self.surface.shaded
        if self.surface.style.mode != 'difference' or shaded is None or shaded.difference is not None:
            return
        if self.zone_dir is None or self._difference_for is shaded:
            return                                 # already being worked out, for this build
        self.statusBar().showMessage(f'difference: fetching the published {self.zone_dir.name} DEM…')
        self.published.request(self.zone_dir.name)

    def _published_ready(self, zone: str, path, what: str) -> None:
        shaded = self.surface.shaded
        if shaded is None or self.zone_dir is None or zone != self.zone_dir.name:
            return
        if self._difference_for is shaded:
            return
        when = time.strftime('%d %b %Y', time.localtime(Path(path).stat().st_mtime))

        def work():
            pub = surface_difference.published_on(Path(path), shaded)
            d = surface_difference.difference(shaded.dem, pub)
            return d, surface_difference.span(d)

        def done(answer):
            self._difference_job = self._difference_for = None
            if shaded is not self.surface.shaded:
                self._difference_wanted()          # a build landed meanwhile: its own
                return
            shaded.difference, shaded.difference_span = answer
            self.surface.recolour()
            self.legend.refresh()
            self._refresh_status()
            kept = f' ({what})' if what.startswith('kept') else ''
            self.statusBar().showMessage(
                f'difference: the exact build less the published {zone} DEM of {when}{kept}, '
                f'±{shaded.difference_span:g} m')

        def failed(why):
            self._difference_job = self._difference_for = None
            self.statusBar().showMessage(f'difference not worked out: {why.splitlines()[0]}')
        self._difference_for = shaded
        self._difference_job = Job(work, done, failed)
        self._difference_runner(self._difference_job)

    def _published_failed(self, zone: str, why: str) -> None:
        if self.zone_dir is None or zone != self.zone_dir.name:
            return                                     # a zone left since it was asked for
        self.statusBar().showMessage(f'difference: the published {zone} DEM could not be fetched - {why}')

    def _profile_colours(self, line):
        """The colour the map gives each point along a measured line: by its
        slope while slope is shown, by its ground otherwise - the legend's
        colours, so the profile and the bar cannot differ."""
        mode, shaded = self.surface.style.mode, self.surface.shaded
        if mode == 'difference':
            if shaded is None or shaded.difference is None:
                return None
            values = along.sample(shaded.difference, shaded.scene_rect, line.scene)
        else:
            values = line.slope if mode == 'slope' else line.ground
        return self.legend.colours(values) if values is not None else None

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
        self.measure.surface_changed()             # which refuses, until the exact one
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
        # the resolution this surface is at, said rather than left to the
        # default: it is 3 arcseconds unless the command line asked for
        # another, and settling a --surface 1 surface at 3 would change its
        # resolution under the mapper
        self.rebuild_surface(self._arcsec)

    def _surface_built(self, built, stale=False, seconds=0.0):
        if self._surface_pending:
            self._surface_pending = False
            self._checks_due.start()
        if getattr(built, 'checks', None) is not None or getattr(built, 'checks_failed', None):
            self.surface_findings = built.checks or []
            self._surface_found_at = time.strftime('%H:%M')
            self._surface_stale = stale
            if built.checks_failed:
                self.statusBar().showMessage(f"the surface's checks failed: {built.checks_failed}")
            self._checks_due.start()
        self._surface_built_shown(built, stale, seconds)

    def _surface_built_shown(self, built, stale=False, seconds=0.0):
        # seconds comes from the builder: once builds overlap, how long one
        # took is not something a single attribute here can hold
        self.surface.set_shaded(built.shaded)
        self._view_settle.start()                # a new grid: the window in view asked again
        self._refresh_status()                   # and the reading under the cursor is of it
        self.legend.refresh()
        self.unreached.set_shaded(built.shaded)
        self.envelope.set_rings(built.envelope_rings)
        self.surface_panel.built(built.shaded, seconds)
        self.surface.set_preview(stale)     # a superseded build is provisional too
        self.measure.surface_changed()
        self._difference_wanted()           # a new build, a new difference - if one is shown
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
        params = built.params or self._loaded_params(fallback=self._arcsec)
        self.preview.adopt(built, params)
        # and the 1" view held on it; the settle timer started above asks for
        # the view again once this has run
        self.fine.adopt(built, self.preview.contours, params)
        self.fine_layer.forget()
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
                    help='build and show the surface once the square is open, at this resolution '
                         '(default 3, which is what the editor builds at; another is for comparing, '
                         'and the rebuilds after it keep to it)')
    args = ap.parse_args(argv[1:])
    if bool(args.zone_dir) != bool(args.square):
        ap.error('give both a zone directory and a square, or neither')

    quieten_qt()          # before the first request; see danu.ui.messages
    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    layers = config.load_layers(user_config_dir() / config.USER_FILE)
    win = MainWindow(layers, cache_dir=user_cache_dir() / 'tiles', data_dir=user_data_dir())
    last = session.read(win.session_path) if not args.zone_dir else None
    if last is not None:
        session.restore_window(win, last)
    win.show()
    # connected before the open is asked for; the signal is queued to the
    # event loop either way, but the order reads as it runs
    if args.surface is not None:
        win.loader.finished.connect(lambda _ws, a=args.surface: win.rebuild_surface(a))
    if args.zone_dir:
        win.open_working_set(args.zone_dir, SquareName.parse(args.square), args.size)
    elif last is not None and session.restore(win, last):
        pass                                     # restore opened the set; the view and surface follow it
    elif recent := win.settings.recent():
        win.open_working_set(*recent[0])
    return app.exec()
