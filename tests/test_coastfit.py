"""danu.water.coastfit: an island's low contours, run out past its coast,
laid again between the coast and the lowest contour that keeps off it -
roantra's N43E029, where 10, 20 and 30 m crossed the coast of every island
2,376 times and 40 m kept inside."""

import math

import pytest

ogr = pytest.importorskip('osgeo.ogr')
pytest.importorskip('osgeo.gdal')

from danu.checks import crossings  # noqa: E402
from danu.core import edits  # noqa: E402
from danu.core.square import Node, Square, SquareName, Way, WorkingSet  # noqa: E402
from danu.water import coastfit  # noqa: E402

A, B = SquareName(125, -23), SquareName(126, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540


def deg(x, y, lon0=125.5):
    return lon0 + x / KX, LAT + y / KY


def one():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def ring(sq, wid, r, tags, n=72, wobble=0.0, k=9, lon0=125.5, clockwise=False):
    """A ring of radius ``r`` m about the square's middle, its radius wobbling
    by ``wobble`` m ``k`` times round - closed onto its first node."""
    refs = []
    for i in range(n):
        a = 2 * math.pi * i / n * (-1 if clockwise else 1)
        rr = r + wobble * math.sin(k * a)
        nid = (max((abs(j) for j in sq.nodes), default=0) + 1) * (1 if wid > 0 else -1)
        lon, lat = deg(rr * math.cos(a), rr * math.sin(a), lon0)
        sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat)
        refs.append(nid)
    sq.ways[wid] = Way(id=wid, refs=refs + [refs[0]], tags=dict(tags))
    return sq.ways[wid]


def coast(sq, wid=4015, r=1000.0, **kw):
    return ring(sq, wid, r, {'natural': 'coastline', 'ele': '0'}, n=96, **kw)


def contour(sq, wid, ele, r, **kw):
    return ring(sq, wid, r, {'contour': 'elevation', 'ele': str(ele)}, **kw)


def island():
    """An island 1 km across: 10 m wholly at sea round it, 20 and 30 m in and
    out over its coast, 40 and 50 m inside."""
    w, sq = one()
    shore = coast(sq)
    contour(sq, -1, 10, 1080)
    contour(sq, -2, 20, 960, wobble=90)
    contour(sq, -3, 30, 900, wobble=150, k=7)
    contour(sq, -4, 40, 700)
    contour(sq, -5, 50, 500)
    return w, sq, shore


def apply(w, chosen):
    p = coastfit.plan(w, chosen, lambda s: edits.IdAllocator(s))
    for s, step in p.steps:
        step.apply(s)
    return p


def levels(sq):
    return sorted({float(x.tags['ele']) for x in sq.ways.values() if 'ele' in x.tags and 'natural' not in x.tags})


def radii(sq, ele):
    return [math.hypot((sq.nodes[r].lon - 125.5) * KX, (sq.nodes[r].lat - LAT) * KY)
            for x in sq.ways.values() if x.tags.get('ele') == f'{ele:g}' for r in x.refs]


def test_the_crossing_levels_are_laid_between_the_coast_and_the_first_kept_off_it():
    w, sq, shore = island()
    assert crossings.find(w), 'no test: nothing crosses'
    p = apply(w, [(sq, shore)])
    assert p.islands == 1 and p.tops == [40.0] and p.dropped == 3 and p.levels == {10.0, 20.0, 30.0}
    assert not crossings.find(w), 'still crossing'
    assert levels(sq) == [10.0, 20.0, 30.0, 40.0, 50.0]
    for ele in (10, 20, 30):
        r = radii(sq, ele)
        assert r and 700 < min(r) and max(r) < 1000, (ele, min(r), max(r))
    # in order, and evenly: the band's 300 m in four
    mid = [sum(radii(sq, e)) / len(radii(sq, e)) for e in (10, 20, 30)]
    assert mid[0] > mid[1] > mid[2]
    for want, got in zip((925, 850, 775), mid, strict=True):
        assert abs(got - want) < 25, mid
    assert sq.ways[-4].tags['ele'] == '40' and sq.ways[-5].tags['ele'] == '50', 'what kept off it is kept'


def test_the_lines_laid_are_closed_rings_and_one_step_undoes_them():
    w, sq, shore = island()
    before = {wid: list(x.refs) for wid, x in sq.ways.items()}
    p = coastfit.plan(w, [(sq, shore)], lambda s: edits.IdAllocator(s))
    (s, step), = p.steps
    step.apply(s)
    laid = [x for wid, x in sq.ways.items() if wid not in before]
    assert laid and all(x.refs[0] == x.refs[-1] for x in laid), 'a ring laid open'
    step.undo(s)
    assert {wid: list(x.refs) for wid, x in sq.ways.items()} == before


def test_a_valley_inland_beyond_what_is_kept_stays():
    """A 30 m hollow inside the 40 m ring is no part of the band."""
    w, sq, shore = island()
    contour(sq, -6, 30, 200)
    apply(w, [(sq, shore)])
    assert -6 in sq.ways


