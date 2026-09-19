"""danu.core.edits: every command takes itself back exactly, in any order."""

import lzma
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from danu.core import edits
from danu.core.square import Square, SquareName, read_square, write_square

GOLDEN = Path(__file__).parent / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


@pytest.fixture
def square():
    return read_square(GOLDEN)


def fresh_square() -> Square:
    """A small square with two contours, for the property test to chew on."""
    sq = Square(name=SquareName(10, 10), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for ele, lat in (('100', 10.2), ('200', 10.6)):
        ids = [alloc.take() for _ in range(4)]
        edits.AddWay(alloc.take(), ids, [(10.1 + 0.2 * i, lat) for i in range(4)], {'ele': ele}).apply(sq)
    return sq


# ------------------------------------------------------------------- ids

def test_ids_are_allocated_below_the_lowest_the_file_holds(square):
    alloc = edits.IdAllocator(square)
    lowest = min(min(square.nodes), min(square.ways))
    first = alloc.take()
    assert first == lowest - 1 and alloc.take() == lowest - 2
    assert first not in square.nodes and first not in square.ways


def test_an_empty_square_starts_at_minus_one():
    assert edits.IdAllocator(Square(name=SquareName(0, 0))).take() == -1


# -------------------------------------------------------------- commands

def test_each_command_applies_and_takes_itself_back(square):
    before = edits.snapshot(square)
    stack = edits.UndoStack(square)
    a = stack.alloc
    way = max(square.contours(), key=lambda w: len(w.refs))
    node = way.refs[len(way.refs) // 2]
    end = way.refs[-1]
    cmds = [
        edits.AddWay(a.take(), [a.take(), a.take(), a.take()], [(125.1, -23.1), (125.2, -23.15), (125.3, -23.1)], {'ele': '303'}),
        edits.ExtendWay(way.id, True, a.take(), (125.55, -23.55)),
        edits.ExtendWay(way.id, False, a.take(), (125.05, -23.05)),
        edits.ExtendWayWithExisting(way.id, True, node),
        edits.InsertNode(way.id, 1, a.take(), (125.41, -23.41)),
        edits.MoveNode(node, (square.nodes[node].lon, square.nodes[node].lat), (125.0, -23.0)),
        edits.SetTags(way.id, dict(way.tags), {**way.tags, 'ele': '999'}),
        edits.DeleteNode(end),
        edits.DeleteWay(way.id),
    ]
    for cmd in cmds:
        snap = edits.snapshot(square)
        stack.do(cmd)
        assert edits.snapshot(square) != snap, cmd.describe()
        stack.undo()
        assert edits.snapshot(square) == snap, f'{cmd.describe()} did not take itself back'
        stack.redo()
        assert edits.snapshot(square) != snap
        stack.undo()
    assert edits.snapshot(square) == before
    assert not stack.dirty


def test_deleting_a_node_drops_a_way_left_with_one_and_undo_restores_both():
    sq = fresh_square()
    wid = min(sq.ways)                       # the last drawn; both have 4 nodes
    refs = list(sq.ways[wid].refs)
    stack = edits.UndoStack(sq)
    for r in refs[:3]:
        stack.do(edits.DeleteNode(r))
    assert wid not in sq.ways                # 4 - 3 = 1 node: not a line, gone
    assert refs[3] in sq.nodes               # the survivor node stays a node
    before = edits.snapshot(sq)
    stack.undo(); stack.undo(); stack.undo()
    assert wid in sq.ways and sq.ways[wid].refs == refs
    stack.redo(); stack.redo(); stack.redo()
    assert edits.snapshot(sq) == before


def test_deleting_a_way_removes_only_the_nodes_nothing_else_uses():
    sq = fresh_square()
    w1, w2 = sorted(sq.ways)
    shared = sq.ways[w1].refs[0]
    sq.ways[w2].refs.append(shared)          # w2 now shares one node with w1
    stack = edits.UndoStack(sq)
    n_before = len(sq.nodes)
    stack.do(edits.DeleteWay(w1))
    assert shared in sq.nodes and len(sq.nodes) == n_before - 3
    stack.undo()
    assert len(sq.nodes) == n_before and w1 in sq.ways


def test_dirty_follows_the_clean_mark_not_the_history(square):
    stack = edits.UndoStack(square)
    assert not stack.dirty
    way = next(square.contours())
    was = way.tags['ele']
    stack.do(edits.SetTags(way.id, dict(way.tags), {**way.tags, 'ele': '5'}))
    assert stack.dirty and stack.describe_undo() == f'{was} m -> 5 m'
    stack.mark_clean()
    assert not stack.dirty
    stack.undo()
    assert stack.dirty                       # differs from what was saved, in the other direction
    stack.redo()
    assert not stack.dirty


# ------------------------------------------------------------- property

@st.composite
def command_sequences(draw):
    """Random edits against fresh_square(), built as the square evolves so
    every command refers to something that exists when it is applied."""
    sq = fresh_square()
    alloc = edits.IdAllocator(sq)
    cmds = []
    for _ in range(draw(st.integers(0, 12))):
        ways = sorted(sq.ways)
        nodes = sorted(sq.nodes)
        kind = draw(st.sampled_from(['add', 'extend', 'insert', 'move', 'tags', 'delnode', 'delway']))
        if kind == 'add' or not ways:
            n = draw(st.integers(2, 5))
            cmd = edits.AddWay(alloc.take(), [alloc.take() for _ in range(n)],
                               [(10.0 + draw(st.floats(0, 1)), 10.0 + draw(st.floats(0, 1))) for _ in range(n)],
                               {'ele': str(draw(st.integers(0, 900)))})
        elif kind == 'extend':
            cmd = edits.ExtendWay(draw(st.sampled_from(ways)), draw(st.booleans()), alloc.take(),
                                  (10.0 + draw(st.floats(0, 1)), 10.0 + draw(st.floats(0, 1))))
        elif kind == 'insert':
            w = draw(st.sampled_from(ways))
            cmd = edits.InsertNode(w, draw(st.integers(0, len(sq.ways[w].refs))), alloc.take(),
                                   (10.0 + draw(st.floats(0, 1)), 10.0 + draw(st.floats(0, 1))))
        elif kind == 'move':
            nid = draw(st.sampled_from(nodes))
            n = sq.nodes[nid]
            cmd = edits.MoveNode(nid, (n.lon, n.lat), (10.0 + draw(st.floats(0, 1)), 10.0 + draw(st.floats(0, 1))))
        elif kind == 'tags':
            w = draw(st.sampled_from(ways))
            cmd = edits.SetTags(w, dict(sq.ways[w].tags), {'ele': str(draw(st.integers(0, 900)))})
        elif kind == 'delnode':
            cmd = edits.DeleteNode(draw(st.sampled_from(nodes)))
        else:
            cmd = edits.DeleteWay(draw(st.sampled_from(ways)))
        cmd.apply(sq)                        # so the next command sees the square as it will be
        cmds.append(cmd)
    return cmds


@settings(max_examples=150, deadline=None)
@given(command_sequences())
def test_any_sequence_of_edits_undone_leaves_the_square_exactly_as_it_was(cmds):
    sq = fresh_square()
    before = edits.snapshot(sq)
    stack = edits.UndoStack(sq)
    snaps = [before]
    for cmd in cmds:
        stack.do(cmd)
        snaps.append(edits.snapshot(sq))
    for i in range(len(cmds)):
        stack.undo()
        assert edits.snapshot(sq) == snaps[-2 - i]
    assert edits.snapshot(sq) == before
    for i in range(len(cmds)):
        stack.redo()
        assert edits.snapshot(sq) == snaps[1 + i]


# ----------------------------------------------------------------- split

def test_splitting_matches_split_long_ways_on_the_file(tmp_path):
    """The command and the file tool are two implementations of one rule;
    run both on the same square and compare the results way for way."""
    from danu.core import split_long_ways as tool
    sq = fresh_square()
    alloc = edits.IdAllocator(sq)
    wid = alloc.take()
    ids = [alloc.take() for _ in range(23)]
    edits.AddWay(wid, ids, [(10.0 + i * 0.01, 10.5) for i in range(23)], {'ele': '150', 'note': 'long'}).apply(sq)
    path = tmp_path / 'N10E010.osm.xz'
    write_square(sq, path)
    # the tool, on the file, limit 10
    tool.split_file(str(path), 10, None, False)
    from_tool = read_square(path)
    # the command, on the model
    cmd = edits.split_long_ways(sq, edits.IdAllocator(sq), limit=10)
    assert cmd is not None and 'split 1' in cmd.describe()
    cmd.apply(sq)
    long_model = [w for w in sq.ways.values() if w.tags.get('note') == 'long']
    long_tool = [w for w in from_tool.ways.values() if w.tags.get('note') == 'long']
    assert len(long_model) == len(long_tool) == 3            # 23 nodes at 10 a piece sharing ends: 10 + 9 + 4
    assert sorted(len(w.refs) for w in long_model) == sorted(len(w.refs) for w in long_tool)
    assert all(len(w.refs) <= 10 for w in long_model)
    # same geometry, in order, ends shared
    seq_model = [r for w in sorted(long_model, key=lambda w: -w.id) for r in w.refs]
    seq_tool = [r for w in sorted(long_tool, key=lambda w: -w.id) for r in w.refs]
    assert seq_model == seq_tool
    joined = seq_model[:1] + [r for i, r in enumerate(seq_model[1:], 1) if r != seq_model[i - 1]]
    assert joined == ids
    cmd.undo(sq)
    assert sq.ways[wid].refs == ids and len([w for w in sq.ways.values() if w.tags.get('note') == 'long']) == 1


def test_nothing_to_split_is_none():
    assert edits.split_long_ways(fresh_square(), edits.IdAllocator(fresh_square())) is None


# ----------------------------------------------------------------- write

def test_write_then_read_is_the_same_square(square, tmp_path):
    out = tmp_path / 'S24E125_Los_Pizarrales.osm.xz'
    write_square(square, out)
    again = read_square(out)
    assert edits.snapshot(again) == edits.snapshot(square)
    assert again.attrs['upload'] == 'never' and again.attrs['generator'] == 'danu'
    plain = tmp_path / 'S24E125.osm'
    write_square(square, plain)
    assert edits.snapshot(read_square(plain)) == edits.snapshot(square)


def test_upload_never_is_written_even_when_the_input_lacked_it(tmp_path):
    sq = fresh_square()
    sq.attrs = {'version': '0.6'}
    out = tmp_path / 'N10E010.osm.xz'
    write_square(sq, out)
    text = lzma.open(out, 'rt').read()
    assert "upload='never'" in text and '"' not in text.split('\n')[1]      # one quoting style, JOSM's
    assert read_square(out).attrs['upload'] == 'never'


def test_a_failed_write_leaves_the_old_file_whole(tmp_path, monkeypatch):
    sq = fresh_square()
    out = tmp_path / 'N10E010.osm.xz'
    write_square(sq, out)
    before = out.read_bytes()
    import danu.core.square as mod
    def boom(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(mod.lzma, 'open', boom)
    with pytest.raises(OSError):
        write_square(sq, out)
    assert out.read_bytes() == before and not list(tmp_path.glob('tmp*'))


def test_tag_values_with_awkward_characters_survive_the_round_trip(tmp_path):
    sq = fresh_square()
    w = sq.ways[min(sq.ways)]
    w.tags['name'] = "O'Brien & <Sons> \"Ltd\""
    out = tmp_path / 'N10E010.osm.xz'
    write_square(sq, out)
    assert read_square(out).ways[w.id].tags['name'] == w.tags['name']
