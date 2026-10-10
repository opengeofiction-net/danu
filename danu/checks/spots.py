"""A spot height which contradicts the contours around it - R38, as a check.

R38: one which does not lie between the elevations of the rings enclosing
it. A spot height is the only thing which says how high a hill goes (R37), and
it is a constraint the surface meets: one below the ring it stands inside digs
a pit in a summit, one far above it raises a spike where the contours stop.
G9 brought the main map's into the squares, and near Gobras, of the 173 inside
a closed contour, 92 contradict it: 82 below a ring they stand inside - 51 of
them by 5 m or less, a 349 m peak inside the 350 m - and 10 past the next
contour up, Colonie Hill 698 m inside the 250 m ring and past the 275 m.

**The ring that matters is the innermost** closed contour round the spot
height, and the one round that says which way the ground goes: inside a 125 m
ring that is inside a 100 m, it is a hill, and the spot height lies between
125 m and the square's next notch up, 150 m - above that, the 150 m contour
is missing round it. Inside a ring that is inside a higher one it is a hollow,
the same turned over. One ring alone is read as a hill, which most are.

A spot height is a node with an elevation that no way passes through: a
graded river's vertices carry levels too, and G7c says where those
contradict a contour.

**One in no ring** stands on ground between the contours nearest it, and is
judged against those: the first contour met in each of eight directions,
within 3 km. More than a step of the ladder above the highest of them is a
summit with no ring drawn round it, or a height that is wrong; as far below
the lowest, the same for a hollow. Fewer than six directions meeting one is
too little to judge by. The main map's heights include ones placed by
mappers who never saw the DEM: Suprrina Hill, 69 m, 100 m from the 5 m
contour; Apson Hill, 192 m, among contours of 5 to 30 m for 2.7 km. On the
gobras squares, 12 of the 29 so judged.

No Qt and no GDAL. Per square, rings by their boxes, then inside or out by
crossings of a ray.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from ..core.ladder import infer
from ..core.square import parse_ele


@dataclass(frozen=True)
class Contradiction:
    square: object              # SquareName
    node: int
    ele: float
    ring: int                   # the innermost ring round it, a way id
    level: float                # its level
    bound: float                # the level the spot height is past
    kind: str                   # 'below' or 'above' - of what the ground allows
    hollow: bool
    lon: float
    lat: float
    name: str | None = None
    lo: float | None = None     # in no ring: the lowest and highest contours nearest it
    hi: float | None = None

    @property
    def open(self) -> bool:
        return self.ring is None

    def describe(self) -> str:
        what = f'{self.name} {self.ele:g} m' if self.name else f'{self.ele:g} m spot height'
        if self.open:
            return f'{what} - in no ring, the contours nearest it {self.lo:g} to {self.hi:g} m'
        if self.kind == 'below':
            where = 'above' if self.hollow else 'below'
            return f'{what} - {where} the {self.level:g} m ring round it'
        return f'{what} - past the {self.bound:g} m, which is not drawn round it'

    def explain(self) -> str:
        if self.open:
            side, by = (('above the highest', self.ele - self.hi) if self.kind == 'above'
                        else ('below the lowest', self.lo - self.ele))
            return (f'in {self.square}, {self.describe()}: standing in no closed contour it lies between '
                    f'the contours nearest it, and it is {by:g} m {side} - a ring would have to be drawn '
                    'round it, or the height is wrong: set it, move it, or delete it')
        ground = 'hollow' if self.hollow else 'hill'
        if self.kind == 'below':
            side = 'above' if self.hollow else 'below'
            return (f'in {self.square}, {self.describe()} (way {self.ring}): on a {ground} it is '
                    f'{abs(self.ele - self.level):g} m {side} the contour it stands inside - set its '
                    'height, or move it or the ring')
        return (f'in {self.square}, {self.describe()}: on a {ground} inside the {self.level:g} m '
                f'(way {self.ring}), {abs(self.ele - self.bound):g} m past the next contour - draw '
                'it, or set the height')


def _ring(square, w):
    """A closed contour as (way id, level, lon, lat arrays, box, area), or
    None for one that is not closed."""
    refs = w.refs
    if len(refs) < 4 or refs[0] != refs[-1] or any(r not in square.nodes for r in refs):
        return None
    X = np.array([square.nodes[r].lon for r in refs])
    Y = np.array([square.nodes[r].lat for r in refs])
    area = abs(float(np.dot(X[:-1], Y[1:]) - np.dot(X[1:], Y[:-1]))) / 2
    return (w.id, w.ele, X, Y, (X.min(), Y.min(), X.max(), Y.max()), area)


def _rings(square):
    """Every closed contour as (way id, level, lon, lat arrays, box, area)."""
    return [r for r in (_ring(square, w) for w in square.contours()) if r is not None]


def _inside(x, y, X, Y) -> bool:
    j = np.arange(len(X) - 1)
    a, b = (X[j], Y[j]), (X[j + 1], Y[j + 1])
    crosses = (a[1] > y) != (b[1] > y)
    with np.errstate(divide='ignore', invalid='ignore'):
        at = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
    return bool((crosses & (x < at)).sum() % 2)


def spot_heights(square) -> dict:
    """The square's spot heights: node id -> (node, elevation)."""
    vertices = {r for w in square.ways.values() for r in w.refs}
    out = {}
    for i, n in square.nodes.items():
        if i in vertices:
            continue
        ele = parse_ele(n.tags.get('ele'))
        if ele is not None:
            out[i] = (n, ele)
    return out


