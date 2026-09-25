"""danu.core.edits: every command takes itself back exactly, in any order."""

import lzma
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from danu.core import edits
from danu.core.square import Node, Square, SquareName, read_square, write_square

GOLDEN = Path(__file__).parent / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


@pytest.fixture
def square():
    return read_square(GOLDEN)


def fresh_square() -> Square:
    """A small square with two contours and a closed ring - a lake shore,
    whose first node is its last - for the property test to chew on."""
    sq = Square(name=SquareName(10, 10), present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    for ele, lat in (('100', 10.2), ('200', 10.6)):
        ids = [alloc.take() for _ in range(4)]
        edits.AddWay(alloc.take(), ids, [(10.1 + 0.2 * i, lat) for i in range(4)], {'ele': ele}).apply(sq)
    ring = [alloc.take() for _ in range(4)]
    edits.AddWay(alloc.take(), ring, [(10.4, 10.4), (10.5, 10.4), (10.5, 10.5), (10.4, 10.5)], {'ele': '50'}).apply(sq)
    sq.ways[min(sq.ways)].refs.append(ring[0])          # closed: the first node is the last
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
    wid = max(sq.ways)                       # the first drawn contour: 4 nodes
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
    ring, w1, w2 = sorted(sq.ways)          # the ring has the lowest id; the contours follow
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
        kind = draw(st.sampled_from(['add', 'close', 'extend', 'insert', 'move', 'tags', 'delnode', 'delway']))
        if kind == 'add' or not ways:
            n = draw(st.integers(2, 5))
            cmd = edits.AddWay(alloc.take(), [alloc.take() for _ in range(n)],
                               [(10.0 + draw(st.floats(0, 1)), 10.0 + draw(st.floats(0, 1))) for _ in range(n)],
                               {'ele': str(draw(st.integers(0, 900)))})
        elif kind == 'close':
            # join a way's first node to its end: a repeated ref, as a ring has
            w = draw(st.sampled_from(ways))
            cmd = edits.ExtendWayWithExisting(w, True, sq.ways[w].refs[0])
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
    assert len(long_model) == len(long_tool) == 3            # pieces of 10, 10 and 5 refs, sharing ends: 23 distinct nodes
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


def test_coordinates_near_zero_are_written_as_decimals_and_read_back_exactly(tmp_path):
    sq = fresh_square()
    alloc = edits.IdAllocator(sq)
    ids = [alloc.take(), alloc.take()]
    coords = [(0.00001, -0.0000123), (1e-7, 125.00001487263)]
    edits.AddWay(alloc.take(), ids, coords, {'ele': '1'}).apply(sq)
    out = tmp_path / 'N00E000.osm'
    write_square(sq, out)
    text = out.read_text()
    assert 'e-0' not in text and "lat='0.00001'" not in text.replace("lon='0.00001'", '')  # decimals, not exponents
    assert "lon='0.00001'" in text and "lat='-0.0000123'" in text and "lon='0.0000001'" in text
    again = read_square(out)
    for nid, (lon, lat) in zip(ids, coords):
        assert again.nodes[nid].lon == lon and again.nodes[nid].lat == lat


def test_deleting_a_node_a_way_references_twice_restores_the_ring():
    sq = fresh_square()
    ring_way = min(sq.ways)
    first = sq.ways[ring_way].refs[0]
    assert sq.ways[ring_way].refs[-1] == first            # a ring
    before = edits.snapshot(sq)
    cmd = edits.DeleteNode(first)
    cmd.apply(sq)
    assert first not in sq.ways[ring_way].refs and len(sq.ways[ring_way].refs) == 3
    cmd.undo(sq)
    assert edits.snapshot(sq) == before


# ----------------------------------------------------------- the set's history

def test_one_history_over_two_squares_with_dirt_per_square():
    a, b = fresh_square(), fresh_square()
    hist = edits.SetUndoStack()
    wa = max(a.ways); wb = max(b.ways)
    hist.do(a, edits.SetTags(wa, dict(a.ways[wa].tags), {'ele': '1'}))
    hist.do(b, edits.SetTags(wb, dict(b.ways[wb].tags), {'ele': '2'}))
    assert hist.dirty(a) and hist.dirty(b) and len(hist.dirty_squares()) == 2
    hist.mark_clean(a)
    assert not hist.dirty(a) and hist.dirty_squares() == [b]
    sq, cmd = hist.undo()
    assert sq is b and b.ways[wb].tags['ele'] != '2' and not hist.dirty(b)
    sq, cmd = hist.undo()
    assert sq is a and hist.dirty(a)                    # undone past the clean mark is dirty again
    assert hist.redo()[0] is a and not hist.dirty(a)
    # one allocator over the set, not one per square - see the collision test
    # below, which is what this used to assert the opposite of
    assert hist.describe_redo() and hist.alloc(a) is hist.alloc(a) is hist.alloc(b)
    assert hist.undo()[0] is a and hist.undo() is None       # one step was left; then nothing


def test_every_command_says_which_ways_it_touches(square):
    a = edits.IdAllocator(square)
    way = next(square.contours())
    node = way.refs[1]
    holders = {w.id for w in square.ways.values() if node in w.refs}
    new_way = a.take()
    cmds = [
        (edits.AddWay(new_way, [a.take(), a.take()], [(125.1, -23.1), (125.2, -23.15)], {'ele': '3'}), {new_way}),
        (edits.ExtendWay(way.id, True, a.take(), (125.5, -23.5)), {way.id}),
        (edits.ExtendWayWithExisting(way.id, False, node), {way.id}),
        (edits.InsertNode(way.id, 1, a.take(), (125.4, -23.4)), {way.id}),
        (edits.MoveNode(node, (0, 0), (1, 1)), holders),
        (edits.SetTags(way.id, dict(way.tags), {'ele': '9'}), {way.id}),
        (edits.DeleteWay(way.id), {way.id}),
    ]
    for cmd, expect in cmds:
        assert cmd.ways(square) == expect, cmd
    dn = edits.DeleteNode(node)
    assert dn.ways(square) == holders
    dn.apply(square)
    assert dn.ways(square) == holders                   # still answers after apply, from its own record
    assert edits.Compound([edits.SetTags(way.id, {}, {}), edits.DeleteWay(new_way)]).ways(square) == {way.id, new_way}


# ------------------------------------------------- redrawing a stretch of a way

def line_square(n=8) -> tuple[Square, int, list[int]]:
    """A square with one open contour of n nodes running east."""
    sq = Square(name=SquareName(10, 10), present=True, attrs={})
    alloc = edits.IdAllocator(sq)
    ids = [alloc.take() for _ in range(n)]
    edits.AddWay(alloc.take(), ids, [(10.1 + 0.1 * i, 10.5) for i in range(n)], {'ele': '100'}).apply(sq)
    return sq, min(sq.ways), ids


def test_a_stretch_of_a_way_is_swapped_for_another_and_put_back():
    sq, wid, ids = line_square()
    alloc = edits.IdAllocator(sq)
    fresh = [alloc.take(), alloc.take()]
    for nid, lat in zip(fresh, (10.6, 10.7)):
        sq.nodes[nid] = Node(id=nid, lat=lat, lon=10.4)
    before = edits.snapshot(sq)
    cmd = edits.ReplaceSection(wid, 2, 5, [ids[2], *fresh, ids[5]])
    cmd.apply(sq)
    assert sq.ways[wid].refs == [ids[0], ids[1], ids[2], *fresh, ids[5], ids[6], ids[7]]
    assert all(n not in sq.nodes for n in (ids[3], ids[4]))     # what it replaced is gone
    assert sq.ways[wid].tags == {'ele': '100'} and sq.ways[wid].id == wid
    assert cmd.describe() == 'redraw 2 nodes as 2'
    cmd.undo(sq)
    assert edits.snapshot(sq) == before
    cmd.apply(sq)
    assert len(sq.ways[wid].refs) == 8                           # and again, the same


def test_a_node_the_rest_of_the_square_still_uses_is_not_deleted_with_the_stretch():
    sq, wid, ids = line_square()
    alloc = edits.IdAllocator(sq)
    other = alloc.take()
    edits.AddWay(other, [ids[3], alloc.take()], [(10.4, 10.5), (10.4, 11.0)], {'ele': '200'}).apply(sq)
    cmd = edits.ReplaceSection(wid, 2, 5, [ids[2], ids[5]])
    cmd.apply(sq)
    assert ids[3] in sq.nodes and ids[4] not in sq.nodes         # one is held by the 200 m way
    cmd.undo(sq)
    assert ids[4] in sq.nodes and sq.ways[wid].refs == ids


def test_a_ring_is_turned_so_a_stretch_over_its_join_is_one_run():
    sq = Square(name=SquareName(10, 10), present=True, attrs={})
    alloc = edits.IdAllocator(sq)
    ring = [alloc.take() for _ in range(6)]
    edits.AddWay(alloc.take(), ring, [(10.1 + 0.1 * i, 10.5 + 0.05 * (i % 3)) for i in range(6)], {'ele': '50'}).apply(sq)
    wid = min(sq.ways)
    sq.ways[wid].refs.append(ring[0])                            # closed
    assert edits.rotate_ring(sq.ways[wid].refs, 2) == [*ring[2:], ring[0], ring[1], ring[2]]
    before = edits.snapshot(sq)
    turn = edits.RotateRing(wid, 4)
    turn.apply(sq)
    w = sq.ways[wid]
    assert w.closed and len(w.refs) == 7 and w.refs[0] == ring[4]
    assert set(w.refs) == set(ring)                              # the same ring, cut elsewhere
    turn.undo(sq)
    assert edits.snapshot(sq) == before


def test_two_squares_of_a_set_never_mint_the_same_id():
    """A square's lowest id is positive unless something has been drawn in it,
    so an allocator built per square offers -1 to every one of them. A working
    set is many squares, and the first contour drawn in each then shares an id
    with the first drawn in the others.

    Harmless while nothing indexes on it. Not harmless once something does:
    the preview keys a way's last geometry on the id, so drawing in one square
    moved the surface in another; and the GeoPackage a build collects writes
    the id as osm_id, so a saved set already held two features claiming to be
    the same way.
    """
    a, b, c = fresh_square(), fresh_square(), fresh_square()
    hist = edits.SetUndoStack()
    minted = set()
    for sq in (a, b, c, a, b):
        alloc = hist.alloc(sq)
        for _ in range(3):
            i = alloc.take()
            assert i not in minted, f'id {i} was minted twice across the set'
            minted.add(i)
    assert len(minted) == 15
    assert all(i < 0 for i in minted), minted


def test_a_square_joining_later_does_not_invalidate_ids_already_given_out():
    """The allocator only ever moves down, so a square opened after some
    drawing has been done cannot be handed an id that is already in use -
    including one already in that square."""
    a = fresh_square()
    hist = edits.SetUndoStack()
    first = [hist.alloc(a).take() for _ in range(3)]

    b = fresh_square()
    b.ways[min(first) - 5] = b.ways[max(b.ways)]      # b already holds a lower id
    after = [hist.alloc(b).take() for _ in range(3)]
    assert min(first) > max(after), 'the allocator handed back out over ids in use'
    assert all(i < min(first) - 5 for i in after), (first, after)
