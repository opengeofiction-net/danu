"""The pieces of a 1 arcsecond view that are computed a window at a time, each
against what the whole raster gives."""

import math

import numpy as np
import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
ogr = pytest.importorskip('osgeo.ogr', reason='GDAL not available')

RES = 1 / 3600
GT = (125 - RES / 2, RES, 0.0, -23 + RES / 2, 0.0, -RES)
ROWS, COLS = 500, 600


def coastline(tmp_path):
    """A GeoPackage of coastline as the build collects it: an open way running
    edge to edge with the sea to its right, and an island ring wound
    counter-clockwise, land on the left."""
    path = tmp_path / 'contours.gpkg'
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    layer = ds.CreateLayer('contour', geom_type=ogr.wkbLineString)
    layer.CreateField(ogr.FieldDefn('natural', ogr.OFTString))
    layer.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))

    def add(points):
        line = ogr.Geometry(ogr.wkbLineString)
        for c, r in points:
            line.AddPoint_2D(GT[0] + c * GT[1], GT[3] + r * GT[5])
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField('natural', 'coastline')
        f.SetField('ele', 0.0)
        f.SetGeometry(line)
        layer.CreateFeature(f)

    # west to east, so the sea is to the south
    add([(c, 200 + 60 * math.sin(c / 45)) for c in range(-5, COLS + 6, 7)])
    # an island in the sea, counter-clockwise on the map: clockwise in rows
    add([(300 + 30 * math.cos(t / 10), 400 - 20 * math.sin(t / 10)) for t in range(0, 64)]
        + [(330, 400)])
    ds = None
    return path


def test_the_sea_a_window_at_a_time_is_the_whole_rasters(tmp_path):
    """``sea_window`` over any window - in the middle, against an edge, across
    the island - is the whole raster's ``sea_mask`` there, cell for cell."""
    from danu.surface import sea_mask

    gpkg = coastline(tmp_path)
    ref = tmp_path / 'ref.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(ref), COLS, ROWS, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(GT)
    ds = None
    out = tmp_path / 'sea.tif'
    assert sea_mask.sea_mask(str(gpkg), str(ref), str(out))
    ds = gdal.Open(str(out))
    whole = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    # the fixture has to have both answers in it, and the island
    assert 0.2 < whole.mean() < 0.8
    assert not whole[400, 300]

    seeds = sea_mask.coast_seeds(gpkg, GT)
    for x0, y0, w, h in ((250, 150, 120, 80), (0, 0, 90, 70), (COLS - 50, ROWS - 40, 50, 40),
                         (260, 360, 90, 80), (0, 0, COLS, ROWS)):
        got = sea_mask.sea_window(*seeds, x0, y0, w, h, (ROWS, COLS))
        assert np.array_equal(got, whole[y0:y0 + h, x0:x0 + w]), (x0, y0)
    # and small ones everywhere: a cell is decided by seeds up to MAX_CELLS
    # away, so a window's reach is only tested where that is past its edge
    for y0 in range(0, ROWS - 12, 23):
        for x0 in range(0, COLS - 12, 41):
            got = sea_mask.sea_window(*seeds, x0, y0, 12, 12, (ROWS, COLS))
            assert np.array_equal(got, whole[y0:y0 + 12, x0:x0 + 12]), (x0, y0)


def test_no_coastline_is_no_seeds(tmp_path):
    from danu.surface import sea_mask

    path = tmp_path / 'contours.gpkg'
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    layer = ds.CreateLayer('contour', geom_type=ogr.wkbLineString)
    layer.CreateField(ogr.FieldDefn('natural', ogr.OFTString))
    ds = None
    assert sea_mask.coast_seeds(path, GT) is None


def fine_over(coarse_array):
    from danu.surface import fine
    from danu.surface.params import load
    from danu.surface.preview import ArrayBand

    crows, ccols = coarse_array.shape
    c = fine.Grid((125 - 1.5 / 3600, 3 / 3600, 0.0, -23 + 1.5 / 3600, 0.0, -3 / 3600), crows, ccols)
    f = fine.Grid(GT, 3 * (crows - 1) + 1, 3 * (ccols - 1) + 1)
    band = ArrayBand(coarse_array)
    return fine.Fine(f, c, None, band, band, load().with_arcsec(1)), band


