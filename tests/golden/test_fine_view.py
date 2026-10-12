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

    def fresh():
        return fine.Fine(fine.Grid.of(g1), fine.Grid.of(r3.grid), Contours(r3.contours_gpkg),
                         Band.open(r3.surface, np.float32), Band.open(r3.dem, np.float32),
                         fine_params, gpkg=r3.contours_gpkg)
    view = fresh()

    def read(path):
        ds = gdal.Open(str(path))            # held: the band dies with it
        return ds.GetRasterBand(1).ReadAsArray()

    return {'view': view, 'fresh': fresh, 'r3': r3, 'zone': zone, 'params': fine_params,
            'dem': read(r1.dem).astype(np.float64),
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
    outer = good.grown(params.fill_cells, shape)
    p = fine.Prepared(view, good, outer,
                      np.full(outer.shape, NODATA, np.float32), np.ones(outer.shape, np.uint8),
                      np.zeros(good.shape, np.float32), np.ones(good.shape, bool),
                      water, np.full(good.shape, rim, np.float32), np.full(good.shape, sea))
    solved = fine.solve(p, shape, params)
    return solved.dem, solved.surface


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
    good = view.grown(round(fine.MARGIN * params.fill_cells), (800, 800))
    water = np.zeros(good.shape, np.uint8)
    water[370 - good.y0:400 - good.y0, 370 - good.x0:400 - good.x0] = 1
    dem, _ = held((800, 800), view, rim=0.2, water=water)
    assert (dem[:30, :30] == 0).all()
    assert (dem[31:, 31:] == 1).all(), 'low ground the coarse DEM does not call sea is land'
    dem, _ = held((800, 800), view, rim=0.2, sea=True)
    assert (dem == 0).all(), 'and low ground it does call sea is sea'


def test_the_first_pass_kept_by_tile_is_the_whole_rasters_to_the_bit(both, tmp_path):
    """What makes keeping it worth anything: a tile searched for one view is
    the answer for the next, because the first pass depends on the contours
    alone. Every tile kept after a run of views is the whole raster's first
    pass, exactly - including those searched beside a tile already kept."""
    import numpy as np

    from danu.surface import NODATA, isofill_lib
    from danu.surface.local import Box

    f = both['view']
    whole, _ = isofill_lib.Isofill.load().run(both['constraints'].astype(np.float32), f.params,
                                              mask=both['mask'], nodata=NODATA, pass2=False)
    kept = [(k, v[0]) for (kind, k), v in f._kept.items() if kind == 'first']
    if not kept:
        # the views test runs first in the module; on its own, make some
        rows, cols = f.fine.shape
        f.view(Box(100, 2100, 349, 2249))
        f.view(Box(300, 2150, 549, 2299))
        kept = [(k, v[0]) for (kind, k), v in f._kept.items() if kind == 'first']
    assert len(kept) > 20
    for k, a in kept:
        assert np.array_equal(a, whole[f.tile(k).slice]), k


def test_a_view_panned_a_little_at_a_time_stays_within_a_metre(both):
    """What answering in tiles adds: a pan leaves most of the view kept and
    solves a strip of tiles beside it, with a rim of its own. Walked across
    the drawn ground and back, a few dozen cells a step, every view is checked
    against the whole build - the strips at the raster's edge included, where
    a rim held short of it once put a column 66 m out."""
    import numpy as np

    from danu.surface.local import Box

    f = both['fresh']()
    rows, cols = f.fine.shape
    worst_fill = worst_dem = 0.0
    for start, step in (((2240, 0), (-9, 23)), ((130, 60), (11, 31)), ((40, 330), (17, -19))):
        cy, cx = start
        for _ in range(16):
            cy = min(max(cy + step[0], 75), rows - 76)
            cx = min(max(cx + step[1], 125), cols - 126)
            v = Box(cx - 125, cy - 75, cx + 124, cy + 74)
            dem, surface = f.view(v)
            worst_fill = max(worst_fill, float(np.abs(surface - both['surface'][v.slice]).max()))
            worst_dem = max(worst_dem, float(np.abs(dem - both['dem'][v.slice]).max()))
    assert worst_fill < 0.01, f'the fill is {worst_fill:.3f} m from the whole build'
    assert worst_dem <= 1.0, f'the DEM is {worst_dem:.3f} m from the whole build'


def test_a_view_smaller_than_a_z15_screen_is_still_within_a_metre(both):
    """Zoomed in, a screen is a few dozen cells - and solved as itself it is
    the shape the margin fails on: 64 cells wide near the square's western
    edge, two views of 44 were 56 m out. Solved as 256 cells around it, none
    are, and nor is a z20 screen of eight by four."""
    import numpy as np

    from danu.surface.local import Box

    worst = 0.0
    for x0 in (176, 208, 240, 272, 304, 320):
        for y0 in (256, 300, 2100, 2200):
            for v in (Box(x0, y0, x0 + 63, y0 + 149), Box(x0, y0, x0 + 7, y0 + 3)):
                f = both['fresh']()
                _, surface = f.view(v)
                worst = max(worst, float(np.abs(surface - both['surface'][v.slice]).max()))
    assert worst < 0.01, f'the fill is {worst:.3f} m from the whole build'


def test_a_solves_shading_is_cut_into_pieces_that_tile_it(both):
    """Every Mercator cell of the view's shading goes to one tile and one
    only, so pieces drawn side by side neither overlap nor leave a gap - and
    pieces of every solve are on one grid, so two solves' meet on whole
    cells."""
    from danu.surface import fine, shade
    from danu.surface.local import Box

    f = both['fresh']()
    wkt = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
           'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]')
    for view in (Box(100, 2100, 349, 2249), Box(160, 2140, 409, 2289)):
        p = f.plan(view)
        solved = fine.solve(p, f.fine.shape, f.params)
        got = fine.pieces(p, solved, f.fine.gt, wkt, f.params)
        assert set(got) == set(f.tiles(p.view))
        metres = shade.fine_metres(f.params)
        cells = set()
        for piece in got.values():
            assert piece.metres == metres
            c0 = round((piece.geotransform[0] + shade.HALF) / metres)
            r0 = round((shade.HALF - piece.geotransform[3]) / metres)
            assert abs(c0 * metres - shade.HALF - piece.geotransform[0]) < 1e-6, 'off the one grid'
            rows, cols = piece.dem.shape
            mine = {(r, c) for r in range(r0, r0 + rows) for c in range(c0, c0 + cols)}
            assert not cells & mine, 'two pieces claim one cell'
            cells |= mine
        rs = [r for r, _ in cells]
        cs = [c for _, c in cells]
        assert len(cells) == (max(rs) - min(rs) + 1) * (max(cs) - min(cs) + 1), 'a gap between pieces'
        f.take(p, solved, got)



