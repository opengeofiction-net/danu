"""The cover and the slack, and why they are the sizes they are.

Arithmetic, so it runs wherever python does - `danu.surface.preview` reaches
GDAL only inside the functions that need it, and these do not.

The sizes were chosen in F3 on accuracy alone and re-measured at 1 arcsecond
once the preview moved to a worker and the solve turned out to be all of what a
preview costs. What the numbers were is in `radii`'s own docstring; what they
have to *be* is here, because a default nothing pins is a default that drifts
back.
"""

import pytest

from danu.surface import params as surface_params
from danu.surface import preview

PARAMS = surface_params.load()


@pytest.mark.parametrize('arcsec', [3.0, 1.0])
def test_the_slack_is_one_radius_and_the_cover_depends_on_the_edit(arcsec):
    p = PARAMS.with_arcsec(arcsec)
    r = p.fill_cells

    cover, slack = preview.radii(p)
    assert slack == r, 'the slack is one radius'
    assert cover == r, 'an ordinary edit gets one radius of cover'

    cover, slack = preview.radii(p, removing=True)
    assert slack == r, 'removing a contour does not change the slack'
    assert cover == 2 * r, (
        'an edit that removes a contour gets two radii of cover - the case '
        'measured to need it, where half a radius left 1.616 m out of date')


def test_an_explicit_radius_beats_the_default_either_way():
    """The golden tests pass their own, to measure what each is worth."""
    p = PARAMS.with_arcsec(1.0)
    assert preview.radii(p, cover=7, slack=9) == (7, 9)
    assert preview.radii(p, cover=7, slack=9, removing=True) == (7, 9)
    assert preview.radii(p, cover=0, slack=0) == (0, 0), 'zero is a value, not absence'


def test_removing_widens_the_window_a_box_grows_to():
    """`grown_by` answers for the same solve `patch` will do, so it takes
    `removing` too - the driver decides whether merging two boxes is free by
    what they cost to solve, and they cost different amounts at the two
    covers."""
    p = PARAMS.with_arcsec(1.0)
    assert preview.grown_by(p, removing=True) > preview.grown_by(p), \
        'a removal grows a box further, and the merge test has to know'


def test_the_window_is_smaller_than_it_was():
    """What the change buys, in the units that matter to the solve: the first
    pass sweeps the grown window, and at 1 arcsecond it was 604 by 604 for a
    three-cell edit and is 364 by 364 now."""
    from danu.surface import local

    p = PARAMS.with_arcsec(1.0)
    box = local.Box(1000, 1000, 1003, 1003)
    shape = (8000, 8000)

    def window(**kw):
        cover, slack = preview.radii(p, **kw)
        return box.grown(cover, shape).grown(local.reach(p, slack), shape).cells

    was = window(cover=2 * p.fill_cells, slack=2 * p.fill_cells)
    assert window() < was / 2, 'an ordinary edit sweeps less than half what it did'
    assert window(removing=True) < was, 'a removal sweeps less than it did'
    assert window() < window(removing=True), 'and less than a removal'
