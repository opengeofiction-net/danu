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


def _cells_by_owner(a, b, owner, owners: int) -> list[set]:
    """For each of ``owners`` ways, the union of ``_cells_of`` over its
    segments - ``owner`` saying whose each is - with the short segments,
    nearly all, boxed at once as ``_by_cell`` boxes them. A call a segment
    was 4.9 s of roantra's 3x3 opening, 807,000 of them."""
    out: list[set] = [set() for _ in range(owners)]
    if not len(a):
        return out
    lo = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    hi = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    span = hi - lo + 1
    small = span[:, 0] * span[:, 1] <= 16
    k = np.flatnonzero(small)
    got = []
    for dx in range(16):
        for dy in range(16 // (dx + 1)):
            m = k[(span[k, 0] > dx) & (span[k, 1] > dy)]
            if len(m):
                got.append(np.column_stack((owner[m], lo[m] + (dx, dy))))
    if got:
        rows = np.unique(np.concatenate(got), axis=0)
        starts = np.flatnonzero(np.r_[True, rows[1:, 0] != rows[:-1, 0]])
        for s0, e0 in zip(starts, np.r_[starts[1:], len(rows)], strict=True):
            out[int(rows[s0, 0])] = set(map(tuple, rows[s0:e0, 1:].tolist()))
    for i in np.flatnonzero(~small):
        out[int(owner[i])] |= _cells_of(a[i], b[i])
    return out


def _cells_many(a, b) -> set:
    """``_cells_by_owner`` of one way's segments."""
    return _cells_by_owner(a, b, np.zeros(len(a), dtype=np.int64), 1)[0]


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


def find(working_set, segments=None) -> list[Crossing]:
    """Every crossing between two contours of the working set; from its
    ``_segments`` if the caller has read them already."""
    keys, pts = segments if segments is not None else _segments(working_set)
    if not keys:
        return []
    lat0 = float(np.mean([p[:, 1].mean() for p in pts]))
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0
    a = np.concatenate([p[:-1] for p in pts]) * (kx, ky)
    b = np.concatenate([p[1:] for p in pts]) * (kx, ky)
    owner = np.concatenate([np.full(len(p) - 1, k) for k, p in enumerate(pts)])
    # segments by the cells they can meet another in - _cells_of's cells -
    # and the cells holding two contours or more tested a size at a time:
    # every cell of n segments stacked and its pairs tested together, not a
    # cell at a time - 70,000 cells and 6.9 s on roantra's 3x3
    by_size: dict = defaultdict(list)
    for idx in _by_cell(a, b).values():
        if len(idx) < 2:
            continue
        own = owner[idx]
        if own.min() == own.max():
            continue
        by_size[len(idx)].append(idx)
    ii_all, jj_all = [], []
    for n, groups in by_size.items():
        # a few thousand pairs' worth at a time, to keep the arrays small
        step = max(1, 2_000_000 // (n * n))
        for g0 in range(0, len(groups), step):
            idx = np.asarray(groups[g0:g0 + step])            # (m, n)
            sa, sb = a[idx], b[idx]                            # (m, n, 2)
            d1 = _orient(sa[:, :, None], sb[:, :, None], sa[:, None, :])
            d2 = _orient(sa[:, :, None], sb[:, :, None], sb[:, None, :])
            d3 = _orient(sa[:, None, :], sb[:, None, :], sa[:, :, None])
            d4 = _orient(sa[:, None, :], sb[:, None, :], sb[:, :, None])
            hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
                  (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
            own = owner[idx]
            hit &= own[:, :, None] != own[:, None, :]
            hit &= np.triu(np.ones((n, n), bool), 1)[None]
            gg, ii, jj = np.nonzero(hit)
            ii_all.append(idx[gg, ii])
            jj_all.append(idx[gg, jj])
    out, seen = [], set()
    if ii_all:
        ii = np.concatenate(ii_all)
        jj = np.concatenate(jj_all)
        # met a cell size at a time; one met twice keeps whichever came
        # first, the same crossing to the 0.1 m it is known by
        p, r = a[ii], b[ii] - a[ii]
        q, s = a[jj], b[jj] - a[jj]
        den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
        t = ((q[:, 0] - p[:, 0]) * s[:, 1] - (q[:, 1] - p[:, 1]) * s[:, 0]) / den
        x = p + r * t[:, None]
    else:
        ii = jj = x = ()
    for i, j, (px, py) in zip(ii, jj, x, strict=True):
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


def _segment_cells(a, b):
    """Each segment against each cell it can meet another in - ``_cells_of``'s
    cells - as two arrays, (segment, cell), the segments with a box of 16
    cells or fewer boxed at once and only the long rest one at a time."""
    lo = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    hi = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    span = hi - lo + 1
    small = np.flatnonzero(span[:, 0] * span[:, 1] <= 16)
    seg, cell = [], []
    for dx in range(16):
        for dy in range(16 // (dx + 1)):            # a box of 16 cells can be 16 by 1
            k = small[(span[small, 0] > dx) & (span[small, 1] > dy)]
            seg.append(k)
            cell.append(lo[k] + (dx, dy))
    for i in np.flatnonzero(span[:, 0] * span[:, 1] > 16):
        cs = _cells_of(a[i], b[i])
        seg.append(np.full(len(cs), i))
        cell.append(np.array(sorted(cs), dtype=np.int64).reshape(-1, 2))
    if not seg:
        return np.zeros(0, dtype=np.int64), np.zeros((0, 2), dtype=np.int64)
    return np.concatenate(seg), np.concatenate(cell).reshape(-1, 2)


def _by_cell(a, b) -> dict:
    """Segments by the cells they can meet another in: cell -> indices, each
    cell's in order. Grouped by sorting, not one segment at a time: 0.3 s
    an edit of N20E066's 1991 m contour, the 120,000 segments near it put
    in their cells singly."""
    out: dict = {}
    seg, cell = _segment_cells(a, b)
    if len(seg):
        order = np.lexsort((seg, cell[:, 1], cell[:, 0]))
        seg, cell = seg[order], cell[order]
        starts = np.flatnonzero(np.r_[True, (cell[1:] != cell[:-1]).any(1)])
        for s0, e0 in zip(starts, np.r_[starts[1:], len(seg)], strict=True):
            out[(int(cell[s0, 0]), int(cell[s0, 1]))] = seg[s0:e0].tolist()
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
        self._listed = None                    # sorted, until an edit
        keys, pts = segments = _segments(working_set)
        lat0 = float(np.mean([p[:, 1].mean() for p in pts])) if pts else 0.0
        self.k = np.array([111320.0 * math.cos(math.radians(lat0)), 110540.0])
        self._ways: dict = {}                    # (square, way) -> (ele, a, b, cells)
        self._cells: dict = defaultdict(set)     # cell -> {(square, way)}
        # every way's cells in one pass, not a way at a time: 14,270 ways
        # each paying the boxing's fixed cost was 3.9 s on roantra's 3x3
        metres = [p * self.k for p in pts]
        a = np.concatenate([m[:-1] for m in metres]) if metres else np.zeros((0, 2))
        b = np.concatenate([m[1:] for m in metres]) if metres else np.zeros((0, 2))
        owner = np.concatenate([np.full(len(m) - 1, n) for n, m in enumerate(metres)]) if metres \
            else np.zeros(0, dtype=np.int64)
        cells = _cells_by_owner(a, b, owner, len(metres))
        for (sq, wid, ele), m, cs in zip(keys, metres, cells, strict=True):
            self._ways[(sq, wid)] = (ele, m[:-1], m[1:], cs)
            for c in cs:
                self._cells[c].add((sq, wid))
        self._by_way: dict = defaultdict(set)
        for c in find(working_set, segments):
            self._by_way[c.a[:2]].add(c)
            self._by_way[c.b[:2]].add(c)

    def crossings(self) -> list[Crossing]:
        """Sorted once an edit: the panel and the map's marks both ask, and
        sorting the crossings of roantra's N44E029 set took 25 ms."""
        if self._listed is None:
            out = {c for cs in self._by_way.values() for c in cs}
            self._listed = sorted(out, key=lambda c: (c.lat, c.lon))
        return self._listed

    def _add(self, sq, wid, ele, lonlat):
        metres = lonlat * self.k
        a, b = metres[:-1], metres[1:]
        cells = _cells_many(a, b)
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
        self._listed = None
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
