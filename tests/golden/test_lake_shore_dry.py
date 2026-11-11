"""Ground just outside water held at sea level is dry (2026-11-11): roantra's
inland sea, r470432, is natural=water - wet inside its rings, dry outside -
and the low strip outside w809152, which no contour describes, reached the
edge of the N43E026 set and flooded as sea in the clamp. The rings now seed a
dry side as a coastline seeds a land side, and the clamp keeps it land."""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LAT = -23.5
SHORE = 125.5                                # the sea's east shore
HILL = 125.85                                # a hill well away from it


def square():
    from danu.core import edits
    from danu.core.square import Member, Relation, Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def ring(pts, tags):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids + [ids[0]], [*pts, pts[0]], tags).apply(sq)
        return wid

    for r, ele in ((0.1, 25), (0.05, 50)):
        ring([(HILL - r, LAT - r), (HILL + r, LAT - r), (HILL + r, LAT + r), (HILL - r, LAT + r)], {'ele': str(ele)})
    # a sea along the west of the square, its level on the relation alone
    shore = ring([(125.0, -23.9), (SHORE, -23.9), (SHORE, -23.1), (125.0, -23.1)], {})
    rid = alloc.take()
    sq.relations[rid] = Relation(id=rid, members=[Member('way', shore, 'outer')],
                                 tags={'natural': 'water', 'ele': '0'})
    return sq


def at(path, lon, lat):
    ds = gdal.Open(str(path))
    gt = ds.GetGeoTransform()
    v = float(ds.GetRasterBand(1).ReadAsArray(int((lon - gt[0]) / gt[1]), int((lat - gt[3]) / gt[5]), 1, 1)[0, 0])
    ds = None
    return v


def test_low_ground_outside_a_sea_level_ring_is_land_not_sea(tmp_path):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(square(), zone / 'S24E125.osm.xz')
    lines = []
    r = build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3), log=lines.append)
    assert r.dem is not None, '\n'.join(lines)
    assert at(r.dem, SHORE - 0.05, LAT) == 0, 'the sea'
    strip = (SHORE + 0.05, LAT)             # outside the ring, far from the hill's contours
    assert at(r.surface, *strip) < 0.5, 'nothing describes it: the fill leaves it at the sea'
    assert at(r.dem, *strip) >= 1, 'dry outside the ring, so land'
    assert any('kept land, dry outside the water at sea level' in ln for ln in lines), lines
