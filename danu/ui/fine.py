"""The ground in view at 1 arcsecond, at z15 and closer - R43, I3b.

The working set is built at 3 arcseconds. Once the map comes to rest at z15 or
closer, the tiles of the view not yet solved at 1 are solved, on a worker, and
kept; ``danu.surface.fine`` is the solve and the keeping, and this is the
wiring, and ``FineLayer`` draws them over the 3 arcsecond surface.

One solve at a time, as the preview has it: at 1 arcsecond the first pass is
the cost, and two of them side by side compete for the same cores and neither
arrives sooner. The view moving on while one runs is not a reason to stop it -
numpy cannot be stopped mid-array - but the next solve is for wherever the
view is by then, not for every place it passed through.
"""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QRectF, QRunnable, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from ..surface import fine, shade
from ..surface.params import Params
from . import mercator as m
from .surface import RAMPS

# the closest zoom at which the 3 arcsecond surface is all there is; at this
# and closer the view is solved at 1. The phase's own number
MIN_ZOOM = 15


class _Signals(QObject):
    done = Signal(int, object, object, object)   # serial, Solved, pieces, error


class _Job(QRunnable):
    """``fine.solve`` off the UI thread, and the shading of what it found:
    arrays in, arrays out. ``projection`` None solves without shading."""

    def __init__(self, serial, prepared, shape, params, gt, projection, signals):
        super().__init__()
        self.serial, self.signals = serial, signals
        self.args = (prepared, shape, params)
        self.gt, self.projection = gt, projection
        # set when run() returns, however it returns - see SurfaceLayer.cleanup
        self.done = threading.Event()

    def run(self):
        solved = shaded = error = None
        try:
            solved = fine.solve(*self.args)
            if self.projection is not None:
                p, _, params = self.args
                shaded = fine.pieces(p, solved, self.gt, self.projection, params)
        except Exception as e:      # noqa: BLE001 - reported on the UI thread
            error = e
        try:
            self.signals.done.emit(self.serial, solved, shaded, error)
        except RuntimeError:
            pass                    # the window went first; see _Job._say in surface.py
        finally:
            self.done.set()


