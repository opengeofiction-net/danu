"""The surface on the map - R9, R10, R11.

One SurfaceLayer, a QGraphicsItem holding one pixmap: the working set's DEM,
built by the same stages the server runs, shaded by the same stages the server
runs, coloured through a Ramp and laid on the canvas at the Mercator extent the
warp gave it. Slow and exact, as phase 2 says: the build runs on a worker and
takes as long as it takes; the surface it shows is the one the nightly build
would publish for these squares, at the resolution chosen.

Recolouring is cheap and stays on the UI thread: the arrays are kept, and a
change of ramp, scaling or mode is a compose() and a new pixmap. Rebuilding is
not, and asks the worker.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFormLayout,
                               QGraphicsItem, QLabel, QPushButton, QSlider, QWidget)

from ..core.square import WorkingSet
from ..surface import shade
from ..surface.params import Params
from ..surface.ramp import Ramp, spectral, traditional

RESOLUTIONS = ((3.0, '3″ - a minute a set, the .hgt archive\'s'), (1.0, '1″ - the published DEM\'s, slow'))
MODES = ('shaded relief', 'hillshade', 'relief')
RAMPS = {'spectral': spectral, 'traditional': traditional}


# ------------------------------------------------------------------ worker

@dataclass
class Built:
    """What the worker hands back: the surface, and what it cannot say."""
    shaded: shade.Shaded
    envelope_rings: list = field(default_factory=list)
    rasters: 'Rasters | None' = None      # for the preview; None when it is off
    params: Params | None = None          # the ones it was actually built with


@dataclass
class Rasters:
    """The build's own grids, kept so an edit can be previewed against them
    rather than rebuilt.

    Held in memory, which is what bounds this: 308 MB for the gobras 3x3 at 3
    arcseconds, and 1.5 to 2.8 GB at 1. So they are kept at the drawing
    resolution and not at the publishing one, where the editor already says
    "slow" in the menu and an edit waits for the exact build. PREVIEW_ARCSEC
    is where that line is drawn.
    """
    constraints: np.ndarray
    mask: np.ndarray
    water: np.ndarray | None
    surface: np.ndarray
    dem: np.ndarray
    geotransform: tuple
    projection: str
    nodata: float
    gpkg: Path


# Above this, the rasters the preview needs are gigabytes and are not kept.
# 3 arcseconds is 308 MB for a three by three and is the resolution drawing
# happens at; 1 arcsecond is the published DEM's, is labelled slow where it is
# chosen, and rebuilds exactly instead.
PREVIEW_ARCSEC = 3.0


class _Signals(QObject):
    finished = Signal(object)        # Built
    failed = Signal(str)


def build_surface(zone_dir: Path, names: list, params: Params, work: Path) -> Built:
    """The squares in ``zone_dir`` as a shaded surface. Runs on a worker and
    touches no Qt object, so it is also the seam the queue's tests replace."""
    # here and not at import: building needs GDAL, looking does not
    from ..surface import build
    # keep_pass1: the overlay wants what the first pass could not answer, and
    # the first pass is nearly all of the fill. Asking for it here is the
    # difference between an edit costing one fill and two - 95 s of the 208 s
    # at 1 arcsecond on a three by three set
    result = build.build_dem(zone_dir, work, params, names=names, keep_pass1=True)
    if result.dem is None:
        raise Nothing('nothing to build: no square in the set holds a contour')
    classes = build.first_pass_classes(result.constraints, result.drawn_mask, params, work)
    shaded = shade.shade_dem(result.dem, params, work, classes=classes)
    from .overlays import envelope_rings
    # the outline is a courtesy; its file missing is not a failed surface
    rings = envelope_rings(result.envelopes) if result.envelopes and result.envelopes.exists() else []
    return Built(shaded, rings, rasters=_rasters(result, work, params), params=params)


def _rasters(result, work: Path, params: Params):
    """The build's grids as arrays, or None where the preview is off.

    Read here, on the worker, because reading them is I/O and the UI thread is
    where the frames are."""
    if params.arcsec > PREVIEW_ARCSEC:
        return None
    try:
        return _read_rasters(result, work)
    except Exception:      # noqa: BLE001
        # The preview is a bonus and must not be able to fail a surface. A
        # build that produced a DEM has produced the thing the user asked for;
        # if its intermediate grids cannot be read back, the editor loses the
        # live preview and rebuilds on every edit instead, which is what it did
        # before phase 4.
        return None


