"""Spot heights imported from the main map - G9, R41.

R37: a spot height is the only thing which shapes a hilltop, and the editor
lets a mapper place one by hand. The main map already holds them: near Gobras,
556 peaks and 8 saddles, 231 and 2 of them with an `ele`. This brings those
into the squares as the water import brings water (R23) - a square stays
self-contained - and a second import reconciles as R40 says: matched by OSM
id, the position and the name from upstream, and the height set here kept.
Upstream's height fills in only where the square has none.

**What is imported** is a `natural=peak`, `volcano` or `saddle` node with a
height that reads as metres - a saddle is the low point of a ridge, and shapes
the surface as surely as a summit. A height is a number, its thousands
separators aside, in metres or feet: one near Gobras is "8,635 Ft", and lands
as 2,632 m. One with no height, or one that reads as neither, is skipped and
counted - a node with no `ele` is no constraint (R36), and an import is not
the place to guess one.

**Only where the contours are.** The build's envelope is the contour lines'
(R21), and a spot height beyond it describes nothing yet: one in a square with
no contour, or past the box of its square's contours, is not imported, and
counted - near Gobras, 49 of the 253. Drawn out to it, a second import brings
it. One the set already holds is reconciled wherever it stands.

A spot height the set holds that upstream no longer answers - deleted, or its
height taken off - is reported, never deleted, as water is (G5b).

No Qt and no GDAL. The fetch is the water import's, over the same server.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

from ..core.ladder import format_ele
from ..core.square import Node, SquareName, parse_ele
from .gone import Gone
from .overpass import QUERY_TIMEOUT, IncompleteAnswer

KINDS = ('peak', 'volcano', 'saddle')
# what upstream is the authority for, on a spot height: what it is and what it
# is called, and where it is. The height is the mapper's, as on water
UPSTREAM_OWNS = ('natural', 'name')
FOOT_M = 0.3048

_HEIGHT = re.compile(r"^\s*(-?\d{1,3}(?:,\d{3})+|-?\d+)(\.\d+)?\s*(m|metres|meters|ft|feet|')?\s*$",
                     re.IGNORECASE)


def metres(value: str | None) -> float | None:
    """A height as upstream wrote it, in metres - or None when it does not
    read as one."""
    if value is None:
        return None
    m = _HEIGHT.match(value)
    if m is None:
        return None
    number = float(m.group(1).replace(',', '') + (m.group(2) or ''))
    unit = (m.group(3) or 'm').lower()
    # a height in feet is good to a third of a metre at best: to the metre
    return float(round(number * FOOT_M)) if unit in ('ft', 'feet', "'") else number


def query(bounds) -> str:
    west, south, east, north = bounds
    kinds = '|'.join(KINDS)
    return (f'[out:xml][timeout:{QUERY_TIMEOUT}][bbox:{south},{west},{north},{east}];\n'
            f'node["natural"~"^({kinds})$"]["ele"];\nout;')


@dataclass
class Heights:
    """What an answer held: the spot heights to import, and the ones skipped
    for a height that does not read - with where, for the report."""
    nodes: dict = field(default_factory=dict)          # id -> Node, `ele` in metres
    skipped: list = field(default_factory=list)        # (id, ele as written, lon, lat)
    beyond: list = field(default_factory=list)         # ids beyond the contours, not imported

    @property
    def answered(self) -> frozenset:
        """Every spot height the answer named, imported or not: one skipped
        for its height, or beyond the contours, is not gone."""
        return frozenset(self.nodes) | frozenset(i for i, *_ in self.skipped) | frozenset(self.beyond)


def parse(payload: bytes) -> Heights:
    out = Heights()
    root = ElementTree.fromstring(payload)
    for elem in root:
        if elem.tag == 'remark' and 'runtime error' in (elem.text or ''):
            raise IncompleteAnswer(' '.join((elem.text or '').split()))
        if elem.tag != 'node':
            continue
        tags = {t.get('k'): t.get('v', '') for t in elem.findall('tag')}
        if tags.get('natural') not in KINDS:
            continue
        i, lon, lat = int(elem.get('id')), float(elem.get('lon')), float(elem.get('lat'))
        height = metres(tags.get('ele'))
        if height is None:
            out.skipped.append((i, tags.get('ele'), lon, lat))
            continue
        kept = {k: tags[k] for k in UPSTREAM_OWNS if k in tags}
        kept['ele'] = format_ele(height)
        out.nodes[i] = Node(id=i, lat=lat, lon=lon, tags=kept)
    return out


def _imported(square):
    """The spot heights a square holds from upstream: a positive id, a kind
    asked for, and a height - every one this imports carries one. The water
    import keeps a `natural=peak` on the vertex of a river that carries one,
    with no height, and that is not a spot height; a spot height a mapper has
    since drawn a line through still is."""
    return [(i, n) for i, n in square.nodes.items()
            if i > 0 and n.tags.get('natural') in KINDS and 'ele' in n.tags]


def held(working_set) -> dict:
    """Which square holds each imported spot height, snapshotted where the
    import is asked for, as water's is."""
    return {i: name for name, sq in working_set.squares.items() for i, _ in _imported(sq)}


