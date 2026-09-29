"""A window solved with nothing behind it - the first build's head start.

``local.resolve`` holds its rim at the last whole-raster answer, which is what
makes a patch exact. The first build of a working set has no such answer and
draws nothing at all until the fill returns, which at 1 arcsecond is a minute
and a half of blank canvas. ``local.resolve_fresh`` solves the view as if it
were the raster - no rim, both passes - and relies on the margin alone.

So this asks whether the margin is enough, the way ``test_local_solve``asks
whether the rim is: solve the same ground both ways and compare. It also
asserts the thing that makes the question worth asking - that a window solved
with no margin at all is much worse - because a test that passes at any margin
is not testing the margin.
"""

import shutil
from pathlib import Path

import pytest
from test_local_solve import lock_params, solved

HERE = Path(__file__).parent
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def drawn_box(surface, mask, side: int):
    """The ``side`` by ``side`` box of drawn ground with the most relief in it.

    Not the middle of the drawn area, which is what this looked for first. Most
    of this square's drawn ground is flat - two thirds of a 200 cell box at the
    median of the mask holds one elevation - and over flat ground every solve
    agrees with every other, including a patch read fifty cells from where it
    belongs. A test that picks its ground by where the contours are rather than
    by what they say passes on arithmetic that is not being done.
    """

    from danu.surface import local
    rows, cols = mask.shape
    best = None
    for r in range(0, rows - side, side // 4):
        for c in range(0, cols - side, side // 4):
            sub, m = surface[r:r + side, c:c + side], mask[r:r + side, c:c + side] != 0
            if m.sum() < side * side // 4:
                continue
            spread = float(sub[m].max() - sub[m].min())
            if best is None or spread > best[0]:
                best = (spread, r, c)
    assert best is not None and best[0] > 100, 'no box of this square holds any relief'
    _, r, c = best
    return local.Box(c, r, c + side - 1, r + side - 1)


def worst_over_drawn(a, b, box, mask):
    import numpy as np
    sl = box.slice
    drawn = mask[sl] != 0
    if not drawn.any():
        return 0.0
    return float(np.abs(a - b[sl].astype(np.float64))[drawn].max())


def test_a_window_with_no_rim_is_the_whole_rasters_answer(tmp_path):
    """The question. Solve a box of the golden square with nothing behind it
    and compare with the whole-raster fill over the same cells."""
    import numpy as np

    from danu.surface import local

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    whole = solved(zone, tmp_path / 'w', p)

    box = drawn_box(whole['surface'], whole['mask'], 200)
    patch, good = local.resolve_fresh(whole['constraints'], whole['mask'], whole['water'],
                                      box, p, nodata=whole['nodata'])
    assert good == box
    assert patch.shape == box.shape

    # the ground has to be ground, or this compares two rasters of nothing
    assert (whole['mask'][box.slice] != 0).sum() > 1000, 'the box is not on drawn ground'

    worst = worst_over_drawn(patch.astype(np.float64), whole['surface'], box, whole['mask'])
    assert worst < 1.0, f'a window with two radii of margin is {worst:.3f} m out'


def test_the_comparison_would_notice_the_patch_being_in_the_wrong_place(tmp_path):
    """Falsification, and not the one this file was first written with.

    The obvious check is that a window with no margin is worse than one with
    two radii. On this fixture it is not: both are exact. The reason is the one
    ``test_local_solve`` gives - the second pass only moves cells the first
    declined, and here those regions are small enough to sit inside any window
    worth solving, so the window's edge never cuts one. The margin earns its
    keep at 1 arcsecond on the gobras 3x3, where the regions are large: a
    window cut back by one radius is 10.09 m out at its worst and by two radii
    0.85 m. Those numbers are in ``local.resolve_fresh`` and not assertable
    here, because this fixture cannot produce the ground that makes them.

    What is assertable is that the comparison above is sensitive to where the
    patch sits. A crop off by fifty cells is the realistic way for this to
    break, and it has to fail loudly when it happens - otherwise the test
    passes on any patch of roughly the right shape.
    """
    import numpy as np

    from danu.surface import local

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    whole = solved(zone, tmp_path / 'w', p)
    box = drawn_box(whole['surface'], whole['mask'], 200)

    patch, _ = local.resolve_fresh(whole['constraints'], whole['mask'], whole['water'],
                                   box, p, nodata=whole['nodata'])
    here = worst_over_drawn(patch.astype(np.float64), whole['surface'], box, whole['mask'])
    from danu.surface.local import Box
    moved = Box(box.x0 + 50, box.y0 + 50, box.x1 + 50, box.y1 + 50)
    there = worst_over_drawn(patch.astype(np.float64), whole['surface'], moved, whole['mask'])
    assert here < 1.0
    assert there > 100.0, (
        f'the patch matches the surface {there:.3f} m away from where it belongs, '
        f'so matching it in place says nothing')


def test_a_box_at_the_rasters_own_edge_is_not_grown_past_it(tmp_path):
    """``fresh_grown`` clips, so a view at the corner of the working set asks
    for cells that exist."""
    from danu.surface import local, params

    p = params.load().with_arcsec(3)
    shape = (500, 400)
    grown = local.fresh_grown(local.Box(0, 0, 10, 10), p, shape)
    assert (grown.x0, grown.y0) == (0, 0)
    assert grown.x1 < shape[1] and grown.y1 < shape[0]
    whole = local.fresh_grown(local.Box(0, 0, 399, 499), p, shape)
    assert (whole.x0, whole.y0, whole.x1, whole.y1) == (0, 0, 399, 499)


def test_the_view_comes_back_shaded_and_where_it_was_asked_for(tmp_path):
    """``view_window`` end to end: the build's own grids in, a shaded surface
    out, on the ground the view covers and nowhere else.

    This is the one part of the head start that needs both GDAL and a real
    build, so it lives here rather than beside the rest of it in
    ``tests/ui/test_surface_view.py`` - the ui job has Qt and no GDAL.
    """
    import numpy as np

    from danu.surface import preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    whole = solved(zone, tmp_path / 'w', p)
    result = whole['result']

    box = drawn_box(whole['surface'], whole['mask'], 200)
    west, north, east, south = preview.box_extent(whole['gt'], box)
    shaded = preview.view_window(result.constraints, result.drawn_mask, result.water_mask,
                                 result.grid, (west, south, east, north), p)
    assert shaded is not None

    # the ground it covers, back through the same arithmetic. A view covers
    # every cell it touches, so a round trip through the box's own corners
    # comes back one cell wider at each far edge rather than identical - the
    # far corner sits exactly on a cell boundary and the cell beyond it is
    # half-covered by definition
    again = preview.view_box(result.grid, (west, south, east, north), whole['mask'].shape)
    assert (again.x0, again.y0) == (box.x0, box.y0)
    assert box.x1 <= again.x1 <= box.x1 + 2
    assert box.y1 <= again.y1 <= box.y1 + 2

    # a surface, not a flat plate: this box was chosen for its relief
    assert float(shaded.dem.max() - shaded.dem.min()) > 100
    assert shaded.shade.dtype == np.uint8 and shaded.shade.shape == shaded.dem.shape

    # and it sits where the box does, not where the raster does. Checked on
    # the canvas, which is where it matters: the scene rectangle the layer
    # would draw it into is the box's own corners, to within a cell of the
    # Mercator grid it was warped onto. The shapes alone would not show this -
    # a window solved a few cells off is the same size as one solved in the
    # right place.
    from danu.ui import mercator as m  # pure arithmetic; it imports no Qt
    left, top = m.lonlat_to_scene(west, north)
    right, bottom = m.lonlat_to_scene(east, south)
    got = shaded.scene_rect
    cell = abs(shaded.geotransform[1]) / (2 * 20037508.342789244) * m.WORLD
    for want, have in zip((left, top, right, bottom), got, strict=True):
        assert abs(want - have) < 3 * cell, f'{got} is not {(left, top, right, bottom)}'


def test_the_view_holds_land_off_zero_the_way_the_clamp_does(tmp_path):
    """Zero is transparent in the relief ramp, so flat ground that interpolates
    to zero would vanish from the map - 64% of the low land in zone-roantra
    did, which is why the build clamps. ``view_window`` cannot run the real
    clamp, whose sea decision floods from open water and needs the whole
    raster, so it holds land off zero inside the drawn mask instead.

    Asserted against the fill it is holding: the raw window has zeros on drawn
    ground, and what comes back has very few.
    """
    import numpy as np

    from danu.surface import local, preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    whole = solved(zone, tmp_path / 'w', p)
    result = whole['result']

    box = drawn_box(whole['surface'], whole['mask'], 200)
    patch, _ = local.resolve_fresh(whole['constraints'], whole['mask'], whole['water'],
                                   box, p, nodata=whole['nodata'])
    drawn = whole['mask'][box.slice] != 0
    raw_zeros = float((patch[drawn] == 0).mean())
    # without this the test asserts nothing: ground that never reads zero is
    # ground the clamp has no work to do on
    assert raw_zeros > 0.01, 'no cell of this ground needed the clamp'

    west, north, east, south = preview.box_extent(whole['gt'], box)
    shaded = preview.view_window(result.constraints, result.drawn_mask, result.water_mask,
                                 result.grid, (west, south, east, north), p)
    shown_zeros = float((np.asarray(shaded.dem) == 0).mean())
    assert shown_zeros < raw_zeros / 2, (
        f'the fill reads zero over {raw_zeros:.1%} of this ground and what is '
        f'shown over {shown_zeros:.1%} - the clamp rule is not being applied')

    # and what is still zero is the ground outside the drawn mask, which the
    # rule leaves alone on purpose: those cells are the raster's untouched
    # surroundings and transparent is what they should be. The two fractions
    # are measured on different grids - the shown one has been through the
    # Mercator warp - so they agree to a few per cent rather than exactly
    undrawn = 1.0 - float(drawn.mean())
    assert abs(shown_zeros - undrawn) < 0.03, (
        f'{shown_zeros:.1%} of the view reads zero against {undrawn:.1%} of it '
        f'lying outside the drawn mask - something else is being held at zero')
