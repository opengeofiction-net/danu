"""Spot heights as constraints - G1.

R36 says a node carrying ``ele`` is a constraint the same as a contour way, and
until now nothing had ever read one: ``collect`` gathered only the lines layer,
and GDAL's own default lists ``ele`` among ``[points]``'s ``unsignificant``
keys, so a node tagged with nothing else was not reported at all.

R37 is why it matters. Contours can only bracket a hilltop - the ground inside
the top ring is somewhere above that ring and below the next one that was never
drawn - so a fill has no reason to put a summit anywhere in that band and does
not. It leaves a plateau. A spot height is the only thing that can say how high
the hill goes.

The hill here is four concentric rings and nothing else, which is the smallest
case that shows it.
"""

import math
import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

LON, LAT = 125.5, -23.5                      # the middle of square S24E125
RINGS = [(0.30, 100), (0.22, 125), (0.14, 150), (0.06, 175)]   # radius in degrees, metres
TOP = RINGS[-1][1]


def a_hill(spot=None, rings=RINGS):
    """Concentric contour rings, and optionally one node carrying ``ele``.

    ``spot`` is (lon, lat, ele) - a string ele is written as given, so a test
    can put something that is not a number there.
    """
    import numpy as np

    from danu.core import edits
    from danu.core.square import Node, Square, SquareName

    sq = Square(name=SquareName(125, -24), present=True,
                attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for r, ele in rings:
        pts = [(LON + r * math.cos(t), LAT + r * math.sin(t))
               for t in np.linspace(0, 2 * math.pi, 73)]
        pts[-1] = pts[0]
        ids = [alloc.take() for _ in pts[:-1]]
        edits.AddWay(alloc.take(), ids + [ids[0]], pts[:-1] + [pts[0]],
                     {'ele': str(ele)}).apply(sq)
    if spot is not None:
        lon, lat, ele = spot
        nid = alloc.take()
        sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat, tags={'ele': str(ele)})
    return sq


def built(sq, tmp_path, name='b', keep_pass1=False):
    """The square built, as (dem, drawn mask, geotransform, result)."""
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / name / 'zone'
    zone.mkdir(parents=True)
    write_square(sq, zone / 'S24E125.osm.xz')
    result = build.build_dem(zone, tmp_path / name / 'w', sp.load().with_arcsec(3),
                             keep_pass1=keep_pass1)
    assert result.dem is not None, 'the hill built nothing'
    ds = gdal.Open(str(result.dem))
    dem = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    del ds
    mds = gdal.Open(str(result.drawn_mask))
    mask = mds.GetRasterBand(1).ReadAsArray() > 0
    del mds
    return dem, mask, gt, result


def summit(dem, gt, cells=40):
    """The highest ground near the middle of the hill, and the flat top's size
    - how many cells there read the same as the peak."""
    import numpy as np
    cx = int((LON - gt[0]) / gt[1])
    cy = int((LAT - gt[3]) / gt[5])
    win = dem[cy - cells:cy + cells, cx - cells:cx + cells]
    peak = float(win.max())
    return peak, int(np.isclose(win, peak).sum()), float(dem[cy, cx])


def test_contours_alone_leave_a_hill_flat_on_top(tmp_path):
    """R37's premise, and the reason the rest of this file exists. The fill
    has nothing above the top ring to aim at, so the whole inside of it comes
    out at the ring's own value."""
    dem, _, gt, _ = built(a_hill(), tmp_path)
    peak, flat, centre = summit(dem, gt)
    assert peak == pytest.approx(TOP, abs=0.5), f'the hill peaks at {peak}, not at the top ring'
    assert centre == pytest.approx(TOP, abs=0.5)
    assert flat > 500, f'only {flat} cells are at the peak; this hill is not flat-topped'


def test_a_spot_height_puts_the_summit_at_its_own_value(tmp_path):
    """G1's exit criterion: a hill with a spot height on it comes out pointed,
    with the spot height's own value at the summit."""
    dem, _, gt, _ = built(a_hill((LON, LAT, 240)), tmp_path)
    peak, flat, centre = summit(dem, gt)
    assert centre == pytest.approx(240, abs=0.5), f'the summit reads {centre}, not the spot height'
    assert peak == pytest.approx(240, abs=0.5), 'something is higher than the spot height'
    assert flat < 20, f'{flat} cells are at the peak; the summit is a plateau, not a point'


