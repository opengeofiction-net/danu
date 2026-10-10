"""The working surface against the published DEM - H3c."""

import math

import numpy as np
import pytest

from danu.surface import difference as D
from danu.surface import shade

R = 6378137.0


def test_the_difference_is_working_less_published_and_sea_in_both_is_none():
    dem = np.array([[10.0, 0.0, 0.0, 5.0, 0.0]], np.float32)
    pub = np.array([[7.0, 0.0, 1.0, np.nan, -3.0]], np.float32)
    d = D.difference(dem, pub)
    assert d[0, 0] == 3.0 and d[0, 1] == 0.0
    assert d[0, 4] == 0.0, 'sea both times, whatever depth the server gave it'
    assert d[0, 2] == -1.0, 'sea here, land there: a change'
    assert np.isnan(d[0, 3]), 'nothing published: nothing to say'


def test_the_span_is_what_changed_rounded_up_never_under_five():
    rng = np.random.default_rng(1)
    d = np.zeros((100, 100), np.float32)
    d[:10] = rng.uniform(-30, 30, (10, 100))          # a thousand cells moved, up to 30 m
    d[0, 0] = 800.0                                    # and one bulldozed hill
    assert D.span(d) == 30.0, 'the percentile, not the hill, and a figure that reads'
    assert D.span(np.zeros((5, 5))) == D.SPAN_MIN_M
    few = np.zeros(10000, np.float32)
    few[:100] = np.linspace(1, 30, 100)                # a hundred cells moved in a square of ten thousand
    assert D.span(few) == 30.0, 'the unchanged ground counted, and the edits saturate'
    assert D.span(np.full((5, 5), 0.3)) == D.SPAN_MIN_M, 'rounding is not a change'
    assert D.span(np.full((5, 5), 1.2)) == D.SPAN_MIN_M
    assert D.span(np.full((5, 5), 130.0)) == 150.0
    assert D.span(np.full((5, 5), 10.02)) == 10.0 and D.span(np.full((5, 5), 31.6)) == 40.0
    assert D.span(np.full((5, 5), np.nan)) == D.SPAN_MIN_M


def test_higher_is_red_lower_blue_and_under_half_a_metre_clear():
    d = np.array([[40.0, -40.0, 0.3, -0.49, 0.5, np.nan]], np.float32)
    c = D.rgba(d, 50.0, d.shape)
    (up, down, small, small2, half, none) = c[0]
    assert up[0] > up[2] + 100 and down[2] > down[0] + 100
    assert small[3] == small2[3] == none[3] == 0
    assert up[3] == down[3] == half[3] == 255
    assert (D.rgba(None, 50.0, (3, 4)) == 0).all(), 'not worked out yet: clear'


def test_the_ends_of_the_ramp_are_the_span():
    c = D.rgba(np.array([[50.0, -50.0, 500.0]], np.float32), 50.0, (1, 3))
    assert tuple(c[0, 0, :3]) == D.DIFF_RAMP.colours[-1][:3] == tuple(c[0, 2, :3])
    assert tuple(c[0, 1, :3]) == D.DIFF_RAMP.colours[0][:3]


def mercator_grid(lon0, lat1, rows, cols, metres):
    x0 = R * math.radians(lon0)
    y1 = R * math.log(math.tan(math.pi / 4 + math.radians(lat1) / 2))
    dem = np.zeros((rows, cols), np.float32)
    return shade.Shaded(dem=dem, shade=np.zeros(dem.shape, np.uint8),
                        geotransform=(x0, metres, 0.0, y1, 0.0, -metres), metres=metres)


def write_lonlat(path, lon0, lat1, step, z):
    gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
    gdal.UseExceptions()
    rows, cols = z.shape
    ds = gdal.GetDriverByName('GTiff').Create(str(path), cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((lon0, step, 0.0, lat1, 0.0, -step))
    ds.SetProjection('EPSG:4326')
    ds.GetRasterBand(1).WriteArray(z)
    ds.FlushCache()
    return path


def test_the_published_dem_is_warped_onto_the_layers_grid(tmp_path):
    """A published DEM rising 100 m a degree eastward, read back onto a
    Mercator grid over part of it: each cell its longitude's height, and
    NaN past the published extent."""
    step = 1 / 120
    lon = 126.0 + (np.arange(120) + 0.5) * step
    z = np.tile(100 * (lon - 126.0), (120, 1)).astype(np.float32)
    path = write_lonlat(tmp_path / 'dem.tif', 126.0, -23.0, step, z)
    s = mercator_grid(126.5, -23.2, 60, 120, 1000.0)               # runs off the east edge
    pub = D.published_on(path, s)
    assert pub.shape == s.dem.shape
    xs = s.geotransform[0] + (np.arange(120) + 0.5) * 1000.0
    lons = np.degrees(xs / R)
    inside = lons < 126.99
    assert np.allclose(pub[30, inside], 100 * (lons[inside] - 126.0), atol=1.0)
    assert np.isnan(pub[30, lons > 127.01]).all()
