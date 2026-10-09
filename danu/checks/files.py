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

Each is cheap enough to ask of a whole square again on any edit to it: 12 ms
for N20E086's 260,000 nodes and 7,000 ways. No Qt.
"""

from __future__ import annotations

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
        return f'the {L.format_ele(way.ele)} m contour, way {way.id}'
    kind = way.tags.get('waterway') or way.tags.get('natural') or 'way'
    name = way.tags.get('name')
    return f'{kind} "{name}", way {way.id}' if name else f'{kind}, way {way.id}'


def _box(square, refs):
    pts = [square.nodes[r] for r in refs if r in square.nodes]
    if not pts:
        return None
    xs, ys = [p.lon for p in pts], [p.lat for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def long_ways(square) -> list[Finding]:
    out = []
    for w in square.ways.values():
        n = len(w.refs)
        if n <= API_LIMIT:
            continue
        box = _box(square, w.refs)
        if box is None:
            continue
        mid = square.nodes.get(w.refs[n // 2])
        if n > GDAL_LIMIT:
            why = (f'{n:,} nodes: GDAL drops a way over {GDAL_LIMIT:,} without a word, and the build '
                   'would refuse the square - save splits it')
        else:
            why = f'{n:,} nodes: the OSM API refuses a way over {API_LIMIT:,} - save splits it'
        out.append(Finding(square.name, 'long', f'{_what(w)} - {n:,} nodes', why,
                           mid.lon if mid else box[0], mid.lat if mid else box[1], box, way=w.id))
    return out


def bad_ele(square) -> list[Finding]:
    out = []
    for w in square.ways.values():
        v = w.tags.get('ele')
        if v is None or parse_ele(v) is not None:
            continue
        box = _box(square, w.refs)
        if box is None:
            continue
        mid = square.nodes.get(w.refs[len(w.refs) // 2])
        out.append(Finding(square.name, 'ele', f'{_what(w)} - ele "{v}"',
                           f'"{v}" is not a height in metres: the build drops it rather than read it as 0 - '
                           'set a number, or take the tag off', mid.lon if mid else box[0],
                           mid.lat if mid else box[1], box, way=w.id))
    for i, n in square.nodes.items():
        v = n.tags.get('ele')
        if v is None or parse_ele(v) is not None:
            continue
        name = n.tags.get('name')
        what = f'{n.tags.get("natural", "node")} "{name}"' if name else f'{n.tags.get("natural", "node")} {i}'
        out.append(Finding(square.name, 'ele', f'{what} - ele "{v}"',
                           f'"{v}" is not a height in metres: the build drops it - set a number',
                           n.lon, n.lat, (n.lon, n.lat, n.lon, n.lat), node=i))
    return out


def off_ladder(square) -> list[Finding]:
    """A row a contour at a value off the square's ladder used once or
    twice, with the values either side."""
    lad = L.infer(square)
    if lad is None:
        return []
    found = {a.value: a for a in L.off_ladder(square, lad)}
    out = []
    for w in square.contours():
        a = found.get(w.ele)
        if a is None:
            continue
        box = _box(square, w.refs)
        if box is None:
            continue
        mid = square.nodes.get(w.refs[len(w.refs) // 2])
        out.append(Finding(square.name, 'ladder', f'{_what(w)} - {a.describe()}',
                           f'{a.describe()}, off the {L.format_ele(lad.interval) + " m " if lad.interval else ""}ladder: a mistyped '
                           'value looks like this - set the right one, or leave it if it is meant',
                           mid.lon if mid else box[0], mid.lat if mid else box[1], box, way=w.id))
    return out


KINDS = {'long': long_ways, 'ele': bad_ele, 'ladder': off_ladder}


def find_in(square) -> list[Finding]:
    return [f for fn in KINDS.values() for f in fn(square)]


def find(working_set) -> list[Finding]:
    return [f for sq in working_set.squares.values() for f in find_in(sq)]


class Index:
    """The findings of a working set, a square asked again on any edit to
    it - cheap enough not to be cleverer. ``update`` takes the edit's ways
    and spot heights as the other indexes do, and asks the whole square."""

    def __init__(self, working_set):
        self.working_set = working_set
        self._by_square = {sq.name: find_in(sq) for sq in working_set.squares.values()}

    def update(self, square, *_):
        self._by_square[square.name] = find_in(square)

    def findings(self, kind: str | None = None) -> list[Finding]:
        out = [f for found in self._by_square.values() for f in found if kind is None or f.kind == kind]
        return sorted(out, key=lambda f: (f.kind, str(f.square), f.text))
