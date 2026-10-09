"""Slope as a mode, and a scaling over the ground in view - H3a. No Qt."""

import math

import numpy as np

from danu.surface import ramp, shade


def plane(rows, cols, rise_per_cell, y1_m=0.0, metres=1000.0):
    dem = np.tile(np.arange(cols, dtype=np.float32) * rise_per_cell + 1, (rows, 1))
    hs = np.full((rows, cols), 181, np.uint8)
    return shade.Shaded(dem=dem, shade=hs, geotransform=(0.0, metres, 0.0, y1_m, 0.0, -metres), metres=metres)


def test_slope_is_taken_against_the_ground_not_the_map():
    """100 m a 1,000 m Mercator cell: 5.7 degrees at the equator. At 60
    degrees a Mercator cell is 500 m of ground, so the same rise a cell is
    twice as steep."""
    at_equator = shade.slope_degrees(plane(5, 9, 100.0).dem, (0.0, 1000.0, 0.0, 2500.0, 0.0, -1000.0))
    assert abs(float(at_equator[2, 4]) - math.degrees(math.atan(0.1))) < 0.05
    y60 = shade.R * math.asinh(math.tan(math.radians(60)))
    at_60 = shade.slope_degrees(plane(5, 9, 100.0).dem, (0.0, 1000.0, 0.0, y60 + 2500.0, 0.0, -1000.0))
    assert abs(float(at_60[2, 4]) - math.degrees(math.atan(0.2))) < 0.2


def test_slope_mode_colours_by_degrees_whatever_the_ramp_and_the_sea_stays_clear():
    s = plane(10, 20, 100.0)
    s.dem[7:, :] = 0.0
    a = shade.compose(s, ramp.spectral(), shade.Scaling('manual', lo=0, hi=5), mode='slope')
    b = shade.compose(s, None, shade.Scaling(), mode='slope')
    assert (a == b).all(), 'the ramp or the scaling coloured a slope'
    want = shade.SLOPE_RAMP.rgba(np.array(math.degrees(math.atan(0.1)), np.float32))
    assert tuple(a[3, 10, :3]) == tuple(want[:3]) and a[3, 10, 3] == 255
    assert (a[8:, :, 3] == 0).all()


def test_slope_composed_in_strips_meets_at_their_joins(monkeypatch):
    rng = np.random.default_rng(3)
    dem = (np.cumsum(np.cumsum(rng.normal(0, 3, (60, 50)), axis=0), axis=1) + 500).astype(np.float32)
    s = shade.Shaded(dem=dem, shade=np.full(dem.shape, 181, np.uint8),
                     geotransform=(0.0, 1000.0, 0.0, 0.0, 0.0, -1000.0), metres=1000.0)
    whole = shade.compose(s, None, shade.Scaling(), mode='slope')
    monkeypatch.setattr(shade, 'strips', lambda rows, cols, **k: [(y, min(7, rows - y)) for y in range(0, rows, 7)])
    banded = shade.compose(s, None, shade.Scaling(), mode='slope')
    assert (whole == banded).all(), 'a strip took its edge rows without their neighbours'


def test_the_view_scaling_stretches_over_the_land_in_its_window():
    s = plane(10, 40, 10.0)                                       # 1 to 391 m west to east
    view = shade.Scaling('view', window=(0, 10, 30, 40))
    lo, hi = view.range_for(s.dem)
    assert (lo, hi) == (301.0, 391.0)
    assert shade.Scaling('view', window=None).range_for(s.dem) == shade.Scaling('auto').range_for(s.dem)
    s.dem[:, 30:] = 0.0
    assert view.range_for(s.dem) == shade.Scaling('auto').range_for(s.dem), 'no land in view'
    s = plane(10, 40, 10.0)
    rgba = shade.compose(s, ramp.spectral(), view, mode='relief')
    assert tuple(rgba[5, 39, :3]) == tuple(ramp.spectral().colour(1.0)[:3]), 'the top of the view is not the ramp top'
