"""The usage log and its replay (H4c): what a mapper did, written as they did
it, played back into another window to the same squares - or to the place
the two part.

Over the fixture's Tenmetre square, S24E126, whose five contours run
east-west at 10 to 50 m from -23.9 to -23.5.
"""

import json

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui import replay, usage
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.settings import Settings
from danu.ui.territory import TerritoryFetcher

TEN = SquareName(126, -24)
L, NB = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton


def frozen(sq):
    return (tuple((i, n.lat, n.lon, tuple(n.tags.items())) for i, n in sq.nodes.items()),
            tuple((i, tuple(w.refs), tuple(w.tags.items())) for i, w in sq.ways.items()))


@pytest.fixture
def make(qtbot, tmp_path, territory_files):
    def start(data=True):
        fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                                   attributes_url=(territory_files / 'admin.json').as_uri())
        w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'),
                       territory_fetcher=fetcher, data_dir=(tmp_path / 'data') if data else None)
        w.prompt_on_close = False
        qtbot.addWidget(w)
        w.resize(900, 700)
        w.show()
        return w
    return start


@pytest.fixture
def run(make, zone, qtbot):
    w = make()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    qtbot.wait(10)
    w.map.set_zoom(12)
    w.map.center_on_lonlat(126.5, -23.65)
    return w


def mouse(w, kind, lon, lat, button=L, buttons=L, mods=Qt.KeyboardModifier.NoModifier):
    pos = w.map.viewportTransform().map(QPointF(*m.lonlat_to_scene(lon, lat)))
    QApplication.sendEvent(w.map.viewport(), QMouseEvent(kind, pos, w.map.viewport().mapToGlobal(pos),
                                                         button, buttons, mods))


def click(w, lon, lat):
    mouse(w, QEvent.Type.MouseButtonPress, lon, lat)
    mouse(w, QEvent.Type.MouseButtonRelease, lon, lat, buttons=NB)