def test_the_ground_falls_away_from_the_spot_height(tmp_path):
    """Pointed means more than one high cell: the ground has to descend from
    the summit to the ring it stands inside. A test that only read the summit
    would pass on a spot height burned into an otherwise flat plateau."""
    import numpy as np
    dem, _, gt, _ = built(a_hill((LON, LAT, 240)), tmp_path)
    cx = int((LON - gt[0]) / gt[1])
    cy = int((LAT - gt[3]) / gt[5])
    out = dem[cy, cx:cx + 60]                     # due east, from the summit
    assert out[0] == pytest.approx(240, abs=0.5)
    drops = np.diff(out.astype(float))
    assert (drops <= 0.001).all(), 'the ground rises somewhere on the way down the hill'
    assert out[-1] < 200, f'sixty cells out it is still at {out[-1]}'


def test_a_spot_height_wins_the_cell_it_shares_with_a_contour(tmp_path):
    """The rasterise order. A contour says the ground reaches this height
    somewhere along here; a spot height says it is exactly this high at this
    point, and the point is the more specific statement."""
    on_the_ring = (LON + RINGS[-1][0], LAT, 400)
    _, _, _, result = built(a_hill(on_the_ring), tmp_path)
    ds = gdal.Open(str(result.constraints))
    cons = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    del ds
    x = int((on_the_ring[0] - gt[0]) / gt[1])
    y = int((on_the_ring[1] - gt[3]) / gt[5])
    assert cons[y, x] == 400, (
        f'the cell reads {cons[y, x]}: the contour was burned over the spot height')


def test_a_node_whose_ele_is_not_a_number_is_dropped(tmp_path):
    """Squares carry ``ele=TBD`` on lake outlines and ``ele=tbd`` on peaks, and
    rasterising coerces each of them to 0 - a sea level constraint planted on a
    hilltop, which is worse than no constraint at all. The ways have been
    cleaned since the pipeline moved; the nodes are new and need the same."""
    dem, _, gt, result = built(a_hill((LON, LAT, 'tbd')), tmp_path)
    ds = gdal.Open(str(result.constraints))
    cons = ds.GetRasterBand(1).ReadAsArray()
    cgt = ds.GetGeoTransform()
    del ds
    x = int((LON - cgt[0]) / cgt[1])
    y = int((LAT - cgt[3]) / cgt[5])
    from danu.surface.build import NODATA
    assert cons[y, x] == NODATA, f'ele=tbd was burned as {cons[y, x]}'
    peak, _, centre = summit(dem, gt)
    assert centre == pytest.approx(TOP, abs=0.5), 'the hill is not the one contours alone give'


def test_the_point_barrier_costs_no_reach(tmp_path):
    """The spec said measure this first. ``barrier_cells`` widens a constraint
    for the sight test, so a one-cell spot height becomes a five by five
    occluder - a contour is a line and hardly notices, a point is not.

    Measured three ways on this hill: a spot on the summit, one standing alone
    between two rings where rays have to pass it, and one outside every contour.
    No cell loses its reach in any of them, and the summit one *gains* reach for
    the disc of cells that can now see something. Class 1 is 'nothing in reach',
    and the classes are not a severity ranking - 3 is 'a single level in sight',
    0 is answered - so this counts the class it means rather than comparing
    numbers.
    """
    from danu.surface import build
    from danu.surface import params as sp

    p = sp.load().with_arcsec(3)

    def classes(sq, name):
        dem, mask, gt, result = built(sq, tmp_path, name=name, keep_pass1=True)
        path = build.first_pass_classes(result.constraints, result.drawn_mask, p,
                                        tmp_path / name / 'w')
        ds = gdal.Open(str(path))
        c = ds.GetRasterBand(1).ReadAsArray()
        del ds
        return c, mask

    base, base_mask = classes(a_hill(), 'base')
    # least the spot is expected to *gain*, where it stands on ground that had
    # nothing in reach: a disc of the fill's radius is 1,257 cells at 20. The
    # one outside the contours is on ground the base build never masked in, so
    # there is nothing of it to compare and its floor is 0
    for name, spot, least_gain in (('summit', (LON, LAT, 200), 1000),
                                   ('between', (LON + 0.18, LAT, 140), 1000),
                                   ('outside', (LON + 0.45, LAT, 60), 0)):
        c, mask = classes(a_hill(spot), name)
        both = base_mask & mask
        lost = int(((base != 1) & (c == 1) & both).sum())
        gained = int(((base == 1) & (c != 1) & both).sum())
        assert lost == 0, f'{name}: {lost} cells lost every constraint in reach to the occluder'
        assert gained >= least_gain, (
            f'{name}: the spot height gave reach to {gained} cells, not the disc it should')


