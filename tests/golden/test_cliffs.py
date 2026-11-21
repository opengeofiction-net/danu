"""A cliff with its top and its height - #191.

A cliff drawn west to east along the middle of the square, so the ground below
is on its right, to the south: its top at 300 m and 100 m high. Contours at
310 m to the north and 190 m to the south. The top edge burns at 300 as the
contour its ele makes it; the foot, a cell and a half to the south, at 200.
"""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5


def a_cliff(tags=None):
    from danu.core import edits
    from danu.core.square import Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def way(pts, t):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids, pts, t).apply(sq)
        return wid

    for dlat, ele in ((0.03, 310), (-0.03, 190)):
        way([(125.1 + 0.016 * i, LAT + dlat) for i in range(51)], {'ele': str(ele)})
    wid = way([(125.3 + 0.01 * i, LAT) for i in range(41)],
              tags if tags is not None else {'natural': 'cliff', 'ele': '300', 'height': '100'})
    return sq, wid


def built(sq, tmp_path, name='b'):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(sq, zone / 'S24E125.osm.xz')
    lines = []
    r = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), log=lines.append)
    assert r.dem is not None
    return r, lines


def read(path):
    ds = gdal.Open(str(path))
    a = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    del ds
    return a, gt


def test_a_cliff_drops_its_height_to_its_right(tmp_path):
    """Across the cliff, north to south: 300 m at the top edge, 200 m two
    cells below it, and nothing in between but the drop."""
    r, log = built(a_cliff()[0], tmp_path)
    dem, gt = read(r.dem)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    col = dem[y - 3:y + 4, x]
    assert col[3] == pytest.approx(300, abs=0.5), col
    assert col[5] == pytest.approx(200, abs=0.5), col
    assert col[2] >= 300 and col[6] <= 200, f'the ground either side runs the wrong way: {col}'
    assert any('1 cliffs, walls the fill does not cross; 1 with a top and a height' in line for line in log)


def test_a_cliff_with_no_height_has_no_foot(tmp_path):
    """Without its height there is nothing to burn beside it: its top is the
    contour its ele makes it, and that is all."""
    r, log = built(a_cliff({'natural': 'cliff', 'ele': '300'})[0], tmp_path)
    dem, gt = read(r.dem)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    assert dem[y, x] == pytest.approx(300, abs=0.5)
    assert dem[y + 2, x] > 250, 'a foot was burned with no height to burn it at'
    assert not any('cliffs with a top and a height' in line for line in log)


def test_the_preview_burns_what_the_build_burned(tmp_path):
    """``Contours.burn`` over the whole raster and over a box across the
    cliff is the build's constraints, cell for cell (R35) - the foot made
    for the grid it is burned on, and found from a cliff outside the box."""
    import numpy as np

    from danu.surface.local import Box
    from danu.surface.preview import Contours
    r, _ = built(a_cliff()[0], tmp_path)
    cons, gt = read(r.constraints)
    ds = gdal.Open(str(r.constraints))
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    del ds
    c = Contours(r.contours_gpkg)
    rows, cols = cons.shape
    assert np.array_equal(c.burn(gt, Box(0, 0, cols - 1, rows - 1), nodata), cons)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    for box in (Box(x - 20, y - 20, x + 20, y + 20), Box(x - 20, y + 1, x + 20, y + 20)):
        assert np.array_equal(c.burn(gt, box, nodata), cons[box.slice])


def test_the_preview_follows_a_cliff_edited(tmp_path):
    """A cliff given a new height in the editor: its foot burned at the new
    level; its height taken off: no foot."""
    from danu.surface.local import Box
    from danu.surface.preview import Contours
    sq, wid = a_cliff()
    r, _ = built(sq, tmp_path)
    cons, gt = read(r.constraints)
    c = Contours(r.contours_gpkg)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    box = Box(x - 5, y - 5, x + 5, y + 5)
    pts = sq.coords(sq.ways[wid])
    c.apply_cliff('S24E125', wid, pts, 260.0)
    assert c.burn(gt, box, -9999)[7, 5] == 260
    c.apply_cliff('S24E125', wid, pts, None, is_cliff=False)
    assert c.cliff_of('S24E125', wid) is None
    assert c.burn(gt, box, -9999)[7, 5] == -9999


