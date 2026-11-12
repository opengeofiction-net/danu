"""A working set's edge is not the end of the drawn ground (isofill 0.13's
edge_void 0, 2026-11-11). Ground the contours do not reach, running to the
set's edge, was held at zero there - the void floods from the raster's edge -
and the clamp made it sea, though the zone goes on beyond: N45E027's valley
floor from N45E028's set. Given the zone's squares, the edge seeds no void
across from one of them, and the ground is solved."""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

RIDGE = (125.001, 125.30)                    # two 50 m lines, north to south, the first by the west edge
FLOOR = (125.15, -23.5)                      # between them, out of the reach of either, running north and south


def squares():
    from danu.core import edits
    from danu.core.square import Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for lon in RIDGE:
        pts = [(lon, -23.999), (lon, -23.001)]
        ids = [alloc.take() for _ in pts]
        edits.AddWay(alloc.take(), ids, pts, {'ele': '50'}).apply(sq)
    blank = Square(name=SquareName(124, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
    return sq, blank


def built(tmp_path, name, beyond):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    sq, west = squares()
    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(sq, zone / 'S24E125.osm.xz')
    write_square(west, zone / 'S24E124.osm.xz')
    lines = []
    r = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), names=[sq.name],
                        beyond=beyond, log=lines.append)
    assert r.dem is not None, '\n'.join(lines)

    def at(path, lon, lat):
        ds = gdal.Open(str(path))
        gt = ds.GetGeoTransform()
        return float(ds.GetRasterBand(1).ReadAsArray(int((lon - gt[0]) / gt[1]), int((lat - gt[3]) / gt[5]), 1, 1)[0, 0])
    return at(r.surface, *FLOOR), at(r.dem, *FLOOR)


def test_unreached_ground_at_an_edge_inside_the_zone_is_solved_not_sea(tmp_path):
    from danu.core.square import SquareName

    fill, dem = built(tmp_path, 'whole', beyond=None)
    assert fill == 0 and dem == 0, 'the edge as the end of the drawn ground: held at zero, sea'
    zone = {SquareName(lon, lat) for lon in (124, 125, 126) for lat in (-25, -24, -23)}
    fill, dem = built(tmp_path, 'set', beyond=zone)
    assert fill > 40 and dem > 40, f'the zone goes on north and south: solved from the lines ({fill:.1f} m)'
    # and across from nothing it is the end, as before: the floor reaches the
    # north edge, and nothing is north of the set
    north = zone - {SquareName(lon, -23) for lon in (124, 125, 126)}
    fill, dem = built(tmp_path, 'open south', beyond=north)
    assert fill == 0 and dem == 0