def test_the_coarse_surface_brought_up_is_bilinear_on_the_shared_centres():
    """A fine cell's centre is a coarse index over three, so a plane comes up
    as the same plane, exactly, and the nearest coarse cell is the one it
    rounds to."""
    from danu.surface.local import Box

    yy, xx = np.mgrid[0:40, 0:50]
    plane = (7.0 * yy - 3.0 * xx + 100).astype(np.float32)
    f, band = fine_over(plane)
    box = Box(20, 10, 130, 100)
    up = f.up(band, box)
    fy, fx = np.mgrid[box.y0:box.y1 + 1, box.x0:box.x1 + 1]
    assert np.allclose(up, 7.0 * fy / 3 - 3.0 * fx / 3 + 100, atol=1e-4)
    near = f.up(band, box, nearest=True)
    assert np.array_equal(near, plane[np.rint(fy / 3).astype(int), np.rint(fx / 3).astype(int)])


def test_bringing_up_reaches_the_last_coarse_row_and_column():
    """The fine grid's last cell sits on the coarse grid's last centre."""
    from danu.surface.local import Box

    plane = np.arange(12, dtype=np.float32).reshape(3, 4)
    f, band = fine_over(plane)
    rows, cols = f.fine.shape
    up = f.up(band, Box(0, 0, cols - 1, rows - 1))
    assert up[-1, -1] == plane[-1, -1] and up[0, 0] == plane[0, 0]


class Drawn:
    """A contour layer with one contour, a block of cells, and one spot height
    far outside it."""

    def burn(self, gt, box, nodata, spots=True):
        a = np.full(box.shape, nodata, np.int16)
        for (y0, y1, x0, x1), ele in (((1000, 1100, 2000, 2300), 100),) + (
                (((3000, 3001, 100, 101), 250),) if spots else ()):
            ys = slice(max(y0, box.y0) - box.y0, max(min(y1, box.y1 + 1) - box.y0, 0))
            xs = slice(max(x0, box.x0) - box.x0, max(min(x1, box.x1 + 1) - box.x0, 0))
            a[ys, xs] = ele
        return a


def drawn():
    from danu.surface import fine
    from danu.surface.params import load
    from danu.surface.preview import ArrayBand

    res = 1 / 3600
    g = fine.Grid((125 - res / 2, res, 0.0, -23 + res / 2, 0.0, -res), 3601, 3601)
    c = fine.Grid((125 - 1.5 * res, 3 * res, 0.0, -23 + 1.5 * res, 0.0, -3 * res), 1201, 1201)
    band = ArrayBand(np.zeros((1201, 1201), np.float32))
    return fine.Fine(g, c, Drawn(), band, band, load().with_arcsec(1))


def test_the_drawn_area_is_the_contours_envelope_and_not_the_spot_heights():
    """R21: a spot height constrains the ground inside the envelope and never
    widens it."""
    from danu.surface.local import Box

    f = drawn()
    whole = f.mask(Box(0, 0, 3600, 3600))
    assert whole.sum() == 100 * 300
    assert whole[1000:1100, 2000:2300].all()
    assert not whole[3000, 100]


def test_the_drawn_area_of_a_window_is_the_wholes():
    """Windows cutting the envelope on every side, and one inside it."""
    from danu.surface.local import Box

    f = drawn()
    whole = f.mask(Box(0, 0, 3600, 3600))
    for box in (Box(1900, 950, 2099, 1049), Box(2200, 1050, 2399, 1149), Box(2050, 1020, 2149, 1079),
                Box(2299, 1099, 2299, 1099), Box(2300, 1100, 2310, 1110)):
        assert np.array_equal(f.mask(box), whole[box.slice]), box


