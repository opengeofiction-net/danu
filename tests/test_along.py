"""What lies along a line drawn on the map - H3b's measure and profile."""

import math

import numpy as np
import pytest

from danu.core.profile import seg_lengths
from danu.surface import along as A
from danu.surface import shade
from danu.ui import mercator as m

R = 6378137.0


def grid(lon0, lat1, rows, cols, metres, z):
    """A Mercator grid from (lon0, lat1) at its north-west corner, ``z`` a
    function of each cell's latitude and longitude."""
    x0 = R * math.radians(lon0)
    y1 = R * math.log(math.tan(math.pi / 4 + math.radians(lat1) / 2))
    ys = y1 - (np.arange(rows) + 0.5) * metres
    xs = x0 + (np.arange(cols) + 0.5) * metres
    lat = np.degrees(np.arctan(np.sinh(ys / R)))
    lon = np.degrees(xs / R)
    dem = z(lat[:, None] + 0 * lon[None, :], lon[None, :] + 0 * lat[:, None]).astype(np.float32)
    return shade.Shaded(dem=dem, shade=np.zeros(dem.shape, np.uint8),
                        geotransform=(x0, metres, 0.0, y1, 0.0, -metres), metres=metres)


def scene(*lonlat):
    return [m.lonlat_to_scene(lon, lat) for lon, lat in lonlat]


def test_the_length_is_on_the_ground_and_the_drawn_points_are_kept():
    pts = scene((126.2, -23.9), (126.2, -23.5), (126.4, -23.5))
    a = A.along(pts)
    want = seg_lengths([(126.2, -23.9), (126.2, -23.5), (126.4, -23.5)])
    assert a.length == pytest.approx(want.sum(), rel=1e-6)
    assert a.vertex_d[1] == pytest.approx(want[0], rel=1e-6) and len(a.vertex_d) == 3
    assert a.ground is None and a.ends is None and a.climbs() == []


def test_the_ground_is_read_a_cell_apart_as_the_status_line_reads_it():
    s = grid(126.0, -23.0, 240, 240, 500.0, lambda lat, lon: 10 + (lat + 23.9) * 100)
    pts = scene((126.2, -23.9), (126.2, -23.5))
    a = A.along(pts, s)
    left, _, right, _ = s.scene_rect
    cell = (right - left) / s.dem.shape[1]
    assert np.diff(a.scene[:, 1]).max() <= cell * 1.0001 + 1e-9
    assert a.ends == pytest.approx((10, 50), abs=1.0)
    # each point the cell under it, by the same arithmetic as the reading
    one = A.sample(s.dem, s.scene_rect, a.scene[[7]])
    assert a.ground[7] == one[0]
    up, down = a.up_down
    assert up == pytest.approx(40, abs=1.0) and down == 0
    assert a.lowest == pytest.approx(10, abs=1) and a.highest == pytest.approx(50, abs=1)


def test_off_the_grid_is_nan_and_the_ends_are_where_it_reaches():
    s = grid(126.0, -23.0, 100, 100, 500.0, lambda lat, lon: 100 + 0 * lat)
    a = A.along(scene((125.9, -23.1), (126.2, -23.1)), s)
    assert np.isnan(a.ground[0]) and not np.isnan(a.ground[-1])
    assert a.ends == (100, 100)


def test_a_climb_is_from_a_trough_to_the_peak_after_it():
    """Down a valley, over a 30 m knoll, and down again: the knoll's near
    side is the climb, and the fall after it is not; drawn the other way,
    the climbs are the knoll's other side and the long rise after it."""
    def z(lat, lon):
        x = (lon - 126.2) / 0.4                                      # 0 to 1 along
        return 100 - 80 * x + 30 * np.exp(-((x - 0.5) / 0.06) ** 2)
    s = grid(126.0, -23.0, 100, 240, 300.0, z)
    pts = scene((126.2, -23.1), (126.6, -23.1))
    a = A.along(pts, s)
    (d0, d1, rise), = a.climbs()
    mid = a.length / 2
    assert 0.35 * a.length < d0 < d1 < mid and 15 < rise < 30
    peak = a.ground_at(d1)
    assert peak == pytest.approx(np.nanmax(a.ground[(a.dist > d0) & (a.dist < mid * 1.2)]))
    back = A.along(pts[::-1], s).climbs()
    assert len(back) == 2 and back[0][1] < back[1][0] and back[1][2] > 30
    flat = A.along(pts, grid(126.0, -23.0, 100, 240, 300.0, lambda lat, lon: 0 * lat + 5))
    assert flat.climbs() == []


def test_a_rise_and_fall_under_the_least_is_not_a_turn():
    """A metre's wobble on a long climb leaves it one climb."""
    a = A.Along(np.zeros((7, 2)), np.arange(7.0) * 100, np.array([10, 15, 14.5, 20, 19.2, 25, 10.0]), [0, 600])
    assert a.climbs() == [(0.0, 500.0, 15.0)]
    assert np.array(a.climbs(least=0.4)) == pytest.approx(np.array([(0, 100, 5.0), (200, 300, 5.5), (400, 500, 5.8)]))


def test_a_climb_under_a_metre_is_the_surface_rounding():
    s = grid(126.0, -23.0, 100, 240, 300.0, lambda lat, lon: 50 + 0.4 * np.sin(lon * 900))
    assert A.along(scene((126.2, -23.1), (126.6, -23.1)), s).climbs() == []


def test_a_place_along_a_drawn_segment_is_its_distance():
    a = A.along(scene((126.2, -23.9), (126.2, -23.5), (126.4, -23.5)))
    assert a.distance_of(0, 0.5) == pytest.approx(a.vertex_d[1] / 2)
    assert a.distance_of(1, 1.0) == pytest.approx(a.length)
    x, y = a.at(a.vertex_d[1])
    assert (x, y) == pytest.approx(m.lonlat_to_scene(126.2, -23.5))


def test_a_rivers_level_is_between_the_levels_given_and_not_past_them():
    levels = [(100.0, 50.0), (300.0, 30.0)]
    assert A.level_between(levels, 200.0) == pytest.approx(40.0)
    assert A.level_between(levels, 100.0) == 50.0
    assert A.level_between(levels, 50.0) is None and A.level_between(levels, 400.0) is None
    assert A.level_between([], 10.0) is None
    assert A.level_between([(10.0, 7.0)], 10.0) == 7.0 and A.level_between([(10.0, 7.0)], 11.0) is None


def test_off_the_surface_and_back_neither_climbs_nor_falls_across_the_gap():
    """Out over 10 m, off the surface, back on at 60 m: no 50 m climb that
    nobody walking the line would make."""
    g = np.array([10, 11, 10, np.nan, np.nan, 60, 60.5, 62, 61.8])
    a = A.Along(np.zeros((9, 2)), np.arange(9.0) * 100, g, [0, 800])
    up, down = a.up_down
    assert up == pytest.approx(1 + 0.5 + 1.5) and down == pytest.approx(1 + 0.2)
    assert [c[:2] for c in a.climbs()] == [(0.0, 100.0), (500.0, 700.0)]
