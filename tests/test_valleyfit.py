"""danu.water.valleyfit: a valley's levels laid again in a lasso, off a
surface its river is the floor of - roantra's N43E029, whose 20, 30 and 40 m
stop short of where they should run up the Xoltzogo, with a chain of hollows
at their levels up the river beyond.

The fixture: a valley rising east along a river on y = 0; each level a
tongue pointing up it, stopping short, and two rings of it further up, as a
coarse DEM leaves them; 50 m kept above. No Qt."""

import math

import pytest

pytest.importorskip('osgeo.ogr')

from osgeo import ogr

from danu.checks import crossings
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet
from danu.water import valleyfit

A = SquareName(125, -23)
LAT = -22.5
KX, KY = 111320 * math.cos(math.radians(LAT)), 110540
RIVER = 9000
TIPS = {20: 0, 30: 600, 40: 1200, 50: 1900}      # where each tongue stops short
RINGS = {20: (-201, -202), 30: (-301, -302), 40: (-401, -402)}


def deg(x, y):
    return 125.5 + x / KX, LAT + y / KY


def xy(n):
    return (n.lon - 125.5) * KX, (n.lat - LAT) * KY


def way(sq, wid, tags, pts):
    refs = []
    for x, y in pts:
        nid = -(len(sq.nodes) + 1000)
        sq.nodes[nid] = Node(id=nid, lon=deg(x, y)[0], lat=deg(x, y)[1])
        refs.append(nid)
    if pts[0] == pts[-1]:
        del sq.nodes[refs[-1]]
        refs[-1] = refs[0]
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


def contour(sq, wid, ele, pts):
    return way(sq, wid, {'contour': 'elevation', 'ele': f'{ele:g}'}, pts)


def ring(cx, cy, rx, ry, n=10):
    pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return pts + [pts[0]]


def tongue(tip, half=40.0, spread=0.12, far=-3000):
    """A level up the valley from the west to a tip at x, and back."""
    north = [(x, half + spread * (tip - x)) for x in range(far, int(tip) + 1, 100)]
    return north + [(tip + half, 0.0)] + [(x, -y) for x, y in reversed(north)]


def valley():
    sq = Square(name=A, present=True, attrs={})
    w = WorkingSet(centre=A, size=1, squares={A: sq})
    way(sq, RIVER, {'waterway': 'river', 'name': 'Test'}, [(x, 0.0) for x in range(-3000, 3001, 50)])
    for ele, tip in TIPS.items():
        contour(sq, ele, ele, tongue(tip))
    for ele, (a, b) in RINGS.items():
        tip = TIPS[ele]
        contour(sq, a, ele, ring(tip + 180, 0, 50, 22))
        contour(sq, b, ele, ring(tip + 340, 0, 50, 22))
    return w, sq


LASSO = [deg(-600, -500), deg(1750, -500), deg(1750, 500), deg(-600, 500)]


def picked(sq, lasso=LASSO, lo=20, hi=40):
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in [*lasso, lasso[0]]:
        r.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(r)
    out = set()
    for w in sq.ways.values():
        if w.ele is None or not lo <= w.ele <= hi:
            continue
        for i in w.refs:
            p = ogr.Geometry(ogr.wkbPoint)
            p.AddPoint_2D(sq.nodes[i].lon, sq.nodes[i].lat)
            if poly.Contains(p):
                out.add(i)
    return {A: out}


def fit(w, sq, **kw):
    p = valleyfit.plan(w, LASSO, picked(sq), edits.SetUndoStack().alloc, **kw)
    for s, step in p.steps:
        step.apply(s)
    return p


def crossings_of_river(sq, ele):
    """Where the river meets the lines of a level: x, metres."""
    river = ogr.Geometry(ogr.wkbLineString)
    for r in sq.ways[RIVER].refs:
        river.AddPoint_2D(*xy(sq.nodes[r]))
    out = []
    for w in sq.ways.values():
        if w.ele != ele:
            continue
        g = ogr.Geometry(ogr.wkbLineString)
        for r in w.refs:
            g.AddPoint_2D(*xy(sq.nodes[r]))
        x = river.Intersection(g)
        pts = [x.GetGeometryRef(i).GetPoint_2D() for i in range(x.GetGeometryCount())] if x.GetGeometryCount() \
            else ([x.GetPoint_2D()] if not x.IsEmpty() else [])
        out += [p[0] for p in pts]
    return sorted(out)


