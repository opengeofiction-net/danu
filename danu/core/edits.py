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

from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

from .square import Node, Square, Way

Coord = tuple[float, float]            # lon, lat


# ------------------------------------------------------------------ ids

class IdAllocator:
    """Fresh negative ids for one square, each below the lowest in use. Nodes
    and ways are different namespaces in OSM, but one counter over both keeps
    a file readable by eye and cannot collide with either."""

    def __init__(self, square: Square):
        lowest = min([0, *square.nodes.keys(), *square.ways.keys()])
        self._next = lowest - 1

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


@dataclass
class AddWay(Command):
    """A new way through new nodes, tagged - a contour drawn at an elevation."""
    way_id: int
    node_ids: list[int]
    coords: list[Coord]
    tags: dict[str, str]

    def apply(self, square: Square) -> None:
        for nid, (lon, lat) in zip(self.node_ids, self.coords):
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

    def apply(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        refs.append(self.node_id) if self.at_end else refs.insert(0, self.node_id)

    def undo(self, square: Square) -> None:
        refs = square.ways[self.way_id].refs
        refs.pop() if self.at_end else refs.pop(0)

    def describe(self) -> str:
        return 'join'


@dataclass
class InsertNode(Command):
    """A new node inserted into a way at an index, between two existing."""
    way_id: int
    index: int
    node_id: int
    coord: Coord

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

    def apply(self, square: Square) -> None:
        n = square.nodes[self.node_id]
        n.lon, n.lat = self.after

    def undo(self, square: Square) -> None:
        n = square.nodes[self.node_id]
        n.lon, n.lat = self.before

    def describe(self) -> str:
        return 'move node'


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
class SetTags(Command):
    """A way's tags replaced - the elevation changed, most often."""
    way_id: int
    before: dict[str, str]
    after: dict[str, str]

    def apply(self, square: Square) -> None:
        square.ways[self.way_id].tags = dict(self.after)

    def undo(self, square: Square) -> None:
        square.ways[self.way_id].tags = dict(self.before)

    def describe(self) -> str:
        a, b = self.before.get('ele'), self.after.get('ele')
        return f'{a} m -> {b} m' if a != b else 'retag'


@dataclass
class Compound(Command):
    """Several commands as one step of undo. Applied in order, undone in
    reverse; the operations of phase 5 - burn a river, flatten a body - are
    compounds, and so is splitting a long way on save."""
    commands: list[Command]
    name: str = 'compound'

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
        cmds.append(_ReplaceWays(wid, way, [(nid, refs, dict(way.tags)) for nid, refs in zip(new_ids, pieces)]))
    if not cmds:
        return None
    return Compound(cmds, name=f'split {len(cmds)} long way(s)')


@dataclass
class _ReplaceWays(Command):
    """One way replaced by several over the same nodes; the inverse of a split."""
    way_id: int
    original: Way
    pieces: list[tuple[int, list[int], dict[str, str]]]

    def apply(self, square: Square) -> None:
        del square.ways[self.way_id]
        for nid, refs, tags in self.pieces:
            square.ways[nid] = Way(id=nid, refs=list(refs), tags=tags)

    def undo(self, square: Square) -> None:
        for nid, _, _ in self.pieces:
            del square.ways[nid]
        square.ways[self.way_id] = self.original

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


def snapshot(square: Square) -> tuple:
    """Everything about a square that an edit can change, as one comparable
    value - for the test that an edit and its undo leave nothing behind."""
    nodes = tuple(sorted((i, n.lat, n.lon, tuple(sorted(n.tags.items()))) for i, n in square.nodes.items()))
    ways = tuple(sorted((i, tuple(w.refs), tuple(sorted(w.tags.items()))) for i, w in square.ways.items()))
    return nodes, ways
