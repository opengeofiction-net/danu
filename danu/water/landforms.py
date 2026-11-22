"""The main map's landforms, imported into the squares - #191.

As water and coastlines are (R23, R40): fetched from Overpass over the working
set, each feature placed whole into the square holding most of it, under its
OSM id and version, one undoable step; a second import reconciles, upstream
owning what the feature is and what it is called, the heights set here kept.

What is imported is what the surface reads (#191):

* the landforms drawn as a line - a ridge or an arete, a valley, a gully or a
  gorge - held along their length once their vertices carry heights (R48),
  graded from the contours by G;
* the cliffs and earth banks, which drop their ``height`` to their right once
  given the ``ele`` of their top (R51);
* the flat landforms drawn as an area, a dry lake or a plateau, held flat at
  their ``ele`` (R50) - ways and relations alike.

The main map holds a great many and almost none with a height: 14,785 ridges
and 38,011 cliffs, 9 and 34 of them with an ``ele`` (2026-11-21). So an import
brings lines to grade and cliffs to give heights to, more than a surface
changed at once - which is why it is an import of its own, not part of
water's.

A vertex's tags are left behind, as a coastline's are: a peak on a ridge is
the spot heights' import's. A held landform the answer no longer names is
reported, never deleted.

No Qt and no GDAL. The fetch is the water import's, over the same server.
"""

from __future__ import annotations

from ..surface.cliff import KINDS as CLIFFS
from ..surface.held import LANDFORMS as LINES
from .gone import Gone
from .overpass import QUERY_TIMEOUT, Water, parse

AREAS = ('dry_lake', 'plateau')
KINDS = LINES + CLIFFS + AREAS
# what upstream is the authority for: what it is and its name. Its heights -
# a ridge's on its vertices, a cliff's ele and height, a flat area's ele - are
# the mapper's once set here, as water's are; a new feature lands with any
# upstream has
UPSTREAM_OWNS = ('natural', 'name')
# and what a landform keeps of upstream's tags: a cliff's height as well as
# the heights water keeps, and a multipolygon's type
KEEP = ('natural', 'name', 'type', 'ele', 'height')


def query(bounds) -> str:
    """Every landform over the box: the lines and cliffs as ways, the flat
    areas as ways or relations - each with what it is made of (``>>``, as
    water's query, for a multipolygon whose outer is a relation)."""
    west, south, east, north = bounds
    ways = '\n  '.join(f'way["natural"="{k}"];' for k in KINDS)
    rels = '\n  '.join(f'relation["natural"="{k}"];' for k in AREAS)
    return (f'[out:xml][timeout:{QUERY_TIMEOUT}][bbox:{south},{west},{north},{east}];\n'
            f'(\n  {ways}\n  {rels}\n);\n(._;>>;);\nout meta;\n')


def is_landform(tags: dict) -> bool:
    return tags.get('natural') in KINDS


def landforms(payload: bytes) -> Water:
    """The answer as features a square can hold: the landforms, and the
    member ways and nodes they are made of, a vertex's tags left behind."""
    got = parse(payload, KEEP)
    out = Water()
    for i, rel in got.relations.items():
        if rel.tags.get('natural') in AREAS:
            out.relations[i] = rel
    members = {m.ref for r in out.relations.values() for m in r.members if m.type == 'way'}
    for i, way in got.ways.items():
        if is_landform(way.tags) or i in members:
            out.ways[i] = way
            for r in way.refs:
                if r in got.nodes:
                    got.nodes[r].tags = {}
                    out.nodes[r] = got.nodes[r]
    return out


def gone(working_set, ways: frozenset, relations: frozenset) -> list[Gone]:
    """Every landform the set holds from the main map - a positive id - that
    the answer did not name: deleted upstream, or no longer a landform."""
    out = []
    for name in sorted(working_set.squares, key=str):
        sq = working_set.squares[name]
        for way in sq.ways.values():
            if way.id > 0 and is_landform(way.tags) and way.id not in ways:
                out.append(Gone(name, 'way', way.id, way.tags.get('name'), way.tags['natural']))
        for rel in sq.relations.values():
            if rel.id > 0 and rel.tags.get('natural') in AREAS and rel.id not in relations:
                out.append(Gone(name, 'relation', rel.id, rel.tags.get('name'), rel.tags['natural']))
    return out