RANGE_M = 3000.0                 # how far a ray looks for the contour nearest a spot height
RAYS = 8
LEAST_RAYS = 6                   # meeting fewer contours than this, it is not judged


class _Segments:
    """A square's contours as segments, a way at a time so an edit replaces
    its own, and as arrays for the rays."""

    def __init__(self, square):
        self.by_way = {}
        for w in square.contours():
            self.put(square, w)
        self._arrays = None

    def put(self, square, way) -> None:
        pts = np.array([(square.nodes[r].lon, square.nodes[r].lat) for r in way.refs if r in square.nodes])
        if len(pts) >= 2:
            self.by_way[way.id] = (pts[:-1], pts[1:], way.ele,
                                   (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()))
        self._arrays = None

    def drop(self, wid) -> None:
        if self.by_way.pop(wid, None) is not None:
            self._arrays = None

    def arrays(self):
        if self._arrays is None:
            parts = list(self.by_way.values())
            if parts:
                self._arrays = (np.concatenate([a for a, _, _, _ in parts]),
                                np.concatenate([b for _, b, _, _ in parts]),
                                np.concatenate([np.full(len(a), e) for a, _, e, _ in parts]))
            else:
                self._arrays = (np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0))
        return self._arrays


def nearest_levels(segments: _Segments, lon: float, lat: float) -> list[float]:
    """The level of the first contour each of RAYS rays from a point meets,
    within RANGE_M - those it meets."""
    A, B, L = segments.arrays()
    if not len(L):
        return []
    k = 111320 * math.cos(math.radians(lat))
    ax, ay = (A[:, 0] - lon) * k, (A[:, 1] - lat) * 110540
    bx, by = (B[:, 0] - lon) * k, (B[:, 1] - lat) * 110540
    # the segments within reach: the point's distance to each, not to its ends,
    # so a long segment passing by with both ends far off is kept
    ex, ey = bx - ax, by - ay
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.clip(np.nan_to_num(-(ax * ex + ay * ey) / (ex * ex + ey * ey)), 0.0, 1.0)
    near = np.hypot(ax + t * ex, ay + t * ey) <= RANGE_M
    ax, ay, bx, by, lv = ax[near], ay[near], bx[near], by[near], L[near]
    ex, ey = bx - ax, by - ay
    out = []
    for t in np.linspace(0, 2 * math.pi, RAYS, endpoint=False):
        dx, dy = math.cos(t), math.sin(t)
        den = dx * ey - dy * ex
        with np.errstate(divide='ignore', invalid='ignore'):
            along = (ax * ey - ay * ex) / den            # how far along the ray
            on = (ax * dy - ay * dx) / den               # where on the segment
        hit = (den != 0) & (along > 0) & (along <= RANGE_M) & (on >= 0) & (on <= 1)
        if hit.any():
            out.append(float(lv[np.flatnonzero(hit)[np.argmin(along[hit])]]))
    return out


def judge_open(square, node, ele, segments, ladder) -> Contradiction | None:
    """One spot height in no ring, against the contours nearest it."""
    step = ladder.interval if ladder is not None else None
    if not step:
        return None
    levels = nearest_levels(segments, node.lon, node.lat)
    if len(levels) < LEAST_RAYS:
        return None
    lo, hi = min(levels), max(levels)
    name = node.tags.get('name')
    if ele > hi + step + 1e-9:
        return Contradiction(square.name, node.id, ele, None, hi, hi + step, 'above', False,
                             node.lon, node.lat, name, lo, hi)
    if ele < lo - step - 1e-9:
        return Contradiction(square.name, node.id, ele, None, lo, lo - step, 'below', True,
                             node.lon, node.lat, name, lo, hi)
    return None


