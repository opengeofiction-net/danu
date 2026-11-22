"""The Validation panel's landform rows - #191. In the fixture's blank square
to the north: a cliff drawn backwards between two contours, chosen from the
panel and reversed with R, and a peak with no height."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName

NORTH = SquareName(125, -23)
LAT = -22.5
D = 0.0009


def slope(sq):
    alloc = edits.IdAllocator(sq)

    def way(pts, tags):
        ids = [alloc.take() for _ in pts]
        wid = alloc.take()
        edits.AddWay(wid, ids, pts, tags).apply(sq)
        return wid

    way([(125.40 + 0.01 * i, LAT - D / 2) for i in range(21)], {'ele': '200'})
    way([(125.40 + 0.01 * i, LAT + D / 2) for i in range(21)], {'ele': '225'})
    # east to west: its right is the north, the 225 m side - backwards
    return way([(125.50 - 0.01 * i, LAT) for i in range(6)], {'natural': 'cliff'})


def rows(dock, check):
    node = dock.node(check)
    return [node.child(j) for j in range(node.childCount())]


def test_a_backwards_cliff_is_listed_chosen_and_reversed(window, qtbot):
    w = window
    sq = w.working_set.squares[NORTH]
    cid = slope(sq)
    sq.nodes[-9001] = Node(id=-9001, lon=125.3, lat=LAT, tags={'natural': 'peak'})
    w.contours.set_working_set(w.working_set)
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.landform_index is not None, timeout=5000)
    dock = w.checks_dock
    assert dock.node('cliff_back').text(0).startswith('Cliffs drawn backwards')
    (row,) = rows(dock, 'cliff_back')
    assert not rows(dock, 'cliff_cross')
    assert [r.data(0, 256).node for r in rows(dock, 'no_height')] == [-9001]
    dock.tree.setCurrentItem(row)
    assert w.editor.selection.way is sq.ways[cid] and 'R reverses it' in w.statusBar().currentMessage()
    w.edit_actions['edit.reverse_coastline'].trigger()
    w._refresh_checks()
    assert not rows(dock, 'cliff_back'), 'still listed once reversed'
    w.editor.undo()
    w._refresh_checks()
    assert len(rows(dock, 'cliff_back')) == 1
