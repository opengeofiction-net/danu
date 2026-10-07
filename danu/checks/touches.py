"""Contours that touch or lie on one another - R16's other half, and the
spec's duplicate coincident contours, as a check (G8e).

R16 says a contour may not cross one of another level at all; the crossings
check (G8a) finds proper crossings, and these are the rest of it:

- **shared** - a node held by contours at different levels: 115 on cleaned
  gobras, 88 of them N21E086's southern edge, where 25 to 175 m contours run in
  a stack along it a metre apart; over 4,000 in the originals;
- **coincident** - two contours running within ``NEAR_M`` of each other for a
  segment or more: two closed 100 m knolls sharing a side, a 100 m triangle on
  top of the 100 m line beside it, that edge stack again. At one level it is a
  duplicate, which confuses the fill; at two, the rasterised contours have two
  levels in one cell and whichever way the file holds last wins it - the
  surface then depends on the order of the ways (measured on gobras).

Contours of one level meeting at a node are not one: that is two ways of a
contour joined. A shared node inside a coincident stretch of the same two is
said once, as the stretch.

No Qt and no GDAL. Within a square - a square's file is what holds the node
ids - by cell, every vertex measured against the segments sharing its cell.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .crossings import CELL_M, _by_cell

NEAR_M = 1.0


@dataclass(frozen=True)
class Touch:
    kind: str                   # 'shared' or 'coincident'
    a: tuple                    # (square name, way id, elevation)
    b: tuple
    lon: float
    lat: float
    node: int | None = None     # a shared node's id
    segments: int = 0           # a coincident stretch's segments, of the way listed first
    metres: float = 0.0

    def describe(self) -> str:
        (_, wa, ea), (_, wb, eb) = self.a, self.b
        if self.kind == 'shared':
            return f'{ea:g} m way {wa} and {eb:g} m way {wb} share node {self.node}'
        what = 'a duplicate of' if ea == eb else 'on top of'
        return f'{ea:g} m way {wa} runs {self.metres:,.0f} m {what} {eb:g} m way {wb}'

    def explain(self) -> str:
        sq = self.a[0]
        if self.kind == 'shared':
            return (f'in {sq}, the {self.a[2]:g} m contour (way {self.a[1]}) and the {self.b[2]:g} m '
                    f'(way {self.b[1]}) share node {self.node} - contours of two levels may not meet '
                    '(R16); U unglues it')
        if self.a[2] == self.b[2]:
            return (f'in {sq}, the {self.a[2]:g} m contour (way {self.a[1]}) runs {self.metres:,.0f} m '
                    f'on top of another at its level (way {self.b[1]}) - a duplicate; delete the '
                    'copy, or cut out what doubles')
        return (f'in {sq}, the {self.a[2]:g} m contour (way {self.a[1]}) runs {self.metres:,.0f} m '
                f'within {NEAR_M:g} m of the {self.b[2]:g} m (way {self.b[1]}) - two levels in one '
                'place (R16); move one of them')


def _k(lat: float) -> np.ndarray:
    return np.array([111320.0 * math.cos(math.radians(lat)), 110540.0])


def _held(square, way, k):
    """A contour's points in metres, or None when it is not whole."""
    if len(way.refs) < 2 or any(r not in square.nodes for r in way.refs):
        return None
    return np.array([(square.nodes[r].lon, square.nodes[r].lat) for r in way.refs]) * k


def find_in(square, only: set | None = None) -> list[Touch]:
    """Every touch in one square - or, given ``only``, every one a way of
    ``only`` is in, which is what an edit asks again."""
    k = _k(square.name.lat + 0.5)
    held = [(w, _held(square, w, k)) for w in square.contours()]
    return _scan(square, [(w, P) for w, P in held if P is not None], only)


