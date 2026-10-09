"""What only a built surface can say - H2: rivers which climb on the DEM
(R29), sea level off the drawn coastline (R32), and unreached ground (R20).
On grids made here; GDAL for the sea level's zero line."""

import numpy as np
import pytest

from danu.checks import surface
from danu.core.square import SquareName

A = SquareName(125, -23)
RES = 1 / 1200                                      # 3 arcseconds
GT = (125.0, RES, 0.0, -22.0, 0.0, -RES)            # the square, north-west corner first


def snap(waterways=(), zero=(), shore=()):
    return surface.Snapshot(waterways=list(waterways), zero=np.array(zero, float).reshape(-1, 2),
                            shore=set(shore), squares=[A])


def river(wid, pts, name='Bass River', kind='river'):
    return (A, wid, name, kind, np.array(pts, float))


def a_hill_across(rows=1200, cols=1200, peak=150.0):
    """Ground at 100 m, a ridge running north-south at lon 125.5 rising to
    ``peak``: anything flowing east to west crosses it."""
    lon = GT[0] + (np.arange(cols) + 0.5) * RES
    ridge = np.maximum(0.0, 1 - np.abs(lon - 125.5) / 0.05) * (peak - 100)
    return np.tile(100 + ridge, (rows, 1))


def test_a_river_over_a_ridge_climbs_what_it_cannot_lose():
    dem = a_hill_across()
    found = surface.climbs(snap([river(7, [(125.4, -22.5), (125.6, -22.5)])]), dem, GT)
    (f,) = found
    assert f.kind == 'climb' and f.way == 7
    assert f.describe().startswith('river "Bass River", way 7 - climbs 50 m it cannot lose')
    assert 125.45 <= f.lon <= 125.55, 'the place is not the climb'


def test_a_river_down_a_slope_or_with_a_bump_under_ten_metres_is_not_listed():
    dem = a_hill_across(peak=105)
    lon = GT[0] + (np.arange(1200) + 0.5) * RES
    dem += np.tile(-(lon - 125) * 100, (1200, 1))                  # falling east, 100 m a degree
    assert surface.climbs(snap([river(8, [(125.1, -22.5), (125.4, -22.5)])]), dem, GT) == []  # straight down
    assert surface.climbs(snap([river(9, [(125.4, -22.5), (125.45, -22.5)])]), dem, GT) == []


def test_one_that_climbs_all_the_way_is_said_to_be_drawn_backwards():
    lon = GT[0] + (np.arange(1200) + 0.5) * RES
    dem = np.tile(100 + (lon - 125) * 100, (1200, 1))               # rising east
    (f,) = surface.climbs(snap([river(10, [(125.1, -22.5), (125.5, -22.5)])]), dem, GT)
    assert f.kind == 'backwards' and 'climbs 40 m, falls 0 m' in f.describe()


def test_unreached_ground_is_a_row_a_square_with_its_share():
    from danu.surface.build import ANSWERED, OUTSIDE, UNREACHED
    classes = np.full((1200, 1200), ANSWERED, np.uint8)
    classes[:, :600] = OUTSIDE                                       # half the square undrawn
    classes[:120, 600:] = UNREACHED                                  # a tenth of the drawn half
    (f,) = surface.unreached(snap(), classes, GT)
    assert f.square == A and f.kind == 'unreached' and '10.0% of the drawn area' in f.describe()
    assert surface.unreached(snap(), np.full((1200, 1200), ANSWERED, np.uint8), GT) == []


gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')


def dem_file(tmp_path, dem):
    path = tmp_path / 'dem.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(path), dem.shape[1], dem.shape[0], 1, gdal.GDT_Float32)
    ds.SetGeoTransform(GT)
    ds.GetRasterBand(1).WriteArray(dem.astype(np.float32))
    ds = None
    return path


def two_islands():
    """Sea at 0, two islands at 5 m: one with its coastline drawn, one
    with none."""
    dem = np.zeros((1200, 1200))
    yy, xx = np.mgrid[0:1200, 0:1200]
    drawn = (xx - 300) ** 2 + (yy - 600) ** 2 < 150 ** 2
    bare = (xx - 900) ** 2 + (yy - 600) ** 2 < 150 ** 2
    dem[drawn | bare] = 5.0
    t = np.linspace(0, 2 * np.pi, 400)
    lon0, lat0 = GT[0] + 300.5 * RES, GT[3] - 600.5 * RES
    shore = np.c_[lon0 + 150 * RES * np.cos(t), lat0 + 150 * RES * np.sin(t)]
    return dem, shore


def test_sea_level_round_an_island_with_no_coastline_is_found_and_one_drawn_is_not(tmp_path):
    dem, shore = two_islands()
    mask = np.ones(dem.shape, np.uint8)
    found = surface.sea_off_shore(snap(zero=shore, shore={(125, -23)}), dem_file(tmp_path, dem), mask, GT)
    (f,) = found
    assert f.kind == 'sea' and f.lon > 125.6, 'the drawn island taken for one with no shore'
    assert 'from a drawn shore' in f.describe()


def test_the_drawn_areas_own_edge_is_no_sea_level_and_an_inland_set_is_not_asked(tmp_path):
    """Outside the drawn area the surface is 0: the envelope's edge is a zero
    line, and on gobras two of them 184 and 114 km long said nothing."""
    dem = np.full((1200, 1200), 20.0)
    mask = np.zeros(dem.shape, np.uint8)
    mask[200:1000, 200:1000] = 1
    dem[mask == 0] = 0.0
    _, shore = two_islands()
    path = dem_file(tmp_path, dem)
    assert surface.sea_off_shore(snap(zero=shore, shore={(125, -23)}), path, mask, GT) == []
    assert surface.sea_off_shore(snap(), path, np.ones(dem.shape, np.uint8), GT) == []


def test_find_reads_a_builds_grids(tmp_path):
    dem, shore = two_islands()
    dem_file(tmp_path, dem)
    for name, arr in (('drawn-mask.tif', np.ones(dem.shape, np.uint8)),):
        ds = gdal.GetDriverByName('GTiff').Create(str(tmp_path / name), 1200, 1200, 1, gdal.GDT_Byte)
        ds.SetGeoTransform(GT)
        ds.GetRasterBand(1).WriteArray(arr)
        ds = None
    found = surface.find(snap(zero=shore, shore={(125, -23)}), tmp_path)
    assert [f.kind for f in found] == ['sea']


def test_worst_first():
    dem = a_hill_across()
    dem[600:, :] = a_hill_across(peak=300)[600:, :]                   # the ridge higher in the south
    found = surface.climbs(snap([river(1, [(125.4, -22.2), (125.6, -22.2)]),
                                 river(2, [(125.4, -22.8), (125.6, -22.8)])]), dem, GT)
    assert [f.way for f in found] == [2, 1]
