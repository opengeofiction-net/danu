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
  warning: plenty are meant, and a hill's top ring is still a hill.

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

from dataclasses import dataclass

import numpy as np

from ..core import ladder as L
from ..core.rings import relation_rings
from ..core.square import parse_ele
from ..water.overpass import flows
from .files import Finding
from .spots import spot_heights


def inside(px, py, rings) -> np.ndarray:
    """Which of the points lie inside the rings, even-odd over all of them."""
    px, py = np.asarray(px, float), np.asarray(py, float)
    odd = np.zeros(px.shape, bool)
    for X, Y in rings:
        for j in range(0, len(X) - 1, 256):          # a chunk of edges at a time
            ax, ay = X[j:j + 257][:-1, None], Y[j:j + 257][:-1, None]
            bx, by = X[j + 1:j + 257][:, None], Y[j + 1:j + 257][:, None]
            crosses = (ay > py) != (by > py)
            with np.errstate(divide='ignore', invalid='ignore'):
                at = ax + (py - ay) * (bx - ax) / (by - ay)
            odd ^= (np.count_nonzero(crosses & (px < at), axis=0) % 2).astype(bool)
    return odd


def crosses(X, Y, rings, box) -> bool:
    """Whether a line's segments properly cross any edge of the rings - a
    contour across a lake with no vertex in the water. Touching at a vertex
    is not a crossing, so a contour snapped to a shore is not one."""
    ax, ay, bx, by = X[:-1], Y[:-1], X[1:], Y[1:]
    m = ((np.minimum(ax, bx) <= box[2]) & (np.maximum(ax, bx) >= box[0])
         & (np.minimum(ay, by) <= box[3]) & (np.maximum(ay, by) >= box[1]))
    if not m.any():
        return False
    ax, ay, bx, by = ax[m][:, None], ay[m][:, None], bx[m][:, None], by[m][:, None]
    for RX, RY in rings:
        for j in range(0, len(RX) - 1, 256):
            cx, cy = RX[j:j + 257][:-1], RY[j:j + 257][:-1]
            dx, dy = RX[j + 1:j + 257], RY[j + 1:j + 257]
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


def _line(square, way) -> _Line | None:
    refs = [r for r in way.refs if r in square.nodes]
    if len(refs) < 2:
        return None
    X = np.array([square.nodes[r].lon for r in refs])
    Y = np.array([square.nodes[r].lat for r in refs])
    closed = len(way.refs) > 3 and way.refs[0] == way.refs[-1] and len(refs) == len(way.refs)
    return _Line(way.id, way.ele, np.array(refs, dtype=np.int64), X, Y,
                 (X.min(), Y.min(), X.max(), Y.max()), closed)


@dataclass
class _Body:
    key: tuple                   # ('way' | 'relation', id)
    level: float | None
    rings: list                  # [(X, Y)]
    on: np.ndarray               # the node ids of its outline
    ways: set                    # the ways of its outline - what an edit names
    box: tuple
    what: str


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
    return _Body(key, parse_ele(tags.get('ele')), rings, np.array(on, dtype=np.int64), ways,
                 (xs.min(), ys.min(), xs.max(), ys.max()), what)


class _Square:
    """One square's contours by their boxes, its bodies and its spot heights."""

    def __init__(self, square):
        self.square = square
        self.lines = {}
        for w in square.contours():
            ln = _line(square, w)
            if ln is not None:
                self.lines[w.id] = ln
        self.bodies = _bodies(square)
        self.spots = {i: (n.lon, n.lat) for i, (n, _) in spot_heights(square).items()}
        self._arrays = None

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
    def spanned(self, body) -> Finding | None:
        levels = set()
        x0, y0, x1, y1 = body.box
        for ln in self.lines_near(body.box):
            if body.level is not None and abs(ln.ele - body.level) < 1e-6:
                continue
            m = (ln.X >= x0) & (ln.X <= x1) & (ln.Y >= y0) & (ln.Y <= y1)
            if m.any():
                m[m] = ~np.isin(ln.refs[m], body.on)
            if (m.any() and inside(ln.X[m], ln.Y[m], body.rings).any()) or crosses(ln.X, ln.Y, body.rings, body.box):
                levels.add(ln.ele)
        if not levels:
            return None
        lo, hi = min(levels), max(levels)
        span = f'the {L.format_ele(lo)} m' if lo == hi else f'{L.format_ele(lo)} to {L.format_ele(hi)} m'
        n = len(levels)
        level = f', its level {L.format_ele(body.level)} m' if body.level is not None else ''
        text = f'{body.what} - {n} contour level{"s" * (n != 1)} inside it, {span}{level}'
        why = (f'a lake is flat, and contours at {span} inside it say the ground under it is not - '
               'select it and F flattens it at its level, or move the contours out of it')
        X, Y = body.rings[0]
        return Finding(self.square.name, 'lake', text, why, float(X[len(X) // 2]), float(Y[len(Y) // 2]),
                       tuple(map(float, body.box)), way=body.key[1] if body.key[0] == 'way' else None,
                       relation=body.key[1] if body.key[0] == 'relation' else None)

    # -------------------------------------------------------------- R39
    def bare(self, ln) -> Finding | None:
        if not ln.closed:
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
        text = f'the {L.format_ele(ln.ele)} m ring, way {ln.id} - nothing inside it'
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
    return out


def find_in(square) -> list[Finding]:
    return list(_all(_Square(square)).values())


def find(working_set) -> list[Finding]:
    return [f for sq in working_set.squares.values() for f in find_in(sq)]


class Index:
    """The findings of a working set, kept as edited: the rings and bodies
    whose box an edit touched, as it was and as it is, are asked again."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._squares = {sq.name: _Square(sq) for sq in working_set.squares.values()}
        self._found = {name: _all(s) for name, s in self._squares.items()}

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for found in self._found.values() for f in found.values() if kind is None or f.kind == kind]
        return sorted(out, key=lambda f: (f.kind, str(f.square), f.text))

    def update(self, square, way_ids=(), spot_ids=()) -> None:
        s = self._squares.get(square.name)
        if s is None or s.square is not square:
            self._squares[square.name] = s = _Square(square)
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
        found = self._found[square.name]
        for key in [k for k in found if k[0] == 'bare' and k[1] in way_ids and k[1] not in s.lines]:
            del found[key]
        for key in [k for k in found if k[0] == 'lake' and k[1] not in s.bodies]:
            del found[key]
        if not moved:
            return
        P = np.array(sorted(moved), float)
        for key, body in s.bodies.items():
            if body.ways & way_ids or _holds_any(body.box, P):
                f = s.spanned(body)
                found.pop(('lake', key), None)
                if f is not None:
                    found[('lake', key)] = f
        for ln in s.lines.values():
            if ln.id in way_ids or _holds_any(ln.box, P):
                f = s.bare(ln)
                found.pop(('bare', ln.id), None)
                if f is not None:
                    found[('bare', ln.id)] = f


def _holds_any(box, P) -> bool:
    return bool(((P[:, 0] >= box[0]) & (P[:, 0] <= box[2]) & (P[:, 1] >= box[1]) & (P[:, 1] <= box[3])).any())


