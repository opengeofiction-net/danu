"""An element of the open squares by its OSM id, as Edit › Find element asks
for it: ``n123``, ``w-50092477``, ``r248`` - the letter JOSM's own search and
the OSM website's short links use - or ``node/123``, ``way 123``,
``relation/248``. A contour's id is negative, minted here, so the sign is part
of the id."""

from __future__ import annotations

import re

KINDS = {'n': 'node', 'w': 'way', 'r': 'relation'}

_ID = re.compile(r'^\s*(n|w|r|node|way|relation)\s*[/:]?\s*(-?\d+)\s*$', re.IGNORECASE)


def parse(text: str) -> tuple[str, int]:
    """(kind, id) from what was typed: kind 'node', 'way' or 'relation'.
    ValueError for anything else, said so the dialog can say it back."""
    m = _ID.match(text or '')
    if m is None:
        raise ValueError(f'{text.strip()!r} is not an element: n, w or r and its id, as w-50092477')
    word = m.group(1).lower()
    return KINDS.get(word, word), int(m.group(2))


def holder(square, kind: str) -> dict:
    return {'node': square.nodes, 'way': square.ways, 'relation': square.relations}[kind]


def find(squares, kind: str, ident: int) -> list:
    """Every (square, element) of ``squares`` holding it, in the order given.
    More than one where squares share an element - a lake across a degree
    line, or ids minted separately in two squares."""
    out = []
    for sq in squares:
        el = holder(sq, kind).get(ident)
        if el is not None:
            out.append((sq, el))
    return out


def way_of(square, node_id: int):
    """A way of the square the node is a vertex of, or None: one with no
    ``natural`` or ``waterway`` tag - a contour - before a water outline, a
    coastline or a river, so the selection is the line a click on the node
    would most likely have meant."""
    found = None
    for w in square.ways.values():
        if node_id in w.refs:
            if 'natural' not in w.tags and 'waterway' not in w.tags:
                return w
            found = found or w
    return found
