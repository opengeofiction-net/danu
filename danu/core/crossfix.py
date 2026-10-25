"""Crossings fixed where the answer is plain: a recovered contour pushed back
off the line at the next level it strays across.

Roantra's recovered 10 m contours run along the main map's coastline and step
over it, again and again - 388 crossings in N46E029, every one of them 0 m
against 10 to 30 m, most 0 against 10. Each is fixed as #267 fixes a lake's
shore (``danu.core.push``): the stretch that strays is replaced by the line
crossed, offset to the contour's side, as far as keeps it clear of every
other contour - the 20 m beyond above all - so the contour stays one line
and fits between.

Only where it is plain which moves and to where:

- **the line crossed is fixed**: a coastline, a water outline, or the main
  map's own way (a positive id); the contour moved is a recovered one, a
  negative id with nothing but its level and ``contour`` on it;
- **the levels are next to each other**: nothing in the set between them.
  0 m against 20 m says the 10 m between is missing, which is a mapper's to
  draw;
- **the side is known**: a coastline's land is on its left; otherwise the
  side most of the contour lies on.

The rest - two recovered contours crossing, levels further apart, a contour
that ends by the line or cannot be pushed clear - is left to the Validation
panel. Only the squares asked for are changed: the editor asks for the
centre square, as the panel's "Centre square only" does.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from ..checks import crossings
from . import edits
from .push import Pusher

PUSH_M = 50.0                  # how far back a contour is pushed, before it steps in
_PLAIN = {'ele', 'contour'}     # a recovered contour carries nothing else


@dataclass
class Plan:
    steps: list = field(default_factory=list)        # (square, Compound)
    added: list = field(default_factory=list)        # the arcs drawn, as [(lon, lat)] runs
    removed: list = field(default_factory=list)      # the stretches they replace
    pushed: int = 0                                  # contours pushed back
    fixed: int = 0                                   # crossings that goes
    left: int = 0                                    # crossings left to the panel


class _Projection:
    def __init__(self, lat0: float):
        self.kx, self.ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0

    def xy(self, n) -> tuple[float, float]:
        return n.lon * self.kx, n.lat * self.ky

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        return x / self.kx, y / self.ky


def _fixed(way) -> bool:
    return (way.id > 0 or way.tags.get('natural') in ('coastline', 'water')
            or 'waterway' in way.tags)


def _movable(way) -> bool:
    return way.id < 0 and set(way.tags) <= _PLAIN


def plan(working_set, alloc, only=None, pull_back_m: float = PUSH_M) -> Plan:
    """What pushing back the plain crossings would do: ``alloc(square)`` an
    allocator for a square, ``only`` the names of the squares whose
    contours may move (all, when None)."""
    out = Plan()
    try:
        from osgeo import ogr
    except ImportError:                    # a build without GDAL leaves them all to the panel
        out.left = len(crossings.find(working_set))
        return out
    found = crossings.find(working_set)
    if not found:
        return out
    squares = {sq.name: sq for sq in working_set.squares.values()}
    levels = sorted({w.ele for sq in squares.values() for w in sq.ways.values() if w.ele is not None})

    def between(a, b) -> bool:
        lo, hi = sorted((a, b))
        return any(lo < e < hi for e in levels)

    # each movable contour, and the fixed ways at the next level it crosses
    partners: dict = defaultdict(set)
    counted: dict = defaultdict(int)
    for c in found:
        for me, other in ((c.a, c.b), (c.b, c.a)):
            mine, theirs = squares[me[0]].ways.get(me[1]), squares[other[0]].ways.get(other[1])
            if (mine is None or theirs is None or (only is not None and me[0] not in only)
                    or not _movable(mine) or not _fixed(theirs) or between(me[2], other[2])
                    or me[2] == other[2]):
                continue
            partners[(me[0], me[1])].add((other[0], other[1]))
            counted[(me[0], me[1])] += 1
    lat0 = working_set.centre.lat + 0.5            # metres about the centre square's middle
    proj = _Projection(lat0)

    def metres(sq, way):
        return [proj.xy(sq.nodes[r]) for r in way.refs if r in sq.nodes]

    # every way with a level, as it stands: what a push keeps clear of
    guard = defaultdict(list)
    probe = Pusher(ogr, None, pull_back_m)
    probe.guard = guard
    for sq in squares.values():
        for w in sq.ways.values():
            if w.ele is not None and 'danu:fill' not in w.tags and len(w.refs) >= 2:
                probe.stays(w.id, [metres(sq, w)])
    steps: dict = defaultdict(list)
    fixed_total = 0
    for (name, wid), others in sorted(partners.items(), key=lambda kv: str(kv[0])):
        sq = squares[name]
        way = sq.ways[wid]
        fixed_ways = [squares[n].ways[o] for n, o in others]
        if len({f.ele for f in fixed_ways}) != 1:
            continue                       # crossing the next level down and up: not plain
        lines = ogr.Geometry(ogr.wkbMultiLineString)
        lines_pts = [metres(squares[n], f) for f, (n, _) in zip(fixed_ways, others, strict=True)]
        for L in lines_pts:
            lines.AddGeometry(probe._line(L))
        pts = metres(sq, way)
        side = _side(lines_pts, fixed_ways, way, pts)
        if side is None:
            continue
        pusher = Pusher(ogr, lines, pull_back_m, side=side, fixed={o for _, o in others}, partial=True)
        pusher.guard = guard
        pusher.drop(wid)                   # the contour itself, as it will stand, goes back in
        got = pusher.round(sq, way, pts, proj, alloc)
        if got is None:
            pusher.stays(wid, [pts])
            continue
        cmd, arcs, gone = got
        steps[name].append(cmd)
        out.pushed += 1
        # what it still crosses: a stretch with no room to be pushed is left
        still = probe._line(pusher.last).Intersection(lines)
        fixed_total += max(0, counted[(name, wid)] - _points(still))
        out.added += [[proj.lonlat(*q) for q in arc] for arc in arcs]
        out.removed += [[proj.lonlat(*q) for q in run] for run in gone]
    out.fixed = fixed_total
    out.left = len(found) - fixed_total
    out.steps = [(squares[n], edits.Compound(cmds, name=f'push back {len(cmds)} crossing contour'
                                              f'{"s" * (len(cmds) != 1)}'))
                 for n, cmds in steps.items()]
    return out


def _points(g) -> int:
    """How many points an intersection is - the crossings it says."""
    if g is None or g.IsEmpty():
        return 0
    name = g.GetGeometryName()
    if name == 'POINT':
        return 1
    if name in ('MULTIPOINT', 'GEOMETRYCOLLECTION'):
        return sum(_points(g.GetGeometryRef(i)) for i in range(g.GetGeometryCount()))
    return 1                               # a stretch shared: one place, said once


def _side(lines_pts, fixed_ways, way, pts):
    """Which side of the lines crossed the contour belongs on, as a test of
    a point at a distance: a coastline's land, left of it, for a contour
    above it; otherwise the side most of the contour's nodes within reach
    lie on. None when that is not plain."""
    segs = _Segments(lines_pts)
    if all(f.tags.get('natural') == 'coastline' for f in fixed_ways):
        if way.ele <= fixed_ways[0].ele:
            return None
        want = True
    else:
        votes = [segs.left(q) for q in pts if segs.distance(q) < 500.0]
        n_left = sum(votes)
        if 2 * n_left == len(votes):
            return None
        want = 2 * n_left > len(votes)
    return lambda q, d: segs.left(q) == want


class _Segments:
    """The lines crossed, as segments in order: which side of them a point
    is, by the nearest - at a vertex, by the turn there."""

    def __init__(self, lines_pts):
        self.lines = [np.asarray(L, dtype=float) for L in lines_pts if len(L) >= 2]
        self.a = np.concatenate([L[:-1] for L in self.lines])
        self.b = np.concatenate([L[1:] for L in self.lines])
        # each segment's neighbours on its own line, -1 at an end
        prev, nxt, k = [], [], 0
        for L in self.lines:
            n = len(L) - 1
            prev += [-1] + list(range(k, k + n - 1))
            nxt += list(range(k + 1, k + n)) + [-1]
            k += n
        self.prev, self.next = np.array(prev), np.array(nxt)

    def _nearest(self, q):
        d = self.b - self.a
        L = (d * d).sum(axis=1)
        L[L == 0] = 1.0
        t = np.clip(((q - self.a) * d).sum(axis=1) / L, 0.0, 1.0)
        dist = np.hypot(*(self.a + t[:, None] * d - q).T)
        i = int(dist.argmin())
        return i, float(t[i]), float(dist[i])

    def distance(self, q) -> float:
        return self._nearest(np.asarray(q, dtype=float))[2]

    def left(self, q) -> bool:
        q = np.asarray(q, dtype=float)
        i, t, _ = self._nearest(q)

        def cross(i):
            a, b = self.a[i], self.b[i]
            return (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        j = self.next[i] if t >= 1.0 else self.prev[i] if t <= 0.0 else -1
        if j < 0:
            return cross(i) > 0
        first, second = (i, j) if t >= 1.0 else (j, i)
        da, db = self.b[first] - self.a[first], self.b[second] - self.a[second]
        turn = da[0] * db[1] - da[1] * db[0]
        # turning left, the left is the wedge inside the turn: left of both;
        # turning right, it is all but the wedge: left of either
        return (cross(first) > 0 and cross(second) > 0) if turn > 0 else (cross(first) > 0 or cross(second) > 0)
