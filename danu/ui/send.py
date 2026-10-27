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

Upload changed squares sends every square here the server doesn't have as
it is - the ``^`` squares (``pending.py``), of every zone imported - one
after another, asked first with them listed. One refused is left as it is
and named: changed on the server since, or held there and never imported
here, it is the open square's Upload that sorts it out.

Revert square to the server's throws the open square's changes here away -
unsaved, and saved but not uploaded - and takes the server's copy, or the
saved file where the server has none. Other squares of the set with unsaved
edits are saved first, or reverted with it: the mapper chooses.

``confirm``, ``ask_label``, ``ask_revert`` and ``runner`` are the tests' to
replace.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..core import dropclient
from ..core.square import LABEL, SquareName, label_of
from . import pending
from .background import Job


def _confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def _ask_revert(parent, square: str, others: list[str]) -> str | None:
    """'one' - the others saved first, if any - 'all', or None."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle('Revert square to the server\'s')
    box.setText(f'Revert {square} to the server\'s copy? Its changes here - unsaved, and saved but not '
                'uploaded - are lost.')
    every = None
    if others:
        them = 'it' if len(others) == 1 else 'them'
        box.setInformativeText(f'{", ".join(others)} {"has" if len(others) == 1 else "have"} unsaved edits too: '
                               f'save {them} first, or revert {them} as well.')
        one = box.addButton(f'Save {them}, revert {square}', QMessageBox.ButtonRole.AcceptRole)
        every = box.addButton(f'Revert all {len(others) + 1}', QMessageBox.ButtonRole.DestructiveRole)
    else:
        one = box.addButton('Revert', QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    return 'one' if clicked is one else 'all' if every is not None and clicked is every else None


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
        self.ask_revert = lambda square, others: _ask_revert(window, square, others)
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
        self._after_writes(go, lambda: not w.editor.dirty(), 'not sent: the open squares were not all saved')

    def _after_writes(self, go, ok, why: str) -> None:
        """``go()`` once the last save asked for has landed - saves are
        written on a worker - if ``ok()`` then; ``why`` said otherwise."""
        w = self.window
        tries = 0

        def when_written():
            nonlocal tries
            if w._writes and tries < 3000:
                tries += 1
                QTimer.singleShot(100, when_written)
            elif not ok():
                self.message.emit(why)
            else:
                go()
        when_written()

    def _run(self, fn, done) -> None:
        self.job = Job(fn, lambda a: (setattr(self, 'job', None), done(a)), self._failed)
        self.runner(self.job)

    def _failed(self, why: str) -> None:
        self.job = None
        self.message.emit(f'the drop not reached: {why.splitlines()[0]}')
        self.window.waiting.refresh()          # an upload of several stopped part way

    def _changed(self, square: SquareName, path: Path) -> None:
        """Refused, made from a version since changed: the mapper's kept, the
        server's imported in its place."""
        kept = dropclient.keep_mine(path)
        self.message.emit(f'{square} changed on the server since you imported it - your version is kept as '
                          f'{kept.name} and shown over theirs; the server\'s is being imported')
        if not self.window.importer.refresh(path.parent, {square}):
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
        self.window.waiting.refresh()

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

    def upload_changed(self) -> None:
        """Every square here not as the server has it, uploaded in turn -
        the open squares' edits saved first, if the mapper says so."""
        w = self.window
        if self.job is not None:
            self.message.emit('a square is already being sent')
            return
        if not w.settings.token:
            self.message.emit('sign in to OGF first: File › Sign in')
            return
        dirs = w.waiting.dirs()
        self._saved_then(lambda: self._run(lambda: pending.scan(dirs), self._chosen))

    def _chosen(self, found: dict) -> None:
        if not found:
            self.message.emit('nothing to upload: every square here is as the server has it')
            return
        todo = sorted((sq, path) for sq, (path, _had) in found.items())
        lines = [f'{path.name}' + ('' if found[sq][1] else ' - not had from the server') for sq, path in todo]
        n = len(todo)
        if not self.confirm('Upload changed squares',
                            f'Upload {n} square{"s" * (n != 1)} to the OpenGeofiction data drop? They are built '
                            'into the elevation the night after.\n\n' + '\n'.join(lines)):
            return
        self._next(todo, {'sent': [], 'refused': [], 'failed': [], 'moved': False}, n)

    def _next(self, todo: list, got: dict, n: int) -> None:
        """The first of ``todo`` uploaded, then the rest; what each did kept
        in ``got``, and said when the last has gone."""
        w = self.window
        if not todo:
            self._uploaded(got)
            return
        (square, path), rest = todo[0], todo[1:]
        api, token = w.settings.url('drop/url'), w.settings.token
        self.message.emit(f'uploading {square}, {n - len(todo) + 1} of {n}…')

        def done(answer):
            reply, new = answer
            if reply.ok:
                got['sent'].append(square)
                ws = w.working_set
                got['moved'] |= new != path and ws is not None and square in ws.squares
            elif reply.status == 412:
                got['refused'].append(square)
            else:
                got['failed'].append(f'{square}: {reply.why}')
            self._next(rest, got, n)
        self._run(lambda: dropclient.upload(api, token, path, **self._kw()), done)

    def _uploaded(self, got: dict) -> None:
        sent = got['sent']
        said = [f'{len(sent)} square{"s" * (len(sent) != 1)} uploaded: built into the elevation tonight']
        if got['refused']:
            said.append(f'not uploaded, changed on the server or never imported here - open it and Upload '
                        f'square: {", ".join(map(str, got["refused"]))}')
        if got['failed']:
            said.append('not uploaded - ' + '; '.join(got['failed']))
        said = '; '.join(said)
        self.message.emit(said)
        if got['moved']:
            self._again(said)                   # renamed by the server: the set's files are under new names
        self._asked_again()

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

    def revert(self) -> None:
        """The open square's changes here thrown away, and the server's copy
        taken - asked first; the set's other unsaved squares saved first or
        reverted too, as the mapper says."""
        w = self.window
        if w.working_set is None or w.zone_dir is None:
            self.message.emit('open a square first')
            return
        if w.importer.busy:
            self.message.emit('an import is already running')
            return
        centre = w.working_set.centre
        dirty = {sq.name: sq for sq in w.editor.history.dirty_squares()}
        others = sorted((n for n in dirty if n != centre), key=str)
        choice = self.ask_revert(str(centre), [str(n) for n in others])
        if choice is None:
            return
        targets = {centre, *others} if choice == 'all' else {centre}
        unfiled = [n for n in others if choice == 'one' and dirty[n].path is None]
        if unfiled:
            self.message.emit(f'not reverted: {", ".join(map(str, unfiled))} has no file yet - '
                              'save it, or revert all')
            return

        def go():
            w._reverting = targets
            if not w.importer.refresh(w.zone_dir, targets):
                w._reverting = None
        for n in others if choice == 'one' else ():
            w._save(dirty[n], dirty[n].path)
        w._saved()
        self._after_writes(go, lambda: {sq.name for sq in w.editor.history.dirty_squares()} <= targets,
                           'not reverted: the other squares were not all saved')

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
