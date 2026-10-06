"""Contours that cross - R16, as a check of what the squares already hold (G8a).

R16 says contours may not cross, and the editor refuses a crossing as it is
drawn. Nothing asked it of what the squares already held, and gobras holds
6,714 crossings between 279 contours: a 425 m contour wandering down a massif
across 36 others, 337 times; 625 to 750 m contours run along a square's edge
across the 25 to 100 m ones that reach it. No surface satisfies a crossing,
and a river crossing a rogue contour reads as a climb - so this comes before
anything that bends contours to fit the water.

A crossing is two contours whose segments properly cross - ``geometry
.crossings``, the drawing check's own test - in any square of the working set,
across squares as well as within one. What a contour is, is ``Square
.contours``: a lake's outline and its fill lines are not.

No Qt and no GDAL. Segments are bucketed by cell and each cell's pairs tested
at once, and one crossing met twice is counted once. The count
was checked against a brute-force walk of the worst contour: 337 both ways.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from ..core.geometry import EPS, _orient

CELL_M = 500.0


def _cells_of(a, b) -> set:
    """The cells a segment, in metres, can meet another segment in. Its box
    of cells where that is small, which is nearly every contour segment;
    for a long one - a straight along a square's edge, a degree drawn
    across - the cells along its line and their neighbours, since a box of
    cells under a long diagonal is tens of thousands and almost all empty."""
    x0, y0 = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    x1, y1 = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    if (x1 - x0 + 1) * (y1 - y0 + 1) <= 16:
        return {(cx, cy) for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1)}
    n = int(np.hypot(*(b - a)) / (CELL_M / 2)) + 2
    pts = a + (b - a) * np.linspace(0.0, 1.0, n)[:, None]
    out = set()
    for cx, cy in np.floor(pts / CELL_M).astype(np.int64):
        out.update((cx + dx, cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    return out


@dataclass(frozen=True)
class Crossing:
    """Where two contours cross: each as (square name, way id, elevation)."""
    a: tuple
    b: tuple
    lon: float
    lat: float


def _segments(working_set):
    """Every contour segment in the set, in metres about the set's middle,
    with the contour each belongs to."""
    keys, pts = [], []
    for sq in working_set.squares.values():
        for way in sq.contours():
            run = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs if r in sq.nodes]
            if len(run) >= 2:
                keys.append((sq.name, way.id, way.ele))
                pts.append(np.asarray(run, dtype=float))
    return keys, pts


def find(working_set) -> list[Crossing]:
    """Every crossing between two contours of the working set."""
    keys, pts = _segments(working_set)
    if not keys:
        return []
    lat0 = float(np.mean([p[:, 1].mean() for p in pts]))
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0
    a = np.concatenate([p[:-1] for p in pts]) * (kx, ky)
    b = np.concatenate([p[1:] for p in pts]) * (kx, ky)
    owner = np.concatenate([np.full(len(p) - 1, k) for k, p in enumerate(pts)])
    lo = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    hi = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    cells: dict = defaultdict(list)
    # most segments are far shorter than a cell and lie in one; the rest
    # go in every cell they can meet another in
    one = (lo == hi).all(axis=1)
    for i in np.flatnonzero(one):
        cells[(int(lo[i, 0]), int(lo[i, 1]))].append(i)
    for i in np.flatnonzero(~one):
        for c in _cells_of(a[i], b[i]):
            cells[c].append(i)
    out, seen = [], set()
    for idx in cells.values():
        if len(idx) < 2:
            continue
        idx = np.asarray(idx)
        if len(np.unique(owner[idx])) < 2:
            continue
        sa, sb = a[idx], b[idx]
        # every pair in the cell at once: segment i against segment j
        d1 = _orient(sa[:, None], sb[:, None], sa[None, :])
        d2 = _orient(sa[:, None], sb[:, None], sb[None, :])
        d3 = _orient(sa[None, :], sb[None, :], sa[:, None])
        d4 = _orient(sa[None, :], sb[None, :], sb[:, None])
        hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
              (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
        hit &= owner[idx][:, None] != owner[idx][None, :]
        hit = np.triu(hit, 1)
        ii, jj = np.nonzero(hit)
        if not len(ii):
            continue
        p, r = sa[ii], sb[ii] - sa[ii]
        q, s = sa[jj], sb[jj] - sa[jj]
        den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
        t = ((q[:, 0] - p[:, 0]) * s[:, 1] - (q[:, 1] - p[:, 1]) * s[:, 0]) / den
        x = p + r * t[:, None]
        for i, j, (px, py) in zip(idx[ii], idx[jj], x, strict=True):
            # one crossing, however it was met: the same two segments in
            # another cell, or a crossing on a vertex, where both segments
            # meeting at it cross - 25 of them on gobras
            ka, kb = sorted((owner[i], owner[j]))
            point = (ka, kb, round(px, 1), round(py, 1))
            if point in seen:
                continue
            seen.add(point)
            # the two named in one order, the order an update names them in
            first, second = sorted((keys[ka], keys[kb]), key=lambda t: (str(t[0]), t[1]))
            out.append(Crossing(first, second, px / kx, py / ky))
    out.sort(key=lambda c: (c.lat, c.lon))
    return out


@dataclass
class Offender:
    """One contour and what it crosses - a row of the panel, worst first."""
    contour: tuple                               # (square name, way id, elevation)
    crossings: list                              # the Crossings it is in
    partners: dict                               # the contour it crosses -> how many times

    def describe(self) -> str:
        sq, wid, ele = self.contour
        n, k = len(self.crossings), len(self.partners)
        return (f'{ele:g} m contour, way {wid} in {sq} - crosses {k} contour{"s" * (k != 1)}'
                + (f', {n} times' if n != k else ''))


def by_contour(crossings: list[Crossing]) -> list[Offender]:
    """The crossings grouped by the contour in them, the contour that crosses
    the most others first - a rogue contour is one row, not hundreds, and is
    at the top, since a crossing does not say which of its two is wrong but
    one that crosses thirty-six others usually does."""
    groups: dict = {}
    for c in crossings:
        for mine, theirs in ((c.a, c.b), (c.b, c.a)):
            o = groups.setdefault(mine, Offender(mine, [], {}))
            o.crossings.append(c)
            o.partners[theirs] = o.partners.get(theirs, 0) + 1
    return sorted(groups.values(), key=lambda o: (-len(o.partners), -len(o.crossings),
                                                  str(o.contour[0]), o.contour[1]))


def _pair_hits(a1, b1, a2, b2):
    """Which segments of one set properly cross which of another, and where:
    (i, j, x) for each crossing, i into the first set and j the second."""
    d1 = _orient(a2[None, :], b2[None, :], a1[:, None])
    d2 = _orient(a2[None, :], b2[None, :], b1[:, None])
    d3 = _orient(a1[:, None], b1[:, None], a2[None, :])
    d4 = _orient(a1[:, None], b1[:, None], b2[None, :])
    hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
          (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
    ii, jj = np.nonzero(hit)
    r = b1[ii] - a1[ii]
    s = b2[jj] - a2[jj]
    den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
    t = ((a2[jj, 0] - a1[ii, 0]) * s[:, 1] - (a2[jj, 1] - a1[ii, 1]) * s[:, 0]) / den
    return ii, jj, a1[ii] + r * t[:, None]


def _by_cell(a, b) -> dict:
    """Segments by the cells they can meet another in: cell -> indices."""
    out: dict = defaultdict(list)
    lo = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    hi = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    one = (lo == hi).all(axis=1)
    for i in np.flatnonzero(one):
        out[(int(lo[i, 0]), int(lo[i, 1]))].append(i)
    for i in np.flatnonzero(~one):
        for c in _cells_of(a[i], b[i]):
            out[c].append(i)
    return out


class Index:
    """The crossings of a working set, kept as it is edited.

    Built once by ``find``; after that an edit asks only about the ways it
    touched - each re-read, its old crossings dropped, and its segments tested
    against the contours sharing a cell with it. On gobras the whole scan is
    1.3 s - 3.6 s to build the index - which an edit should not wait for;
    one way is a few milliseconds.
    """

    def __init__(self, working_set):
        self.working_set = working_set
        keys, pts = _segments(working_set)
        lat0 = float(np.mean([p[:, 1].mean() for p in pts])) if pts else 0.0
        self.k = np.array([111320.0 * math.cos(math.radians(lat0)), 110540.0])
        self._ways: dict = {}                    # (square, way) -> (ele, a, b, cells)
        self._cells: dict = defaultdict(set)     # cell -> {(square, way)}
        for (sq, wid, ele), p in zip(keys, pts, strict=True):
            self._add(sq, wid, ele, p)
        self._by_way: dict = defaultdict(set)
        for c in find(working_set):
            self._by_way[c.a[:2]].add(c)
            self._by_way[c.b[:2]].add(c)

    def crossings(self) -> list[Crossing]:
        out = {c for cs in self._by_way.values() for c in cs}
        return sorted(out, key=lambda c: (c.lat, c.lon))

    def _add(self, sq, wid, ele, lonlat):
        metres = lonlat * self.k
        a, b = metres[:-1], metres[1:]
        cells = set().union(*(_cells_of(s, e) for s, e in zip(a, b, strict=True)))
        self._ways[(sq, wid)] = (ele, a, b, cells)
        for c in cells:
            self._cells[c].add((sq, wid))

    def _drop(self, key):
        held = self._ways.pop(key, None)
        if held is not None:
            for c in held[3]:
                self._cells[c].discard(key)
        for c in self._by_way.pop(key, set()):
            other = c.b[:2] if c.a[:2] == key else c.a[:2]
            self._by_way[other].discard(c)

    def update(self, square, way_ids) -> None:
        """The ways an edit touched, in one square: each read again as it
        stands - gone, no longer a contour, moved or re-levelled - and its
        crossings found again."""
        contours = {w.id: w for w in square.contours()}
        for wid in way_ids:
            key = (square.name, wid)
            self._drop(key)
            way = contours.get(wid)
            if way is None:
                continue
            run = [(square.nodes[r].lon, square.nodes[r].lat) for r in way.refs if r in square.nodes]
            if len(run) < 2:
                continue
            self._add(square.name, wid, way.ele, np.asarray(run, dtype=float))
            ele, a, b, cells = self._ways[key]
            near = sorted(set().union(*(self._cells[c] for c in cells)) - {key},
                          key=lambda k: (str(k[0]), k[1]))
            if not near:
                continue
            # every nearby contour's segments, each tagged with its way, and
            # tested cell by cell against this way's segments in the same
            # cell - not all against all, which for the 425 m rogue's 613
            # segments was a matrix of everything near it and 400 ms
            oa = np.concatenate([self._ways[o][1] for o in near])
            ob = np.concatenate([self._ways[o][2] for o in near])
            who = np.concatenate([np.full(len(self._ways[o][1]), n) for n, o in enumerate(near)])
            mine_in, theirs_in = _by_cell(a, b), _by_cell(oa, ob)
            hits = []
            for cell, mi in mine_in.items():
                ti = theirs_in.get(cell)
                if ti is None:
                    continue
                mi, ti = np.asarray(mi), np.asarray(ti)
                ii, jj, x = _pair_hits(a[mi], b[mi], oa[ti], ob[ti])
                hits += zip(ti[jj], x, strict=True)
            seen = set()
            for j, (px, py) in hits:
                other = near[who[j]]
                point = (other, round(px, 1), round(py, 1))
                if point in seen:
                    continue
                seen.add(point)
                mine, theirs = (square.name, wid, ele), (other[0], other[1], self._ways[other][0])
                first, second = sorted((mine, theirs), key=lambda t: (str(t[0]), t[1]))
                c = Crossing(first, second, px / self.k[0], py / self.k[1])
                self._by_way[key].add(c)
                self._by_way[other].add(c)
