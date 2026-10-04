"""A river as the chain of ways it was split into - G6d.

Mappers split a river wherever they stopped, or a tag changed, or a bridge
went over: on the gobras set 158 of 398 named rivers and streams are more than
one way, the Bosco River thirty-eight. Graded way by way, a piece with one
crossing gets nothing, though the next piece has five. Graded as the chain it
belongs to - JOSM's *non-branching way sequence* - the 149 chains of three or
more ways there level 7,478 points instead of 4,090, measured through the
editor's own grade.

A chain runs end to end through nodes where exactly two waterway lines meet,
both ending there. It stops where a third line meets it (a confluence, the
network's business, not the chain's), where one passes through without ending
(a tributary drawn on to the river's side), where it comes back on itself, and
where it simply ends.

**A gap of up to ``TOLERANCE_M`` between two free ends is crossed**, for the
grade and nothing else: no node is added or moved, because upstream owns the
geometry (G5a). These gaps are mapping errors - a piece of stream that stops
a metre or two short of the next. On the gobras set there are seven within
5 m, six of them within 1 m, and not one between two differently named
waterways at any distance up to 25 m. Every one crossed is reported, so it can
be fixed where it was made rather than hidden here. A gap is not crossed
between two differently named waterways, nor where two free ends are in reach,
which is a branch the data does not say is one.

Node identity: an imported node's id is its OSM id and the same in every
square that holds it, which is how a chain runs from one square into the next.
A negative id was allocated in one square's file and means nothing in another.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

# the lines a chain is walked along, and the ones an import keeps as lines
# (overpass.LINE_KINDS is this list)
LINE_KINDS = ('river', 'stream')
TOLERANCE_M = 5.0


@dataclass(frozen=True)
class Link:
    """One way of a chain, and whether it is walked against its drawing."""
    square: object
    way: object
    backwards: bool = False

    def refs(self) -> list[int]:
        return list(reversed(self.way.refs)) if self.backwards else list(self.way.refs)


@dataclass(frozen=True)
class Join:
    """A gap the chain was walked across - a mapping error, reported."""
    after: int                # way id walked from
    before: int               # way id walked into
    gap_m: float
    lon: float
    lat: float


@dataclass
class Chain:
    links: list[Link] = field(default_factory=list)
    joins: list[Join] = field(default_factory=list)
    # why it stops at each end, for the proposal to say
    stops: tuple[str, str] = ('end', 'end')


def node_key(square, nid: int):
    return nid if nid > 0 else (square.name, nid)


def _metres(a, b) -> float:
    lat = math.radians((a.lat + b.lat) / 2)
    return math.hypot((a.lon - b.lon) * 111320 * math.cos(lat), (a.lat - b.lat) * 110540)


class Network:
    """Every waterway line in a working set, indexed by where they end and
    where they pass through - built once per grade, which is a walk of the
    set's ways and is a few milliseconds on the gobras 3x3."""

    def __init__(self, working_set, tolerance_m: float = TOLERANCE_M):
        self.tolerance_m = tolerance_m
        self.ends: dict = {}                 # node key -> [(square, way, at_start)]
        self.through: set = set()            # node keys some line passes through
        self.node: dict = {}                 # node key -> Node, for distances
        self.at: dict = {}                   # node key -> [(square, way)] at any vertex
        self.lines: list = []                # (square, way), every waterway line
        for square in working_set.squares.values():
            for way in square.ways.values():
                if way.tags.get('waterway') not in LINE_KINDS or len(way.refs) < 2:
                    continue
                self.lines.append((square, way))
                for at_start, nid in ((True, way.refs[0]), (False, way.refs[-1])):
                    k = node_key(square, nid)
                    self.ends.setdefault(k, []).append((square, way, at_start))
                for nid in way.refs:
                    k = node_key(square, nid)
                    self.at.setdefault(k, []).append((square, way))
                    if nid in square.nodes:
                        self.node[k] = square.nodes[nid]
                for nid in way.refs[1:-1]:
                    self.through.add(node_key(square, nid))
        self._cells = None                   # segments by cell, built when a side is asked for
        self._joined = None                  # gaps and sides, both ways, for component
        self._free = None                    # free ends by cell, for _across

    def chain_of(self, square, way) -> Chain:
        """The non-branching sequence ``way`` belongs to, in one walking
        order: from the end of ``way`` as drawn onward, and from its start
        back, put together."""
        return self._sequence(square, way, set(), by_name=False)

    def stem_of(self, square, way, claimed=frozenset()) -> Chain:
        """The stem ``way`` belongs to - G6d-2: a chain that, at a
        confluence, carries on into the one arm with its own name. Which is
        the main stem where names settle it - 445 of the gobras set's 632
        confluences - and where they do not it stops, and the order the stems
        are graded in, longest first, decides it instead. ``claimed`` are ways
        another stem already holds; it stops short of them."""
        return self._sequence(square, way, set(claimed), by_name=True)

    def _sequence(self, square, way, claimed: set, by_name: bool) -> Chain:
        seen = claimed | {(square.name, way.id)}
        ahead, joins_a, stop_a = self._walk(square, way, False, seen, by_name)
        behind, joins_b, stop_b = self._walk(square, way, True, seen, by_name)
        # behind was walked outward from the start; turned round, it leads in
        links = [Link(s, w, not back) for s, w, back in reversed(behind)]
        links.append(Link(square, way, False))
        links += [Link(s, w, back) for s, w, back in ahead]
        joins = [Join(j.before, j.after, j.gap_m, j.lon, j.lat) for j in reversed(joins_b)] + joins_a
        return Chain(links, joins, (stop_b, stop_a))

    def _walk(self, square, way, from_start: bool, seen: set, by_name: bool = False):
        """Outward from one end of ``way``: the ways met, each with whether it
        is walked against its drawing, the gaps crossed, and why it stopped."""
        out, joins = [], []
        sq, w, start = square, way, from_start
        while True:
            nid = w.refs[0] if start else w.refs[-1]
            k = node_key(sq, nid)
            others = [(s2, w2, at) for s2, w2, at in self.ends.get(k, ())
                      if (s2.name, w2.id) != (sq.name, w.id)]
            if k in self.through:
                return out, joins, 'a line passes through'
            if len(others) > 1 and by_name and w.tags.get('name'):
                # the main stem by name: the one arm that carries it on
                same = [o for o in others if o[1].tags.get('name') == w.tags.get('name')]
                if len(same) == 1:
                    others = same
            if len(others) > 1:
                return out, joins, 'a confluence'
            if len(others) == 1:
                s2, w2, at = others[0]
                if (s2.name, w2.id) in seen:
                    return out, joins, 'it comes back on itself'
            else:
                hit = self._across(sq, w, k, seen)
                if isinstance(hit, str):
                    return out, joins, hit
                s2, w2, at, gap = hit
                here = self.node.get(k)
                joins.append(Join(w.id, w2.id, gap, here.lon if here else 0.0,
                                  here.lat if here else 0.0))
            seen.add((s2.name, w2.id))
            # walked onward from the end it was met at: met at its start, it
            # is walked as drawn; met at its end, against
            out.append((s2, w2, not at))
            sq, w, start = s2, w2, not at

    def _across(self, square, way, k, seen):
        """The one free end within the tolerance of a dangling end, or why
        there is none to cross to."""
        here = self.node.get(k)
        if here is None:
            return 'it ends'
        if self._free is None:
            # the free ends by cell - a scan of every end for each one asked
            # about was most of a network's second
            self._free = {}
            for k2, ends in self.ends.items():
                there = self.node.get(k2)
                if len(ends) == 1 and k2 not in self.through and there is not None:
                    self._free.setdefault(_cell(there), []).append(k2)
        near = []
        cx, cy = _cell(here)
        reach = int(self.tolerance_m / 100) + 1        # a cell is over 100 m at any latitude mapped
        for k2 in (k2 for dx in range(-reach, reach + 1) for dy in range(-reach, reach + 1)
                   for k2 in self._free.get((cx + dx, cy + dy), ())):
            if k2 == k:
                continue
            there = self.node[k2]
            d = _metres(here, there)
            if d <= self.tolerance_m:
                s2, w2, at = self.ends[k2][0]
                if (s2.name, w2.id) != (square.name, way.id):
                    near.append((d, s2, w2, at))
        if not near:
            return 'it ends'
        if len(near) > 1:
            return 'two pieces are in reach of its end'
        d, s2, w2, at = near[0]
        if (s2.name, w2.id) in seen:
            return 'it comes back on itself'
        a, b = way.tags.get('name'), w2.tags.get('name')
        if a and b and a != b:
            return f'{b} is in reach of its end, but is another stream'
        return s2, w2, at, round(d, 1)


