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


def _key(square, nid: int):
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
        for square in working_set.squares.values():
            for way in square.ways.values():
                if way.tags.get('waterway') not in LINE_KINDS or len(way.refs) < 2:
                    continue
                for at_start, nid in ((True, way.refs[0]), (False, way.refs[-1])):
                    k = _key(square, nid)
                    self.ends.setdefault(k, []).append((square, way, at_start))
                    if nid in square.nodes:
                        self.node[k] = square.nodes[nid]
                for nid in way.refs[1:-1]:
                    self.through.add(_key(square, nid))

    def chain_of(self, square, way) -> Chain:
        """The non-branching sequence ``way`` belongs to, in one walking
        order: from the end of ``way`` as drawn onward, and from its start
        back, put together."""
        seen = {(square.name, way.id)}
        ahead, joins_a, stop_a = self._walk(square, way, False, seen)
        behind, joins_b, stop_b = self._walk(square, way, True, seen)
        # behind was walked outward from the start; turned round, it leads in
        links = [Link(s, w, not back) for s, w, back in reversed(behind)]
        links.append(Link(square, way, False))
        links += [Link(s, w, back) for s, w, back in ahead]
        joins = [Join(j.before, j.after, j.gap_m, j.lon, j.lat) for j in reversed(joins_b)] + joins_a
        return Chain(links, joins, (stop_b, stop_a))

    def _walk(self, square, way, from_start: bool, seen: set):
        """Outward from one end of ``way``: the ways met, each with whether it
        is walked against its drawing, the gaps crossed, and why it stopped."""
        out, joins = [], []
        sq, w, start = square, way, from_start
        while True:
            nid = w.refs[0] if start else w.refs[-1]
            k = _key(sq, nid)
            others = [(s2, w2, at) for s2, w2, at in self.ends.get(k, ())
                      if (s2.name, w2.id) != (sq.name, w.id)]
            if k in self.through:
                return out, joins, 'a line passes through'
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
        near = []
        for k2, ends in self.ends.items():
            if k2 == k or len(ends) != 1 or k2 in self.through:
                continue
            there = self.node.get(k2)
            if there is None or abs(there.lat - here.lat) > 0.001:
                continue
            d = _metres(here, there)
            if d <= self.tolerance_m:
                s2, w2, at = ends[0]
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