def _read_rasters(result, work: Path):
    from osgeo import gdal
    held = {}

    def read(path, dtype=None):
        ds = gdal.Open(str(path))        # held: the band dies with the dataset
        held[str(path)] = ds
        a = ds.GetRasterBand(1).ReadAsArray()
        return a.astype(dtype) if dtype is not None else a

    cons = read(result.constraints, np.float32)
    band = held[str(result.constraints)].GetRasterBand(1)
    dem_ds = gdal.Open(str(result.dem))
    return Rasters(constraints=cons,
                   mask=read(result.drawn_mask),
                   water=read(result.water_mask) if result.water_mask else None,
                   surface=read(result.surface, np.float32),
                   dem=dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32),
                   geotransform=tuple(dem_ds.GetGeoTransform()),
                   projection=dem_ds.GetProjection(),
                   nodata=band.GetNoDataValue(),
                   gpkg=result.contours_gpkg)


class Nothing(Exception):
    """There is nothing to build - reported as itself, not as a traceback."""


class _Job(QRunnable):
    def __init__(self, fn, zone_dir: Path, names: list, params: Params, work: Path,
                 signals: _Signals):
        super().__init__()
        self.fn, self.zone_dir, self.names = fn, zone_dir, names
        self.params, self.work, self.signals = params, work, signals
        # set when run() returns, however it returns. What makes it safe to
        # remove the working directory is that the build has stopped writing,
        # which is this - not the delivery of a signal, which is queued to
        # another thread and arrives later.
        self.done = threading.Event()

    def run(self):
        try:
            self._run()
        finally:
            self.done.set()

    def _run(self):
        try:
            built = self.fn(self.zone_dir, self.names, self.params, self.work)
        except Nothing as e:
            self._say(str(e))
            return
        except ImportError as e:
            self._say(f'building a surface needs GDAL, which could not be imported: {e}')
            return
        except Exception as e:      # noqa: BLE001 - reported as text, on the UI thread
            self._say(f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}')
            return
        try:
            self.signals.finished.emit(built)
        except RuntimeError:
            pass                    # see _say

    def _say(self, text: str):
        """Report a failure, unless there is no longer anyone to report it to.

        A job outlives the window when the application is closing, and emitting
        then raises *Signal source has been deleted* out of QRunnable::run -
        which Qt prints and nobody sees. The failure being reported is usually
        the teardown itself, so the report is worth less than the crash costs.
        """
        try:
            self.signals.failed.emit(text)
        except RuntimeError:
            pass


