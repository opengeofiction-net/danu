"""The ground in view at 1 arcsecond, at z15 and closer - R43, I3b.

The working set is built at 3 arcseconds. Once the map comes to rest at z15 or
closer, the tiles of the view not yet solved at 1 are solved, on a worker, and
kept; ``danu.surface.fine`` is the solve and the keeping, and this is the
wiring. Nothing draws them yet - I3c does - so what this offers is a signal
saying which tiles have arrived, and how long after the view settled.

One solve at a time, as the preview has it: at 1 arcsecond the first pass is
the cost, and two of them side by side compete for the same cores and neither
arrives sooner. The view moving on while one runs is not a reason to stop it -
numpy cannot be stopped mid-array - but the next solve is for wherever the
view is by then, not for every place it passed through.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QRunnable, Signal

from ..surface import fine
from ..surface.params import Params

# the closest zoom at which the 3 arcsecond surface is all there is; at this
# and closer the view is solved at 1. The phase's own number
MIN_ZOOM = 15


class _Signals(QObject):
    done = Signal(int, object, object)        # serial, Solved, error


class _Job(QRunnable):
    """``fine.solve`` off the UI thread: arrays in, arrays out."""

    def __init__(self, serial, prepared, shape, params, signals):
        super().__init__()
        self.serial, self.args, self.signals = serial, (prepared, shape, params), signals
        # set when run() returns, however it returns - see SurfaceLayer.cleanup
        self.done = threading.Event()

    def run(self):
        solved = error = None
        try:
            solved = fine.solve(*self.args)
        except Exception as e:      # noqa: BLE001 - reported on the UI thread
            error = e
        try:
            self.signals.done.emit(self.serial, solved, error)
        except RuntimeError:
            pass                    # the window went first; see _Job._say in surface.py
        finally:
            self.done.set()


class FineDriver(QObject):
    """Solves the view at 1 arcsecond, a tile at a time, and keeps the tiles."""

    arrived = Signal(object, float)   # the tiles solved, and seconds since the view settled
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
        self._said = ''

    def forget(self) -> None:
        """Drop the tiles and the build they were held on. A solve in flight
        runs on, and its answer is dropped when it lands."""
        self._gen += 1
        self.fine = None
        self._want = None
        self._plan = None
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
        self._job = _Job(self._serial, p, self.fine.fine.shape, self.fine.params, self._signals)
        self._job.setAutoDelete(False)       # Python owns it; see loader.py
        if self._runner is None:
            self._job.run()
        else:
            self._runner(self._job)

    def _solved(self, serial, solved, error) -> None:
        if serial != self._solving:
            return                           # forgotten while it ran
        self._solving = 0
        p, self._plan = self._plan, None
        if error is not None:
            self._say(f'no 1" view: {type(error).__name__}: {error}')
            return
        keys = self.fine.take(p, solved)
        self.arrived.emit(keys, time.perf_counter() - self._since)
        self._next()                         # the view may have moved on meanwhile

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