def envelopes(working_set) -> dict:
    """Where the contours are, per degree square: the box of the vertices of
    every way with a numeric ``ele`` falling in it, as ``{SquareName: (west,
    south, east, north)}``. The build's envelope (R21) is this box to the
    cell. Taken on the UI thread, where the import is asked for."""
    out: dict = {}
    for sq in working_set.squares.values():
        for w in sq.ways.values():
            if parse_ele(w.tags.get('ele')) is None:
                continue
            for r in w.refs:
                n = sq.nodes.get(r)
                if n is None:
                    continue
                name = SquareName((math.floor(n.lon) + 180) % 360 - 180, math.floor(n.lat))
                box = out.get(name)
                out[name] = ((n.lon, n.lat, n.lon, n.lat) if box is None else
                             (min(box[0], n.lon), min(box[1], n.lat), max(box[2], n.lon), max(box[3], n.lat)))
    return out


def within(heights: Heights, boxes: dict, held_at: dict | None = None) -> Heights:
    """The answer with the spot heights beyond the contours taken out and
    counted: a new one in a square with no box, or outside its box. One the
    set holds stays, to be reconciled where it is."""
    held_at = held_at or {}
    out = Heights(skipped=list(heights.skipped), beyond=list(heights.beyond))
    for i, n in heights.nodes.items():
        box = boxes.get(SquareName((math.floor(n.lon) + 180) % 360 - 180, math.floor(n.lat)))
        if i in held_at or (box is not None and box[0] <= n.lon <= box[2] and box[1] <= n.lat <= box[3]):
            out.nodes[i] = n
        else:
            out.beyond.append(i)
    return out


def place(heights: Heights, working_set, held_at: dict | None = None) -> dict:
    """Each spot height into a square, as ``{SquareName: {id: Node}}``: one
    the set holds goes back where it is held, the rest into the square it
    falls in. One outside the set is dropped - Overpass answers a box."""
    held_at = held_at or {}
    out: dict = {}
    for i, n in heights.nodes.items():
        name = held_at.get(i)
        if name is None:
            sq = working_set.at(n.lon, n.lat)
            name = sq.name if sq is not None else None
        if name is not None:
            out.setdefault(name, {})[i] = n
    return out


def gone(working_set, answered: frozenset) -> list[Gone]:
    """Every imported spot height the set holds that the answer did not name
    - deleted upstream, or its height taken off."""
    out = []
    for name in sorted(working_set.squares, key=str):
        for i, n in sorted(_imported(working_set.squares[name])):
            if i not in answered:
                out.append(Gone(name, 'node', i, n.tags.get('name'), n.tags['natural']))
    return out
