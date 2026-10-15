"""A crash - J6: an exception nothing caught, or a fault in C, written down
and offered as a GitHub issue the mapper reads before it is sent.

PySide6 hands an exception raised in a slot, in an override of Qt's - a paint
event - or in a ``QRunnable`` on the thread pool to ``sys.excepthook``, and
one on a Python thread to ``threading.excepthook``; either way the editor
goes on running, measured on 6.11. Each is written to a report under
``crashes/`` beside the usage log - the versions, the trace and the last of
the log - and a dialog, on the main thread whichever thread raised it, says
so, writes the autosave there and then, and offers the issue. The same fault
again in the same run, as a paint event's is at every paint, is counted, not
written or shown again.

A fault in C - a segfault in GDAL or Qt - ends the process before any of
that can run. ``faulthandler`` writes the Python stacks to a file of the
run's own, under a header naming the run's usage log; the run ending as it
should takes the file away, so one that has more than its header at the next
start is a run that died, and is offered then. A file another Danu still
has open is not: on Windows it cannot be renamed, and on Linux its owner is
alive and its file has only the header.

Nothing leaves the machine but by the mapper's own hand: the issue opens in
the browser filled in, to be read, cut and submitted there. The home
directory in a path is written ``~``.
"""

from __future__ import annotations

import faulthandler
import html
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from . import about

ISSUES = f'{about.HOME}/issues/new'
KEEP = 20                       # reports kept, and fault files
LOG_LINES = 40                  # of the usage log, in a report
URL_MAX = 7500                  # GitHub's new-issue link, encoded; past ~8k it is refused
HEAD = '# '                     # a fault file's header lines


def _private(text: str) -> str:
    """The home directory as ``~``, as written and as the usage log's JSON
    escapes it."""
    home = str(Path.home())
    if len(home) < 2:
        return text
    return text.replace(home.replace('\\', '\\\\'), '~').replace(home, '~')


def log_tail(path: Path | None, n: int = LOG_LINES) -> str:
    if path is None:
        return ''
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return ''.join(f.readlines()[-n:])
    except OSError:
        return ''


class Report:
    """What a report says, as a file and as an issue."""

    def __init__(self, title: str, trace: str, log: str, versions: dict[str, str] | None = None,
                 fault: bool = False):
        self.title = title
        self.fault = fault                     # a fault's dump, what matters first; a traceback's last
        self.versions = about.versions() if versions is None else versions
        self.trace = trace
        self.log = log
        self.when = time.strftime('%Y-%m-%d %H:%M:%S')
        self.path: Path | None = None          # the file, once written

    def text(self) -> str:
        return _private('\n'.join([
            f'Danu crash report, {self.when}', '',
            '## Versions', about.text(self.versions), '',
            '## Trace', self.trace.rstrip(), '',
            '## The last of the usage log', self.log.rstrip() or '(none)', '']))

    def issue_body(self, log: str | None = None, trace: str | None = None) -> str:
        log = self.log if log is None else log
        trace = self.trace if trace is None else trace
        fence = '```'
        return _private('\n'.join([
            '**What were you doing when it happened?**', '', '', '',
            '<!-- The rest is what Danu wrote down. Read it, and take out anything '
            'you would rather not share, before submitting. -->', '',
            '### Versions', fence, about.text(self.versions), fence, '',
            '### Trace', fence, trace.rstrip(), fence, '',
            '### The last of the usage log', fence, log.rstrip() or '(none)', fence, '']))

    def issue_url(self) -> str:
        """The new-issue link, cut to fit: the log's oldest lines first, then
        the trace - a traceback's oldest, since its last lines are where it
        went wrong, and a fault's last, the C stack under the Python one."""
        def url(body):
            return f'{ISSUES}?title={quote(_private(self.title))}&body={quote(body)}'
        log, trace = self.log.splitlines(keepends=True), self.trace.splitlines(keepends=True)
        while True:
            u = url(self.issue_body(''.join(log), ''.join(trace)))
            if len(u) <= URL_MAX:
                return u
            if log:
                log = log[1:]
            elif len(trace) > 1 and self.fault:
                trace = [*trace[:-2], '...\n'] if trace[-1] == '...\n' else [*trace[:-1], '...\n']
            elif len(trace) > 1:
                trace = ['...\n', *trace[2:]] if trace[0] == '...\n' else ['...\n', *trace[1:]]
            else:
                return u[:URL_MAX]


