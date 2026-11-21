"""A saddle read as a saddle - #191, from #370.

The square is a pass: 500 m contours running east-west 1.3 km to the north
and the south, the valleys either side, and a 525 m hill ring to the east and
to the west, 550 m at its middle. The saddle between them, 510 m, is the top of the pass and the bottom of
the ridge. As a plain spot height it is a point, which the fill can only take
for a peak or a pit; the pass between the hills came out as a hump with the
saddle a pit in it. Read as a saddle, its pass is burned down to the 500 m
contours either side, and the pass reads highest at the saddle.
"""

import math
import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5
SADDLE = 510


def a_pass(kind='saddle', ele=SADDLE, at=(LON, LAT)):
    """The pass, and a spot height at ``at`` tagged ``natural=kind`` (None,
    a plain spot height)."""
    import numpy as np

    from danu.core import edits
    from danu.core.square import Node, Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True,
                attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)

    def way(pts, level):
        ids = [alloc.take() for _ in pts]
        edits.AddWay(alloc.take(), ids, pts, {'ele': str(level)}).apply(sq)

    for dlat in (0.012, -0.012):
        way([(125.05 + 0.018 * i, LAT + dlat) for i in range(51)], 500)
    for dlon in (0.025, -0.025):
        for r, level in ((0.012, 525), (0.006, 550)):
            pts = [(LON + dlon + r * math.cos(t), LAT + r * math.sin(t))
                   for t in np.linspace(0, 2 * math.pi, 73)]
            pts[-1] = pts[0]
            ids = [alloc.take() for _ in pts[:-1]]
            edits.AddWay(alloc.take(), ids + [ids[0]], pts[:-1] + [pts[0]], {'ele': str(level)}).apply(sq)
    nid = alloc.take()
    tags = {'ele': str(ele)}
    if kind:
        tags['natural'] = kind
    sq.nodes[nid] = Node(id=nid, lon=at[0], lat=at[1], tags=tags)
    return sq, nid


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


def north_south(dem, gt, cells=14):
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    return dem[y - cells:y + cells + 1, x], cells


def test_the_rays_find_the_pass():
    """Two sectors down, to the 500 m contours north and south; two up, to
    the hills - so two lines, the pass, each from the saddle down to 500 m
    about 1.3 km away."""
    from danu.checks.spots import _Segments
    from danu.surface import saddle
    sq, nid = a_pass()
    got = saddle.lines(_Segments(sq).arrays(), LON, LAT, SADDLE)
    assert got is not None and len(got) == 2
    ends = sorted(b[1] for _a, b in got)
    assert all(a == (LON, LAT, SADDLE) for a, _b in got)
    assert [b[2] for _a, b in got] == [500, 500]
    assert ends[0] == pytest.approx(LAT - 0.012, abs=1e-3) and ends[1] == pytest.approx(LAT + 0.012, abs=1e-3)


def test_a_saddle_is_the_top_of_its_pass(tmp_path):
    """Along the pass, north to south, the ground rises to the saddle and
    falls away from it. As a plain spot height the saddle was a pit in a
    hump: something beside it higher than it."""
    import numpy as np
    r, log = built(a_pass()[0], tmp_path, 'saddle')
    plain, _ = built(a_pass(kind=None)[0], tmp_path, 'plain')
    s, gt = read(r.dem)
    p, _ = read(plain.dem)
    along, c = north_south(s, gt)
    before, _ = north_south(p, gt)
    # here a pit of under a metre - castellan's 504 m saddle stood in a 516 m
    # hump; this ground is too regular for that, and the pit is the same fault
    assert before.max() > SADDLE + 0.5, 'the plain spot height is no pit, so this tests nothing'
    assert along[c] == pytest.approx(SADDLE, abs=0.5)
    assert along.max() <= SADDLE + 0.5, f'the pass rises past its saddle: {along.max():.1f} m'
    assert np.all(np.diff(along[:c + 1]) >= -0.5) and np.all(np.diff(along[c:]) <= 0.5), \
        'the pass does not rise to the saddle and fall away from it'
    assert any('1 saddles read as passes' in line for line in log)


def test_the_saddles_pass_is_a_layer_of_its_own(tmp_path):
    """The build keeps each saddle's pass as two lines of the ``saddle``
    layer, keyed by its node; the saddle itself is still a spot height."""
    from osgeo import ogr
    sq, nid = a_pass()
    r, _ = built(sq, tmp_path)
    ds = ogr.Open(str(r.contours_gpkg))
    ids = [f.GetField('osm_id') for f in ds.GetLayerByName('saddle')]
    spots = [f.GetField('osm_id') for f in ds.GetLayerByName('spot')]
    del ds
    assert ids == [str(nid), str(nid)]
    assert spots == [str(nid)]


def test_ground_that_is_not_a_pass_leaves_it_a_spot_height(tmp_path):
    """A saddle on the hill to the east, inside its ring, is not one: every
    ray meets the ring above it... or below. It stays a spot height alone,
    and the build says so."""
    from osgeo import ogr
    sq, _nid = a_pass(at=(LON + 0.025, LAT), ele=530)
    r, log = built(sq, tmp_path)
    ds = ogr.Open(str(r.contours_gpkg))
    assert ds.GetLayerByName('saddle').GetFeatureCount() == 0
    del ds
    assert any('0 saddles read as passes; 1 not' in line for line in log)


def test_the_preview_burns_what_the_build_burned(tmp_path):
    """``Contours.burn`` - the editor's - over the whole raster and over a box
    across the pass is the build's constraints, cell for cell (R35)."""
    import numpy as np

    from danu.surface.local import Box
    from danu.surface.preview import Contours
    r, _ = built(a_pass()[0], tmp_path)
    cons, gt = read(r.constraints)
    ds = gdal.Open(str(r.constraints))
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    del ds
    c = Contours(r.contours_gpkg)
    rows, cols = cons.shape
    assert np.array_equal(c.burn(gt, Box(0, 0, cols - 1, rows - 1), nodata), cons)
    y = int((LAT - gt[3]) / gt[5])
    x = int((LON - gt[0]) / gt[1])
    box = Box(x - 20, y - 50, x + 20, y + 50)
    assert np.array_equal(c.burn(gt, box, nodata), cons[box.slice])


def test_the_preview_puts_a_saddles_pass_in_again(tmp_path):
    """A saddle's pass taken out and put in again, as the editor does when
    the saddle is moved or re-tagged."""
    from danu.checks.spots import _Segments
    from danu.surface import saddle
    from danu.surface.preview import Contours
    sq, nid = a_pass()
    r, _ = built(sq, tmp_path)
    c = Contours(r.contours_gpkg)
    assert len(c.saddle_lines('S24E125', nid)) == 2
    assert c.remove_saddle('S24E125', nid)
    assert c.saddle_lines('S24E125', nid) == []
    c.apply_saddle('S24E125', nid, saddle.lines(_Segments(sq).arrays(), LON, LAT, SADDLE))
    assert len(c.saddle_lines('S24E125', nid)) == 2
