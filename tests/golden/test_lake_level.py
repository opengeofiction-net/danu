"""Lakes held at their level (#191): each body of water with a numeric
``ele`` of its own burned whole into the constraints at it, islands left out.

The shore alone does not hold a lake flat - isofill declines a cell that sees
one level all round, as it does a hilltop - and fill lines drawn across the
water did the job until now, only where a mapper had flattened. At 0 m they
also left rows the clamp lifted to 1 m, as it does a low island. The preview
burns the lakes as the build does, cell for cell (R35).
"""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5                      # the middle of square S24E125
LAKE, ISLAND = 0.2, 0.04                     # half-widths in degrees
FILL = 0.00108                               # 120 m apart, as flattening drew them


def box(r):
    return [(LON - r, LAT - r), (LON + r, LAT - r), (LON + r, LAT + r), (LON - r, LAT + r)]


def a_lake(level, contours, fill=False, shore=True):
    """Contours round a lake at ``level`` with an island in it, the lake a
    relation with no ``type`` - as an import holds one - its rings at the
    level too unless ``shore`` is False, as a main-map lake tagged on the
    relation alone is; and, if asked, fill lines across the water clear of
    the island, as flattening drew them."""
    from danu.core import edits
    from danu.core.square import Member, Relation, Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def ring(r, tags):
        pts = box(r)
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids + [ids[0]], pts + [pts[0]], tags).apply(sq)
        return wid

    for r, ele in contours:
        ring(r, {'ele': str(ele)})
    rim = {'ele': str(level)} if shore else {}
    outer, inner = ring(LAKE, rim), ring(ISLAND, rim)
    rid = alloc.take()
    sq.relations[rid] = Relation(id=rid, members=[Member('way', outer, 'outer'), Member('way', inner, 'inner')],
                                 tags={'natural': 'water', 'ele': str(level)})
    lat = LAT - LAKE + FILL
    while fill and lat < LAT + LAKE:
        if abs(lat - LAT) > ISLAND + FILL:
            pts = [(LON - LAKE, lat), (LON + LAKE, lat)]
            ids = [alloc.take() for _ in pts]
            edits.AddWay(alloc.take(), ids, pts, {'ele': str(level), 'danu:fill': f'relation/{rid}'}).apply(sq)
        lat += FILL
    return sq


def built(sq, tmp_path, name):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(sq, zone / 'S24E125.osm.xz')
    lines = []
    result = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), log=lines.append)
    assert result.dem is not None, '\n'.join(lines)
    ds = gdal.Open(str(result.dem))
    dem, gt = ds.GetRasterBand(1).ReadAsArray(), ds.GetGeoTransform()
    del ds
    return dem, gt, lines, result


def window(dem, gt, x0, y0, x1, y1):
    c0, c1 = int((x0 - gt[0]) / gt[1]), int((x1 - gt[0]) / gt[1])
    r0, r1 = int((y1 - gt[3]) / gt[5]), int((y0 - gt[3]) / gt[5])
    return dem[r0:r1, c0:c1]


M = 0.01                                     # clear of the shores


def water(dem, gt):
    """The lake north of its island."""
    return window(dem, gt, LON - LAKE + M, LAT + ISLAND + M, LON + LAKE - M, LAT + LAKE - M)


def island(dem, gt):
    return window(dem, gt, LON - ISLAND + M, LAT - ISLAND + M, LON + ISLAND - M, LAT + ISLAND - M)


def test_a_lake_at_sea_level_is_water_and_its_island_land(tmp_path):
    """Roantra's inland sea, flattened at 0 m - with the fill lines it still
    carries, between which the clamp put stripes at 1 m."""
    dem, gt, lines, _ = built(a_lake(0, [(0.3, 10)], fill=True), tmp_path, 'sea')
    assert any('1 lakes held at their level' in line for line in lines), '\n'.join(lines)
    w = water(dem, gt)
    assert w.size > 1000 and (w == 0).all(), f'{(w != 0).sum()} cells of the lake are not water'
    assert (island(dem, gt) >= 1).all(), 'the island went under with the lake'