class FineDriver(QObject):
    """Solves the view at 1 arcsecond, a tile at a time, and keeps the tiles."""

    arrived = Signal(object, float)   # the tiles solved, and seconds since the view settled
    cleared = Signal()                # every tile gone: nothing kept is to be drawn
    unavailable = Signal(str)         # why there is no 1 arcsecond view, once per reason

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fine: fine.Fine | None = None
        self._gen = 0                  # bumped by every adopt and forget
        self._want: fine.Box | None = None
        self._since = 0.0              # when the view that is wanted settled
        self._job: _Job | None = None
        self._plan: fine.Prepared | None = None
        self._serial = 0
        self._solving = 0
        self._runner = None
        self._said = ''
        self._projection: str | None = None   # the build's, for shading; None shades nothing
        self._signals = _Signals()
        self._signals.done.connect(self._solved)

    # --------------------------------------------------------- the build

    def adopt(self, built, contours, params: Params) -> None:
        """Take a build as the 3 arcsecond ground the view is held on, with
        ``contours`` - the preview's layer, so a view burns what the editor
        has. Every tile kept so far goes: it was held on the last build."""
        self.forget()
        r = built.rasters
        if params.arcsec != 3:
            # built at 1 already, by the resolution choice I3d removes
            return
        if r is None or contours is None:
            self._say('no 1" view: the build kept no grids to hold it on')
            return
        rows, cols = r.dem.shape
        coarse = fine.Grid(r.geotransform, rows, cols)
        res = r.geotransform[1] / 3
        g = r.geotransform
        grid = fine.Grid((g[0] + res, res, 0.0, g[3] - res, 0.0, -res), 3 * (rows - 1) + 1, 3 * (cols - 1) + 1)
        try:
            self.fine = fine.Fine(grid, coarse, contours, r.surface, r.dem,
                                  params.with_arcsec(1), gpkg=r.gpkg)
        except Exception as e:      # noqa: BLE001 - the 1" view is a bonus, never a failed surface
            self._say(f'no 1" view: {type(e).__name__}: {e}')
            return
        self._projection = r.projection
        self._said = ''

    def forget(self) -> None:
        """Drop the tiles and the build they were held on. A solve in flight
        runs on, and its answer is dropped when it lands."""
        self._gen += 1
        self.fine = None
        self._want = None
        self._plan = None
        # 0, which no job is ever given: _serial only counts up, so the answer
        # of a solve in flight matches neither this nor any solve started
        # after it, and _solved drops it
        self._solving = 0

    def _say(self, why: str) -> None:
        if why != self._said:
            self._said = why
            self.unavailable.emit(why)

    # -------------------------------------------------------------- view

    def view(self, bounds: tuple[float, float, float, float], zoom: int) -> None:
        """The map has come to rest on ``bounds`` (west, south, east, north)
        at ``zoom``. Below MIN_ZOOM nothing is solved, and the tiles kept stay
        kept for coming back."""
        if self.fine is None or zoom < MIN_ZOOM:
            self._want = None
            return
        box = self.fine.cells(*bounds)
        if box is None:
            self._want = None
            return
        self._want = box
        self._since = time.perf_counter()
        self._next()

    def _next(self) -> None:
        if self._solving or self._want is None or self.fine is None:
            return
        p = self.fine.plan(self._want)
        if p is None:
            return
        self._plan = p
        self._serial += 1
        self._solving = self._serial
        self._job = _Job(self._serial, p, self.fine.fine.shape, self.fine.params,
                         self.fine.fine.gt, self._projection, self._signals)
        self._job.setAutoDelete(False)       # Python owns it; see loader.py
        if self._runner is None:
            self._job.run()
        else:
            self._runner(self._job)

    def _solved(self, serial, solved, shaded, error) -> None:
        if serial != self._solving:
            return                           # forgotten while it ran
        self._solving = 0
        p, self._plan = self._plan, None
        if error is not None:
            self._say(f'no 1" view: {type(error).__name__}: {error}')
            return
        keys = self.fine.take(p, solved, shaded)
        self.arrived.emit(keys, time.perf_counter() - self._since)
        self._next()                         # the view may have moved on meanwhile

    def edited(self) -> None:
        """The contours changed under the tiles. Until I4 works out which
        tiles an edit reaches, every one goes and the view is solved again -
        so what is drawn at 1 arcsecond is never ground from before the edit.
        Called once the preview has patched the 3 arcsecond surface, which is
        what the new solve's rim is held on. A solve in flight was of the old
        contours, and its answer is dropped."""
        if self.fine is None:
            return
        self.fine.clear()
        self.cleared.emit()
        self._solving = 0
        self._plan = None
        self._since = time.perf_counter()
        self._next()

    # ----------------------------------------------------------- threads

    def set_runner(self, runner) -> None:
        """Solve through ``runner`` - ``QThreadPool.start`` in the window -
        rather than on the calling thread, which is what the tests keep."""
        self._runner = runner

    def cleanup(self, wait_ms: int = 5000) -> bool:
        """Wait for a solve in flight, so a closing window does not leave one
        emitting into a deleted object. As PreviewDriver.cleanup."""
        job = self._job
        self._want = None
        if job is None:
            return True
        if not job.done.wait(wait_ms / 1000.0):
            self._signals.done.disconnect(self._solved)
            return False
        self._job = None
        self._solving = 0
        return True


