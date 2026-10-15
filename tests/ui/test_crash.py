"""A crash (J6): an exception on any thread written to a report and shown,
a fault in C offered at the next start, and the issue each fills in."""

import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from danu.ui import crash

VERSIONS = {'danu': '0.2.0', 'python': '3', 'platform': 'here'}
ROOT = Path(__file__).parents[2]


class Fakes(QWidget):
    """What the reporter asks of a window: its usage log, its edits and the
    autosave - and a widget, the dialog's parent."""

    def __init__(self, log: Path | None = None, dirty: bool = False, flush=None):
        super().__init__()
        self.usage = type('U', (), {'path': log})()
        self.editor = type('E', (), {'dirty': lambda _self: dirty})()
        self.flushed = 0

        def default():
            self.flushed += 1
        self.autosave = type('A', (), {'flush': staticmethod(flush or default)})()


@pytest.fixture
def reporter(tmp_path, qapp):
    r = crash.Reporter(tmp_path / 'crashes')
    r._versions = dict(VERSIONS)              # not GDAL and isofill loaded for each test
    r.install(fault=False)                    # pytest's fault handler stays; see test_a_fault_*
    yield r
    r.uninstall()
    if r.dialog is not None:
        r.dialog.close()


def raise_in_slot(message='boom'):
    def fail():
        raise ValueError(message)
    QTimer.singleShot(0, fail)


def test_an_exception_in_a_slot_is_written_and_shown(reporter, qtbot, tmp_path):
    log = tmp_path / 'run.jsonl'
    log.write_text(''.join(f'{{"t": {i}, "kind": "key"}}\n' for i in range(100)))
    reporter.attach(Fakes(log))
    raise_in_slot()
    qtbot.waitUntil(lambda: reporter.dialog is not None, timeout=2000)
    assert len(reporter.reports) == 1
    text = reporter.reports[0].read_text()
    assert 'danu: 0.2.0' in text
    assert 'ValueError: boom' in text and 'on thread MainThread' in text
    assert '"t": 99' in text and '"t": 59' not in text, 'the last of the log, not all of it'
    assert reporter.dialog.report.title == 'Crash: ValueError: boom'
    assert 'still running' in reporter.dialog.label.text()
    assert 'No edits were waiting' in reporter.dialog.label.text()


def test_the_same_fault_again_is_counted_not_shown(reporter, qtbot):
    """A paint event's exception comes back at every paint."""
    for _ in range(3):
        raise_in_slot()
    qtbot.waitUntil(lambda: reporter.repeats == 2, timeout=2000)
    assert len(reporter.reports) == 1
    raise_in_slot('elsewhere')                # the same line: the same fault
    qtbot.wait(50)
    assert len(reporter.reports) == 1


def test_a_second_fault_waits_in_its_file_while_one_is_shown(reporter, qtbot):
    def first():
        raise ValueError('first')

    def second():
        raise KeyError('second')
    QTimer.singleShot(0, first)
    QTimer.singleShot(0, second)
    qtbot.waitUntil(lambda: len(reporter.reports) == 2, timeout=2000)
    qtbot.wait(50)
    shown = reporter.dialog
    assert shown is not None and shown.report.title == 'Crash: ValueError: first'
    assert [w for w in QApplication.topLevelWidgets() if isinstance(w, crash.CrashDialog) and w.isVisible()] == [shown]


def test_one_on_the_pool_is_shown_on_the_main_thread(reporter, qtbot):
    shown_on = []
    reporter.caught.connect(lambda _r: shown_on.append(threading.current_thread()))

    def fail():
        raise RuntimeError('on the pool')
    QThreadPool.globalInstance().start(fail)
    qtbot.waitUntil(lambda: reporter.dialog is not None, timeout=5000)
    assert shown_on == [threading.main_thread()]
    text = reporter.reports[0].read_text()
    assert 'RuntimeError: on the pool' in text and 'on thread MainThread' not in text


def test_one_on_a_python_thread_too(reporter, qtbot):
    def fail():
        raise KeyError('k')
    t = threading.Thread(target=fail, name='worker')
    t.start()
    t.join()
    qtbot.waitUntil(lambda: reporter.dialog is not None, timeout=2000)
    assert 'on thread worker' in reporter.reports[0].read_text()


@pytest.mark.parametrize('dirty, flush, said', [
    (True, None, 'Your edits are in the autosave'),
    (True, 'raise', 'could not be written'),
    ('raise', None, 'could not be written'),
    (False, None, 'No edits were waiting'),
])
def test_the_edits_go_to_the_autosave_there_and_then(reporter, qtbot, dirty, flush, said):
    def broken(*_a):
        raise OSError('disk full')
    w = Fakes(dirty=dirty is True, flush=broken if flush else None)
    if dirty == 'raise':                      # the window itself broken
        w.editor = type('E', (), {'dirty': broken})()
    reporter.attach(w)
    raise_in_slot()
    qtbot.waitUntil(lambda: reporter.dialog is not None, timeout=2000)
    assert said in reporter.dialog.label.text()
    assert w.flushed == (1 if dirty is True and not flush else 0)


def test_the_hooks_found_are_put_back(tmp_path, qapp):
    before = sys.excepthook, threading.excepthook
    r = crash.Reporter(tmp_path)
    r.install(fault=False)
    assert sys.excepthook != before[0]
    r.uninstall()
    assert (sys.excepthook, threading.excepthook) == before


# ------------------------------------------------------------------ the issue
def issue(url: str) -> tuple[str, str]:
    q = parse_qs(urlsplit(url).query)
    return q['title'][0], q['body'][0]


