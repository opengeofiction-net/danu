"""Reading a working set off the thread that paints.

The spec's three threads are UI, Compute and Network; a read is neither of the
last two, but it is seconds for a large square and the window must not freeze
for it. So the read runs on Qt's thread pool and comes back as a signal with
the WorkingSet in it, or with the error's text.

Python's GIL means the read still takes CPU the UI would like, and a pure
Python parse does not yield much of it. The window stays alive - events are
processed between bytecodes - but not silky. That is the honest state; a
faster reader is a later optimisation and this interface does not change for
it.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core.square import SquareName, WorkingSet


class _Signals(QObject):
    finished = Signal(object)        # WorkingSet
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, zone_dir: Path, centre: SquareName, size: int, signals: _Signals):
        super().__init__()
        self.zone_dir, self.centre, self.size, self.signals = zone_dir, centre, size, signals

    def run(self):
        try:
            ws = WorkingSet.open(self.zone_dir, self.centre, self.size)
        except Exception as e:      # noqa: BLE001 - anything, reported as text
            self.signals.failed.emit(f'{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}')
            return
        self.signals.finished.emit(ws)


class WorkingSetLoader(QObject):
    """One read at a time. A second request while one is running is refused
    with ``busy`` True, rather than queued: the caller asked for something
    else now and the first result is no longer wanted, but a running read
    cannot be stopped, so the simplest true statement is 'wait'."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._signals: _Signals | None = None
        self._job: _Job | None = None
        self.busy = False

    def load(self, zone_dir: Path, centre: SquareName, size: int = 3) -> bool:
        if self.busy:
            return False
        self.busy = True
        sig = _Signals()
        sig.finished.connect(self._done)
        sig.failed.connect(self._fail)
        job = _Job(Path(zone_dir), centre, size, sig)
        # Both kept, and the runnable's deletion taken off Qt. The pool deletes
        # a runnable's C++ side when run() returns, and nothing here held the
        # Python wrapper: once start() returned, the only reference was the
        # argument temporary, so the object could be freed while a pool thread
        # was still inside run(). Python owns it now, and the next load
        # replaces it - on this thread, where Qt objects should be freed.
        job.setAutoDelete(False)
        self._signals, self._job = sig, job
        QThreadPool.globalInstance().start(job)
        return True

    def _done(self, ws):
        self.busy = False
        self.finished.emit(ws)

    def _fail(self, text: str):
        self.busy = False
        self.failed.emit(text)
