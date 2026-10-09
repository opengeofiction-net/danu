"""Saves and the checks' first scan, off the UI thread.

Both were seconds of it on gobras - 21.6 s to save the 3x3, 9.3 s to open the
checks panel - and the desktop offered to kill the window. The window fixture
runs both where they are asked for; these run them on their workers, or hold
them, to see what happens in between.
"""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox

from danu.core import edits, save
from danu.core.square import SquareName, read_square

TEN = SquareName(126, -24)
NORTH = SquareName(125, -23)


def draw_into(w, square, ele, lon, lat):
    alloc = w.editor.history.alloc(square)
    cmd = edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(lon, lat), (lon + 0.1, lat)], {'ele': str(ele)})
    w.editor.do(square, cmd)
    return cmd


def test_a_save_on_the_writer_lands_and_a_close_waits_for_it(window, zone):
    w = window
    w._write_runner = w._write_pool.start
    ten = w.working_set.squares[TEN]
    draw_into(w, ten, 61, 126.2, -23.45)
    assert w.save_all()
    w.wait_for_writes()
    assert not w.editor.dirty() and 61 in read_square(zone / 'S24E126_Tenmetre.osm.xz').elevations()
    assert 'saved S24E126_Tenmetre.osm.xz' in w.statusBar().currentMessage()
    draw_into(w, ten, 62, 126.2, -23.40)
    w.save_all()
    w.close()                                    # waits: the file is whole and has it
    assert not w._writes and not w.editor.dirty(), 'closed before the write had answered'
    assert 62 in read_square(zone / 'S24E126_Tenmetre.osm.xz').elevations()


def test_an_edit_made_while_the_file_is_written_keeps_the_square_dirty(window, zone):
    w = window
    held = []
    w._write_runner = held.append
    ten = w.working_set.squares[TEN]
    draw_into(w, ten, 61, 126.2, -23.45)
    w.save_all()
    assert w.statusBar().currentMessage() == 'saving 1 square…'
    assert w.editor.dirty(), 'clean before its file was written'
    draw_into(w, ten, 62, 126.2, -23.40)        # while it is written
    held.pop().run()
    on_disk = read_square(zone / 'S24E126_Tenmetre.osm.xz').elevations()
    assert 61 in on_disk and 62 not in on_disk
    assert w.editor.dirty() and w.windowTitle().endswith('*'), 'the edit made meanwhile was taken as saved'
    w.editor.undo()
    assert not w.editor.dirty(), 'back to what the file holds'


def test_a_write_that_fails_says_so_and_leaves_the_square_dirty(window, zone, monkeypatch):
    w = window
    told = []
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(lambda *a, **k: told.append(a[2])))

    def refuse(pending):
        raise OSError('No space left on device')
    monkeypatch.setattr(save, 'write', refuse)
    before = (zone / 'S24E126_Tenmetre.osm.xz').read_bytes()
    draw_into(w, w.working_set.squares[TEN], 61, 126.2, -23.45)
    w.save_all()
    assert w.editor.dirty() and told and 'No space left on device' in told[0]
    assert 'not saved' in w.statusBar().currentMessage()
    assert (zone / 'S24E126_Tenmetre.osm.xz').read_bytes() == before


def test_the_checks_scan_runs_on_a_worker_and_takes_the_edits_made_meanwhile(window):
    """Held: the panel says it is finding them. The scan reads the square,
    a crossing is drawn, and then the scan's answer lands - with the
    crossing in it, put to the indexes as the edit it was."""
    w = window
    held = []
    w._checks_runner = held.append
    w.checks_dock.toggleViewAction().trigger()
    assert 'Finding' in w.checks_dock.summary.text() and w.crossing_index is None
    sq = w.working_set.squares[NORTH]
    a = draw_into(w, sq, 100, 125.3, -22.5)
    job = held.pop()
    read = job.fn()                                   # the worker's scan, before the edit
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()],
                                 [(125.35, -22.55), (125.35, -22.45)], {'ele': '125'}))
    job.signals.done.emit(read)
    assert any(a.way_id in (c.a[1], c.b[1]) for c in w.crossing_index.crossings()), \
        'the crossing drawn while the scan ran is not listed'
    assert 'crossing' in w.checks_dock.summary.text()


def test_the_checks_scan_on_the_pool(window, qtbot):
    w = window
    w._checks_runner = QThreadPool.globalInstance().start
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.spot_index is not None, timeout=15000)
    assert w._checks_job is None and 'Finding' not in w.checks_dock.summary.text()


def test_a_scan_a_dict_changed_under_is_started_again(window, monkeypatch):
    from danu.ui import app
    calls = []
    real = app.crossings.Index

    def flaky(ws):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('dictionary changed size during iteration')
        return real(ws)
    monkeypatch.setattr(app.crossings, 'Index', flaky)
    assert app.find_checks(window.working_set)[0] is not None and len(calls) == 2


def test_a_scan_that_fails_says_so_in_the_panel(window, monkeypatch):
    from danu.ui import app

    def broken(ws, **_):
        raise ValueError('a square with no name')
    monkeypatch.setattr(app, 'find_checks', broken)
    window.checks_dock.toggleViewAction().trigger()
    assert 'could not be found: ValueError: a square with no name' in window.checks_dock.summary.text()
    assert window._checks_job is None
