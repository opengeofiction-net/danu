"""Autosave and recovery in the window - H4.

Each dirty square's change is written to the store five seconds after the
edits stop, and at least once a minute while they do not, so a Danu killed
mid-edit loses a minute at the most. What is written is the change since the
square's last save (``danu.core.change``), the size of the edit; nothing is
written over the mapper's files. A save takes the square's autosave away, and
so does a close that throws the edits away.

Opening a working set offers back, square by square, what an earlier run
autosaved for it and never saved: each put onto the square as read, as one
step an undo takes back, and the square dirty until it is saved. A change
against a file that has changed since is refused and said, and set aside
under ``set-aside/`` as an ``.osc`` JOSM can open, as is one not chosen.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..core.autosave import Entry, Store
from ..core.change import ApplyChange, change_of

IDLE_MS = 5_000                # written once the edits have stopped this long
EVERY_MS = 60_000              # and at least this often while they have not


class AutoSaver(QObject):
    """Reads the window's working set, zone and history each time, since a
    new set brings a new history."""

    failed = Signal(str)

    def __init__(self, window, store: Store, parent=None):
        super().__init__(parent)
        self.window, self.store = window, store
        self.written = 0                   # squares written by the last flush, for the tests
        # what this run wrote, (zone, name): the only autosaves it takes away
        # by itself. One an earlier run left is the mapper's until it has
        # been offered back - a flush on opening the set would otherwise see
        # the square clean and delete the very edits it was kept for
        self._mine: set = set()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_MS)
        self._idle.timeout.connect(self.flush)
        self._every = QTimer(self)
        self._every.setSingleShot(True)
        self._every.setInterval(EVERY_MS)
        self._every.timeout.connect(self.flush)

    def edited(self) -> None:
        # a set opened is an edited() with nothing dirty; an undo back to
        # clean still wants the flush that takes its autosave away
        if self.window.working_set is None or not (self.window.editor.dirty() or self._mine):
            return
        self._idle.start()
        if not self._every.isActive():
            self._every.start()

    @property
    def pending(self) -> bool:
        return self._idle.isActive() or self._every.isActive()

    def flush(self) -> None:
        """Every dirty square's change written now, and a clean one's
        autosave taken away."""
        self._idle.stop()
        self._every.stop()
        self.written = 0
        ws, zone = self.window.working_set, self.window.zone_dir
        if ws is None or zone is None:
            return
        history = self.window.editor.history
        try:
            for sq in ws.squares.values():
                change = change_of(sq, history.journal(sq), history.versions(sq)) if history.dirty(sq) else None
                if change is None or change.empty:
                    self._forget(zone, sq.name)
                    continue
                self.store.write(zone, sq, change)
                self._mine.add((zone, sq.name))
                self.written += 1
        except OSError as e:
            self.failed.emit(f'autosave failed: {e}')

    def saved(self, square) -> None:
        """A square written to its file: its autosave goes, unless an edit
        made during the write keeps it dirty, which the next flush writes."""
        if self.window.zone_dir is not None and not self.window.editor.history.dirty(square):
            self._forget(self.window.zone_dir, square.name)

    def _forget(self, zone, name) -> None:
        if (zone, name) in self._mine:
            self.store.remove(zone, name)
            self._mine.discard((zone, name))

    def discard(self) -> None:
        """The edits thrown away on purpose: their autosaves with them."""
        self._idle.stop()
        self._every.stop()
        ws, zone = self.window.working_set, self.window.zone_dir
        if ws is not None and zone is not None:
            for name in ws.squares:
                self._forget(zone, name)


def offer(entries: list[Entry], parent=None) -> list[Entry] | None:
    """The autosaves to put back, chosen in a dialog; None if it was closed
    or all were set aside, which the caller takes as none chosen - so every
    one is set aside, none left to be written over. The tests answer it by
    replacing this function."""
    dlg = RecoveryDialog(entries, parent)
    if not dlg.exec():
        return None
    return dlg.chosen()


class RecoveryDialog(QDialog):
    def __init__(self, entries: list[Entry], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Danu - recover autosaved edits')
        self.entries = entries
        body = QVBoxLayout(self)
        body.addWidget(QLabel('These squares have edits an earlier run autosaved and never saved. '
                              'Those chosen are put back, as one step an undo takes back; the rest '
                              'are set aside, where JOSM can open them.'))
        rows = QWidget()
        col = QVBoxLayout(rows)
        self.boxes: list[QCheckBox] = []
        for e in entries:
            why = e.refused()
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(e.written))
            c = e.data.get('counts', {})
            what = ', '.join(f'{n} {w}' for w, n in (('created', c.get('create', 0)),
                                                     ('modified', c.get('modify', 0)),
                                                     ('deleted', c.get('delete', 0))) if n)
            box = QCheckBox(f'{e.square} - {what}, autosaved {when}'
                            + (f' - cannot be put back: {why}' if why else ''))
            box.setChecked(why is None)
            box.setEnabled(why is None)
            col.addWidget(box)
            self.boxes.append(box)
        scroll = QScrollArea()
        scroll.setWidget(rows)
        scroll.setWidgetResizable(True)
        body.addWidget(scroll)
        buttons = QDialogButtonBox()
        buttons.addButton('Put back the chosen', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('Set them all aside', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body.addWidget(buttons)
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def chosen(self) -> list[Entry]:
        return [e for e, b in zip(self.entries, self.boxes, strict=True) if b.isChecked() and b.isEnabled()]


def recovery_steps(entries: list[Entry], ws) -> list:
    """The step a recovery is: each entry's change on its square of the set."""
    return [(ws.squares[e.square], ApplyChange(e.change())) for e in entries if e.square in ws.squares]
