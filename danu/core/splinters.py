"""Splinters: every chain of small rings a lasso picks absorbed into the line
of their level beside it - E (danu.core.absorb) done for each, as one step.

A recovery from a coarse DEM leaves a valley's contour as a tip and a chain
of small rings at its level up the valley, or a ring touching its line at a
corner. Here a splinter is a ring under SMALL_M2 that is a hollow - the
nearest contour of another level outside it is higher - linked ring to ring
within absorb's reach, the chain within that reach of a line of its level.
A knoll - the nearest outside lower - is a hill, and kept.

Each chain is absorbed into the nearest line of its level, levels in turn
from the lowest, on a copy of the square, so a line absorbed into twice
takes the second from where the first left it. One that would make its
line cross a contour it did not cross before is held back, and listed with
the chains absorb refused and those no line reaches.

Worked square by square, in metres about each, by GDAL's geometry. No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from osgeo import ogr

from . import absorb
from .edits import Compound
from .square import Square, is_coastline

SMALL_M2 = 20000.0         # a ring smaller than this may be a splinter
GAP_M = absorb.GAP_M       # ring to ring, and chain to line
_LOOK_M = (100.0, 300.0, 1000.0)   # how far out a hollow's neighbour is looked for, in turn


@dataclass
class Plan:
    """What absorbing would do, before it is done."""
    steps: list = field(default_factory=list)        # (square, Compound)
    removed: list = field(default_factory=list)      # what goes, as [(lon, lat)] runs
    added: list = field(default_factory=list)        # the lines as they become
    outline: list = field(default_factory=list)      # the lasso, as a ring
    rings: int = 0                                   # rings absorbed
    chains: int = 0                                  # in this many chains
    lines: int = 0                                   # into this many lines
    knolls: int = 0                                  # small rings kept as hills
    held: list = field(default_factory=list)         # (why, lon, lat): chains not absorbed


def _line(pts) -> ogr.Geometry:
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(x, y)
    return g


def _poly(pts) -> ogr.Geometry | None:
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in pts:
        r.AddPoint_2D(x, y)
    g = ogr.Geometry(ogr.wkbPolygon)
    g.AddGeometry(r)
    g = g.Buffer(0)
    return g if g is not None and not g.IsEmpty() and g.GetArea() > 0 else None


def _meets(a: ogr.Geometry, b: ogr.Geometry) -> int:
    """How many places two lines meet - a stretch along each other as two,
    so a touch made an overlap counts as more."""
    g = a.Intersection(b)
    if g is None or g.IsEmpty():
        return 0
    parts = [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())] or [g]
    return sum(2 if 'LINE' in p.GetGeometryName() else 1 for p in parts)


def _near(e, f, d: float) -> bool:
    return not (f[0] > e[1] + d or f[1] < e[0] - d or f[2] > e[3] + d or f[3] < e[2] - d)


class _Work:
    """One square's contours in metres, kept as the absorbs go on a copy."""

    def __init__(self, sq: Square):
        lats = [n.lat for n in sq.nodes.values()] or [0.0]
        lat0 = (min(lats) + max(lats)) / 2
        self.kx, self.ky = 111320 * math.cos(math.radians(lat0)), 110540.0
        self.sq = Square(name=sq.name, present=sq.present, nodes=dict(sq.nodes), ways=dict(sq.ways),
                         relations=sq.relations, attrs=sq.attrs)
        self.geo, self.env = {}, {}
        self._boxes = None
        for w in sq.ways.values():
            if (w.ele is not None or is_coastline(w)) and len(w.refs) > 1:
                self.put(w.id)

    def pts(self, wid):
        sq = self.sq
        return [(sq.nodes[r].lon * self.kx, sq.nodes[r].lat * self.ky) for r in sq.ways[wid].refs if r in sq.nodes]

    def put(self, wid):
        g = _line(self.pts(wid))
        self.geo[wid], self.env[wid] = g, g.GetEnvelope()

    def drop(self, wid):
        self.geo.pop(wid, None)
        self.env.pop(wid, None)

    def boxes(self):
        """Every way's id and envelope as an array, as first read - for the
        knoll test, asked before anything is absorbed."""
        if self._boxes is None:
            ids = list(self.env)
            self._boxes = ids, np.array([self.env[o] for o in ids]).reshape(-1, 4)
        return self._boxes

    def lonlat(self, x, y):
        return x / self.kx, y / self.ky


def plan(working_set, lasso, picked: dict, alloc, report=None) -> Plan:
    """The splinters among what ``picked`` ({square name: node ids}) holds,
    absorbed; ``lasso`` [(lon, lat)] is drawn round them. ``alloc(square)``
    gives the ids."""
    out = Plan()
    if lasso:
        out.outline.append([*lasso, lasso[0]])
    for name, ids in sorted(picked.items(), key=lambda kv: str(kv[0])):
        sq = working_set.square(name)
        if sq is None or not ids:
            continue
        _square(sq, ids, alloc(sq), out, report)
    return out


