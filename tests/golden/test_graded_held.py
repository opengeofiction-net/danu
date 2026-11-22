"""Graded waterways held by the second pass - #372.

Grading writes an ``ele`` onto a river's vertices. Read as spot heights, they
were the steepest pair in reach wherever the contours either side are further
apart than the fill reaches, and the ground beside the river came out as a flat
plain ending in a step. So a graded waterway is held instead: a line, its
heights interpolated between its vertices, which isofill keeps in its second
pass and never shows its first (``--held``, 0.14.0).

The square here is ground falling south across contours running east-west, and
a river along the middle of it graded from 58 m to 42 m - with two vertices
left ungraded, so it makes a run of four, a run of one and a run of two.
"""

import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5                      # the middle of square S24E125
CONTOURS = [(-0.08, 30), (-0.03, 40), (0.03, 70), (0.08, 80)]    # lat offset, metres
RIVER = [(125.20 + 0.075 * i, e) for i, e in enumerate([58, 56, 54, 52, None, 48, None, 44, 42])]
RUNS = [[58, 56, 54, 52], [48], [44, 42]]


def a_valley(graded=True, river=True, contours=CONTOURS):
    """The contours, and the river along LAT - its vertices carrying their
    heights when ``graded``, none when not."""
    from danu.core import edits
    from danu.core.square import Node, Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True,
                attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for dlat, ele in contours:
        pts = [(125.02 + 0.0192 * i, LAT + dlat) for i in range(51)]
        ids = [alloc.take() for _ in pts]
        edits.AddWay(alloc.take(), ids, pts, {'ele': str(ele)}).apply(sq)
    if river:
        ids = []
        for lon, ele in RIVER:
            nid = alloc.take()
            tags = {'ele': str(ele)} if graded and ele is not None else {}
            sq.nodes[nid] = Node(id=nid, lon=lon, lat=LAT, tags=tags)
            ids.append(nid)
        wid = alloc.take()
        from danu.core.square import Way
        sq.ways[wid] = Way(id=wid, refs=ids, tags={'waterway': 'river', 'name': 'Test'})
    return sq


def built(sq, tmp_path, name='b', **kw):
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(sq, zone / 'S24E125.osm.xz')
    result = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3), **kw)
    assert result.dem is not None
    return result


def read(path):
    ds = gdal.Open(str(path))
    a = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    del ds
    return a, gt


def test_graded_vertices_are_held_runs_and_not_spot_heights(tmp_path):
    """The river's graded vertices leave the spot layer, and go into the held
    layer as its runs: a line for each stretch of graded vertices, a point for
    the one standing alone."""
    from osgeo import ogr
    r = built(a_valley(), tmp_path)
    ds = ogr.Open(str(r.contours_gpkg))
    assert ds.GetLayerByName('spot').GetFeatureCount() == 0
    runs = []
    for f in ds.GetLayerByName('held'):
        g = f.GetGeometryRef()
        runs.append([round(g.GetPoint(i)[2]) for i in range(g.GetPointCount())])
    del ds
    assert sorted(runs) == sorted(RUNS)
    assert r.held is not None and r.held.exists()


def test_the_held_raster_interpolates_between_vertices(tmp_path):
    """Halfway between two graded vertices the held raster reads halfway
    between their heights - the line, not its points."""
    r = built(a_valley(), tmp_path)
    h, gt = read(r.held)
    y = int((LAT - gt[3]) / gt[5])
    mid = (RIVER[0][0] + RIVER[1][0]) / 2
    x = int((mid - gt[0]) / gt[1])
    assert h[y, x] == pytest.approx(57, abs=0.3)
    # and nothing is held across the ungraded vertex between the runs
    assert h[y, int((RIVER[4][0] - gt[0]) / gt[1])] == -32768


def test_the_surface_keeps_the_held_heights(tmp_path):
    """Every held cell inside the drawn area comes out of the fill at exactly
    its held height: the second pass keeps them."""
    import numpy as np
    r = built(a_valley(), tmp_path)
    h, _ = read(r.held)
    s, _ = read(r.surface)
    m, _ = read(r.drawn_mask)
    at = (h != -32768) & (m > 0)
    assert at.sum() > 100
    assert np.array_equal(s[at], h[at])


