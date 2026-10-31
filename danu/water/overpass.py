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

import math
import urllib.request
from dataclasses import dataclass, field
from xml.etree import ElementTree

from .. import USER_AGENT
from ..core import chains
from ..core.square import Member, Node, Relation, SquareName, Way, xml_version

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
LINE_KINDS = chains.LINE_KINDS        # one list, with the grade's (G6c)

# and the one that is an area rather than a line. `waterway=riverbank` is
# deprecated in favour of natural=water + water=river, and the data has not
# caught up: over the gobras 3x3 there are 115 of them, 114 closed, and not
# one also carries natural=water - so without this the river *surfaces* are
# missed entirely, 11,835 nodes of them. Measured rather than assumed, after
# `waterway=riverbank` turned up in the batch grader's FLOWING list and
# nowhere in the query.
AREA_KINDS = ('riverbank',)

# what flows, as a `waterway` or a `water` value. natural=water covers still
# water and flowing water alike, and a river area is not flat: it descends
# along its course - R27. Flattening relation 89708, the Bosco River, at the
# lowest contour its outline touches put the whole of it at 0 m - the level
# near its mouth - and cost 1,262 m of river ascent on its own. Here, without
# GDAL, so the editor's choice of what can take one level and the batch
# grader's are the same list
FLOWING = ('river', 'stream', 'canal', 'ditch', 'drain', 'riverbank')


def flows(tags: dict[str, str]) -> bool:
    """Whether water with these tags descends along its course, so has no
    single level to be set or flattened at."""
    return tags.get('waterway') in FLOWING or tags.get('water') in FLOWING

# the tags upstream is the authority for, on a feature the square already
# holds: what kind of water it is and what it is called. A second import takes
# these from the answer even where the mapper has changed them - G5a, and the
# line R40 draws, upstream owning where the river is. Everything else on the
# feature, `ele` first among it, is the mapper's. And a relation's `type`,
# without which JOSM takes a lake for no multipolygon at all
UPSTREAM_OWNS = ('natural', 'water', 'waterway', 'name', 'type')

# the tags a feature keeps. A key alone means every value of it
KEEP = (*UPSTREAM_OWNS, 'ele')


def asked_for(kind: str, tags: dict[str, str]) -> bool:
    """Whether the query asks for a feature of this kind with these tags.

    The question G5b's "gone from upstream" turns on. A feature the square
    holds and the answer does not name is gone only if the query would have
    returned it - otherwise every coastline and contour would be reported
    missing on every import. So this is the query's own selection, said a
    second time, and a test holds the two together.
    """
    if kind == 'way':
        return (tags.get('waterway') in LINE_KINDS + AREA_KINDS
                or tags.get('natural') == 'water')
    if kind == 'relation':
        return tags.get('natural') == 'water'
    return False