def test_grids_whose_centres_do_not_line_up_are_refused():
    """``up`` reads a coarse cell by a fine index over the ratio, which is
    right only if the two grids' first centres are the same point."""
    from danu.surface import fine
    from danu.surface.params import load
    from danu.surface.preview import ArrayBand

    band = ArrayBand(np.zeros((3, 4), np.float32))
    f = fine.Grid(GT, 7, 10)
    shifted = fine.Grid((125 + 1.5 / 3600, 3 / 3600, 0.0, -23 + 1.5 / 3600, 0.0, -3 / 3600), 3, 4)
    with pytest.raises(ValueError, match='apart'):
        fine.Fine(f, shifted, None, band, band, load().with_arcsec(1))
    north = fine.Grid((125 - 1.5 / 3600, 3 / 3600, 0.0, -23 - 1.5 / 3600, 0.0, -3 / 3600), 3, 4)
    with pytest.raises(ValueError, match='apart'):
        fine.Fine(f, north, None, band, band, load().with_arcsec(1))


def solved_as(p, value):
    """A Solved for ``p`` holding ``value`` everywhere, standing in for isofill."""
    from danu.surface import fine

    return fine.Solved(np.full(p.view.shape, value, np.float32), np.full(p.view.shape, value, np.float32),
                       np.full(p.good.shape, value, np.float32))


