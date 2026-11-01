"""What a square's file says, with no surface - H1a, three rows of the
validation table:

- **ways over 2,000 nodes, and over 10,000** (R30). The OSM API refuses the
  first and GDAL drops the second silently - ten contours went missing from
  `S37E147_Madison_City` that way. Save splits them; until then they are listed.
- **an `ele` that is not a number** (R31). The build drops it and says so only
  in its log; `gdal_rasterize` would have made it 0, a sea level line across
  the ground. A lake's level in feet from the main map is one: Kettle Lake,
  `ele=1,853 Ft`.
- **a value off the ladder, used once or twice** - 113 and 135 once each in
  N20E086, between 110/115 and 125/150, which is what a mistyped 125 looks
  like. A row a contour, to choose and fix; the elevation panel's advice line
  that said it before is gone.

Kept as edited, a way or a node at a time: asked of a whole square on every
edit, roantra's N44E029 with its water imported was 140 ms of each. No Qt.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..core import ladder as L
from ..core.square import parse_ele

API_LIMIT = 2000                 # the OSM API refuses a way longer
GDAL_LIMIT = 10000               # GDAL's OSM driver drops one longer, saying nothing


@dataclass(frozen=True)
class Finding:
    square: object               # SquareName
    kind: str                    # 'long', 'ele', 'ladder'
    text: str
    why: str
    lon: float
    lat: float
    box: tuple                   # west, south, east, north - what choosing it shows
    way: int | None = None
    node: int | None = None
    relation: int | None = None

    def describe(self) -> str:
        return self.text

    def explain(self) -> str:
        return self.why


def _what(way) -> str:
    if way.ele is not None and set(way.tags) <= {'ele', 'contour'}:
        return f'{L.format_ele(way.ele)} m contour, way {way.id}'
    kind = way.tags.get('waterway') or way.tags.get('natural') or 'way'
    name = way.tags.get('name')
    return f'{kind} "{name}", way {way.id}' if name else f'{kind}, way {way.id}'


def _box(square, refs):
    pts = [square.nodes[r] for r in refs if r in square.nodes]
    if not pts:
        return None
    xs, ys = [p.lon for p in pts], [p.lat for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _long(square, w) -> Finding | None:
    n = len(w.refs)
    if n <= API_LIMIT:
        return None
    box = _box(square, w.refs)
    if box is None:
        return None
    mid = square.nodes.get(w.refs[n // 2])
    if n > GDAL_LIMIT:
        why = (f'{n:,} nodes: GDAL drops a way over {GDAL_LIMIT:,} without a word, and the build '
               'would refuse the square - save splits it')
    else:
        why = f'{n:,} nodes: the OSM API refuses a way over {API_LIMIT:,} - save splits it'
    return Finding(square.name, 'long', f'{_what(w)} - {n:,} nodes', why,
                   mid.lon if mid else box[0], mid.lat if mid else box[1], box, way=w.id)


def _bad_way(square, w) -> Finding | None:
    v = w.tags.get('ele')
    if v is None or parse_ele(v) is not None:
        return None
    box = _box(square, w.refs)
    if box is None:
        return None
    mid = square.nodes.get(w.refs[len(w.refs) // 2])
    return Finding(square.name, 'ele', f'{_what(w)} - ele "{v}"',
                   f'"{v}" is not a height in metres: the build drops it rather than read it as 0 - '
                   'set a number, or take the tag off', mid.lon if mid else box[0],
                   mid.lat if mid else box[1], box, way=w.id)


def _bad_node(i, n, square_name) -> Finding | None:
    v = n.tags.get('ele') if n.tags else None
    if v is None or parse_ele(v) is not None:
        return None
    name = n.tags.get('name')
    what = f'{n.tags.get("natural", "node")} "{name}"' if name else f'{n.tags.get("natural", "node")} {i}'
    return Finding(square_name, 'ele', f'{what} - ele "{v}"',
                   f'"{v}" is not a height in metres: the build drops it - set a number',
                   n.lon, n.lat, (n.lon, n.lat, n.lon, n.lat), node=i)


def _ladder_rows(square, eles: dict) -> list[Finding]:
    """A row a contour at a value off the square's ladder used once or
    twice, with the values either side - from the contours' levels,
    ``eles``, way id to level."""
    counts = Counter(eles.values())
    lad = L.infer_from(counts, square.name.name)
    if lad is None:
        return []
    found = {a.value: a for a in L.off_ladder_from(counts, lad)}
    out = []
    for wid, ele in eles.items():
        a = found.get(ele)
        if a is None:
            continue
        w = square.ways[wid]
        box = _box(square, w.refs)
        if box is None:
            continue
        mid = square.nodes.get(w.refs[len(w.refs) // 2])
        out.append(Finding(square.name, 'ladder', f'{_what(w)} - {a.describe()}',
                           f'{a.describe()}, off the {L.format_ele(lad.interval) + " m " if lad.interval else ""}ladder: a mistyped '
                           'value looks like this - set the right one, or leave it if it is meant',
                           mid.lon if mid else box[0], mid.lat if mid else box[1], box, way=w.id))
    return out


def long_ways(square) -> list[Finding]:
    return [f for w in square.ways.values() if (f := _long(square, w)) is not None]


def bad_ele(square) -> list[Finding]:
    out = [f for w in square.ways.values() if (f := _bad_way(square, w)) is not None]
    return out + [f for i, n in square.nodes.items() if (f := _bad_node(i, n, square.name)) is not None]


def off_ladder(square) -> list[Finding]:
    return _ladder_rows(square, {w.id: w.ele for w in square.contours()})


KINDS = {'long': long_ways, 'ele': bad_ele, 'ladder': off_ladder}


def find_in(square) -> list[Finding]:
    return [f for fn in KINDS.values() for f in fn(square)]


def find(working_set) -> list[Finding]:
    return [f for sq in working_set.squares.values() for f in find_in(sq)]


class _Held:
    """One square's findings, kept as edited: a way's rows, a node's row,
    and the ladder's rows, which are the contours' levels counted again."""

    def __init__(self, square):
        self.square = square
        self.ways = {}
        for w in square.ways.values():
            rows = [f for f in (_long(square, w), _bad_way(square, w)) if f is not None]
            if rows:
                self.ways[w.id] = rows
        self.nodes = {i: f for i, n in square.nodes.items() if (f := _bad_node(i, n, square.name)) is not None}
        self.ladder = off_ladder(square)

    def update(self, way_ids, spot_ids) -> None:
        square = self.square
        asked = set(spot_ids)
        for wid in way_ids:
            self.ways.pop(wid, None)
            w = square.ways.get(wid)
            if w is None:
                continue
            rows = [f for f in (_long(square, w), _bad_way(square, w)) if f is not None]
            if rows:
                self.ways[wid] = rows
            asked.update(w.refs)
        for i in [i for i in self.nodes if i not in square.nodes]:
            del self.nodes[i]
        for i in asked:
            self.nodes.pop(i, None)
            n = square.nodes.get(i)
            if n is not None and (f := _bad_node(i, n, square.name)) is not None:
                self.nodes[i] = f
        # the levels counted again whole - 2 ms - since what is a contour
        # turns on the water round it as well as on the way
        self.ladder = off_ladder(square)

    def findings(self) -> list[Finding]:
        return ([f for rows in self.ways.values() for f in rows if f.kind == 'long']
                + [f for rows in self.ways.values() for f in rows if f.kind == 'ele']
                + list(self.nodes.values()) + self.ladder)


class Index:
    """The findings of a working set, kept as edited. A way an edit names is
    asked again, and the nodes of it and the spot heights it names; the
    ladder's rows are worked out again from the contours' levels. Asked whole
    on every edit, roantra's N44E029 with its water was 140 ms of each."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._by_square = {sq.name: _Held(sq) for sq in working_set.squares.values()}

    def update(self, square, way_ids=(), spot_ids=()) -> None:
        held = self._by_square.get(square.name)
        if held is None or held.square is not square:
            self._by_square[square.name] = _Held(square)
            return
        held.update(set(way_ids or ()), set(spot_ids or ()))

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for held in self._by_square.values() for f in held.findings() if kind is None or f.kind == kind]
        return sorted(out, key=lambda f: (f.kind, str(f.square), f.text))