def _square(sq: Square, ids: set, alloc, out: Plan, report) -> None:
    work = _Work(sq)
    s = work.sq
    rings = {}
    for w in sq.ways.values():
        if w.closed and w.ele is not None and not is_coastline(w) and len(w.refs) > 3 and ids.intersection(w.refs):
            g = _poly(work.pts(w.id))
            if g is not None and g.GetArea() < SMALL_M2:
                rings[w.id] = g
    if not rings:
        return
    hollow = {}
    for wid, g in rings.items():
        if _is_hollow(work, wid, g):
            hollow[wid] = g
        else:
            out.knolls += 1
    # every small ring is kept from being a line a chain is taken into: a
    # knoll beside a hollow is not the valley's contour
    small = set(rings)
    original = {}                       # line id: its refs before
    gone = []
    for ele in sorted({s.ways[i].ele for i in hollow}):
        if report is not None:
            report(f'absorbing the splinters at {ele:g} m…')
        level = [i for i in hollow if s.ways[i].ele == ele]
        for chain in _chains(work, level, hollow):
            blob = ogr.Geometry(ogr.wkbGeometryCollection)
            for i in chain:
                blob.AddGeometry(hollow[i])
            c = blob.Centroid()
            where = work.lonlat(c.GetX(), c.GetY())
            lines = sorted((work.geo[w.id].Distance(blob), w.id) for w in s.ways.values()
                           if w.ele == ele and w.id not in small and not is_coastline(w) and w.id in work.geo
                           and _near(work.env[w.id], blob.GetEnvelope(), GAP_M))
            lines = [wid for d, wid in lines if d <= GAP_M]
            if not lines:
                out.held.append((f'no {ele:g} m line within {GAP_M:g} m', *where))
                continue
            main = lines[0]
            got = absorb.absorb(s, main, chain, alloc)
            if isinstance(got, str):
                out.held.append((got.split(' - ')[0], *where))
                continue
            cmd, coords = got
            new = _line([(lon * work.kx, lat * work.ky) for lon, lat in coords])
            if _crosses(work, main, set(chain), new, blob.GetEnvelope()):
                out.held.append((f'its {ele:g} m line would cross a contour', *where))
                continue
            original.setdefault(main, [(s.nodes[r].lon, s.nodes[r].lat) for r in s.ways[main].refs if r in s.nodes])
            gone += [[(s.nodes[r].lon, s.nodes[r].lat) for r in s.ways[i].refs if r in s.nodes] for i in chain]
            cmd.apply(s)
            work.put(main)
            for i in chain:
                work.drop(i)
                hollow.pop(i, None)
            cmds = out.steps[-1][1].commands if out.steps and out.steps[-1][0] is sq else None
            if cmds is None:
                out.steps.append((sq, Compound([cmd], name=f'absorb the splinters in {sq.name.name}')))
            else:
                cmds.append(cmd)
            out.rings += len(chain)
            out.chains += 1
    out.lines += len(original)
    out.removed += [*original.values(), *gone]
    out.added += [[(s.nodes[r].lon, s.nodes[r].lat) for r in s.ways[m].refs if r in s.nodes] for m in original]


def _is_hollow(work: _Work, wid: int, g: ogr.Geometry) -> bool:
    """The nearest contour of another level outside the ring higher than it
    - or none near at all. Looked for further out in turn; what one reach
    finds stands only if it is within that reach, since a long line's
    envelope comes near where the line does not."""
    s = work.sq
    ele, e = s.ways[wid].ele, work.env[wid]
    line = work.geo[wid]
    ids, box = work.boxes()
    for reach in _LOOK_M:
        best, lev = math.inf, None
        near = np.nonzero((box[:, 0] <= e[1] + reach) & (box[:, 1] >= e[0] - reach)
                          & (box[:, 2] <= e[3] + reach) & (box[:, 3] >= e[2] - reach))[0]
        for k in near:
            o = ids[k]
            w = s.ways[o]
            if w.ele is None or w.ele == ele or g.Contains(work.geo[o]):
                continue
            d = line.Distance(work.geo[o])
            if d < best:
                best, lev = d, w.ele
        if lev is not None and (best <= reach or reach == _LOOK_M[-1]):
            return lev > ele
    return True


def _chains(work: _Work, level: list, polys: dict) -> list[list[int]]:
    """The rings linked ring to ring within reach, each chain once."""
    parent = {i: i for i in level}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, i in enumerate(level):
        for j in level[a + 1:]:
            if _near(work.env[i], work.env[j], GAP_M) and polys[i].Distance(polys[j]) <= GAP_M:
                parent[root(i)] = root(j)
    chains = {}
    for i in level:
        chains.setdefault(root(i), []).append(i)
    return sorted(chains.values(), key=lambda c: min(c))


def _crosses(work: _Work, main: int, chain: set, new: ogr.Geometry, where) -> bool:
    """The line as absorbed meeting a contour more often than it did. Only
    what lies about the chain is asked: absorb changes the line no further
    from it than its reach, and elsewhere the line is as it was."""
    old = work.geo[main]
    for o, f in work.env.items():
        if o == main or o in chain or not _near(where, f, 2 * GAP_M):
            continue
        g = work.geo[o]
        if _meets(new, g) > _meets(old, g):
            return True
    return False
