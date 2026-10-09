"""The surface's checks in the panel - H2: asked of a build, on its worker,
while the panel is open; said pending while that build runs, and stale once
an edit follows it."""

import pytest

pytest.importorskip('PySide6')

from danu.checks import surface as surface_checks
from danu.checks.files import Finding
from danu.core import edits
from danu.core.square import SquareName
from danu.surface import params as surface_params
from danu.ui.surface import Built, SurfaceBuilder

NORTH = SquareName(125, -23)
CLIMB = Finding(NORTH, 'climb', 'river "Bass River", way 7 - climbs 50 m it cannot lose', 'burn it',
                125.5, -22.5, (125.4, -22.6, 125.6, -22.4), way=7)
SEA = Finding(NORTH, 'sea', 'sea level 1.5 km from a drawn shore, for 3.4 km', 'an island with no coastline',
              125.9, -22.9, (125.8, -22.95, 125.95, -22.85))


class FakeSet:
    squares = {}


def test_a_build_asks_the_checks_of_its_own_grids_before_it_is_handed_back(monkeypatch):
    jobs = []
    builder = SurfaceBuilder(build_fn=lambda *a: Built(shaded=object()), runner=jobs.append)
    got = []
    builder.finished.connect(lambda b, stale, secs: got.append(b))
    asked = []
    monkeypatch.setattr(surface_checks, 'find', lambda snap, work: asked.append((snap, work)) or [CLIMB])
    builder.checks_snapshot = lambda ws: 'the snapshot'
    builder.request(FakeSet(), surface_params.load())
    assert builder.checking
    jobs.pop().run()
    (built,) = got
    assert built.checks == [CLIMB] and asked == [('the snapshot', builder.work)]
    # nobody looking: no snapshot, no checks, and a check that fails costs its list
    builder.checks_snapshot = lambda ws: None
    builder.request(FakeSet(), surface_params.load())
    assert not builder.checking
    jobs.pop().run()
    assert got[-1].checks is None
    builder.checks_snapshot = lambda ws: 'again'
    monkeypatch.setattr(surface_checks, 'find', lambda snap, work: 1 / 0)
    builder.request(FakeSet(), surface_params.load())
    jobs.pop().run()
    assert got[-1].checks is None and 'ZeroDivisionError' in got[-1].checks_failed
    builder.cleanup()


def test_the_panel_says_pending_then_the_findings_then_stale(window, qtbot):
    w = window
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.inside_index is not None, timeout=5000)
    d = w.checks_dock
    assert 'nothing yet' in d.surface_summary.text() and not d.surface_busy.isVisible()
    w.builder.checking = True
    w._surface_starting()
    w._refresh_checks()
    assert 'the build now running will say them' in d.surface_summary.text() and d.surface_busy.isVisible()
    shaded = w.surface.shaded
    built = Built(shaded=shaded, checks=[CLIMB, SEA])
    w._surface_built_shown = lambda *a: None        # the surface itself is not what this is about
    w._surface_built(built, False, 1.0)
    w._refresh_checks()
    assert not d.surface_busy.isVisible()
    assert d.surface_summary.text().startswith('From the build at ')
    assert '1 river climbing, 1 stretch of sea level off the shore' in d.surface_summary.text()
    heads = [d.surface_tree.topLevelItem(i).text(0) for i in range(d.surface_tree.topLevelItemCount())]
    assert heads == ['Rivers which climb on the surface (R29) - B burns a climb (1)',
                     'Sea level off the drawn coastline (R32) (1)']
    # a sea level row is a place, with nothing to select
    sea = d.surface_tree.topLevelItem(1).child(0)
    d.surface_tree.setCurrentItem(sea)
    assert 'no coastline' in w.statusBar().currentMessage()
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.AddNode(alloc.take(), (125.5, -22.5), {'ele': '300'}))
    w._refresh_checks()
    assert 'edits since, so the next build will say again' in d.surface_summary.text()
