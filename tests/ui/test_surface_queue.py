"""The build queue - F4.

Phase 3's builder ran one build and refused the next: a second Ctrl+R, or a
change of resolution while a build was running, was answered with "a surface is
still building" and dropped. Phase 4 has the editor asking for a surface after
every edit, so dropping is not an option and queueing each one is worse - a run
of twenty edits would cost twenty builds to show the twentieth.

So requests coalesce: newest wins, and only the newest is ever started. These
tests drive that with the build function and the executor replaced, so the
queue is exercised without GDAL and without threads.
"""

import pytest

pytest.importorskip('PySide6')

from danu.surface import params as surface_params         # noqa: E402
from danu.ui.surface import Built, Nothing, SurfaceBuilder  # noqa: E402

PARAMS = surface_params.load()


class FakeSet:
    """Just enough WorkingSet for stage_zone to be given nothing to do."""
    def __init__(self):
        self.squares = {}


class Harness:
    """A builder whose jobs run only when the test says so."""

    def __init__(self, build_fn=None):
        self.jobs = []
        self.built_for = []
        self.builder = SurfaceBuilder(build_fn=build_fn or self._build, runner=self.jobs.append)
        self.results, self.failures, self.starts = [], [], []
        self.builder.started.connect(lambda: self.starts.append(True))
        self.builder.finished.connect(lambda b, stale: self.results.append((b, stale)))
        self.builder.failed.connect(self.failures.append)

    def _build(self, zone_dir, names, params, work):
        self.built_for.append(params.arcsec)
        return Built(shaded=object())

    def finish(self):
        """Run the job the pool was handed, and deliver its signal."""
        assert self.jobs, 'no job was started'
        self.jobs.pop(0).run()

    def ask(self, arcsec):
        return self.builder.request(FakeSet(), PARAMS.with_arcsec(arcsec))


def test_a_request_while_building_is_not_refused(qtbot):
    """The behaviour F4 exists to replace. The old builder returned False here
    and the edit was lost."""
    h = Harness()
    h.ask(3.0)
    assert h.builder.busy
    assert h.ask(1.0) > 0, 'the second request was refused'
    assert len(h.jobs) == 1, 'the second request started a build of its own'


def test_only_the_newest_of_several_requests_is_built(qtbot):
    """Coalescing: three edits during one build cost one more build, not
    three, and the one that runs is the last asked for."""
    h = Harness()
    h.ask(3.0)
    for arcsec in (1.0, 2.0, 0.5):
        h.ask(arcsec)
    h.finish()                       # the first build completes
    assert h.built_for == [3.0], 'more than the first build has run'
    h.finish()                       # whatever was waiting
    assert h.built_for == [3.0, 0.5], f'the queue built {h.built_for[1:]}, not the newest'
    assert not h.jobs, 'a build is still queued after the newest was built'


def test_a_superseded_result_is_delivered_and_marked_stale(qtbot):
    """It cannot be cancelled - isofill has no hook - so it is shown rather
    than wasted, and the flag is what lets R19 say so."""
    h = Harness()
    h.ask(3.0)
    h.ask(1.0)
    h.finish()
    assert len(h.results) == 1
    assert h.results[0][1] is True, 'a superseded build was not marked stale'
    h.finish()
    assert h.results[1][1] is False, 'the newest build was marked stale'


def test_a_lone_build_is_never_stale(qtbot):
    h = Harness()
    h.ask(3.0)
    h.finish()
    assert [stale for _, stale in h.results] == [False]
    assert not h.builder.busy


def test_a_failed_build_still_lets_the_queue_run_on(qtbot):
    """A build that raises must not wedge the queue - the next request has to
    start, or one bad edit stops the editor rebuilding for the session."""
    def explode(zone_dir, names, params, work):
        if params.arcsec == 3.0:
            raise ValueError('contrived')
        return Built(shaded=object())

    h = Harness(build_fn=explode)
    h.ask(3.0)
    h.ask(1.0)
    h.finish()
    assert h.failures and 'contrived' in h.failures[0]
    h.finish()
    assert len(h.results) == 1, 'the queue did not run on after a failure'


def test_nothing_to_build_is_reported_as_itself(qtbot):
    """A set with no contour in it is a sentence, not a traceback."""
    def nothing(zone_dir, names, params, work):
        raise Nothing('nothing to build: no square in the set holds a contour')

    h = Harness(build_fn=nothing)
    h.ask(3.0)
    h.finish()
    assert h.failures == ['nothing to build: no square in the set holds a contour']


def test_staging_happens_once_per_build_not_once_per_request(qtbot):
    """What coalescing is worth on the UI thread: staging the gobras 3x3 is
    177 ms, and the requests that never start must not pay it."""
    h = Harness()
    staged = []
    import danu.core.save as save
    real = save.stage_zone
    save.stage_zone = lambda squares, dirty, into: staged.append(into) or real(squares, dirty, into)
    try:
        h.ask(3.0)
        for arcsec in (1.0, 2.0, 0.5):
            h.ask(arcsec)
        h.finish()
        h.finish()
    finally:
        save.stage_zone = real
    assert len(staged) == 2, f'staged {len(staged)} times for 4 requests and 2 builds'
