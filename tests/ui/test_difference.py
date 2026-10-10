"""The difference (H3c): the exact build less the published DEM, as a fifth
way of showing the surface.

The surface is the fixture's Tenmetre ground, rising north from 10 m at
-23.9 to 50 at -23.5; the published DEM is the same ground 10 m lower east of
126.5 - so that half has been raised since the server last built it.
"""

import math

import numpy as np
import pytest

pytest.importorskip('PySide6')
pytest.importorskip('osgeo.gdal', reason='GDAL not available')

from PySide6.QtCore import Qt

from danu.surface import difference as D
from danu.surface import shade
from danu.ui import mercator as m
from danu.ui.surface import Built, _composed_now

R = 6378137.0


def rising_north(raise_m=0.0):
    x0 = R * math.radians(126.0)
    y1 = R * math.log(math.tan(math.pi / 4 + math.radians(-23.0) / 2))
    rows, cols, metres = 260, 230, 500.0
    ys = y1 - (np.arange(rows) + 0.5) * metres
    lat = np.degrees(np.arctan(np.sinh(ys / R)))
    dem = np.repeat((10 + (lat + 23.9) * 100 + raise_m)[:, None], cols, axis=1).astype(np.float32)
    return shade.Shaded(dem=dem, shade=np.zeros(dem.shape, np.uint8),
                        geotransform=(x0, metres, 0.0, y1, 0.0, -metres), metres=metres)


def publish(root, zone='pizarrales'):
    """The zone's published DEM: the same ground, 10 m lower east of 126.5."""
    from osgeo import gdal
    gdal.UseExceptions()
    step = 1 / 120
    lat = -23.0 - (np.arange(120) + 0.5) * step
    lon = 126.0 + (np.arange(120) + 0.5) * step
    z = (10 + (lat[:, None] + 23.9) * 100) + 0 * lon[None, :]
    z[:, lon > 126.5] -= 10
    d = root / zone
    d.mkdir(parents=True, exist_ok=True)
    ds = gdal.GetDriverByName('GTiff').Create(str(d / f'dem-{zone}.tif'), 120, 120, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((126.0, step, 0.0, -23.0, 0.0, -step))
    ds.SetProjection('EPSG:4326')
    ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
    ds.FlushCache()


@pytest.fixture
def w(window, tmp_path):
    served = tmp_path / 'served'
    publish(served)
    window.published.url = 'file://' + str(served) + '/{zone}/dem-{zone}.tif'
    window.published.cache = tmp_path / 'cache'
    window.published.runner = lambda job: job.run()
    window._difference_runner = lambda job: job.run()
    window.surface.set_runner(None)                   # composed where asked, to read back
    window.surface.set_shaded(rising_north())
    window.surface.set_preview(False)
    window.map.set_zoom(9)
    window.map.center_on_lonlat(126.5, -23.7)
    return window


def reading(w, lon, lat):
    w._cursor(lon, lat)
    return w._status.text()


def test_nothing_is_fetched_until_the_difference_is_shown(w):
    w.surface_panel.mode.setCurrentText('slope')
    assert not (w.published.cache / 'pizarrales').exists()
    assert w.surface.shaded.difference is None


def test_shown_it_is_the_exact_build_less_the_published_dem(w):
    w.surface_panel.mode.setCurrentText('difference')
    s = w.surface.shaded
    assert s.difference is not None and s.difference_span == D.SPAN_MIN_M * 2
    assert 'changed +10.0 m' in reading(w, 126.8, -23.7)
    assert 'unchanged' in reading(w, 126.2, -23.7)
    assert 'not published' in reading(w, 127.02, -23.5), 'past the published extent'
    assert 'the published pizarrales DEM of' in w.statusBar().currentMessage()
    rgba, stretch = _composed_now(s, w.surface.style)
    x, y = m.lonlat_to_scene(126.8, -23.7)
    left, top, right, bottom = s.scene_rect
    r = int((y - top) / (bottom - top) * s.dem.shape[0])
    east = int((x - left) / (right - left) * s.dem.shape[1])
    west = int((m.lonlat_to_scene(126.2, -23.7)[0] - left) / (right - left) * s.dem.shape[1])
    assert rgba[r, east, 3] == 255 and rgba[r, east, 0] > rgba[r, east, 2] + 50, 'raised: red'
    assert rgba[r, west, 3] == 0, 'unchanged: clear, the map through it'
    assert stretch == (-10.0, 10.0)


def test_the_legend_reads_the_span_either_side_and_does_not_pinch(w):
    w.surface_panel.mode.setCurrentText('difference')
    lg = w.legend
    assert lg.isVisible() and lg.land == (-10.0, 10.0) and lg.fixed
    up, down = lg.colours([9.0, -9.0])
    assert up[0] > up[2] and down[2] > down[0]
    assert not lg.press(lg.bar_rect().center(), Qt.MouseButton.LeftButton), 'a press on the bar pinched'
    assert w.surface_panel.scaling.currentText() != 'pinch'
    assert not w.surface_panel.ramp.isEnabled() and not w.surface_panel.scaling.isEnabled()


def test_a_preview_leaves_the_exact_difference_as_it_was(w):
    w.surface_panel.mode.setCurrentText('difference')
    before = w.surface.shaded.difference.copy()
    w.surface.shaded.dem[100:110, 100:110] += 50           # a preview's patch
    assert w.surface.recolour_box(100, 100, 10, 10)
    w._surface_previewed([(100, 100, 10, 10)], 0.05)
    assert np.array_equal(w.surface.shaded.difference, before, equal_nan=True)


def test_a_new_build_has_its_own_difference_worked_out(w):
    w.surface_panel.mode.setCurrentText('difference')
    w._surface_built_shown(Built(rising_north(raise_m=3.0)))
    assert w.surface.shaded.difference is not None
    assert 'changed +13.0 m' in reading(w, 126.8, -23.7)
    assert 'changed +3.0 m' in reading(w, 126.2, -23.7)


def test_a_zone_with_nothing_published_says_so(w, tmp_path):
    w.published.url = 'file://' + str(tmp_path / 'nowhere') + '/{zone}/dem-{zone}.tif'
    w.surface_panel.mode.setCurrentText('difference')
    assert 'could not be fetched' in w.statusBar().currentMessage()
    assert w.surface.shaded.difference is None and not w.legend.isVisible()


def test_the_profile_is_filled_with_the_difference_along_it(w):
    from tests.ui.test_measure import click, double_click
    w.surface_panel.mode.setCurrentText('difference')
    w.edit_actions['tool.measure'].trigger()
    click(w, 126.3, -23.7)
    double_click(w, 126.7, -23.7)
    got = w.profile_dock.plot.colourer(w.measure.result)
    first, last = got[0], got[-1]
    assert tuple(first[:3]) == tuple(D.DIFF_RAMP.colours[2][:3]), 'unchanged in the west: the ramp\'s middle'
    assert last[0] > last[2] + 50, 'raised in the east: red'
