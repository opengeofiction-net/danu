"""The sea mask's seeds: a land seed left of every coastline segment, a sea
seed right of it - and none that the step to it carries across a coastline.

The case that found it is gobras' N20E086 after the main map's coast was
imported: two islets a hundred metres off the shore, closer than SIDE_STEP,
put their sea seeds on the mainland, nearer the ground behind it than the
shore's own land seeds, and that ground went to the sea in a cone five
kilometres long.
"""

import numpy as np
import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
ogr = pytest.importorskip('osgeo.ogr', reason='GDAL not available')

from danu.surface import sea_mask  # noqa: E402

RES = 3 / 3600
GT = (125 - RES / 2, RES, 0.0, -23 + RES / 2, 0.0, -RES)
ROWS, COLS = 200, 240
SHORE = 60                  # the mainland's shore, a row: land north of it, sea south


def layer(tmp_path, *lines):
    """A GeoPackage of coastline as the build collects it, each line given in
    (col, row), and its layer filtered to the coastline as the mask reads it."""
    path = tmp_path / 'contours.gpkg'
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    lyr = ds.CreateLayer('contour', geom_type=ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn('natural', ogr.OFTString))
    for points in lines:
        g = ogr.Geometry(ogr.wkbLineString)
        for c, r in points:
            g.AddPoint_2D(GT[0] + c * GT[1], GT[3] + r * GT[5])
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField('natural', 'coastline')
        f.SetGeometry(g)
        lyr.CreateFeature(f)
    ds = None
    return path


def shore():
    """West to east along SHORE, so the sea is to the south."""
    return [(c, SHORE + 0.3) for c in range(-5, COLS + 6, 3)]


def islet(c0, r0, size):
    """A small square island, counter-clockwise on the map - clockwise in
    rows - so land is on its left."""
    return [(c0, r0), (c0, r0 + size), (c0 + size, r0 + size), (c0 + size, r0), (c0, r0)]


def seeds(path):
    src = ogr.Open(str(path))
    lyr = src.GetLayer(0)
    gone = []
    water, land = sea_mask.seed_points(lyr, GT, gone)
    return np.array(water), np.array(land), gone


def test_a_plain_coast_keeps_every_seed():
    """Nothing the step crosses, nothing dropped: the mask is what it was."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as d:
        water, land, gone = seeds(layer(Path(d), shore()))
    assert gone == [0, 0] and len(water) == len(land) > 50
    assert (water[:, 1] > SHORE).all() and (land[:, 1] <= SHORE).all()


def test_an_islet_closer_to_the_shore_than_the_step_puts_no_sea_seed_on_the_land(tmp_path, monkeypatch):
    """Half a step off the shore, a cell across: its north side's sea seeds
    used to land north of the shore, on the mainland."""
    path = layer(tmp_path, shore(), islet(100, SHORE + 1.3, 1.2))
    water, land, gone = seeds(path)
    assert gone[0] > 0 and (water[:, 1] > SHORE).all(), 'a sea seed on the mainland'
    assert (land[:, 1] <= SHORE + 3).all()
    with monkeypatch.context() as m:
        m.setattr(sea_mask, '_odd_crossings', lambda segs, own, probes, **k: np.zeros(len(probes), bool))
        every, _, _ = seeds(path)
    assert (every[:, 1] < SHORE).any(), 'the fixture must step a sea seed across the shore'


def coast(tmp_path):
    """The real thing: N20E086's coastline round the two islets, on a 3"
    grid over it, as the build's own GeoPackage and reference raster."""
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).parent / 'golden' / 'n20e086-coast.json').read_text())
    west, south, east, north = data['box']
    # the build's grid: a cell centred on every whole degree, every 3",
    # which is where each seed's truncation to a cell falls
    res = 3 / 3600
    gt = (west - res / 2, res, 0.0, north + res / 2, 0.0, -res)
    cols, rows = round((east - west) / res), round((north - south) / res)
    path = tmp_path / 'coast.gpkg'
    ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
    lyr = ds.CreateLayer('contour', geom_type=ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn('natural', ogr.OFTString))
    for line in data['lines']:
        g = ogr.Geometry(ogr.wkbLineString)
        for lon, lat in line['points']:
            g.AddPoint_2D(lon, lat)
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField('natural', 'coastline')
        f.SetGeometry(g)
        lyr.CreateFeature(f)
    ds = None
    ref = tmp_path / 'coast-ref.tif'
    r = gdal.GetDriverByName('GTiff').Create(str(ref), cols, rows, 1, gdal.GDT_Byte)
    r.SetGeoTransform(gt)
    r = None
    return path, ref, gt


