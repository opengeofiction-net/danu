"""danu.ui.mercator: the projection the canvas lives in. Pure arithmetic."""

import math

import pytest
from hypothesis import given, strategies as st

from danu.ui import mercator as m


def test_the_world_is_square_and_sized_for_the_scene_zoom():
    assert m.WORLD == 256 * 2 ** 19
    assert m.tile_size(m.SCENE_ZOOM) == 256
    assert m.tile_size(0) == m.WORLD


@given(st.floats(-180, 180), st.floats(-85, 85))
def test_projection_round_trips(lon, lat):
    x, y = m.lonlat_to_scene(lon, lat)
    lon2, lat2 = m.scene_to_lonlat(x, y)
    assert math.isclose(lon, lon2, abs_tol=1e-9)
    assert math.isclose(lat, lat2, abs_tol=1e-9)


def test_the_corners_and_the_middle():
    assert m.lonlat_to_scene(-180, 0) == (0.0, m.WORLD / 2)
    assert m.lonlat_to_scene(0, 0) == (m.WORLD / 2, m.WORLD / 2)
    x, y = m.lonlat_to_scene(180, m.MAX_LAT)
    assert math.isclose(x, m.WORLD) and math.isclose(y, 0.0, abs_tol=1e-6)


def test_latitude_beyond_the_cut_is_clamped_not_infinite():
    _, y = m.lonlat_to_scene(0, 90)
    assert math.isclose(y, 0.0, abs_tol=1e-6)
    _, y = m.lonlat_to_scene(0, -90)
    assert math.isclose(y, m.WORLD, abs_tol=1e-6)


@given(st.integers(0, 19))
def test_scale_and_zoom_are_inverses(z):
    assert math.isclose(m.zoom_for_scale(m.scale_for_zoom(z)), z)


def test_tile_rects_tile_the_world_at_each_zoom():
    for z in (0, 1, 5, 19):
        n = 1 << z
        left, top, right, bottom = m.tile_rect(z, n - 1, n - 1)
        assert math.isclose(right, m.WORLD) and math.isclose(bottom, m.WORLD)
        assert math.isclose(right - left, m.tile_size(z))


def test_tiles_in_rect_covers_exactly_the_tiles_touched():
    s = m.tile_size(3)
    tiles = list(m.tiles_in_rect(s * 1.5, s * 2.5, s * 3.5, s * 3.5, 3))
    assert tiles == [(3, 1, 2), (3, 2, 2), (3, 3, 2), (3, 1, 3), (3, 2, 3), (3, 3, 3)]


def test_tiles_in_rect_clamps_y_and_not_x():
    s = m.tile_size(2)
    tiles = list(m.tiles_in_rect(-s, -s, s, s * 5, 2))
    ys = {t[2] for t in tiles}
    xs = {t[1] for t in tiles}
    assert ys == {0, 1, 2, 3}            # nothing above or below the world
    assert xs == {-1, 0}                 # but the west of -180 is drawn
    assert m.wrap_x(-1, 2) == 3 and m.wrap_x(4, 2) == 0


def test_tiles_in_rect_of_nothing_is_nothing():
    assert list(m.tiles_in_rect(5, 5, 5, 9, 4)) == []
    assert list(m.tiles_in_rect(9, 5, 5, 9, 4)) == []


def test_zoom_to_fit_picks_the_largest_zoom_that_fits():
    # one degree square at the equator in a 1000x700 viewport: at z9 a degree
    # is 364 px, at z10 728 px, which no longer fits 700 high
    x0, y0 = m.lonlat_to_scene(87, 21)
    x1, y1 = m.lonlat_to_scene(88, 20)
    assert m.zoom_to_fit(1000, 700, x0, y0, x1, y1) == 9
    assert m.zoom_to_fit(1000, 800, x0, y0, x1, y1) == 10
    assert m.zoom_to_fit(10, 10, 0, 0, m.WORLD, m.WORLD) == 0
    assert m.zoom_to_fit(1e9, 1e9, 0, 0, 1, 1) == m.MAX_ZOOM


def test_the_array_projection_is_the_scalar_one_to_far_below_a_pixel():
    """The editor projects a whole working set at once, and the two forms have
    to agree.

    Not to the last bit: numpy's log, tan and cos are not always the libm math
    reaches, and on the CI runner they part company in the last place - 8.9e-07
    scene units, where 1.0 is a pixel at the zoom the scene is measured in.
    They are identical on some machines and this asserted that, which is a true
    statement about one libm and not about the code. A hundred-thousandth of a
    pixel is the bound that means something: far below anything a mapper can
    point at, far above the disagreement seen."""
    import numpy as np

    rng = np.random.default_rng(1)
    lon = rng.uniform(-180, 180, 50_000)
    lat = rng.uniform(-89.9, 89.9, 50_000)
    # and the places the formula is delicate: the poles it clamps at, the
    # equator, the meridian, and coordinates small enough to go exponential
    lon = np.concatenate([lon, [0.0, -0.0, 180.0, -180.0, 1e-7, -1e-7]])
    lat = np.concatenate([lat, [0.0, -0.0, 90.0, -90.0, m.MAX_LAT, -m.MAX_LAT]])

    got = m.lonlat_to_scene_array(lon, lat)
    want = np.array([m.lonlat_to_scene(a, b) for a, b in zip(lon, lat)])
    assert got.shape == want.shape == (len(lon), 2)
    worst = float(np.abs(got - want).max())
    assert worst < 1e-5, f'worst {worst} scene units, which is {worst:.1e} of a pixel at z19'


def test_both_projections_clamp_at_the_mercator_cut():
    """Mercator's y runs to infinity at the poles, so both forms clamp the
    latitude before projecting - the scalar on its first line, the array with
    np.clip. Beyond the cut they have to agree exactly rather than to within
    a fraction of a pixel, because there the disagreement would not be a
    rounding difference: one clamping and the other not puts the pole at
    infinity against the edge of the world."""
    import numpy as np

    beyond = [m.MAX_LAT, -m.MAX_LAT, 85.1, -85.1, 89.9, 90.0, -90.0, 1e6]
    got = m.lonlat_to_scene_array([10.0] * len(beyond), beyond)
    want = np.array([m.lonlat_to_scene(10.0, b) for b in beyond])
    assert np.array_equal(got, want), f'{got} != {want}'
    # and the clamp really is doing something: past it, y stops moving
    assert got[beyond.index(90.0)][1] == got[beyond.index(1e6)][1]
    assert np.isfinite(got).all()