def key(w, k):
    QApplication.sendEvent(w.map, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


def mapping(w):
    """A contour drawn by clicks and ended with Enter, a node of the 30 m one
    dragged, an undo and a redo, and the elevation stepped by the wheel."""
    w.elevation.set(25)
    mouse(w, QEvent.Type.MouseMove, 126.1, -23.6, button=NB, buttons=NB)      # hovering: only the last is logged
    mouse(w, QEvent.Type.MouseMove, 126.2, -23.7, button=NB, buttons=NB)
    w.edit_actions['tool.draw'].trigger()
    for lon in (126.30, 126.45, 126.60):
        click(w, lon, -23.75)
    key(w, Qt.Key.Key_Return)
    w.edit_actions['tool.select'].trigger()
    sq = w.working_set.squares[TEN]
    thirty = next(wy for wy in sq.ways.values() if wy.tags.get('ele') == '30')
    n = sq.nodes[thirty.refs[0]]
    mouse(w, QEvent.Type.MouseButtonPress, n.lon, n.lat)
    for k in range(1, 6):
        mouse(w, QEvent.Type.MouseMove, n.lon + 0.004 * k, n.lat + 0.002 * k)
    mouse(w, QEvent.Type.MouseButtonRelease, n.lon + 0.02, n.lat + 0.01, buttons=NB)
    w.edit_actions['edit.undo'].trigger()
    w.edit_actions['edit.redo'].trigger()
    pos = QPointF(w.map.viewport().rect().center())
    QApplication.sendEvent(w.map.viewport(), QWheelEvent(pos, w.map.viewport().mapToGlobal(pos), QPoint(),
                                                         QPoint(0, 120), NB, Qt.KeyboardModifier.ControlModifier,
                                                         Qt.ScrollPhase.NoScrollPhase, False))
    return sq


def logged(w):
    return [json.loads(line) for line in w.usage.path.read_text().splitlines()]


def test_each_click_is_written_with_what_it_could_snap_to(run):
    sq = mapping(run)
    recs = logged(run)
    kinds = [r['kind'] for r in recs]
    assert kinds[0] == 'start' and 'open' in kinds
    opened = next(r for r in recs if r['kind'] == 'open')
    assert opened['centre'] == 'S24E125' and str(sq.name) in opened['files']
    presses = [r for r in recs if r['kind'] == 'press']
    assert [p['tool'] for p in presses] == ['draw'] * 3 + ['select']
    grab = presses[-1]
    thirty = next(wy for wy in sq.ways.values() if wy.tags.get('ele') == '30')
    assert grab['snap']['node']['id'] == thirty.refs[0] and grab['snap']['node']['px'] < 1
    assert grab['snap']['way']['ele'] == '30' and grab['zoom'] == 12
    assert sum(r['kind'] == 'move' for r in recs) == 5, 'the drag, a move at a time'
    hovers = [r for r in recs if r['kind'] == 'hover']
    assert len(hovers) == 1 and hovers[0]['at'][0] == pytest.approx(126.2), 'of a hover, its last place'
    did = [r for r in recs if r['kind'] in ('did', 'undid', 'redid')]
    assert [r['kind'] for r in did][-2:] == ['undid', 'redid']
    assert any(r['kind'] == 'said' for r in recs) and any(r['kind'] == 'wheel' for r in recs)
    assert {'tool'} <= set(kinds) and any(r['kind'] == 'action' and r['name'] == 'edit.undo' for r in recs)
    assert any(r['kind'] == 'key' and r['key'] == int(Qt.Key.Key_Return) for r in recs), 'the Enter that ended it'


def test_replayed_into_another_window_it_comes_to_the_same_squares(run, make):
    sq = mapping(run)
    want = frozen(sq)
    elevation = run.elevation.value
    run.close()
    w2 = make(data=False)
    report = replay.Replayer(w2, replay.records(run.usage.path)).run()
    assert report.parted is None, report.describe()
    assert report.played > 15 and not report.stale
    assert frozen(w2.working_set.squares[TEN]) == want
    assert w2.elevation.value == elevation, 'the wheel stepped it there too'
    last = [r for r in replay.records(run.usage.path) if 'centre' in r][-1]
    assert w2.map.zoom == last['zoom'] and abs(w2.map.center_lonlat()[0] - last['centre'][0]) < 1e-3, \
        'the view the mapper had, to watch it by'


def test_an_action_is_written_before_what_it_did(run):
    mapping(run)
    recs = replay.records(run.usage.path)
    k = next(i for i, r in enumerate(recs) if r['kind'] == 'action' and r['name'] == 'edit.undo')
    assert recs[k + 1]['kind'] == 'undid'


def test_where_the_replay_parts_from_the_log_it_says_so(run, make, tmp_path):
    mapping(run)
    recs = replay.records(run.usage.path)
    first = next(r for r in recs if r['kind'] == 'did')
    first['step'][0]['what'] = 'something else'
    w2 = make(data=False)
    report = replay.Replayer(w2, recs).run()
    assert report.parted is not None and report.parted['logged'][0][1] == ('something else',)
    assert 'parted at' in report.describe()


def test_files_changed_since_the_log_are_said(run, make):
    mapping(run)
    recs = replay.records(run.usage.path)
    next(r for r in recs if r['kind'] == 'open')['files'][str(TEN)][2] = 1
    report = replay.Replayer(make(data=False), recs).run()
    assert str(TEN) in report.stale


def test_a_crash_cut_line_ends_the_log_not_the_reading(run, tmp_path):
    mapping(run)
    text = run.usage.path.read_text()
    cut = tmp_path / 'cut.jsonl'
    cut.write_text(text + '{"t": 9, "kind": "pre')
    assert len(replay.records(cut)) == len(replay.records(run.usage.path))


def test_the_last_runs_are_kept_and_no_more(tmp_path, monkeypatch):
    d = tmp_path / 'usage'
    d.mkdir()
    for k in range(30):
        (d / f'2026{k:04d}.jsonl').write_text('')
    monkeypatch.setattr(usage, 'KEEP', 20)
    log = usage.UsageLog.__new__(usage.UsageLog)     # the pruning alone, with no window to log
    log.directory = d
    log._prune()
    assert len(list(d.glob('*.jsonl'))) == 19, 'room for the run starting'


def test_without_a_data_directory_nothing_is_logged(window):
    assert window.usage is None
