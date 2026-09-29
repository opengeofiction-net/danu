"""The viewport solved before the fill - the first build's head start.

A rebuild leaves the previous surface on screen and patches it as the edits
land. The first build of a working set has nothing: ``_loaded`` clears the
surface and the canvas is blank until the fill returns, which at 1 arcsecond
is a minute and a half. So the build hands back the ground the view covers
before it starts filling, and these are the parts of that which do not need
GDAL: the arithmetic that turns a lon/lat view into cells, and the plumbing
that carries the result from the worker to the window.

What the window is worth is measured in ``tests/golden/test_fresh_window.py``
and in ``local.resolve_fresh``; none of that is here.
"""

import pytest

pytest.importorskip('PySide6')

from danu.surface import params as surface_params
from danu.surface.preview import view_box
from danu.ui.surface import Built, SurfaceBuilder

PARAMS = surface_params.load()


class FakeGrid:
    """Just enough ``build.Grid`` for ``view_box``, which reads ``te`` and
    ``res`` and nothing else.

    The real one cannot be imported here: ``danu.surface.build`` imports GDAL
    at module level and this job has Qt and no GDAL. So the arithmetic is
    tested against a stand-in, and ``tests/golden/test_fresh_window.py`` ties
    it to a real ``Grid`` from a real build - the job that has GDAL and no Qt.
    These numbers are a 3 by 2 degree set at 1 arcsecond, with the half cell
    ``Grid.te`` adds on every side.
    """
    north = 22.0
    res = 1 / 3600
    te = (86 - 1 / 7200, 20 - 1 / 7200, 89 + 1 / 7200, 22 + 1 / 7200)


GRID = FakeGrid()
SHAPE = (7201, 10801)


class FakeSet:
    def __init__(self):
        self.squares = {}


def test_a_view_over_the_middle_of_the_grid_is_the_cells_it_covers():
    box = view_box(GRID, (87.0, 20.5, 87.1, 20.6), SHAPE)
    # 0.1 degree is 360 cells at 1 arcsecond, and the grid starts half a cell
    # west of 86 - so a view an exact degree tenth wide covers 360 cells and
    # the cell its edges fall in at each end
    assert box.x1 - box.x0 in (360, 361)
    assert box.y1 - box.y0 in (360, 361)
    # north is up: a box's y0 comes from the view's *northern* edge
    assert box.y0 == pytest.approx((GRID.north - 20.6) * 3600, abs=2)


def test_a_view_hanging_off_the_corner_is_clipped_to_the_grid():
    box = view_box(GRID, (85.0, 19.0, 86.5, 20.5), SHAPE)
    assert (box.x0, box.y1) == (0, SHAPE[0] - 1)
    assert box.x1 < SHAPE[1] and box.y0 >= 0


def test_a_view_that_does_not_reach_the_grid_at_all_is_no_box():
    assert view_box(GRID, (100.0, 40.0, 101.0, 41.0), SHAPE) is None
    assert view_box(GRID, (80.0, 20.5, 85.0, 20.6), SHAPE) is None


def test_the_viewport_reaches_the_build_and_its_answer_reaches_the_window():
    """The plumbing end to end, with the build replaced: a request carrying a
    viewport hands it to the build function, and what the build function calls
    ``early`` with arrives on the builder's ``partial``."""
    seen, views = [], []

    def build_fn(zone_dir, names, params, work, viewport=None, early=None):
        views.append(viewport)
        early('the view')
        return Built(shaded=object())

    jobs = []
    b = SurfaceBuilder(build_fn=build_fn, runner=jobs.append)
    b.partial.connect(seen.append)
    b.request(FakeSet(), PARAMS.with_arcsec(3), viewport=(1.0, 2.0, 3.0, 4.0))
    jobs.pop(0).run()
    assert views == [(1.0, 2.0, 3.0, 4.0)]
    assert seen == ['the view']


def test_a_request_with_no_viewport_calls_the_build_the_way_it_always_was():
    """A build function that takes the four arguments this always had must
    keep working, because every other caller and every other test has one."""
    calls = []

    def build_fn(zone_dir, names, params, work):
        calls.append(params.arcsec)
        return Built(shaded=object())

    jobs = []
    b = SurfaceBuilder(build_fn=build_fn, runner=jobs.append)
    partials = []
    b.partial.connect(partials.append)
    b.request(FakeSet(), PARAMS.with_arcsec(3))
    jobs.pop(0).run()
    assert calls == [3]
    assert partials == []


def test_the_window_asks_for_a_head_start_only_when_it_has_nothing(window):
    """The guard that decides whether the view is worth solving at all.

    With a surface up, a provisional window would replace a whole exact
    surface with a viewport-sized one - everything outside the view lost, to
    say something about the inside the preview says better.
    """
    assert window.surface.shaded is None
    view = window._head_start()
    assert view is not None and len(view) == 4
    west, south, east, north = view
    assert west < east and south < north

    window.surface.shaded = object()        # as a build landing would leave it
    assert window._head_start() is None


def test_a_view_of_another_set_is_not_drawn_over_this_one(window):
    """A 1 arcsecond build is long enough to open another square in, and
    opening one clears the surface - so the guard on ``shaded`` alone would let
    the old set's ground onto the new set's canvas."""
    window._head_start()
    assert window._view_for is window.working_set

    window.working_set = object()           # as _loaded would, for another set
    window._surface_view(object())
    assert window.surface.shaded is None


def test_a_viewport_handed_over_back_to_front_is_no_box():
    """Not reachable from ``_head_start``, whose rectangle is well ordered -
    but a box with a negative side slices to nothing and reaches isofill as a
    zero-width raster, which it rejects as bad arguments long after the
    mistake. Cheaper to refuse it here."""
    assert view_box(GRID, (87.1, 20.6, 87.0, 20.5), SHAPE) is None