def test_a_spot_height_outside_the_contours_joins_the_envelope(tmp_path):
    """Pinned because it is a decision, not an accident. ``drawn_area`` takes
    the convex hull of the constraints raster per degree square, and a spot
    height is in that raster - so one placed beyond the contours stretches the
    hull and the ground between is filled.

    That follows from R36 reading a spot height as a constraint *the same as a
    contour way*, and a contour way out there would stretch the hull too. The
    alternative - the envelope being the contour lines' alone, with spot heights
    constraining inside it but never extending it - is coherent as well, since
    isofill counts constraints outside the mask as evidence either way. This
    says which one is in force.
    """
    _, inside, _, _ = built(a_hill((LON, LAT, 200)), tmp_path, name='in')
    _, outside, _, _ = built(a_hill((LON + 0.45, LAT, 60)), tmp_path, name='out')
    _, plain, _, _ = built(a_hill(), tmp_path, name='plain')
    assert int(inside.sum()) == int(plain.sum()), (
        'a spot height inside the contours changed the envelope')
    assert int(outside.sum()) > int(plain.sum()) * 1.1, (
        'a spot height beyond the contours did not stretch the envelope')


def test_the_scan_counts_every_ele_outside_a_way_element(tmp_path):
    """What the guard's count is, exactly, because it is looser than its name
    and the looseness is the thing to be clear about.

    It counts ``ele`` tags not inside a ``way`` element. The fixture holds both
    kinds that land there: ``-4``, which no way references and is a spot height
    in anybody's reading; and ``-1`` and ``-2``, which carry ``ele`` and are
    also nodes of the contour way, written before it as OSM XML always writes
    them. All three count. That is right for the guard, which is only asking
    whether a square had anything the points layer should have reported - and
    all three are reported, since ``ele`` is significant there now.

    The real fixture has no node carrying ``ele`` at all, so this is the only
    place the count is exercised.
    """
    from danu.surface.build import _way_counts

    path = tmp_path / 'square.osm'
    path.write_text(
        '<?xml version="1.0"?>\n<osm version="0.6">'
        '<node id="-1" lat="-23.5" lon="125.5"><tag k="ele" v="225"/></node>'
        '<node id="-2" lat="-23.4" lon="125.5"><tag k="ele" v="230"/></node>'
        '<node id="-3" lat="-23.3" lon="125.5"/>'
        '<node id="-4" lat="-23.2" lon="125.5"><tag k="ele" v="240"/></node>'
        '<way id="-9"><nd ref="-1"/><nd ref="-2"/><tag k="ele" v="100"/></way>'
        '</osm>')
    assert _way_counts(path) == (0, 0, 2, 1, 3)
    # and the same however the reads fall, since a token split across a block
    # boundary is the way a scan like this goes wrong
    for chunk in (7, 13, 64):
        assert _way_counts(path, chunk=chunk) == (0, 0, 2, 1, 3), f'lost a token at chunk {chunk}'



