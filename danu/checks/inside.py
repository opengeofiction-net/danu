"""What lies inside a ring - H1b, two rows of the validation table:

- **a water body spanning contours** (R33). A lake is flat; a contour at
  another level inside it says the ground under it is not. Listed with the
  levels inside, and F flattens it. Flowing water is not a body - a river area
  descends along its course (R27) - and a lake's own fill lines and the
  contours at its level, which flatten leaves touching its shore, are not
  other levels.
- **a ring with nothing inside it** (R39) - a closed contour holding no other
  contour and no spot height: the top of a hill, or the bottom of a hollow,
  with nothing to say how high or how deep it goes. A report rather than a
  warning: plenty are meant, and a hill's top ring is still a hill. And only
  a ring of some size, 10 ha by default: half the 3,758 on gobras are under
  0.6 ha, knolls a few dozen metres across where a spot height would say
  nothing the ring does not; 170 are 10 ha or more.
- **a coastline drawn backwards** - a ring of ``natural=coastline``, one way
  or several end to end, winding clockwise round contours above sea level. A
  coastline keeps land on its left, so the build reads what it holds as sea:
  sangria's island, its coast drawn clockwise, built with everything below
  about 200 m at sea level and only its contour lines standing out of it. A
  clockwise ring holding nothing above 0 m is a lagoon or a pond drawn as
  coast, and is left alone when land lies round it, on three sides or four;
  with open water round it, it is an islet drawn backwards - 18 of the 23
  empty clockwise rings on util, against 1,388 empty anticlockwise ones. An
  island inside a clockwise ring, its own coast anticlockwise and its ways
  agreeing, is a hole in it. A coastline is never itself the land: huz
  draws its coast at ele=1. A coast that is no ring in its square - huz's
  island runs across 79 E, each square holding two open halves, its node ids
  its own - is judged by its sides instead: the contour vertices within
  ``SIDE_M`` of it, by the side of the coastline segment nearest each. Land
  is on a coastline's left, a vertex above 0 m being land and below it sea,
  and one at 0 m the shore itself and no vote; an open chain with nearly all
  of it on the right is drawn backwards. Only so near: a contour a kilometre off is as likely
  the far shore of a strait, nearest this coast across the water.

A contour is inside a ring when a vertex of it is, by crossings of a ray with
every ring of a body counted together, so an island is a hole - or when a
segment of it crosses the ring with no vertex inside, as a contour with a
vertex either side of a small lake does. A node the ring itself passes
through - a contour sharing a node with a lake's shore - is neither; one
only drawn along the shore, on nodes of its own, is judged as any other.

Per square, the contours by their boxes, kept as edited: an edit asks again the
rings and bodies whose box it touched, as they were and as they are. No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from ..core import ladder as L
from ..core.rings import closed_rings, relation_rings
from ..core.square import parse_ele
from ..water.overpass import flows
from .files import Finding
from .spots import spot_heights

CHUNK = 64                       # a ring's edges asked a chunk at a time, each by its own box


def _box(X, Y) -> tuple:
    return (X.min(), Y.min(), X.max(), Y.max())


def _near(boxes, n, x0, y0, x1, y1):
    """Which of n rings' boxes overlap a box - every ring when none are
    given. A sea of 683 rings asks a contour of the few near it."""
    if boxes is None:
        return range(n)
    B = np.asarray(boxes, float).reshape(-1, 4)
    return np.flatnonzero((B[:, 0] <= x1) & (B[:, 2] >= x0) & (B[:, 1] <= y1) & (B[:, 3] >= y0))


def _among(ids, sorted_ids) -> np.ndarray:
    """Which of the ids are in an array of them kept sorted - np.isin sorts
    the second afresh each call, 15 ms a contour for the sea's 114k nodes."""
    k = np.searchsorted(sorted_ids, ids)
    return sorted_ids[np.minimum(k, len(sorted_ids) - 1)] == ids if len(sorted_ids) else np.zeros(len(ids), bool)


