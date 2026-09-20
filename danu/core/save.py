"""Saving a square - phase 3's exit: a square drawn from blank, saved, is a
square the server builds unchanged.

A save is a few things in one place so they cannot be forgotten separately:
a square that never had a file gets the frame ``make_square`` gives a blank
one, because the frame is what a mapper sees in JOSM and what makes a square
a square; ways over the API's 2,000 nodes are split, as ``split_long_ways``
does to a file, because the file is unusable otherwise; then the file is
written the way ``write_square`` writes it - ``upload='never'``, negative
ids, plain decimals - and the square is clean.

The frame and the split go through the history as commands, so what a save
did to the drawing is visible to undo like any other edit, and the file and
the model do not quietly differ.

Off-ladder advice - a value off the regular ladder and used once or twice -
is read at the same moment and handed back for the status line. Advice, not
error: the file is saved either way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import edits, ladder as L
from .square import Square, SquareName, write_square

FRAME_NOTE = 'square frame - do not edit'


def default_path(zone_dir: str | os.PathLike, name: SquareName) -> Path:
    """Where a square with no file yet goes: ``<zone>/<NAME>.osm.xz``. A
    mapper can add a place name to the file later; the build reads the
    first seven characters and ignores the rest."""
    return Path(zone_dir) / f'{name.name}.osm.xz'


def has_frame(square: Square) -> bool:
    """A closed way tagged ``ref`` with the square's own name and no ``ele``
    - a mapper's own ``ref`` on a contour is not a frame."""
    return any(w.closed and w.ele is None and w.tags.get('ref') == square.name.name for w in square.ways.values())


def frame_command(square: Square, alloc: edits.IdAllocator, note: str = FRAME_NOTE) -> edits.AddWay:
    """The frame ``make_square`` gives a blank square: one closed way around
    the degree, tagged with the square's name. Untagged with ``ele``, so the
    build never sees it as a contour. ``make_square`` writes its XML by hand;
    a test holds the two frames equal."""
    lon, lat = square.name.lon, square.name.lat
    corners = [(lon, lat), (lon + 1, lat), (lon + 1, lat + 1), (lon, lat + 1)]
    ids = [alloc.take() for _ in corners]
    cmd = edits.AddWay(alloc.take(), ids, [(float(x), float(y)) for x, y in corners],
                       {'ref': square.name.name, 'note': note})
    return _ClosedAddWay(cmd)


@dataclass
class _ClosedAddWay(edits.Command):
    """AddWay, then the first node again at the end: a ring."""
    add: edits.AddWay

    def apply(self, square: Square) -> None:
        self.add.apply(square)
        square.ways[self.add.way_id].refs.append(self.add.node_ids[0])

    def undo(self, square: Square) -> None:
        square.ways[self.add.way_id].refs.pop()
        self.add.undo(square)

    def describe(self) -> str:
        return 'add the square frame'

    def ways(self, square: Square) -> set[int]:
        return {self.add.way_id}


@dataclass
class SaveReport:
    path: Path
    framed: bool = False               # a frame was added: the square was drawn from nothing
    split: int = 0                     # ways split for the 2,000 node rule
    advice: list[L.OffLadder] = field(default_factory=list)

    def describe(self) -> str:
        parts = [f'saved {self.path.name}']
        if self.framed:
            parts.append('with a frame')
        if self.split:
            parts.append(f'{self.split} long way(s) split')
        if self.advice:
            parts.append('advice: ' + '; '.join(a.describe() for a in self.advice[:3])
                         + (f' and {len(self.advice) - 3} more' if len(self.advice) > 3 else ''))
        return ', '.join(parts)


def stage_zone(squares, dirty, into: str | os.PathLike) -> Path:
    """A zone directory for the build to read that holds the squares as they
    are in memory, not as they are on disk: a square with unsaved edits, or
    one drawn from blank with no file yet, is written there; a clean square
    is a symlink to its file. What the surface shows is then what is drawn,
    saved or not - the editor's ground rule.

    Written as ``.osm.xz`` because the pipeline reads nothing else - it
    refuses a bare ``.osm`` and decompresses as it goes - but at the fastest
    preset: this copy lives for one build."""
    into = Path(into)
    if into.exists():
        for p in into.iterdir():
            p.unlink()
    into.mkdir(parents=True, exist_ok=True)
    dirty_ids = {id(sq) for sq in dirty}
    for sq in squares:
        if not sq.present and not sq.ways:
            continue
        if id(sq) in dirty_ids or sq.path is None:
            write_square(sq, into / f'{sq.name.name}.osm.xz', preset=0)
        else:
            (into / sq.path.name).symlink_to(sq.path.resolve())
    return into


def save_square(square: Square, history: edits.SetUndoStack, path: str | os.PathLike | None = None,
                ladder: L.Ladder | None = None) -> SaveReport:
    """Frame if new, split if needed, write, mark clean. ``path`` defaults
    to the square's own file; a square that has none must be given one."""
    if path is None:
        if square.path is None:
            raise ValueError(f'{square.name} has no file yet; a path is needed')
        path = square.path
    path = Path(path)
    report = SaveReport(path)
    alloc = history.alloc(square)
    if not square.present and not has_frame(square):
        history.do(square, frame_command(square, alloc))
        report.framed = True
    split = edits.split_long_ways(square, alloc)
    if split is not None:
        history.do(square, split)
        report.split = len(split.commands)
    write_square(square, path)
    square.path = path
    square.present = True
    history.mark_clean(square)
    lad = ladder if ladder is not None else L.infer(square)
    if lad is not None:
        report.advice = L.off_ladder(square, lad)
    return report
