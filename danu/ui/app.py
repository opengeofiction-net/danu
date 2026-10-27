"""The window. Presentation only: it holds a MapView and tells you where the
cursor is. Everything it will grow - layers, squares, contours, editing -
arrives in later phases, and none of it lives in this file.

Run with ``python -m danu.ui``. There is no console script yet: one would land
in the server package, which has no PySide6 and no business with an editor.
That comes with the desktop packaging.
"""

from __future__ import annotations

import argparse
import html
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QByteArray, QEvent, QRectF, QStandardPaths, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
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
from ..core import doubled, dropclient, edits, make_square, save, territory, zone_index
from ..core.autosave import Store
from ..core.square import Square, SquareName, WorkingSet, list_squares, read_square
from ..surface import along, shade
from ..surface import difference as surface_difference
from ..water import coast, flatten, overpass, peaks
from ..water.gone import gone
from . import about, config, crash, desktop, josm, oauth, pending, session, theme, update, wms
from . import autosave as autosave_ui
from . import help as help_ui
from . import mercator as m
from .autosave import AutoSaver
from .background import Job
from .checks_dock import ChecksDock
from .contours import ContourLayer
from .drop import DropClient
from .elevation import PICK_PX, ElevationControl, ElevationPanel
from .gone_dock import GoneDock
from .ground import GroundItem
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
from .pending import Pending
from .published import PublishedDem
from .reference import ReferenceItem
from .selection_panel import SelectionPanel
from .send import Sender
from .settings import REBUILD_KEY, Settings
from .squares import SquaresItem
from .start import StartCard
from .surface import ARCSEC, SurfaceBuilder, SurfaceLayer, SurfacePanel
from .territory import TerritoryFetcher
from .tiles import TileFetcher, TileLayer
from .tools import EditController, Selection
from .usage import UsageLog
from .water import (
    Snapshot,
    WaterImporter,
    coast_commands,
    coast_work,
    copies_by,
    fetch_coast,
    fetch_heights,
    height_commands,
    heights_held,
    heights_work,
    held_by,
    move_commands,
)
from .water import commands as water_commands
from .zones import ZoneEditor

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


# an edit of more ways than this has the checks found again whole, on the
# worker, rather than put to them way by way on the UI thread - about 14 ms a
# way there on roantra, and a whole scan of its six squares 23 s off it
WIDE_EDIT = 500


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



def _undo_hint(doubled: str) -> str:
    """How an import comes back off the history: one step, or two when the
    copies it doubled were removed after it."""
    if doubled:
        return 'Ctrl+Z puts the doubled back, and again takes the import'
    return 'Ctrl+Z takes them all back'