def test_an_islet_is_laid_up_to_its_highest_spot_height():
    w, sq = one()
    shore = coast(sq, r=300)
    contour(sq, -1, 10, 330, wobble=40)
    contour(sq, -2, 20, 250, wobble=80)
    lon, lat = deg(0, 0)
    sq.nodes[99] = Node(id=99, lon=lon, lat=lat, tags={'natural': 'peak', 'ele': '27'})
    p = apply(w, [(sq, shore)])
    assert p.tops == [27.0] and p.levels == {10.0, 20.0}
    assert not crossings.find(w)
    assert max(radii(sq, 10)) < 300 and max(radii(sq, 20)) < min(radii(sq, 10))


def test_an_islet_with_no_height_is_laid_up_to_the_next_level():
    w, sq = one()
    shore = coast(sq, r=300)
    contour(sq, -1, 10, 330, wobble=40)
    contour(sq, -2, 20, 250, wobble=80)
    p = apply(w, [(sq, shore)])
    assert p.tops == [30.0], 'the step between the levels that cross, above them'
    assert not crossings.find(w) and p.levels == {10.0, 20.0}


def test_a_coast_nothing_crosses_is_left_alone():
    w, sq = one()
    shore = coast(sq)
    contour(sq, -1, 10, 900)
    p = apply(w, [(sq, shore)])
    assert not p.steps and p.islands == 0 and not p.refused


def test_the_mainland_and_a_sea_drawn_round_are_refused():
    w, sq = one()
    ids = []
    for i, x in enumerate((-2000, 2000)):
        lon, lat = deg(x, 0)
        sq.nodes[500 + i] = Node(id=500 + i, lon=lon, lat=lat)
        ids.append(500 + i)
    main = Way(id=7, refs=ids, tags={'natural': 'coastline', 'ele': '0'})
    sq.ways[7] = main
    sea = coast(sq, wid=8, r=400, clockwise=True)
    p = coastfit.plan(w, [(sq, main), (sq, sea)], lambda s: edits.IdAllocator(s))
    whys = sorted(why for why, _, _ in p.refused)
    assert not p.steps and len(whys) == 2
    assert 'does not close in the open set' in whys[0] and 'clockwise' in whys[1]


def test_an_island_across_a_square_edge_is_laid_in_both_squares():
    a = Square(name=A, present=True, attrs={})
    b = Square(name=B, present=True, attrs={})
    w = WorkingSet(centre=A, size=1, squares={A: a, B: b})
    # an island about the edge at 126: its coastline in A, its contours cut
    # at the edge, a piece in each square
    shore = coast(a, lon0=126.0)
    # the contours as each square holds them: the half on its side
    for sq, keep in ((a, lambda lon: lon <= 126.0), (b, lambda lon: lon >= 126.0)):
        for wid, ele, r, kw in ((-11, 10, 1080, {}), (-12, 20, 960, {'wobble': 90}), (-14, 40, 700, {})):
            tmp = Square(name=sq.name, present=True, attrs={})
            x = ring(tmp, wid, r, {'contour': 'elevation', 'ele': str(ele)}, lon0=126.0, **kw)
            pts = [(tmp.nodes[r].lon, tmp.nodes[r].lat) for r in x.refs]
            run = [p for p in pts if keep(p[0])]
            base = max((abs(j) for j in sq.nodes), default=0) + 1
            refs = []
            for i, (lon, lat) in enumerate(run):
                sq.nodes[-(base + i)] = Node(id=-(base + i), lon=lon, lat=lat)
                refs.append(-(base + i))
            sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(x.tags))
    p = apply(w, [(a, shore)])
    assert p.islands == 1 and p.levels == {10.0, 20.0}
    assert any(x.tags.get('ele') == '10' for x in a.ways.values())
    assert any(x.tags.get('ele') == '10' for x in b.ways.values()), 'the half in the other square not laid'
    assert -14 in a.ways and -14 in b.ways
    for sq in (a, b):
        w0, s0, e0, n0 = sq.name.bounds
        assert all(w0 - 1e-9 <= sq.nodes[r].lon <= e0 + 1e-9 for x in sq.ways.values()
                   if x.tags.get('ele') in ('10', '20') for r in x.refs), 'a piece laid over the edge'


def test_a_crossing_level_under_a_kept_one_is_laid_again_below_it():
    """40 m crosses the coast and 50 m keeps inside: the top is 50, and 40 is
    laid with the levels under it - nothing that goes is lost."""
    w, sq = one()
    shore = coast(sq)
    contour(sq, -1, 10, 1080)
    contour(sq, -2, 20, 960, wobble=90)
    contour(sq, -4, 40, 900, wobble=150, k=7)
    contour(sq, -5, 50, 600)
    p = apply(w, [(sq, shore)])
    assert p.tops == [50.0] and p.levels == {10.0, 20.0, 40.0}
    assert not crossings.find(w)
    assert levels(sq) == [10.0, 20.0, 40.0, 50.0]


def test_a_contour_at_sea_crossing_another_island_is_left_to_that_one():
    w, sq = one()
    shore = coast(sq, r=500)
    contour(sq, -1, 10, 520, wobble=40)                       # this island's, over its coast
    # another island east, its own 10 m out over its coast and within 150 m of this one
    other = ring(sq, 4016, 120, {'natural': 'coastline', 'ele': '0'}, n=48, lon0=125.5 + 700 / KX)
    theirs = ring(sq, -2, 140, {'contour': 'elevation', 'ele': '10'}, wobble=30, lon0=125.5 + 700 / KX)
    p = apply(w, [(sq, shore)])
    assert p.islands == 1 and theirs.id in sq.ways and other.id in sq.ways
