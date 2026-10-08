"""Editing a square: commands with inverses, on an undo stack.

Every change to a Square goes through a Command, and every Command can take
itself back exactly - R17 asks for undo and redo across every operation,
including the compound ones, and the property test asks that an edit followed
by its undo restores the working set exactly, node for node and tag for tag.
Nothing here knows about Qt; the tools in the editor build commands and hand
them to the stack.

Ids are negative and unique within the file, allocated below the lowest the
square holds - R4, as corrected: a square is edited, sent and built as one
file, and JOSM treats a negative id the same way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .reconcile import Reconciled, reconcile
from .square import Member, Node, Relation, Square, Way

Coord = tuple[float, float]            # lon, lat


# ------------------------------------------------------------------ ids

class IdAllocator:
    """Fresh negative ids, each below the lowest in use. Nodes, ways and
    relations are three namespaces in OSM, but one counter over all of them
    keeps a file readable by eye and cannot collide with any.

    Below the lowest in every square it has been shown, not just the first.
    One counter per square mints -1 for each of them - the lowest id in a
    square drawn from real data is positive, so -1 is what every such square
    offers first - and a working set is many squares. Two contours drawn in
    two squares then share an id, which is harmless while nothing indexes on
    it and is not once something does: the preview keys a way's last geometry
    on it, and the GeoPackage a build collects writes it as `osm_id`, so a
    saved set already produced two features claiming to be the same way.
    """

    def __init__(self, square: Square):
        self._next = 0
        self.include(square)

    def include(self, square: Square) -> None:
        """Take this square's ids into account as well."""
        lowest = min([0, *square.nodes.keys(), *square.ways.keys(), *square.relations.keys()])
        # lowest is at most 0, so this is the whole of it: the counter only
        # ever moves down, and a square whose ids are all above it changes
        # nothing
        self._next = min(self._next, lowest - 1)

    def take(self) -> int:
        i = self._next
        self._next -= 1
        return i

    def peek(self) -> int:
        return self._next


# ------------------------------------------------------------ commands

class Command:
    """Apply and take back, exactly. Subclasses hold everything they need to
    do both, so a command is replayable after any number of other commands
    have been undone and redone around it."""

    def apply(self, square: Square) -> None:
        raise NotImplementedError

    def undo(self, square: Square) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        return type(self).__name__

    def ways(self, square: Square) -> set[int]:
        """The ways this command changes, adds or removes - what a view has
        to redraw. Asked before apply and after undo alike, so it answers
        from the command's own fields, not from what the square holds."""
        raise NotImplementedError

    def spots(self, square: Square) -> set[int]:
        """The nodes whose standing as a constraint this command may change -
        R36's spot heights, a node carrying ``ele``.

        *May*, and not *does*: like ``ways`` this is answered from the
        command's own fields, and a command that moves a node does not know
        whether that node is a spot height, a vertex of a contour or neither.
        It names the node and the caller asks the square, which is what
        ``ways`` already makes the preview do with a way that may or may not
        carry an elevation.

        Empty by default, because most commands are about ways and the ones
        that are not say so."""
        return set()


def ways_holding(square: Square, node_id: int) -> set[int]:
    """The ways of a square that reference a node."""
    return {wid for wid, w in square.ways.items() if node_id in w.refs}


@dataclass
class AddWay(Command):
    """A new way through new nodes, tagged - a contour drawn at an elevation."""
    way_id: int
    node_ids: list[int]
    coords: list[Coord]
    tags: dict[str, str]

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        for nid, (lon, lat) in zip(self.node_ids, self.coords, strict=True):
            square.nodes[nid] = Node(id=nid, lat=lat, lon=lon)
        square.ways[self.way_id] = Way(id=self.way_id, refs=list(self.node_ids), tags=dict(self.tags))

    def undo(self, square: Square) -> None:
        del square.ways[self.way_id]
        for nid in self.node_ids:
            del square.nodes[nid]

    def describe(self) -> str:
        return f'draw {self.tags.get("ele", "?")} m, {len(self.node_ids)} nodes'