@pytest.mark.parametrize('where,ele', [
    ('summit', 240),                      # clear of every contour
    ('on the ring', 400),                 # sharing a cell with one, so the burn order shows
])
def test_a_preview_over_a_spot_height_burns_what_the_build_burns(tmp_path, where, ele):
    """The preview burns a box from its own layer, clearing it to nodata first
    - so a box over a hilltop would hand the solve a raster with no summit in
    it, and the hill would flatten under the cursor until the exact rebuild.

    Asserted as the whole box matching the build's constraints, not just the
    one cell: that covers the burn order too, which is why one of these cases
    puts the spot height on a contour. The preview agreeing with the build is
    the preview's whole premise.

    Spot heights are not editable yet - that is G2 - so the layer is read-only
    here.
    """
    from danu.surface import preview
    from danu.surface.build import NODATA
    from danu.surface.local import Box

    lon = LON if where == 'summit' else LON + RINGS[-1][0]
    _, _, _, result = built(a_hill((lon, LAT, ele)), tmp_path)
    ds = gdal.Open(str(result.constraints))
    cgt = ds.GetGeoTransform()
    whole = ds.GetRasterBand(1).ReadAsArray()
    del ds
    x = int((lon - cgt[0]) / cgt[1])
    y = int((LAT - cgt[3]) / cgt[5])
    assert whole[y, x] == ele, 'the build did not put the spot height there'

    box = Box(x - 30, y - 30, x + 30, y + 30)
    burned = preview.Contours(result.contours_gpkg).burn(cgt, box, NODATA)
    assert burned[y - box.y0, x - box.x0] == ele, (
        'the preview burned a box over the spot height and lost it')
    assert (burned == whole[box.slice]).all(), 'the preview and the build disagree over this box'


def test_a_spot_height_in_a_later_square_still_makes_the_layer(tmp_path):
    """The spot layer is created by whichever square first contributes one,
    which need not be the first square read - and that square's translate is an
    append to a GeoPackage that has no such layer yet. The contour path never
    exercises this, because it creates its layer on square one whatever that
    square holds.

    Which square is read first is not incidental here, and it is not left to a
    dict either: ``collect`` walks ``sorted(squares.items())`` and ``SquareName``
    is ordered, so S24E125 goes before S24E126 and the spot layer cannot be
    created until the second translate. The assertion below says so rather than
    trusting the comment, because a test that silently stopped exercising this
    path would keep passing.

    What this holds is that the later square's spot height reaches the raster.
    ``collect`` passes no ``geometryType`` on that translate; it used to, and
    the option came out again when removing it changed no test - including this
    one, and including the single-square cases above, which are the first
    square contributing. An append creates the layer with the geometry the OSM
    driver's points layer has.
    """
    from danu.core import edits
    from danu.core.square import Node, SquareName, write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    # S24E125 first, by name, with contours and no spot height
    write_square(a_hill(), zone / 'S24E125.osm.xz')
    # and its eastern neighbour, which has one
    east = a_hill(rings=[(0.10, 300)])
    east.name = SquareName(126, -24)
    for node in east.nodes.values():
        node.lon += 1.0
    nid = edits.IdAllocator(east).take()
    east.nodes[nid] = Node(id=nid, lon=LON + 1.0, lat=LAT, tags={'ele': '400'})
    write_square(east, zone / 'S24E126.osm.xz')

    # the order collect will read them in, and that the spot height is in the
    # second one: both halves of what this test is for
    assert sorted(result_names := [SquareName(125, -24), SquareName(126, -24)]) == result_names
    assert not any('ele' in n.tags for n in a_hill().nodes.values())

    result = build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3))
    assert result.dem is not None
    ds = gdal.Open(str(result.constraints))
    cons = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    del ds
    x = int((LON + 1.0 - gt[0]) / gt[1])
    y = int((LAT - gt[3]) / gt[5])
    assert cons[y, x] == 400, (
        f"the second square's spot height reads {cons[y, x]}: the layer was never made")


def test_dropping_a_nodes_bad_ele_is_said_out_loud(tmp_path):
    """The guard that warns when a square holds ``ele`` outside a way and
    contributes no spot height runs before the non-numeric rows are dropped, so
    a square whose only spot height is ``ele=tbd`` passes it. That is not a
    silent loss, because the cleanup says so itself - which is what this holds,
    since the two together are the whole of what a mapper gets told.
    """
    from danu.core.square import write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(a_hill((LON, LAT, 'tbd')), zone / 'S24E125.osm.xz')
    said = []
    build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3), log=said.append)
    assert any('ignoring nodes whose ele is not a number' in line and 'tbd' in line
               for line in said), f'nothing said that the node was dropped: {said}'