def judge(square, node, ele, rings, ladder, segments=None) -> Contradiction | None:
    """One spot height against the rings round it - or, in none, against the
    contours nearest it."""
    x, y = node.lon, node.lat
    round_it = [(area, wid, level) for wid, level, X, Y, (x0, y0, x1, y1), area in rings
                if x0 <= x <= x1 and y0 <= y <= y1 and _inside(x, y, X, Y)]
    if not round_it:
        return judge_open(square, node, ele, segments, ladder) if segments is not None else None
    round_it.sort()
    _, wid, level = round_it[0]
    outer = next((lv for _, _, lv in round_it[1:] if lv != level), None)
    hollow = outer is not None and outer > level
    name = node.tags.get('name')
    if (not hollow and ele < level - 1e-9) or (hollow and ele > level + 1e-9):
        return Contradiction(square.name, node.id, ele, wid, level, level, 'below', hollow, x, y, name)
    # the next contour: a rung of the regular ladder, not the next value the
    # square happens to hold - an off-ladder 135 m is not the contour after
    # the 125 m on a 25 m ladder
    if ladder is None:
        nxt = None
    elif ladder.interval:
        # the rung beyond the ring's level, on the ladder's phase - an
        # off-ladder 135 m ring on a 25 m ladder is followed by 150, not 160
        k = (level - (ladder.phase or 0.0)) / ladder.interval
        step = math.ceil(k - 1 - 1e-9) if hollow else math.floor(k + 1 + 1e-9)
        nxt = step * ladder.interval + (ladder.phase or 0.0)
    else:
        nxt = ladder.below(level) if hollow else ladder.above(level)
    if nxt is not None and ((not hollow and ele > nxt + 1e-9) or (hollow and ele < nxt - 1e-9)):
        return Contradiction(square.name, node.id, ele, wid, level, nxt, 'above', hollow, x, y, name)
    return None


def find_in(square, only: set | None = None, rings=None, segments=None, heights=None) -> list[Contradiction]:
    rings = _rings(square) if rings is None else rings
    segments = _Segments(square) if segments is None else segments
    if not segments.by_way:
        return []
    ladder = infer(square)
    out = []
    for i, (n, ele) in (spot_heights(square) if heights is None else heights).items():
        if only is not None and i not in only:
            continue
        c = judge(square, n, ele, rings, ladder, segments)
        if c is not None:
            out.append(c)
    return sorted(out, key=lambda c: (str(c.square), -abs(c.ele - c.bound), c.node))


def find(working_set) -> list[Contradiction]:
    return [c for sq in working_set.squares.values() for c in find_in(sq)]


class Index:
    """The contradictions of a working set, kept as it is edited. A spot
    height an edit names is judged again; so is every one inside the box of a
    ring an edit touched, as it was and as it is."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._rings: dict = {}                 # square name -> rings
        self._segments: dict = {}              # square name -> its contours as segments
        self._by_square: dict = defaultdict(dict)
        for sq in working_set.squares.values():
            self._rings[sq.name] = _rings(sq)
            self._segments[sq.name] = _Segments(sq)
            for c in find_in(sq, rings=self._rings[sq.name], segments=self._segments[sq.name]):
                self._by_square[sq.name][c.node] = c

    def contradictions(self) -> list[Contradiction]:
        out = [c for found in self._by_square.values() for c in found.values()]
        return sorted(out, key=lambda c: (str(c.square), -abs(c.ele - c.bound), c.node))

    def update(self, square, way_ids, spot_ids=()) -> None:
        way_ids = set(way_ids)
        old_rings = {r[0]: r for r in self._rings.get(square.name, [])}
        segs = self._segments.get(square.name)
        if segs is None:
            segs = self._segments[square.name] = _Segments(square)
        # the edited ways' rings and segments replaced, and nothing else read
        # again: rebuilt whole, a square's rings were 48 ms of every edit
        contours = {w.id: w for w in square.contours()} if way_ids else {}
        boxes, moved = [], set()
        rings = dict(old_rings)
        for wid in way_ids:
            was = rings.pop(wid, None)
            if was is not None:
                boxes.append(was[4])
            old = segs.by_way.get(wid)
            segs.drop(wid)
            now = None
            if wid in contours:
                r = _ring(square, contours[wid])
                if r is not None:
                    rings[wid] = r
                    boxes.append(r[4])
                segs.put(square, contours[wid])
                now = segs.by_way.get(wid)
            # what moved: a spot height in no ring is judged by contours up to
            # RANGE_M off, so it is asked again when a point within that of it
            # moved - not the edited contour's whole box, which for a long one
            # is most of the square
            pts = lambda seg: set(map(tuple, np.vstack([seg[0], seg[1][-1:]]))) if seg else set()  # noqa: E731
            # each way's own difference, gathered by union: two edited contours
            # sharing the node that moved would cancel each other's out
            moved |= pts(old) ^ pts(now)
        self._rings[square.name] = rings = list(rings.values())
        heights = spot_heights(square)
        again = set(spot_ids)
        if boxes or moved:
            P = np.array(sorted(moved), float).reshape(-1, 2)
            for i, (n, _) in heights.items():
                if any(x0 <= n.lon <= x1 and y0 <= n.lat <= y1 for x0, y0, x1, y1 in boxes):
                    again.add(i)
                elif len(P):
                    k = 111320 * math.cos(math.radians(n.lat))
                    if (np.hypot((P[:, 0] - n.lon) * k, (P[:, 1] - n.lat) * 110540) <= RANGE_M).any():
                        again.add(i)
        held = self._by_square[square.name]
        for i in again:
            held.pop(i, None)
        for c in find_in(square, only=again, rings=rings, segments=segs, heights=heights):
            held[c.node] = c
