"""What waits on the mapper, square by square: ``*`` edits not saved, ``^``
saved but not uploaded - the file is not the version the server has, or
this folder never had it from the server (``dropclient.unsent``).

The marks follow each square's grid name, on the open set's frames and on
the zones map alike; the window's title has ``*`` for the set and ``^`` for
the centre. Where a degree is too small for a name, the mark alone is drawn
at its middle. The squares here are every zone's under the import folder,
and the open set's folder - one an import made, with a manifest: read on a worker when the window opens, when a save lands, and
after an import, an upload or a delete - not as the mapper draws, when only
``*`` changes.

``X`` is a square outside its folder's zone - one an import made of a
neighbour beyond the zone's edge, or one drawn there. It can't be uploaded
from here, so it is not ``^``, and Upload changed squares leaves it out.
The zone's extent is the one ``mirror`` keeps beside it; without one, no
square is known to be outside.

``runner`` is the tests' to replace.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from ..core import dropclient, mirror
from ..core.square import SquareName, list_squares
from .background import Job


def scan(dirs: list[Path]) -> dict[SquareName, tuple[Path, bool]]:
    """``dropclient.unsent`` over each folder, less its squares outside its
    zone; one that can't be read, or holds two files for a square, has
    nothing to say."""
    return scan_all(dirs)[0]


def scan_all(dirs: list[Path]) -> tuple[dict[SquareName, tuple[Path, bool]], dict[SquareName, Path]]:
    """``scan``'s, and the squares each folder has outside its zone, with
    their files."""
    out: dict[SquareName, tuple[Path, bool]] = {}
    outside: dict[SquareName, Path] = {}
    for d in dirs:
        try:
            found = dropclient.unsent(d)
            cells = mirror.extent(d)
            here = ({} if cells is None else
                    {c: p for c, p in list_squares(d, compressed_only=True).items() if c not in cells})
        except (OSError, FileExistsError):
            continue
        outside.update(here)
        out.update((c, v) for c, v in found.items() if c not in here)
    return out, outside


def marks(dirty: set[SquareName], unsent, outside=()) -> dict[SquareName, str]:
    """Each square's marks: ``*``, and ``^`` - or ``X``, outside the zone."""
    return {c: ('*' if c in dirty else '') + ('X' if c in outside else '^' if c in unsent else '')
            for c in set(dirty) | set(unsent) | set(outside)}


class Pending(QObject):
    changed = Signal()

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.runner = QThreadPool.globalInstance().start
        self.unsent: dict[SquareName, tuple[Path, bool]] = {}
        self.outside: dict[SquareName, Path] = {}
        self.job = None
        self._again = False
        self._jobs: list[Job] = []          # every one run, for detach

    def dirs(self) -> list[Path]:
        """Every folder under the import folder, and the set's: ``unsent``
        is the filter, saying nothing of one without a manifest."""
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
            self.unsent, self.outside = found
            try:
                self.changed.emit()
            except RuntimeError:
                return                      # the window went while it read
            if self._again:
                self._again = False
                self.refresh()

        def failed(_why):
            self.job = None
            if self._again:
                self._again = False
                self.refresh()
        for old in list(self._jobs):        # those answered, let go of here: not in their own signal
            self._let_go(old)
        job = self.job = Job(lambda: scan_all(dirs), done, failed)
        self._jobs.append(job)
        self.runner(job)

    def _let_go(self, job: Job) -> None:
        """A job answered, or the window closing: let go of (``Job.release``)."""
        job.release()
        if job in self._jobs:
            self._jobs.remove(job)
        if self.job is job:
            self.job = None

    def detach(self) -> None:
        for job in list(self._jobs):
            self._let_go(job)
