"""The preview against the exact build - R19's half of phase 4.

F3 asked whether a box solved against a held rim is the whole raster's answer,
and measured that it is. This asks the question that comes before it: whether
the constraints handed to that solve can be produced without rebuilding, and
whether what comes out is still the build's own answer.

The trap here is ordering. Rasterising with ATTRIBUTE=ele is last-writer-wins
where two contours touch one cell, so a box burned in a different order from
the whole raster disagrees with it - 1,359 of 48,841 cells when the features
come back in spatial-index order, scattered through the box rather than at its
edge. These hold the burn to the build's order.
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


def built(zone, work, params):
    import numpy as np
    from danu.surface import build
    result = build.build_dem(zone, work, params)
    assert result.dem is not None, 'the fixture built nothing'
    held = {}

    def read(path, dtype=None):
        ds = gdal.Open(str(path))            # held: the band dies with it
        held[str(path)] = ds
        a = ds.GetRasterBand(1).ReadAsArray()
        return a.astype(dtype) if dtype is not None else a

    return {
        'surface': read(work / 'rounded.tif', np.float32),
        'constraints': read(result.constraints, np.float32),
        'mask': read(result.drawn_mask),
        'water': read(result.water_mask) if result.water_mask else None,
        'nodata': held[str(result.constraints)].GetRasterBand(1).GetNoDataValue(),
        'gt': gdal.Open(str(result.constraints)).GetGeoTransform(),
        'result': result,
    }


def a_level_worth_deleting(square):
    """Every contour at the lowest elevation drawn more than once. Deleting a
    single contour on this fixture can change nothing at all - 39 of its 94 are
    an exact copy of another - and a test of an edit that changed nothing
    asserts nothing. See test_local_solve for the full account."""
    contours = [w for w in square.ways.values() if w.ele is not None]
    at = {}
    for w in contours:
        at.setdefault(w.ele, []).append(w)
    levels = sorted(ele for ele, ws in at.items() if len(ws) > 1)
    assert levels, 'no elevation in the fixture is drawn more than once'
    return at[levels[0]]


def test_a_box_burned_from_the_layer_is_the_whole_rasters_burn(tmp_path):
    """The ordering trap, pinned. Burn boxes from the in-memory layer and hold
    every cell to what the whole-raster rasterise put there.

    Boxes at several sizes, because the disagreement this guards against grows
    with the number of contours in the box, and a single small box would miss
    it: the spatial-index ordering that motivated this agreed on 97% of cells.
    """
    import numpy as np
    from danu.surface import build, local, preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    b = built(zone, tmp_path / 'work', p)
    layer = preview.Contours(b['result'].contours_gpkg)
    assert len(layer) > 50, 'the fixture put almost nothing in the layer'

    cons = b['constraints']
    drawn = np.argwhere(cons != b['nodata'])
    assert len(drawn) > 1000, 'the fixture drew almost nothing'
    y, x = (int(v) for v in drawn[len(drawn) // 2])

    checked = 0
    for half in (2, 10, 40, 100):
        box = local.Box(x - half, y - half, x + half, y + half)
        grown = box.grown(2 * p.fill_cells, cons.shape).grown(
            local.reach(p, 2 * p.fill_cells), cons.shape)
        got = layer.burn(b['gt'], grown, b['nodata'])
        want = cons[grown.slice]
        differ = int((got != want).sum())
        assert differ == 0, f'{differ} of {want.size} cells differ in a {grown.shape} box'
        # and the box has to have had contours in it, or this compared two
        # rasters of nodata and would pass whatever the order was
        assert int((want != b['nodata']).sum()) > 0, 'that box holds no constraint at all'
        checked += 1
    assert checked == 4


def test_a_preview_of_a_deleted_level_is_the_rebuilds_answer(tmp_path):
    """End to end: delete a contour level, preview it without rebuilding, and
    compare with the build that would have run.

    The preview never calls collect, rasterise, drawn_area, water_mask or
    clamp. What it does is mutate the layer, burn one box and solve it."""
    import numpy as np
    from danu.core import edits
    from danu.core.square import read_square, write_square
    from danu.surface import local, preview

    p = lock_params()
    zone = tmp_path / 'before'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    before = built(zone, tmp_path / 'wbefore', p)

    square = read_square(zone / SQUARE.name)
    victims = a_level_worth_deleting(square)
    coords = [(square.nodes[r].lon, square.nodes[r].lat)
              for w in victims for r in w.refs if r in square.nodes]

    # the preview: the layer loses those ways, and one box is solved
    layer = preview.Contours(before['result'].contours_gpkg)
    n_before = len(layer)
    for way in victims:
        assert layer.remove(way.id), f'way {way.id} was not in the layer'
    assert len(layer) < n_before, 'removing the level took nothing out'

    gt = before['gt']
    ys = [int((lat - gt[3]) / gt[5]) for _, lat in coords]
    xs = [int((lon - gt[0]) / gt[1]) for lon, _ in coords]
    box = local.Box.around(ys, xs)

    dem_ds = gdal.Open(str(before['result'].dem))        # held
    kept = preview.Kept(constraints=before['constraints'], mask=before['mask'],
                        water=before['water'], surface=before['surface'],
                        geotransform=gt, nodata=before['nodata'], contours=layer,
                        dem=dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32))
    keep_a_copy = before['constraints'].copy()
    mask_copy = before['mask'].copy()
    water_copy = before['water'].copy() if before['water'] is not None else None
    patch, good = preview.patch(kept, box, p)
    assert np.array_equal(kept.constraints, keep_a_copy), \
        'the preview left its burn behind in the kept constraints'
    # constraints are written on purpose and put back; these two are not
    # written at all - isofill takes both as const - and the asymmetry is
    # worth pinning rather than leaving to a reading of the header
    assert np.array_equal(kept.mask, mask_copy), 'the preview moved the drawn mask'
    assert water_copy is None or np.array_equal(kept.water, water_copy), \
        'the preview moved the water mask'

    # the exact build of the same edit
    history = edits.SetUndoStack()
    for way in victims:
        history.do(square, edits.DeleteWay(way.id))
    after_zone = tmp_path / 'after'
    after_zone.mkdir()
    write_square(square, after_zone / 'S24E125.osm.xz')
    after = built(after_zone, tmp_path / 'wafter', p)
    whole = after['surface'].astype(np.float64)

    # the edit has to have moved the surface, or this compares two copies of it
    moved = int((whole != before['surface'].astype(np.float64)).sum())
    assert moved > 50, f'deleting the level moved only {moved} cells'

    got = before['surface'].copy()
    got[good.slice] = patch
    err = np.abs(got.astype(np.float64) - whole)
    assert float(err[good.slice].max()) == 0.0, \
        f'the previewed patch is {float(err[good.slice].max()):.6f} m out'
    stale = err.copy()
    stale[good.slice] = 0
    assert float(stale.max()) == 0.0, \
        f'ground outside the patch is {float(stale.max()):.3f} m out of date'


def test_a_contour_the_build_never_saw_burns_last(tmp_path):
    """A new way takes a new FID, so it is burned after the build's own
    contours and wins a shared cell. That is a deliberate limit - stated in
    Contours - and this pins the behaviour rather than leaving it to chance."""
    import numpy as np
    from danu.surface import build, local, preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    b = built(zone, tmp_path / 'work', p)
    layer = preview.Contours(b['result'].contours_gpkg)

    cons = b['constraints']
    drawn = np.argwhere(cons != b['nodata'])
    y, x = (int(v) for v in drawn[len(drawn) // 2])
    gt = b['gt']
    # a two-point line straight over that drawn cell, at an elevation nothing
    # else uses
    lon = gt[0] + (x + 0.5) * gt[1]
    lat = gt[3] + (y + 0.5) * gt[5]
    layer.apply(999_000_001, [(lon - 0.02, lat), (lon + 0.02, lat)], 4321.0)

    box = local.Box(x - 3, y - 3, x + 3, y + 3)
    got = layer.burn(gt, box, b['nodata'])
    assert 4321 in set(np.unique(got).tolist()), 'the new contour did not burn at all'
    assert got[3, 3] == 4321, 'the new contour did not win the cell it crosses'


def test_the_layer_is_made_on_the_gdal_the_servers_have(tmp_path, monkeypatch):
    """OGR's in-memory driver was renamed from Memory to MEM in GDAL 3.11.
    Trixie ships 3.10, and so does CI; a desk on 3.12 has both. Asking for
    'MEM' alone returns None there rather than raising, and the failure
    surfaces as an AttributeError on None two lines later - which is exactly
    how this was found, with the suite green locally and three tests red on CI.

    So: hide 'MEM' the way 3.10 does, and build the layer anyway.
    """
    from osgeo import ogr

    from danu.surface import preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    b = built(zone, tmp_path / 'work', p)

    real = ogr.GetDriverByName

    def only_the_old_name(name):
        return None if name == 'MEM' else real(name)

    monkeypatch.setattr(ogr, 'GetDriverByName', only_the_old_name)
    assert ogr.GetDriverByName('MEM') is None, 'the older GDAL is not being simulated'
    layer = preview.Contours(b['result'].contours_gpkg)
    assert len(layer) > 50, 'the layer came back empty on the older name'


def test_burning_in_the_wrong_order_is_a_different_raster(tmp_path):
    """The claim the ordering rests on, made falsifiable.

    Everything else here asserts the burn *matches* the whole raster, which
    would also pass if order made no difference at all - if the contours never
    overlapped, or if the rasteriser broke ties some order-independent way.
    Then the FID bookkeeping in Contours would be ceremony, and nothing would
    say so.

    So: the same geometry and the same elevations, FIDs renumbered back to
    front, and the tie broken the other way. On this fixture that moves 80
    cells, which is the figure docs/spec.md quotes.
    """
    import numpy as np
    from osgeo import ogr

    from danu.surface import local, preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    b = built(zone, tmp_path / 'work', p)

    forward = preview.Contours(b['result'].contours_gpkg)
    backward = preview.Contours(b['result'].contours_gpkg)
    feats = [(f.GetFID(), f.GetGeometryRef().Clone(), f.GetField('ele'), f.GetField('osm_id'))
             for f in backward.layer]
    top = max(fid for fid, *_ in feats)
    for fid, *_ in feats:
        backward.layer.DeleteFeature(fid)
    defn = backward.layer.GetLayerDefn()
    for fid, geom, ele, osm in feats:
        g = ogr.Feature(defn)
        g.SetFID(top - fid + 1)
        g.SetGeometry(geom)
        g.SetField('ele', ele)
        g.SetField('osm_id', osm)
        backward.layer.CreateFeature(g)
    assert len(backward) == len(forward), 'the reversal lost features'

    cons = b['constraints']
    drawn = np.argwhere(cons != b['nodata'])
    y, x = (int(v) for v in drawn[len(drawn) // 2])
    box = local.Box(x - 10, y - 10, x + 10, y + 10)
    grown = box.grown(2 * p.fill_cells, cons.shape).grown(
        local.reach(p, 2 * p.fill_cells), cons.shape)
    want = cons[grown.slice]

    assert int((forward.burn(b['gt'], grown, b['nodata']) != want).sum()) == 0
    wrong = int((backward.burn(b['gt'], grown, b['nodata']) != want).sum())
    assert wrong > 0, ('burning back to front changed nothing, so FID order is '
                       'not what makes the burn match and Contours is keeping '
                       'FIDs for no reason')
    assert wrong == 80, f'the fixture moved {wrong} cells, not the 80 the spec quotes'


def test_a_clamped_patch_is_the_clamps_own_answer(tmp_path):
    """clamp_patch against land_clamp over the same ground.

    The clamp has two halves and only one is local: deciding which cells are
    sea polygonizes the whole raster, and the arithmetic that follows is four
    lines. This reuses the decision from the build and redoes the arithmetic,
    so over unedited ground it must agree cell for cell.
    """
    import numpy as np
    from danu.surface import preview

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    work = tmp_path / 'work'
    b = built(zone, work, p)
    dem_ds = gdal.Open(str(b['result'].dem))          # held
    dem = dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)

    got = preview.clamp_patch(b['surface'], b['constraints'], dem)

    # The sea/land decision, which is the part that is reused rather than
    # recomputed, and so the part that could be wrong: exact.
    assert np.array_equal(got == 0, dem == 0), \
        f'{int(((got == 0) != (dem == 0)).sum())} cells fall on the other side of the coast'

    # The elevations, to the precision the published DEM is written at. dem.tif
    # is LERC at MAX_Z_ERROR, which is lossy on purpose - 0.05 m, a twentieth
    # of the whole-metre quantisation the DEM went to Float32 to escape - so
    # the patch is not merely equal to it, it is finer than it. Asserting
    # equality here failed on 12,880 cells reading 3.2000 against 3.2301, which
    # is the compression, not the clamp.
    # The tolerance is MAX_Z_ERROR plus one float32 step at the elevation
    # concerned. The worst cell here is 0.0500030517578125 out, which is 0.05
    # plus an ulp of a value around fifty metres - LERC's guarantee is met and
    # the excess is the type the DEM is stored in, not the clamp.
    err = float(np.abs(got.astype(np.float64) - dem.astype(np.float64)).max())
    ulp = float(np.spacing(np.float32(np.abs(dem).max())))
    assert err <= p.dem_max_z_error + ulp, \
        f'the patch is {err:.7f} m from the clamp, past {p.dem_max_z_error:g} + {ulp:.2g}'

    # and it has to be doing something: the three rules each have to bite on
    # this fixture, or the test would pass on a function that returned its
    # input unchanged
    assert int((dem == 0).sum()) > 0, 'no sea, so the sea rule is untested'
    assert int((b['surface'] < 1).sum()) > 0, 'nothing below 1 m, so the floor is untested'
    from danu.surface.build import NODATA
    assert int((b['constraints'] != NODATA).sum()) > 0, 'nothing burned'
    assert not np.array_equal(b['surface'], dem), 'the clamp changed nothing at all here'


def test_a_shaded_window_is_the_whole_rasters_shading(tmp_path):
    """shade_window against shade_dem over the same ground.

    Every stage reads its neighbours - the box filter, the hillshade's three by
    three, whatever bilinear touches - so the window is grown by a halo and
    only the inside is the whole raster's answer. This measures how far in that
    becomes true rather than asserting a margin someone chose.
    """
    import numpy as np
    from danu.surface import local, shade

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    work = tmp_path / 'work'
    b = built(zone, work, p)
    whole = shade.shade_dem(b['result'].dem, p, work)

    dem_ds = gdal.Open(str(b['result'].dem))          # held
    dem = dem_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    gt = dem_ds.GetGeoTransform()
    rows, cols = dem.shape

    # a window over drawn ground, well away from the raster's own edge
    # Well inside the raster, because every stage here reads its neighbours
    # and a window at the edge has nothing outside it to be computed against.
    # Not centred on a contour: this fixture's drawn cells all sit within 43
    # cells of an edge, and the shading does not need one - it needs relief.
    halo = 2 * p.fill_cells
    half = 60
    edge = halo + half + 1
    best, win = -1.0, None
    for cy in range(edge, rows - edge, 40):
        for cx in range(edge, cols - edge, 40):
            cand = local.Box(cx - half, cy - half, cx + half, cy + half).grown(halo, (rows, cols))
            relief = float(np.ptp(dem[cand.slice]))
            if relief > best:
                best, win = relief, cand
    assert win is not None and not win.touches_edge((rows, cols))
    # the middle of this fixture is flat sea, and a flat window's hillshade is
    # a constant that would match anything
    assert best > 1.0, f'the most relief any window inside the raster has is {best:.2f} m'

    sub_gt = (gt[0] + win.x0 * gt[1], gt[1], 0.0, gt[3] + win.y0 * gt[5], 0.0, gt[5])
    m_dem, m_shade, m_gt, metres = shade.shade_window(
        dem[win.slice], sub_gt, dem_ds.GetProjection(), p,
        align_to=whole.geotransform)
    assert metres == whole.metres, 'the window shaded at a different cell size'

    # where the window's Mercator grid sits inside the whole one
    # aligned, so these are whole cells and the rounding is a formality - a
    # patch that landed between cells could not be spliced in at all
    fx = (m_gt[0] - whole.geotransform[0]) / whole.geotransform[1]
    fy = (m_gt[3] - whole.geotransform[3]) / whole.geotransform[5]
    # This is also what pins shade_window dropping xRes/yRes on the aligned
    # path: asking a warp for a resolution *and* a size leaves it unclear which
    # the binding acts on, and if the alignment stopped taking effect these two
    # assertions are what would say so. Do not restore those options as
    # redundant.
    assert abs(fx - round(fx)) < 1e-6 and abs(fy - round(fy)) < 1e-6, \
        f'the window landed {fx - round(fx):+.3f}, {fy - round(fy):+.3f} cells off the grid'
    ox, oy = int(round(fx)), int(round(fy))
    wr, wc = m_shade.shape
    theirs = whole.shade[oy:oy + wr, ox:ox + wc].astype(np.int16)
    assert theirs.shape == m_shade.shape, 'the window did not land inside the whole raster'
    diff = np.abs(m_shade.astype(np.int16) - theirs)

    # cropping the halo is what makes it the whole raster's answer, and the
    # difference at the rim is what says the halo is needed at all
    inset = max(4, p.smooth_cells)
    inner = diff[inset:-inset, inset:-inset]
    assert inner.max() <= 1, f'the inside of the window is {inner.max()} grey levels out'
    assert diff.max() > inner.max(), \
        'the window edge is as good as its middle, so the halo is doing nothing'


def test_the_clamp_puts_the_burned_constraints_back():
    """The third of clamp_patch's rules, on ground built to need it.

    The golden fixture cannot test this: the fill reproduces its constraints at
    the cells they were burned into, so putting them back changes nothing there
    and deleting the line leaves every other assertion green. It is the rule
    that keeps a coastline drawn at zero at zero, and a contour authoritative
    over whatever the fill made of it, so it is worth more than an untestable
    line. Synthetic arrays, then, built to make each rule bite on its own.
    """
    import numpy as np
    from danu.surface import preview
    from danu.surface.build import NODATA

    surface = np.array([[0.2, 50.0, 0.2, 7.0]], dtype=np.float32)
    cons = np.array([[NODATA, NODATA, 0.0, 9.0]], dtype=np.float32)
    # the last exact build's answer: only the first cell was called sea
    kept = np.array([[0.0, 50.0, 0.0, 9.0]], dtype=np.float32)

    got = preview.clamp_patch(surface, cons, kept)

    assert got[0, 0] == 0.0, 'sea did not go to zero'
    assert got[0, 1] == 50.0, 'land was not left alone'
    # burned at zero, and the clamp called it sea - it must still read zero,
    # which is the rule and the sea rule agreeing
    assert got[0, 2] == 0.0, 'a coastline burned at zero did not stay at zero'
    # burned at 9 where the fill said 7: the burn wins
    assert got[0, 3] == 9.0, 'a burned contour did not override the fill'

    # and the floor, which needs a cell that is neither sea nor burned
    low = preview.clamp_patch(np.array([[0.2]], np.float32),
                              np.array([[NODATA]], np.float32),
                              np.array([[1.0]], np.float32))
    assert low[0, 0] == 1.0, 'land below a metre was not lifted to one'
