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
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
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


class _Signals(QObject):
    finished = Signal(object)        # Built
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, ws: WorkingSet, params: Params, work: Path, signals: _Signals):
        super().__init__()
        self.ws, self.params, self.work, self.signals = ws, params, work, signals

    def run(self):
        try:
            # here and not at import: building needs GDAL, looking does not
            from ..surface import build
            zone_dir = next(iter(self.ws.present())).path.parent
            names = [s.name for s in self.ws.present()]
            result = build.build_dem(zone_dir, self.work, self.params, names=names)
            if result.dem is None:
                self.signals.failed.emit('nothing to build: no square in the set holds a contour')
                return
            classes = build.first_pass_classes(result.constraints, result.drawn_mask, self.params, self.work)
            shaded = shade.shade_dem(result.dem, self.params, self.work, classes=classes)
            from .overlays import envelope_rings
            rings = envelope_rings(result.envelopes) if result.envelopes else []
        except ImportError as e:
            self.signals.failed.emit(f'building a surface needs GDAL, which could not be imported: {e}')
            return
        except Exception as e:      # noqa: BLE001 - reported as text, on the UI thread
            self.signals.failed.emit(f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}')
            return
        self.signals.finished.emit(Built(shaded, rings))


class SurfaceBuilder(QObject):
    """One build at a time, on the pool; the result arrives as a signal."""
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self._signals = None
        self.work = Path(tempfile.mkdtemp(prefix='danu-surface-'))

    def build(self, ws: WorkingSet, params: Params) -> bool:
        if self.busy:
            return False
        self.busy = True
        sig = _Signals()
        sig.finished.connect(self._done)
        sig.failed.connect(self._fail)
        self._signals = sig
        QThreadPool.globalInstance().start(_Job(ws, params, self.work, sig))
        return True

    def _done(self, shaded):
        self.busy = False
        self.finished.emit(shaded)

    def _fail(self, text):
        self.busy = False
        self.failed.emit(text)

    def cleanup(self):
        shutil.rmtree(self.work, ignore_errors=True)


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
        """compose() the kept arrays into the pixmap; cheap, on the UI thread."""
        ramp: Ramp | None = None if self.style.mode == 'hillshade' else RAMPS[self.style.ramp]()
        rgba = shade.compose(self.shaded, ramp, self.style.scaling, self.style.mode, self.style.shade_strength)
        rows, cols = rgba.shape[:2]
        # QImage over the array, then a copy so the array may go
        self._array = np.ascontiguousarray(rgba)
        img = QImage(self._array.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(img.copy())

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap is None:
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(self._rect, self._pixmap, QRectF(self._pixmap.rect()))


# ------------------------------------------------------------------- panel

class SurfacePanel(QDockWidget):
    """Rebuild, resolution, mode, ramp, scaling and opacity. It edits the
    layer's Style and asks the window to rebuild; it computes nothing."""

    rebuild = Signal(float)              # arcsec

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
        self.scaling.addItems(['auto', 'manual', 'pitch'])
        self.lo = QDoubleSpinBox(); self.lo.setRange(-500, 9000); self.lo.setValue(0)
        self.hi = QDoubleSpinBox(); self.hi.setRange(-500, 9000); self.hi.setValue(1000)
        self.centre = QDoubleSpinBox(); self.centre.setRange(-500, 9000); self.centre.setValue(100)
        self.width = QDoubleSpinBox(); self.width.setRange(1, 5000); self.width.setValue(50)
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
        form.addRow('Pitch centre / width', self._pair(self.centre, self.width))
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
        manual, pitch = self.scaling.currentText() == 'manual', self.scaling.currentText() == 'pitch'
        for w in (self.lo, self.hi):
            w.setEnabled(manual)
        for w in (self.centre, self.width):
            w.setEnabled(pitch)
        self.ramp.setEnabled(self.mode.currentText() != 'hillshade')
        self.scaling.setEnabled(self.mode.currentText() != 'hillshade' and self.ramp.currentText() != 'traditional')
        self.layer.set_style(self.current_style())

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

    def failed(self, text: str):
        self.button.setEnabled(True)
        self.status.setText('the build failed: ' + text.splitlines()[0])
