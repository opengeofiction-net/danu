"""A contour of a square's own that comes back to itself, mended on opening.

What JOSM lists in a vectorised square and Danu's checks did not see, the
checks comparing node ids and testing proper crossings only - roantra's
N44E026, once its nodes at one place were made one (``edits.merge_doubled``):

- **a spike** - out along the contour and back: over the same nodes (``a b
  a``), JOSM's "way contains segment twice", or along the same line through
  other nodes, a turn of 180 degrees, a fold - 62 tips in 52 contours;
- **a loop** - round from a node to the same node again, or to a node that
  stands on a segment of the contour elsewhere.

A spike is cut back to its root: it holds no ground. A loop is made a ring of
its own, sharing the node with what is left - a saddle at the level, which the
touches check allows, and nothing lost, as cutting it out would lose it. A
node standing on a segment of its own contour is put into that segment first,
which makes it a loop through one node. A ring of no area left is dropped by
the caller, as one of fewer than three places.

Within ``TOL_M`` - 5 cm, the file's places being a centimetre. Found across a
square's contours at once in numpy, segments bucketed by cell; only a contour
found is walked in Python. No Qt and no GDAL.
"""

from __future__ import annotations

import math

import numpy as np

TOL_M = 0.05
CELL_M = 100.0
_BIG = 64                   # a segment over this many cells is bucketed along its line


def scale(lat: float) -> tuple[float, float]:
    """Metres a degree of longitude and of latitude, at ``lat``."""
    return 111320.0 * math.cos(math.radians(lat)), 110540.0


# ------------------------------------------------------------- finding

def _ring(refs: list[int], closed: bool) -> list[int]:
    return list(refs[:-1] if closed else refs)


def suspects(xy_of, ways) -> set[int]:
    """The ids of ``ways`` - (id, refs, closed) - with a fold or a node on a
    segment of their own. ``xy_of(refs)`` is their nodes in metres."""
    ids, lens, closed, chunks = [], [], [], []
    for wid, refs, cl in ways:
        c = _ring(refs, cl)
        if len(c) < 3:
            continue
        ids.append(wid)
        lens.append(len(c))
        closed.append(cl)
        chunks.append(c)
    if not ids:
        return set()
    P = xy_of([r for c in chunks for r in c])
    lens = np.asarray(lens)
    closed = np.asarray(closed)
    W = np.repeat(np.arange(len(ids)), lens)
    start = np.repeat(np.cumsum(lens) - lens, lens)
    idx = np.arange(len(P))
    pos = idx - start
    L = lens[W]
    cl = closed[W]
    prev = np.where(pos == 0, np.where(cl, idx + L - 1, -1), idx - 1)
    nxt = np.where(pos == L - 1, np.where(cl, idx - L + 1, -1), idx + 1)
    found = set()
    ok = (prev >= 0) & (nxt >= 0)
    i = idx[ok]
    u = P[i] - P[prev[ok]]
    v = P[nxt[ok]] - P[i]
    lu, lv = np.hypot(*u.T), np.hypot(*v.T)
    big = np.maximum(lu, lv)
    fold = (lu > 0) & (lv > 0) & (np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) < TOL_M * big) \
        & ((u * v).sum(axis=1) < 0)
    found.update(int(w) for w in np.unique(W[i[fold]]))
    node, _ = _on_own_segment(P, W, nxt)
    found.update(int(w) for w in np.unique(W[node]))
    return {ids[w] for w in found}


