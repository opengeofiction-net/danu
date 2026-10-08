"""A spot height which contradicts the contours around it - R38, as a check.

R38: one which does not lie between the elevations of the rings enclosing
it. A spot height is the only thing which says how high a hill goes (R37), and
it is a constraint the surface meets: one below the ring it stands inside digs
a pit in a summit, one far above it raises a spike where the contours stop.
G9 brought the main map's into the squares, and near Gobras, of 173 inside a
closed contour, 82 agreed: 82 were below a ring they stand inside - 51 of them
by 5 m or less, a 349 m peak inside the 350 m - and 9 more than two steps above
theirs, Colonie Hill 698 m inside a 250 m ring.

**The ring that matters is the innermost** closed contour round the spot
height, and the one round that says which way the ground goes: inside a 125 m
ring that is inside a 100 m, it is a hill, and the spot height lies between
125 m and the square's next notch up, 150 m - above that, the 150 m contour
is missing round it. Inside a ring that is inside a higher one it is a hollow,
the same turned over. One ring alone is read as a hill, which most are.

A spot height is a node with an elevation that no way passes through: a
graded river's vertices carry levels too, and G7c says where those
contradict a contour. One in no ring is not judged here - R39's question.

No Qt and no GDAL. Per square, rings by their boxes, then inside or out by
crossings of a ray.
"""

from __future__ import annotations

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

    def describe(self) -> str:
        what = f'{self.name} {self.ele:g} m' if self.name else f'{self.ele:g} m spot height'
        if self.kind == 'below':
            where = 'above' if self.hollow else 'below'
            return f'{what} - {where} the {self.level:g} m ring round it'
        return f'{what} - past the {self.bound:g} m, which is not drawn round it'

    def explain(self) -> str:
        ground = 'hollow' if self.hollow else 'hill'
        if self.kind == 'below':
            side = 'above' if self.hollow else 'below'
            return (f'in {self.square}, {self.describe()} (way {self.ring}): on a {ground} it is '
                    f'{abs(self.ele - self.level):g} m {side} the contour it stands inside - set its '
                    'height, or move it or the ring')
        return (f'in {self.square}, {self.describe()}: on a {ground} inside the {self.level:g} m '
                f'(way {self.ring}), {abs(self.ele - self.bound):g} m past the next contour - draw '
                'it, or set the height')


def _rings(square):
    """Every closed contour as (way id, level, lon, lat arrays, box, area)."""
    out = []
    for w in square.contours():
        refs = w.refs
        if len(refs) < 4 or refs[0] != refs[-1] or any(r not in square.nodes for r in refs):
            continue
        X = np.array([square.nodes[r].lon for r in refs])
        Y = np.array([square.nodes[r].lat for r in refs])
        area = abs(float(np.dot(X[:-1], Y[1:]) - np.dot(X[1:], Y[:-1]))) / 2
        out.append((w.id, w.ele, X, Y, (X.min(), Y.min(), X.max(), Y.max()), area))
    return out


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


def judge(square, node, ele, rings, ladder) -> Contradiction | None:
    """One spot height against the rings round it."""
    x, y = node.lon, node.lat
    round_it = [(area, wid, level) for wid, level, X, Y, (x0, y0, x1, y1), area in rings
                if x0 <= x <= x1 and y0 <= y <= y1 and _inside(x, y, X, Y)]
    if not round_it:
        return None
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
        nxt = level - ladder.interval if hollow else level + ladder.interval
    else:
        nxt = ladder.below(level) if hollow else ladder.above(level)
    if nxt is not None and ((not hollow and ele > nxt + 1e-9) or (hollow and ele < nxt - 1e-9)):
        return Contradiction(square.name, node.id, ele, wid, level, nxt, 'above', hollow, x, y, name)
    return None


def find_in(square, only: set | None = None, rings=None) -> list[Contradiction]:
    rings = _rings(square) if rings is None else rings
    if not rings:
        return []
    ladder = infer(square)
    out = []
    for i, (n, ele) in spot_heights(square).items():
        if only is not None and i not in only:
            continue
        c = judge(square, n, ele, rings, ladder)
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
        self._by_square: dict = defaultdict(dict)
        for sq in working_set.squares.values():
            self._rings[sq.name] = _rings(sq)
            for c in find_in(sq, rings=self._rings[sq.name]):
                self._by_square[sq.name][c.node] = c

    def contradictions(self) -> list[Contradiction]:
        out = [c for found in self._by_square.values() for c in found.values()]
        return sorted(out, key=lambda c: (str(c.square), -abs(c.ele - c.bound), c.node))

    def update(self, square, way_ids, spot_ids=()) -> None:
        boxes = [r[4] for r in self._rings.get(square.name, []) if r[0] in set(way_ids)]
        self._rings[square.name] = rings = _rings(square)
        boxes += [r[4] for r in rings if r[0] in set(way_ids)]
        again = set(spot_ids)
        if boxes:
            for i, (n, _) in spot_heights(square).items():
                if any(x0 <= n.lon <= x1 and y0 <= n.lat <= y1 for x0, y0, x1, y1 in boxes):
                    again.add(i)
        held = self._by_square[square.name]
        for i in again:
            held.pop(i, None)
        for c in find_in(square, only=again, rings=rings):
            held[c.node] = c
