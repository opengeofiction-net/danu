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
        self.builder.finished.connect(
            lambda b, stale, secs: self.results.append((b, stale, secs)))
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
    assert [stale for _, stale, _s in h.results] == [False]
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


def test_each_build_reports_its_own_elapsed_time(qtbot, monkeypatch):
    """How long a build took travels with its result.

    A single attribute on the window cannot hold it once builds overlap: the
    superseded build is delivered while its successor is already queued, so one
    slot is one build's worth of a quantity there are two of. Today `_done`
    emits before starting the next and a single slot would happen to be right -
    which is the trap, because nothing at the window end can see that ordering.
    This pins the number to the build rather than to the order.
    """
    clock = [0.0]
    monkeypatch.setattr('danu.ui.surface.time.monotonic', lambda: clock[0])
    h = Harness()
    h.ask(3.0)                   # the slow one starts at 0
    clock[0] = 10.0
    h.ask(1.0)                   # superseded while it runs
    clock[0] = 12.0
    h.finish()                   # the slow one lands, having taken 12 s
    clock[0] = 15.0
    h.finish()                   # the fast one, started at 12, took 3
    assert [round(secs, 3) for _b, _stale, secs in h.results] == [12.0, 3.0], h.results


def test_cleanup_waits_for_the_build_before_removing_its_directory(qtbot):
    """Closing the window while a build runs must not pull the working
    directory out from under it.

    That cost a traceback ending "rounded.tif: No such file or directory" from
    inside the clamp: the rmtree had taken the file the build was about to
    read. It needed closing during a build, which was rare while builds were
    only ever asked for by hand - and is what closing after drawing does, now
    that an idle timer asks for them.
    """
    h = Harness()
    h.ask(3.0)
    work = h.builder.work
    assert work.exists() and h.builder.busy

    # the job has not run, so the pool has nothing to wait for and cleanup
    # cannot know that; what it must not do is delete while _running
    done = h.builder.cleanup(wait_ms=50)
    assert not done, 'cleanup claimed the build had finished'
    assert work.exists(), 'the working directory was removed while a build was running'

    h.finish()
    assert h.builder.cleanup(wait_ms=50) is True
    assert not work.exists(), 'the working directory was left behind after the build ended'


def test_cleanup_stops_the_queue_taking_more_work(qtbot):
    """A request already waiting must not start a build into a directory that
    is about to go."""
    h = Harness()
    h.ask(3.0)
    h.ask(1.0)                      # queued behind it
    h.builder.cleanup(wait_ms=50)
    h.finish()                      # the running one completes
    assert not h.jobs, 'a queued build started after cleanup'


def test_a_job_whose_window_has_gone_does_not_raise_out_of_run(qtbot):
    """The second half of the same crash. A job outliving the window emits
    into a deleted QObject, and *Signal source has been deleted* comes out of
    QRunnable::run where nobody sees it - while the failure it was reporting
    was the teardown itself."""
    from danu.ui.surface import _Job, _Signals

    class Dead:
        class _S:
            @staticmethod
            def emit(*_a):
                raise RuntimeError('Signal source has been deleted')
        finished = failed = _S()

    def explode(zone_dir, names, params, work):
        raise ValueError('while the window was closing')

    for fn in (explode, lambda *a: Built(shaded=object())):
        job = _Job(fn, h_path(), [], PARAMS, h_path(), Dead())
        job.run()               # must not raise


def h_path():
    from pathlib import Path
    return Path('.')
