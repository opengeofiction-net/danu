"""File's Upload, Rename and Delete square (#190, N5b): the open square sent
to the data drop, on a worker, from the version last imported.

An upload asks first, saying where it goes. Unsaved edits are saved first -
asked, not done behind the mapper's back - as the upload is of the file.
Refused because the square changed on the server since it was imported, the
mapper's file is kept beside it as ``.mine.osm.xz``, the server's version is
imported in its place, and the set opened again with the copy drawn over it
(``reference.py``): theirs to redo their changes on, and upload again.
Mappers sharing a square sort that out between themselves.

A square the server holds that was never imported here - edited before Danu
1.3, whose Import kept a square changed here unrecorded - is not a conflict
anybody else made: the mapper is asked whether to replace the server's copy,
told when it last changed, and the server keeps the one replaced.

``confirm``, ``ask_label`` and ``runner`` are the tests' to replace.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..core import dropclient
from ..core.square import LABEL, SquareName, label_of
from .background import Job


def _confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def _ask_label(parent, current: str) -> str | None:
    text, ok = QInputDialog.getText(parent, 'Rename square', 'Its name - letters, digits, spaces and -; '
                                    'empty for none:', QLineEdit.EchoMode.Normal, current.replace('_', ' '))
    return text.strip().replace(' ', '_') if ok else None


class Sender(QObject):
    message = Signal(str)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.runner = QThreadPool.globalInstance().start
        self.confirm = lambda title, text: _confirm(window, title, text)
        self.ask_label = lambda current: _ask_label(window, current)
        self.opener = None                  # urllib's, unless a test's
        self.job = None

    # ------------------------------------------------------------ helpers
    def _kw(self) -> dict:
        return {} if self.opener is None else {'opener': self.opener}

    def _square(self) -> tuple[SquareName, Path] | None:
        """The open square and its file, or why not, said."""
        w = self.window
        if self.job is not None:
            self.message.emit('a square is already being sent')
            return None
        if w.working_set is None:
            self.message.emit('open a square first')
            return None
        if not w.settings.token:
            self.message.emit('sign in to OGF first: File › Sign in')
            return None
        centre = w.working_set.centre
        sq = w.working_set.squares[centre]
        if sq.path is None or not Path(sq.path).exists():
            self.message.emit(f'{centre} has no file yet: save it first')
            return None
        return centre, Path(sq.path)

    def _saved_then(self, go) -> None:
        """Unsaved edits saved, if the mapper says so - the file is what goes -
        and ``go()`` once the last of them has landed: saves are written on
        a worker."""
        w = self.window
        if w.editor.dirty():
            if not self.confirm('Unsaved edits', 'The open squares have unsaved edits. Save them first?'):
                return
            if not w.save_all():
                return

        tries = 0

        def when_written():
            nonlocal tries
            if w._writes and tries < 3000:
                tries += 1
                QTimer.singleShot(100, when_written)
            elif w.editor.dirty():
                self.message.emit('not sent: the open squares were not all saved')
            else:
                go()
        when_written()

    def _run(self, fn, done) -> None:
        self.job = Job(fn, lambda a: (setattr(self, 'job', None), done(a)), self._failed)
        self.runner(self.job)

    def _failed(self, why: str) -> None:
        self.job = None
        self.message.emit(f'the drop not reached: {why.splitlines()[0]}')

    def _changed(self, square: SquareName, path: Path) -> None:
        """Refused, made from a version since changed: the mapper's kept, the
        server's imported in its place."""
        kept = dropclient.keep_mine(path)
        self.message.emit(f'{square} changed on the server since you imported it - your version is kept as '
                          f'{kept.name} and shown over theirs; the server\'s is being imported')
        if not self.window.importer.refresh(path.parent, square):
            self.message.emit(f'{square}: your version is kept as {kept.name} - import the zone to fetch theirs')

    def _again(self, said: str) -> None:
        """The set opened again: a file renamed, or replaced."""
        w = self.window
        ws = w.working_set
        if ws is None or w.zone_dir is None:
            return

        def opened(*_):
            w.loader.finished.disconnect(opened)
            w.statusBar().showMessage(said)
        w.loader.finished.connect(opened)
        w.open_working_set(w.zone_dir, ws.centre, ws.size)

    def _asked_again(self) -> None:
        self.window._drop_asked = None
        self.window.show_ground()

    # ------------------------------------------------------------ actions
    def upload(self) -> None:
        got = self._square()
        if got is not None:
            self._saved_then(lambda: self._upload(*got))

    def _upload(self, square: SquareName, path: Path, over: str | None = None) -> None:
        if over is None and not self.confirm('Upload square', f'Upload {path.name} to the OpenGeofiction data '
                                             'drop? It is built into the elevation the night after.'):
            return
        w = self.window
        api, token = w.settings.url('drop/url'), w.settings.token
        self.message.emit(f'uploading {square}…')

        def done(answer):
            reply, new = answer
            if reply.ok:
                said = f'{square} uploaded as {new.name}: built into the elevation tonight'
                self.message.emit(said)
                if new != path:
                    self._again(said)
                self._asked_again()
            elif reply.status == 412 and reply.body.get('unimported'):
                self._unimported(square, path, reply.body['held'])
            elif reply.status == 412:           # changed there since it was imported
                self._changed(square, path)
            else:
                self.message.emit(f'{square} not uploaded: {reply.why}')
        self._run(lambda: dropclient.upload(api, token, path, over=over, **self._kw()), done)

    def _unimported(self, square: SquareName, path: Path, held: dict) -> None:
        """Held there, never imported here: the mapper's to say which wins."""
        when = time.strftime('%Y-%m-%d %H:%M %Z', time.localtime(float(held.get('mtime', 0))))
        if not self.confirm('Replace the server\'s square',
                            f'Your copy of {square} was not imported from the server\'s - it may have been '
                            f'edited before Danu 1.3. The server\'s, {held.get("file")}, last changed {when}.\n\n'
                            'Replace the server\'s with yours? The server keeps the one replaced, for an '
                            'administrator to put back.'):
            self.message.emit(f'{square} not uploaded: the server\'s copy left as it is')
            return
        self._upload(square, path, over=str(held['sha256']))

    def rename(self) -> None:
        got = self._square()
        if got is None:
            return
        square, path = got
        label = self.ask_label(label_of(path))
        if label is None or label == label_of(path):
            return
        if label and not LABEL.fullmatch(label):
            self.message.emit(f'{label!r}: a name is letters, digits, spaces and -, up to 64')
            return
        w = self.window
        api, token = w.settings.url('drop/url'), w.settings.token

        def done(answer):
            reply, new = answer
            if reply.ok:
                said = f'{square} renamed {new.name}'
                self.message.emit(said)
                self._again(said)
            else:
                self.message.emit(f'{square} not renamed: {reply.why}')
        self._run(lambda: dropclient.rename(api, token, path, label, **self._kw()), done)

    def delete(self) -> None:
        got = self._square()
        if got is None:
            return
        square, path = got
        if not self.confirm('Delete square from the server',
                            f'Delete {path.name} from the OpenGeofiction data drop? Its contours go from the '
                            'elevation the night after. Your copy here stays.'):
            return
        w = self.window
        api, token = w.settings.url('drop/url'), w.settings.token

        def done(reply):
            if reply.ok:
                self.message.emit(f'{square} deleted from the server; your copy here stays')
                self._asked_again()
            else:
                self.message.emit(f'{square} not deleted: {reply.why}')
        self._run(lambda: dropclient.delete(api, token, path, **self._kw()), done)

    def discard(self) -> None:
        """The refused copy of the open square, deleted, and its drawing gone."""
        w = self.window
        if w.working_set is None or w.zone_dir is None:
            return
        mine = dropclient.mine_for(w.zone_dir, w.working_set.centre)
        if mine is None:
            self.message.emit('no refused version of this square is kept')
            return
        if not self.confirm('Discard refused version', f'Delete {mine.name}, your refused version?'):
            return
        mine.unlink(missing_ok=True)
        w.reference.set_square(None)
        w.update_reference_actions()
        self.message.emit(f'{mine.name} discarded')
