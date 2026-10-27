"""What waits on the mapper, square by square: ``*`` edits not saved, ``^``
saved but not uploaded - the file is not the version the server has, or
the server never had it from here (``dropclient.unsent``).

The marks follow each square's grid name, on the open set's frames and on
the zones map alike; the window's title has ``*`` for the set and ``^`` for
the centre. Where a degree is too small for a name, the mark alone is drawn
at its middle. The squares here are every zone's under the import folder,
and the open set's folder - one an import made, with a manifest: read on a worker when the window opens, when a save lands, and
after an import, an upload or a delete - not as the mapper draws, when only
``*`` changes.

``runner`` is the tests' to replace.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from ..core import dropclient
from ..core.square import SquareName
from .background import Job


def scan(dirs: list[Path]) -> dict[SquareName, tuple[Path, bool]]:
    """``dropclient.unsent`` over each folder; one that can't be read, or
    holds two files for a square, has nothing to say."""
    out: dict[SquareName, tuple[Path, bool]] = {}
    for d in dirs:
        try:
            out.update(dropclient.unsent(d))
        except (OSError, FileExistsError):
            continue
    return out


def marks(dirty: set[SquareName], unsent) -> dict[SquareName, str]:
    """Each square's marks: ``*``, ``^``, or both."""
    return {c: ('*' if c in dirty else '') + ('^' if c in unsent else '') for c in set(dirty) | set(unsent)}


class Pending(QObject):
    changed = Signal()

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.runner = QThreadPool.globalInstance().start
        self.unsent: dict[SquareName, tuple[Path, bool]] = {}
        self.job = None
        self._again = False
        self._jobs: list[Job] = []          # every one run, for detach

    def dirs(self) -> list[Path]:
        w = self.window
        out = []
        root = w.settings.import_root
        if root.is_dir():
            out = sorted(p for p in root.iterdir() if p.is_dir())
        if w.zone_dir is not None and Path(w.zone_dir) not in out:
            out.append(Path(w.zone_dir))
        return out

    def refresh(self) -> None:
        """The folders read again, on a worker - once more after, if asked
        while a read is out."""
        if self.job is not None:
            self._again = True
            return
        dirs = self.dirs()

        def done(found):
            self.job = None
            self.unsent = found
            self.changed.emit()
            if self._again:
                self._again = False
                self.refresh()

        def failed(_why):
            self.job = None
        for old in list(self._jobs):        # those answered, let go of here: not in their own signal
            self._let_go(old)
        job = self.job = Job(lambda: scan(dirs), done, failed)
        self._jobs.append(job)
        self.runner(job)

    def _let_go(self, job: Job) -> None:
        """A job answered, or the window closing: what it ran and its slots
        dropped, as ``ZoneEditor.detach`` does - the pool keeps each job it
        ran, and its slots held the window."""
        job.fn = None
        for signal in (job.signals.done, job.signals.failed):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        if job in self._jobs:
            self._jobs.remove(job)
        if self.job is job:
            self.job = None

    def detach(self) -> None:
        for job in list(self._jobs):
            self._let_go(job)
