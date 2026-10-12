"""A 1 arcsecond view of a working set built at 3, against a whole 1 arcsecond
build of it - phase 7's measure for I3.

The view is solved from the 3 arcsecond build and the contours alone: burned,
masked and given its sea for the window, its first pass searched over the view
grown by two and a half radii, its second held at its rim on the 3 arcsecond
surface. The whole build is what the server would publish at 1 arcsecond, and
the phase ends when a view is within a metre of it.

Fifty views the size of a z15 screen, each centred on a cell of drawn ground -
the square is 1% drawn, so views placed evenly would compare empty ground with
empty ground and pass however wrong the solve was.
"""

import shutil
import tomllib
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def lock_params():
    from danu.surface import params
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    return params.load().with_arcsec(lock['arcsec'])


@pytest.fixture(scope='module')
def both(tmp_path_factory):
    """The square built whole at 3 arcseconds and at 1, and the view solver
    over the first."""
    import numpy as np

    from danu.surface import build, fine
    from danu.surface.preview import Band, Contours

    tmp = tmp_path_factory.mktemp('fine')
    zone = tmp / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    coarse_params = lock_params()
    assert coarse_params.arcsec == 3, 'the comparison is a 3 arcsecond build against a 1'
    fine_params = coarse_params.with_arcsec(1)
    r3 = build.build_dem(zone, tmp / 'w3', coarse_params)
    r1 = build.build_dem(zone, tmp / 'w1', fine_params)
    g1 = build.Grid(r3.grid.west, r3.grid.east, r3.grid.south, r3.grid.north, 1.0)
    view = fine.Fine(fine.Grid.of(g1), fine.Grid.of(r3.grid), Contours(r3.contours_gpkg),
                     Band.open(r3.surface, np.float32), Band.open(r3.dem, np.float32),
                     fine_params, gpkg=r3.contours_gpkg)

    def read(path):
        ds = gdal.Open(str(path))            # held: the band dies with it
        return ds.GetRasterBand(1).ReadAsArray()

    return {'view': view, 'dem': read(r1.dem).astype(np.float64),
            'surface': read(r1.surface).astype(np.float64),
            'mask': read(r1.drawn_mask), 'constraints': read(r1.constraints)}


def test_the_views_inputs_are_the_whole_builds(both):
    """The burn and the drawn area, taken a window at a time, are what the
    whole build rasterised - cell for cell. Everything else rests on this."""
    import numpy as np

    from danu.surface import NODATA
    from danu.surface.local import Box

    f = both['view']
    assert f.fine.shape == both['dem'].shape
    rows, cols = f.fine.shape
    whole = Box(0, 0, cols - 1, rows - 1)
    assert both['mask'].any()
    assert np.array_equal(f.mask(whole), both['mask'])
    assert np.array_equal(f.contours.burn(f.fine.gt, whole, NODATA), both['constraints'])
    # and a window of each is the window of the whole
    box = Box(100, 1900, 899, 2599)
    assert np.array_equal(f.mask(box), both['mask'][box.slice])


def test_a_view_is_within_a_metre_of_the_whole_1_arcsecond_build(both):
    """The phase's measure. Fifty z15 screens on drawn ground.

    The fill is within 2 mm on every one. The DEM is within a metre, and the
    metre is the clamp: whether low ground is sea is decided over the whole
    raster, so the view reads it off the 3 arcsecond DEM, and where the two
    grids decide a cell differently it is sea in one and the lowest land, 1 m,
    in the other."""
    import numpy as np

    from danu.surface.local import Box

    f = both['view']
    rows, cols = f.fine.shape
    ly, lx = np.nonzero(both['dem'] > 0)
    worst_fill = worst_dem = 0.0
    for i in np.random.default_rng(1).choice(len(ly), 50, replace=False):
        cy, cx = int(ly[i]), int(lx[i])
        v = Box(max(0, cx - 125), max(0, cy - 75), min(cols - 1, cx + 124), min(rows - 1, cy + 74))
        dem, surface = f.view(v)
        worst_fill = max(worst_fill, float(np.abs(surface - both['surface'][v.slice]).max()))
        worst_dem = max(worst_dem, float(np.abs(dem - both['dem'][v.slice]).max()))
    assert worst_fill < 0.01, f'the fill is {worst_fill:.3f} m from the whole build'
    assert worst_dem <= 1.0, f'the DEM is {worst_dem:.3f} m from the whole build'


def held(shape, view, rim=50.0, water=None, sea=False):
    """A view over ground with no contour in it, its rim at ``rim``."""
    import numpy as np

    from danu.surface import NODATA, fine

    params = lock_params().with_arcsec(1)
    good = view.grown(round(fine.MARGIN * params.fill_cells), shape)
    grown = good.grown(params.fill_cells, shape)
    p = fine.Prepared(view, good, grown,
                      np.full(grown.shape, NODATA, np.float32), np.ones(grown.shape, np.uint8),
                      water, np.full(good.shape, rim, np.float32), np.full(good.shape, sea))
    return fine.solve(p, shape, params)


def test_ground_inside_the_rim_is_held_at_it():
    """Nothing in the box answers the first pass, so everything in it is
    the rim's: held on all four sides, it is the rim's height throughout."""
    import numpy as np

    from danu.surface.local import Box

    dem, surface = held((800, 800), Box(370, 370, 429, 429))
    assert np.allclose(surface, 50.0, atol=0.01)
    assert np.allclose(dem, 50.0, atol=0.01)


def test_a_rim_on_the_rasters_own_edge_is_not_held():
    """Where the box runs into the raster's edge there is nothing beyond it to
    hold, and the ground out of reach there is void, as the whole build has
    it: zero, and then the lowest land."""
    import numpy as np

    from danu.surface.local import Box

    dem, surface = held((800, 800), Box(370, 10, 429, 69))
    assert np.allclose(surface, 0.0)
    assert np.allclose(dem, 1.0)


def test_water_is_sea_and_the_coarse_sea_takes_only_low_ground():
    """The window's water reads zero; the 3 arcsecond DEM's sea takes ground
    the fill left under half a metre and no other."""
    import numpy as np

    from danu.surface import fine
    from danu.surface.local import Box

    view = Box(370, 370, 429, 429)
    dem, _ = held((800, 800), view, sea=True)
    assert np.allclose(dem, 50.0, atol=0.01), 'held at 50 m is not sea, whatever the coarse DEM says'
    params = lock_params().with_arcsec(1)
    grown = view.grown(round(fine.MARGIN * params.fill_cells), (800, 800)).grown(params.fill_cells, (800, 800))
    water = np.zeros(grown.shape, np.uint8)
    water[370 - grown.y0:400 - grown.y0, 370 - grown.x0:400 - grown.x0] = 1
    dem, _ = held((800, 800), view, rim=0.2, water=water)
    assert (dem[:30, :30] == 0).all()
    assert (dem[31:, 31:] == 1).all(), 'low ground the coarse DEM does not call sea is land'
    dem, _ = held((800, 800), view, rim=0.2, sea=True)
    assert (dem == 0).all(), 'and low ground it does call sea is sea'