def test_the_profile_places_each_level_at_its_furthest_upstream():
    w, sq = valley()
    pts = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in sq.ways[RIVER].refs]
    contours = []
    for wy in sq.ways.values():
        if wy.ele is not None:
            g = ogr.Geometry(ogr.wkbLineString)
            for r in wy.refs:
                g.AddPoint_2D(sq.nodes[r].lon, sq.nodes[r].lat)
            contours.append((wy.ele, g))
    window = ogr.CreateGeometryFromWkt('POLYGON ((124 -24, 127 -24, 127 -21, 124 -21, 124 -24))')
    hs = valleyfit.profile(pts, contours, valleyfit._Proj(LAT), window, 10.0)
    at = {round(xy(sq.nodes[r])[0]): h for r, h in zip(sq.ways[RIVER].refs, hs, strict=True)}
    # 20 m reaches up to its second ring's far end, 0 + 340 + 50
    assert at[350] < 20 < at[400], (at[350], at[400])
    assert at[950] < 30 < at[1000], (at[950], at[1000])            # 30 m to 600 + 390
    assert all(at[x] <= at[x + 50] + 1e-9 for x in range(-3000, 2950, 50)), 'not rising up the valley'
    assert at[-3000] >= 15.0, 'fell more than half a step below the lowest level crossed'


def test_the_levels_run_up_the_valley_past_their_splinters():
    w, sq = valley()
    assert crossings_of_river(sq, 20)
    p = fit(w, sq)
    assert p.refused is None and p.steps, p.refused
    assert p.levels == [20.0, 30.0, 40.0] and p.rivers == ['Test']
    assert p.splinters == 6 and not [i for ids in RINGS.values() for i in ids if i in sq.ways]
    assert not p.pinched, p.pinched
    assert not crossings.find(w)
    for ele in (20, 30, 40):
        xs = crossings_of_river(sq, ele)
        assert len(xs) == 1, (ele, xs)                       # one V, not a tip and rings
        assert xs[0] > TIPS[ele] + 340 + 50 - 20, (ele, xs)   # up past the last of its rings


def test_what_is_above_and_the_sides_are_held():
    w, sq = valley()
    above = list(sq.ways[50].refs)
    side = {r for r in sq.ways[20].refs if abs(xy(sq.nodes[r])[1]) > 150}
    coords = {(round(xy(sq.nodes[r])[0]), round(xy(sq.nodes[r])[1])) for r in side}
    fit(w, sq)
    assert sq.ways[50].refs == above, 'the level above moved'
    now = {(round(xy(n)[0]), round(xy(n)[1])) for n in sq.nodes.values()}
    assert coords <= now, 'the valley side not held where it was drawn'


def test_one_step_undoes_it_and_the_plan_changes_nothing():
    w, sq = valley()
    was = ({wid: list(x.refs) for wid, x in sq.ways.items()}, dict(sq.nodes))
    p = valleyfit.plan(w, LASSO, picked(sq), edits.SetUndoStack().alloc)
    assert ({wid: list(x.refs) for wid, x in sq.ways.items()}, dict(sq.nodes)) == was
    (s, step), = p.steps
    step.apply(s)
    step.undo(s)
    assert ({wid: list(x.refs) for wid, x in sq.ways.items()}, dict(sq.nodes)) == was


def test_a_knoll_is_kept():
    """A small 40 m ring with the 30 m round it, by the river: a hill."""
    w, sq = valley()
    contour(sq, 31, 30, ring(300, 160, 70, 40))
    contour(sq, 41, 40, ring(300, 160, 25, 15))
    p = fit(w, sq)
    assert 41 in sq.ways and p.knolls == 1, (p.knolls, p.refused)
    assert not crossings.find(w)


def test_no_river_is_refused():
    w, sq = valley()
    del sq.ways[RIVER]
    p = fit(w, sq)
    assert not p.steps and 'no river' in (p.refused or ''), p.refused


def test_nothing_picked_is_refused():
    w, sq = valley()
    p = valleyfit.plan(w, LASSO, {A: set()}, edits.SetUndoStack().alloc)
    assert not p.steps and 'no contour picked' in p.refused


def test_a_narrow_ring_however_long_is_small():
    strip = ogr.CreateGeometryFromWkt('POLYGON ((0 0, 600 0, 600 76, 0 76, 0 0))')
    blob = ogr.CreateGeometryFromWkt('POLYGON ((0 0, 220 0, 220 220, 0 220, 0 0))')
    assert valleyfit.small_ring(strip) and not valleyfit.small_ring(blob)
