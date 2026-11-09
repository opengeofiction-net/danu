"""Water held alongside a working set (#279) is held at its level in the
set's build: roantra's inland sea, homed in N46E030, reaches N44E027's set,
and built without it the ground round it was guessed from where the contours
stop - surface over the sea, and land beyond the fill taken for sea. Shown
on a copy of those squares (2026-11-09); here, the sea is in the set's
constraints at its level, from a square that is not the set's."""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

HILL = (125.6, -23.5)                        # in S24E125, the set's square
SHORE = 125.29                               # the sea's east shore, in the set's square


def squares():
    """S24E125 with a hill of rings, and S24E124 holding a sea at 0 m that
    reaches east across the degree line to within a kilometre of the hill's
    lowest ring - a relation with no ``type``, as an import holds one."""
    from danu.core import edits
    from danu.core.square import Member, Relation, Square, SquareName

    def square(lon):
        sq = Square(name=SquareName(lon, -24), present=True, attrs={'version': '0.6', 'upload': 'never'})
        return sq, edits.IdAllocator(sq)

    def ring(sq, alloc, pts, tags):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids + [ids[0]], [*pts, pts[0]], tags).apply(sq)
        return wid

    land, la = square(125)
    x, y = HILL
    for r, ele in ((0.3, 25), (0.2, 50), (0.1, 100)):
        ring(land, la, [(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)], {'ele': str(ele)})
    sea, sa = square(124)
    shore = ring(sea, sa, [(124.6, -23.8), (SHORE, -23.8), (SHORE, -23.2), (124.6, -23.2)], {'ele': '0'})
    # an island first, as the inland sea's relation lists one
    islet = ring(sea, sa, [(124.70, -23.30), (124.72, -23.30), (124.72, -23.28), (124.70, -23.28)], {'ele': '0'})
    rid = sa.take()
    sea.relations[rid] = Relation(id=rid, members=[Member('way', islet, 'inner'), Member('way', shore, 'outer')],
                                  tags={'natural': 'water', 'ele': '0'})
    return land, sea


def built(tmp_path, name, water):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    land, sea = squares()
    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(land, zone / 'S24E125.osm.xz')
    write_square(sea, zone / 'S24E124.osm.xz')
    lines = []
    result = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), names=[land.name],
                             water_names=[sea.name] if water else None, log=lines.append)
    assert result.dem is not None, '\n'.join(lines)
    ds = gdal.Open(str(result.constraints))
    band = ds.GetRasterBand(1)
    cont, gt, nodata = band.ReadAsArray(), ds.GetGeoTransform(), band.GetNoDataValue()
    del ds
    built.last = result
    return cont, gt, nodata, lines


def at(dem, gt, lon, lat):
    return float(dem[int((lat - gt[3]) / gt[5]), int((lon - gt[0]) / gt[1])])


def test_a_sea_held_alongside_is_held_at_its_level_and_does_not_widen_the_grid(tmp_path):
    cont, gt, nodata, lines = built(tmp_path, 'with', water=True)
    assert any('1 of them from squares alongside' in ln for ln in lines), lines
    assert gt[0] == pytest.approx(125, abs=0.001), 'the grid is the set\'s square alone'
    without, gt0, _, lines0 = built(tmp_path, 'without', water=False)
    assert gt0 == gt and not any('alongside' in ln for ln in lines0)
    sea = (125.15, HILL[1])                  # in the sea, in the set's square
    assert at(cont, gt, *sea) == 0, 'burned at its level'
    assert at(without, gt0, *sea) == nodata, 'nothing said there without it'
    assert at(cont, gt, *HILL) == at(without, gt0, *HILL), 'the set\'s own constraints as they were'


def test_the_preview_burns_a_lake_whose_first_ring_is_an_island_where_the_build_does(tmp_path):
    """The preview, and the 1" view on it, finds the lakes in a box by their
    envelopes, and OGR takes a polygon's from its first ring: with the sea's
    island first, no view but the island's had the sea in it."""
    from danu.surface import NODATA
    from danu.surface.local import Box
    from danu.surface.preview import Contours

    cont, gt, _, _ = built(tmp_path, 'with', water=True)
    layer = Contours(built.last.contours_gpkg)
    lon, lat = 125.15, HILL[1]                # in the sea, nowhere near its island
    c, r = int((lon - gt[0]) / gt[1]), int((lat - gt[3]) / gt[5])
    box = Box(c - 40, r - 40, c + 39, r + 39)
    burned = layer.burn(gt, box, NODATA)
    assert (burned == 0).all(), 'the sea burned in the box, as the build burned it'
    assert (burned == cont[box.slice]).all()
