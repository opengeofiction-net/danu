"""Autosave and recovery (H4): the edits a killed Danu had not saved are put
back by the next one to open the set, square by square, as one step.

Over the fixture's Tenmetre square, S24E126, whose five contours run
east-west at 10 to 50 m - in the set the window opens round Los Pizarrales.
"""

import os

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import autosave as A
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.settings import Settings
from danu.ui.territory import TerritoryFetcher

TEN = SquareName(126, -24)


def frozen(sq):
    return (tuple((i, n.lat, n.lon, tuple(n.tags.items())) for i, n in sq.nodes.items()),
            tuple((i, tuple(w.refs), tuple(w.tags.items())) for i, w in sq.ways.items()),
            tuple((i, tuple(r.members), tuple(r.tags.items())) for i, r in sq.relations.items()))


@pytest.fixture
def run(qtbot, zone, tmp_path, territory_files, monkeypatch):
    """A Danu over the zone with a data directory - called again, the next
    run, over the same one. What the offer is answered with is the test's."""
    answers = []
    monkeypatch.setattr(A, 'offer', lambda entries, parent=None: answers.pop(0)(entries, parent) if answers else entries)

    def start():
        fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                                   attributes_url=(territory_files / 'admin.json').as_uri())
        w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                       territory_fetcher=fetcher, data_dir=tmp_path / 'data')
        w.prompt_on_close = False
        w._write_runner = lambda job: job.run()
        qtbot.addWidget(w)
        w.show()
        with qtbot.waitSignal(w.loader.finished, timeout=15000):
            assert w.open_working_set(zone, SquareName(125, -24))
        qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
        qtbot.wait(10)                               # the offer, queued once the set is shown
        return w
    start.answers = answers
    return start


def edit(w):
    """Two edits to Tenmetre as the tools make them: a contour drawn, a node
    of the 30 m one moved."""
    sq = w.working_set.squares[TEN]
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.2, -23.45), (126.8, -23.45)],
                                 {'ele': '55'}))
    thirty = next(wy for wy in sq.ways.values() if wy.tags.get('ele') == '30')
    n = sq.nodes[thirty.refs[0]]
    w.editor.do(sq, edits.MoveNode(n.id, (n.lon, n.lat), (n.lon, n.lat + 0.01)))
    return sq


def test_an_edit_arms_both_timers_and_a_flush_writes_the_change(run):
    w = run()
    assert not w.autosave.pending
    edit(w)
    assert w.autosave._idle.isActive() and w.autosave._every.isActive()
    assert w.autosave._idle.interval() == A.IDLE_MS == 5000 and A.EVERY_MS == 60000
    w.autosave.flush()
    assert w.autosave.written == 1 and not w.autosave.pending
    (e,) = w.autosave.store.entries()
    assert e.square == TEN and e.data['counts'] == {'create': 3, 'modify': 1, 'delete': 0}
    assert e.change_path.suffix == '.osc' and e.change_path.parent.parent == w.autosave.store.root


def test_the_edits_stopping_writes_them(run, qtbot, monkeypatch):
    monkeypatch.setattr(A, 'IDLE_MS', 50)
    monkeypatch.setattr(A, 'EVERY_MS', 60_000)         # never reached here: only the idle can fire
    w = run()
    edit(w)
    qtbot.waitUntil(lambda: w.autosave.store.entries() != [], timeout=2000)


def test_edits_going_on_do_not_put_it_off(run, qtbot, monkeypatch):
    monkeypatch.setattr(A, 'IDLE_MS', 60_000)          # never reached here: only the minute's can fire
    monkeypatch.setattr(A, 'EVERY_MS', 120)
    w = run()
    edit(w)
    qtbot.waitUntil(lambda: w.autosave.store.entries() != [], timeout=2000)
    w.autosave.store.remove(w.zone_dir, TEN)
    sq = w.working_set.squares[TEN]
    for _ in range(12):                              # each edit restarts the idle timer
        n = next(iter(sq.nodes.values()))
        w.editor.do(sq, edits.MoveNode(n.id, (n.lon, n.lat), (n.lon + 1e-5, n.lat)))
        qtbot.wait(20)
    assert w.autosave.store.entries() != [], 'written within the minute while the edits went on'


