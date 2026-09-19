"""danu.core.save: a square drawn from nothing becomes a file the build reads."""

from pathlib import Path

import pytest

from danu.core import edits, save
from danu.core.ladder import regular_ladder
from danu.core.square import Square, SquareName, read_square


def drawn_from_blank(n_rings=3) -> tuple[Square, edits.SetUndoStack]:
    """A square nobody has drawn, with a few concentric contours put in
    through the history as the tools would."""
    sq = Square(name=SquareName(126, -24))                 # present=False: no file
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    for i in range(n_rings):
        ele = 101 + 50 * i
        d = 0.4 - 0.1 * i
        cx, cy = 126.5, -23.5
        pts = [(cx - d, cy - d), (cx + d, cy - d), (cx + d, cy + d), (cx - d, cy + d)]
        ids = [alloc.take() for _ in pts]
        hist.do(sq, edits.AddWay(alloc.take(), ids, pts, {'ele': str(ele)}))
        hist.do(sq, edits.ExtendWayWithExisting(min(sq.ways), True, ids[0]))     # closed
    return sq, hist


def test_a_blank_square_is_saved_with_a_frame_and_reads_back(tmp_path):
    sq, hist = drawn_from_blank()
    assert hist.dirty(sq) and not save.has_frame(sq)
    with pytest.raises(ValueError):
        save.save_square(sq, hist)                        # no file yet: a path is needed
    path = save.default_path(tmp_path, sq.name)
    assert path == tmp_path / 'S24E126.osm.xz'
    report = save.save_square(sq, hist, path)
    assert report.framed and report.split == 0 and report.path == path
    assert sq.present and sq.path == path and not hist.dirty(sq) and save.has_frame(sq)
    again = read_square(path)
    frame = [w for w in again.ways.values() if w.tags.get('ref') == 'S24E126']
    assert len(frame) == 1 and frame[0].closed and frame[0].ele is None
    corners = {(again.nodes[r].lon, again.nodes[r].lat) for r in frame[0].refs}
    assert corners == {(126, -24), (127, -24), (127, -23), (126, -23)}
    assert sorted(w.ele for w in again.contours()) == [101, 151, 201]
    assert again.attrs['upload'] == 'never'
    assert 'saved S24E126.osm.xz, with a frame' == report.describe()
    # the frame is an edit like any other: undo takes it back
    hist.undo()
    assert not save.has_frame(sq) and hist.dirty(sq)


def test_a_second_save_adds_no_second_frame_and_keeps_the_path(tmp_path):
    sq, hist = drawn_from_blank()
    path = save.default_path(tmp_path, sq.name)
    save.save_square(sq, hist, path)
    alloc = hist.alloc(sq)
    hist.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, -23.9), (126.2, -23.9)], {'ele': '51'}))
    report = save.save_square(sq, hist)                   # to its own file
    assert not report.framed and report.path == path and not hist.dirty(sq)
    assert sum(1 for w in read_square(path).ways.values() if w.tags.get('ref')) == 1


def test_long_ways_are_split_on_save_and_the_split_is_one_undo_step(tmp_path):
    sq = Square(name=SquareName(10, 10), present=True, path=tmp_path / 'N10E010.osm.xz')
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    n = 4500
    ids = [alloc.take() for _ in range(n)]
    hist.do(sq, edits.AddWay(alloc.take(), ids, [(10.1 + i * 1e-4, 10.5) for i in range(n)], {'ele': '250'}))
    report = save.save_square(sq, hist)
    assert report.split == 1 and 'split' in report.describe()
    again = read_square(sq.path)
    pieces = [w for w in again.contours()]
    assert len(pieces) == 3 and all(len(w.refs) <= 2000 for w in pieces)
    assert sum(len(w.refs) for w in pieces) == n + 2          # ends shared
    hist.undo()
    assert len(sq.ways) == 1 and len(next(iter(sq.ways.values())).refs) == n and hist.dirty(sq)


def test_off_ladder_advice_comes_back_with_the_save(tmp_path):
    sq, hist = drawn_from_blank()
    alloc = hist.alloc(sq)
    hist.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.1, -23.9), (126.2, -23.9)], {'ele': '135'}))
    report = save.save_square(sq, hist, save.default_path(tmp_path, sq.name), ladder=regular_ladder(50, 1, 300))
    assert [a.value for a in report.advice] == [135] and '135 m used once' in report.describe()
    report = save.save_square(sq, hist)                   # ladder inferred when none is given
    assert [a.value for a in report.advice] == [135]
