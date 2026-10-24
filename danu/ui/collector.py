"""Python's garbage collector, run on the main thread only.

Left to itself the collector runs on whichever thread allocated the object
that crossed its threshold - a check or a solve on a pool worker as often as
not - and frees whatever cycles it finds there, Qt's objects among them. A
Qt object freed on a worker while the main thread paints with it is a
segfault in C, past anything Python can catch: 2026-10-24, the crossings
check garbage-collecting on a worker while the zones map painted, a 0 m
contour just deleted.

So automatic collection is switched off and this asks for it on the main
thread, between events. Python 3.14's collector, measured:

- ``gc.collect(0)`` frees the young generation's cycles, and kept to its
  threshold of 2,000 that is under a millisecond. Each tick past the
  threshold does that.
- ``gc.collect(1)``, an increment of the old generation, freed none of 3,000
  dead old cycles in 2,000 calls on a heap of 3 million objects - the
  automatic collector's own increments do not stand in for it here.
- ``gc.collect(2)`` frees them, at about 300 ms on that heap. So a full
  collection follows ``FULL_AFTER`` young ones, held back until the mapper
  has left the keyboard and mouse alone for ``IDLE_S`` seconds - a pause
  nobody is drawing through.

Reference counting frees everything else as it always has, on any thread;
only cycles wait.
"""

from __future__ import annotations

import gc
import time

from PySide6.QtCore import QEvent, QObject, QTimer

INTERVAL_MS = 500
FULL_AFTER = 100        # young collections before a full one is due
IDLE_S = 15.0           # seconds without input before a due full one runs

_INPUT = {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseMove,
          QEvent.Type.Wheel, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
          QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.NativeGesture}


class MainThreadCollector(QObject):
    """Constructed on the main thread with the application; ``stop()`` gives
    the collector back. ``clock`` is the tests'."""

    def __init__(self, app=None, interval_ms: int = INTERVAL_MS, clock=time.monotonic):
        super().__init__(app)
        self.clock = clock
        self._was = gc.isenabled()
        self.threshold = gc.get_threshold()[0] or 700
        self.young = 0                            # young collections since the last full one
        self.last_input = clock()
        gc.disable()
        if app is not None:
            app.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in _INPUT:
            self.last_input = self.clock()
        return False

    def tick(self) -> int:
        """What this tick collected: the young generation past its
        threshold, and a full collection when one is due and the mapper idle.
        The number of objects freed, or 0."""
        freed = 0
        if gc.get_count()[0] >= self.threshold:
            freed += gc.collect(0)
            self.young += 1
        if self.young >= FULL_AFTER and self.clock() - self.last_input >= IDLE_S:
            freed += gc.collect(2)
            self.young = 0
        return freed

    def stop(self) -> None:
        self.timer.stop()
        gc.collect()
        if self._was:
            gc.enable()