def test_the_first_pass_never_sees_them(tmp_path):
    """The first pass of a graded river is the first pass of the same river
    ungraded, to the bit - which is the whole of the fix."""
    import numpy as np

    from danu.surface import build
    r1 = built(a_valley(), tmp_path, 'graded', keep_pass1=True)
    r0 = built(a_valley(graded=False), tmp_path, 'plain', keep_pass1=True)
    with np.load(build._pass1_file(r1.dem.parent)) as a, np.load(build._pass1_file(r0.dem.parent)) as b:
        assert np.array_equal(a['surface'], b['surface'])


def test_the_library_and_the_binary_hold_them_alike(tmp_path):
    """The editor fills through the library and the server's large zones
    through the binary (R35): the same surface either way."""
    import numpy as np
    lib = built(a_valley(), tmp_path, 'lib', library=True)
    exe = built(a_valley(), tmp_path, 'exe', library=False)
    assert np.array_equal(read(lib.surface)[0], read(exe.surface)[0])
    assert np.array_equal(read(lib.dem)[0], read(exe.dem)[0])


def test_a_build_with_nothing_graded_has_no_held_raster(tmp_path):
    """No graded waterway, no held raster, and the fill is the one it always
    was."""
    r = built(a_valley(graded=False), tmp_path)
    assert r.held is None


