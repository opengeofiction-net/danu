"""Absorb: a contour and the pieces of it lying beside it made one line.

A recovery from a coarse DEM leaves a valley's contour as a tip at the
river and a chain of small rings at its level up the valley - each a hollow
the old interpolator dug - where the one contour should run up one side and
down the other. The pieces are linked nearest first, and each pair linked
is made one by the hull of the two: the gap bridged as wide as the pieces
are, the notch where two meet filled. The contour's stretch inside what
that makes is replaced by its outline, on the side that wraps the pieces,
and the pieces go.

Worked in metres about the pieces, by GDAL's geometry, which every build of
Danu has. No Qt.
"""

from __future__ import annotations

import math
from itertools import pairwise

from osgeo import ogr

from .edits import Command, Compound, DeleteWay, IdAllocator, ReplaceWay
from .square import Square

GAP_M = 100.0              # pieces further apart than this are not one valley's
SIMPLIFY_M = 2.0           # the outline drawn to within this
SNAP_M = 2.0               # where the line meets the outline this close to a node of its own, that node
_EDGE_M = 0.5              # the outline taken this far out, so a contour along a piece's edge is in it
_MITRE = ['JOIN_STYLE=MITRE', 'MITRE_LIMIT=3']


class _Frame:
    """Degrees to local metres and back, about a latitude."""

    def __init__(self, lat: float):
        self.kx, self.ky = 111320 * math.cos(math.radians(lat)), 110540.0

    def m(self, lon: float, lat: float) -> tuple[float, float]:
        return lon * self.kx, lat * self.ky

    def deg(self, x: float, y: float) -> tuple[float, float]:
        return x / self.kx, y / self.ky


def _polygon(pts) -> ogr.Geometry | None:
    pts = list(pts)
    if not pts:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(set(pts)) < 3:
        return None
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in pts:
        ring.AddPoint_2D(x, y)
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    p = p.Buffer(0)                      # a piece drawn crossing itself made sound
    return p if p is not None and not p.IsEmpty() and p.GetArea() > 0 else None


def _hull(*geoms) -> ogr.Geometry:
    c = ogr.Geometry(ogr.wkbGeometryCollection)
    for g in geoms:
        c.AddGeometry(g)
    return c.ConvexHull()


def _line(pts) -> ogr.Geometry:
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(x, y)
    return g


def _along(L, cum, pt) -> float:
    """How far along the line L a point on it is."""
    best, at = math.inf, 0.0
    for i, (a, b) in enumerate(pairwise(L)):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1.0)))
        d = math.hypot(a[0] + t * dx - pt[0], a[1] + t * dy - pt[1])
        if d < best:
            best, at = d, cum[i] + t * math.dist(a, b)
    return at


def _at(L, cum, s) -> tuple[int, tuple[float, float]]:
    """The segment of L a distance along it falls in, and the point there."""
    for i in range(len(L) - 1):
        if cum[i + 1] >= s:
            t = (s - cum[i]) / ((cum[i + 1] - cum[i]) or 1.0)
            return i, (L[i][0] + t * (L[i + 1][0] - L[i][0]), L[i][1] + t * (L[i + 1][1] - L[i][1]))
    return len(L) - 2, L[-1]