def _cell(n) -> tuple[int, int]:
    return math.floor(n.lon * 500), math.floor(n.lat * 500)


def _seg_metres(here, a, b):
    """Distance in metres from a node to the segment a-b, and how far along
    it the nearest point lies, as a fraction."""
    lat = math.radians(here.lat)
    kx, ky = 111320 * math.cos(lat), 110540
    ax, ay = (a.lon - here.lon) * kx, (a.lat - here.lat) * ky
    bx, by = (b.lon - here.lon) * kx, (b.lat - here.lat) * ky
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy), t


@dataclass(frozen=True)
class Side:
    """A free end that stops short of another line's side - a tributary that
    never quite reached its river. The commonest snapping miss on the gobras
    set; joined for the grade, within the tolerance, and reported."""
    square: object
    way: object
    seg: int                  # the segment of ``way`` it is nearest, by index into refs
    t: float                  # how far along that segment
    gap_m: float


def _sides(network, square, way, end_key):
    here = network.node.get(end_key)
    if here is None:
        return []
    if network._cells is None:
        cells = {}
        for s2, w2 in network.lines:
            ns = s2.nodes
            for i, (r0, r1) in enumerate(pairwise(w2.refs)):
                if r0 in ns and r1 in ns:
                    # in every cell it crosses the box of: a segment can be a
                    # kilometre long, and an end beside one of its own ends
                    # is nowhere near its middle
                    (x0, y0), (x1, y1) = _cell(ns[r0]), _cell(ns[r1])
                    for x in range(min(x0, x1), max(x0, x1) + 1):
                        for y in range(min(y0, y1), max(y0, y1) + 1):
                            cells.setdefault((x, y), []).append((s2, w2, i))
        network._cells = cells
    cx, cy = _cell(here)
    out, seen = [], set()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for s2, w2, i in network._cells.get((cx + dx, cy + dy), ()):
                if (s2.name, w2.id) == (square.name, way.id) or (s2.name, w2.id, i) in seen:
                    continue
                seen.add((s2.name, w2.id, i))
                ns = s2.nodes
                d, t = _seg_metres(here, ns[w2.refs[i]], ns[w2.refs[i + 1]])
                if d <= network.tolerance_m:
                    out.append(Side(s2, w2, i, t, round(d, 1)))
    return out