def _chunks(X, Y) -> np.ndarray:
    """A ring's chunks of edges, the box of each as a row (x0, y0, x1, y1):
    chunk k is the edges from node k * CHUNK to node (k + 1) * CHUNK."""
    n = len(X) - 1
    out = np.empty((-(-n // CHUNK), 4))
    for k, j in enumerate(range(0, n, CHUNK)):
        cx, cy = X[j:j + CHUNK + 1], Y[j:j + CHUNK + 1]
        out[k] = cx.min(), cy.min(), cx.max(), cy.max()
    return out


def inside(px, py, rings, boxes=None, chunks=None) -> np.ndarray:
    """Which of the points lie inside the rings, even-odd over all of them.
    The rings are closed, so a point outside one's box crosses it an even
    number of times: each ring is asked only of the points in its box, and
    each chunk of its edges only of the points level with it and to its
    left, which a ray to the east could cross it from. ``boxes`` and
    ``chunks``, a ring's each, are worked out here if not given."""
    px, py = np.asarray(px, float), np.asarray(py, float)
    odd = np.zeros(px.shape, bool)
    if not px.size:
        return odd
    for k in _near(boxes, len(rings), px.min(), py.min(), px.max(), py.max()):
        X, Y = rings[k]
        x0, y0, x1, y1 = boxes[k] if boxes is not None else _box(X, Y)
        sel = np.flatnonzero((px >= x0) & (px <= x1) & (py >= y0) & (py <= y1))
        if not len(sel):
            continue
        qx, qy = px[sel], py[sel]
        o = np.zeros(len(sel), bool)
        ch = chunks[k] if chunks is not None else _chunks(X, Y)
        for c in np.flatnonzero((ch[:, 1] <= qy.max()) & (ch[:, 3] >= qy.min()) & (ch[:, 2] >= qx.min())):
            _cx0, cy0, cx1, cy1 = ch[c]
            near = np.flatnonzero((qy >= cy0) & (qy <= cy1) & (qx <= cx1))
            if not len(near):
                continue
            j = c * CHUNK
            ax, ay = X[j:j + CHUNK + 1][:-1, None], Y[j:j + CHUNK + 1][:-1, None]
            bx, by = X[j + 1:j + CHUNK + 1][:, None], Y[j + 1:j + CHUNK + 1][:, None]
            nx, ny = qx[near], qy[near]
            crosses = (ay > ny) != (by > ny)
            with np.errstate(divide='ignore', invalid='ignore'):
                at = ax + (ny - ay) * (bx - ax) / (by - ay)
            o[near] ^= (np.count_nonzero(crosses & (nx < at), axis=0) % 2).astype(bool)
        odd[sel] ^= o
    return odd


def crosses(X, Y, rings, box, boxes=None, chunks=None) -> bool:
    """Whether a line's segments properly cross any edge of the rings - a
    contour across a lake with no vertex in the water. Touching at a vertex
    is not a crossing, so a contour snapped to a shore is not one. Each ring,
    and each chunk of its edges, is asked only of the segments over its own
    box - ``boxes`` and ``chunks`` as for ``inside``."""
    ax, ay, bx, by = X[:-1], Y[:-1], X[1:], Y[1:]
    sx0, sx1, sy0, sy1 = np.minimum(ax, bx), np.maximum(ax, bx), np.minimum(ay, by), np.maximum(ay, by)
    near = np.flatnonzero((sx0 <= box[2]) & (sx1 >= box[0]) & (sy0 <= box[3]) & (sy1 >= box[1]))
    if not len(near):
        return False
    for k in _near(boxes, len(rings), sx0[near].min(), sy0[near].min(), sx1[near].max(), sy1[near].max()):
        RX, RY = rings[k]
        r = boxes[k] if boxes is not None else _box(RX, RY)
        sel = near[(sx0[near] <= r[2]) & (sx1[near] >= r[0]) & (sy0[near] <= r[3]) & (sy1[near] >= r[1])]
        if not len(sel):
            continue
        ch = chunks[k] if chunks is not None else _chunks(RX, RY)
        lo_x, hi_x, lo_y, hi_y = sx0[sel].min(), sx1[sel].max(), sy0[sel].min(), sy1[sel].max()
        for c in np.flatnonzero((ch[:, 0] <= hi_x) & (ch[:, 2] >= lo_x) & (ch[:, 1] <= hi_y) & (ch[:, 3] >= lo_y)):
            cx0, cy0, cx1, cy1 = ch[c]
            seg = sel[(sx0[sel] <= cx1) & (sx1[sel] >= cx0) & (sy0[sel] <= cy1) & (sy1[sel] >= cy0)]
            if not len(seg):
                continue
            ax, ay, bx, by = (X[:-1][seg][:, None], Y[:-1][seg][:, None],
                              X[1:][seg][:, None], Y[1:][seg][:, None])
            j = c * CHUNK
            cx, cy = RX[j:j + CHUNK + 1][:-1], RY[j:j + CHUNK + 1][:-1]
            dx, dy = RX[j + 1:j + CHUNK + 1], RY[j + 1:j + CHUNK + 1]
            d1 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            d2 = (bx - ax) * (dy - ay) - (by - ay) * (dx - ax)
            d3 = (dx - cx) * (ay - cy) - (dy - cy) * (ax - cx)
            d4 = (dx - cx) * (by - cy) - (dy - cy) * (bx - cx)
            if (((d1 > 0) & (d2 < 0) | (d1 < 0) & (d2 > 0))
                    & ((d3 > 0) & (d4 < 0) | (d3 < 0) & (d4 > 0))).any():
                return True
    return False


def _overlap(box, boxes) -> np.ndarray:
    return ((boxes[:, 0] <= box[2]) & (boxes[:, 2] >= box[0])
            & (boxes[:, 1] <= box[3]) & (boxes[:, 3] >= box[1]))


@dataclass
class _Line:
    id: int
    ele: float
    refs: np.ndarray
    X: np.ndarray
    Y: np.ndarray
    box: tuple
    closed: bool
    area: float                  # square metres, a closed one's; 0 for an open one


BARE_MIN_M2 = 100_000            # 10 ha: the smallest ring reported as holding nothing


def _area(X, Y) -> float:
    """A ring's area in square metres, the degrees scaled at its latitude."""
    kx = 111320 * math.cos(math.radians(float(Y.mean())))
    return abs(float(np.dot(X[:-1], Y[1:]) - np.dot(X[1:], Y[:-1]))) / 2 * kx * 110540


def _line(square, way) -> _Line | None:
    refs = [r for r in way.refs if r in square.nodes]
    if len(refs) < 2:
        return None
    X = np.array([square.nodes[r].lon for r in refs])
    Y = np.array([square.nodes[r].lat for r in refs])
    closed = len(way.refs) > 3 and way.refs[0] == way.refs[-1] and len(refs) == len(way.refs)
    return _Line(way.id, way.ele, np.array(refs, dtype=np.int64), X, Y,
                 (X.min(), Y.min(), X.max(), Y.max()), closed, _area(X, Y) if closed else 0.0)


@dataclass
class _Body:
    key: tuple                   # ('way' | 'relation', id)
    level: float | None
    rings: list                  # [(X, Y)]
    on: np.ndarray               # the node ids of its outline, sorted, once each
    ways: set                    # the ways of its outline - what an edit names
    box: tuple
    what: str
    boxes: np.ndarray            # each ring's own, a row each: a contour asks only the rings near it
    chunks: list                 # each ring's chunks of edges, by box (_chunks)


def _bodies(square) -> dict:
    out = {}
    members = {m.ref for r in square.relations.values() for m in r.members if m.type == 'way'}
    for w in square.ways.values():
        if (w.tags.get('natural') != 'water' or flows(w.tags) or w.id in members
                or not (len(w.refs) > 3 and w.refs[0] == w.refs[-1])):
            continue
        b = _body(square, ('way', w.id), w.tags, [w.refs], {w.id})
        if b is not None:
            out[b.key] = b
    for r in square.relations.values():
        if r.tags.get('natural') != 'water' or flows(r.tags):
            continue
        b = _body(square, ('relation', r.id), r.tags, relation_rings(square, r),
                  {m.ref for m in r.members if m.type == 'way'})
        if b is not None:
            out[b.key] = b
    return out


def _body(square, key, tags, ring_refs, ways) -> _Body | None:
    rings, on = [], []
    for refs in ring_refs:
        pts = [square.nodes[r] for r in refs if r in square.nodes]
        if len(pts) < 4:
            continue
        rings.append((np.array([p.lon for p in pts]), np.array([p.lat for p in pts])))
        on.extend(refs)
    if not rings:
        return None
    xs = np.concatenate([X for X, _ in rings]); ys = np.concatenate([Y for _, Y in rings])
    name = tags.get('name')
    what = f'lake "{name}"' if name else f'lake, {key[0]} {key[1]}'
    return _Body(key, parse_ele(tags.get('ele')), rings, np.unique(np.array(on, dtype=np.int64)), ways,
                 (xs.min(), ys.min(), xs.max(), ys.max()), what, np.array([_box(X, Y) for X, Y in rings]),
                 [_chunks(X, Y) for X, Y in rings])


def _signed(X, Y) -> float:
    """Twice a ring's signed area in square degrees: positive anticlockwise."""
    return float(np.dot(X[:-1], Y[1:]) - np.dot(X[1:], Y[:-1]))


def coast_ways(square) -> set[int]:
    return {w.id for w in square.ways.values() if w.tags.get('natural') == 'coastline'}


def _coasts(square) -> tuple[dict, set]:
    """The coastline ways closed on themselves and drawn clockwise, each as
    a body at 0 m whose rings are its own and the anticlockwise ones inside
    it - islands in it, holes under even-odd. Keyed ('coast', its id).

    And a ring of several ways end to end, when every one of them runs on
    from the last as drawn. Not when they disagree: a way's direction is its
    own, and stitching turns a way to run on from the one before - one of
    huz's two halves reversed, the other was turned to match it and dropped
    off the list. Those ways are judged each by its sides, as every way
    that is not a ring of its own is too. So is an island drawn in ways that
    disagree: it is no hole in a ring round it.

    And the ways of the rings taken, either way round, which are judged as
    rings and not by their sides as well."""
    ways = [square.ways[i] for i in sorted(coast_ways(square))]
    rings = []
    for refs in closed_rings([w.refs for w in ways]):
        if not _as_drawn(refs, [w.refs for w in ways if not (len(w.refs) > 3 and w.refs[0] == w.refs[-1])
                                and set(w.refs) <= set(refs)]):
            continue
        pts = [square.nodes[r] for r in refs if r in square.nodes]
        if len(pts) != len(refs):
            continue
        X, Y = np.array([p.lon for p in pts]), np.array([p.lat for p in pts])
        rings.append((refs, X, Y, _box(X, Y), _signed(X, Y)))
    out = {}
    ringed = {w.id for refs, *_ in rings for w in ways if set(w.refs) <= set(refs)}
    for refs, X, Y, box, area in rings:
        if area >= 0:
            continue
        on = set(refs)
        mine = sorted(w.id for w in ways if set(w.refs) <= on)
        holes = [(r, x, y) for r, x, y, b, a in rings if a > 0 and b[0] >= box[0] and b[1] >= box[1]
                 and b[2] <= box[2] and b[3] <= box[3]]
        ring_refs = [refs, *(r for r, _, _ in holes)]
        all_rings = [(X, Y), *((x, y) for _, x, y in holes)]
        if not mine:
            continue                       # a ring is its ways' to list, and has none of its own
        key = ('coast', int(refs[0]))            # by its own node: a way can lie on two rings
        listed = ', '.join(str(i) for i in mine[:3]) + (f' and {len(mine) - 3} more' if len(mine) > 3 else '')
        what = f'coastline, way{"s" * (len(mine) != 1)} {listed}'
        out[key] = _Body(key, 0.0, all_rings, np.unique(np.array([r for rr in ring_refs for r in rr], dtype=np.int64)),
                         set(mine), box, what, np.array([_box(x, y) for x, y in all_rings]),
                         [_chunks(x, y) for x, y in all_rings])
    return out, ringed


SIDE_M = 250.0                   # how near an open coast a contour vertex says which side its land is
SIDE_SHARE = 0.9                 # the share of those on its right that says it is drawn backwards
SIDE_MIN = 10                    # and how many at least


def _side(a, b, p) -> np.ndarray:
    return (b[:, 0] - a[:, 0]) * (p[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (p[:, 0] - a[:, 0])


def _as_drawn(ring, pieces) -> bool:
    """Whether every piece of a ring runs the ring's way: each node of it
    followed in the ring by the piece's next."""
    n = len(ring) - 1
    at = {r: i for i, r in enumerate(ring[:-1])}
    return all(ring[(at[a] + 1) % n] == b for piece in pieces for a, b in pairwise(piece) if a in at)


class _Sides:
    """A square's coastline ways that are not rings of their own - open, or
    a part of a ring of several - each in its own direction, for which side
    of it the land is. In metres about the square's middle latitude, the
    segments by cells of ``SIDE_M``."""

    def __init__(self, square, ringed=()):
        ways = [square.ways[i] for i in sorted(coast_ways(square)) if i not in ringed]
        lat0 = getattr(square.name, 'lat', 0) + 0.5
        self.kx, self.ky = 111320 * math.cos(math.radians(lat0)), 110540.0
        self.keys, self.ways, self.what = [], [], []
        A, B, PREV, NEXT, FIRST, LAST, C = [], [], [], [], [], [], []
        for w in ways:
            chain = w.refs
            if (len(chain) > 3 and chain[0] == chain[-1]) or any(r not in square.nodes for r in chain):
                continue
            xy = np.array([(square.nodes[r].lon * self.kx, square.nodes[r].lat * self.ky) for r in chain])
            n = len(xy) - 1
            if n < 1:
                continue
            mine = [w.id]
            k = len(self.keys)
            self.keys.append(('coast', w.id))
            self.ways.append(set(mine))
            listed = ', '.join(str(i) for i in mine[:3]) + (f' and {len(mine) - 3} more' if len(mine) > 3 else '')
            self.what.append(f'coastline, way{"s" * (len(mine) != 1)} {listed}')
            A.append(xy[:-1]); B.append(xy[1:]); C.append(np.full(n, k))
            gap = np.full((1, 2), np.nan)
            # each segment's neighbours, for a vertex nearest a corner; a way's
            # ends have none, and a vertex nearest one has no side - where it
            # meets the next way, that way's segment is as likely the nearest
            PREV.append(np.vstack([gap, xy[:-2]])); NEXT.append(np.vstack([xy[2:], gap]))
            FIRST.append(np.arange(n) == 0); LAST.append(np.arange(n) == n - 1)
        self.empty = not A
        if self.empty:
            return
        self.A, self.B, self.C = np.concatenate(A), np.concatenate(B), np.concatenate(C)
        self.PREV, self.NEXT = np.concatenate(PREV), np.concatenate(NEXT)
        self.FIRST, self.LAST = np.concatenate(FIRST), np.concatenate(LAST)
        lo, hi = np.minimum(self.A, self.B), np.maximum(self.A, self.B)
        self.lo, self.hi = lo.min(0) - SIDE_M, hi.max(0) + SIDE_M
        c0, c1 = np.floor(lo / SIDE_M).astype(np.int64), np.floor(hi / SIDE_M).astype(np.int64)
        self.cells: dict = {}
        for i in range(len(self.A)):
            for cx in range(c0[i, 0], c1[i, 0] + 1):
                for cy in range(c0[i, 1], c1[i, 1] + 1):
                    self.cells.setdefault((cx, cy), []).append(i)

    def votes(self, ln) -> dict:
        """What a contour says of each chain, {chain: [vertices on its left
        or right as they should be, the other way]}: a vertex above 0 m is
        land and below it sea, judged by the side of the segment nearest it,
        within ``SIDE_M``."""
        out: dict = {}
        if self.empty or ln.ele == 0:
            return out
        P = np.column_stack([ln.X * self.kx, ln.Y * self.ky])
        m = (P[:, 0] >= self.lo[0]) & (P[:, 0] <= self.hi[0]) & (P[:, 1] >= self.lo[1]) & (P[:, 1] <= self.hi[1])
        P = P[m]
        if not len(P):
            return out
        cell = np.floor(P / SIDE_M).astype(np.int64)
        keys, back = np.unique(cell, axis=0, return_inverse=True)
        for g, (cx, cy) in enumerate(keys.tolist()):
            segs = sorted({i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for i in self.cells.get((cx + dx, cy + dy), ())})
            if not segs:
                continue
            pts = P[back.ravel() == g]
            s = np.array(segs)
            a, b = self.A[s][None], self.B[s][None]
            d = b - a
            t = np.clip(((pts[:, None] - a) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-12), 0, 1)
            dist = np.hypot(*(pts[:, None] - (a + t[..., None] * d)).transpose(2, 0, 1))
            k = dist.argmin(1)
            rows = np.arange(len(pts))
            near, tk, i = dist[rows, k] <= SIDE_M, t[rows, k], s[k]
            cross = _side(self.A[i], self.B[i], pts)
            # nearest a corner: left of it if left of both its segments where
            # the line turns left there, of either where it turns right
            for at, ina, inb, outa, outb in ((tk <= 0, self.PREV[i], self.A[i], self.A[i], self.B[i]),
                                             (tk >= 1, self.A[i], self.B[i], self.B[i], self.NEXT[i])):
                c = at & ~np.isnan(ina[:, 0]) & ~np.isnan(outb[:, 0])
                if c.any():
                    s_in, s_out = _side(ina[c], inb[c], pts[c]), _side(outa[c], outb[c], pts[c])
                    left_turn = _side(ina[c], inb[c], outb[c]) > 0
                    cross[c] = np.where(left_turn, np.where((s_in > 0) & (s_out > 0), 1.0, -1.0),
                                        np.where((s_in > 0) | (s_out > 0), 1.0, -1.0))
            cross[((tk <= 0) & self.FIRST[i]) | ((tk >= 1) & self.LAST[i])] = 0
            ok = near & (cross != 0)
            right_way = (cross > 0) == (ln.ele > 0)
            for chain, rw in zip(self.C[i][ok].tolist(), right_way[ok].tolist(), strict=True):
                v = out.setdefault(chain, [0, 0])
                v[0 if rw else 1] += 1
        return out


class _Square:
    """One square's contours by their boxes, its bodies and its spot heights."""

    def __init__(self, square, bare_min: float = BARE_MIN_M2):
        self.square = square
        self.bare_min = bare_min
        self.lines = {}
        for w in square.contours():
            ln = _line(square, w)
            if ln is not None:
                self.lines[w.id] = ln
        self.bodies = _bodies(square)
        self.coasts, ringed = _coasts(square)
        self.coast_ids = coast_ways(square)
        self.sides = _Sides(square, ringed)
        self.side_votes = ({i: self.sides.votes(ln) for i, ln in self.lines.items() if i not in self.coast_ids}
                           if not self.sides.empty else {})
        self.spots = {i: (n.lon, n.lat) for i, (n, _) in spot_heights(square).items()}
        self._arrays = None
        # body key -> line id -> whether that line lies in or across it: what
        # spanned() found, kept so that an edit asks again only the lines it
        # changed - a line not edited cannot have moved into or out of a lake
        # that was not. Roantra's estuary, asked whole, is seconds
        self.held: dict = {}

    def arrays(self):
        if self._arrays is None:
            ids = list(self.lines)
            boxes = np.array([self.lines[i].box for i in ids]).reshape(-1, 4)
            self._arrays = (ids, boxes)
        return self._arrays

    def lines_near(self, box, but=None):
        ids, boxes = self.arrays()
        if not ids:
            return []
        return [self.lines[ids[k]] for k in np.flatnonzero(_overlap(box, boxes)) if ids[k] != but]

    # -------------------------------------------------------------- R33
    def _in(self, body, ln) -> bool:
        """Whether a line lies in or across a body, at a level not its own."""
        if body.level is not None and abs(ln.ele - body.level) < 1e-6:
            return False
        x0, y0, x1, y1 = body.box
        m = (ln.X >= x0) & (ln.X <= x1) & (ln.Y >= y0) & (ln.Y <= y1)
        if m.any():
            m[m] = ~_among(ln.refs[m], body.on)
        return bool((m.any() and inside(ln.X[m], ln.Y[m], body.rings, body.boxes, body.chunks).any())
                    or crosses(ln.X, ln.Y, body.rings, body.box, body.boxes, body.chunks))

    def spanned(self, body, only=None) -> Finding | None:
        """R33 for a body: the levels of the contours in it. ``only``, the
        ids of the lines an edit changed, asks just those again - the body
        itself unchanged - and the rest as held."""
        held = self.held.get(body.key)
        if only is None or held is None:
            held = self.held[body.key] = {ln.id: True for ln in self.lines_near(body.box) if self._in(body, ln)}
        else:
            x0, y0, x1, y1 = body.box
            for i in only:
                held.pop(i, None)
                ln = self.lines.get(i)
                if (ln is not None and ln.box[0] <= x1 and ln.box[2] >= x0 and ln.box[1] <= y1
                        and ln.box[3] >= y0 and self._in(body, ln)):
                    held[i] = True
        levels = {self.lines[i].ele for i in held if i in self.lines}
        if not levels:
            return None
        lo, hi = min(levels), max(levels)
        span = f'{L.format_ele(lo)} m' if lo == hi else f'{L.format_ele(lo)} to {L.format_ele(hi)} m'
        n = len(levels)
        level = f', level {L.format_ele(body.level)} m' if body.level is not None else ''
        text = f'{body.what} - {n} contour level{"s" * (n != 1)} inside, {span}{level}'
        why = (f'a lake is flat, and contours at {span} inside it say the ground under it is not - '
               'select it and F flattens it at its level, or move the contours out of it')
        X, Y = body.rings[0]
        return Finding(self.square.name, 'lake', text, why, float(X[len(X) // 2]), float(Y[len(Y) // 2]),
                       tuple(map(float, body.box)), way=body.key[1] if body.key[0] == 'way' else None,
                       relation=body.key[1] if body.key[0] == 'relation' else None)

    # --------------------------------------------------- the coast's side
    def backwards(self, body, only=None) -> dict:
        """A clockwise coastline ring holding contours above 0 m, or holding
        nothing with open water round it: land the build will read as sea,
        as a finding for each of its ways. ``only`` as for ``spanned``."""
        held = self.held.get(body.key)
        x0, y0, x1, y1 = body.box
        if only is None or held is None:
            held = self.held[body.key] = {ln.id: True for ln in self.lines_near(body.box)
                                          if ln.ele > 0 and ln.id not in self.coast_ids and self._in(body, ln)}
        else:
            for i in only:
                held.pop(i, None)
                ln = self.lines.get(i)
                if (ln is not None and ln.ele > 0 and i not in self.coast_ids and ln.box[0] <= x1
                        and ln.box[2] >= x0 and ln.box[1] <= y1 and ln.box[3] >= y0 and self._in(body, ln)):
                    held[i] = True
        levels = {self.lines[i].ele for i in held if i in self.lines}
        if levels:
            n = len(held)
            reason = (f'drawn clockwise round {n} contour{"s" * (n != 1)} above sea level, '
                      f'up to {L.format_ele(max(levels))} m')
        else:
            sides = self._land_round(body)
            if sides >= 3:
                return {}                          # a pond in the land, drawn as coast
            reason = ('drawn clockwise round nothing, open water round it' if not sides else
                      f'drawn clockwise round nothing, land beside it in {sides} of the four quarters '
                      'round it only') + ' - an islet drawn backwards'
        why = ('a coastline keeps land on its left and sea on its right, and this one runs clockwise '
               'round land - the build reads everything it holds as sea, down to the contour lines. '
               'Select each of its ways and R reverses it')
        # each way's row at the way's own middle, not the ring's: chosen, the
        # map goes to the way that R will reverse
        nodes, ways = self.square.nodes, self.square.ways
        at = {}
        for wid in body.ways:
            refs = [r for r in ways[wid].refs if r in nodes] if wid in ways else []
            if refs:
                n = nodes[refs[len(refs) // 2]]
                at[wid] = (float(n.lon), float(n.lat))
        X, Y = body.rings[0]
        return _each_way(self.square.name, body.ways, reason, why,
                         float(X[len(X) // 2]), float(Y[len(Y) // 2]), tuple(map(float, body.box)), at)

    def _land_round(self, body) -> int:
        """On how many sides of four - by the direction from its middle - a
        contour above 0 m lies within ``SIDE_M`` outside a ring: a pond has
        land all round it, an islet near a shore on one side or two."""
        X, Y = body.rings[0]
        kx, ky = 111320 * math.cos(math.radians(float(Y.mean()))), 110540.0
        px, py = SIDE_M / kx, SIDE_M / ky
        x0, y0, x1, y1 = body.box
        big = (x0 - px, y0 - py, x1 + px, y1 + py)
        R = np.column_stack([X * kx, Y * ky])
        a, b = R[:-1], R[1:]
        d = b - a
        cx, cy = R[:, 0].mean(), R[:, 1].mean()
        quads = set()
        for ln in self.lines_near(big):
            if ln.ele <= 0 or ln.id in self.coast_ids:
                continue
            m = (ln.X >= big[0]) & (ln.X <= big[2]) & (ln.Y >= big[1]) & (ln.Y <= big[3])
            P = np.column_stack([ln.X[m] * kx, ln.Y[m] * ky])
            if not len(P):
                continue
            t = np.clip(((P[:, None] - a) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-12), 0, 1)
            near = np.hypot(*(P[:, None] - (a + t[..., None] * d)).transpose(2, 0, 1)).min(1) <= SIDE_M
            ang = np.degrees(np.arctan2(P[near, 1] - cy, P[near, 0] - cx)) % 360
            quads |= set((ang // 90).astype(int).tolist())
            if len(quads) == 4:
                break
        return len(quads)

    def backwards_open(self) -> dict:
        """The open coastline chains drawn backwards by their sides, as
        {key: Finding}: nearly all the contour vertices near one on its
        right."""
        out = {}
        if self.sides.empty:
            return out
        tally: dict = {}
        for votes in self.side_votes.values():
            for chain, (ok, back) in votes.items():
                t = tally.setdefault(chain, [0, 0])
                t[0] += ok
                t[1] += back
        for chain, (ok, back) in tally.items():
            if back < SIDE_MIN or back < SIDE_SHARE * (ok + back):
                continue
            reason = (f'land on its right: {back} contour vertices within '
                      f'{SIDE_M:g} m on its sea side, {ok} on its land side')
            why = ('a coastline keeps land on its left and sea on its right, and the land beside this one '
                   'is on its right - the build reads it as sea. Select each of its ways and R reverses it')
            seg = np.flatnonzero(self.sides.C == chain)
            mid = self.sides.A[seg[len(seg) // 2]]
            pts = np.concatenate([self.sides.A[seg], self.sides.B[seg[-1:]]])
            box = (pts[:, 0].min() / self.sides.kx, pts[:, 1].min() / self.sides.ky,
                   pts[:, 0].max() / self.sides.kx, pts[:, 1].max() / self.sides.ky)
            out.update(_each_way(self.square.name, self.sides.ways[chain],
                                 reason, why, float(mid[0] / self.sides.kx), float(mid[1] / self.sides.ky),
                                 tuple(map(float, box))))
        return out

    # -------------------------------------------------------------- R39
    def bare(self, ln) -> Finding | None:
        if not ln.closed or ln.area < self.bare_min:
            return None
        x0, y0, x1, y1 = ln.box
        ring = [(ln.X, ln.Y)]
        for other in self.lines_near(ln.box, but=ln.id):
            m = (other.X >= x0) & (other.X <= x1) & (other.Y >= y0) & (other.Y <= y1)
            if m.any():
                m[m] = ~np.isin(other.refs[m], ln.refs)
            if (m.any() and inside(other.X[m], other.Y[m], ring).any()) or crosses(other.X, other.Y, ring, ln.box):
                return None
        near = [p for p in self.spots.values() if x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
        if near and inside([p[0] for p in near], [p[1] for p in near], ring).any():
            return None
        text = f'{L.format_ele(ln.ele)} m ring, way {ln.id} - {ln.area / 1e4:,.0f} ha, nothing inside'
        why = ('a closed contour with no contour and no spot height inside: the top of a hill or the '
               'bottom of a hollow, with nothing to say how high or deep it goes - a spot height '
               'would (R37); plenty are meant')
        k = len(ln.X) // 2
        return Finding(self.square.name, 'bare', text, why, float(ln.X[k]), float(ln.Y[k]),
                       tuple(map(float, ln.box)), way=ln.id)


def _all(sq: _Square) -> dict:
    out = {}
    for key, body in sq.bodies.items():
        f = sq.spanned(body)
        if f is not None:
            out[('lake', key)] = f
    for ln in sq.lines.values():
        f = sq.bare(ln)
        if f is not None:
            out[('bare', ln.id)] = f
    out.update(_coast_findings(sq))
    return out


def _coast_findings(sq: _Square, only=None) -> dict:
    out = {}
    for body in sq.coasts.values():
        out.update(sq.backwards(body, None if only is None or body.ways & only else only))
    out.update(sq.backwards_open())
    return out


def _each_way(square, ways, reason, why, lon, lat, box, at=None) -> dict:
    """A finding a way, each its own row to select and reverse, keyed
    ('coast', way id), naming the others it is drawn end to end with; at its
    own point in ``at`` when given, (lon, lat) otherwise."""
    out = {}
    for wid in sorted(ways):
        here = (at or {}).get(wid, (lon, lat))
        others = sorted(ways - {wid})
        also = (f', drawn end to end with {", ".join(map(str, others[:3]))}'
                + (f' and {len(others) - 3} more' if len(others) > 3 else '')) if others else ''
        out[('coast', wid)] = Finding(square, 'coast', f'coastline, way {wid}{also} - {reason}', why,
                                      *here, box, way=wid)
    return out


def backwards_coasts(square) -> list[Finding]:
    """The coastlines drawn backwards round land - for the build to say,
    which reads what they hold as sea whatever this says."""
    return list(_coast_findings(_Square(square)).values())


def held(square) -> tuple[dict, int]:
    """The lakes a square's surface holds at their level, as
    ``{'way/<id>' | 'relation/<id>': (level, rings of (lon, lat))}``, and how
    many with a level are not held: those R33 reports, contours at other
    levels inside them. Holding one of those would put the ground under it at
    the lake's level whatever the contours say - roantra's N44E030 has 34
    ways of water at 0 m over hills up to 100 m - so it is left to its shore
    and the contours, as before, until flattening moves them out."""
    s = _Square(square)
    out, spanned = {}, 0
    for key, body in s.bodies.items():
        if body.level is None:
            continue
        if s.spanned(body) is not None:
            spanned += 1
            continue
        out[f'{key[0]}/{key[1]}'] = (body.level, [list(zip(X.tolist(), Y.tolist(), strict=True))
                                                  for X, Y in body.rings])
    return out, spanned


def find_in(square, bare_min: float = BARE_MIN_M2) -> list[Finding]:
    return list(_all(_Square(square, bare_min)).values())


def find(working_set, bare_min: float = BARE_MIN_M2) -> list[Finding]:
    return [f for sq in working_set.squares.values() for f in find_in(sq, bare_min)]


class Index:
    """The findings of a working set, kept as edited: the rings and bodies
    whose box an edit touched, as it was and as it is, are asked again."""

    def __init__(self, working_set, bare_min: float = BARE_MIN_M2):
        self.working_set = working_set
        self.bare_min = bare_min
        self._squares = {sq.name: _Square(sq, bare_min) for sq in working_set.squares.values()}
        self._found = {name: _all(s) for name, s in self._squares.items()}

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for found in self._found.values() for f in found.values() if kind is None or f.kind == kind]
        return sorted(out, key=lambda f: (f.kind, str(f.square), f.text))

    def update(self, square, way_ids=(), spot_ids=()) -> None:
        s = self._squares.get(square.name)
        if s is None or s.square is not square:
            self._squares[square.name] = s = _Square(square, self.bare_min)
            self._found[square.name] = _all(s)
            return
        way_ids, spot_ids = set(way_ids or ()), set(spot_ids or ())
        if not (way_ids or spot_ids):
            return
        # what moved: the points an edited line or outline had and has not
        # now, or has and had not, and where an edited spot height was and is.
        # Only a ring or a body round one of those can have changed - a node
        # moved at one end of a contour two thousand long asks the rings at
        # that end, not every ring in the contour's box
        before = {i: s.lines[i] for i in way_ids if i in s.lines}
        bodies_before = [b for b in s.bodies.values() if b.ways & way_ids]
        coasts_before = [b for b in s.coasts.values() if b.ways & way_ids]
        spots_before = {i: s.spots[i] for i in spot_ids if i in s.spots}
        water = square.water_bodies()
        for i in way_ids:
            s.lines.pop(i, None)
            w = square.ways.get(i)
            # a contour as Square.contours() has one: an elevation, and not
            # water's outline or a lake's fill line
            if w is not None and w.ele is not None and i not in water and 'danu:fill' not in w.tags:
                ln = _line(square, w)
                if ln is not None:
                    s.lines[i] = ln
        s._arrays = None
        # the bodies again only when water was edited, and the spot heights
        # only when one was, or a way now passes through or off one - each is
        # the whole square read, 15 ms of N20E087's spot heights
        if way_ids & (water | {i for b in bodies_before for i in b.ways}):
            s.bodies = _bodies(square)
            s.held = {k: v for k, v in s.held.items() if k in s.bodies or k in s.coasts}
        # and the coast's rings, when a coastline was edited: reversed, joined
        # or redrawn, each ring it is in is asked whole again
        coast_edited = bool(way_ids & (coast_ways(square) | {i for b in coasts_before for i in b.ways}))
        if coast_edited:
            s.coasts, ringed = _coasts(square)
            s.held = {k: v for k, v in s.held.items() if k in s.bodies or k in s.coasts}
            s.coast_ids = coast_ways(square)
            # every contour's votes again, a coastline having moved under
            # them: 0.6 s on huz's S54E079, its coast edited a way at a time
            s.sides = _Sides(square, ringed)
            s.side_votes = ({i: s.sides.votes(ln) for i, ln in s.lines.items() if i not in s.coast_ids}
                            if not s.sides.empty else {})
        elif not s.sides.empty:
            for i in way_ids:
                s.side_votes.pop(i, None)
                if i in s.lines and i not in s.coast_ids:
                    s.side_votes[i] = s.sides.votes(s.lines[i])
        touched = {r for i in way_ids for r in getattr(square.ways.get(i), 'refs', ())}
        touched |= {int(r) for ln in before.values() for r in ln.refs}
        if spot_ids or touched & (set(s.spots) | {i for i, n in ((r, square.nodes.get(r)) for r in touched)
                                                    if n is not None and 'ele' in n.tags}):
            s.spots = {i: (n.lon, n.lat) for i, (n, _) in spot_heights(square).items()}
        moved = set()
        for i in way_ids:
            old, new = before.get(i), s.lines.get(i)
            moved ^= set(zip(old.X, old.Y, strict=True)) if old is not None else set()
            moved ^= set(zip(new.X, new.Y, strict=True)) if new is not None else set()
        for b in bodies_before + [b for b in s.bodies.values() if b.ways & way_ids]:
            for X, Y in b.rings:
                moved |= set(zip(X, Y, strict=True))
        for i in spot_ids:
            moved |= {p for p in (spots_before.get(i), s.spots.get(i)) if p is not None}
        # and the boxes of the segments edited, as they were and are: a node
        # moved outside a lake's box can still take its segment across it
        spans = _segments_at([*before.values(), *(s.lines[i] for i in way_ids if i in s.lines)], moved)
        found = self._found[square.name]
        for key in [k for k in found if k[0] == 'bare' and k[1] in way_ids and k[1] not in s.lines]:
            del found[key]
        for key in [k for k in found if k[0] == 'lake' and k[1] not in s.bodies]:
            del found[key]
        # the coast's findings again, every ring and way of it: a ring not
        # itself edited is asked only of the lines edited, against what it
        # held, and the open ways are summed from the votes kept - few rings,
        # cheap each, against a whole scan
        for key in [k for k in found if k[0] == 'coast']:
            del found[key]
        found.update(_coast_findings(s, None if coast_edited else way_ids))
        if not moved and not len(spans):
            return
        P = np.array(sorted(moved), float).reshape(-1, 2)
        for key, body in s.bodies.items():
            if body.ways & way_ids or _holds_any(body.box, P) or _overlap(body.box, spans).any():
                # the body edited is asked whole; one only edited near, of the lines edited
                f = s.spanned(body, None if body.ways & way_ids else way_ids)
                found.pop(('lake', key), None)
                if f is not None:
                    found[('lake', key)] = f
        for ln in s.lines.values():
            if ln.id in way_ids or _holds_any(ln.box, P) or _overlap(ln.box, spans).any():
                f = s.bare(ln)
                found.pop(('bare', ln.id), None)
                if f is not None:
                    found[('bare', ln.id)] = f


def _segments_at(lines, moved) -> np.ndarray:
    """The boxes of the lines' segments with an end among the points moved,
    as rows (x0, y0, x1, y1) - what an edit can have taken across a ring
    without a vertex inside its box."""
    out = []
    for ln in lines:
        at = np.array([(x, y) in moved for x, y in zip(ln.X, ln.Y, strict=True)])
        k = np.flatnonzero(at[:-1] | at[1:])
        if len(k):
            ax, ay, bx, by = ln.X[k], ln.Y[k], ln.X[k + 1], ln.Y[k + 1]
            out.append(np.column_stack([np.minimum(ax, bx), np.minimum(ay, by), np.maximum(ax, bx), np.maximum(ay, by)]))
    return np.concatenate(out) if out else np.empty((0, 4))


def _holds_any(box, P) -> bool:
    return bool(((P[:, 0] >= box[0]) & (P[:, 0] <= box[2]) & (P[:, 1] >= box[1]) & (P[:, 1] <= box[3])).any())


