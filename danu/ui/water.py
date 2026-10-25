"""The water import, on a worker - G4c.

Fetching and parsing is 1.3 seconds on the gobras 3x3: 0.72 to fetch 13.89 MB,
0.52 to parse 158,633 nodes into 4,673 features, 0.04 to decide which square
each belongs to. Twenty-six times the frame budget, so it does not run where
the frames are; a fortieth of what the batch grading's timeout was written
for, so it does not want a progress dialogue either. A worker and a line in
the status bar.

Newest wins, as the surface builder's queue does and for the same reason: a
mapper who presses import twice should get one import, not two. The second
request replaces whatever was waiting; the one already out cannot be stopped -
``urlopen`` is a blocking read with no cancellation hook - so it is allowed to
finish and its answer is dropped, which costs a few seconds of somebody else's
bandwidth and no correctness.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..core import zone_index
from ..core.square import Square, read_square
from ..water import coast, overpass, peaks
from ..water import gone as gone_mod


@dataclass(frozen=True)
class Answer:
    """What an import brought back: the features placed by square, and the
    ids of every way and relation the answer named, placed or not. G5b reads
    absence from the second against what the set holds, and it has to be the
    whole answer - a feature placed into a neighbour, or dropped for an anchor
    outside the set, is not gone."""
    placed: dict
    ways: frozenset
    relations: frozenset
    # a spot-height import's (G9): the nodes the answer named, imported or
    # skipped, and the skipped with why - (id, ele as written, lon, lat)
    nodes: frozenset = frozenset()
    skipped: tuple = ()
    beyond: int = 0                    # spot heights beyond the contours, not imported
    # which of the answer's ways each of their nodes is on: a held way gone
    # from it with its nodes on others was merged into them (#250)
    on: dict = field(default_factory=dict)
    # features whose home is now another square, (kind, id): (was, is); and
    # the zone's squares outside the set read for it, by name
    moved: dict = field(default_factory=dict)
    loaded: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    """What a water import takes from the UI thread: where the set - and
    the squares read alongside it - holds each feature, and the zone's
    folder, whose other squares the worker reads for the rest."""
    held: dict
    zone_dir: object = None


def water_work(payload: bytes, working_set, held) -> Answer:
    """The answer placed by home - among the zone's squares where the set
    knows its zone - and the squares outside the set that a home, or a move
    from one, needs, read here off the UI thread."""
    water = overpass.parse(payload)
    snap = held if isinstance(held, Snapshot) else Snapshot(held)
    zone, files = None, {}
    if snap.zone_dir is not None:
        files = zone_index.squares(snap.zone_dir)
        open_ = set(working_set.squares) | set(getattr(working_set, 'extra', {}))
        zone = (set(files), zone_index.held(snap.zone_dir, skip=open_))
    placed, moved = overpass.homes(water, working_set, snap.held, zone)
    need = set(placed) | {n for pair in moved.values() for n in pair}
    loaded = {n: read_square(files[n]) for n in sorted(need, key=str)
              if n in files and n not in working_set.squares and n not in getattr(working_set, 'extra', {})}
    return Answer(placed, frozenset(water.ways), frozenset(water.relations),
                  on=gone_mod.nodes_on(water.ways.values()), moved=moved, loaded=loaded)


def heights_held(working_set) -> tuple:
    """What the spot-height import snapshots on the UI thread: where each one
    it holds is, and where the contours are."""
    return peaks.held(working_set), peaks.envelopes(working_set)


def heights_work(payload: bytes, working_set, held: tuple) -> Answer:
    """A spot-height answer, the ones beyond the contours taken out, placed
    - G9."""
    at, boxes = held
    got = peaks.within(peaks.parse(payload), boxes, at)
    return Answer(peaks.place(got, working_set, at), frozenset(), frozenset(),
                  nodes=got.answered, skipped=tuple(got.skipped), beyond=len(got.beyond))


def coast_work(payload: bytes, working_set, held: dict) -> Answer:
    """A coastline answer, placed as water's is - each way whole into the
    square holding its first node, or where the set already holds it."""
    got = coast.coastlines(payload)
    return Answer(overpass.place(got, working_set, held), frozenset(got.ways), frozenset())


def fetch_coast(bounds, url: str = overpass.OVERPASS_URL) -> bytes:
    return overpass.fetch(bounds, url=url, text=coast.query(bounds))


def coast_commands(placed: dict, working_set) -> list[tuple[Square, object]]:
    """A coastline import as its steps, a command a square, reconciling as
    water's does - upstream owning that it is a coastline, where it runs and
    which way."""
    from ..core import edits
    steps = []
    for name in sorted(placed, key=str):
        square = working_set.squares.get(name)
        if square is not None:
            got = placed[name]
            steps.append((square, edits.ImportWater(
                upstream_owns=coast.UPSTREAM_OWNS, new_nodes=dict(got.nodes), new_ways=dict(got.ways),
                name=f'import coastline into {name}')))
    return steps


def fetch_heights(bounds, url: str = overpass.OVERPASS_URL) -> bytes:
    return overpass.fetch(bounds, url=url, text=peaks.query(bounds))


def held_by(working_set) -> dict:
    """Which square holds each way and relation, as ``(kind, id)`` to name.

    Taken on the UI thread when the import starts, because a square's
    contents are the UI thread's: the worker places against this snapshot
    rather than walking ``ways`` and ``relations`` a mapper may be editing.
    What the worker does still read is the grid - ``WorkingSet.at`` maps a
    point to one of the set's squares by name, for a feature's anchor - and
    no edit changes the grid; opening another set replaces the whole object,
    and ``_water_imported`` refuses an answer for a set no longer open. A feature deleted in the
    second and a half the fetch takes is placed where it was, and written
    there afresh - which is what importing it would have done anyway.
    """
    out = {}
    for name, square in [*working_set.squares.items(), *getattr(working_set, 'extra', {}).items()]:
        out.update((('way', i), name) for i in square.ways)
        out.update((('relation', i), name) for i in square.relations)
    return out


class _Signals(QObject):
    finished = Signal(object, int)      # Answer, the serial it was for
    failed = Signal(str, int)


class _Job(QRunnable):
    def __init__(self, fetch, bounds, working_set, held: dict, serial: int,
                 signals: _Signals, work=water_work):
        super().__init__()
        self.work = work
        self.fetch, self.bounds, self.working_set = fetch, bounds, working_set
        self.held, self.serial, self.signals = held, serial, signals

    def run(self):
        try:
            answer = self.work(self.fetch(self.bounds), self.working_set, self.held)
        except Exception as exc:      # noqa: BLE001 - reported as text, on the UI thread
            self._say(f'{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}')
            return
        try:
            self.signals.finished.emit(answer, self.serial)
        except RuntimeError:
            pass                      # the window went; see _say

    def _say(self, text: str):
        try:
            self.signals.failed.emit(text, self.serial)
        except RuntimeError:
            pass                      # a job outlives the window when it closes


class WaterImporter(QObject):
    """One import at a time, newest wins. Water's, by default; ``work``,
    ``held`` and ``fetch`` given, the spot heights' (G9) on the same footing."""

    started = Signal(object)           # the set the fetch now out is for
    finished = Signal(object, object)  # Answer, the set it was asked for
    failed = Signal(str)

    def __init__(self, parent=None, fetch=None, runner=None, work=water_work, held=None):
        super().__init__(parent)
        self._work, self._held = work, held or held_by
        self._fetch = fetch or overpass.fetch
        self._runner = runner or QThreadPool.globalInstance().start
        self._serial = 0
        self._running = False
        self._wanted = None
        self._out = None               # the set the job now running was asked for
        self._signals = None
        self._job = None

    @property
    def busy(self) -> bool:
        return self._running

    def request(self, working_set) -> int:
        """Ask for the working set's water, and get the serial given.

        Always accepted. A request made while one is out replaces whatever
        was waiting rather than queueing behind it: two imports of the same
        bounds answer the same, and the newest is the one whose bounds are
        current.
        """
        self._serial += 1
        self._wanted = working_set
        if not self._running:
            self._start()
        return self._serial

    def _start(self):
        working_set, self._wanted = self._wanted, None
        self._out = working_set
        self._running = True
        sig = _Signals()
        sig.finished.connect(self._done)
        sig.failed.connect(self._fail)
        job = _Job(self._fetch, working_set.bounds, working_set, self._held(working_set),
                   self._serial, sig, self._work)
        job.setAutoDelete(False)       # Python owns it; see the note in loader.py
        self._signals, self._job = sig, job
        self.started.emit(working_set)
        self._runner(job)

    def _done(self, answer, serial: int):
        self._running = False
        # the answer to a request that has been superseded is dropped rather
        # than shown: its bounds are not the ones the mapper is looking at
        if serial == self._serial:
            self.finished.emit(answer, self._out)
        self._next()

    def _fail(self, text: str, serial: int):
        self._running = False
        if serial == self._serial:
            self.failed.emit(text)
        self._next()

    def _next(self):
        if self._wanted is not None and not self._running:
            self._start()