class SurfaceBuilder(QObject):
    """One build at a time, newest wins.

    A request made while a build is running does not queue behind it and does
    not bounce: it replaces whatever else was waiting, so a run of edits costs
    one more build and not one each. Only the newest is ever started, because
    only the newest is what is drawn.

    A build already running cannot be stopped - `isofill` is a C call with no
    cancellation hook, and the pass it is in has to finish. So a superseded
    build is spent either way, and what it hands back is shown rather than
    thrown away: it is the surface as things stood a moment ago, which beats a
    blank canvas while the newer one runs. ``finished`` says whether it is
    stale, and R19's job is to make that visible.

    Staging happens when a build starts, not when it is asked for - it is 177
    ms on the gobras 3x3, and coalesced requests should not each pay it.

    How long a build took travels with its result. A single attribute on the
    window cannot hold it once builds overlap: a superseded build is delivered
    while its successor is already queued, and one slot is one build's worth of
    a quantity there are now two of. It happens to be safe today - ``_done``
    emits before it starts the next - but that is an ordering nobody can see
    from the window, so the number goes in the signal instead.
    """
    started = Signal()
    finished = Signal(object, bool, float)   # Built, stale, seconds
    failed = Signal(str)

    def __init__(self, parent=None, build_fn=build_surface, runner=None):
        super().__init__(parent)
        self._build_fn = build_fn
        self._runner = runner or QThreadPool.globalInstance().start
        self._serial = 0          # requests made
        self._started = 0         # the serial the running build was started for
        self._started_at = 0.0    # and when, so its own elapsed time goes back with it
        self._wanted = None       # the newest request not yet started
        self._running = False
        self._signals = None
        self._job = None
        self.work = Path(tempfile.mkdtemp(prefix='danu-surface-'))

    @property
    def busy(self) -> bool:
        return self._running

    def request(self, ws: WorkingSet, params: Params, dirty=()) -> int:
        """Ask for a surface, and get the serial the request was given.

        Always accepted. If a build is running this displaces any request
        already waiting behind it; the working set is read when the build
        starts, so what gets built is the newest state either way.
        """
        self._serial += 1
        self._wanted = (ws, params, tuple(dirty))
        if not self._running:
            self._start()
        return self._serial

    def _start(self):
        ws, params, dirty = self._wanted
        self._wanted = None
        self._started = self._serial
        self._started_at = time.monotonic()
        # staged from memory on this thread: the worker must not read squares
        # the tools are editing
        from ..core.save import stage_zone
        zone_dir = stage_zone(ws.squares.values(), dirty, self.work / 'zone')
        names = [sq.name for sq in ws.squares.values() if sq.present or sq.ways]
        self._running = True
        sig = _Signals()
        sig.finished.connect(self._done)
        sig.failed.connect(self._fail)
        job = _Job(self._build_fn, zone_dir, names, params, self.work, sig)
        job.setAutoDelete(False)         # Python owns it; see the note in loader.py
        self._signals, self._job = sig, job
        self.started.emit()
        self._runner(job)

    def _done(self, built):
        self._running = False
        stale = self._wanted is not None
        self.finished.emit(built, stale, time.monotonic() - self._started_at)
        self._next()

    def _fail(self, text):
        self._running = False
        self.failed.emit(text)
        self._next()

    def _next(self):
        if self._wanted is not None and not self._running:
            self._start()

    def cleanup(self, wait_ms: int = 15_000) -> bool:
        """Stop taking work and remove the working directory.

        Waits for the build that is running, because the directory is where it
        is writing. Removing it underneath cost a traceback ending

            RuntimeError: .../rounded.tif: No such file or directory

        from inside the clamp - the build had got as far as wanting the file
        the rmtree had just taken. Closing the window during a build used to
        mean closing during a Ctrl+R and was rare; once an idle timer started
        asking for builds by itself, it became what closing after drawing
        does.

        If the wait runs out the directory is left behind rather than pulled
        out from under a live writer. It is a temporary directory and the
        system will have it.

        What this does *not* wait for is the finished signal, which is queued
        to the UI thread and arrives after. A handler that goes back to the
        directory - reopening the GeoPackage, say - finds it gone. That is
        only safe because the one caller is ``closeEvent``, where a complaint
        about a vanished temporary path is the last thing that happens; a
        second caller would want the results drained first.
        """
        self._wanted = None                  # nothing more starts
        done = True
        if self._running and self._job is not None:
            # the job's own flag, not the pool's: waitForDone would wait on
            # whatever else is using the global pool and would answer for a
            # job that never reached it
            done = self._job.done.wait(wait_ms / 1000.0)
        if done:
            shutil.rmtree(self.work, ignore_errors=True)
        return done


# ------------------------------------------------------------------- layer

@dataclass
class Style:
    mode: str = 'shaded relief'
    ramp: str = 'spectral'
    scaling: shade.Scaling = field(default_factory=shade.Scaling)
    shade_strength: float = 1.0