class IncompleteAnswer(OSError):
    """Overpass ran out of time or memory and sent what it had.

    It does that with an HTTP 200 and a ``<remark>`` saying *runtime error*,
    so nothing below the parse can tell a truncated answer from a whole one.
    Importing it would be harmless to the merge, which writes only what it is
    given; it would not be harmless to G5b, which reads absence as deletion
    and would report every feature the answer was cut short of as gone
    upstream. An answer that says it is incomplete is refused whole.

    Raised by ``parse`` because ``parse`` is the one place that reads the
    payload; a stored answer replayed through it should be refused for the
    same reason a fresh one is. An ``OSError`` although ``parse`` does no
    I/O, because what went wrong is the server failing to deliver - the
    payload is well formed, there is just not all of it - and that is the
    class of failure the import already reports for a dropped connection.
    """


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

    ``out meta`` rather than ``out geom``: the ids are the point, and a
    member's ref is how a relation says what it is made of. Meta and not
    ``out body`` for the version, which the square keeps beside the id - JOSM
    will not open a positive id without one.
    """
    west, south, east, north = bounds
    kinds = '\n  '.join(f'way["waterway"="{kind}"];'
                        for kind in LINE_KINDS + AREA_KINDS)
    return (f'[out:xml][timeout:{QUERY_TIMEOUT}][bbox:{south},{west},{north},{east}];\n'
            f'(\n  {kinds}\n'
            f'  way["natural"="water"];\n'
            f'  relation["natural"="water"];\n'
            f');\n(._;>>;);\nout meta;\n')


def fetch(bounds, url: str = OVERPASS_URL, opener=None, retries: int = RETRIES,
          text: str | None = None) -> bytes:
    """The answer to ``query``, as bytes - or to ``text``, another query over
    the same server, the spot heights' (G9). Raises after ``retries``
    failures.

    ``opener`` is the seam the tests use - none of them reach the network, as
    none of the tile or territory tests do.
    """
    opener = opener or urllib.request.urlopen
    data = (text if text is not None else query(bounds)).encode()
    last: Exception | None = None
    for _attempt in range(retries):
        try:
            with opener(urllib.request.Request(url, data=data, headers={'User-Agent': USER_AGENT}), timeout=READ_TIMEOUT) as resp:
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
        if elem.tag == 'remark' and 'runtime error' in (elem.text or ''):
            raise IncompleteAnswer(' '.join((elem.text or '').split()))
        tags = {t.get('k'): t.get('v', '') for t in elem.findall('tag')}
        if elem.tag == 'node':
            water.nodes[int(elem.get('id'))] = Node(
                id=int(elem.get('id')), lat=float(elem.get('lat')),
                lon=float(elem.get('lon')), tags=kept(tags), version=xml_version(elem))
        elif elem.tag == 'way':
            water.ways[int(elem.get('id'))] = Way(
                id=int(elem.get('id')),
                refs=[int(nd.get('ref')) for nd in elem.findall('nd')],
                tags=kept(tags), version=xml_version(elem))
        elif elem.tag == 'relation':
            water.relations[int(elem.get('id'))] = Relation(
                id=int(elem.get('id')),
                members=[Member(type=m.get('type'), ref=int(m.get('ref')),
                                role=m.get('role') or '')
                         for m in elem.findall('member')],
                tags=kept(tags), version=xml_version(elem))
    return water


def place(water: Water, working_set, held: dict | None = None) -> dict:
    """Which square each feature belongs to, as ``{SquareName: Water}``,
    among the open set's squares. A held feature stays where it is held,
    always - this never moves one, for a caller that takes nothing out of
    where it was, as the coastline import does. ``homes`` is the whole of it."""
    return homes(water, working_set, held, move=False)[0]


def homes(water: Water, working_set, held: dict | None = None,
          zone: tuple | None = None, move: bool = True) -> tuple[dict, dict]:
    """Which square each feature belongs to - its *home* - as ``{SquareName:
    Water}``, and the features whose home has moved, as ``{(kind, id): (the
    square that held it, its home now)}``.

    A feature goes whole into one square: the one holding most of its nodes,
    among the zone's squares and the open set's - ``zone`` is the zone's
    square names and what its files hold, ``(names, held)``; without it, the
    set's alone. Its nodes go with it, including the ones that fall in a
    neighbour, and a relation takes its members with it.

    Whole, rather than clipped at the boundary, for two reasons that are the
    same reason. A clipped river is two ways with two ids, and the next import
    has nothing to match the original against - R40 is the whole of G5 and
    rests on the id arriving unchanged. And a clipped ring is not a ring: cut
    a lake at a degree line and the multipolygon it belonged to describes an
    open shape, which is how an island becomes a peninsula.

    **Most of its nodes**, not its first node, which was the rule until the
    sea came: r470432's first node is two squares from N46E030, so opened
    there it was dropped and its 916 ways came in bare, as lines. Where most
    of a feature lies is the mapper's to see, and does not move when the main
    map lists a relation's members in another order.

    **A feature already held stays where it is** - G5b - unless another square
    now holds more of its nodes than that one: in a world being built the
    sea grows and shrinks, and its home follows it. Never for a tie, so a lake
    across a degree line half and half does not flit between the two. ``held``
    is the open squares', snapshotted on the UI thread when the import was
    asked for; the zone's files say for the rest. A feature moved is the
    caller's to take out of the square that held it - a relation's member
    ways and relations moved with it each said too, as their own move.
    """
    held = held or {}
    zone_names, zone_held = zone if zone is not None else (set(), {})
    cand = set(working_set.squares) | set(zone_names)
    out: dict = {}
    moved: dict = {}

    def home_of(kind, fid, counts):
        return _home(cand, counts, held.get((kind, fid)) or zone_held.get((kind, fid)), move)

    def note(kind, fid, home):
        was = held.get((kind, fid)) or zone_held.get((kind, fid))
        if was is not None and was != home:
            moved[(kind, fid)] = (was, home)

    # Relations first, and everything they are made of goes with them rather
    # than where its own nodes would put it. Otherwise a lake's outer ring is
    # placed twice - once on its own account and once as a member - and a
    # square two degrees from the relation holds half its shape.
    #
    # And relations sharing a member way go together: a ring is held in one
    # file, and every relation naming it with it - r3505's shore is three ways
    # of the sea's, and held with each where most of it lies, the three were
    # written twice and moved back and forth on every import
    claimed: set[int] = set()
    taken: set[int] = set()
    for group in _sharing(water, _outermost_first(water)):
        group = [r for r in group if r.id not in taken]
        if not group:
            continue                 # already placed, with the relation that names them
        nodes = set().union(*(_nodes_of(water, r) for r in group))
        # where the group is held, if all of it is in one square
        holders = {held.get(('relation', r.id)) or zone_held.get(('relation', r.id)) for r in group}
        was = next(iter(holders)) if len(holders) == 1 else None
        square = _home(cand, _counts(water, nodes), was, move)
        if square is None:
            continue
        ways, rels = _put(out, square, water, relations=group)
        claimed |= ways
        taken |= rels
        for wid in ways:
            note('way', wid, square)
        for rid in rels:
            note('relation', rid, square)
    for way in water.ways.values():
        if way.id in claimed:
            continue
        square = home_of('way', way.id, _counts(water, set(way.refs)))
        if square is not None:
            _put(out, square, water, ways=[way])
            note('way', way.id, square)
    return out, moved


def _home(cand, counts, was, move):
    """The square of ``cand`` holding most of ``counts`` - ties to the lower
    name - unless ``was``, where it is held, holds as many: or always ``was``,
    not ``move``."""
    counts = {n: c for n, c in counts.items() if n in cand}
    if not counts:
        return None
    best = max(sorted(counts, key=str), key=counts.get)
    if was is not None and (not move or counts.get(was, 0) >= counts[best]):
        return was
    return best


def _sharing(water: Water, rels: list) -> list[list]:
    """The relations in groups, those naming a way in common together, in
    the order given - a group is led by its first."""
    parent = {r.id: r.id for r in rels}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    by_way: dict = {}
    for r in rels:
        for m in r.members:
            if m.type == 'way':
                other = by_way.setdefault(m.ref, r.id)
                if other != r.id:
                    parent[find(r.id)] = find(other)
    groups: dict = {}
    for r in rels:
        groups.setdefault(find(r.id), []).append(r)
    return list(groups.values())


def _nodes_of(water: Water, rel: Relation, seen=None) -> set[int]:
    """Every node a relation is made of, through its member ways and
    relations - each once, shared by two rings or not. ``seen`` is the whole
    walk's: a relation reached twice adds nothing the first visit did not,
    and a relation naming itself is stopped."""
    seen = set() if seen is None else seen
    if rel.id in seen:
        return set()
    seen.add(rel.id)
    out: set[int] = set()
    for mem in rel.members:
        if mem.type == 'node':
            out.add(mem.ref)
        elif mem.type == 'way' and mem.ref in water.ways:
            out.update(water.ways[mem.ref].refs)
        elif mem.type == 'relation' and mem.ref in water.relations:
            out |= _nodes_of(water, water.relations[mem.ref], seen)
    return out


def _counts(water: Water, node_ids) -> dict:
    """How many of the nodes fall in each degree square."""
    out: dict = {}
    for i in node_ids:
        n = water.nodes.get(i)
        if n is None:
            continue
        try:
            name = SquareName((math.floor(n.lon) + 180) % 360 - 180, math.floor(n.lat))
        except ValueError:
            continue
        out[name] = out.get(name, 0) + 1
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