def test_a_view_is_answered_in_whole_tiles_searching_only_new_ground():
    from danu.surface import fine
    from danu.surface.local import Box

    f = drawn()
    view = Box(300, 300, 549, 449)                 # a z15 screen, across tile edges
    p = f.plan(view)
    T = fine.TILE
    solved = fine.at_least(view, fine.SMALLEST, f.fine.shape)   # 150 rows is under the smallest
    assert (p.view.x0, p.view.y0, p.view.x1 + 1, p.view.y1 + 1) == (
        solved.x0 // T * T, solved.y0 // T * T, (solved.x1 // T + 1) * T, (solved.y1 // T + 1) * T)
    assert p.todo.all(), 'nothing is kept yet'
    f.take(p, solved_as(p, 7))
    assert f.known(view) and f.plan(view) is None
    dem, surface = f.read(view)
    assert (dem == 7).all() and (surface == 7).all()
    # moved east by a tile and a bit: a column of tiles is new, and the view
    # is solved again whole - a strip on a rim of its own is not a shape the
    # margin holds for
    moved = Box(300 + T + 10, 300, 549 + T + 10, 449)
    p = f.plan(moved)
    assert (p.view.x0, p.view.x1 + 1) == (moved.x0 // T * T, (moved.x1 // T + 1) * T)
    # but the first pass it starts from is kept for every tile the last solve
    # searched whole, so only the rest is searched again
    assert not p.todo.all() and p.todo.any()
    assert (p.first[~p.todo] == 7).all()


def test_only_tiles_searched_whole_are_kept():
    """A tile the solve searched only part of - cut by the margin's edge - is
    not a first pass anyone can reuse."""
    from danu.surface.local import Box

    f = drawn()
    p = f.plan(Box(300, 300, 549, 449))
    f.take(p, solved_as(p, 1))
    good = p.good
    for (kind, k) in f._kept:
        if kind == 'first':
            t = f.tile(k)
            assert good.x0 <= t.x0 and t.x1 <= good.x1 and good.y0 <= t.y0 and t.y1 <= good.y1


def test_the_tiles_kept_stay_inside_the_budget_and_the_oldest_go_first():
    from danu.surface.local import Box

    f = drawn()
    first = Box(300, 300, 549, 449)
    p = f.plan(first)
    f.take(p, solved_as(p, 1))
    assert f.known(first)
    f.budget = 2 * f._held                   # room for about two views like it
    for i in range(1, 8):
        far = Box(300 + 400 * i, 1000 + 300 * i, 549 + 400 * i, 1149 + 300 * i)
        q = f.plan(far)
        if q is not None:
            f.take(q, solved_as(q, 2))
        f.read(far)
        assert f._held <= f.budget
    assert not f.known(first), 'the first view, never read again, has gone'
    assert f.known(far), 'and the last is kept'


def test_a_view_read_again_is_kept_over_one_not_looked_at():
    """Least recently used, not first in: the view a mapper keeps coming
    back to stays while the ones passed through go."""
    from danu.surface.local import Box

    f = drawn()
    home = Box(300, 300, 549, 449)
    p = f.plan(home)
    f.take(p, solved_as(p, 1))
    f.budget = 2 * f._held
    for i in range(1, 8):
        far = Box(300 + 400 * i, 1000 + 300 * i, 549 + 400 * i, 1149 + 300 * i)
        q = f.plan(far)
        f.take(q, solved_as(q, 2))
        assert f.read(home) is not None, f'home went at view {i}'


def test_the_tiles_at_the_grids_south_and_east_edges_are_cut_to_it():
    from danu.surface import fine
    from danu.surface.local import Box

    f = drawn()
    rows, cols = f.fine.shape
    T = fine.TILE
    last = f.tile(((rows - 1) // T, (cols - 1) // T))
    assert (last.y1, last.x1) == (rows - 1, cols - 1)
    corner = Box(cols - 250, rows - 150, cols - 1, rows - 1)
    p = f.plan(corner)
    assert (p.view.y1, p.view.x1) == (rows - 1, cols - 1)
    f.take(p, solved_as(p, 3))
    dem, _ = f.read(corner)
    assert dem.shape == corner.shape and (dem == 3).all()


def test_a_small_view_is_solved_as_the_smallest_view_around_it():
    from danu.surface import fine
    from danu.surface.local import Box

    S = fine.SMALLEST
    assert fine.at_least(Box(1000, 1000, 1007, 1003), S, (3601, 3601)) == Box(
        1003 - S // 2, 1001 - S // 2, 1003 - S // 2 + S - 1, 1001 - S // 2 + S - 1)
    # at the raster's edge it is pushed inside rather than cut
    assert fine.at_least(Box(0, 3597, 7, 3600), S, (3601, 3601)) == Box(0, 3601 - S, S - 1, 3600)
    # and one already as large is left as it is
    big = Box(10, 10, 10 + S, 10 + S + 40)
    assert fine.at_least(big, S, (3601, 3601)) == big


def test_an_edit_drops_the_first_pass_it_reaches_and_the_dem_a_radius_further():
    """Fine.drop: the 3 arcsecond box an edit was solved again over, as the
    1 arcsecond cells it covers; the first pass of every tile in it, and the
    DEM of every tile within a radius more. Nothing else."""
    from danu.surface import fine
    from danu.surface.local import Box

    f = drawn()
    T, R = fine.TILE, f.params.fill_cells
    for view in (Box(300, 300, 549, 449), Box(1300, 1300, 1549, 1449)):
        p = f.plan(view)
        f.take(p, solved_as(p, 1))
    firsts = {k for kind, k in f._kept if kind == 'first'}
    dems = {k for kind, k in f._kept if kind == 'dem'}
    coarse = Box(140, 130, 150, 136)                 # in the first view's ground
    box = f.fine_box(coarse)
    assert box == Box(140 * 3 - 1, 130 * 3 - 1, 150 * 3 + 1, 136 * 3 + 1)
    dropped = f.drop(coarse)
    reach = box.grown(R, f.fine.shape)
    gone_first = {k for k in firsts if ('first', k) not in f._kept}
    gone_dem = {k for k in dems if ('dem', k) not in f._kept}
    assert gone_first == firsts & set(f.tiles(box)) and gone_first
    assert gone_dem == dems & set(f.tiles(reach)) and set(dropped) == gone_dem
    assert gone_dem > (dems & set(f.tiles(box))), 'the DEM went no further than the first pass'
    assert all(('dem', k) in f._kept for k in f.tiles(Box(1300, 1300, 1549, 1449))), \
        'a view nowhere near the edit lost tiles'
    assert f.tiles(Box(0, 0, T - 1, T - 1)) == [(0, 0)]
