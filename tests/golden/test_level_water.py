"""A lake at sea level held as water - flattened at 0 m, as roantra's inland
sea is, with its fill lines across it.

The clamp lifts to 1 m whatever reads zero walled off from the edge of the
zone, since it cannot tell a lake from a low island. The rows between the fill
lines are all of that, and came out as stripes at 1 m across the water. The
lake's own area says its interior is water - its island excepted.
"""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5                      # the middle of square S24E125
LAKE, ISLAND, LAND = 0.2, 0.04, 0.3          # half-widths in degrees
FILL = 0.00108                               # 120 m apart, as flattening draws them


def box(r):
    return [(LON - r, LAT - r), (LON + r, LAT - r), (LON + r, LAT + r), (LON - r, LAT + r)]


def a_lake():
    """A 10 m contour round a lake at 0 m with an island in it, the lake a
    relation with no ``type`` - as an import holds one - and fill lines across
    the water clear of the island."""
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

    ring(LAND, {'ele': '10'})
    outer, inner = ring(LAKE, {'ele': '0'}), ring(ISLAND, {'ele': '0'})
    rid = alloc.take()
    sq.relations[rid] = Relation(id=rid, members=[Member('way', outer, 'outer'), Member('way', inner, 'inner')],
                                 tags={'natural': 'water', 'ele': '0'})
    lat = LAT - LAKE + FILL
    while lat < LAT + LAKE:
        if abs(lat - LAT) > ISLAND + FILL:
            pts = [(LON - LAKE, lat), (LON + LAKE, lat)]
            ids = [alloc.take() for _ in pts]
            edits.AddWay(alloc.take(), ids, pts, {'ele': '0', 'danu:fill': f'relation/{rid}'}).apply(sq)
        lat += FILL
    return sq


def built(tmp_path, name):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(a_lake(), zone / 'S24E125.osm.xz')
    lines = []
    result = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), log=lines.append)
    assert result.dem is not None, '\n'.join(lines)
    ds = gdal.Open(str(result.dem))
    dem, gt = ds.GetRasterBand(1).ReadAsArray(), ds.GetGeoTransform()
    del ds
    return dem, gt, lines


def window(dem, gt, x0, y0, x1, y1):
    c0, c1 = int((x0 - gt[0]) / gt[1]), int((x1 - gt[0]) / gt[1])
    r0, r1 = int((y1 - gt[3]) / gt[5]), int((y0 - gt[3]) / gt[5])
    return dem[r0:r1, c0:c1]


def test_a_lake_at_sea_level_is_water_between_its_fill_lines_and_its_island_land(tmp_path):
    dem, gt, lines = built(tmp_path, 'level')
    assert any('1 water body at sea level' in line for line in lines), '\n'.join(lines)
    m = 0.01                                          # clear of the shores
    water = window(dem, gt, LON - LAKE + m, LAT + ISLAND + m, LON + LAKE - m, LAT + LAKE - m)
    assert water.size > 1000 and (water == 0).all(), f'{(water != 0).sum()} cells of the lake are not water'
    island = window(dem, gt, LON - ISLAND + m, LAT - ISLAND + m, LON + ISLAND - m, LAT + ISLAND - m)
    assert island.size and (island >= 1).all(), 'the island went under with the lake'


def test_without_it_the_rows_between_the_fill_lines_stand_at_a_metre(tmp_path, monkeypatch):
    """What the test above is for: the stripes, with the lake left out of the mask."""
    from danu.surface import build
    monkeypatch.setattr(build, 'level_water', lambda gpkg, grid, work, water, log=None: water)
    dem, gt, _ = built(tmp_path, 'striped')
    m = 0.01
    water = window(dem, gt, LON - LAKE + m, LAT + ISLAND + m, LON + LAKE - m, LAT + LAKE - m)
    assert (water == 1).sum() > water.size // 10, 'no stripes: the case above no longer arises'