def test_an_edit_drops_the_tiles_it_reaches_and_keeps_the_rest(both, tmp_path):
    """I4: a contour deleted, the 3 arcsecond preview patched as the editor
    patches it, and the 1 arcsecond tiles it reached dropped. Every tile kept
    is still the whole 1 arcsecond build's answer after the deletion, and the
    views solved again are within a metre of it.

    The contour is way -75409002, at 149 m, which no other contour
    duplicates: of sixteen taken from this square, it was the one whose
    deletion moved the ground at all, by 149 m. Measured on gobras City over
    six deletions and six drags, tiles kept are within 4 mm, at any reach;
    this square needed one radius beyond the patch - 1.6 cm at none."""
    import collections
    import shutil
    from pathlib import Path

    import numpy as np

    from danu.core import edits
    from danu.core.square import read_square, write_square
    from danu.surface import build, fine, local, preview

    r3, coarse_params = both['r3'], lock_params()
    square = read_square(both['zone'] / SQUARE.name)
    victim = square.ways[-75409002]
    assert victim.ele == 149.0
    pts = [(square.nodes[r].lon, square.nodes[r].lat) for r in victim.refs]
    history = edits.SetUndoStack()
    history.do(square, edits.DeleteWay(victim.id))
    after = tmp_path / 'after'
    after.mkdir()
    write_square(square, after / 'S24E125.osm.xz')
    r1a = build.build_dem(after, tmp_path / 'wa', both['params'])

    def read(path):
        ds = gdal.Open(str(path))
        return ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    fill_after, dem_after = read(r1a.surface), read(r1a.dem)

    def own(path):
        dst = tmp_path / 'own' / Path(path).name
        dst.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, dst)
        return dst
    layer = preview.Contours(r3.contours_gpkg)
    ds = gdal.Open(str(r3.dem))
    gt = ds.GetGeoTransform()
    ds = None
    kept = preview.Kept(constraints=preview.Band.open(r3.constraints, np.float32),
                        mask=preview.Band.open(r3.drawn_mask), water=None,
                        surface=preview.Band.open(own(r3.surface), np.float32, update=True),
                        geotransform=gt, nodata=-9999, contours=layer,
                        dem=preview.Band.open(own(r3.dem), np.float32, update=True))
    g1 = build.Grid(r3.grid.west, r3.grid.east, r3.grid.south, r3.grid.north, 1.0)
    f = fine.Fine(fine.Grid.of(g1), fine.Grid.of(r3.grid), layer, kept.surface, kept.dem,
                  both['params'], gpkg=r3.contours_gpkg)

    box = local.Box.around([int((lat - gt[3]) / gt[5]) for _, lat in pts],
                           [int((lon - gt[0]) / gt[1]) for lon, _ in pts])
    centre = f.fine_box(box)
    rows, cols = f.fine.shape
    views = []
    for dy in (-450, -150, 150, 450):
        for dx in (-500, 0, 500):
            y = min(max((centre.y0 + centre.y1) // 2 + dy, 75), rows - 76)
            x = min(max((centre.x0 + centre.x1) // 2 + dx, 125), cols - 126)
            views.append(local.Box(x - 125, y - 75, x + 124, y + 74))
    for v in views:
        f.view(v)
    before = collections.OrderedDict(f._kept)

    # the edit, as the editor makes it
    assert layer.remove(victim.id)
    patch, good = preview.patch(kept, box, coarse_params, removing=True)
    kept.surface.write(good, patch)
    win = good.grown(coarse_params.smooth_cells + 4, kept.shape)
    kept.dem.write(win, preview.clamp_patch(kept.surface.read(win), layer.burn(gt, win, -9999),
                                            kept.dem.read(win)))

    def worst_kept():
        return max(float(np.abs(v[0][1] - fill_after[f.tile(k).slice]).max())
                   for (kind, k), v in f._kept.items() if kind == 'dem')
    assert worst_kept() > 1.0, 'kept whole, some tile is out of date - or this edit tests nothing'
    dropped = f.drop(good)
    assert dropped and len(dropped) < len([1 for kind, _ in before if kind == 'dem']), \
        'it dropped nothing, or everything'
    assert worst_kept() < 0.01, f'a tile kept is {worst_kept():.3f} m from the build after the edit'
    for v in views:
        dem, surface = f.view(v)
        assert float(np.abs(surface - fill_after[v.slice]).max()) < 0.01
        assert float(np.abs(dem - dem_after[v.slice]).max()) <= 1.0
