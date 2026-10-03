"""The water import, on a worker - G4c.

Fetching and parsing is 1.3 seconds on the gobras 3x3: 0.72 to fetch 13.89 MB,
0.52 to parse 158,633 nodes into 4,673 features, 0.04 to decide which square
each belongs to. Twenty-six times the frame budget, so it does not run where
the frames are; a fortieth of what the batch grading's timeout was written
for, so it does not want a progress dialogue either. A worker and a line in
the status bar.

Newest wins, as the surface builder's queue does and for the same reason: a
mapper who presses import twice should get one import, not two. The second
request replaces whatever was waiting; the one already out cannot be stopped -
``urlopen`` is a blocking read with no cancellation hook - so it is allowed to
finish and its answer is dropped, which costs a few seconds of somebody else's
bandwidth and no correctness.
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core.square import Square
from ..water import overpass


class _Signals(QObject):
    finished = Signal(object, int)      # {SquareName: Water}, the serial it was for
    failed = Signal(str, int)


class _Job(QRunnable):
    def __init__(self, fetch, bounds, working_set, serial: int, signals: _Signals):
        super().__init__()
        self.fetch, self.bounds, self.working_set = fetch, bounds, working_set
        self.serial, self.signals = serial, signals

    def run(self):
        try:
            placed = overpass.place(overpass.parse(self.fetch(self.bounds)),
                                    self.working_set)
        except Exception as exc:      # noqa: BLE001 - reported as text, on the UI thread
            self._say(f'{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}')
            return
        try:
            self.signals.finished.emit(placed, self.serial)
        except RuntimeError:
            pass                      # the window went; see _say

    def _say(self, text: str):
        try:
            self.signals.failed.emit(text, self.serial)
        except RuntimeError:
            pass                      # a job outlives the window when it closes


class WaterImporter(QObject):
    """One import at a time, newest wins."""

    started = Signal(object)           # the set the fetch now out is for
    finished = Signal(object, object)  # {SquareName: Water}, the set it was asked for
    failed = Signal(str)

    def __init__(self, parent=None, fetch=None, runner=None):
        super().__init__(parent)
        self._fetch = fetch or overpass.fetch
        self._runner = runner or QThreadPool.globalInstance().start
        self._serial = 0
        self._running = False
        self._wanted = None
        self._out = None               # the set the job now running was asked for
        self._signals = None
        self._job = None

    @property
    def busy(self) -> bool:
        return self._running

    def request(self, working_set) -> int:
        """Ask for the working set's water, and get the serial given.

        Always accepted. A request made while one is out replaces whatever
        was waiting rather than queueing behind it: two imports of the same
        bounds answer the same, and the newest is the one whose bounds are
        current.
        """
        self._serial += 1
        self._wanted = working_set
        if not self._running:
            self._start()
        return self._serial

    def _start(self):
        working_set, self._wanted = self._wanted, None
        self._out = working_set
        self._running = True
        sig = _Signals()
        sig.finished.connect(self._done)
        sig.failed.connect(self._fail)
        job = _Job(self._fetch, working_set.bounds, working_set, self._serial, sig)
        job.setAutoDelete(False)       # Python owns it; see the note in loader.py
        self._signals, self._job = sig, job
        self.started.emit(working_set)
        self._runner(job)

    def _done(self, placed, serial: int):
        self._running = False
        # the answer to a request that has been superseded is dropped rather
        # than shown: its bounds are not the ones the mapper is looking at
        if serial == self._serial:
            self.finished.emit(placed, self._out)
        self._next()

    def _fail(self, text: str, serial: int):
        self._running = False
        if serial == self._serial:
            self.failed.emit(text)
        self._next()

    def _next(self):
        if self._wanted is not None and not self._running:
            self._start()


def commands(placed: dict, working_set) -> list[tuple[Square, object]]:
    """One import as the steps it takes: a command per square, to go on the
    history together.

    A square the set has no file for is given its features all the same - #87
    settled that an import may bring one into being, and ``save_square``
    frames and writes it when the mapper saves. ``WorkingSet.open`` puts an
    empty ``Square`` in for every name of the grid, so that square is here to
    be written into; the skip below is for a name the grid does not hold at
    all, which ``place`` cannot produce and a caller passing its own dict can.
    """
    from ..core import edits
    steps = []
    for name in sorted(placed, key=str):
        square = working_set.squares.get(name)
        if square is None:
            continue
        water = placed[name]
        steps.append((square, edits.ImportWater(
            new_nodes=dict(water.nodes), new_ways=dict(water.ways),
            new_relations=dict(water.relations),
            name=f'import water into {name}')))
    return steps
