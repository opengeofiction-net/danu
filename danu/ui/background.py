"""A function run off the UI thread, its answer back on it.

What the save's compression and the checks' first scan share: each was
seconds of the UI thread - 21.6 s to save the gobras 3x3, 9.3 s to open the
checks panel over it - and the desktop called the window not responding. The
answer arrives as a signal, which Qt delivers on the thread the signals
object lives on, the UI's.
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, Signal


class Signals(QObject):
    done = Signal(object)              # what the function answered
    failed = Signal(str)               # why it did not, as text


class Job(QRunnable):
    """``fn()`` on a worker. ``runner`` - a pool's ``start``, or a test's
    ``lambda job: job.run()`` - decides where; the job is Python's to keep,
    as the loader's are."""

    def __init__(self, fn, on_done, on_failed):
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = Signals()
        self.signals.done.connect(on_done)
        self.signals.failed.connect(on_failed)

    def run(self):
        try:
            answer = self.fn()
        except Exception as exc:       # noqa: BLE001 - reported as text, on the UI thread
            self._emit(self.signals.failed, f'{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}')
            return
        self._emit(self.signals.done, answer)

    @staticmethod
    def _emit(signal, value):
        try:
            signal.emit(value)
        except RuntimeError:
            pass                       # the window went while it ran
