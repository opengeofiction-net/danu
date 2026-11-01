"""The layer's pick arrays and segment grid patched in place after an edit -
points moved, or a way's nodes changed, added or deleted - the same answers
as building them again, without the cost."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import SquareName

NORTH = SquareName(125, -23)


def add(w, pts, ele, ring=False):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in pts]
    w.editor.do(sq, edits.AddWay(wid, ids, pts, {'ele': str(ele)}))
    if ring:
        w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, ids[0]))
    return sq.ways[wid]


def by_way(layer):
    """The arrays and grid as each way has them, whatever order a build put
    the ways in."""
    layer._ensure_arrays()
    segs = {}
    for key, i in layer._way_at.items():
        s0 = layer._seg_start[i]
        n = len(layer._ways[i].pts) - 1
        segs[key] = (layer._seg_a[s0:s0 + n].tolist(), layer._seg_b[s0:s0 + n].tolist(),
                     layer._seg_lo[s0:s0 + n].tolist(), layer._seg_hi[s0:s0 + n].tolist())
    nodes = {key: layer._node_xy[j:j + len(layer._geoms[key].pts)].tolist() for key, j in layer._node_at.items()}
    grid = {}
    for cell, idx in layer._segment_grid().items():
        grid[cell] = sorted((layer._ways[int(layer._seg_way[k])].square.name, layer._ways[int(layer._seg_way[k])].way.id,
                             int(layer._seg_i[k])) for k in idx)
    return segs, nodes, grid


def rebuilt(layer):
    layer._arrays_stale = True
    return by_way(layer)


@pytest.fixture
def board(window):
    a = add(window, [(125.30, -22.75), (125.30, -22.65), (125.31, -22.60)], 100)
    b = add(window, [(125.34, -22.75), (125.35, -22.70), (125.34, -22.65)], 125)
    ring = add(window, [(125.40, -22.70), (125.42, -22.70), (125.41, -22.68)], 150, ring=True)
    layer = window.editor.layer
    by_way(layer)                                   # built, the grid with them
    return window, window.working_set.squares[NORTH], layer, a, b, ring


def test_a_node_moved_patches_the_arrays_to_what_a_build_makes(board):
    w, sq, layer, a, b, ring = board
    nid = b.refs[1]
    n = sq.nodes[nid]
    # far enough to leave its grid cells
    w.editor.do(sq, edits.MoveNode(nid, (n.lon, n.lat), (125.39, -22.62)))
    assert not layer._arrays_stale, 'built again, not patched'
    assert by_way(layer) == rebuilt(layer)


def test_nodes_moved_together_and_a_ring_turned_patch_too(board):
    w, sq, layer, a, b, ring = board
    moves = [edits.MoveNode(r, (sq.nodes[r].lon, sq.nodes[r].lat),
                            (sq.nodes[r].lon + 0.05, sq.nodes[r].lat - 0.03)) for r in dict.fromkeys(ring.refs)]
    w.editor.do(sq, edits.Compound(moves, 'moved'))
    assert not layer._arrays_stale
    assert by_way(layer) == rebuilt(layer)
    w.editor.undo()
    assert not layer._arrays_stale
    assert by_way(layer) == rebuilt(layer)


def test_an_edit_that_changes_a_ways_nodes_patches_them_too(board):
    """A node put in, a way drawn, one deleted, and each undone: the old
    emptied and the new appended - and picked, and crossed, where they are."""
    w, sq, layer, a, b, ring = board
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.InsertNode(a.id, 1, alloc.take(), (125.305, -22.70)))
    assert not layer._arrays_stale, 'built again, not patched'
    assert by_way(layer) == rebuilt(layer)
    c = add(w, [(125.36, -22.62), (125.36, -22.58)], 175)
    # a line across b's middle segment, square to it
    (x, y), (qx, qy) = layer.node_xy(sq, b.refs[1]), layer.node_xy(sq, b.refs[2])
    mx, my, dx, dy = (x + qx) / 2, (y + qy) / 2, qx - x, qy - y
    across = [(mx - dy * 0.1, my + dx * 0.1), (mx + dy * 0.1, my - dx * 0.1)]
    assert layer.crossed_by(across) == {(NORTH, b.id)}
    w.editor.do(sq, edits.DeleteWay(b.id))
    assert not layer._arrays_stale
    assert by_way(layer) == rebuilt(layer)
    assert layer.crossed_by(across) == set(), 'a deleted way crossed still'
    x, y = layer.node_xy(sq, c.refs[0])
    assert layer.pick_node(x, y, 1.0)[1] == c.refs[0], 'a drawn way not picked'
    for _ in range(3):
        w.editor.undo()
        assert not layer._arrays_stale
        assert by_way(layer) == rebuilt(layer)


def test_past_their_share_emptied_the_arrays_are_built_whole(board, monkeypatch):
    w, sq, layer, a, b, ring = board
    monkeypatch.setattr(type(layer), 'DEAD_SHARE', 0.0)
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.InsertNode(a.id, 1, alloc.take(), (125.305, -22.70)))
    assert layer._arrays_stale
    assert by_way(layer) == rebuilt(layer) and layer._dead_segs == 0


def test_a_moved_node_is_picked_where_it_is_now(board):
    w, sq, layer, a, b, ring = board
    nid = b.refs[1]
    n = sq.nodes[nid]
    w.editor.do(sq, edits.MoveNode(nid, (n.lon, n.lat), (125.39, -22.62)))
    x, y = layer.node_xy(sq, nid)
    hit = layer.pick_node(x, y, 1.0)
    assert hit is not None and hit[1] == nid
    # across the middle of a segment that moved, square to it
    qx, qy = layer.node_xy(sq, b.refs[2])
    mx, my, dx, dy = (x + qx) / 2, (y + qy) / 2, qx - x, qy - y
    assert layer.crossed_by([(mx - dy * 0.1, my + dx * 0.1), (mx + dy * 0.1, my - dx * 0.1)]) == {(NORTH, b.id)}


def test_a_box_asked_by_the_grid_is_what_every_segment_asked_says(board):
    """Once the grid is there, a box's segments are its cells' - the same
    segments, ascending, as the comparisons over all of them."""
    import random
    w, sq, layer, a, b, ring = board
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.InsertNode(a.id, 1, alloc.take(), (125.305, -22.70)))   # patched, some emptied
    layer._segment_grid()
    xs = [layer.node_xy(sq, r) for way in (a, b, ring) for r in sq.ways[way.id].refs]
    random.seed(4)
    for _ in range(200):
        x, y = random.choice(xs)
        r = random.choice((0.5, 50.0, 3000.0, 1e6))          # the last over more cells than the grid asks
        box = (x - r, y - r * random.random(), x + r * random.random(), y + r)
        by_grid = layer._segments_in(*box)
        grid, layer._seg_grid = layer._seg_grid, None
        by_all = layer._segments_in(*box)
        layer._seg_grid = grid
        assert by_grid.tolist() == by_all.tolist()


def test_a_grid_first_built_after_a_patch_leaves_out_what_it_emptied(board):
    """The grid built when first asked, after a patch emptied a way's
    segments: those are in no cell, and the rest are where a build puts them."""
    w, sq, layer, a, b, ring = board
    layer._seg_grid = None
    alloc = w.editor.history.alloc(sq)
    w.editor.do(sq, edits.InsertNode(a.id, 1, alloc.take(), (125.305, -22.70)))
    assert layer._dead_segs and layer._seg_grid is None
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert by_way(layer) == rebuilt(layer)