def commands(placed: dict, working_set) -> list[tuple[Square, object]]:
    """One import as the steps it takes: a command per square, to go on the
    history together.

    A square the set has no file for is given its features all the same - #87
    settled that an import may bring one into being, and ``save_square``
    frames and writes it when the mapper saves. ``WorkingSet.open`` puts an
    empty ``Square`` in for every name of the grid, so that square is here to
    be written into; the skip below is for a name the grid does not hold at
    all, which ``place`` cannot produce and a caller passing its own dict can.
    """
    from ..core import edits
    steps = []
    for name in sorted(placed, key=str):
        square = working_set.square(name)        # a home outside the grid is read alongside it
        if square is None:
            continue
        water = placed[name]
        steps.append((square, edits.ImportWater(
            upstream_owns=overpass.UPSTREAM_OWNS,
            new_nodes=dict(water.nodes), new_ways=dict(water.ways),
            new_relations=dict(water.relations),
            name=f'import water into {name}')))
    return steps


def height_commands(placed: dict, working_set) -> list[tuple[Square, object]]:
    """A spot-height import as its steps, a command a square - G9. The same
    command as water's, reconciling the same way, upstream owning what a spot
    height is and what it is called."""
    from ..core import edits
    steps = []
    for name in sorted(placed, key=str):
        square = working_set.squares.get(name)
        if square is not None:
            steps.append((square, edits.ImportWater(
                upstream_owns=peaks.UPSTREAM_OWNS, new_nodes=dict(placed[name]),
                name=f'import spot heights into {name}')))
    return steps