class MainWindow(QMainWindow):
    def __init__(self, layers: list[config.Layer], cache_dir: Path | None = None,
                 settings: Settings | None = None, territory_fetcher: TerritoryFetcher | None = None,
                 data_dir: Path | None = None):
        super().__init__()
        self.setWindowTitle(about.title())
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
        # whose ground each square is, shaded, and the drop's word on it (#190)
        self.ground = GroundItem()
        self.map.scene().addItem(self.ground)
        self.drop = DropClient(self.settings.url('drop/url'), self.settings.server_url, parent=self)
        self.drop.answered.connect(self._drop_answered)
        self._drop_asked = None             # (square, token) last asked about
        self._browsing = False              # the start page put away for the zones map
        self._drop_runner = QThreadPool.globalInstance().start      # the tests' to make run in place
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
        self._panel_focus = None                # the rings the panel's row put up, while they are its
        # the first scan over a set runs on a worker - 9.3 s on gobras - and
        # the edits made while it runs are put to it when it lands
        self._checks_runner = QThreadPool.globalInstance().start
        self._checks_job = None
        self._checks_missed: list = []
        self._checks_redo = False               # the scan running is to be done again when it lands
        self._checks_wide = False               # a whole scan is due, after a wide edit
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
        self.checks_dock.centre_only.setChecked(self.settings.checks_centre_only)
        self.checks_dock.centre_only.toggled.connect(self._checks_centre_only)
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
        # the zone's folder with the set's holdings: a feature's home may be a
        # square of the zone outside the set, the sea's two squares away
        self.water = WaterImporter(self, fetch=lambda bounds: overpass.fetch(bounds, url=self.settings.overpass_url),
                                   held=lambda ws: Snapshot(held_by(ws), self.zone_dir, copies_by(ws)))
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
        # and its coastlines, on the same footing again
        self.coast = WaterImporter(self, fetch=lambda bounds: fetch_coast(bounds, self.settings.overpass_url),
                                   work=coast_work)
        self.coast.started.connect(lambda ws: self.statusBar().showMessage(
            'importing coastlines from Overpass…'))
        self.coast.finished.connect(self._coast_imported)
        self.coast.failed.connect(
            lambda why: self.statusBar().showMessage(f'coastline import failed: {why.splitlines()[0]}'))
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
        self.editor.runner = lambda job: self._checks_runner(job)
        # to the preview only while the surface rebuilds itself (#239): off,
        # nothing is solved until Ctrl+R, which the preview then adopts
        self._surface_out_of_date = False
        # a session's surface not built again, automatic rebuilds off: the
        # session written meanwhile still says one is wanted
        self.surface_wanted = False
        self.editor.editedWays.connect(self._edited_ways)
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
        # the data drop's zones (#190, N6): on the map for anyone, edited by administrators
        self.zone_editor = ZoneEditor(self, self)
        self.zone_editor.message.connect(lambda t: self.statusBar().showMessage(t) if t else None)
        self.map.recentre = self.open_square_at
        self.map.scene().addItem(self.zone_editor.item)
        self.zones_dock = self.zone_editor.dock
        # open from the first run, so the zones are on the map and it is a way
        # in: tabbed with the surface panel, the surface in front
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.zones_dock)
        self.tabifyDockWidget(self.surface_panel, self.zones_dock)
        self.surface_panel.raise_()
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
        # where each zone square's water reaches, worked out once and kept
        self._zone_water_cache = cache_dir.parent / 'zone-water.json' if cache_dir else None
        self._alongside_job: Job | None = None
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
        # each square's marks on the map: '*' unsaved, '^' saved but not uploaded
        self.waiting = Pending(self, self)
        self.waiting.changed.connect(self._show_marks)
        self.importer.finished.connect(lambda *_: self.waiting.refresh())
        self.waiting.refresh()
        # File › Revert square to the server's: the squares whose changes here
        # are being thrown away, until the set opens again without them
        self._reverting: set | None = None
        self.importer.failed.connect(lambda _why: setattr(self, '_reverting', None))
        # the open square to the data drop (#190, N5b), and a refused one's copy over it
        self.sender = Sender(self, self)
        self.sender.message.connect(lambda t: self.statusBar().showMessage(t) if t else None)
        self.reference = ReferenceItem()
        self.map.scene().addItem(self.reference)
        self._menus()
        # the start page (J5a), shown by update_start once it is known that
        # nothing is being opened - or over what is, when asked for (J5c)
        self.zones_map_action = QAction('&Zones map', self)
        self.zones_map_action.setToolTip('the zones on the map: double-click a square to open it')
        self.zones_map_action.triggered.connect(self.browse_zones)
        self.start = StartCard(self.map, self.account_action, self.zones_map_action, self.import_action,
                               self.open_action, self.new_square_action)
        self.start.hide()
        self._start_asked = False
        self.start.closed.connect(self.close_start)
        self.start.menuAnswered.connect(self._menu_answered)
        self._docked_only()
        self._default_layout = self.saveState()       # what Reset panels goes back to
        # the outlines and the map's clicks follow the panel's action, which
        # says so only as it changes: told how it starts
        self.zone_editor.show(self.zones_dock.toggleViewAction().isChecked())
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
        self._drop = QLabel('')
        self._drop.setOpenExternalLinks(True)
        self._drop.setToolTip('whether the open square is yours to upload, from the data drop')
        self.statusBar().addPermanentWidget(self._drop)
        self._status = QLabel()
        self.statusBar().addPermanentWidget(self._status)
        # a newer release (J7), first of the permanent ones when there is one
        self.newer = QLabel()
        self.newer.setOpenExternalLinks(True)
        self.newer.setVisible(False)
        self.statusBar().insertPermanentWidget(0, self.newer)
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
        self._show_marks()

    def _show_marks(self):
        """Each square's marks, on its frame and on the zones map; in the
        title, the set's unsaved edits and the centre's file not uploaded."""
        dirty = {sq.name for sq in self.editor.history.dirty_squares()}
        got = pending.marks(dirty, self.waiting.unsent)
        for item in (self.squares, self.zone_editor.item):
            if item.marks != got:
                item.marks = got
                item.update()
        if self.working_set is not None:
            ws = self.working_set
            self.setWindowTitle(about.title(ws.centre, bool(dirty), ws.squares[ws.centre].label,
                                            ws.centre in self.waiting.unsent))

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
        self.show_ground()

    def show_ground(self) -> None:
        """Each square's ground shaded for the mapper signed in (#190), and
        the drop asked about the open one."""
        ws, index = self.working_set, self.territory.index
        user = self.settings.user if self.settings.token else ''
        on = self.surface_panel.show_ground.isChecked()
        if ws is None or index is None or not user or not on:
            self.ground.set_ground([])
        else:
            try:
                # OGR's buffer, so GDAL, which the editor's import must not need
                from ..core.ground import ground as whose_ground
            except ImportError:
                whose_ground = None
            grounds = []
            for sq in ws.squares if whose_ground else ():
                try:
                    grounds.append(whose_ground(index, sq.bounds, user))
                except RuntimeError as e:       # OGR's, on a territory it can't make whole
                    self.statusBar().showMessage(f'{sq}: whose ground not shaded - {e}')
            self.ground.set_ground(grounds)
        if ws is not None and self._drop_asked != (ws.centre, self.settings.token):
            self._drop_asked = (ws.centre, self.settings.token)
            self._drop.setText('upload: asking…')
            self._drop.setStyleSheet('')
            self.drop.ask(ws.centre, self.settings.token)

    def show_reference(self) -> None:
        """The open square's refused copy, if one is kept beside it, read on
        a worker and drawn over the square (#190, N5b)."""
        ws = self.working_set
        mine = dropclient.mine_for(self.zone_dir, ws.centre) if ws is not None and self.zone_dir else None
        if mine is None:
            self.reference.set_square(None)
            self.update_reference_actions()
            return
        centre = ws.centre

        def read(sq):
            if self.working_set is not None and self.working_set.centre == centre:
                self.reference.set_square(sq)
                self.update_reference_actions()
                # after whatever opened the set has said so
                QTimer.singleShot(0, lambda: self.statusBar().showMessage(
                    f'{mine.name}, your refused version, is drawn dashed over the square: '
                    'redo your changes, upload again, then discard it'))
        job = Job(lambda: read_square(mine, centre), read,
                  lambda why: self.statusBar().showMessage(f'{mine.name} not read: {why.splitlines()[0]}'))
        self._reference_job = job
        self._checks_runner(job)

    def update_reference_actions(self) -> None:
        on = self.reference.square is not None
        # both menus built: File's action first, View's after it
        if 'view.refused' in getattr(self, 'view_actions', {}):
            self.drop_actions['drop.discard'].setEnabled(on)
            self.view_actions['view.refused'].setEnabled(on)

    def _drop_answered(self, square: str, line: str, warn: bool) -> None:
        if self.working_set is None or self.working_set.centre.name != square:
            return
        self._drop.setText(line)
        self._drop.setStyleSheet('color: #b04000; font-weight: bold' if warn else '')

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
        self.start.set_account(user)
        self.zone_editor.update_buttons()
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
            self.waiting.refresh()

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
        nobody has drawn. The set is re-read so it shows as present.

        With nothing open (J5c) - a mapper starting a territory, from the
        start page - the square offered is the one in the middle of the map,
        and the set opens round it. Its zone is the drop's (#226): the square
        goes where Import puts that zone, ``<import root>/<zone>/``, so that
        Import and Upload find it - or, the drop holding it already, the zone
        is imported rather than a blank written over it. In no zone, or the
        drop not reached, the zone's directory is asked for, from the import
        root - made first, or the dialog starts somewhere of the system's."""
        ws = self.working_set
        if ws is None:
            if self._pending is not None:
                self.statusBar().showMessage('a square is being read')
                return
            lon, lat = self.map.center_lonlat()
            try:
                default = str(SquareName(int(np.floor(lon)), int(np.floor(lat))))
            except ValueError:                           # the map's edge, past the squares
                default = ''
            name = self._ask_square_name(default)
            if name is not None:
                self._new_in_its_zone(name)
            return
        elif self.zone_dir is None:
            self.statusBar().showMessage('open a square in the zone first')
            return
        elif self.editor.dirty():
            self.statusBar().showMessage('save first: a new square re-reads the set')
            return
        else:
            zone_dir = self.zone_dir
            default = next((str(n) for n, s in ws.squares.items() if not s.present), str(ws.centre))
        name = self._ask_square_name(default)
        if name is not None:
            self._write_blank(zone_dir, name)

    def _ask_square_name(self, default: str) -> SquareName | None:
        text, ok = self.ask_text('New blank square', 'Square (e.g. N20E087):', default)
        if not ok or not text.strip():
            return None
        try:
            return SquareName.parse(text.strip())
        except ValueError as e:
            QMessageBox.warning(self, 'Danu', str(e))
            return None

    def _new_in_its_zone(self, name: SquareName) -> None:
        """Nothing open: the drop asked which zone the new square is in."""
        api, token = self.settings.url('drop/url'), self.settings.token
        self.statusBar().showMessage(f'asking the drop which zone {name} is in…')

        def answered(info):
            if info.ok and info.body.get('zone'):
                zone_dir = self.settings.import_root / str(info.body['zone'])
                if info.body.get('held'):
                    self.import_then_open(zone_dir, name, f"{name} is held on the server as "
                                           f"{info.body['held'].get('file', '')} - importing {zone_dir.name}")
                    return
                zone_dir.mkdir(parents=True, exist_ok=True)
                self._write_blank(zone_dir, name)
                return
            if info.status == 404 and 'square' in info.body:
                self.statusBar().showMessage(f'{name} is in no zone, so it can\'t be uploaded yet - '
                                             'choose a directory for it')
            self._new_asking_the_directory(name)

        def unreached(_why):
            self._new_asking_the_directory(name)
        job = Job(lambda: dropclient.square_info(api, name, token), answered, unreached)
        self._new_square_job = job
        self._drop_runner(job)

    def _new_asking_the_directory(self, name: SquareName) -> None:
        root = self.settings.squares_root or self.settings.import_root
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        chosen = QFileDialog.getExistingDirectory(self, "The zone's directory, for the new square", str(root))
        if chosen:
            self._write_blank(Path(chosen), name)

    def import_then_open(self, zone_dir: Path, name: SquareName, said: str) -> None:
        """The square's zone imported, and it opened: a new square the server
        holds already, or one double-clicked on the zones map (#190) - drawn
        or still to be, as an absent square opens."""
        self.statusBar().showMessage(said)

        def imported(answer):
            done()
            if Path(answer[1]) == zone_dir:
                self.open_working_set(zone_dir, name, self.settings.size)

        def done(*_):
            self.importer.finished.disconnect(imported)
            self.importer.failed.disconnect(done)
        self.importer.finished.connect(imported)
        self.importer.failed.connect(done)
        if not self.importer.refresh(zone_dir):
            done()

    def _write_blank(self, zone_dir: Path, name: SquareName) -> None:
        ws = self.working_set
        path = save.default_path(zone_dir, name)
        if (path.exists() or name in list_squares(zone_dir)
                or (ws is not None and name in ws.squares and ws.squares[name].present)):
            QMessageBox.warning(self, 'Danu', f'{name} already exists in {zone_dir.name}')
            return
        make_square.write_square(path, name.lon, name.lat, save.FRAME_NOTE)
        self.statusBar().showMessage(f'wrote {path.name}')
        if ws is None:
            self.open_working_set(zone_dir, name, self.settings.size)
        else:
            self.open_working_set(zone_dir, ws.centre, ws.size)

    def ask_text(self, title: str, label: str, text: str) -> tuple[str, bool]:
        """A line of text asked for; the tests hand in the answer."""
        return QInputDialog.getText(self, title, label, text=text)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, 'controls'):
            self.controls.recolour()                     # see MapControls.recolour

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
        self.zone_editor.detach()
        self.waiting.detach()
        if self._alongside_job is not None:     # it held this window, kept by the pool
            self._alongside_job.release()
            self._alongside_job = None
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
                ('edit.import_coastline', '&Import', self.import_coastline),
                ('edit.mark_coastline', '&Mark / unmark', ed.toggle_coastline),
                ('edit.reverse_coastline', '&Reverse', ed.reverse_coastline),
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
                ('edit.absorb', '&Absorb pieces', ed.absorb),
                ('edit.push_crossings', 'Push back &crossings', lambda: ed.push_crossings()),
                ('edit.cut_loop', 'Cut &out the loop chosen',
                 lambda: ed.cut_loop(self.checks_dock.current_loop())),
                ('view.josm', 'Show in &JOSM', self.show_in_josm),
                ('view.josm_surface', 'Show in &JOSM', self.show_surface_in_josm),
                # toggled turns the loupe on and off, below: the button's toggle reaches it
                # through setChecked, which triggers nothing
                ('view.magnify', '&Magnify', None),
                ('view.set_west', 'Set a square &west', lambda: self.move_set(-1, 0)),
                ('view.set_east', 'Set a square &east', lambda: self.move_set(1, 0)),
                ('view.set_north', 'Set a square &north', lambda: self.move_set(0, 1)),
                ('view.set_south', 'Set a square &south', lambda: self.move_set(0, -1))):
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
        # the open square to the data drop (#190)
        self.drop_actions: dict[str, QAction] = {}
        for name, text, slot in (('drop.upload', '&Upload square…', self.sender.upload),
                                 ('drop.upload_changed', 'Upload &changed squares…', self.sender.upload_changed),
                                 ('drop.rename', 'Re&name square…', self.sender.rename),
                                 ('drop.delete', '&Delete square from server…', self.sender.delete),
                                 ('drop.discard', 'Discard re&fused version…', self.sender.discard),
                                 ('drop.revert', 'Re&vert square to the server\'s…', self.sender.revert)):
            a = QAction(text, self)
            a.triggered.connect(slot)
            file.addAction(a)
            self.drop_actions[name] = a
        file.addSeparator()
        self.account_action = QAction(self)
        self.account_action.triggered.connect(self.account)
        file.addAction(self.account_action)
        self.preferences_action = QAction('&Preferences…', self)
        self.preferences_action.setShortcut(QKeySequence.StandardKey.Preferences)
        # in the application's menu on macOS, where it is looked for (#194)
        self.preferences_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.preferences_action.triggered.connect(self.preferences)
        file.addAction(self.preferences_action)
        file.addSeparator()
        quit_action = QAction('&Quit', self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.triggered.connect(self.close)
        file.addAction(quit_action)

        edit = self.menuBar().addMenu('&Edit')
        for name in ('edit.undo', 'edit.redo', None, 'edit.delete', 'edit.delete_way', 'edit.split', 'edit.unglue',
                     'edit.absorb', 'edit.push_crossings', None, 'tool.select', 'tool.draw', 'tool.spot', 'tool.measure', None):
            if name:
                edit.addAction(e[name])
            else:
                edit.addSeparator()
        water = edit.addMenu('&Water')
        for name in ('edit.import_water', 'edit.set_level', 'edit.grade', 'edit.grade_network', 'edit.flatten',
                     'edit.burn', 'edit.burn_all'):
            water.addAction(e[name])
        edit.addMenu('Spot &height').addAction(e['edit.import_heights'])
        coastline = edit.addMenu('&Coastline')
        for name in ('edit.import_coastline', 'edit.mark_coastline', 'edit.reverse_coastline'):
            coastline.addAction(e[name])
        edit.addAction(e['edit.cut_loop'])

        view = self.menuBar().addMenu('&View')
        view.addAction(e['view.magnify'])
        view.addAction(e['view.josm'])
        for name in ('view.set_west', 'view.set_east', 'view.set_north', 'view.set_south'):
            view.addAction(e[name])
        view.addSeparator()
        # the surface panel's three overlays, the same choices as its boxes
        p = self.surface_panel
        self.view_actions: dict[str, QAction] = {}
        for name, text, box in (('view.unknown', '&Unknown ground', p.show_unreached),
                                ('view.single_level', 'Single-&level ground', p.show_one_level),
                                ('view.envelope', '&Envelope', p.show_envelope),
                                ('view.ground', 'Whose &ground', p.show_ground)):
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
        p.show_ground.toggled.connect(lambda _: self.show_ground())
        refused = QAction('&Refused version', self)
        refused.setCheckable(True)
        refused.setChecked(True)
        refused.setToolTip('your version of the open square, kept when its upload was refused')
        refused.toggled.connect(self.reference.setVisible)
        view.addAction(refused)
        self.view_actions['view.refused'] = refused
        self.update_reference_actions()
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
        self.auto_rebuild_action = QAction('Rebuild &automatically', self)
        self.auto_rebuild_action.setCheckable(True)
        self.auto_rebuild_action.setChecked(self.settings.auto_rebuild)
        self.auto_rebuild_action.setToolTip('each edit rebuilt as it is made; off, the surface waits for '
                                            f'{QKeySequence(REBUILD_KEY).toString(QKeySequence.SequenceFormat.NativeText)}')
        self._logged(self.auto_rebuild_action, 'surface.auto_rebuild')
        self.auto_rebuild_action.toggled.connect(self.set_auto_rebuild)
        box = self.surface_panel.auto
        box.setChecked(self.auto_rebuild_action.isChecked())
        self.auto_rebuild_action.toggled.connect(box.setChecked)
        box.toggled.connect(self.auto_rebuild_action.setChecked)
        surface.addAction(self.auto_rebuild_action)
        self.pinch_action = QAction('&Pinch ramp on active elevation', self)
        self.pinch_action.setShortcut(QKeySequence(self.settings.key('surface.pinch')))
        self._logged(self.pinch_action, 'surface.pinch')
        self.pinch_action.triggered.connect(self.legend.pinch_on_active)
        surface.addAction(self.pinch_action)
        surface.addAction(e['view.josm_surface'])
        self.surface_actions = {'surface.pinch': self.pinch_action}

        help_ = self.menuBar().addMenu('&Help')
        # J5b: the three pages, and the wiki page that is Danu's from outside
        self.help_window = None
        self.open_url = None                         # the tests' to hand in; the browser otherwise
        self.help_actions: dict[str, QAction] = {}
        for name, text in (('getting-started', '&Getting started'), ('keys', '&Keys'), ('layers', '&Layers')):
            a = QAction(text, self)
            self._logged(a, f'help.{name}')
            a.triggered.connect(lambda _=False, n=name: self.show_help(n))
            help_.addAction(a)
            self.help_actions[name] = a
        self.help_actions['getting-started'].setShortcut(QKeySequence.StandardKey.HelpContents)
        # and the start page (J5c), over whatever is open
        self.start_action = QAction('&Start page', self)
        self._logged(self.start_action, 'help.start')
        self.start_action.triggered.connect(self.show_start)
        help_.addAction(self.start_action)
        help_.addSeparator()
        self.wiki_action = QAction('Danu on the OGF &wiki', self)
        self.wiki_action.triggered.connect(lambda: self._open(help_ui.WIKI))
        help_.addAction(self.wiki_action)
        help_.addSeparator()
        self.about_action = QAction('&About Danu', self)
        self.about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self._logged(self.about_action, 'help.about')
        self.about_action.triggered.connect(lambda: about.show(self))
        help_.addAction(self.about_action)

    def show_help(self, name: str) -> None:
        """A page of Help, in the one Help window."""
        if self.help_window is None:
            self.help_window = help_ui.HelpWindow(self.action_labels, self.settings.key, self,
                                                  open_url=self._open)
        self.help_window.show_page(name)

    def _open(self, url: str) -> None:
        if self.open_url is not None:
            self.open_url(url)
        else:
            QDesktopServices.openUrl(QUrl(url))

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
        if dlg.menu is not None and dlg.menu.isChecked() != (desktop.installed() is not None):
            self.set_menu_entry(dlg.menu.isChecked())
        self.apply_settings()
        return True

    def set_menu_entry(self, on: bool) -> bool:
        """The AppImage in the applications menu, or out of it (J5c). True
        if done; a directory that cannot be written is said."""
        image = desktop.appimage()
        try:
            if on and image is not None:
                desktop.install(image)
            elif not on:
                desktop.remove()
        except OSError as e:
            QMessageBox.warning(self, 'Danu', f'The applications menu could not be changed.\n\n{e}')
            return False
        self.settings.menu_offered = True                # answered, here or on the start page
        self.statusBar().showMessage('Danu is in the applications menu' if on
                                     else 'Danu is out of the applications menu')
        self.update_start()
        return True

    def _menu_answered(self, taken: bool) -> None:
        self.settings.menu_offered = True
        if taken:
            self.set_menu_entry(True)

    def show_newer(self, tag: str, url: str) -> None:
        """A newer release, in the status line with a link to its page."""
        self.newer.setText(f'<a href="{html.escape(url, quote=True)}">Danu {html.escape(tag.removeprefix("v"))} is out</a>')
        self.newer.setToolTip(f'You have {about.__version__}. {url}')
        self.newer.setVisible(True)

    def apply_settings(self) -> None:
        """The settings put to use, as the preferences left them: keys at
        once, the servers from their next use."""
        s = self.settings
        theme.apply(QApplication.instance(), s.theme)
        if not s.update_check:
            self.newer.setVisible(False)                 # turned off: not said either
        elif update.is_newer(s.update_latest[0]) and not update.from_store():
            self.show_newer(*s.update_latest)            # on again: what was found, said again
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
        if (s.url('drop/url'), s.server_url) != (self.drop.base_url, self.drop.server):
            self.drop.base_url, self.drop.server = s.url('drop/url').rstrip('/'), s.server_url
            self._drop_asked = None
            self.show_ground()
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
                self.profile_dock, self.selection_panel, self.zones_dock]

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
        # renamed among them: the set's file for it is under the old name, gone (#190)
        replaced = {n.split('_')[0].split('.')[0]
                    for n in (*done['new'], *done['updated'], *done['overwritten'], *done.get('renamed', ()))}
        if self._reverting is not None:
            # opened again whatever was replaced: an unsaved edit to a square
            # the server has as it is here goes too
            held = {n.split('_')[0].split('.')[0] for n in (*replaced, *done['current'])}
            gone = sorted(str(n) for n in self._reverting if str(n) not in held)
            said = (f'{", ".join(sorted(str(n) for n in self._reverting))} reverted to the server\'s'
                    + (f' - {", ".join(gone)} not on the server, so as last saved here' if gone else ''))

            def reverted(*_):
                self.loader.finished.disconnect(reverted)
                self.statusBar().showMessage(said)
            self.loader.finished.connect(reverted)
            self.open_working_set(self.zone_dir, ws.centre, ws.size)
            return
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
        # every edit left unsaved is one being reverted: thrown away, autosave
        # and all - once the read has started, so one refused keeps them
        reverting, self._reverting = self._reverting is not None, None
        if not reverting and self.autosave is not None and self.editor.dirty():
            # the set being left has edits nobody saved: kept, and offered
            # back the next time it is opened
            self.autosave.flush()
        if not self.loader.load(zone_dir, centre, size):
            self.statusBar().showMessage('still reading the last square - a moment')
            return False
        if reverting and self.autosave is not None:
            self.autosave.discard()
        self._pending = (zone_dir, centre, size)
        self.surface_wanted = False
        self.zone_dir = zone_dir
        self._start_asked = False                        # others asked for: what it was shown over has gone
        self.update_start()                              # the start page goes while it is read
        self.open_action.setEnabled(False)
        self.statusBar().showMessage(f'reading {centre} and its neighbours from {zone_dir.name}…')
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        return True

    def update_start(self) -> None:
        """The start page, while there is no working set and none is being
        read: at start when nothing opened, and after a read that failed.
        Or over the squares, asked for, until closed or others are opened."""
        nothing = self.working_set is None and self._pending is None and not self._browsing
        self.start.offer_menu(desktop.appimage() is not None and desktop.installed() is None
                              and not self.settings.menu_offered)
        self.start.set_closable(not nothing)
        self.start.setVisible(nothing or self._start_asked)

    def show_start(self) -> None:
        self._start_asked = True
        self.update_start()

    def move_set(self, dx: int, dy: int) -> None:
        """The open set a square over: Alt and an arrow."""
        ws = self.working_set
        if ws is None or self.zone_dir is None:
            self.statusBar().showMessage('open a square first')
            return
        to = ws.centre.neighbour(dx, dy)
        if to is None:
            self.statusBar().showMessage('no square past the pole')
            return
        self.open_working_set(self.zone_dir, to, ws.size)

    def open_square_at(self, p) -> bool:
        """Ctrl and a double-click: the square under it opened. One of the
        open set's - drawn or absent - the set moves onto it, from this zone's
        directory; another, the zones map's open, its zone imported first if
        need be; no zones read, from this zone's directory as well.

        Not with the draw tool: Ctrl snaps a line there, and a double-click
        ends one - a line drawn with Ctrl held moved the set mid-stroke (#258).
        False, and the double-click is the tool's."""
        if self.editor.tool == 'draw':
            return False
        lon, lat = m.scene_to_lonlat(p.x(), p.y())
        try:
            cell = SquareName(int(np.floor(lon)), int(np.floor(lat)))
        except ValueError:
            return True
        ws = self.working_set
        if ws is not None and self.zone_dir is not None and cell in ws.squares:
            self.open_working_set(self.zone_dir, cell, ws.size)
        elif self.zone_editor.zone_of(cell) is not None:
            self.zone_editor.open_square(cell)
        elif self.zone_dir is not None:
            self.open_working_set(self.zone_dir, cell, ws.size if ws is not None else self.settings.size)
        else:
            self.statusBar().showMessage(f'{cell} is in no zone: open a square first, or import its zone')
        return True

    def browse_zones(self) -> None:
        """The start page's way in (#190): the card put away, the Zones panel
        in front, and the map framed on the zones - double-click a square to
        open it. Help › Start page brings the card back."""
        self._browsing = True
        self._start_asked = False
        self.update_start()
        self.zones_dock.show()
        self.zones_dock.raise_()
        self.zone_editor.frame_all()

    def close_start(self) -> None:
        self._start_asked = False
        self.update_start()

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
        self.setWindowTitle(about.title(ws.centre, label=ws.squares[ws.centre].label))
        self._show_marks()
        self.waiting.refresh()                  # the set's folder may be outside the import folder
        self._territory.setText('territory: looking…')
        self.territory.refresh()
        self.show_reference()
        self.zone_editor.show_here()
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
        else:
            said = '; '.join(t for t in (self._close_rings(), self._drop_fill_lines()) if t)
            if said:
                self.statusBar().showMessage(said)
        self._read_alongside(ws)

    def _read_alongside(self, ws: WorkingSet) -> None:
        """The zone's squares outside the set holding water that reaches into
        it - the sea, whose home is two squares from N46E030 - read on a
        worker and held alongside the set: their water drawn and chosen as
        the set's is, an edit to it made in its home and saved with the set.
        Their contours are not the set's and are not drawn."""
        zone = self.zone_dir
        if zone is None:
            return
        cache = self._zone_water_cache
        skip = set(ws.squares) | set(ws.extra)
        bounds = ws.bounds

        def work():
            if cache is not None:
                zone_index.load_extents(cache)
            names = zone_index.reaching(zone, bounds, skip)
            files = zone_index.squares(zone)
            got = {n: read_square(files[n]) for n in names}
            if cache is not None:
                zone_index.save_extents(cache)
            return got

        def done(got):
            if self.working_set is not ws:
                return                     # another set opened meanwhile
            new = [sq for n, sq in got.items() if ws.square(n) is None]
            for sq in new:
                ws.extra[sq.name] = sq
            if new:
                self.contours.add_alongside(new)
                self.statusBar().showMessage(
                    f'water held in {", ".join(str(sq.name) for sq in new)}, outside the set, '
                    'shown where it reaches in')

        def failed(why):
            self.statusBar().showMessage(f'water outside the set not read: {why.splitlines()[0]}')
        # the last set's let go of: one still out would answer into a set gone
        if self._alongside_job is not None:
            self._alongside_job.release()
        self._alongside_job = Job(work, done, failed)
        self._checks_runner(self._alongside_job)

    def _offer_recovery(self) -> None:
        """This run's own unsaved edits to the set carried back onto it - the
        set read again in this run, moved or reopened - and what an earlier run
        autosaved for it and never saved offered, square by square; what is
        not taken is set aside, not lost."""
        ws, zone = self.working_set, self.zone_dir
        if ws is None or zone is None:
            return
        store = self.autosave.store
        mine = [e for e in store.entries(zone) if e.square in ws.squares]
        elsewhere = [e for e in store.entries() if e not in mine]
        said = []
        if mine:
            with self.autosave.held():
                # read before anything is shown: the dialog's event loop runs
                # timers, and a change taken from under it was #258
                mine, unreadable = autosave_ui.readable(mine)
                for e, why in unreadable:
                    store.set_aside(e)
                    said.append(f'the autosave of {e.square} could not be read ({why}), set aside')
                carried = [e for e in mine if self.autosave.wrote(zone, e.square) and e.refused() is None]
                offered = [e for e in mine if e not in carried]
                chosen = (autosave_ui.offer(offered, self) or []) if offered else []
                steps = autosave_ui.recovery_steps(carried + chosen, ws)
                if steps:
                    self.editor.do_across(steps)
                    back = [str(sq.name) for sq, _ in steps]
                    kept = [n for n in back if any(str(e.square) == n for e in carried)]
                    if kept:
                        said.append('unsaved edits carried: ' + ', '.join(kept))
                    if len(kept) < len(back):
                        said.append('put back the autosaved edits to '
                                    + ', '.join(n for n in back if n not in kept))
                aside = [store.set_aside(e) for e in offered if e not in chosen]
                if aside:
                    said.append(f'set aside {len(aside)} in {aside[0].parent}')
            self.autosave.flush()                        # the recovery is the autosave now
        if elsewhere:
            names = ', '.join(f'{e.square} ({e.zone.name})' for e in elsewhere[:4])
            said.append(f'autosaved edits are held for {names}{" and more" if len(elsewhere) > 4 else ""}'
                        ' - open there to recover them')
        said += [t for t in (self._close_rings(), self._drop_fill_lines()) if t]
        if said:
            self.statusBar().showMessage('; '.join(said))

    def _close_rings(self) -> str:
        """The set's rings closed by position only, closed onto their first
        node - one step, after any recovery, whose edits name the nodes as
        the file had them. What it says, or ''."""
        ws = self.working_set
        steps = [(sq, cmd) for sq in ws.squares.values() if (cmd := edits.close_rings(sq)) is not None]
        if not steps:
            return ''
        self.editor.do_across(steps)
        n = sum(len(cmd.closes) for _, cmd in steps)
        what = ('ring whose last node stood at its first node\'s place' if n == 1 else
                'rings whose last node stood at their first node\'s place')
        return f'closed {n:,} {what}, in ' + ', '.join(str(sq.name) for sq, _ in steps) + ' - saving keeps it'

    def _drop_fill_lines(self) -> str:
        """The set's fill lines taken out - ``danu:fill``, drawn across a lake
        by flattening to hold it flat until the build held a lake at its
        level itself (#191) - one step, after any recovery. What it says, or
        ''."""
        ws = self.working_set
        steps = [(sq, cmd) for sq in ws.squares.values() if (cmd := edits.drop_fill_lines(sq)) is not None]
        if not steps:
            return ''
        n = sum(len(cmd.ids) for _, cmd in steps)
        for _, cmd in steps:
            cmd.total = n
        self.editor.do_across(steps)
        return (f'removed {n:,} fill line{"s" * (n != 1)} across lakes, in '
                + ', '.join(str(sq.name) for sq, _ in steps)
                + ' - no longer drawn; saving keeps it')

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
        # the edits so far are in this build; one made after it is asked for
        # puts the surface out of date again
        self._surface_out_of_date = self.surface_wanted = False
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
        # the server builds at 1 arcsecond; the editor at 3, with the view at
        # 1 from z15 (R43). It said "the same stages the server runs", which
        # read as the same surface, and was no longer what was happening
        self.statusBar().showMessage(
            f'building the surface at {self._arcsec:g}″ by the server\'s stages - '
            + ('at z15 and closer the view is solved at 1″' if self._arcsec == ARCSEC
               else 'the whole set at this resolution, for comparing'))

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

    def import_coastline(self) -> bool:
        """The main map's coastlines, into the squares at ele=0 - asked for,
        as water is, and reconciled the same way."""
        if self.working_set is None:
            self.statusBar().showMessage('open a square first')
            return False
        queued = self.coast.busy
        self.coast.request(self.working_set)
        if queued:
            self.statusBar().showMessage('already importing; the newer request wins')
        return True

    def _coast_imported(self, answer, working_set):
        """One coastline import, one step on the history: upstream's way and
        direction, the square's ele kept, and a held one upstream no longer
        has reported and kept."""
        if working_set is not self.working_set:
            self.statusBar().showMessage(
                'the working set changed while the coastlines were fetched - import again')
            return
        self.gone_from_upstream = coast.gone(working_set, answer.ways)
        steps = coast_commands(answer.placed, working_set)
        if steps:
            self.editor.do_across(steps)
        kept_doubled = self._doubled(working_set)
        self.gone_dock.show_report(self.gone_from_upstream, reshaped=[])
        if self.gone_from_upstream:
            self.gone_dock.show()
            self.gone_dock.raise_()
        n = sum(len(w.ways) for w in answer.placed.values())
        kept = (f'; {len(self.gone_from_upstream)} held no longer upstream, kept'
                if self.gone_from_upstream else '')
        if not n:
            self.statusBar().showMessage(f'no coastline in this working set{kept}{kept_doubled}')
            return
        where = ', '.join(f'{name} {len(answer.placed[name].ways)}' for name in sorted(answer.placed, key=str))
        self.statusBar().showMessage(f'imported {n} coastline way{"s" * (n != 1)} at 0 m - {where}{kept}'
                                     f'{kept_doubled}. {_undo_hint(kept_doubled)}')

    def _doubled(self, working_set) -> str:
        """After an import: the negative contours lying wholly on top of a
        main-map way at their level, removed - a step of their own, so the
        first Ctrl+Z puts them back and the second takes the import. Said
        as the end of the import's message."""
        steps = doubled.commands(working_set)
        if not steps:
            return ''
        self.editor.do_across(steps)
        n = sum(isinstance(c, edits.DeleteWay) for _, cmd in steps for c in cmd.commands)
        said = f'; {n} contour{"s" * (n != 1)} doubled under the main map\'s removed, its kept'
        # a water relation with no level of its own takes the one its
        # recovered shore held: the sea, at 0 m
        given = [(sq, c) for sq, cmd in steps for c in cmd.commands if isinstance(c, edits.SetRelationTags)]
        if given:
            names = [sq.relations[c.relation_id].tags.get('name') or f'relation {c.relation_id}' for sq, c in given]
            said += (f'; {", ".join(names[:3])}{" and more" if len(names) > 3 else ""} given the level '
                     f'{"its" if len(names) == 1 else "their"} recovered shore had')
        return said

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
        self.gone_from_upstream = gone(working_set, answer.ways, answer.relations, answer.on)
        # and the lakes flattened here, as they stand, to see which the
        # import reshapes - their fill lines and clipped contours were laid
        # against the old outline (G7a-bis)
        was_flat = flatten.flattened(working_set)
        merged = [g for g in self.gone_from_upstream if g.merged_into]
        held = len(self.gone_from_upstream) - len(merged)
        kept = (f'; {held} held no longer upstream, kept' if held else '') + (
            f'; {len(merged)} merged upstream into other ways, removed' if merged else '')
        # the zone's squares outside the set a home is in, or was, read on
        # the worker: alongside the set from now, edited and saved with it
        for name, sq in answer.loaded.items():
            if working_set.square(name) is None:
                working_set.extra[name] = sq
        # a feature whose home moved: out of where it was, its level with it
        steps = move_commands(answer, working_set, self.editor.history.alloc)
        steps += water_commands(placed, working_set)
        outside = sorted({str(n) for n in placed if n not in working_set.squares})
        if outside:
            kept += (f'; held in {", ".join(outside)}, outside the set where most of it lies - '
                     'saved with the set')
        if answer.moved:
            n = sum(1 for kind, _ in answer.moved if kind == 'relation') or len(answer.moved)
            kept += f'; {n} moved to where most of {"them" if n != 1 else "it"} now lies'
        # after the import, which has moved their nodes where upstream has
        # them: a merged way's nodes are its new ways', and only the ones
        # nothing in the square holds go with it (#250)
        steps += [(working_set.squares[g.square], edits.DeleteWay(g.id)) for g in merged]
        if steps:
            # the editor's own path, not a copy of it: see EditController.do_across
            self.editor.do_across(steps)
        kept_doubled = self._doubled(working_set)
        kept += kept_doubled
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
            f'imported {features} water features - {where}{kept}. {_undo_hint(kept_doubled)}')

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
                if self._checks_redo or sum(len(w) + len(s) for _, w, s in self._checks_missed) > WIDE_EDIT:
                    # edited too widely meanwhile to put to it way by way: found again
                    self._checks_redo, self._checks_missed = False, []
                    self._checks_shown(self.checks_dock.isVisible())
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
        the first scan runs is kept for it. One of more than WIDE_EDIT ways
        has them found again whole, on the worker."""
        wide = len(ways or ()) + len(spot_ids or ()) > WIDE_EDIT
        if self._checks_job is not None:
            if wide or self._checks_redo:
                self._checks_redo, self._checks_missed = True, []
            else:
                self._checks_missed.append((square, set(ways or ()), set(spot_ids or ())))
            return
        if self.crossing_index is not None and (wide or self._checks_wide):
            if self.surface_findings is not None and (ways or spot_ids):
                self._surface_stale = True
            if not self._checks_wide:
                self._checks_wide = True             # once for the step, whatever squares it spans
                QTimer.singleShot(0, self._checks_again)
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

    def _checks_centre_only(self, on: bool) -> None:
        self.settings.checks_centre_only = on
        # a surface build's findings can be there with no scan yet; one
        # running fills the panel itself when it lands
        if self._checks_job is None:
            self._refresh_checks()

    def _shown(self, found):
        """What the panel lists and the map marks of a check's findings: all
        the set's, or with Centre square only, those in the centre square -
        one on its edge counts."""
        ws = self.working_set
        if found is None or ws is None or not self.checks_dock.centre_only.isChecked():
            return found
        w, s, e, n = ws.centre.bounds
        return [f for f in found if w <= f.lon <= e and s <= f.lat <= n]

    def _checks_again(self) -> None:
        """The checks found again whole, on the worker, after an edit too wide
        to put to them way by way."""
        self._checks_wide = False
        (self.crossing_index, self.loop_index, self.touch_index, self.spot_index,
         self.file_index, self.inside_index) = (None,) * 6
        self._checks_shown(self.checks_dock.isVisible())

    def _refresh_checks(self) -> None:
        sh = self._shown
        self.checks_dock.show_crossings(sh(self.crossing_index.crossings() if self.crossing_index is not None else []))
        self.checks_dock.show_loops(sh(self.loop_index.loops() if self.loop_index is not None else []))
        self.checks_dock.show_touches(sh(self.touch_index.touches() if self.touch_index is not None else []))
        self.checks_dock.show_spots(sh(self.spot_index.contradictions() if self.spot_index is not None else []))
        self.checks_dock.show_files(sh(self.file_index.findings() if self.file_index is not None else []))
        self.checks_dock.show_inside(sh(self.inside_index.findings() if self.inside_index is not None else []))
        self.checks_dock.show_surface(sh(self.surface_findings), self._surface_found_at, self._surface_stale,
                                      self._surface_pending)
        self._refocus()
        self._refresh_marks()

    def _focus(self, pts: list) -> None:
        """The rings round the row chosen in the panel - kept as the panel's,
        so a refresh after an edit can follow them."""
        self.editor.marks_focus = self._panel_focus = pts

    def _refocus(self) -> None:
        """The panel's rings, after a refresh: round what the row chosen finds
        now, or gone with the row once what it found is mended. Rings a tool
        put up - a move refused - are the tool's, and stay. The selection and
        the view are left as they are: the mapper is mid-edit."""
        if self._panel_focus is None or self.editor.marks_focus is not self._panel_focus:
            return
        found = self.checks_dock.current_finding()
        if found is None:
            self._panel_focus = None
            self.editor.marks_focus = []
            return
        check, f = found
        self._focus([m.lonlat_to_scene(c.lon, c.lat) for c in (f[1] if check == 'crossings' else [f])])

    def _refresh_marks(self) -> None:
        """The crossings marked on the map while the panel is open, and not
        otherwise: 6,714 red crosses over gobras are what the panel is for,
        not what drawing a contour is."""
        on = self.checks_dock.isVisible() and self.crossing_index is not None
        sh = self._shown
        self.editor.marks = ([m.lonlat_to_scene(c.lon, c.lat) for c in sh(self.crossing_index.crossings())]
                             + [m.lonlat_to_scene(lp.lon, lp.lat)
                                for lp in sh(self.loop_index.loops() if self.loop_index is not None else [])]
                             + [m.lonlat_to_scene(t.lon, t.lat)
                                for t in sh(self.touch_index.touches() if self.touch_index is not None else [])]
                             + [m.lonlat_to_scene(c.lon, c.lat)
                                for c in sh(self.spot_index.contradictions() if self.spot_index is not None else [])]
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in sh(self.file_index.findings() if self.file_index is not None else [])]
                             # the lakes, and not the report: 3,882 rings over gobras would be
                             # crosses over every hill
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in sh(self.inside_index.findings('lake') if self.inside_index is not None else [])]
                             # a square of unreached ground is a row, not a place to mark
                             + [m.lonlat_to_scene(f.lon, f.lat)
                                for f in sh(self.surface_findings or []) if f.kind != 'unreached']
                             if on else [])
        if not on:
            self.editor.marks_focus = []
        self.editor.overlay.update()

    def _choose_crossing(self, key, found) -> None:
        """A row of the Validation panel chosen: its contour selected, its
        crossings ringed and brought into view."""
        ws = self.working_set
        square = ws.squares.get(key[0]) if ws is not None else None
        way = square.ways.get(key[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {key[1]} is no longer in {key[0]}')
            return
        self.editor.set_tool('select')
        self.editor.selection = Selection(square, way)
        self._focus([m.lonlat_to_scene(c.lon, c.lat) for c in found])
        lons, lats = [c.lon for c in found], [c.lat for c in found]
        self._show_place(min(lons), min(lats), max(lons), max(lats))
        self.editor.overlay.update()
        n = len(found)
        self.statusBar().showMessage(
            f'the {key[2]:g} m contour, way {key[1]} - {n} crossing{"s" * (n != 1)} ringed; '
            'delete it or redraw over it, whichever of the two is wrong')

    def _choose_loop(self, loop) -> None:
        """A contour crossing itself, chosen in the Validation panel: it
        selected, the place ringed and brought into view - G8c."""
        ws = self.working_set
        square = ws.squares.get(loop.contour[0]) if ws is not None else None
        way = square.ways.get(loop.contour[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {loop.contour[1]} is no longer in {loop.contour[0]}')
            return
        self.editor.set_tool('select')
        self.editor.selection = Selection(square, way)
        self._focus([m.lonlat_to_scene(loop.lon, loop.lat)])
        self._show_place(loop.lon, loop.lat, loop.lon, loop.lat)
        self.editor.overlay.update()
        key = self.settings.key('edit.cut_loop') or 'O'
        self.statusBar().showMessage(f'{loop.explain()} - ringed; {key} proposes the loop cut out')

    def _choose_touch(self, touch) -> None:
        """Contours that touch, chosen in the Validation panel: the first of
        them selected - at the node, for one two levels share, so U unglues
        it - the place ringed and brought into view (G8e)."""
        ws = self.working_set
        square = ws.squares.get(touch.a[0]) if ws is not None else None
        way = square.ways.get(touch.a[1]) if square is not None else None
        if way is None:
            self.statusBar().showMessage(f'way {touch.a[1]} is no longer in {touch.a[0]}')
            return
        self.editor.set_tool('select')
        node = touch.node if touch.kind in ('shared', 'fork') and touch.node in way.refs else None
        self.editor.selection = Selection(square, way, node)
        self._focus([m.lonlat_to_scene(touch.lon, touch.lat)])
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
        self._focus([m.lonlat_to_scene(c.lon, c.lat)])
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
            self._focus([m.lonlat_to_scene(f.lon, f.lat)])
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
        self._focus([m.lonlat_to_scene(f.lon, f.lat)])
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

    def _edited_ways(self, square, ways, spots) -> None:
        if self.settings.auto_rebuild:
            self.preview.edited(square, ways, spots)
            return
        if not self._surface_out_of_date and self._arcsec:
            self._surface_out_of_date = True
            self.statusBar().showMessage(
                'the surface is out of date: automatic rebuilds are off - '
                f'{QKeySequence(REBUILD_KEY).toString(QKeySequence.SequenceFormat.NativeText)} rebuilds it')

    def set_auto_rebuild(self, on: bool) -> None:
        """Surface › Rebuild automatically (#239). Off, edits leave the
        surface as it is - no preview, no rebuild once the drawing stops, the
        close view not solved again - until Ctrl+R. On again, what was edited
        meanwhile is rebuilt then."""
        self.settings.auto_rebuild = on
        if self.auto_rebuild_action.isChecked() != on:
            self.auto_rebuild_action.setChecked(on)
        if not on:
            self.preview.stop_waiting()
        elif self._surface_out_of_date and self._arcsec:
            self.rebuild_surface(self._arcsec)

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
        # what it was asked for is still to build: off, turning automatic
        # rebuilds on again rebuilds it
        self._surface_out_of_date = bool(self._arcsec and self.editor.history.dirty_squares())
        self.surface_panel.failed(text)
        self.statusBar().showMessage('the surface could not be built')
        QMessageBox.warning(self, 'Danu', f'The surface could not be built.\n\n{text}')

    def _load_failed(self, text: str):
        QApplication.restoreOverrideCursor()
        self.open_action.setEnabled(True)
        self._pending = None
        self.update_start()
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
    # a crash on purpose, to see a build report one: python, thread or fault
    ap.add_argument('--crash', choices=crash.PROVOKE, help=argparse.SUPPRESS)
    args = ap.parse_args(argv[1:])
    if bool(args.zone_dir) != bool(args.square):
        ap.error('give both a zone directory and a square, or neither')

    quieten_qt()          # before the first request; see danu.ui.messages
    app = QApplication(argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(about.__version__)
    # the Wayland app id and the X11 class: what the desktop matches to
    # danu.desktop for the name and icon it shows. Unset, Qt took it from
    # argv[0], which under python -m is __main__
    app.setDesktopFileName(APP_NAME)
    app.setWindowIcon(about.icon())
    # what nothing catches from here on is written down and offered as an
    # issue; a fault in C at the next start (J6)
    reporter = crash.Reporter(user_data_dir() / 'crashes')
    reporter.install()
    # garbage collected on this thread alone, never on a worker that would
    # free a Qt object the window is painting with - danu.ui.collector
    from .collector import MainThreadCollector
    collector = MainThreadCollector(app)
    # the theme before the first widget, which would be drawn in the desktop's
    settings = Settings()
    theme.apply(app, settings.theme)
    # an AppImage moved, or its newer self run, keeps its place in the menu
    try:
        desktop.follow(desktop.appimage())
    except OSError:
        pass                                     # left as it was; the preferences say where it is
    layers = config.load_layers(user_config_dir() / config.USER_FILE)
    win = MainWindow(layers, cache_dir=user_cache_dir() / 'tiles', data_dir=user_data_dir(),
                     settings=settings)
    reporter.attach(win)
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
    if settings.start_always:
        win.show_start()                         # over what is opening, by the preferences
    win.update_start()                           # nothing opened, or opening: the start page or not
    QTimer.singleShot(0, reporter.offer_earlier)  # a run that died, once the window is up
    # a newer release, asked of GitHub once a day; in main, so no test's window asks
    win.updates = update.UpdateCheck(settings, win)
    win.updates.found.connect(win.show_newer)
    win.updates.start()
    if args.crash:
        QTimer.singleShot(1000, lambda: crash.provoke(args.crash))
    try:
        return app.exec()
    finally:
        collector.stop()
        reporter.uninstall()