def _on_own_segment(P: np.ndarray, W: np.ndarray, nxt: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each node standing on a segment of its own way, not either end of it,
    as (node index, the segment's first node's index): ``W`` the index of
    each node's way - 0 up, packed into 20 bits of a key, not a way's id -
    ``nxt`` the next node along its way, or -1."""
    idx = np.arange(len(P))
    # segments by cell, each node against its way's segments in its cell
    s = idx[nxt >= 0]
    a, b = P[s], P[nxt[s]]
    lo = np.floor((np.minimum(a, b) - TOL_M) / CELL_M).astype(np.int64)
    hi = np.floor((np.maximum(a, b) + TOL_M) / CELL_M).astype(np.int64)
    span = hi - lo + 1
    count = span[:, 0] * span[:, 1]
    small = count <= _BIG
    rep = np.repeat(np.flatnonzero(small), count[small])
    within = np.arange(len(rep)) - np.repeat(np.cumsum(count[small]) - count[small], count[small])
    cx = lo[rep, 0] + within % span[rep, 0]
    cy = lo[rep, 1] + within // span[rep, 0]
    seg, sx, sy = [rep], [cx], [cy]
    for k in np.flatnonzero(~small):
        n = int(np.hypot(*(b[k] - a[k])) / (CELL_M / 2)) + 2
        cells = {(int(x) + dx, int(y) + dy)
                 for x, y in np.floor((a[k] + (b[k] - a[k]) * np.linspace(0, 1, n)[:, None]) / CELL_M)
                 for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        seg.append(np.full(len(cells), k))
        sx.append(np.array([c[0] for c in cells], dtype=np.int64))
        sy.append(np.array([c[1] for c in cells], dtype=np.int64))
    seg, sx, sy = np.concatenate(seg), np.concatenate(sx), np.concatenate(sy)
    off = 1 << 21

    def key(w, x, y):
        return (w.astype(np.int64) << 44) | ((x + off) << 22) | (y + off)
    skey = key(W[s[seg]], sx, sy)
    order = np.argsort(skey, kind='stable')
    skey, seg = skey[order], seg[order]
    cell = np.floor(P / CELL_M).astype(np.int64)
    nkey = key(W, cell[:, 0], cell[:, 1])
    first, last = np.searchsorted(skey, nkey, 'left'), np.searchsorted(skey, nkey, 'right')
    cnt = last - first
    node = np.repeat(idx, cnt)
    which = seg[np.repeat(first, cnt) + np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)]
    sa, sb = s[which], nxt[s[which]]
    keep = (sa != node) & (sb != node)
    node, sa, sb = node[keep], sa[keep], sb[keep]
    ab = P[sb] - P[sa]
    ap = P[node] - P[sa]
    lab = np.hypot(*ab.T)
    t = (ap * ab).sum(axis=1) / np.where(lab > 0, lab * lab, 1)
    off_line = np.abs(ab[:, 0] * ap[:, 1] - ab[:, 1] * ap[:, 0]) / np.where(lab > 0, lab, 1)
    on = (lab > 0) & (off_line < TOL_M) & (t * lab > TOL_M) & ((1 - t) * lab > TOL_M)
    return node[on], sa[on]


# ------------------------------------------------------------- mending

def _repeats(c: list[int], closed: bool) -> tuple[list[int], list[list[int]], int]:
    """Spikes over the same nodes cut back, loops through one node made
    rings - innermost first - on a contour as a list of its nodes, a ring's
    first not repeated at its end."""
    rings: list[list[int]] = []
    spiked = 0
    while True:
        changed = True
        while changed and len(c) > 1:
            changed = False
            n = len(c)
            for i in range(n) if closed else range(1, n):
                if c[i] == c[i - 1]:                      # a node twice in a row
                    del c[i]
                    changed = True
                    break
                if (closed or i < n - 1) and n > 2 and c[i - 1] == c[(i + 1) % n]:
                    for k in sorted((i, (i + 1) % n), reverse=True):   # a b a: b and the second a
                        del c[k]
                    spiked += 1
                    changed = True
                    break
        seen: dict[int, int] = {}
        best = None
        for j, r in enumerate(c):
            if r in seen and (best is None or j - seen[r] < best[1] - best[0]):
                best = (seen[r], j)
            seen[r] = j
        if best is None:
            return c, rings, spiked
        i, j = best
        rings.append(c[i:j])
        c = c[:i + 1] + c[j + 1:]


def _fold(P: np.ndarray, closed: bool) -> int | None:
    """The first node the contour turns back at, along the line it came."""
    n = len(P)
    if n < 3:
        return None
    i = np.arange(n) if closed else np.arange(1, n - 1)
    u = P[i] - P[i - 1]
    v = P[(i + 1) % n] - P[i]
    lu, lv = np.hypot(*u.T), np.hypot(*v.T)
    hit = (lu > 0) & (lv > 0) & (np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) < TOL_M * np.maximum(lu, lv)) \
        & ((u * v).sum(axis=1) < 0)
    k = np.flatnonzero(hit)
    return int(i[k[0]]) if len(k) else None


def _touch(P: np.ndarray, closed: bool) -> tuple[int, int] | None:
    """A node standing on a segment of its own contour, not either end of
    it - (node index, segment index) - or None."""
    n = len(P)
    nxt = np.arange(1, n + 1)
    nxt[-1] = 0 if closed else -1
    one_way = np.zeros(n, dtype=np.int64)          # every node of the one contour: way index 0
    node, seg = _on_own_segment(P, one_way, nxt)
    if not len(node):
        return None
    k = int(np.argmin(node))
    return int(node[k]), int(seg[k])


def unpinched(refs: list[int], closed: bool) -> tuple[list[int], list[list[int]], int]:
    """``mended`` by node ids alone: the line, its loops as rings - each
    closed, its first node again at its end - and how many spikes went."""
    c, rings, spiked = _repeats(_ring(refs, closed), closed)
    return _closed(c, refs, closed), [r + [r[0]] for r in rings], spiked


def _closed(c: list[int], refs: list[int], closed: bool) -> list[int]:
    if closed and c:
        if refs and refs[0] in c:                     # a ring's start kept
            k = c.index(refs[0])
            c = c[k:] + c[:k]
        c = c + [c[0]]
    return c


def mended(refs: list[int], closed: bool, xy_of) -> tuple[list[int], list[list[int]], int]:
    """The contour with its spikes cut back and its loops made rings: the
    line, the rings - each closed - and how many spikes went. ``xy_of(refs)``
    is nodes in metres."""
    work = [(_ring(refs, closed), closed, True)]
    line: list[int] = []
    rings: list[list[int]] = []
    spikes = 0
    while work:
        c, cl, main = work.pop()
        # each pass takes a node out, or puts one in that the next takes out
        # with a loop, so this ends long before the bound; the bound is a guard,
        # and a contour it stopped is left as far as it got, for the checks
        for _ in range(4 * len(c) + 8):
            c, loops, spiked = _repeats(c, cl)
            spikes += spiked
            work += [(r, True, False) for r in loops]
            if len(c) < 3:
                break
            P = xy_of(c)
            k = _fold(P, cl)
            if k is not None:
                del c[k]
                spikes += 1
                continue
            t = _touch(P, cl)
            if t is None:
                break
            node, seg = t
            c.insert(seg + 1, c[node])
        if main:
            line = _closed(c, refs, cl)
        else:
            rings.append(c + [c[0]])
    return line, rings, spikes
