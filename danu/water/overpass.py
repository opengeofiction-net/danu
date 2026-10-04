"""Water from Overpass, as features a square can hold - R23.

An import, not a cache. A square is opened, edited and built from its own
file, and a working set that needs the network to describe its own rivers is
not self-contained; so what comes back from Overpass is turned into nodes,
ways and relations and written into the squares, where the mapper can edit it
and the build can read it like anything else they drew.

**What is asked for** is the working set's bounds. Not the centre square: a
river is graded along its course and a lake is flattened across its surface,
and both are cut short by asking for a degree at a time. Not the view either,
which is a thing that moves.

**What is kept** is `natural=water`, `water=*`, `waterway=*`, `name` and any
`ele`, and nothing else. A square is somebody's file and an import that drags
in `source`, `wikidata` and a decade of someone's tagging is harder to
reconcile and harder to read.

``waterway`` is in that list and was not in the sentence that set it, which
said `natural=water`, `water=*`, `name=*` and `ele`. It is here because R27 -
*flowing water is never flattened* - cannot be honoured by a square that
cannot tell a river from a lake, and R25 grades a river along its course.
Dropping it would import rivers as untagged lines and leave the rest of the
phase unable to do the thing it is for. Said rather than assumed, because it
is a widening of what was asked.

**Identity.** A feature arrives with the positive OSM id it had, which is what
a later import matches on - R40, and G5's whole subject. ``IdAllocator`` mints
below the lowest id in use and takes 0 as its ceiling, so positive ids never
move it and nothing a mapper draws can collide with one.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, field
from xml.etree import ElementTree

from ..core.square import Member, Node, Relation, Way

OVERPASS_URL = 'https://overpass.opengeofiction.net/api/interpreter'

# What the server is given to answer in, and what we wait. The batch grading
# asks for 900 seconds because a quarter hour at 3am is nothing; an editor is
# somebody sitting there, and a query that has not answered in a minute is one
# to be told about rather than waited out. The read waits a little longer than
# the server's own limit so that a timeout comes back as Overpass saying so,
# with its reason, rather than as us cutting the connection and guessing.
QUERY_TIMEOUT = 60
READ_TIMEOUT = 75
RETRIES = 3

# The waterways worth importing. The same two the batch grading reads as
# lines, for the same reason: a drain or a ditch is a dug channel, not what
# the terrain is shaped around, and grading one as a valley floor would pull
# the ground down along a thing somebody dug.
LINE_KINDS = ('river', 'stream')

# and the one that is an area rather than a line. `waterway=riverbank` is
# deprecated in favour of natural=water + water=river, and the data has not
# caught up: over the gobras 3x3 there are 115 of them, 114 closed, and not
# one also carries natural=water - so without this the river *surfaces* are
# missed entirely, 11,835 nodes of them. Measured rather than assumed, after
# `waterway=riverbank` turned up in the batch grader's FLOWING list and
# nowhere in the query.
AREA_KINDS = ('riverbank',)

# the tags upstream is the authority for, on a feature the square already
# holds: what kind of water it is and what it is called. A second import takes
# these from the answer even where the mapper has changed them - G5a, and the
# line R40 draws, upstream owning where the river is. Everything else on the
# feature, `ele` first among it, is the mapper's
UPSTREAM_OWNS = ('natural', 'water', 'waterway', 'name')

# the tags a feature keeps. A key alone means every value of it
KEEP = (*UPSTREAM_OWNS, 'ele')


def query(bounds: tuple[float, float, float, float]) -> str:
    """The Overpass QL for a working set's bounds, as (west, south, east,
    north).

    The box goes in the settings rather than on every statement, where each
    one inherits it - the same query, written once.

    The same answer, too, which was worth checking: a global ``[bbox:]``
    applies to the selection statements and *not* to the recurse, so the
    geometry of a feature straddling the edge still comes back whole. Review
    read it the other way and called it the one thing to settle before merge,
    which was the right instinct - a bounded recurse would hand a square a
    river with its far bank missing. Run both ways over the gobras 3x3 the
    two answers hold the same 158,633 nodes, 4,561 ways and 112 relations,
    id for id, and **1,535 of those nodes are outside the box**, across the
    39 ways that cross it. The files differ by one line: the global form
    echoes a ``<bounds>`` element. And the waterways are
    exact matches rather than one regex, because an exact tag value is an
    index lookup where a pattern is a test run over what the index returned.

    Named kinds rather than a bare ``way["waterway"]``, which was tried and
    measured. Over the gobras 3x3 it brings 969 more ways and 17,262 more
    nodes - 467 drains, 280 ditches, 44 canals, 32 docks, 24 dams, 5 weirs, a
    pair of lock gates and a boatyard - none of which anything grades, all of
    which a square would then hold and a re-import reconcile. A dam and a weir
    are lines *across* water; a ditch graded as a valley floor is a dug
    channel read as terrain. R23 names the scope: rivers, streams and water
    bodies.

    ``>>`` and not ``>``, which is the one place this costs anything.
    ``recurse.cc`` has ``DOWN`` collecting a relation's member nodes, its
    member ways and those ways' nodes, and ``DOWN_REL`` doing the same after
    a ``relations_loop`` over member *relations*. A multipolygon whose outer
    is itself a relation is a shape OSM holds, and under ``>`` it arrives as a
    member id with nothing behind it - a feature without its geometry, which
    is not something a square can hold. ``place`` follows nested relations
    for the same reason.

    ``out body`` rather than ``out geom``: the ids are the point, and a
    member's ref is how a relation says what it is made of.
    """
    west, south, east, north = bounds
    kinds = '\n  '.join(f'way["waterway"="{kind}"];'
                        for kind in LINE_KINDS + AREA_KINDS)
    return (f'[out:xml][timeout:{QUERY_TIMEOUT}][bbox:{south},{west},{north},{east}];\n'
            f'(\n  {kinds}\n'
            f'  way["natural"="water"];\n'
            f'  relation["natural"="water"];\n'
            f');\n(._;>>;);\nout body;\n')


def fetch(bounds, url: str = OVERPASS_URL, opener=None, retries: int = RETRIES) -> bytes:
    """The answer to ``query``, as bytes. Raises after ``retries`` failures.

    ``opener`` is the seam the tests use - none of them reach the network, as
    none of the tile or territory tests do.
    """
    opener = opener or urllib.request.urlopen
    data = query(bounds).encode()
    last: Exception | None = None
    for _attempt in range(retries):
        try:
            with opener(urllib.request.Request(url, data=data), timeout=READ_TIMEOUT) as resp:
                return resp.read()
        except Exception as exc:      # noqa: BLE001 - every failure is the same failure
            last = exc
    raise OSError(f'overpass did not answer after {retries} attempts: {last}')


def kept(tags: dict[str, str]) -> dict[str, str]:
    """The tags an imported feature keeps, in the order ``KEEP`` names them so
    that two imports of one feature write the same line."""
    return {k: tags[k] for k in KEEP if k in tags}


@dataclass
class Water:
    """What one import brought back, as things a square can hold."""
    nodes: dict[int, Node] = field(default_factory=dict)
    ways: dict[int, Way] = field(default_factory=dict)
    relations: dict[int, Relation] = field(default_factory=dict)

    def __len__(self) -> int:
        """The features, which is the ways and the relations. The nodes are
        geometry: a river's thousand of them are not a thousand things a
        mapper imported."""
        return len(self.ways) + len(self.relations)


def parse(payload: bytes) -> Water:
    """Overpass XML as nodes, ways and relations, tags filtered by ``kept``.

    A node keeps no tags at all unless it carries one of ``KEEP`` - a river's
    vertices are geometry and nothing else, and the ones that do carry
    something are the rare ones worth keeping, a named spring among them.
    """
    water = Water()
    root = ElementTree.fromstring(payload)
    for elem in root:
        tags = {t.get('k'): t.get('v', '') for t in elem.findall('tag')}
        if elem.tag == 'node':
            water.nodes[int(elem.get('id'))] = Node(
                id=int(elem.get('id')), lat=float(elem.get('lat')),
                lon=float(elem.get('lon')), tags=kept(tags))
        elif elem.tag == 'way':
            water.ways[int(elem.get('id'))] = Way(
                id=int(elem.get('id')),
                refs=[int(nd.get('ref')) for nd in elem.findall('nd')],
                tags=kept(tags))
        elif elem.tag == 'relation':
            water.relations[int(elem.get('id'))] = Relation(
                id=int(elem.get('id')),
                members=[Member(type=m.get('type'), ref=int(m.get('ref')),
                                role=m.get('role') or '')
                         for m in elem.findall('member')],
                tags=kept(tags))
    return water


def place(water: Water, working_set) -> dict:
    """Which square each feature belongs to, as ``{SquareName: Water}``.

    A feature goes whole into one square - the one holding its *anchor*, which
    is a way's first node and a relation's first member that resolves to one.
    Its nodes go with it, including the ones that fall in a neighbour.

    Whole, rather than clipped at the boundary, for two reasons that are the
    same reason. A clipped river is two ways with two ids, and the next import
    has nothing to match the original against - R40 is the whole of G5 and
    rests on the id arriving unchanged. And a clipped ring is not a ring: cut
    a lake at a degree line and the multipolygon it belonged to describes an
    open shape, which is how an island becomes a peninsula.

    The cost is squares whose contents reach past their own degree, which
    nothing here objects to - ``write_square`` writes a node where it is, and
    the build reads the working set rather than a square. A feature whose
    anchor is outside the set is dropped: Overpass answers a bounding box and
    the set is not one, so some of what comes back is a river passing by.
    """
    out: dict = {}
    # Relations first, and everything they are made of goes with them rather
    # than where its own first node happens to fall. Otherwise a lake's outer
    # ring is placed twice - once on its own account and once as a member -
    # and a square two degrees from the relation holds half its shape.
    #
    # Only a relation that was placed claims anything: one anchored outside
    # the set is dropped, and a member way of it that *is* inside has to be
    # left for the loop below to place on its own account.
    claimed: set[int] = set()
    taken: set[int] = set()
    for rel in _outermost_first(water):
        if rel.id in taken:
            continue                 # already placed, with the relation that names it
        square = _square_of(working_set, _relation_anchor(water, rel))
        if square is None:
            continue
        ways, rels = _put(out, square, water, relations=[rel])
        claimed |= ways
        taken |= rels
    for way in water.ways.values():
        if way.id in claimed:
            continue
        square = _square_of(working_set, _way_anchor(water, way))
        if square is not None:
            _put(out, square, water, ways=[way])
    return out


def _outermost_first(water: Water) -> list:
    """The relations, those that nothing else names before those that are
    named - so a nested one is placed by its parent rather than on its own
    account first and then again as a member, in two squares.

    Not a full topological sort, and it does not need to be: what matters is
    that a relation with a parent is not reached before the parent. A cycle
    has no outermost member, so its relations all fall into the second group,
    where the order between them is arbitrary and ``_put``'s ``seen`` guard
    stops the walk.
    """
    named = {mem.ref for rel in water.relations.values()
             for mem in rel.members if mem.type == 'relation'}
    loose = [r for r in water.relations.values() if r.id not in named]
    return loose + [r for r in water.relations.values() if r.id in named]


def _way_anchor(water: Water, way: Way) -> Node | None:
    for ref in way.refs:
        node = water.nodes.get(ref)
        if node is not None:
            return node
    return None


def _relation_anchor(water: Water, rel: Relation, seen=None) -> Node | None:
    """The first member that resolves to a node, following relation members.

    ``seen`` is the path and not the walk: a relation is added on the way in
    and taken out again on the way out, so a cycle is stopped without a second
    branch being refused for having been down the same way.

    Review asked for this, on the argument that an accumulating set would mark
    an inner relation seen on a branch that found nothing and then refuse a
    later branch that needed it. I could not build that case, and on reflection
    it cannot exist: whether a relation resolves depends on what it can reach,
    not on how it was reached, so a second visit returns exactly what the first
    did. The shape here is the right one and costs nothing; it is not a fix for
    a bug anyone has seen.
    """
    seen = set() if seen is None else seen
    if rel.id in seen:
        return None
    seen.add(rel.id)
    try:
        return _anchor_in(water, rel, seen)
    finally:
        seen.discard(rel.id)


def _anchor_in(water: Water, rel: Relation, seen) -> Node | None:
    for mem in rel.members:
        if mem.type == 'node':
            node = water.nodes.get(mem.ref)
            if node is not None:
                return node
        elif mem.type == 'way':
            way = water.ways.get(mem.ref)
            if way is not None:
                node = _way_anchor(water, way)
                if node is not None:
                    return node
        elif mem.type == 'relation':
            inner = water.relations.get(mem.ref)
            if inner is not None:
                node = _relation_anchor(water, inner, seen)
                if node is not None:
                    return node
    return None


def _square_of(working_set, anchor: Node | None):
    if anchor is None:
        return None
    square = working_set.at(anchor.lon, anchor.lat)
    return square.name if square is not None else None


def _put(out: dict, name, water: Water, ways=(), relations=(), seen=None) -> tuple[set, set]:
    """Put features into a square's bucket, with their geometry, and say which
    way and relation ids went in.

    Relations nest: a multipolygon's outer may itself be a relation, which is
    a shape OSM really holds. ``seen`` is what stops a relation that names
    itself, directly or round a ring of others, from walking for ever - bad
    data rather than a shape, but bad data is what a public API returns.
    """
    seen = set() if seen is None else seen
    bucket = out.setdefault(name, Water())
    placed: set[int] = set()
    rels: set[int] = set()
    for way in ways:
        bucket.ways[way.id] = way
        placed.add(way.id)
        for ref in way.refs:
            node = water.nodes.get(ref)
            if node is not None:
                bucket.nodes[node.id] = node
    for rel in relations:
        if rel.id in seen:
            continue
        seen.add(rel.id)
        bucket.relations[rel.id] = rel
        rels.add(rel.id)
        for mem in rel.members:
            if mem.type == 'way' and mem.ref in water.ways:
                more, _ = _put(out, name, water, ways=[water.ways[mem.ref]], seen=seen)
                placed |= more
            elif mem.type == 'node' and mem.ref in water.nodes:
                bucket.nodes[mem.ref] = water.nodes[mem.ref]
            elif mem.type == 'relation' and mem.ref in water.relations:
                more, inner = _put(out, name, water,
                                   relations=[water.relations[mem.ref]], seen=seen)
                placed |= more
                rels |= inner
    return placed, rels