class FineLayer(QGraphicsItem):
    """The 1 arcsecond tiles, drawn over the 3 arcsecond surface at z15 and
    closer - R43.

    A child of the surface's layer, so it takes the surface's opacity and
    visibility with it, and is coloured exactly as the surface is: the same
    ``shade.compose``, the same mode and ramp, and the same colour stretch -
    the range the surface's last whole recolour worked out, not one from the
    tile, which would come out a different colour from the ground around it.

    Drawn as one picture, not a tile at a time. Every tile's shading is on
    one Mercator grid, so the tiles in view are pasted into one array,
    composed and drawn once: drawn apart and smoothed, each tile's edge was
    blended with nothing - Qt does not read past the rectangle it is asked to
    draw - and every tile edge showed as a line two or three grey levels deep
    at z15. Composed again only when the tiles in view or the style change.
    Nothing is drawn in the difference mode, which the tiles cannot give yet.
    """

    def __init__(self, surface, driver: FineDriver):
        super().__init__(surface)
        self.surface, self.driver = surface, driver
        self._picture = None            # (what it was made of, QPixmap, scene rect)
        self.published = (0, ())        # (revision, pieces) - see _publish
        surface.fine = self
        self.setVisible(False)

    def set_zoom(self, zoom: int) -> None:
        self.setVisible(zoom >= MIN_ZOOM)

    def arrived(self, keys, _seconds: float = 0.0) -> None:
        self._picture = None
        self._publish()
        self.update()

    def forget(self) -> None:
        self._picture = None
        self._publish()
        self.update()

    def _publish(self) -> None:
        """Every tile's shading kept, as a tuple a thread can read whole -
        the WMS answers on its own, and the store it comes from is changed on
        this one. Replaced, never changed in place."""
        f = self.driver.fine
        self.published = (f.revision, tuple(p for _, p in f.pieces_kept())) if f is not None else (0, ())

    def surface_for(self, rect: QRectF):
        """The 1 arcsecond ground under ``rect`` - a ``shade.Shaded`` on the
        Mercator grid - if this layer is showing and every cell of ``rect``
        is solved; else None, and the reader takes the 3 arcsecond surface.
        Never part of one and part of the other: a line measured half on
        each would read two grids as one."""
        f = self.driver.fine
        if f is None or not self.isVisible() or self.surface.style.mode == 'difference':
            return None
        got = [f.piece(k) for k in self.tiles_in(rect)]
        if not got or any(p is None for p in got):
            return None
        whole, covered = fine.mosaic(got)
        left, top, right, bottom = whole.scene_rect
        rows, cols = whole.dem.shape
        c0 = int((rect.left() - left) / (right - left) * cols)
        c1 = int((rect.right() - left) / (right - left) * cols)
        r0 = int((rect.top() - top) / (bottom - top) * rows)
        r1 = int((rect.bottom() - top) / (bottom - top) * rows)
        if c0 < 0 or r0 < 0 or c1 >= cols or r1 >= rows or not covered[r0:r1 + 1, c0:c1 + 1].all():
            return None
        return whole

    def boundingRect(self) -> QRectF:
        return self.surface.boundingRect()

    def _style_key(self):
        st = self.surface.style
        return st.mode, st.ramp, st.scaling, st.shade_strength, self.surface.stretch

    def tiles_in(self, rect: QRectF) -> list:
        """The tiles a scene rectangle covers, if there is a 1 arcsecond view."""
        f = self.driver.fine
        if f is None:
            return []
        west, north = m.scene_to_lonlat(rect.left(), rect.top())
        east, south = m.scene_to_lonlat(rect.right(), rect.bottom())
        box = f.cells(west, south, east, north)
        return f.tiles(box) if box is not None else []

    def picture(self, rect: QRectF):
        """The tiles over ``rect`` as one pixmap and the scene rect it covers,
        or None when none of them is solved."""
        f = self.driver.fine
        style_key = self._style_key()
        got = [(k, f.piece(k)) for k in self.tiles_in(rect)]
        got = [(k, p) for k, p in got if p is not None]
        if not got:
            return None
        made_of = (style_key, f.revision, tuple(k for k, _ in got))
        if self._picture is not None and self._picture[0] == made_of:
            return self._picture[1:]
        whole, covered = fine.mosaic(p for _, p in got)
        # composed as one, as the surface is: a slope taken a tile at a time
        # would be one-sided at every tile's edge
        st = self.surface.style
        ramp = None if st.mode == 'hillshade' else RAMPS[st.ramp]()
        rgba = shade.compose(whole, ramp, st.scaling, st.mode, st.shade_strength,
                             stretch=self.surface.stretch)
        # a cell no tile covers is clear, whatever the ramp makes of a zero
        rgba[~covered] = 0
        rgba = np.ascontiguousarray(rgba)
        rows, cols = rgba.shape[:2]
        img = QImage(rgba.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        left, top, right, bottom = whole.scene_rect
        self._picture = (made_of, QPixmap.fromImage(img), QRectF(left, top, right - left, bottom - top))
        return self._picture[1:]

    def paint(self, painter: QPainter, option, widget=None):
        if self.driver.fine is None or self.surface.style.mode == 'difference' or \
                self.surface.stretch is None and self.surface.style.mode not in ('hillshade', 'slope'):
            return
        from .mapview import visible_rect
        got = self.picture(visible_rect(painter, option, self.boundingRect()))
        if got is None:
            return
        pix, at = got
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.surface.smooth)
        painter.drawPixmap(at, pix, QRectF(pix.rect()))