class SurfaceLayer(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setZValue(50)                 # over the tiles, under the squares and contours
        self.shaded: shade.Shaded | None = None
        self.style = Style()
        self._pixmap: QPixmap | None = None
        self._rect = QRectF()
        self._array = None
        self._stretch: tuple | None = None
        self._preview = False

    def set_shaded(self, shaded: shade.Shaded | None):
        self.prepareGeometryChange()
        self.shaded = shaded
        if shaded is None:
            self._pixmap, self._rect, self._array = None, QRectF(), None
        else:
            l, t, r, b = shaded.scene_rect
            self._rect = QRectF(l, t, r - l, b - t)
            self.recolour()
        self.update()

    def set_style(self, style: Style):
        self.style = style
        if self.shaded is not None:
            self.recolour()
            self.update()

    def recolour(self):
        """compose() the kept arrays into the pixmap.

        Not cheap, which I had asserted it was without measuring. On the gobras
        3x3 at 3 arcseconds the composed array is 24.4 M cells and this is
        1,472 ms in shaded relief, 1,376 in relief and 275 in hillshade - about
        twenty-four times the solve it follows. A preview that took 62 ms to
        work out was spending a second and a half being shown, which is what
        recolour_box is for.
        """
        ramp: Ramp | None = None if self.style.mode == 'hillshade' else RAMPS[self.style.ramp]()
        self._stretch = self.style.scaling.range_for(self.shaded.dem)
        rgba = shade.compose(self.shaded, ramp, self.style.scaling, self.style.mode,
                             self.style.shade_strength, stretch=self._stretch)
        rows, cols = rgba.shape[:2]
        # QImage over the array, then a copy so the array may go
        self._array = np.ascontiguousarray(rgba)
        img = QImage(self._array.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(img.copy())

    def recolour_box(self, y0: int, x0: int, rows: int, cols: int) -> bool:
        """Recolour one rectangle of the surface and paint it into the pixmap.

        The colour scale is the one the last whole recolour worked out, not one
        worked out from the rectangle: in ``auto`` the range comes from the
        land in the whole array, and a patch that restretched to its own
        contents would come out a different colour from the ground around it.
        It also stops the scale jumping on every edit, which is worth having
        anyway; the next whole recolour brings it up to date.
        """
        if self._pixmap is None or self._array is None or self.shaded is None:
            return False
        y0, x0 = max(0, y0), max(0, x0)
        rows = min(rows, self._array.shape[0] - y0)
        cols = min(cols, self._array.shape[1] - x0)
        if rows <= 0 or cols <= 0:
            return False
        sl = (slice(y0, y0 + rows), slice(x0, x0 + cols))
        ramp: Ramp | None = None if self.style.mode == 'hillshade' else RAMPS[self.style.ramp]()
        window = shade.Shaded(dem=self.shaded.dem[sl], shade=self.shaded.shade[sl],
                              geotransform=self.shaded.geotransform, metres=self.shaded.metres)
        rgba = np.ascontiguousarray(
            shade.compose(window, ramp, self.style.scaling, self.style.mode,
                          self.style.shade_strength, stretch=self._stretch))
        self._array[sl] = rgba
        img = QImage(rgba.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        painter = QPainter(self._pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(x0, y0, img)
        painter.end()
        self.update()
        return True

    def boundingRect(self) -> QRectF:
        return self._rect

    def set_preview(self, previewing: bool):
        """Whether what is drawn is a preview or the exact build - R19's "the
        two states are distinguishable at a glance"."""
        if previewing != self._preview:
            self._preview = previewing
            self.update()

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(self._rect, self._pixmap, QRectF(self._pixmap.rect()))
        if self._preview:
            # A dashed edge around the surface. Cosmetic, so the width is in
            # device pixels and stays the same on screen at any zoom - a pen
            # in scene units would thicken as the view zoomed in. Around the
            # whole surface and not the
            # patch: what is provisional is the surface, since one preview's
            # rim is the next one's ground, and outlining the last box edited
            # would say the rest had been settled.
            pen = QPen(QColor(255, 170, 0), 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._rect)


# ------------------------------------------------------------------- panel

class SurfacePanel(QDockWidget):
    """Rebuild, resolution, mode, ramp, scaling and opacity. It edits the
    layer's Style and asks the window to rebuild; it computes nothing."""

    rebuild = Signal(float)              # arcsec
    styleChanged = Signal(object)        # the Style, after every change

    def __init__(self, layer: SurfaceLayer, parent=None, unreached=None, envelope=None):
        super().__init__('Surface', parent)
        self.setObjectName('surface')
        self.layer = layer
        self.unreached, self.envelope = unreached, envelope
        body = QWidget()
        form = QFormLayout(body)

        self.resolution = QComboBox()
        for arcsec, label in RESOLUTIONS:
            self.resolution.addItem(label, arcsec)
        self.button = QPushButton('Rebuild surface')
        self.button.clicked.connect(lambda: self.rebuild.emit(float(self.resolution.currentData())))
        form.addRow('Resolution', self.resolution)
        form.addRow(self.button)

        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.ramp = QComboBox()
        self.ramp.addItems(list(RAMPS))
        self.scaling = QComboBox()
        self.scaling.addItems(['auto', 'manual', 'pinch'])
        self.lo = QDoubleSpinBox(); self.lo.setRange(-500, 9000); self.lo.setValue(0)
        self.hi = QDoubleSpinBox(); self.hi.setRange(-500, 9000); self.hi.setValue(1000)
        # the planet's range and then some: a legend drag must never be clamped here
        self.centre = QDoubleSpinBox(); self.centre.setRange(-12000, 12000); self.centre.setValue(100)
        self.width = QDoubleSpinBox(); self.width.setRange(1, 24000); self.width.setValue(50)
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(0, 100); self.opacity.setValue(85)
        self.show_unreached = QCheckBox('Ground the contours do not describe')
        self.show_unreached.setChecked(True)
        self.show_one_level = QCheckBox('…and cells seeing one level (mostly beside contours)')
        self.show_one_level.setChecked(False)
        self.show_envelope = QCheckBox('Envelope of the drawn ground')
        self.show_envelope.setChecked(True)
        self.reading = QLabel('')
        self.reading.setWordWrap(True)
        self.status = QLabel('no surface built yet')
        self.status.setWordWrap(True)
        form.addRow('Show', self.mode)
        form.addRow('Ramp', self.ramp)
        form.addRow('Scaling', self.scaling)
        form.addRow('Min / max', self._pair(self.lo, self.hi))
        form.addRow('Pinch centre / width', self._pair(self.centre, self.width))
        form.addRow('Opacity', self.opacity)
        form.addRow(self.show_unreached)
        form.addRow(self.show_one_level)
        form.addRow(self.reading)
        form.addRow(self.show_envelope)
        form.addRow(self.status)
        self.setWidget(body)
        if self.unreached is not None:
            self.show_unreached.toggled.connect(self.unreached.setVisible)
            self.show_one_level.toggled.connect(self.unreached.set_one_level)
        if self.envelope is not None:
            self.show_envelope.toggled.connect(self.envelope.setVisible)

        for w in (self.mode, self.ramp, self.scaling):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.lo, self.hi, self.centre, self.width):
            w.valueChanged.connect(self._changed)
        self.opacity.valueChanged.connect(lambda v: self.layer.setOpacity(v / 100.0))
        self.layer.setOpacity(0.85)
        self._changed()

    @staticmethod
    def _pair(a, b):
        w = QWidget()
        lay = QFormLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addRow(a)
        lay.addRow(b)
        return w

    def current_style(self) -> Style:
        return Style(mode=self.mode.currentText(), ramp=self.ramp.currentText(),
                     scaling=shade.Scaling(self.scaling.currentText(), self.lo.value(), self.hi.value(),
                                           self.centre.value(), self.width.value()))

    def _changed(self, *_):
        manual, pinch = self.scaling.currentText() == 'manual', self.scaling.currentText() == 'pinch'
        for w in (self.lo, self.hi):
            w.setEnabled(manual)
        for w in (self.centre, self.width):
            w.setEnabled(pinch)
        self.ramp.setEnabled(self.mode.currentText() != 'hillshade')
        self.scaling.setEnabled(self.mode.currentText() != 'hillshade' and self.ramp.currentText() != 'traditional')
        self.layer.set_style(self.current_style())
        self.styleChanged.emit(self.layer.style)

    def show_resolution(self, arcsec: float) -> bool:
        """Put the combo on the resolution being built.

        The panel is where a reader looks to see what the surface is; a build
        started from anywhere else - the command line's --surface, or a
        rebuild that names its own - has to move it, or the panel says one
        thing while the build does another. Signals stay blocked because this
        is reporting a build, not asking for one."""
        for i in range(self.resolution.count()):
            if abs(float(self.resolution.itemData(i)) - arcsec) < 1e-9:
                was = self.resolution.blockSignals(True)
                self.resolution.setCurrentIndex(i)
                self.resolution.blockSignals(was)
                return True
        return False

    def building(self, text: str):
        self.button.setEnabled(False)
        self.status.setText(text)

    def built(self, shaded: shade.Shaded, seconds: float):
        self.button.setEnabled(True)
        rows, cols = shaded.dem.shape
        land = shaded.dem[shaded.dem > 0]
        rng = f'{land.min():.0f}-{land.max():.0f} m' if land.size else 'no land'
        self.status.setText(f'{cols}×{rows} at {shaded.metres:g} m, {rng}, {seconds:.0f} s')
        if self.unreached is not None:
            self.reading.setText(self.unreached.summary())

    def previewed(self, seconds: float):
        """A patch went in without a rebuild. Says so, and says it is not the
        exact answer - which the dashed edge on the canvas also says."""
        self.status.setText(f'preview, {seconds * 1000:.0f} ms - exact on idle')

    def failed(self, text: str):
        self.button.setEnabled(True)
        self.status.setText('the build failed: ' + text.splitlines()[0])