# along the bloom: from the islets north-west, two to five kilometres inland
BLOOM = [(86.6873, 20.8145), (86.6773, 20.8205), (86.6673, 20.8265), (86.6573, 20.8325)]


def sea_at(tmp_path, path, ref, gt, points):
    out = tmp_path / 'coast-mask.tif'
    assert sea_mask.sea_mask(str(path), str(ref), str(out))
    a = gdal.Open(str(out)).ReadAsArray()
    return [bool(a[int((lat - gt[3]) / gt[5]), int((lon - gt[0]) / gt[1])]) for lon, lat in points]


def test_the_bloom_behind_n20e086s_islets_is_land(tmp_path):
    path, ref, gt = coast(tmp_path)
    assert sea_at(tmp_path, path, ref, gt, BLOOM) == [False] * len(BLOOM)


def test_without_the_drop_the_islets_take_the_land_behind_for_the_sea(tmp_path, monkeypatch):
    """The fixture is the failure: every seed kept, the ground behind the
    islets reads as sea - which is what makes the test above worth having."""
    monkeypatch.setattr(sea_mask, '_odd_crossings', lambda segs, own, probes, **k: np.zeros(len(probes), bool))
    path, ref, gt = coast(tmp_path)
    assert sea_at(tmp_path, path, ref, gt, BLOOM) == [True] * len(BLOOM)


def test_the_buckets_find_what_a_test_against_every_segment_finds():
    """The crossing test files segments in buckets; that it misses none is
    held against the same test made against every segment, on random lines."""
    rng = np.random.default_rng(7)
    walk = np.cumsum(rng.normal(0, 1.5, (400, 2)), axis=0) + 50
    segs = np.concatenate([walk[:-1], walk[1:]], axis=1)
    segs = segs[(segs[:, :2] != segs[:, 2:]).any(1)]
    own = rng.integers(0, len(segs), 3000)
    start = (segs[own, :2] + segs[own, 2:]) / 2
    probes = np.concatenate([start, start + rng.normal(0, 3, (3000, 2))], axis=1)
    got = sea_mask._odd_crossings(segs, own, probes, chunk=700)

    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    want = []
    for i, p in enumerate(probes):
        a, b = segs[:, :2], segs[:, 2:]
        hit = ((orient(p[None, :2], p[None, 2:], a) > 0) != (orient(p[None, :2], p[None, 2:], b) > 0)) & (
            (orient(a, b, p[None, :2]) > 0) != (orient(a, b, p[None, 2:]) > 0))
        hit[own[i]] = False
        want.append(hit.sum() % 2 == 1)
    assert got.tolist() == want and 0 < got.sum() < len(got)


def test_a_step_through_a_vertex_crosses_the_line_once():
    """A probe straight through the vertex two segments share crosses the
    line - one of the two, by the half-open rule, and not both or neither."""
    segs = np.array([[0, 10, 10, 10],             # its own segment
                     [0, 11.5, 5, 11.5], [5, 11.5, 10, 11.5],     # a line, its vertex in the way
                     [0, 20, 5, 13], [5, 13, 10, 20]])            # a vee it touches the point of
    probes = np.array([[5, 10, 5, 12.5], [5, 12.5, 5, 13]])
    got = sea_mask._odd_crossings(segs, np.array([0, 0]), probes)
    assert got.tolist() == [True, False]
