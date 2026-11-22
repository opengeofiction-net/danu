"""The landforms the contours contradict, and those still to be given a
height - #191, three rows of the validation panel.

- **a cliff drawn backwards**: a cliff or an earth bank keeps its low side on
  its right, and the contours beside it say the right is the high side. Rays
  square to it, a pair from the middle of each of its segments, each to the
  first contour it meets within ``RANGE_M``: a pair whose right-hand contour
  is higher is a vote that it is backwards, lower that it is right. More than
  twice as many backwards as right, and at least ``MIN_VOTES``, is backwards;
  R turns it. Of gobras's 345 cliffs, 36 are so.
- **a cliff across contours**: one with no ``ele`` crossing contours - its
  drop is across it, and where a contour runs through it the contours say
  there is none there. 161 of gobras's, 576 crossings between them. One with
  an ``ele`` is a contour, and its crossings are R16's own row.
- **a landform with no height**: a peak, a volcano, a saddle or a sinkhole
  with no ``ele``; a ridge, an arete, a valley, a gully or a gorge with no
  level at any point of it; a dry lake or a plateau with no level. The main
  map has them by the thousand, and the build makes nothing of one until it
  has.

Per square, as the other checks; the contours by way, so an edit puts its
own back. No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core import geometry
from ..core.square import flat_tags, parse_ele
from ..surface import cliff as _cliff
from ..surface import held
from .files import Finding

RANGE_M = 300.0              # a ray's reach to the contour beside a cliff
MIN_VOTES = 2                # pairs saying it is backwards, at the least
_M_LAT = 110540.0


def _k(lat: float) -> float:
    return 111320.0 * math.cos(math.radians(lat))


@dataclass
class _Contour:
    A: np.ndarray            # (n, 2) segment starts, lon/lat
    B: np.ndarray
    ele: float
    box: tuple


def _contour(square, way) -> _Contour | None:
    pts = np.array([(square.nodes[r].lon, square.nodes[r].lat) for r in way.refs if r in square.nodes])
    if len(pts) < 2:
        return None
    return _Contour(pts[:-1], pts[1:], way.ele, (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()))


def _is_contour(way, water) -> bool:
    """A contour as ``Square.contours`` has one."""
    return way.ele is not None and way.id not in water and 'danu:fill' not in way.tags


def _box(pts, pad_deg=(0.0, 0.0)) -> tuple:
    X, Y = pts[:, 0], pts[:, 1]
    return (X.min() - pad_deg[0], Y.min() - pad_deg[1], X.max() + pad_deg[0], Y.max() + pad_deg[1])


def _overlaps(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


class _Square:
    def __init__(self, square):
        self.square = square
        water = square.water_bodies()
        self.contours = {}
        for w in square.ways.values():
            if _is_contour(w, water):
                c = _contour(square, w)
                if c is not None:
                    self.contours[w.id] = c

    def near(self, box, skip=None):
        """The contour segments in a box, as (A, B, levels) arrays."""
        parts = [c for wid, c in self.contours.items() if wid != skip and _overlaps(c.box, box)]
        if not parts:
            return np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0)
        return (np.concatenate([c.A for c in parts]), np.concatenate([c.B for c in parts]),
                np.concatenate([np.full(len(c.A), c.ele) for c in parts]))

    def cliff_box(self, way):
        pts = self.points(way)
        if pts is None:
            return None
        lat = float(pts[:, 1].mean())
        return _box(pts, (RANGE_M / _k(lat), RANGE_M / _M_LAT))

    def points(self, way):
        nodes = self.square.nodes
        pts = np.array([(nodes[r].lon, nodes[r].lat) for r in way.refs if r in nodes])
        return pts if len(pts) >= 2 else None


def _first(A, B, L, lon, lat, dx, dy):
    """The level of the first contour a ray from a point meets within RANGE_M,
    ``(dx, dy)`` a unit vector in metres east and north - or None."""
    if not len(L):
        return None
    k = _k(lat)
    ax, ay = (A[:, 0] - lon) * k, (A[:, 1] - lat) * _M_LAT
    bx, by = (B[:, 0] - lon) * k, (B[:, 1] - lat) * _M_LAT
    ex, ey = bx - ax, by - ay
    den = dx * ey - dy * ex
    with np.errstate(divide='ignore', invalid='ignore'):
        along = (ax * ey - ay * ex) / den
        on = (ax * dy - ay * dx) / den
    hit = (den != 0) & (along > 0) & (along <= RANGE_M) & (on >= 0) & (on <= 1)
    if not hit.any():
        return None
    return float(L[np.flatnonzero(hit)[np.argmin(along[hit])]])


def votes(s: _Square, way) -> tuple[int, int]:
    """(backwards, right): the pairs of rays square to the cliff that say its
    right is the high side, and the low."""
    pts = s.points(way)
    if pts is None:
        return 0, 0
    A, B, L = s.near(s.cliff_box(way), skip=way.id)
    back = right = 0
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:], strict=True):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        k = _k(my)
        dx, dy = (x1 - x0) * k, (y1 - y0) * _M_LAT
        n = math.hypot(dx, dy)
        if n == 0:
            continue
        dx, dy = dx / n, dy / n
        r = _first(A, B, L, mx, my, dy, -dx)          # its right, north up
        left = _first(A, B, L, mx, my, -dy, dx)
        if r is None or left is None or r == left:
            continue
        if r > left:
            back += 1
        else:
            right += 1
    return back, right


def crossings(s: _Square, way) -> int:
    pts = s.points(way)
    if pts is None:
        return 0
    A, B, _L = s.near(_box(pts), skip=way.id)
    if not len(A):
        return 0
    n = 0
    for p, q in zip(pts[:-1], pts[1:], strict=True):
        lo, hi = np.minimum(p, q), np.maximum(p, q)
        near = ((np.minimum(A[:, 0], B[:, 0]) <= hi[0]) & (np.maximum(A[:, 0], B[:, 0]) >= lo[0])
                & (np.minimum(A[:, 1], B[:, 1]) <= hi[1]) & (np.maximum(A[:, 1], B[:, 1]) >= lo[1]))
        if near.any():
            n += int(geometry.crossings(p, q, A[near], B[near]).sum())
    return n


def _what(way) -> str:
    return way.tags['natural'].replace('_', ' ')


def _named(way, what) -> str:
    name = way.tags.get('name')
    return f'{what} "{name}", way {way.id}' if name else f'{what}, way {way.id}'


def _finding(square, kind, text, why, pts, way=None, node=None, relation=None) -> Finding:
    mid = pts[len(pts) // 2]
    return Finding(square.name, kind, text, why, float(mid[0]), float(mid[1]), _box(np.asarray(pts)),
                   way=way, node=node, relation=relation)


def judge_way(s: _Square, way) -> dict:
    """The findings of one way, keyed (kind, way id)."""
    out = {}
    square = s.square
    pts = s.points(way)
    if pts is None:
        return out
    if _cliff.is_cliff(way):
        what = _what(way)
        back, right = votes(s, way)
        if back >= MIN_VOTES and back > 2 * right:
            out[('cliff_back', way.id)] = _finding(
                square, 'cliff_back', f'{_named(way, what)} - its right the high side',
                f'the contours beside the {what} are higher on its right, {back} places to {right}: '
                'its low side is on its right, so R reverses it', pts, way=way.id)
        if way.ele is None:
            n = crossings(s, way)
            if n:
                out[('cliff_cross', way.id)] = _finding(
                    square, 'cliff_cross', f'{_named(way, what)} - crosses {n} contour{"s" * (n != 1)}',
                    f'the {what} crosses {n} contour{"s" * (n != 1)}: its drop is across it, and the contours '
                    'run through it - mend them or it', pts, way=way.id)
    elif held.landform(way) is not None and not way.closed:
        nodes = square.nodes
        if not any(parse_ele(nodes[r].tags.get('ele')) is not None for r in way.refs if r in nodes):
            what = _what(way)
            out[('no_height', way.id)] = _finding(
                square, 'no_height', f'{_named(way, what)} - no levels',
                f'the {what} has no level at any point: choose it, and G grades it from the contours it '
                'crosses', pts, way=way.id)
    elif way.closed and flat_tags(way.tags) and way.ele is None and not _in_flat_relation(square, way):
        what = way.tags.get('natural', 'flat area').replace('_', ' ')
        out[('no_height', way.id)] = _finding(
            square, 'no_height', f'{_named(way, what)} - no level',
            f'the {what} has no level: set one, or F flattens it', pts, way=way.id)
    return out


def _in_flat_relation(square, way) -> bool:
    return any(flat_tags(rel.tags) and any(m.type == 'way' and m.ref == way.id for m in rel.members)
               for rel in square.relations.values())


def judge_relation(s: _Square, rel) -> dict:
    square = s.square
    if not flat_tags(rel.tags) or rel.tags.get('natural') not in ('dry_lake', 'plateau') \
            or parse_ele(rel.tags.get('ele')) is not None:
        return {}
    nodes = square.nodes
    pts = [(nodes[r].lon, nodes[r].lat) for m in rel.members if m.type == 'way' and m.ref in square.ways
           for r in square.ways[m.ref].refs if r in nodes]
    if not pts:
        return {}
    what = rel.tags['natural'].replace('_', ' ')
    name = rel.tags.get('name')
    text = f'{what} "{name}", relation {rel.id}' if name else f'{what}, relation {rel.id}'
    return {('no_height', 'rel', rel.id): _finding(
        square, 'no_height', f'{text} - no level', f'the {what} has no level: set one, or F flattens it',
        pts, relation=rel.id)}


def judge_node(square, nid) -> dict:
    node = square.nodes.get(nid)
    if node is None or node.tags.get('natural') not in held.SPOT_KINDS or parse_ele(node.tags.get('ele')) is not None:
        return {}
    what = node.tags['natural']
    name = node.tags.get('name')
    text = f'{what} "{name}", node {nid}' if name else f'{what}, node {nid}'
    return {('no_height', 'node', nid): Finding(
        square.name, 'no_height', f'{text} - no height', f'the {what} has no height: choose it, and give it one',
        node.lon, node.lat, (node.lon, node.lat, node.lon, node.lat), node=nid)}


def _all(s: _Square) -> dict:
    square = s.square
    out = {}
    for way in square.ways.values():
        if way.tags.get('natural') in held.LANDFORMS or _cliff.is_cliff(way) or flat_tags(way.tags):
            out.update(judge_way(s, way))
    for rel in square.relations.values():
        out.update(judge_relation(s, rel))
    for nid, node in square.nodes.items():
        if node.tags.get('natural') in held.SPOT_KINDS:
            out.update(judge_node(square, nid))
    return out


def find_in(square) -> list[Finding]:
    return list(_all(_Square(square)).values())


def find(working_set) -> list[Finding]:
    return [f for sq in working_set.squares.values() for f in find_in(sq)]


class Index:
    """The findings of a working set, kept as edited: a landform edited is
    judged again, and a cliff an edited contour runs near, as it was and is."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._squares = {sq.name: _Square(sq) for sq in working_set.squares.values()}
        self._found = {name: _all(s) for name, s in self._squares.items()}

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for found in self._found.values() for f in found.values() if kind is None or f.kind == kind]
        return sorted(out, key=lambda f: (f.kind, -_count(f), str(f.square), f.text))

    def update(self, square, way_ids=(), spot_ids=()) -> None:
        s = self._squares.get(square.name)
        if s is None or s.square is not square:
            self._squares[square.name] = s = _Square(square)
            self._found[square.name] = _all(s)
            return
        found = self._found[square.name]
        for nid in spot_ids or ():
            found.pop(('no_height', 'node', nid), None)
            found.update(judge_node(square, nid))
        way_ids = set(way_ids or ())
        if not way_ids:
            return
        water = square.water_bodies()
        boxes = []                                    # the contours edited, as they were and are
        for wid in way_ids:
            was = s.contours.pop(wid, None)
            if was is not None:
                boxes.append(was.box)
            w = square.ways.get(wid)
            if w is not None and _is_contour(w, water):
                c = _contour(square, w)
                if c is not None:
                    s.contours[wid] = c
                    boxes.append(c.box)
        again = set(way_ids)
        for wid, w in square.ways.items():
            if _cliff.is_cliff(w) and wid not in again:
                box = s.cliff_box(w)
                if box is not None and any(_overlaps(box, b) for b in boxes):
                    again.add(wid)
        for wid in again:
            for kind in ('cliff_back', 'cliff_cross', 'no_height'):
                found.pop((kind, wid), None)
            w = square.ways.get(wid)
            if w is not None:
                found.update(judge_way(s, w))
            # a vertex given a level, or taken one: nodes on it are judged too
            for nid in (w.refs if w is not None else ()):
                if ('no_height', 'node', nid) in found or (
                        square.nodes.get(nid) is not None
                        and square.nodes[nid].tags.get('natural') in held.SPOT_KINDS):
                    found.pop(('no_height', 'node', nid), None)
                    found.update(judge_node(square, nid))
        # a flat relation, its rings edited or its tags
        for rel in square.relations.values():
            if any(m.type == 'way' and m.ref in way_ids for m in rel.members):
                found.pop(('no_height', 'rel', rel.id), None)
                found.update(judge_relation(s, rel))
        for key in [k for k in found if k[0] == 'no_height' and k[1] == 'rel' and k[2] not in square.relations]:
            del found[key]


def _count(f: Finding) -> int:
    """A cliff's crossings, to list the worst first."""
    if f.kind != 'cliff_cross':
        return 0
    try:
        return int(f.text.rsplit('crosses ', 1)[1].split()[0])
    except (IndexError, ValueError):
        return 0
