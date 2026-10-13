"""The main map's coastlines, imported into the squares.

As water is (R23, R40): fetched from Overpass over the working set, each way
placed whole into the square holding its first node, under its OSM id and
version, one undoable step; a second import reconciles, upstream owning where
the coast is and which way it runs. A coastline lands carrying ``ele=0`` as
well as ``natural=coastline``, as every coastline in these squares does, so
the build holds it at sea level - the mapper's ``ele`` kept on a second
import, as on water.

Upstream's direction is right by definition: on the main map a coastline has
the land on its left and the sea on its right, and that is what the build
reads the sea from. A mapper's own 0 m line along the same shore is left
alone - deleting it, or marking it, is the mapper's to do.

A held coastline the answer no longer names is reported, never deleted.

No Qt and no GDAL. The fetch is the water import's, over the same server.
"""

from __future__ import annotations

from ..core.square import is_coastline
from .gone import Gone
from .overpass import QUERY_TIMEOUT, Water, parse

# what upstream is the authority for on a coastline: that it is one, and its
# name if it has one. Its ele is the mapper's, as on water
UPSTREAM_OWNS = ('natural', 'name')


def query(bounds) -> str:
    """Every coastline way over the box, with its nodes - ``out meta`` for the
    version, which the square keeps beside the id."""
    west, south, east, north = bounds
    return (f'[out:xml][timeout:{QUERY_TIMEOUT}][bbox:{south},{west},{north},{east}];\n'
            f'(way["natural"="coastline"];>;);\nout meta;\n')


def coastlines(payload: bytes) -> Water:
    """The answer as ways a square can hold: each coastline at ``ele=0``, its
    nodes untagged geometry. Anything else the answer holds is dropped."""
    got = parse(payload)
    out = Water()
    for i, way in got.ways.items():
        if not is_coastline(way):
            continue
        way.tags = {**{k: way.tags[k] for k in UPSTREAM_OWNS if k in way.tags}, 'ele': '0'}
        out.ways[i] = way
        for r in way.refs:
            if r in got.nodes:
                # geometry and nothing else: a peak's ele on a vertex would
                # land as a spot height, which is the spot heights' import's
                got.nodes[r].tags = {}
                out.nodes[r] = got.nodes[r]
    return out


def gone(working_set, answered: frozenset) -> list[Gone]:
    """Every coastline the set holds from the main map - a positive id - that
    the answer did not name: deleted upstream, or no longer a coastline."""
    out = []
    for name in sorted(working_set.squares, key=str):
        for way in working_set.squares[name].ways.values():
            if way.id > 0 and is_coastline(way) and way.id not in answered:
                out.append(Gone(name, 'way', way.id, way.tags.get('name'), 'coastline'))
    return out