def move_commands(answer, working_set, alloc) -> list:
    """What moves a feature's home: out of the square that held it, its
    level carried onto the copy the import writes in its new home - as a
    re-import into its own square keeps it - and its fill lines (G7a) with
    it. ``alloc(square)`` gives the id allocator for a square. As (square,
    Compound) steps, to go on the history with the import's own; the placed
    copies' tags are given the old copy's level here, before the import's
    commands are made from them."""
    from ..core import edits
    from ..core.reconcile import merge_tags
    from ..water.flatten import FILL
    out = []
    by_square: dict = {}
    for (kind, fid), (was, now) in sorted(answer.moved.items(), key=lambda kv: (str(kv[1][0]), kv[0])):
        src, dst = working_set.square(was), answer.placed.get(now)
        if src is None or dst is None:
            continue
        cmds = by_square.setdefault(was, [])
        if kind == 'relation' and fid in src.relations:
            old = src.relations[fid]
            if fid in dst.relations:
                dst.relations[fid].tags = merge_tags(old.tags, dst.relations[fid].tags, overpass.UPSTREAM_OWNS)
            cmds.insert(0, edits.DeleteRelation(fid))
        elif kind == 'way' and fid in src.ways:
            old = src.ways[fid]
            if fid in dst.ways:
                dst.ways[fid].tags = merge_tags(old.tags, dst.ways[fid].tags, overpass.UPSTREAM_OWNS)
            # a ring another relation staying there still names, stays too
            staying = {m.ref for r in src.relations.values() if ('relation', r.id) not in answer.moved
                       for m in r.members if m.type == 'way'}
            if fid not in staying:
                cmds.append(edits.DeleteWay(fid))
        # its fill lines, which say whose they are
        key = f'{kind}/{fid}'
        target = working_set.square(now)
        for line in [w for w in src.ways.values() if w.tags.get(FILL) == key]:
            cmds.append(edits.DeleteWay(line.id))
            if target is not None:
                ids = alloc(target)
                coords = [(src.nodes[r].lon, src.nodes[r].lat) for r in line.refs if r in src.nodes]
                out.append((target, edits.AddWay(ids.take(), [ids.take() for _ in coords], coords, dict(line.tags))))
    for name, cmds in by_square.items():
        if cmds:
            out.insert(0, (working_set.square(name), edits.Compound(cmds, name=f'move water out of {name}')))
    return out
