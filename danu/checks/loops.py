"""Contours that cross themselves - R16 asked of one contour, a check (G8c).

R16 says contours may not cross, and a contour crossing itself is the same
fault: no surface has one level on both strands of a figure of eight. The
crossings check (G8a) pairs a contour only with others. Two shapes, both
found on gobras:

- **a crossing** - two segments of the one contour properly crossing: 23 in
  7 contours of the originals, none once they were cleaned;
- **a pinch** - the contour passing through one node twice: 20 in the
  originals, 6 after. Some are a loop through a node; some a spike, out along
  a segment and back over it; some a run out along a straight edge and back
  over the same nodes, one pinch for each node of it.

Each is cut out the same way: the part of the contour between the two
visits goes - at a crossing, a node is put where the strands cross - and on a
closed contour, which has two such parts, the shorter. A run out and back
goes whole with its outermost pinch.

No Qt and no GDAL. Segments in metres, bucketed by cell as the crossings
check does, and each cell's pairs tested at once.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from ..core import edits
from ..core.geometry import EPS, _orient
from .crossings import CELL_M, _cells_of


@dataclass(frozen=True)
class Loop:
    """Where a contour comes back to itself. ``i`` and ``j`` are positions
    in its refs: a pinch's two visits to ``node``; a crossing's two segments,
    each from refs[i] to refs[i + 1]."""
    contour: tuple                      # (square name, way id, elevation)
    kind: str                           # 'crossing' or 'pinch'
    i: int
    j: int
    lon: float
    lat: float
    node: int | None = None

    def describe(self) -> str:
        """Short enough for a row of the panel."""
        _, wid, ele = self.contour
        what = 'crosses itself' if self.kind == 'crossing' else f'through node {self.node} twice'
        return f'{ele:g} m contour, way {wid} - {what}'

    def explain(self) -> str:
        sq, wid, ele = self.contour
        what = 'crosses itself' if self.kind == 'crossing' else f'passes through node {self.node} twice'
        return f'the {ele:g} m contour, way {wid} in {sq}, {what}'


def _k(lat0: float) -> np.ndarray:
    return np.array([111320.0 * math.cos(math.radians(lat0)), 110540.0])


def _lonlat(square, way) -> np.ndarray | None:
    if any(r not in square.nodes for r in way.refs) or len(way.refs) < 3:
        return None
    return np.array([(square.nodes[r].lon, square.nodes[r].lat) for r in way.refs], dtype=float)


def _pinches(square, way, key) -> list[Loop]:
    """A node the contour holds twice - its closing node once."""
    refs = way.refs
    closed = refs[0] == refs[-1]
    out, seen = [], {}
    for i, r in enumerate(refs[:-1] if closed else refs):
        if r in seen:
            node = square.nodes[r]
            out.append(Loop(key, 'pinch', seen[r], i, node.lon, node.lat, r))
        else:
            seen[r] = i
    return out


def _self_crossings(lines, closed) -> list:
    """For lines in metres - each closed or not - every pair of segments of one line properly
    crossing, not next to each other: (line, i, j, point). All lines at
    once: segments grouped by line and cell, and the pairs in every group
    tested together, since nearly every group is a few segments and a
    call a group was most of the time."""
    if not lines:
        return []
    a = np.concatenate([m[:-1] for m in lines])
    b = np.concatenate([m[1:] for m in lines])
    owner = np.concatenate([np.full(len(m) - 1, k) for k, m in enumerate(lines)])
    first = np.concatenate([[0], np.cumsum([len(m) - 1 for m in lines])[:-1]])
    lo = np.floor(np.minimum(a, b) / CELL_M).astype(np.int64)
    hi = np.floor(np.maximum(a, b) / CELL_M).astype(np.int64)
    one = (lo == hi).all(axis=1)
    seg = list(np.flatnonzero(one))
    cx, cy = list(lo[one, 0]), list(lo[one, 1])
    for i in np.flatnonzero(~one):
        for c in _cells_of(a[i], b[i]):
            seg.append(i)
            cx.append(c[0])
            cy.append(c[1])
    seg, cx, cy = np.asarray(seg), np.asarray(cx), np.asarray(cy)
    order = np.lexsort((seg, cy, cx, owner[seg]))
    seg, cx, cy = seg[order], cx[order], cy[order]
    new = np.ones(len(seg), dtype=bool)
    new[1:] = (owner[seg][1:] != owner[seg][:-1]) | (cx[1:] != cx[:-1]) | (cy[1:] != cy[:-1])
    starts = np.flatnonzero(new)
    sizes = np.diff(np.append(starts, len(seg)))
    pi, pj = [], []
    for size in np.unique(sizes[sizes > 1]):
        groups = starts[sizes == size][:, None] + np.arange(size)[None]
        u, v = np.triu_indices(size, 1)
        pi.append(seg[groups[:, u]].ravel())
        pj.append(seg[groups[:, v]].ravel())
    if not pi:
        return []
    i, j = np.concatenate(pi), np.concatenate(pj)
    i, j = np.minimum(i, j), np.maximum(i, j)
    n = np.array([len(m) - 1 for m in lines])[owner[i]]
    li, lj = i - first[owner[i]], j - first[owner[i]]
    ring = np.asarray(closed)[owner[i]]
    keep = (lj - li >= 2) & ~(ring & (li == 0) & (lj == n - 1))
    i, j = i[keep], j[keep]
    d1 = _orient(a[j], b[j], a[i])
    d2 = _orient(a[j], b[j], b[i])
    d3 = _orient(a[i], b[i], a[j])
    d4 = _orient(a[i], b[i], b[j])
    hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
          (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
    out = set()
    for p, q in zip(i[hit], j[hit], strict=True):
        k = int(owner[p])
        out.add((k, int(p - first[k]), int(q - first[k])))
    return [(k, p, q, _meeting(a[first[k] + p], b[first[k] + p], a[first[k] + q], b[first[k] + q]))
            for k, p, q in sorted(out)]


def find_in(square, way) -> list[Loop]:
    """Every place the one contour comes back to itself."""
    return _find([(square, way)])


def _find(held) -> list[Loop]:
    out, lines, keys, closed = [], [], [], []
    for square, way in held:
        pts = _lonlat(square, way)
        if pts is None or way.ele is None:
            continue
        key = (square.name, way.id, way.ele)
        out += _pinches(square, way, key)
        k = _k(float(pts[:, 1].mean()))
        lines.append(pts * k)
        keys.append((key, k))
        closed.append(way.refs[0] == way.refs[-1])
    for line, i, j, x in _self_crossings(lines, closed):
        key, k = keys[line]
        lon, lat = x / k
        out.append(Loop(key, 'crossing', i, j, float(lon), float(lat)))
    out.sort(key=lambda lp: (str(lp.contour[0]), lp.contour[1], lp.i, lp.j))
    return out


def _meeting(p, p2, q, q2):
    r, s_ = p2 - p, q2 - q
    den = r[0] * s_[1] - r[1] * s_[0]
    t = ((q[0] - p[0]) * s_[1] - (q[1] - p[1]) * s_[0]) / den
    return p + r * t


def find(working_set) -> list[Loop]:
    return _find([(sq, w) for sq in working_set.squares.values() for w in sq.contours()])


@dataclass
class Cut:
    """What cutting a loop out does: the command, the run that goes as
    (lon, lat) points, and how long it is."""
    command: object
    removed: list
    metres: float
    nodes: int                          # vertices it takes with it


def cut(square, way, loop: Loop, alloc) -> Cut | str:
    """The loop cut out of the contour - or why not, as a string. The way is
    read from the square: an edit replaces the object."""
    way = square.ways.get(way.id)
    if way is None or loop.contour[1] != way.id:
        return 'that contour is no longer there'
    if loop not in find_in(square, way):
        return 'that loop is no longer there - the contour has changed'
    refs = list(way.refs)
    closed = refs[0] == refs[-1]
    pts = _lonlat(square, way)
    k = _k(float(pts[:, 1].mean()))
    new_nodes = {}
    if loop.kind == 'pinch':
        inner = refs[loop.i:loop.j + 1]                  # from the node round to it again
        inner_xy = pts[loop.i:loop.j + 1]
        outer = refs[:loop.i + 1] + refs[loop.j + 1:]
        outer_xy = np.vstack([pts[:loop.i + 1], pts[loop.j + 1:]])
    else:
        x = np.array([loop.lon, loop.lat])
        nid = alloc(square).take()
        new_nodes[nid] = (loop.lon, loop.lat)
        inner = [nid, *refs[loop.i + 1:loop.j + 1], nid]
        inner_xy = np.vstack([x, pts[loop.i + 1:loop.j + 1], x])
        outer = refs[:loop.i + 1] + [nid] + refs[loop.j + 1:]
        outer_xy = np.vstack([pts[:loop.i + 1], x, pts[loop.j + 1:]])

    def length(xy):
        return float(np.hypot(*np.diff(xy * k, axis=0).T).sum())
    # an open contour keeps the line and loses the loop; a closed one has two
    # loops either side of the place, and loses the shorter
    keep, gone = (outer, inner) if not closed or length(inner_xy) <= length(outer_xy) else (inner, outer)
    gone_xy = inner_xy if gone is inner else outer_xy
    if len(set(keep)) < (3 if closed else 2):
        return 'nothing of the contour would be left'
    taken = len(set(gone) - set(keep))
    cmd = edits.ReplaceWay(way.id, [(way.id, keep)], new_nodes)
    return Cut(cmd, [tuple(p) for p in gone_xy], length(gone_xy), taken)


class Index:
    """The loops of a working set, kept as it is edited: an edit's ways are
    asked again, each on its own - a way at a time is milliseconds."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._by_way: dict = defaultdict(list)
        for sq in working_set.squares.values():
            for w in sq.contours():
                found = find_in(sq, w)
                if found:
                    self._by_way[(sq.name, w.id)] = found

    def loops(self) -> list[Loop]:
        out = [lp for found in self._by_way.values() for lp in found]
        return sorted(out, key=lambda lp: (lp.lat, lp.lon))

    def update(self, square, way_ids) -> None:
        contours = {w.id: w for w in square.contours()}
        for wid in way_ids:
            self._by_way.pop((square.name, wid), None)
            way = contours.get(wid)
            if way is not None:
                found = find_in(square, way)
                if found:
                    self._by_way[(square.name, wid)] = found
