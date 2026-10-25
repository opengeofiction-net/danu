"""A contour pushed off something it strays across, as one line: each stretch
that reaches it replaced by the thing's own outline offset to the contour's
side, at the furthest distance that keeps clear of every other contour.

Two users. Flatten (``danu.water.flatten``, #267) pushes the contour at the
level next to a lake's out round the water. The crossings fix
(``danu.core.crossfix``) pushes a contour off the one at the next level it
crosses - a recovered 10 m contour stepping in and out over the main map's
coastline - onto the side it belongs.

The offset is GDAL's buffer, of the water or the line crossed; a stretch whose
offset would cross or pass by another contour is tried at half the distance,
then half again, down to ``WRAP_MIN_M``, each on its own. Worked in metres
on the caller's projection.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from itertools import pairwise

import numpy as np

from . import edits

WRAP_MIN_M = 5.0           # a contour pushed round no nearer than this
WRAP_SIMPLIFY_M = 2.0      # the offset drawn to within this
_CELL_M = 1000.0           # the guard's index
_MARGIN_M = 500.0          # the water clipped this far beyond twice the furthest push
_PROBES = 64               # the points of an arc asked which side of a line it is on


def _length(pts) -> list[float]:
    """Distance along the run of points, at each."""
    out = [0.0]
    for (x0, y0), (x1, y1) in pairwise(pts):
        out.append(out[-1] + math.hypot(x1 - x0, y1 - y0))
    return out


class Pusher:
    """Contours pushed off ``water`` - a polygon, or lines - and what is
    around them to keep clear of.

    ``side``, when given, says which side of a line crossed the contour
    belongs on: called with a point and the distance pushed, true on the
    contour's side. Without it, the side the stretch ran - the one it and
    the offset enclose least between - which is right for water and wrong
    for a line crossed, where the stretch ran on both. ``partial`` pushes
    what it can of a contour and leaves the rest as it was."""

    def __init__(self, ogr, water, pull_back_m, side=None, fixed=frozenset(), partial=False):
        self.ogr, self.water, self.side = ogr, water, side
        # a stretch that cannot be pushed left as it is, the rest pushed -
        # not for a lake, where it would leave a contour in the water
        self.partial = partial
        self.fixed = set(fixed)            # the ways pushed off: never in the way
        self.dists = []
        d = pull_back_m
        while d >= WRAP_MIN_M:
            self.dists.append(d)
            d /= 2
        self.zones = {}
        self.guard = defaultdict(list)     # cell: [(way id, envelope, line)] of every contour as it will stand
        self._stays_log = []               # what went into the guard, in order

    @classmethod
    def make(cls, polys, pull_back_m, partial=False):
        try:
            from osgeo import ogr
        except ImportError:                # a build without GDAL cuts instead
            return None
        water = None
        for ring in polys:
            r = ogr.Geometry(ogr.wkbLinearRing)
            for x, y in ring:
                r.AddPoint_2D(x, y)
            g = ogr.Geometry(ogr.wkbPolygon)
            g.AddGeometry(r)
            g = g.Buffer(0)
            water = g if water is None else water.SymDifference(g)     # an island is a hole
        return cls(ogr, water, pull_back_m, partial=partial) if water is not None and not water.IsEmpty() else None

    def _line(self, pts):
        g = self.ogr.Geometry(self.ogr.wkbLineString)
        for x, y in pts:
            g.AddPoint_2D(x, y)
        return g

    @staticmethod
    def _cells(env):
        x0, x1, y0, y1 = env
        return [(i, j) for i in range(math.floor(x0 / _CELL_M), math.floor(x1 / _CELL_M) + 1)
                for j in range(math.floor(y0 / _CELL_M), math.floor(y1 / _CELL_M) + 1)]

    def stays(self, wid, lines) -> None:
        """A contour as it will stand, to keep clear of."""
        for pts in lines:
            if len(pts) >= 2:
                g = self._line(pts)
                entry = (wid, g.GetEnvelope(), g)
                for c in self._cells(entry[1]):
                    self.guard[c].append(entry)
                self._stays_log.append(entry)

    def _unstay(self, mark) -> None:
        """Take back everything put in the guard since ``mark``: a contour
        worked again starts from the guard as it was before it."""
        for entry in self._stays_log[mark:]:
            for c in self._cells(entry[1]):
                self.guard[c] = [g for g in self.guard[c] if g is not entry]
        del self._stays_log[mark:]

    def drop(self, wid) -> None:
        for c in list(self.guard):
            self.guard[c] = [g for g in self.guard[c] if g[0] != wid]

    def clear(self, wid, arcs, between=None) -> bool:
        """Whether arcs drawn for way ``wid`` cross or touch no other
        contour - nor, with the stretches they replace, pass one by: the
        ground between the two is all one side of the contour."""
        for k, arc in enumerate(arcs):
            g = self._line(arc)
            if between is not None:
                g = self._polygon([*between[k], *reversed(arc)]) or g
            env = g.GetEnvelope()
            x0, x1, y0, y1 = env
            seen = set()
            for c in self._cells(env):
                for entry in self.guard.get(c, ()):
                    other, (a0, a1, b0, b1), h = entry
                    if (other == wid or other in self.fixed or id(entry) in seen
                            or not (a0 <= x1 and x0 <= a1 and b0 <= y1 and y0 <= b1)):
                        continue
                    seen.add(id(entry))
                    if g.Intersects(h):
                        return False
        return True

    def _zone(self, d):
        if d not in self.zones:
            z = self.water.Buffer(d).SimplifyPreserveTopology(WRAP_SIMPLIFY_M)
            polys = [z] if z.GetGeometryName() == 'POLYGON' else [z.GetGeometryRef(i) for i in range(z.GetGeometryCount())]
            rings = [[p.GetGeometryRef(k).GetPoint_2D(j) for j in range(p.GetGeometryRef(k).GetPointCount() - 1)]
                     for p in polys for k in range(p.GetGeometryCount())]
            # each ring closed, as a line, and measured along once: an arc is
            # placed on it by position, and a shore's offset is thousands long
            self.zones[d] = z, [(r, self._line([*r, r[0]]), (c := [*r, r[0]]), _length(c)) for r in rings]
        return self.zones[d]

    def round(self, sq, way, pts, proj, alloc):
        """The contour pushed off, each stretch at the furthest distance that
        keeps it clear of the others, as (command, arcs drawn, runs
        replaced); or None.

        Worked against the water - or the lines - about the contour only:
        clipped to a box round it with room to spare, and the offsets made
        from that. Roantra's estuary, relation 470435, is 147 km by 104 km
        and 33,000 vertices, and every test of it whole, for each of the
        hundreds of contours round it, held a flatten for a minute."""
        whole, zones = self.water, self.zones
        x0, x1, y0, y1 = self._line(pts).GetEnvelope()
        reach = 2 * (self.dists[0] if self.dists else 0.0) + _MARGIN_M
        bx0, bx1, by0, by1 = x0 - reach, x1 + reach, y0 - reach, y1 + reach
        local = self.water.Intersection(self._box(bx0, bx1, by0, by1))
        if local is None or local.IsEmpty():
            return None
        self.water, self.zones = local, {}
        mark = len(self._stays_log)
        try:
            got = self._round(sq, way, pts, proj, alloc)
        finally:
            self.water, self.zones = whole, zones
        # an arc with a vertex within half the margin of the box's edge
        # followed the cut there, not a shore - the clipped water's edge is
        # straight, its offset no further out than the push, so an arc along
        # it has its vertices there. Round a lake the contour crosses whole,
        # the far shore is outside the box: that one again, against all of it
        edge = _MARGIN_M / 2
        if got is not None and any(not (bx0 + edge < x < bx1 - edge and by0 + edge < y < by1 - edge)
                                   for arc in got[1] for x, y in arc):
            self._unstay(mark)
            got = self._round(sq, way, pts, proj, alloc)
        return got

    def _box(self, x0, x1, y0, y1):
        r = self.ogr.Geometry(self.ogr.wkbLinearRing)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            r.AddPoint_2D(x, y)
        g = self.ogr.Geometry(self.ogr.wkbPolygon)
        g.AddGeometry(r)
        return g

    def _round(self, sq, way, pts, proj, alloc):
        refs, L = list(way.refs), list(pts)
        if way.refs[0] == way.refs[-1] and len(way.refs) > 3:
            # begun again at its node furthest from the water, so no stretch
            # replaced runs across where it begins and ends - from the water
            # itself, not the reach of the first distance: a small island's
            # ring all within that is pushed at a nearer one
            # - and on its own side of a line crossed: a node furthest off it
            # may be the furthest a stray reaches the wrong way
            at = [k for k in range(len(L) - 1) if self.side is None or self.side(L[k], self.dists[0])]
            if not at:
                return None
            k = max(at, key=lambda k: self._point(L[k]).Distance(self.water))
            if self._point(L[k]).Distance(self.water) <= 0:
                return None                              # it lies all in the water
            refs, L = [*refs[k:-1], *refs[:k], refs[k]], [*L[k:-1], *L[:k], L[k]]
        cum = _length(L)
        line = self._line(L)
        runs = self._runs(L, cum, line, 0, 0.0, cum[-1], way.id)
        if not runs:
            return None
        ids = alloc(sq)
        new_nodes, out, now, arcs, gone, k = {}, [], [], [], [], 0
        for i_in, i_out, arc in runs:
            out += refs[k:i_in + 1]
            now += L[k:i_in + 1]
            for q in arc:
                if math.dist(q, L[i_in]) < 0.01 or math.dist(q, L[i_out + 1]) < 0.01:
                    continue                             # met on a node of its own
                nid = ids.take()
                new_nodes[nid] = proj.lonlat(*q)
                out.append(nid)
                now.append(q)
            arcs.append(arc)
            gone.append([arc[0], *L[i_in + 1:i_out + 1], arc[-1]])
            k = i_out + 1
        out += refs[k:]
        now += L[k:]
        self.stays(way.id, [now])
        self.last = now                    # the line as pushed, in metres
        return edits.ReplaceWay(way.id, [(way.id, out)], new_nodes), arcs, gone

    def _runs(self, L, cum, line, level, lo, hi, wid):
        """The stretches of L between ``lo`` and ``hi`` along it that reach
        the water, each with the arc of the offset that replaces it: at
        ``dists[level]``, or for a stretch whose arc there is not clear, at
        the next distance in. None when one cannot be pushed at all."""
        if level == len(self.dists):
            return None
        d = self.dists[level]
        zone, rings = self._zone(d)
        inside = line.Intersection(zone)
        parts = ([inside.GetGeometryRef(i) for i in range(inside.GetGeometryCount())]
                 if inside.GetGeometryCount() else [inside])
        spans = sorted(sp for g in parts
                       if not g.IsEmpty() and g.GetGeometryName() == 'LINESTRING' and g.Intersects(self.water)
                       for sp in _spans(L, cum, [g.GetPoint_2D(j) for j in range(g.GetPointCount())]))
        spans = [s for s in spans if lo - 1e-6 <= s[0] and s[1] <= hi + 1e-6]
        if self.side is not None:
            spans = self._joined(L, cum, spans, d)
            if spans is None:
                return None
        out = []
        for s_in, s_out in spans:
            if s_in <= 1e-6 or s_out >= cum[-1] - 1e-6:
                if not self.partial:
                    return None                          # it ends by the water
                # it ends within reach: nearer in, the stretch may not
                out += self._runs(L, cum, line, level + 1, s_in, s_out, wid) or []
                continue
            i_in, P = _point(L, cum, s_in)
            i_out, Q = _point(L, cum, s_out)
            arc = self._arc(rings, P, Q, L[i_in + 1:i_out + 1], d)
            if arc is not None and self.clear(wid, [arc], [[P, *L[i_in + 1:i_out + 1], Q]]):
                out.append((i_in, i_out, arc))
                continue
            inner = self._runs(L, cum, line, level + 1, s_in, s_out, wid)
            if inner is None:
                if self.partial:
                    continue
                return None
            out += inner
        return out

    def _joined(self, L, cum, spans, d):
        """Spans joined where the contour strays further than ``d`` across
        a line: one that leaves the reach on the wrong side runs on to where
        it comes back on the right one. None when it never does."""
        out, cur = [], None
        for s_in, s_out in spans:
            if cur is None:
                if not self.side(_point(L, cum, s_in)[1], d):
                    if self.partial:
                        continue                         # begun on the wrong side: left
                    return None
                cur = [s_in, s_out]
            else:
                cur[1] = s_out
            if self.side(_point(L, cum, s_out)[1], d):
                out.append(tuple(cur))
                cur = None
        return out if cur is None or self.partial else None

    def _arc(self, rings, P, Q, between, d):
        """The offset from P to Q on the contour's side, or None when P and
        Q are on different rings of it, or neither way round is that side.
        P and Q are placed along the ring where they fall, not at its
        nearest vertex: a straight shore's offset has a vertex only at each
        end."""
        near = min(rings, key=lambda r: r[1].Distance(self._point(P)))
        if min(rings, key=lambda r: r[1].Distance(self._point(Q))) is not near:
            return None
        ring, _, closed, cum = near
        sp, sq = _along(closed, cum, P), _along(closed, cum, Q)
        forward = (sq - sp) % cum[-1]

        def walk(a, b):
            # the ring's vertices met going forward from position a to b -
            # found along it by bisection: a shore's offset can be 30,000
            # vertices, and sorting them for every arc was most of the push
            i, j = bisect.bisect_right(cum, a, 0, len(ring)), bisect.bisect_left(cum, b, 0, len(ring))
            if a <= b:
                return closed[i:j]
            return closed[i:len(ring)] + closed[:j]
        sides = ([P, *walk(sp, sq), Q], [P, *reversed(walk(sq, sp)), Q])
        if self.side is not None:
            def on_side(arc):
                # its vertices and its segments' middles, up to _PROBES of
                # them spread along it: the long way round an offset ring can
                # be thousands, each asked of every segment crossed - one
                # contour in N46E030 sat on that for twenty minutes
                probes = [*arc[1:-1], *(((x0 + x1) / 2, (y0 + y1) / 2) for (x0, y0), (x1, y1) in pairwise(arc))]
                if len(probes) > _PROBES:
                    probes = [probes[i * len(probes) // _PROBES] for i in range(_PROBES)]
                return all(self.side(q, d) for q in probes)
            # the shorter way round first: the longer is asked only if it is not
            for arc in (sides if forward <= cum[-1] - forward else sides[::-1]):
                if on_side(arc):
                    return arc
            return None

        def apart(side):
            g = self._polygon([P, *between, Q, *reversed(side)])
            return g.GetArea() if g is not None else math.inf
        return min(sides, key=apart)

    def _point(self, q):
        g = self.ogr.Geometry(self.ogr.wkbPoint)
        g.AddPoint_2D(*q)
        return g

    def _polygon(self, pts):
        if len(pts) < 3:
            return None
        r = self.ogr.Geometry(self.ogr.wkbLinearRing)
        for x, y in [*pts, pts[0]]:
            r.AddPoint_2D(x, y)
        g = self.ogr.Geometry(self.ogr.wkbPolygon)
        g.AddGeometry(r)
        return g.Buffer(0)


def _along(L, cum, pt) -> float:
    """How far along the run of points L a point on it is. In numpy, the
    run's arrays kept for the few runs last asked of: the same contour and
    the same offset ring are asked again and again, and a loop in Python
    over 2,000 segments for each was most of a push in N46E030."""
    for hit in _ARRAYS:
        if hit[0] is L:
            _, a, d, seg, sq, c = hit
            break
    else:
        a = np.asarray(L[:-1], dtype=float)
        d = np.asarray(L[1:], dtype=float) - a
        seg = np.hypot(*d.T)
        sq = np.where(seg > 0, seg * seg, 1.0)
        c = np.asarray(cum[:-1], dtype=float)
        _ARRAYS.insert(0, (L, a, d, seg, sq, c))
        del _ARRAYS[8:]
    q = np.asarray(pt, dtype=float)
    t = np.clip(((q - a) * d).sum(axis=1) / sq, 0.0, 1.0)
    dist = np.hypot(*(a + t[:, None] * d - q).T)
    i = int(dist.argmin())
    return float(c[i] + t[i] * seg[i])


_ARRAYS: list = []          # (run, its arrays) of the runs last asked along


def _spans(L, cum, piece) -> list[tuple[float, float]]:
    """Where a stretch of L - a piece GDAL cut from it, as points - begins
    and ends along it. On a ring the closing point is both 0 and the whole
    length: taken as the end the rest of the stretch is nearer, or a stretch
    running up to it would read as running from the start, over everything
    between. A piece running through it - newer GEOS joins the two either
    side - is two stretches, one to the end and one from the start."""
    ring = L[0] == L[-1]
    if ring:
        for j in range(1, len(piece) - 1):
            if math.dist(piece[j], L[0]) < 1e-6:
                return _spans(L, cum, piece[:j + 1]) + _spans(L, cum, piece[j:])
    n = len(piece)
    ends = []
    for j, nb in ((0, 1), (n - 1, n - 2)):
        s = _along(L, cum, piece[j])
        if ring and math.dist(piece[j], L[0]) < 1e-6 and 0 <= nb < n:
            s = 0.0 if _along(L, cum, piece[nb]) < cum[-1] / 2 else cum[-1]
        ends.append(s)
    return [(min(ends), max(ends))]


def _point(L, cum, s) -> tuple[int, tuple[float, float]]:
    """The segment of L a distance along it falls in, and the point there."""
    for i in range(len(L) - 1):
        if cum[i + 1] >= s:
            t = (s - cum[i]) / ((cum[i + 1] - cum[i]) or 1.0)
            return i, (L[i][0] + t * (L[i + 1][0] - L[i][0]), L[i][1] + t * (L[i + 1][1] - L[i][1]))
    return len(L) - 2, L[-1]