def test_killed_and_started_again_the_edits_are_put_back_as_one_step(run):
    w = run()
    sq = edit(w)
    want = frozen(sq)
    w.autosave.flush()
    del w                                            # killed: nothing saved, nothing cleared
    w2 = run()
    again = w2.working_set.squares[TEN]
    assert frozen(again) == want, 'the edits, in the order the square had them'
    assert w2.editor.history.dirty(again)
    assert 'put back the autosaved edits to S24E126' in w2.statusBar().currentMessage()
    w2.editor.undo()
    assert not w2.editor.history.dirty(again), 'one undo takes the recovery back'
    (e,) = w2.autosave.store.entries()
    assert e.data['seq'] == 2, 'the recovery is the autosave now'


def test_saved_it_is_gone_and_the_next_run_offers_nothing(run):
    w = run()
    sq = edit(w)
    w.autosave.flush()
    w.save_all()
    assert not w.editor.history.dirty(sq) and w.autosave.store.entries() == []
    w2 = run()
    assert not w2.editor.history.dirty(w2.working_set.squares[TEN])


def test_a_file_changed_since_is_refused_and_set_aside(run):
    w = run()
    edit(w)
    w.autosave.flush()
    path = w.working_set.squares[TEN].path
    os.utime(path, ns=(1, 1))                          # JOSM saved over it in between
    seen = []
    run.answers.append(lambda entries, _: seen.extend(entries) or [])
    w2 = run()
    assert seen and 'has changed since' in seen[0].refused()
    assert not w2.editor.history.dirty(w2.working_set.squares[TEN])
    assert w2.autosave.store.entries() == []
    aside = list((w2.autosave.store.root).rglob('set-aside/*.osc'))
    assert len(aside) == 1 and 'set aside 1' in w2.statusBar().currentMessage()


def test_one_not_chosen_is_set_aside_not_lost(run):
    w = run()
    edit(w)
    w.autosave.flush()
    run.answers.append(lambda entries, _: [])
    w2 = run()
    assert not w2.editor.history.dirty(w2.working_set.squares[TEN])
    assert len(list(w2.autosave.store.root.rglob('set-aside/*.osc'))) == 1


def test_an_earlier_runs_autosave_outlives_a_flush_before_it_is_offered(run):
    """The set opens clean, and a timer can flush while the offer is still
    open: that must not take what an earlier run left for it."""
    w = run()
    want = frozen(edit(w))
    w.autosave.flush()

    def flushed_first(entries, window):
        window.autosave.flush()
        assert window.autosave.store.entries() != [], 'gone before it was offered'
        return list(entries)
    run.answers.append(flushed_first)
    w2 = run()
    assert frozen(w2.working_set.squares[TEN]) == want


def test_leaving_a_set_with_edits_keeps_them(run, zone, qtbot):
    w = run()
    edit(w)
    assert w.autosave.store.entries() == []
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(126, -24), 1)
    assert [e.square for e in w.autosave.store.entries()] == [TEN]


def test_a_close_that_throws_the_edits_away_takes_their_autosave(run, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w = run()
    edit(w)
    w.autosave.flush()
    w.prompt_on_close = True
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Discard)
    w.close()
    assert w.autosave.store.entries() == []


def test_undone_back_to_the_file_its_autosave_goes(run):
    w = run()
    edit(w)
    w.editor.undo()
    w.autosave.flush()
    w.editor.undo()
    assert not w.editor.dirty() and w.autosave.pending, 'the undo to clean still asks for a flush'
    w.autosave.flush()
    assert w.autosave.store.entries() == []


def test_saved_then_edited_again_is_against_the_file_saved(run):
    """The change is against the file as saved, which a save must say."""
    w = run()
    edit(w)
    w.save_all()
    sq = w.working_set.squares[TEN]
    n = next(iter(sq.nodes.values()))
    w.editor.do(sq, edits.MoveNode(n.id, (n.lon, n.lat), (n.lon + 1e-3, n.lat)))
    want = frozen(sq)
    w.autosave.flush()
    w2 = run()
    assert frozen(w2.working_set.squares[TEN]) == want
