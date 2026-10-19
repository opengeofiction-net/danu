"""File › Import… (H6g): a zone's squares mirrored from the server into the
import root, on workers, with the one question - overwrite a square changed
here? - asked on the UI thread. ``danu.core.mirror`` does the work.

The open working set is not pulled from under the mapper: with unsaved
edits, every square of it is kept as it is here and that is said; without,
its squares are updated and the set opened again from them.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import mirror
from .background import Job


class OverwriteDialog(QDialog):
    """The squares changed here that the server has otherwise: a box each,
    unticked - kept unless the mapper says."""

    def __init__(self, zone: str, names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Import {zone}')
        box = QVBoxLayout(self)
        text = QLabel(f'{len(names)} square{"s" * (len(names) != 1)} in {zone} changed here, '
                      'and different on the server. Tick those to overwrite with the server\'s:')
        text.setWordWrap(True)
        box.addWidget(text)
        inner = QWidget()
        rows = QVBoxLayout(inner)
        self.boxes = {n: QCheckBox(n) for n in names}
        for b in self.boxes.values():
            rows.addWidget(b)
        rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        box.addWidget(scroll, 1)
        every = QPushButton('Tick all')
        every.clicked.connect(lambda: [b.setChecked(True) for b in self.boxes.values()])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton(every, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def chosen(self) -> set[str]:
        return {n for n, b in self.boxes.items() if b.isChecked()}


def choose_zone(parent, zones: list[str], current: str | None) -> str | None:
    if not zones:
        return None
    at = zones.index(current) if current in zones else 0
    zone, ok = QInputDialog.getItem(parent, 'Import squares', 'Zone to import:', zones, at, False)
    return zone if ok else None


def ask_overwrite(parent, zone: str, names: list[str]) -> set[str] | None:
    """The squares to overwrite; None if the import is called off."""
    dlg = OverwriteDialog(zone, names, parent)
    return dlg.chosen() if dlg.exec() else None


class Importer(QObject):
    """One import at a time, for the window. ``choose`` and ``ask`` are the
    tests' to replace; ``runner`` where the work goes."""

    message = Signal(str)
    finished = Signal(object)            # (zone, its directory, what was done - mirror.settle's)
    failed = Signal(str)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.runner = QThreadPool.globalInstance().start
        self.choose = lambda zones, current: choose_zone(window, zones, current)
        self.ask = lambda zone, names: ask_overwrite(window, zone, names)
        self.opener = None                  # urllib's, unless a test's
        self.job = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def _kw(self) -> dict:
        return {} if self.opener is None else {'opener': self.opener}

    def start(self) -> None:
        if self.busy:
            self.message.emit('an import is already running')
            return
        base, api = self.window.settings.url('squares/mirror'), self.window.settings.url('drop/url')
        self.message.emit('asking the server for its zones…')
        self.job = Job(lambda: mirror.list_zones(base, api=api, **self._kw()), self._zones, self._failed)
        self.runner(self.job)

    def _zones(self, zones: list[str]) -> None:
        self.job = None
        current = self.window.zone_dir.name if self.window.zone_dir is not None else None
        zone = self.choose(zones, current)
        if zone is None:
            self.message.emit('' if zones else 'the server lists no zones')
            return
        self.import_zone(zone)

    def import_zone(self, zone: str) -> bool:
        """One zone imported into the import root, as File › Import does once
        it is chosen - the Zones panel's Import, and a square opened from the
        zone map (#190). A square changed here is asked about as ever."""
        if self.busy:
            self.message.emit('an import is already running')
            return False
        root, base = self.window.settings.import_root, self.window.settings.url('squares/mirror')
        api = self.window.settings.url('drop/url')
        job = None

        def report(step):
            job.report(step)
        job = Job(lambda: mirror.fetch(zone, root, base, report=report, api=api, **self._kw()), self._fetched,
                  self._failed,
                  on_progress=lambda s: self.message.emit(
                      f'importing {zone}: {s[0]} of {s[1]} squares' + (f' - {s[2]}' if s[2] else '')))
        self.job = job
        self.runner(job)
        return True

    def refresh(self, zone_dir: Path, square) -> bool:
        """One zone fetched again without a question (#190, N5b): the server's
        ``square`` put in place whatever is here - a refused upload's copy is
        kept beside it first - and the rest as any import has them, a square
        changed here kept as it is."""
        if self.busy:
            self.message.emit('an import is already running')
            return False
        zone_dir = Path(zone_dir)
        base, api = self.window.settings.url('squares/mirror'), self.window.settings.url('drop/url')
        self.job = Job(lambda: mirror.fetch(zone_dir.name, zone_dir.parent, base, api=api, **self._kw()),
                       lambda f: self._fetched(f, square), self._failed)
        self.runner(self.job)
        return True

    def _fetched(self, f: mirror.Fetched, square=None) -> None:
        self.job = None
        keep = self._held(f.zone_dir)
        changed = sorted(n for n in f.changed if n not in keep)
        overwrite: set[str] = set()
        if square is not None:
            overwrite = {n for n in changed if mirror._cell(n) == square}
            changed = []
        if changed:
            answer = self.ask(f.zone, changed)
            if answer is None:
                f.discard()
                self.message.emit(f'import of {f.zone} called off - nothing changed')
                return
            overwrite = answer
        done = mirror.settle(f, overwrite, keep)
        self.message.emit(summary(f.zone, done))
        self.finished.emit((f.zone, f.zone_dir, done))

    def _held(self, zone_dir: Path) -> set[str]:
        """The open set's squares in this zone, when it has unsaved edits:
        kept, whatever the server has."""
        w = self.window
        if w.working_set is None or w.zone_dir is None or Path(w.zone_dir) != Path(zone_dir) \
                or not w.editor.dirty():
            return set()
        return {sq.path.name for sq in w.working_set.squares.values() if sq.path is not None}

    def _failed(self, why: str) -> None:
        self.job = None
        first = why.splitlines()[0]
        self.message.emit(f'import failed: {first}')
        self.failed.emit(first)


def summary(zone: str, done: dict[str, list[str]]) -> str:
    parts = []
    for kind, word in (('new', 'new'), ('updated', 'updated'), ('overwritten', 'overwritten'),
                       ('current', 'up to date'), ('renamed', 'renamed'), ('kept', 'kept as here'),
                       ('held', 'held back'), ('gone', 'no longer on the server')):
        if done.get(kind):
            parts.append(f'{len(done[kind])} {word}')
    line = f'imported {zone}: ' + (', '.join(parts) if parts else 'nothing listed')
    if done.get('held'):
        line += ' - the open squares held back, having unsaved edits'
    return line