def _title(exc_type, exc) -> str:
    first = (str(exc).splitlines() or [''])[0]
    t = f'Crash: {exc_type.__name__}' + (f': {first}' if first else '')
    return t if len(t) <= 100 else t[:97] + '...'


def _signature(exc_type, tb) -> tuple:
    """The same fault, as a repeated paint raises it: its type and the line
    it was raised on."""
    frames = traceback.extract_tb(tb)
    last = frames[-1] if frames else None
    return (exc_type.__name__, last.filename if last else '', last.lineno if last else 0)


class Reporter(QObject):
    """The hooks, the reports and the dialog. ``window`` is set once there
    is one, for the usage log and the autosave."""

    caught = Signal(object)            # a Report written; queued to the main thread

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.window = None
        self.reports: list[Path] = []
        self.repeats = 0               # the same fault again, not shown
        self._seen: set = set()
        self._lock = threading.Lock()
        self._versions: dict[str, str] | None = None
        self._fault = None             # this run's fault file, open
        self._previous = None          # the hooks found, put back by uninstall
        self.dialog: CrashDialog | None = None
        self.caught.connect(self._show, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------- hooks
    def install(self, fault: bool = True) -> None:
        """The hooks, and with ``fault`` the fault file - which the tests,
        under pytest's own fault handler, leave to a process of their own."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self._prune()
        self._previous = (sys.excepthook, threading.excepthook)
        sys.excepthook = self._except
        threading.excepthook = lambda a: self._except(a.exc_type, a.exc_value, a.exc_traceback)
        if not fault:
            return
        path = self.directory / time.strftime(f'%Y%m%d-%H%M%S-{os.getpid()}.fault')
        try:
            self._fault = open(path, 'w', encoding='utf-8')
            self._fault.write(f'{HEAD}danu {about.__version__}, {about.basics()["platform"]}\n')
            self._fault.flush()
            faulthandler.enable(self._fault, all_threads=True)
        except OSError:
            self._fault = None         # no record of a fault; the exceptions still are

    def attach(self, window) -> None:
        """The window: its usage log named in the fault file, for the next start."""
        self.window = window
        usage = getattr(window, 'usage', None)
        if self._fault is not None and usage is not None:
            self._fault.write(f'{HEAD}log {usage.path}\n')
            self._fault.flush()

    def uninstall(self) -> None:
        """The run ending as it should: the hooks put back, the fault file gone."""
        if self._previous is not None:
            sys.excepthook, threading.excepthook = self._previous
            self._previous = None
        if self._fault is not None:
            faulthandler.disable()
            path = Path(self._fault.name)
            self._fault.close()
            self._fault = None
            path.unlink(missing_ok=True)

    def _except(self, exc_type, exc, tb) -> None:
        """On whichever thread raised it: the terminal told as before, the
        report written, the dialog asked for."""
        sys.__excepthook__(exc_type, exc, tb)
        if exc_type is KeyboardInterrupt or exc is None:
            return
        try:
            sig = _signature(exc_type, tb)
            with self._lock:
                if sig in self._seen:
                    self.repeats += 1
                    return
                self._seen.add(sig)
                if self._versions is None:
                    self._versions = about.versions()
            where = threading.current_thread().name
            trace = f'on thread {where}\n' + ''.join(traceback.format_exception(exc_type, exc, tb))
            report = Report(_title(exc_type, exc), trace, log_tail(self._log_path()), self._versions)
            self._write(report)
            self.caught.emit(report)
        except Exception:                                 # noqa: BLE001 - a report must not raise in a hook
            traceback.print_exc()

    def _log_path(self) -> Path | None:
        usage = getattr(self.window, 'usage', None)
        return getattr(usage, 'path', None)

    def _write(self, report: Report) -> None:
        path = self.directory / time.strftime(f'%Y%m%d-%H%M%S-{os.getpid()}-{len(self.reports) + 1}.txt')
        try:
            path.write_text(report.text(), encoding='utf-8')
        except OSError:
            return
        report.path = path
        self.reports.append(path)

    def _prune(self) -> None:
        for pattern in ('*.txt', '*.fault'):
            files = sorted(self.directory.glob(pattern))
            for p in files[:max(0, len(files) - (KEEP - 1))]:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass                                 # another Danu's, open

    # ------------------------------------------------------ the next start
    def earlier(self) -> list[Report]:
        """Each run that died in C since, as a report, written and its fault
        file taken away - offered once."""
        out = []
        for path in sorted(self.directory.glob('*.fault')):
            if self._fault is not None and Path(self._fault.name) == path:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            lines = text.splitlines(keepends=True)
            body = [ln for ln in lines if not ln.startswith(HEAD)]
            if not ''.join(body).strip():
                continue                                 # running, or ended without a fault
            claimed = path.with_suffix('.offered')
            try:
                path.replace(claimed)                    # refused while its process has it open
            except OSError:
                continue
            log = next((Path(ln[len(HEAD) + 4:].strip()) for ln in lines if ln.startswith(f'{HEAD}log ')), None)
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(claimed.stat().st_mtime))
            first = next((ln.strip() for ln in body if ln.strip()), 'a fault')
            report = Report(f'Crash: {first}', f'the run that ended {when}\n' + ''.join(body),
                            log_tail(log), self._versions_now(), fault=True)
            self._write(report)
            claimed.unlink(missing_ok=True)
            out.append(report)
        return out

    def _versions_now(self) -> dict[str, str]:
        if self._versions is None:
            self._versions = about.versions()
        return self._versions

    def offer_earlier(self) -> None:
        reports = self.earlier()
        if reports:
            self._show(reports[-1], earlier=len(reports))

    # ------------------------------------------------------------ the dialog
    def _show(self, report: Report, earlier: int = 0) -> None:
        if self.dialog is not None and self.dialog.isVisible():
            return                                       # one at a time; this one is in its file
        saved = self._autosave() if not earlier else None
        self.dialog = CrashDialog(report, saved=saved, earlier=earlier, parent=self.window)
        self.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialog.destroyed.connect(lambda *_: setattr(self, 'dialog', None))
        self.dialog.open()

    def _autosave(self) -> bool | None:
        """The edits written to the autosave now: True if they were, None if
        there were none, False if it could not."""
        w = self.window
        if w is None or getattr(w, 'autosave', None) is None or not w.editor.dirty():
            return None
        try:
            w.autosave.flush()
        except Exception:                                # noqa: BLE001 - in a broken state, say so
            return False
        return True


class CrashDialog(QDialog):
    """What happened, where the report is, and the issue it fills in."""

    def __init__(self, report: Report, saved: bool | None = None, earlier: int = 0, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle('Danu - something went wrong')
        if earlier:
            head = ('Danu stopped unexpectedly last time.' if earlier == 1 else
                    f'Danu stopped unexpectedly {earlier} times since it last ran. This is the latest.')
            edits = ('Any edits it had not saved are in the autosave, and are offered back '
                     'when those squares are next opened.')
        else:
            head = 'Something went wrong that Danu did not expect. It is still running.'
            edits = {True: 'Your edits are in the autosave: if Danu closes, they are offered '
                           'back when the squares are next opened. Save them now if you can.',
                     False: 'The autosave could not be written - save your edits now if you can.',
                     None: 'No edits were waiting to be saved.'}[saved]
        path = report.path
        where = f'A report was written to <code>{html.escape(_private(str(path)))}</code>.' if path else ''
        self.label = QLabel(f'<p><b>{head}</b></p><p>{edits}</p><p>{where}</p>'
                            '<p>Report it on GitHub, and it can be fixed: the issue opens in your browser '
                            'filled in from the report below. Nothing is sent until you submit it there.</p>')
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        body = QPlainTextEdit(report.text())
        body.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.issue = buttons.addButton('Report on GitHub…', QDialogButtonBox.ButtonRole.ActionRole)
        self.issue.setDefault(True)
        self.copy = buttons.addButton('Copy report', QDialogButtonBox.ButtonRole.ActionRole)
        self.issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(report.issue_url())))
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(report.text()))
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)
        lay.addWidget(body)
        lay.addWidget(buttons)
        self.resize(640, 440)


PROVOKE = ('python', 'thread', 'fault')


def provoke(how: str) -> None:
    """A crash asked for - ``danu --crash`` - to see a build write and offer
    its report: an exception on the main thread or on the pool, or a fault."""
    if how == 'fault':
        faulthandler._sigsegv()
    elif how == 'thread':
        from PySide6.QtCore import QThreadPool

        def fail():
            raise RuntimeError('a crash on the thread pool, asked for by --crash')
        QThreadPool.globalInstance().start(fail)
    else:
        raise RuntimeError('a crash asked for by --crash')