def test_the_issue_is_the_report_cut_to_fit():
    trace = 'Traceback (most recent call last):\n' + ''.join(
        f'  File "x.py", line {i}, in f\n' for i in range(400)) + 'ValueError: the end\n'
    log = ''.join(f'{{"t": {i}, "kind": "move"}}\n' for i in range(400))
    r = crash.Report('Crash: ValueError: the end', trace, log, VERSIONS)
    url = r.issue_url()
    assert url.startswith(crash.ISSUES + '?') and len(url) <= crash.URL_MAX
    title, body = issue(url)
    assert title == 'Crash: ValueError: the end'
    assert 'What were you doing' in body and 'danu: 0.2.0' in body
    assert 'ValueError: the end' in body, "a traceback's last line kept"
    assert '"t": 0,' not in body and '"t": 399' not in body, 'the log goes first'


def test_a_faults_dump_is_cut_from_its_end():
    dump = 'Fatal Python error: Segmentation fault\n\n' + ''.join(
        f'  Binary file "lib.so", at +0x{i:x}\n' for i in range(400))
    r = crash.Report('Crash: Fatal Python error: Segmentation fault', dump, '', VERSIONS, fault=True)
    url = r.issue_url()
    assert len(url) <= crash.URL_MAX
    _title, body = issue(url)
    assert 'Fatal Python error: Segmentation fault' in body and '+0x0\n' in body
    assert '+0x18f' not in body


def test_the_home_directory_is_not_in_it(monkeypatch, tmp_path):
    home = tmp_path / 'home' / 'mapper'
    monkeypatch.setattr(Path, 'home', lambda: home)
    trace = f'File "{home / "danu" / "app.py"}"\n'
    log = '{"zone": "' + str(home / 'zones' / 'z').replace('\\', '\\\\') + '"}\n'
    r = crash.Report('Crash: x', trace, log, VERSIONS)
    for text in (r.text(), issue(r.issue_url())[1]):
        assert str(home) not in text and 'mapper' not in text
        assert str(Path('~') / 'danu' / 'app.py') in text


def test_the_dialog_opens_the_issue_only_when_asked(monkeypatch, qtbot):
    opened = []
    monkeypatch.setattr(crash.QDesktopServices, 'openUrl', lambda u: opened.append(u.toString()))
    r = crash.Report('Crash: x', 'Traceback\nValueError: x\n', '', VERSIONS)
    dlg = crash.CrashDialog(r)
    qtbot.addWidget(dlg)
    assert opened == []
    assert dlg.issue.isDefault()
    dlg.issue.click()
    assert len(opened) == 1 and issue(opened[0])[0] == 'Crash: x'
    dlg.copy.click()
    assert QApplication.clipboard().text() == r.text()


# ---------------------------------------------------- a fault, next start
RUN = """
import sys, faulthandler
from pathlib import Path
from danu.ui import crash
r = crash.Reporter(Path(sys.argv[1]))
r.install()
log = Path(sys.argv[1]).parent / 'usage.jsonl'
log.write_text('{"kind": "start"}\\n{"kind": "press", "last": true}\\n')
r.attach(type('W', (), {'usage': type('U', (), {'path': log})()})())
if sys.argv[2] == 'fault':
    faulthandler._sigsegv()
r.uninstall()
"""


def run(directory: Path, how: str) -> subprocess.CompletedProcess:
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'QT_QPA_PLATFORM': 'offscreen'}
    return subprocess.run([sys.executable, '-c', RUN, str(directory), how], env=env,
                          capture_output=True, text=True, timeout=60)


def test_a_fault_in_c_is_offered_at_the_next_start_once(tmp_path, qapp):
    d = tmp_path / 'crashes'
    assert run(d, 'fault').returncode != 0
    r = crash.Reporter(d)
    r._versions = dict(VERSIONS)
    got = r.earlier()
    assert len(got) == 1 and got[0].fault
    assert 'Segmentation fault' in got[0].title
    assert 'in <module>' in got[0].trace, 'the Python stack'
    assert '"last": true' in got[0].log, "that run's own log"
    assert got[0].path.exists() and not list(d.glob('*.fault'))
    assert r.earlier() == [], 'offered once'


def test_a_run_that_ended_well_leaves_nothing(tmp_path, qapp):
    d = tmp_path / 'crashes'
    assert run(d, 'clean').returncode == 0
    assert list(d.iterdir()) == []


def test_a_run_still_going_or_killed_is_not_a_fault(tmp_path, qapp):
    d = tmp_path / 'crashes'
    d.mkdir()
    alive = d / '20261015-080000-1.fault'
    alive.write_text(f'{crash.HEAD}danu 0.2.0, here\n{crash.LOG}/x.jsonl\n')
    r = crash.Reporter(d)
    assert r.earlier() == []
    assert alive.exists()


def test_the_dialog_for_an_earlier_run(tmp_path, qtbot):
    r = crash.Report('Crash: Fatal Python error: Segmentation fault', 'Fatal...\n', '', VERSIONS, fault=True)
    dlg = crash.CrashDialog(r, earlier=2)
    qtbot.addWidget(dlg)
    assert '2 times' in dlg.label.text() and 'Any edits it had not saved' in dlg.label.text()


def test_old_reports_are_pruned(tmp_path, qapp):
    d = tmp_path / 'crashes'
    d.mkdir()
    for i in range(crash.KEEP + 5):
        (d / f'20261015-0800{i:02d}-1-1.txt').write_text('old')
    r = crash.Reporter(d)
    r.install(fault=False)
    r.uninstall()
    assert len(list(d.glob('*.txt'))) == crash.KEEP - 1
