"""danu.water.lassofit: the contours below the highest level a lasso picked,
laid again between the mainland's coast and that level, inside the lasso -
roantra's N43E029, whose 10, 20 and 30 m run out over a coast that doesn't
close in the open set.

The fixture's mainland: a coast running east along y = 0, land to the north;
10, 20 and 30 m waving across it every 400 m, 40 and 50 m keeping off it."""

import math

import pytest

pytest.importorskip('osgeo.ogr')
pytest.importorskip('osgeo.gdal')

from danu.checks import crossings
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet
from danu.water import lassofit

A = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
COAST = 4015


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def xy(n):
    return (n.lon - 125.5) * KX, (n.lat - LAT) * KY


def line(sq, wid, tags, pts):
    refs = []
    for x, y in pts:
        nid = -(len(sq.nodes) + 1)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    if pts[0] == pts[-1]:                      # a ring: closed onto its first node
        del sq.nodes[refs[-1]]
        refs[-1] = refs[0]
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


def wave(base, amp):
    return [(x, base + amp * math.sin(2 * math.pi * x / 400)) for x in range(-3000, 3001, 20)]


def contour(sq, wid, ele, pts):
    return line(sq, wid, {'contour': 'elevation', 'ele': f'{ele:g}'}, pts)


def circle(cx, cy, r, n=48, wobble=0.0):
    pts = [(cx + (r + wobble * math.sin(7 * 2 * math.pi * i / n)) * math.cos(2 * math.pi * i / n),
            cy + (r + wobble * math.sin(7 * 2 * math.pi * i / n)) * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def mainland():
    sq = Square(name=A, present=True, attrs={})
    w = WorkingSet(centre=A, size=1, squares={A: sq})
    line(sq, COAST, {'natural': 'coastline', 'ele': '0'}, [(x, 0.0) for x in range(-3000, 3001, 25)])
    contour(sq, -1, 10, wave(30, 50))
    contour(sq, -2, 20, wave(70, 80))
    contour(sq, -3, 30, wave(110, 115))
    contour(sq, -4, 40, [(x, 280.0) for x in range(-3000, 3001, 50)])
    contour(sq, -5, 50, [(x, 380.0) for x in range(-3000, 3001, 50)])
    return w, sq


def box(x0, y0, x1, y1):
    return [deg(x0, y0), deg(x1, y0), deg(x1, y1), deg(x0, y1)]


def pick(w, lasso):
    """As the editor's lasso with no filter: every node inside on a contour
    or a coastline."""
    (w0, s0), (e0, n0) = lasso[0], lasso[2]
    out = {}
    for name, sq in w.squares.items():
        ids = {r for way in sq.ways.values() for r in way.refs
               if w0 <= sq.nodes[r].lon <= e0 and s0 <= sq.nodes[r].lat <= n0}
        if ids:
            out[name] = ids
    return out


def fit(w, lasso):
    stack = edits.SetUndoStack()
    p = lassofit.plan(w, lasso, pick(w, lasso), stack.alloc)
    for s, step in p.steps:
        step.apply(s)
    return p


def inside(lasso, c):
    (w0, s0), (e0, n0) = lasso[0], lasso[2]
    return w0 <= c.lon <= e0 and s0 <= c.lat <= n0


def at(sq, ele):
    return [x for x in sq.ways.values() if x.tags.get('ele') == f'{ele:g}']


LASSO = box(-1000, -200, 1000, 320)          # the coast, 10-40 m; not 50


def test_the_levels_below_the_highest_picked_are_laid_between_the_coast_and_it():
    w, sq = mainland()
    before = crossings.find(w)
    assert any(inside(LASSO, c) for c in before), 'no test: nothing crosses in the lasso'
    p = fit(w, LASSO)
    assert p.upper == 40.0 and p.levels == {10.0, 20.0, 30.0} and p.dropped == 3, (p.upper, p.levels, p.refused)
    after = crossings.find(w)
    assert not [c for c in after if inside(LASSO, c)], 'still crossing in the lasso'
    assert len(after) < len(before)
    # in order between the coast and 40 m, across the middle of the lasso
    for ele in (10, 20, 30):
        ys = [xy(sq.nodes[r])[1] for x in at(sq, ele) for r in x.refs if abs(xy(sq.nodes[r])[0]) < 700]
        assert ys and 0 < min(ys) and max(ys) < 280, (ele, min(ys), max(ys))
    mid = [sum(ys) / len(ys) for ys in ([xy(sq.nodes[r])[1] for x in at(sq, e) for r in x.refs
                                         if abs(xy(sq.nodes[r])[0]) < 500] for e in (10, 20, 30))]
    assert mid[0] < mid[1] < mid[2], mid
    assert [x.id for x in at(sq, 40)] == [-4] and [x.id for x in at(sq, 50)] == [-5], 'what is above is kept'


def test_each_level_laid_is_joined_to_what_is_kept_of_it_outside_the_lasso():
    w, sq = mainland()
    fit(w, LASSO)
    for ele in (10, 20, 30):
        ways = at(sq, ele)
        assert len(ways) == 1, (ele, len(ways))
        xs = [xy(sq.nodes[r])[0] for r in ways[0].refs]
        assert min(xs) < -2900 and max(xs) > 2900, (ele, min(xs), max(xs))
        assert ways[0].tags == {'contour': 'elevation', 'ele': f'{ele:g}'}, 'its tags kept'


def test_one_step_undoes_it():
    w, sq = mainland()
    was = {wid: list(x.refs) for wid, x in sq.ways.items()}
    stack = edits.SetUndoStack()
    p = lassofit.plan(w, LASSO, pick(w, LASSO), stack.alloc)
    (s, step), = p.steps
    step.apply(s)
    assert {wid: list(x.refs) for wid, x in sq.ways.items()} != was
    step.undo(s)
    assert {wid: list(x.refs) for wid, x in sq.ways.items()} == was


def test_a_hill_inside_is_kept_and_laid_round():
    w, sq = mainland()
    hill = contour(sq, -6, 30, circle(300, 180, 30))
    p = fit(w, LASSO)
    assert -6 in sq.ways and sq.ways[-6].refs == hill.refs
    assert not [c for c in crossings.find(w) if inside(LASSO, c)]
    assert p.laid >= 3


def test_the_highest_level_picked_crossing_the_coast_is_refused():
    w, sq = mainland()
    lasso = box(-1000, -200, 1000, 240)      # up to 30 m, which crosses
    p = fit(w, lasso)
    assert not p.steps
    assert p.upper is None, 'the coast in the lasso said fitted'
    assert any('30 m, the highest level picked, crosses the coast' in why for why, _, _ in p.refused), p.refused


def test_an_island_wholly_in_the_lasso_is_fitted_as_an_island():
    w, sq = mainland()
    line(sq, 4016, {'natural': 'coastline', 'ele': '0'}, circle(0, -600, 100))
    contour(sq, -7, 10, circle(0, -600, 100, wobble=30))
    lasso = box(-1000, -800, 1000, 320)
    p = fit(w, lasso)
    assert p.islands == 1, p.refused
    assert not [c for c in crossings.find(w) if 4016 in (c.a[1], c.b[1])], 'the island still crossed'
    assert not [c for c in crossings.find(w) if inside(LASSO, c)]


def test_no_coastline_in_the_lasso_says_so():
    w, sq = mainland()
    lasso = box(-1000, 200, 1000, 320)
    p = fit(w, lasso)
    assert not p.steps and any('coastline' in why for why, _, _ in p.refused), p.refused


def test_the_upper_level_is_the_highest_picked():
    w, sq = mainland()
    assert lassofit.upper_of(w, pick(w, LASSO)) == 40.0
    assert lassofit.upper_of(w, pick(w, box(-1000, -200, 1000, 400))) == 50.0
    assert lassofit.upper_of(w, {A: {sq.ways[COAST].refs[0]}}) is None


def test_islands_fitted_and_the_coast_refused_say_so_apart():
    """The islands wholly in the lasso fitted, and the mainland's part
    refused: the plan is the islands', with no upper level of its own."""
    w, sq = mainland()
    line(sq, 4016, {'natural': 'coastline', 'ele': '0'}, circle(0, -600, 100))
    contour(sq, -7, 10, circle(0, -600, 100, wobble=30))
    p = fit(w, box(-1000, -800, 1000, 240))      # up to 30 m, which crosses the mainland's coast
    assert p.islands == 1 and p.steps
    assert p.upper is None
    assert any('crosses the coast' in why for why, _, _ in p.refused), p.refused