LEVELS = [(0.3, 100), (0.25, 110)]          # the ground falling away from the lake


@pytest.mark.parametrize('shore', [True, False], ids=['shore at its level', 'level on the lake alone'])
def test_a_lake_among_contours_is_flat_at_its_level_with_no_fill_lines(tmp_path, shore):
    """A lake at 120 m inside contours at 100 and 110 m, nothing across it:
    every cell of it at 120 - whether its shore says so too or only the lake
    does, as a main-map lake tagged on its relation alone does."""
    dem, gt, _, _ = built(a_lake(120, LEVELS, shore=shore), tmp_path, 'held')
    w = water(dem, gt)
    assert w.size > 1000 and (w == 120).all(), f'{(w != 120).sum()} cells of the lake are not at 120 m'


def test_without_it_a_lake_tagged_alone_is_not_flat(tmp_path, monkeypatch):
    """What the test above is for: the lake with its level on the relation
    alone, left to the contours round it."""
    from danu.surface import build
    monkeypatch.setattr(build, 'lake_rings', lambda path, name=None: ([], 0))
    dem, gt, _, _ = built(a_lake(120, LEVELS, shore=False), tmp_path, 'loose')
    w = water(dem, gt)
    assert (w != 120).sum() > w.size // 10, 'flat anyway: the case above no longer arises'


def test_the_preview_burns_the_lake_as_the_build_does(tmp_path):
    """R35: the preview's layers, burned over the whole raster, are the
    build's constraints cell for cell - and stay so when a level is set on the
    lake there, as flattening sets it."""
    import numpy as np

    from danu.surface import local, preview

    _, _, _, result = built(a_lake(120, LEVELS), tmp_path, 'preview')
    ds = gdal.Open(str(result.constraints))
    cons, gt = ds.GetRasterBand(1).ReadAsArray(), ds.GetGeoTransform()
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    del ds
    layer = preview.Contours(result.contours_gpkg)
    whole = local.Box(0, 0, cons.shape[1] - 1, cons.shape[0] - 1)
    assert np.array_equal(layer.burn(gt, whole, nodata), cons)
    key = next(iter(layer._lake_fid))
    ele, poly = layer.lake(key)
    assert ele == 120 and poly.GetGeometryCount() == 2, 'the lake and its island'
    rings = [[poly.GetGeometryRef(i).GetPoint_2D(j) for j in range(poly.GetGeometryRef(i).GetPointCount())]
             for i in range(poly.GetGeometryCount())]
    layer.apply_lake(key, rings, 130)
    got = layer.burn(gt, whole, nodata)
    held = water(got, gt)
    assert (held == 130).all(), 'the new level is not what the preview burns'
    assert layer.remove_lake(key) and not layer.remove_lake(key)
    assert (water(layer.burn(gt, whole, nodata), gt) == nodata).all()


def test_a_lake_over_contours_at_other_levels_is_left_to_them(tmp_path):
    """R33's case: water at 0 m drawn over a hill whose contours go on inside
    it - N44E030 has 34 such ways. Held, the hill would go to sea level; it is
    left to the contours, and the build says how many it left."""
    from danu.core import edits
    sq = a_lake(120, LEVELS, shore=False)
    alloc = edits.IdAllocator(sq)
    pts = [(LON - 0.1, LAT + 0.1), (LON + 0.1, LAT + 0.1)]
    ids = [alloc.take() for _ in pts]
    edits.AddWay(alloc.take(), ids, pts, {'ele': '150'}).apply(sq)
    dem, gt, lines, _ = built(sq, tmp_path, 'spanned')
    assert any('0 lakes held at their level; 1 not' in line for line in lines), '\n'.join(lines)
    assert (water(dem, gt) != 120).sum() > 1000, 'held over a contour at 150 m'