def free_end_side(network, square, way, at_start: bool) -> Side | None:
    """Where a free end of ``way`` stops short of another line's side, if it
    does within the tolerance and at one place. None for an end that meets
    something already, or nothing, or more than one line - which is a branch
    the data does not say."""
    nid = way.refs[0] if at_start else way.refs[-1]
    k = node_key(square, nid)
    if len(network.at.get(k, ())) != 1:
        return None                      # it meets something already
    hits = _sides(network, square, way, k)
    lines = {(h.square.name, h.way.id) for h in hits}
    if len(lines) != 1:
        return None
    return min(hits, key=lambda h: h.gap_m)


def component(network, square, way) -> list:
    """Every line connected to ``way``: by a node they share, by a gap end to
    end, or by an end that stops short of another's side - the river network
    G6d-2 grades as one. The same network whichever of its lines it is asked
    from: a gap or a side reached is a link both ways, found from the free end
    that makes it, so a river finds the tributary that stops short of it."""
    if network._joined is None:
        joined: dict = {}
        for s, w in network.lines:
            a = (s.name, w.id)
            for at_start in (True, False):
                k = node_key(s, w.refs[0] if at_start else w.refs[-1])
                if len(network.at.get(k, ())) != 1:
                    continue
                hit = network._across(s, w, k, set())
                found = [] if isinstance(hit, str) else [(hit[0].name, hit[1].id)]
                side = free_end_side(network, s, w, at_start)
                if side is not None:
                    found.append((side.square.name, side.way.id))
                for b in found:
                    joined.setdefault(a, set()).add(b)
                    joined.setdefault(b, set()).add(a)
        network._joined = joined
    start = (square.name, way.id)
    lookup = {(s.name, w.id): (s, w) for s, w in network.lines}
    todo, seen = [start], {start}
    while todo:
        here = todo.pop()
        s, w = lookup[here]
        near = set(network._joined.get(here, ()))
        for nid in w.refs:
            for s2, w2 in network.at.get(node_key(s, nid), ()):
                near.add((s2.name, w2.id))
        for key in near - seen:
            if key in lookup:
                seen.add(key)
                todo.append(key)
    return [lookup[k] for k in seen]