def a_drop(cliff=True):
    """Contours at 300 m to the north and 200 m to the south, in reach of
    each other, and a cliff with no heights at all between them along LAT -
    or the same way not a cliff."""
    from danu.core import edits
    from danu.core.square import Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def way(pts, t):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids, pts, t).apply(sq)
        return wid

    for dlat, ele in ((0.012, 300), (-0.012, 200)):
        way([(125.1 + 0.016 * i, LAT + dlat) for i in range(51)], {'ele': str(ele)})
    wid = way([(125.05 + 0.01 * i, LAT) for i in range(91)], {'natural': 'cliff'} if cliff else {'fixme': 'x'})
    return sq, wid


def test_a_cliff_with_no_heights_is_a_wall_each_side_filled_from_its_own(tmp_path):
    """isofill 0.16's wall: without the cliff the ground ramps from 300 to
    200 m across it; with it, each side is filled from its own contour and
    the drop is at the cliff - all but the whole 100 m within a cell or two.
    Not quite level with each contour: the cliff stops short of the raster's
    edge, and the two sides meet round its ends."""
    import numpy as np
    r, log = built(a_drop()[0], tmp_path, 'cliff')
    plain, _ = built(a_drop(cliff=False)[0], tmp_path, 'plain')
    dem, gt = read(r.dem)
    ramp, _ = read(plain.dem)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    assert 220 < ramp[y - 4, x] < 290 and 210 < ramp[y + 4, x] < 280, 'no ramp without the cliff: this tests nothing'
    col = dem[y - 6:y + 7, x]
    assert 290 < dem[y - 4, x] <= 300 and 200 <= dem[y + 4, x] < 210, col
    assert np.abs(np.diff(col)).max() > 80, f'no drop at the cliff: {col}'
    assert dem[y, x] > 290, 'the cliff is not at the top of its drop'
    assert r.wall is not None and plain.wall is None
    assert any('1 cliffs, walls the fill does not cross' in line for line in log)


def test_the_preview_burns_the_wall_the_build_burned(tmp_path):
    """``Contours.burn_wall`` over the whole raster and over a box is
    ``rasterise_wall``'s raster, cell for cell; a box with no cliff, None."""
    import numpy as np

    from danu.surface.local import Box
    from danu.surface.preview import Contours
    r, _ = built(a_drop()[0], tmp_path)
    w, gt = read(r.wall)
    c = Contours(r.contours_gpkg)
    rows, cols = w.shape
    assert np.array_equal(c.burn_wall(gt, Box(0, 0, cols - 1, rows - 1)), w)
    y = int((LAT - gt[3]) / gt[5])
    box = Box(cols // 3, y - 10, cols // 2, y + 10)
    assert np.array_equal(c.burn_wall(gt, box), w[box.slice])
    assert c.burn_wall(gt, Box(0, 0, 20, 20)) is None


def test_a_box_solved_in_the_editor_keeps_the_wall_as_the_build_does(tmp_path):
    """The editor's box solve, the passes apart, with the wall: near the whole
    build's answer across the cliff - a few metres off, the two sides meeting
    round the cliff's far ends, which a box cannot see; the rebuild on idle
    settles it. Without the wall the box ramps across, tens of metres out."""
    import numpy as np

    from danu.surface import local
    from danu.surface import params as sp
    r, _ = built(a_drop()[0], tmp_path)
    params = sp.load().with_arcsec(3)
    cons, gt = read(r.constraints)
    mask, _ = read(r.drawn_mask)
    surface, _ = read(r.surface)
    w, _ = read(r.wall)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    box = local.Box(x - 3, y - 3, x + 3, y + 3)
    walled, good = local.resolve(cons.astype(np.float32), mask, None, surface, box, params,
                                 nodata=-9999.0, wall=w)
    bare, _ = local.resolve(cons.astype(np.float32), mask, None, surface, box, params, nodata=-9999.0)
    band = slice(y - good.y0 - 8, y - good.y0 + 9)
    exact = surface[good.slice]
    off, bare_off = np.abs(walled - exact)[band].max(), np.abs(bare - exact)[band].max()
    assert bare_off > 20 and off < bare_off / 4, (off, bare_off)