@dataclass
class ExtendWay(Command):
    """A new node appended at one end of an existing way - continuing it."""
    way_id: int
    at_end: bool
    node_id: int
    coord: Coord

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        lon, lat = self.coord
        square.nodes[self.node_id] = Node(id=self.node_id, lat=lat, lon=lon)
        refs = square.ways[self.way_id].refs
        refs.append(self.node_id) if self.at_end else refs.insert(0, self.node_id)

    def undo(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        refs.pop() if self.at_end else refs.pop(0)
        del square.nodes[self.node_id]

    def describe(self) -> str:
        return 'continue'


@dataclass
class ExtendWayWithExisting(Command):
    """An existing node joined to one end of a way - snapping a continuation
    onto a node already there. The node is shared, not copied."""
    way_id: int
    at_end: bool
    node_id: int

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        refs.append(self.node_id) if self.at_end else refs.insert(0, self.node_id)

    def undo(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        refs.pop() if self.at_end else refs.pop(0)

    def describe(self) -> str:
        return 'join'


@dataclass
class AddNode(Command):
    """A node of its own, tagged - a spot height, which is the only kind of
    node that means anything without a way around it.

    Not ``InsertNode``, which puts a vertex into an existing way. This one
    belongs to nothing: R37 says a spot height is the only thing that can say
    how high a hill goes, and the hill's contours are already drawn."""
    node_id: int
    coord: Coord
    tags: dict[str, str] = field(default_factory=dict)

    def ways(self, square: Square) -> set[int]:
        return set()

    def spots(self, square: Square) -> set[int]:
        return {self.node_id}

    def apply(self, square: Square) -> None:
        lon, lat = self.coord
        square.nodes[self.node_id] = Node(id=self.node_id, lat=lat, lon=lon,
                                          tags=dict(self.tags))

    def undo(self, square: Square) -> None:
        del square.nodes[self.node_id]

    def describe(self) -> str:
        ele = self.tags.get('ele')
        return f'spot height at {ele} m' if ele else 'add node'


@dataclass
class SetNodeTags(Command):
    """A node's tags replaced - a spot height's elevation changed, most
    often, and the way a node becomes or stops being one."""
    node_id: int
    before: dict[str, str]
    after: dict[str, str]

    def ways(self, square: Square) -> set[int]:
        return ways_holding(square, self.node_id)

    def spots(self, square: Square) -> set[int]:
        return {self.node_id}

    def apply(self, square: Square) -> None:
        square.nodes[self.node_id].tags = dict(self.after)

    def undo(self, square: Square) -> None:
        square.nodes[self.node_id].tags = dict(self.before)

    def describe(self) -> str:
        a, b = self.before.get('ele'), self.after.get('ele')
        return f'{a} m -> {b} m' if a != b else 'retag node'


@dataclass
class InsertNode(Command):
    """A new node inserted into a way at an index, between two existing."""
    way_id: int
    index: int
    node_id: int
    coord: Coord

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        lon, lat = self.coord
        square.nodes[self.node_id] = Node(id=self.node_id, lat=lat, lon=lon)
        square.ways[self.way_id].refs.insert(self.index, self.node_id)

    def undo(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        assert refs[self.index] == self.node_id
        del refs[self.index]
        del square.nodes[self.node_id]

    def describe(self) -> str:
        return 'insert node'


@dataclass
class MoveNode(Command):
    node_id: int
    before: Coord
    after: Coord

    def ways(self, square: Square) -> set[int]:
        return ways_holding(square, self.node_id)

    def spots(self, square: Square) -> set[int]:
        return {self.node_id}

    def apply(self, square: Square) -> None:
        n = square.nodes[self.node_id]
        n.lon, n.lat = self.after

    def undo(self, square: Square) -> None:
        n = square.nodes[self.node_id]
        n.lon, n.lat = self.before

    def describe(self) -> str:
        return 'move node'


@dataclass
class TranslateWay(Command):
    """A whole way moved - G8b: a contour drawn in the wrong place, its shape
    right, put where it belongs as one step.

    ``moves`` holds the way's own nodes, before and after. A node the way
    shares with another is not moved, which would drag the other with it:
    the way takes a copy at the new place instead (``copies``, old id to new
    id and place), and leaves the other way where it was - a misplaced
    contour moved away from the contours it was snapped to comes away from
    them."""
    way_id: int
    moves: dict[int, tuple[Coord, Coord]]
    copies: dict[int, tuple[int, Coord]]

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def spots(self, square: Square) -> set[int]:
        # what it writes: the nodes it moves and the copies it makes; a
        # shared node it copied from is left as it was
        return set(self.moves) | {new for new, _ in self.copies.values()}

    def apply(self, square: Square) -> None:
        for nid, (_, (lon, lat)) in self.moves.items():
            n = square.nodes[nid]
            n.lon, n.lat = lon, lat
        for new, (lon, lat) in self.copies.values():
            square.nodes[new] = Node(id=new, lat=lat, lon=lon)
        way = square.ways[self.way_id]
        way.refs = [self.copies[r][0] if r in self.copies else r for r in way.refs]

    def undo(self, square: Square) -> None:
        back = {new: old for old, (new, _) in self.copies.items()}
        way = square.ways[self.way_id]
        way.refs = [back.get(r, r) for r in way.refs]
        for new in back:
            del square.nodes[new]
        for nid, ((lon, lat), _) in self.moves.items():
            n = square.nodes[nid]
            n.lon, n.lat = lon, lat

    def describe(self) -> str:
        return 'move contour'


def translate_way(square: Square, way_id: int, move, alloc: IdAllocator) -> TranslateWay:
    """The command that moves a way by ``move`` - a function from a node's
    (lon, lat) to where it goes - copying the nodes it shares with another
    way rather than moving them."""
    way = square.ways[way_id]
    moves, copies = {}, {}
    for r in dict.fromkeys(way.refs):          # a ring's first node once
        n = square.nodes[r]
        to = move(n.lon, n.lat)
        if ways_holding(square, r) - {way_id}:
            copies[r] = (alloc.take(), to)
        else:
            moves[r] = ((n.lon, n.lat), to)
    return TranslateWay(way_id, moves, copies)


SPLIT_GAP_M = 5.0


def _back(square: Square, frm: int, toward: int, metres: float):
    """The point ``metres`` from node ``frm`` along the line to ``toward`` -
    at most a third of the way, so a short segment keeps a stretch."""
    a, b = square.nodes[frm], square.nodes[toward]
    kx = 111320.0 * math.cos(math.radians(a.lat))
    length = math.hypot((b.lon - a.lon) * kx, (b.lat - a.lat) * 110540.0)
    t = min(metres / length, 1 / 3) if length > 0 else 0.0
    return a.lon + (b.lon - a.lon) * t, a.lat + (b.lat - a.lat) * t


def split_way(square: Square, way_id: int, node_id: int, alloc: IdAllocator,
              gap_m: float = SPLIT_GAP_M) -> ReplaceWay | str:
    """A way split at one of its nodes, the two new ends unglued and drawn
    back ``gap_m`` along their own lines, so they come apart where a mapper
    can see and take hold of them. An open way becomes two, the first
    keeping its id; a closed one opens into one line from the node round to
    it. The node itself goes, unless another way holds it. Why not, as a
    string."""
    way = square.ways.get(way_id)
    if way is None:
        return 'that way is no longer there'
    refs = way.refs
    if node_id not in refs:
        return 'that node is not on it'
    closed = refs[0] == refs[-1] and len(refs) > 3
    if (refs[:-1] if closed else refs).count(node_id) > 1:
        return 'it passes through that node twice - cut out the loop first'
    if closed:
        k = refs.index(node_id)
        line = refs[k:-1] + refs[:k] + [node_id]           # from the node round to it
        n1, n2 = alloc.take(), alloc.take()
        new = {n1: _back(square, node_id, line[1], gap_m), n2: _back(square, node_id, line[-2], gap_m)}
        return ReplaceWay(way_id, [(way_id, [n1, *line[1:-1], n2])], new)
    k = refs.index(node_id)
    if k in (0, len(refs) - 1):
        return 'that is an end already'
    n1, n2 = alloc.take(), alloc.take()
    new = {n1: _back(square, node_id, refs[k - 1], gap_m), n2: _back(square, node_id, refs[k + 1], gap_m)}
    return ReplaceWay(way_id, [(way_id, [*refs[:k], n1]), (alloc.take(), [n2, *refs[k + 1:]])], new)


def unglue_node(square: Square, way_id: int, node_id: int, alloc: IdAllocator,
                gap_m: float = SPLIT_GAP_M) -> Command | str:
    """A node shared by several ways, left to ``way_id`` alone - G8e. Each
    other way holding it gets a node of its own, drawn ``gap_m`` from it into
    its own bend - toward the middle of its two neighbours - so the contours
    come apart where they met, a third of the way there at most. A way that
    runs straight through the node is moved square to its line, away from the
    way that keeps it. Why not, as a string."""
    way = square.ways.get(way_id)
    if way is None or node_id not in way.refs:
        return 'that node is not on the way selected'
    others = sorted(ways_holding(square, node_id) - {way_id})
    if not others:
        return 'no other way holds that node'
    n = square.nodes[node_id]
    kx = 111320.0 * math.cos(math.radians(n.lat))
    k = (kx, 110540.0)

    def neighbours(refs):
        """The node's neighbours along a way, in metres from it - a ring's
        closing node has one at each end of its refs."""
        out = []
        for i, r in enumerate(refs):
            if r != node_id:
                continue
            for j in (i - 1, i + 1):
                if 0 <= j < len(refs) and refs[j] != node_id:
                    m = square.nodes[refs[j]]
                    out.append(((m.lon - n.lon) * k[0], (m.lat - n.lat) * k[1]))
        return out
    mine = neighbours(way.refs)
    steps = []
    for oid in others:
        refs = list(square.ways[oid].refs)
        near = neighbours(refs)
        mx = sum(p[0] for p in near) / len(near) if near else 0.0
        my = sum(p[1] for p in near) / len(near) if near else 0.0
        length = math.hypot(mx, my)
        if length < 1e-3 and len(near) >= 2:
            # straight through: square to its line, away from the way kept
            dx, dy = near[0][0] - near[-1][0], near[0][1] - near[-1][1]
            ux, uy = -dy, dx
            norm = math.hypot(ux, uy) or 1.0
            ux, uy = ux / norm, uy / norm
            if mine and sum(ux * p[0] + uy * p[1] for p in mine) > 0:
                ux, uy = -ux, -uy
            d = gap_m
        else:
            ux, uy = (mx / length, my / length) if length else (1.0, 0.0)
            d = min(gap_m, length / 3) if near else gap_m
        nid = alloc.take()
        to = (n.lon + ux * d / k[0], n.lat + uy * d / k[1])
        steps.append(ReplaceWay(oid, [(oid, [nid if r == node_id else r for r in refs])], {nid: to}))
    return Compound(steps, name='unglue')


def join_ways(square: Square, way_id: int, end: int, other_id: int, onto: int) -> Command | str:
    """A way's end ``end`` put onto ``onto``, an end of ``other_id`` - or the
    way's own other end, which closes it. The two become one way, keeping
    the first's id; the dragged end goes, unless another way holds it. Why
    not, as a string."""
    way, other = square.ways.get(way_id), square.ways.get(other_id)
    if way is None or other is None:
        return 'that way is no longer there'
    for w, n in ((way, end), (other, onto)):
        if w.refs[0] == w.refs[-1]:
            return 'a closed contour has no end to join'
        if n not in (w.refs[0], w.refs[-1]):
            return 'only an end joins - that node is in the middle of its contour'
    if way.tags.get('ele') != other.tags.get('ele'):
        return f'the levels differ - {way.tags.get("ele")} m and {other.tags.get("ele")} m'
    clash = sorted(k for k in set(way.tags) & set(other.tags) if way.tags[k] != other.tags[k])
    if clash:
        return f'their tags differ - {clash[0]}: {way.tags[clash[0]]} and {other.tags[clash[0]]}'
    mine = list(way.refs) if way.refs[-1] == end else list(reversed(way.refs))
    if way_id == other_id:
        if len(mine) < 4:
            return 'too short to close'
        return ReplaceWay(way_id, [(way_id, [*mine[:-1], mine[0]])], {})
    theirs = list(other.refs) if other.refs[0] == onto else list(reversed(other.refs))
    # the tags of both, neither's lost: they agree where they share a key
    steps = [ReplaceWay(way_id, [(way_id, [*mine[:-1], *theirs])], {}), DeleteWay(other_id)]
    if set(other.tags) - set(way.tags):
        steps.append(SetTags(way_id, dict(way.tags), {**other.tags, **way.tags}))
    return Compound(steps, name='join')


@dataclass
class DeleteNode(Command):
    """A node removed from every way that references it, and from the square.
    A way left with one node is removed too, as part of the same command, so
    the file never holds a way that is not a line. Everything removed is kept
    for the undo, with the positions the refs sat at."""
    node_id: int
    node: Node | None = None
    positions: dict[int, list[int]] = field(default_factory=dict)    # way -> indexes held
    removed_ways: dict[int, Way] = field(default_factory=dict)

    def ways(self, square: Square) -> set[int]:
        return ways_holding(square, self.node_id) | set(self.positions) | set(self.removed_ways)

    def spots(self, square: Square) -> set[int]:
        return {self.node_id}

    def apply(self, square: Square) -> None:
        self.node = square.nodes.pop(self.node_id)
        self.positions, self.removed_ways = {}, {}
        for wid, way in list(square.ways.items()):
            idx = [i for i, r in enumerate(way.refs) if r == self.node_id]
            if not idx:
                continue
            self.positions[wid] = idx
            way.refs = [r for r in way.refs if r != self.node_id]
            if len(way.refs) < 2:
                self.removed_ways[wid] = square.ways.pop(wid)

    def undo(self, square: Square) -> None:
        square.nodes[self.node_id] = self.node
        for wid, way in self.removed_ways.items():
            square.ways[wid] = way
        for wid, idx in self.positions.items():
            refs = square.ways[wid].refs
            for i in idx:                       # ascending, so each index is right when reached
                refs.insert(i, self.node_id)

    def describe(self) -> str:
        return 'delete node'


@dataclass
class DeleteWay(Command):
    """A way removed, and with it the nodes nothing else references."""
    way_id: int
    way: Way | None = None
    orphans: dict[int, Node] = field(default_factory=dict)

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        self.way = square.ways.pop(self.way_id)
        still_used = {r for w in square.ways.values() for r in w.refs}
        self.orphans = {}
        for r in self.way.refs:
            if r not in still_used and r in square.nodes:
                self.orphans[r] = square.nodes.pop(r)

    def undo(self, square: Square) -> None:
        square.nodes.update(self.orphans)
        square.ways[self.way_id] = self.way

    def describe(self) -> str:
        return f'delete way {self.way.tags.get("ele", "") if self.way else ""}'.strip()


@dataclass
class ReplaceWay(Command):
    """A way replaced by pieces through its own nodes and new ones - a contour
    clipped at a lake's shore, or bent back from a river (G7). No pieces is
    the way removed. Nodes the way held that nothing references afterwards go
    with it, as ``DeleteWay``'s orphans do, and everything is kept for the
    undo. The tags are the way's, on every piece; the first piece may keep
    the way's own id."""
    way_id: int
    pieces: list[tuple[int, list[int]]]
    new_nodes: dict[int, Coord]
    original: Way | None = None
    orphans: dict[int, Node] = field(default_factory=dict)

    def ways(self, square: Square) -> set[int]:
        return {self.way_id, *(wid for wid, _ in self.pieces)}

    def apply(self, square: Square) -> None:
        self.original = square.ways.pop(self.way_id)
        for nid, (lon, lat) in self.new_nodes.items():
            square.nodes[nid] = Node(id=nid, lat=lat, lon=lon)
        for wid, refs in self.pieces:
            square.ways[wid] = Way(id=wid, refs=list(refs), tags=dict(self.original.tags))
        still_used = {r for w in square.ways.values() for r in w.refs}
        self.orphans = {r: square.nodes.pop(r) for r in dict.fromkeys(self.original.refs)
                        if r not in still_used and r in square.nodes}

    def undo(self, square: Square) -> None:
        for wid, _ in self.pieces:
            del square.ways[wid]
        for nid in self.new_nodes:
            del square.nodes[nid]
        square.nodes.update(self.orphans)
        square.ways[self.way_id] = self.original
        self.orphans = {}

    def describe(self) -> str:
        ele = self.original.tags.get('ele', '') if self.original else ''
        return f'reshape {ele} m contour' if self.pieces else f'remove {ele} m contour'


@dataclass
class SetNodeLevels(Command):
    """Many vertices' tags replaced as one step - a graded river's levels
    (G6b), and Ctrl+Z takes the whole grade back.

    Not a ``Compound`` of ``SetNodeTags``: each of those answers ``ways()``
    by scanning every way in the square for the one node it names, and a
    grade names hundreds. The ways they are vertices of are known here - one
    for a river, several for a chain (G6d) - and are the only ways to redraw:
    their shape has not changed, their levels have.
    """
    changes: dict[int, tuple[dict, dict]]      # node id -> (tags before, after)
    way_ids: tuple[int, ...] = ()               # the ways they are vertices of, to redraw
    name: str = 'set levels'

    def ways(self, square: Square) -> set[int]:
        return set(self.way_ids)

    def spots(self, square: Square) -> set[int]:
        return set(self.changes)

    def apply(self, square: Square) -> None:
        for nid, (_, after) in self.changes.items():
            square.nodes[nid].tags = dict(after)

    def undo(self, square: Square) -> None:
        for nid, (before, _) in self.changes.items():
            square.nodes[nid].tags = dict(before)

    def describe(self) -> str:
        return self.name


@dataclass
class SetRelationTags(Command):
    """A relation's tags replaced - a lake's level set, most often (G6a).

    ``ways()`` names the members, as ``DeleteRelation`` does and for the same
    reason: the layer draws a lake's level on the lake, and the lake is
    rebuilt from the ways the relation names - a change to the relation alone
    names no way, so without them the level on the canvas would be the old
    one until something else touched the lake."""
    relation_id: int
    before: dict[str, str]
    after: dict[str, str]

    def ways(self, square: Square) -> set[int]:
        rel = square.relations.get(self.relation_id)
        return {m.ref for m in rel.members if m.type == 'way'} if rel else set()

    def apply(self, square: Square) -> None:
        square.relations[self.relation_id].tags = dict(self.after)

    def undo(self, square: Square) -> None:
        square.relations[self.relation_id].tags = dict(self.before)

    def describe(self) -> str:
        a, b = self.before.get('ele'), self.after.get('ele')
        return f'{a} m -> {b} m' if a != b else 'retag relation'


@dataclass
class DeleteRelation(Command):
    """A relation removed - the relation alone. ``delete_relation`` is what
    a mapper means by deleting a lake, and builds this into a step with the
    rings that go with it."""
    relation_id: int
    relation: Relation | None = None

    def ways(self, square: Square) -> set[int]:
        """Its member ways, which are drawn as water - filled, outlined - only
        because the relation said so. Gone, they are drawn as what they are on
        their own account, and the layer has to be told to look again."""
        rel = self.relation or square.relations.get(self.relation_id)
        return {m.ref for m in rel.members if m.type == 'way'} if rel else set()

    def apply(self, square: Square) -> None:
        self.relation = square.relations.pop(self.relation_id)

    def undo(self, square: Square) -> None:
        square.relations[self.relation_id] = self.relation

    def describe(self) -> str:
        name = self.relation.tags.get('name') if self.relation else None
        return f'delete relation {name}' if name else 'delete relation'


def delete_relation(square: Square, relation_id: int) -> Compound:
    """A relation and the member ways that are nothing without it, as one step.

    A lake's ring carries no tags; the relation holds them. Delete the
    relation alone and the ring is left as an untagged line that nothing
    names - the very thing G5b reports as junk on the next import. So a ring
    goes with its relation when it is untagged and no other relation in the
    square names it. A tagged ring is a feature in its own right, and a ring
    another relation also names - a lake sharing a shore with a riverbank -
    still has a use; both stay.
    """
    rel = square.relations[relation_id]
    others = {m.ref for r in square.relations.values() if r.id != relation_id
              for m in r.members if m.type == 'way'}
    rings = []
    for m in rel.members:
        if m.type != 'way' or m.ref in others or m.ref in rings:
            continue
        way = square.ways.get(m.ref)
        if way is not None and not way.tags:
            rings.append(m.ref)
    name = rel.tags.get('name')
    return Compound([DeleteRelation(relation_id), *(DeleteWay(w) for w in rings)],
                    name=f'delete {name}' if name else 'delete relation')


def rotate_ring(refs: list[int], by: int) -> list[int]:
    """A closed way's refs turned so another of its nodes leads. The same ring
    through the same ground; only where it is cut open moves."""
    body = refs[:-1]
    if not body:                     # not reachable through the tools: a closed way
        return list(refs)            # has at least one node. rotate_ring is public
    by %= len(body)
    out = body[by:] + body[:by]
    return out + [out[0]]


@dataclass
class RotateRing(Command):
    """Turn a closed way so a stretch that straddles its join becomes one run
    of consecutive refs, which is the shape ReplaceSection swaps. Any run it
    does not straddle needs no turning.

    The same ring through the same ground, so the build reads the same
    surface from it: measured on the golden square with all 25 of its rings
    turned a third of the way round, 0 of 1,442,401 cells differ.

    Contours only. A way's direction means nothing for these, but a
    ``natural=coastline`` carries the land on its left and the sea on its
    right - ``danu.surface.build.water_mask`` reads the sea from it - so
    turning one would move the shore. The editor keeps them out by asking a
    redraw's target for the elevation being drawn at, which a coastline has
    not got."""
    way_id: int
    by: int

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        way = square.ways[self.way_id]
        way.refs[:] = rotate_ring(way.refs, self.by)

    def undo(self, square: Square) -> None:
        way = square.ways[self.way_id]
        way.refs[:] = rotate_ring(way.refs, -self.by)

    def describe(self) -> str:
        return 'turn a ring'


@dataclass
class ReplaceSection(Command):
    """The stretch of a way between two of its own nodes, swapped for another
    run - a contour redrawn between two points of itself.

    ``refs`` carries both ends, which are the way's own nodes and stay; what
    lay between them goes, and any node of it the square no longer uses goes
    with it. The way keeps its id, its tags and its direction, so what the
    build reads is the same contour with a different middle."""
    way_id: int
    start: int                                        # index into refs, start < end
    end: int
    refs: list[int]                                   # the replacement, both ends included
    old: list[int] = field(default_factory=list)
    orphans: dict[int, Node] = field(default_factory=dict)

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        way = square.ways[self.way_id]
        self.old = way.refs[self.start:self.end + 1]
        way.refs[self.start:self.end + 1] = list(self.refs)
        used = {r for w in square.ways.values() for r in w.refs}
        self.orphans = {nid: square.nodes.pop(nid) for nid in self.old
                        if nid not in used and nid in square.nodes}

    def undo(self, square: Square) -> None:
        way = square.ways[self.way_id]
        way.refs[self.start:self.start + len(self.refs)] = list(self.old)
        square.nodes.update(self.orphans)
        self.orphans = {}

    def describe(self) -> str:
        if not self.old:                         # asked before it has been applied
            return f'redraw a stretch as {len(self.refs) - 2} nodes'
        return f'redraw {len(self.old) - 2} nodes as {len(self.refs) - 2}'


@dataclass
class SetTags(Command):
    """A way's tags replaced - the elevation changed, most often."""
    way_id: int
    before: dict[str, str]
    after: dict[str, str]

    def ways(self, square: Square) -> set[int]:
        return {self.way_id}

    def apply(self, square: Square) -> None:
        square.ways[self.way_id].tags = dict(self.after)

    def undo(self, square: Square) -> None:
        square.ways[self.way_id].tags = dict(self.before)

    def describe(self) -> str:
        a, b = self.before.get('ele'), self.after.get('ele')
        return f'{a} m -> {b} m' if a != b else 'retag'


@dataclass
class ImportWater(Command):
    """One import's features into one square, as one step on the history.

    R40 asks for that in as many words - *an import is one undoable step* -
    and the reason is not tidiness. An import writes hundreds of features at
    once over somebody's file; the answer to a bad one has to be Ctrl+Z and
    not an afternoon.

    What it writes is the import *reconciled* with the square - G5a, and
    ``danu/core/reconcile.py`` for the rule. A feature the square already
    holds takes its geometry from upstream and keeps the elevation set on it
    here; until G5a a second import overwrote it whole, which took itself back
    exactly and threw away every elevation set since the first. The merge is
    worked out when the step is applied, against the square as it then is, so
    a redo after an undo works it out again against the square the undo put
    back - the same square, and so the same answer.

    ``upstream_owns`` has no default. It is the line between what upstream is
    the authority for and what the mapper is, and an import that did not say
    where it fell would be making the choice silently - so every caller says.

    The fields are ``new_*`` and not ``nodes``/``ways``/``relations`` because
    a dataclass field named ``ways`` would shadow the ``ways()`` every command
    owes its caller - the instance attribute wins the lookup, and
    ``cmd.ways(square)`` becomes an attempt to call a dict.

    There is no ``relations()`` beside ``ways()`` and ``spots()`` because
    nothing asks for one: the preview burns contours and spot heights, and the
    canvas draws them. A relation is carried and saved and not yet drawn, so
    adding the accessor now would be guessing at what its caller wants.
    """
    upstream_owns: tuple[str, ...]
    new_nodes: dict[int, Node] = field(default_factory=dict)
    new_ways: dict[int, Way] = field(default_factory=dict)
    new_relations: dict[int, Relation] = field(default_factory=dict)
    name: str = 'import water'
    # what the square held at each id before, or None where it held nothing
    before: dict = field(default_factory=dict)
    # what was written: the reconciled features, the vertices a re-route left
    # behind, and the local ways a moved shared node redraws. The last two are
    # kept across an undo, because the driver asks ways() and spots() *after*
    # the undo to know what to redraw, and the answer is the same set
    written: Reconciled | None = field(default=None, repr=False)
    moved: set[int] = field(default_factory=set, repr=False)
    _spots: set[int] | None = field(default=None, repr=False)

    def ways(self, square: Square) -> set[int]:
        # the ways it writes, and the local ones a node it moved redraws - a
        # contour snapped to a river goes where the river goes
        return set(self.new_ways) | self.moved

    def spots(self, square: Square) -> set[int]:
        """The nodes that carry an elevation, not every node imported.

        ``spots`` is answered from the command's own fields, and here those
        fields *are* the nodes - so unlike ``MoveNode``, which names a node
        and lets the driver ask the square, this one can tell. It has to: a
        river network is 158,633 vertices on the gobras set and the driver
        walks this on the UI thread, where a hundred and fifty thousand
        no-ops is a stall rather than a saving.

        Once applied, the answer is the elevation-carrying nodes among what
        was *written* - which a held vertex's own `ele` can add to - and it is
        kept across an undo on purpose: the driver asks after the undo to know
        what to redraw, and the nodes the import touched are the ones that
        moved back. It is the import's set, not a fresh look at the square.
        """
        if self._spots is not None:
            return self._spots
        return {i for i, n in self.new_nodes.items() if 'ele' in n.tags}

    def apply(self, square: Square) -> None:
        if self.before:
            # captured once. The stack's undo-then-redo puts the square back
            # before this runs again, so re-snapshotting would give the same
            # answer - but only because of the order the caller happens to
            # use, and a command owns its own invariant: applied twice with
            # no undo between, a second snapshot would record the import and
            # the original would be gone
            self._write(square, self.written)
            return
        w = reconcile(square, self.new_nodes, self.new_ways, self.new_relations,
                      self.upstream_owns)
        self.before = {
            'nodes': {i: square.nodes.get(i) for i in (*w.nodes, *w.removed)},
            'ways': {i: square.ways.get(i) for i in w.ways},
            'relations': {i: square.relations.get(i) for i in w.relations},
        }
        self.written, self.moved = w, w.moved
        # the spot heights among what was written, which is not always what
        # was given: a vertex the mapper put an `ele` on keeps it, and a
        # vertex upstream moved that carries one has to be redrawn where it
        # went
        self._spots = {i for i, n in w.nodes.items() if 'ele' in n.tags}
        self._write(square, w)

    @staticmethod
    def _write(square: Square, w: Reconciled) -> None:
        square.nodes.update(w.nodes)
        square.ways.update(w.ways)
        square.relations.update(w.relations)
        for i in w.removed:
            square.nodes.pop(i, None)

    def undo(self, square: Square) -> None:
        for kind, holder in (('nodes', square.nodes), ('ways', square.ways),
                             ('relations', square.relations)):
            for i, was in self.before.get(kind, {}).items():
                if was is None:
                    holder.pop(i, None)
                else:
                    holder[i] = was
        # `written` goes with the snapshot, so a redo works the merge out
        # afresh; `moved` and the spots stay, because the driver asks for them
        # after this returns to know what the undo just moved back
        self.before, self.written = {}, None

    def describe(self) -> str:
        # ways and relations, not nodes, which is what a feature is here and
        # in ``overpass.Water.__len__``: a river of a thousand vertices is one
        # thing a mapper imported, and saying 158,633 would be true and useless
        return f'{self.name}: {len(self.new_ways) + len(self.new_relations)} features'


@dataclass
class Compound(Command):
    """Several commands as one step of undo. Applied in order, undone in
    reverse; the operations of phase 5 - burn a river, flatten a body - are
    compounds, and so is splitting a long way on save."""
    commands: list[Command]
    name: str = 'compound'

    def ways(self, square: Square) -> set[int]:
        return set().union(*(c.ways(square) for c in self.commands)) if self.commands else set()

    def spots(self, square: Square) -> set[int]:
        return set().union(*(c.spots(square) for c in self.commands)) if self.commands else set()

    def apply(self, square: Square) -> None:
        for c in self.commands:
            c.apply(square)

    def undo(self, square: Square) -> None:
        for c in reversed(self.commands):
            c.undo(square)

    def describe(self) -> str:
        return self.name


# ---------------------------------------------------------------- split

def split_long_ways(square: Square, alloc: IdAllocator, limit: int = 2000) -> Compound | None:
    """The command that splits every way over ``limit`` nodes into pieces of
    at most ``limit``, consecutive pieces sharing their boundary node, tags
    copied to each, direction kept - exactly as danu.core.split_long_ways does
    to a file, and a test holds the two equal. The first piece keeps the
    way's id; the rest take fresh ones. None when nothing is over the limit.

    On save rather than on every edit: the OSM API refuses a way over 2,000
    nodes, so that is the rule the file has to satisfy, and GDAL drops one
    over 10,000 silently, which is the rule that bites."""
    cmds: list[Command] = []
    for wid in sorted(square.ways):
        way = square.ways[wid]
        n = len(way.refs)
        if n <= limit:
            continue
        step = limit - 1
        pieces = [way.refs[s:s + limit] for s in range(0, n - 1, step)]
        new_ids = [wid] + [alloc.take() for _ in pieces[1:]]
        cmds.append(_ReplaceWays(wid, way, [(nid, refs, dict(way.tags)) for nid, refs in zip(new_ids, pieces, strict=True)]))
    if not cmds:
        return None
    return Compound(cmds, name=f'split {len(cmds)} long way(s)')


@dataclass
class _ReplaceWays(Command):
    """One way replaced by several over the same nodes; the inverse of a split.

    Any relation that named the way is mended as part of the same command: the
    member is replaced by one per piece, in order and with the same role.
    Without that, a split takes a lake's outer ring down to its first two
    thousand nodes and leaves the rest of the ring in the file belonging to
    nothing - a hole in the shape, written on save, and nothing said. The
    whole relation's member list is kept for the undo rather than the one
    member, because restoring a list exactly is the only way to be sure.
    """
    way_id: int
    original: Way
    pieces: list[tuple[int, list[int], dict[str, str]]]
    members: dict[int, list[Member]] = field(default_factory=dict)   # relation -> as it was

    def ways(self, square: Square) -> set[int]:
        return {self.way_id, *(nid for nid, _, _ in self.pieces)}

    def apply(self, square: Square) -> None:
        del square.ways[self.way_id]
        for nid, refs, tags in self.pieces:
            square.ways[nid] = Way(id=nid, refs=list(refs), tags=tags)
        self.members = {}
        for rid, rel in square.relations.items():
            if not any(m.type == 'way' and m.ref == self.way_id for m in rel.members):
                continue
            self.members[rid] = list(rel.members)
            mended: list[Member] = []
            for m in rel.members:
                if m.type == 'way' and m.ref == self.way_id:
                    mended += [Member('way', nid, m.role) for nid, _, _ in self.pieces]
                else:
                    mended.append(m)
            rel.members = mended

    def undo(self, square: Square) -> None:
        for nid, _, _ in self.pieces:
            del square.ways[nid]
        square.ways[self.way_id] = self.original
        for rid, was in self.members.items():
            if rid in square.relations:
                # nothing deletes a relation yet - that is G4's - but a
                # command does not get to assume what ran after it
                square.relations[rid].members = list(was)
        self.members = {}

    def describe(self) -> str:
        return f'split way {self.way_id} into {len(self.pieces)}'


# ----------------------------------------------------------------- stack

class UndoStack:
    """The history of one square. ``do`` applies and records; ``undo`` and
    ``redo`` walk it; ``dirty`` says whether the square differs from the last
    ``mark_clean``, which is what a save calls."""

    def __init__(self, square: Square):
        self.square = square
        self.alloc = IdAllocator(square)
        self._done: list[Command] = []
        self._undone: list[Command] = []
        self._clean_at = 0

    def do(self, cmd: Command) -> None:
        cmd.apply(self.square)
        self._done.append(cmd)
        self._undone.clear()

    def undo(self) -> Command | None:
        if not self._done:
            return None
        cmd = self._done.pop()
        cmd.undo(self.square)
        self._undone.append(cmd)
        return cmd

    def redo(self) -> Command | None:
        if not self._undone:
            return None
        cmd = self._undone.pop()
        cmd.apply(self.square)
        self._done.append(cmd)
        return cmd

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def dirty(self) -> bool:
        return len(self._done) != self._clean_at

    def mark_clean(self) -> None:
        self._clean_at = len(self._done)

    def describe_undo(self) -> str:
        return self._done[-1].describe() if self._done else ''

    def describe_redo(self) -> str:
        return self._undone[-1].describe() if self._undone else ''


class SetUndoStack:
    """One history over every square of a working set - R17 wants one undo
    key, and an edit near an edge touches the neighbour. Each step is a
    command on a square; ``dirty`` is answered per square, since each is
    its own file to save."""

    def __init__(self):
        # each entry is a *step*: the pairs that go and come back together.
        # One pair for an ordinary edit; several where one action touches
        # more than one square, which R40 asks for by name - an import is one
        # undoable step, and an import of a working set lands in up to nine
        # files at once. The answer to a bad one has to be one Ctrl+Z.
        self._done: list[list[tuple[Square, Command]]] = []
        self._undone: list[list[tuple[Square, Command]]] = []
        self._squares: dict[int, Square] = {}      # every square touched, by identity
        self._clean: dict[int, int] = {}           # id(square) -> steps done at the last save
        self._alloc: IdAllocator | None = None

    def alloc(self, square: Square) -> IdAllocator:
        """The working set's allocator, widened to clear this square too.

        One allocator, not one per square: see IdAllocator. A square joining
        later only lowers the counter, so ids already handed out stay valid.
        """
        if self._alloc is None:
            self._alloc = IdAllocator(square)
        else:
            self._alloc.include(square)
        return self._alloc

    def do(self, square: Square, cmd: Command) -> None:
        self.do_across([(square, cmd)])

    def do_across(self, steps) -> None:
        """One step over several squares - applied in order, undone in
        reverse, and taken off the history together.

        Nothing is not a step. An empty list used to go on the history all the
        same, and the Ctrl+Z that reached it popped it, undid nothing, and
        answered None - which every caller reads as "there was nothing to
        undo", so the keypress was swallowed and the edit before it stayed
        done. The redo stack was cleared for it too.
        """
        steps = list(steps)
        if not steps:
            return
        for square, cmd in steps:
            cmd.apply(square)
            self._squares[id(square)] = square
        self._done.append(steps)
        self._undone.clear()

    def undo(self) -> tuple[Square, Command] | None:
        """The last step undone, and the pair it was. A step over several
        squares answers with its first pair, which is what a caller wanting
        one thing to describe is asking for; ``undo_across`` gives all of
        them."""
        step = self.undo_across()
        return step[0] if step else None

    def undo_across(self) -> list | None:
        if not self._done:
            return None
        step = self._done.pop()
        for square, cmd in reversed(step):
            cmd.undo(square)
        self._undone.append(step)
        return step

    def redo(self) -> tuple[Square, Command] | None:
        step = self.redo_across()
        return step[0] if step else None

    def redo_across(self) -> list | None:
        if not self._undone:
            return None
        step = self._undone.pop()
        for square, cmd in step:
            cmd.apply(square)
        self._done.append(step)
        return step

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    def describe_undo(self) -> str:
        return self._done[-1][0][1].describe() if self._done else ''

    def describe_redo(self) -> str:
        return self._undone[-1][0][1].describe() if self._undone else ''

    def _steps(self, square: Square) -> int:
        """How many steps have touched this square. A step over several
        squares counts once for each of them it names, and once only however
        many commands it carries for that square - what this feeds is
        ``dirty``, which asks whether the file differs from the last save."""
        return sum(1 for step in self._done if any(sq is square for sq, _ in step))

    def dirty(self, square: Square) -> bool:
        return self._steps(square) != self._clean.get(id(square), 0)

    def dirty_squares(self) -> list[Square]:
        return [sq for sq in self._squares.values() if self.dirty(sq)]

    def mark_clean(self, square: Square) -> None:
        self._squares[id(square)] = square
        self._clean[id(square)] = self._steps(square)


def snapshot(square: Square) -> tuple:
    """Everything about a square that an edit can change, as one comparable
    value - for the test that an edit and its undo leave nothing behind."""
    nodes = tuple(sorted((i, n.lat, n.lon, tuple(sorted(n.tags.items()))) for i, n in square.nodes.items()))
    ways = tuple(sorted((i, tuple(w.refs), tuple(sorted(w.tags.items()))) for i, w in square.ways.items()))
    relations = tuple(sorted(
        (i, tuple((mem.type, mem.ref, mem.role) for mem in r.members), tuple(sorted(r.tags.items())))
        for i, r in square.relations.items()))
    return nodes, ways, relations