def absorb(square: Square, main_id: int, piece_ids, alloc: IdAllocator,
           gap_m: float = GAP_M) -> tuple[Command, list[tuple[float, float]]] | str:
    """The command that makes ``main_id`` run round the pieces and takes the
    pieces away, with the line it makes as (lon, lat); or why not."""
    main = square.ways.get(main_id)
    pieces = [square.ways.get(i) for i in piece_ids]
    if main is None or main.ele is None or any(p is None for p in pieces):
        return 'that contour is no longer there'
    if not pieces:
        return 'no pieces picked - pick them with Shift and a lasso round them'
    other = sorted({p.ele for p in pieces if p.ele != main.ele})
    if other:
        return f'the pieces are not all at {main.ele:g} m - {other[0]:g} m among them'
    if main.closed:
        return 'the contour is a ring - absorb into an open contour'
    nodes = square.nodes
    lats = [nodes[r].lat for p in pieces for r in p.refs if r in nodes]
    if not lats:
        return 'the pieces are no longer there'
    f = _Frame(sum(lats) / len(lats))
    polys = []
    for p in pieces:
        g = _polygon([f.m(nodes[r].lon, nodes[r].lat) for r in p.refs if r in nodes])
        if g is None:
            return f'way {p.id} is too small to be a piece'
        polys.append(g)
    # linked nearest first - a spanning tree - each pair by its hull
    blob, linked, rest = polys[0].Clone(), [0], set(range(1, len(polys)))
    while rest:
        d, i, j = min((polys[i].Distance(polys[j]), i, j) for i in linked for j in rest)
        if d > gap_m:
            return f'two pieces are {d:,.0f} m apart - past the {gap_m:,.0f} m that is one valley'
        blob = blob.Union(_hull(polys[i], polys[j]))
        linked.append(j)
        rest.discard(j)
    pieces_area = blob.Clone()
    for g in polys:
        pieces_area = pieces_area.Union(g)
    L = [f.m(nodes[r].lon, nodes[r].lat) for r in main.refs]
    line = _line(L)
    d = line.Distance(blob)
    if d > gap_m:
        return f'the pieces are {d:,.0f} m from the contour - past the {gap_m:,.0f} m that is one valley'
    if d > 0:
        # the contour bridged to the nearest piece as the pieces are to each other
        k = min(range(len(L) - 1), key=lambda k: _line(L[k:k + 2]).Distance(blob))
        near = min(polys, key=lambda g: g.Distance(_line(L[k:k + 2])))
        blob = blob.Union(_hull(near, _line(L[k:k + 2])))
    blob = blob.Buffer(_EDGE_M, _MITRE).SimplifyPreserveTopology(SIMPLIFY_M)
    if blob.GetGeometryName() != 'POLYGON':
        return 'the pieces do not make one shape'
    cum = [0.0]
    for a, b in pairwise(L):
        cum.append(cum[-1] + math.dist(a, b))
    inside = line.Intersection(blob)
    parts = ([inside.GetGeometryRef(i) for i in range(inside.GetGeometryCount())]
             if inside.GetGeometryName().startswith('MULTI') or inside.GetGeometryName() == 'GEOMETRYCOLLECTION'
             else [inside])
    ends = [_along(L, cum, g.GetPoint_2D(k)) for g in parts if not g.IsEmpty() and g.GetGeometryName() == 'LINESTRING'
            for k in (0, g.GetPointCount() - 1)]
    if not ends:
        return 'the contour does not reach the pieces'
    s_in, s_out = min(ends), max(ends)
    if s_in <= 1e-6 or s_out >= cum[-1] - 1e-6:
        return 'the contour ends among the pieces - it has to run in and out of them'
    i_in, P = _at(L, cum, s_in)
    i_out, Q = _at(L, cum, s_out)
    # met on the far node of its segment, at either end: the cut moved past
    # that node, so it stays the line's own - the keeps below then reuse it
    # rather than drawing a node again at its place
    if i_in < i_out and math.dist(P, L[i_in + 1]) <= SNAP_M:
        i_in += 1
    if i_out > i_in and math.dist(Q, L[i_out]) <= SNAP_M:
        i_out -= 1
    ring = blob.GetGeometryRef(0)
    R = [ring.GetPoint_2D(k) for k in range(ring.GetPointCount() - 1)]
    kP = min(range(len(R)), key=lambda k: math.dist(R[k], P))
    kQ = min(range(len(R)), key=lambda k: math.dist(R[k], Q))
    arcs = ([R[(kP + k) % len(R)] for k in range((kQ - kP) % len(R) + 1)],
            [R[(kP - k) % len(R)] for k in range((kP - kQ) % len(R) + 1)])
    cut = L[i_in + 1:i_out + 1]

    def wraps(arc) -> float:
        # asked of the pieces themselves, not of the hulls that bridged them:
        # the side meant is the one round the pieces
        g = _polygon([P, *cut, Q, *reversed(arc)])
        return g.Intersection(pieces_area).GetArea() if g is not None else 0.0
    arc = max(arcs, key=wraps)
    run = [P, *arc[1:-1], Q]
    # the ends where the line meets the outline: a node of the line's own if one is that close
    keep_in = math.dist(P, L[i_in]) <= SNAP_M
    keep_out = math.dist(Q, L[i_out + 1]) <= SNAP_M
    if keep_in:
        run = run[1:]
    if keep_out:
        run = run[:-1]
    new_nodes, mid = {}, []
    for x, y in run:
        nid = alloc.take()
        new_nodes[nid] = f.deg(x, y)
        mid.append(nid)
    refs = [*main.refs[:i_in + 1], *mid, *main.refs[i_out + 1:]]
    steps: list[Command] = [ReplaceWay(main_id, [(main_id, refs)], new_nodes)]
    steps += [DeleteWay(p.id) for p in pieces]
    coords = [new_nodes[r] if r in new_nodes else (nodes[r].lon, nodes[r].lat) for r in refs]
    n = len(pieces)
    return Compound(steps, f'absorb {n} piece{"s" * (n != 1)} into the {main.ele:g} m contour'), coords