def test_burning_the_spot_heights_does_not_wipe_the_contours(tmp_path):
    """``rasterise`` burns the two layers in two calls, the second into the
    raster the first created. It passes no ``initValues`` there, which is what
    makes that an addition rather than a fresh start - and if it were ever a
    fresh start the contours would vanish and only the spot heights remain.

    The hill tests would catch that too, by the ground no longer falling away
    from the summit, but they would catch it as a strange-looking surface. This
    catches it as the thing it is.
    """

    from danu.surface.build import NODATA

    _, _, _, plain = built(a_hill(), tmp_path, name='plain')
    _, _, _, spotted = built(a_hill((LON, LAT, 240)), tmp_path, name='spotted')

    def constraints(result):
        ds = gdal.Open(str(result.constraints))
        a = ds.GetRasterBand(1).ReadAsArray()
        del ds
        return a

    before, after = constraints(plain), constraints(spotted)
    kept = (before != NODATA)
    assert int(kept.sum()) > 1000, 'the rings burned nothing to keep'
    assert (after[kept] == before[kept]).all(), (
        'the second burn changed cells the contours had written')
    added = int((after != NODATA).sum()) - int(kept.sum())
    assert added == 1, f'the spot height added {added} constraint cells, not one'


def test_the_preview_copies_the_spot_layers_own_geometry_type(tmp_path):
    """The preview re-creates the build's layers in memory to burn from, and a
    copy that declares a different geometry from the source is a preview
    burning a different shape - the one divergence this arrangement exists to
    prevent. Taken from the source rather than named again."""
    from osgeo import ogr

    from danu.surface import preview

    _, _, _, result = built(a_hill((LON, LAT, 240)), tmp_path)
    src = ogr.Open(str(result.contours_gpkg))
    want = src.GetLayer('spot').GetGeomType()
    del src
    contours = preview.Contours(result.contours_gpkg)
    assert contours.spots is not None, 'the preview did not pick the spot layer up'
    assert contours.spots.GetGeomType() == want, (
        f'the preview calls the spot layer {contours.spots.GetGeomType()} '
        f'where the build has {want}')


def test_a_square_of_nothing_but_spot_heights_builds(tmp_path):
    """``collect`` returns a GeoPackage when either layer has features, so a
    set with spot heights and no contour ways is a thing that reaches
    ``rasterise``. It arrives as both layers even so - the lines translate runs
    for every square and creates ``contour`` on the first, empty if that square
    had none - which is what makes ``rasterise``'s first call the contour one
    whatever the squares hold.
    """
    from osgeo import ogr

    from danu.core import edits
    from danu.core.square import Node, Square, SquareName, write_square
    from danu.surface import build
    from danu.surface import params as sp

    sq = Square(name=SquareName(125, -24), present=True,
                attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for lon, lat, ele in ((LON - 0.1, LAT - 0.1, 300), (LON + 0.1, LAT + 0.1, 350)):
        nid = alloc.take()
        sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat, tags={'ele': str(ele)})
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(sq, zone / 'S24E125.osm.xz')

    said = []
    result = build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3), log=said.append)
    assert result.dem is not None, f'a square of spot heights built nothing: {said}'
    assert any('2 spot heights' in line for line in said)

    ds = ogr.Open(str(result.contours_gpkg))
    names = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]
    del ds
    assert names[0] == 'contour' and 'spot' in names, (
        f'{names}: rasterise would not be creating the raster from the contour layer')

    cds = gdal.Open(str(result.constraints))
    cons = cds.GetRasterBand(1).ReadAsArray()
    gt = cds.GetGeoTransform()
    del cds
    x = int((LON - 0.1 - gt[0]) / gt[1])
    y = int((LAT - 0.1 - gt[3]) / gt[5])
    assert cons[y, x] == 300, f'the spot height reads {cons[y, x]}'