def _scan(square, held, only) -> list[Touch]:
    """The touches among ``held`` - (way, points in metres) - that a way of
    ``only`` is in, or all of them."""
    ways = [w for w, _ in held]
    if not ways:
        return []
    k = _k(square.name.lat + 0.5)
    by_id = {w.id: w for w in ways}
    key = {w.id: (square.name, w.id, w.ele) for w in ways}
    out = []
    # shared nodes, between ways of different levels - only the nodes of
    # ``only``'s ways, when an edit asks
    holders: dict = defaultdict(set)
    mine = set().union(*(by_id[w].refs for w in only if w in by_id)) if only is not None else None
    for w in ways:
        for r in (set(w.refs) if mine is None else set(w.refs) & mine):
            holders[r].add(w.id)
    shared = {}
    for r, hs in holders.items():
        if len(hs) < 2 or (only is not None and not hs & only):
            continue
        hs = sorted(hs)
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                if only is not None and hs[i] not in only and hs[j] not in only:
                    continue                        # a pair the edit did not touch
                if by_id[hs[i]].ele != by_id[hs[j]].ele:
                    shared.setdefault((hs[i], hs[j]), []).append(r)
    # coincident stretches: a vertex within NEAR_M of another way's segment,
    # two of them next to each other - a segment lying along the other
    pts, owner, pos, a, b, seg_owner = [], [], [], [], [], []
    for w, P in held:
        pts.append(P)
        owner += [w.id] * len(P)
        pos += list(range(len(P)))
        a.append(P[:-1])
        b.append(P[1:])
        seg_owner += [w.id] * (len(P) - 1)
    P = np.concatenate(pts)
    owner, pos = np.array(owner), np.array(pos)
    a, b, seg_owner = np.concatenate(a), np.concatenate(b), np.array(seg_owner)
    if only is not None:
        # an edit's: only what lies in the cells of its ways and theirs round
        # them - a vertex within a metre of a segment is in its cell or the next
        def cell_key(xy):
            c = np.floor(xy / CELL_M).astype(np.int64)
            return c[:, 0] * 1_000_003 + c[:, 1]
        theirs = np.isin(owner, list(only))
        c = np.floor(P[theirs] / CELL_M).astype(np.int64)
        near_cells = np.unique(np.concatenate([(c + (dx, dy)) @ np.array([1_000_003, 1])
                                               for dx in (-1, 0, 1) for dy in (-1, 0, 1)]))
        keep_p = np.isin(cell_key(P), near_cells)
        long_seg = (np.abs(np.floor(a / CELL_M) - np.floor(b / CELL_M)) > 1).any(1)
        keep_s = np.isin(cell_key(a), near_cells) | np.isin(cell_key(b), near_cells) | long_seg
        P, owner, pos = P[keep_p], owner[keep_p], pos[keep_p]
        a, b, seg_owner = a[keep_s], b[keep_s], seg_owner[keep_s]
    hits: dict = defaultdict(set)              # (way, other) -> positions of way's vertices on other
    if len(P) and len(a):
        # the vertices by cell, grouped at once rather than one by one
        cells = np.floor(P / CELL_M).astype(np.int64)
        order = np.lexsort((cells[:, 1], cells[:, 0]))
        cs = cells[order]
        starts = np.flatnonzero(np.r_[True, (cs[1:] != cs[:-1]).any(1)])
        ends = np.r_[starts[1:], len(cs)]
        by_cell = {(int(cs[s0, 0]), int(cs[s0, 1])): order[s0:e0] for s0, e0 in zip(starts, ends, strict=True)}
        for cell, segs in _by_cell(a, b).items():
            vi = by_cell.get(cell)
            if vi is None:
                continue
            segs, vi = np.asarray(segs), np.asarray(vi)
            if len(np.union1d(owner[vi], seg_owner[segs])) < 2:
                continue                                # one contour's own cell: nothing to meet
            if only is not None:
                keep_v = np.isin(owner[vi], list(only))
                keep_s = np.isin(seg_owner[segs], list(only))
                if not keep_v.any() and not keep_s.any():
                    continue
            A, ab = a[segs], b[segs] - a[segs]
            w_ = P[vi][:, None] - A[None]
            t = np.clip((w_ * ab[None]).sum(2) / np.maximum((ab * ab).sum(1)[None], 1e-12), 0.0, 1.0)
            d = np.hypot(*(A[None] + ab[None] * t[..., None] - P[vi][:, None]).transpose(2, 0, 1))
            near = (d < NEAR_M) & (owner[vi][:, None] != seg_owner[segs][None])
            for x, y in zip(*np.nonzero(near), strict=True):
                hits[(int(owner[vi[x]]), int(seg_owner[segs[y]]))].add(int(pos[vi[x]]))
    stretches: dict = {}
    on_pair: dict = {}                          # pair -> the nodes of every stretch of it
    for (wid, oid), at in hits.items():
        if only is not None and wid not in only and oid not in only:
            continue
        at = sorted(at)
        w = by_id[wid]
        n = len(w.refs) - 1
        closed = w.refs[0] == w.refs[-1]
        runs, cur = [], [at[0]]
        for p in at[1:]:
            if p == cur[-1] + 1:
                cur.append(p)
            else:
                runs.append(cur)
                cur = [p]
        runs.append(cur)
        if closed and len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == n:
            runs[0] = runs.pop() + runs[0]         # round the ring's closing node
        for run in runs:
            if len(run) < 2:
                continue
            xy = np.array([pts_of(square, w, i) for i in run]) * k
            metres = float(np.hypot(*np.diff(xy, axis=0).T).sum())
            if metres <= NEAR_M:
                continue                            # vertices on one spot, not a stretch
            pair = tuple(sorted((wid, oid)))
            on_pair.setdefault(pair, set()).update(w.refs[i] for i in run)
            # the longest, and of two as long the lower way id's: decided by
            # what they are, not by the order the square holds its ways in
            best = stretches.get(pair)
            if best is None or (round(metres, 3), -wid) > (round(best[2], 3), -best[0]):
                mid = square.nodes[w.refs[run[len(run) // 2]]]
                stretches[pair] = (wid, len(run) - 1, metres, mid.lon, mid.lat)
    for (x, y), (wid, segs_, metres, lon, lat) in stretches.items():
        oid = y if wid == x else x
        out.append(Touch('coincident', key[wid], key[oid], lon, lat, segments=segs_, metres=metres))
    for (x, y), nodes in shared.items():
        on = on_pair.get((x, y), set())
        for r in nodes:
            if r in on:
                continue                            # said as the stretch
            n = square.nodes[r]
            out.append(Touch('shared', key[x], key[y], n.lon, n.lat, node=r))
    out.sort(key=lambda t: (t.kind, t.lat, t.lon))
    return out


def pts_of(square, way, i):
    n = square.nodes[way.refs[i]]
    return n.lon, n.lat


def find(working_set) -> list[Touch]:
    return [t for sq in working_set.squares.values() for t in find_in(sq)]


class Index:
    """The touches of a working set, kept as it is edited: an edit's ways
    read again, and asked against the ways whose boxes come near them -
    each way's points kept, so an edit does not read its square again."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._by_way: dict = defaultdict(set)
        self._held: dict = {}                  # square name -> {way id: (way, points, box)}
        for sq in working_set.squares.values():
            k = _k(sq.name.lat + 0.5)
            here = {}
            for w in sq.contours():
                P = _held(sq, w, k)
                if P is not None:
                    here[w.id] = (w, P, np.r_[P.min(0), P.max(0)])
            self._held[sq.name] = here
            for t in _scan(sq, [(w, P) for w, P, _ in here.values()], None):
                self._add(t)

    def _add(self, t):
        self._by_way[t.a[:2]].add(t)
        self._by_way[t.b[:2]].add(t)

    def touches(self) -> list[Touch]:
        out = {t for ts in self._by_way.values() for t in ts}
        return sorted(out, key=lambda t: (t.kind, t.lat, t.lon))

    def update(self, square, way_ids) -> None:
        ids = set(way_ids)
        here = self._held.setdefault(square.name, {})
        k = _k(square.name.lat + 0.5)
        contours = {w.id: w for w in square.contours()}
        for wid in ids:
            for t in self._by_way.pop((square.name, wid), set()):
                for other in (t.a[:2], t.b[:2]):
                    self._by_way.get(other, set()).discard(t)
            here.pop(wid, None)
            way = contours.get(wid)
            P = _held(square, way, k) if way is not None else None
            if P is not None:
                here[wid] = (way, P, np.r_[P.min(0), P.max(0)])
        mine = [here[w][2] for w in ids if w in here]
        if not mine:
            return
        lo = np.min([b_[:2] for b_ in mine], axis=0) - NEAR_M - 1
        hi = np.max([b_[2:] for b_ in mine], axis=0) + NEAR_M + 1
        near = [(w, P) for w, P, box in here.values()
                if (box[2:] >= lo).all() and (box[:2] <= hi).all()]
        for t in _scan(square, near, ids & set(here)):
            self._add(t)