def test_the_preview_burns_what_the_build_burned(tmp_path):
    """``Contours.burn_held`` over the whole raster and over a box inside it
    is ``rasterise_held``'s raster, cell for cell (R35)."""
    import numpy as np

    from danu.surface.local import Box
    from danu.surface.preview import Contours
    r = built(a_valley(), tmp_path)
    h, gt = read(r.held)
    c = Contours(r.contours_gpkg)
    rows, cols = h.shape
    whole = c.burn_held(gt, Box(0, 0, cols - 1, rows - 1))
    assert np.array_equal(whole, h)
    y = int((LAT - gt[3]) / gt[5])
    box = Box(cols // 4, y - 30, cols // 2, y + 30)
    assert np.array_equal(c.burn_held(gt, box), h[box.slice])
    # and a box well north of the river burns nothing
    assert c.burn_held(gt, Box(cols // 4, y - 300, cols // 2, y - 200)) is None


def test_the_preview_edits_a_ways_runs(tmp_path):
    """A way's runs put in again from the square as edited, as the editor
    does when a vertex is graded: the new height is burned, the old one gone."""

    from danu.surface import held
    from danu.surface.local import Box
    from danu.surface.preview import Contours
    sq = a_valley()
    r = built(sq, tmp_path)
    _h, gt = read(r.held)
    c = Contours(r.contours_gpkg)
    wid, way = next((w, way) for w, way in sq.ways.items() if 'waterway' in way.tags)
    gap = way.refs[4]
    sq.nodes[gap].tags['ele'] = '50'
    c.apply_held('S24E125', wid, held.runs(sq, way))
    y = int((LAT - gt[3]) / gt[5])
    x = int((RIVER[4][0] - gt[0]) / gt[1])
    burned = c.burn_held(gt, Box(x - 5, y - 5, x + 5, y + 5))
    assert burned[5, 5] == pytest.approx(50, abs=0.3)
    assert len(c.held_runs('S24E125', wid)) == 2
    c.remove_held('S24E125', wid)
    assert c.burn_held(gt, Box(x - 5, y - 5, x + 5, y + 5)) is None
    assert c.held_runs('S24E125', wid) == []


def test_ground_only_the_river_reaches_is_solved_not_void(tmp_path):
    """The contours far apart, so the ground along the middle is out of reach
    of both, and floods from the raster's edge as void. As spot heights the
    river's vertices put the ground beside it in reach; held, isofill 0.15.0
    counts it in reach still, so that ground is solved - and the ground beyond
    the river's reach is void as it was. On 0.14.0 it all went to sea level,
    the river standing in it."""
    apart = [(-0.08, 30), (0.08, 80)]
    r = built(a_valley(contours=apart), tmp_path)
    plain = built(a_valley(graded=False, contours=apart), tmp_path, 'plain')
    s, gt = read(r.surface)
    p, _ = read(plain.surface)
    y = int((LAT - gt[3]) / gt[5])
    x = int((RIVER[1][0] - gt[0]) / gt[1])
    assert p[y + 5, x] == 0, 'the middle is not void without the river, so this tests nothing'
    assert s[y + 5, x] > 20, f'the ground beside the river came out at {s[y + 5, x]:.1f} m, as void'
    far = int(0.04 / abs(gt[5]))
    assert s[y + far, x] == 0, 'ground beyond the river\'s reach is no longer void'


def test_a_box_solved_in_the_editor_holds_the_river_as_the_build_does(tmp_path):
    """The editor's preview solves a box with the two passes apart
    (``local.resolve``); with the river held as isofill holds it between its
    passes, the box is the whole build's answer near the river. Without it,
    the river is gone from the box, and the box is nearly 2 m out."""
    import numpy as np

    from danu.surface import local
    from danu.surface import params as sp
    r = built(a_valley(), tmp_path)
    params = sp.load().with_arcsec(3)
    cons, gt = read(r.constraints)
    mask, _ = read(r.drawn_mask)
    surface, _ = read(r.surface)
    h, _ = read(r.held)
    ds = gdal.Open(str(r.constraints))
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    del ds
    y = int((LAT - gt[3]) / gt[5])
    x = int((RIVER[2][0] - gt[0]) / gt[1])
    box = local.Box(x - 3, y - 3, x + 3, y + 3)
    held_patch, good = local.resolve(cons.astype(np.float32), mask, None, surface, box, params,
                                     nodata=nodata, held=h)
    bare_patch, _ = local.resolve(cons.astype(np.float32), mask, None, surface, box, params,
                                  nodata=nodata)
    # ``good`` is the box grown by the cover, two radii each way, so 87 rows;
    # compared here over the band between the 40 m and 70 m contours, 25
    # rows either side of the river: beyond them the ground is
    # out of reach of both and floods from the raster's edge as void, which
    # a box cannot see from inside - the local solve's own limit, settled by
    # the rebuild on idle, and nothing to do with the river
    exact = surface[good.slice]
    band = slice(y - good.y0 - 25, y - good.y0 + 26)
    assert np.abs(held_patch - exact)[band].max() < 0.01
    assert np.abs(bare_patch - exact)[band].max() > 1


def test_the_editors_split_solve_is_the_builds(tmp_path):
    """The editor runs the passes apart - the first, then ``Isofill.hold``,
    then ``diffuse`` - and that has to be ``run`` with ``held``, cell for
    cell, or the editor and the server describe different ground (R35)."""
    import numpy as np

    from danu.surface import isofill_lib
    from danu.surface import params as sp
    r = built(a_valley(contours=[(-0.08, 30), (0.08, 80)]), tmp_path)
    params = sp.load().with_arcsec(3)
    lib = isofill_lib.Isofill.load()
    cons, _ = read(r.constraints)
    mask, _ = read(r.drawn_mask)
    h, _ = read(r.held)
    cons = cons.astype(np.float32)
    whole, _ = lib.run(cons, params, mask=mask, nodata=-9999.0, held=h)
    first, _ = lib.run(cons, params, mask=mask, nodata=-9999.0, pass2=False)
    split = lib.diffuse(lib.hold(first, h, params.fill_cells), mask=mask)
    assert np.array_equal(whole.view(np.uint32), split.view(np.uint32))


@pytest.mark.parametrize('kind', ['valley', 'ridge'])
def test_a_landform_line_is_held_as_a_river_is(tmp_path, kind):
    """#191: a ``natural=valley`` or ``ridge`` drawn as a line, heights on its
    vertices, is held as a graded river is - its vertices not spot heights,
    its runs the held layer, its heights kept by the fill."""
    import numpy as np
    from osgeo import ogr
    sq = a_valley()
    wid, way = next((w, x) for w, x in sq.ways.items() if 'waterway' in x.tags)
    way.tags = {'natural': kind}
    r = built(sq, tmp_path)
    ds = ogr.Open(str(r.contours_gpkg))
    assert ds.GetLayerByName('spot').GetFeatureCount() == 0
    assert ds.GetLayerByName('held').GetFeatureCount() == len(RUNS)
    del ds
    h, _ = read(r.held)
    s, _ = read(r.surface)
    m, _ = read(r.drawn_mask)
    at = (h != -32768) & (m > 0)
    assert at.sum() > 100 and np.array_equal(s[at], h[at])
