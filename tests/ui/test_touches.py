"""The checks panel's third check - contours that touch or lie on one
another - and U to unglue a shared node (G8e).

In the fixture's blank square to the north: a 125 m V whose tip is a node of
the 100 m line, and a 150 m running 30 cm along a 175 m. The golden square
holds 39 contours duplicated whole, which the check lists too: the rows read
here are the north square's.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way

NORTH = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540
_ids = iter(range(-9000, -5001))


def nodes(sq, pts):
    out = []
    for lon, lat in pts:
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
        out.append(i)
    return out


def way(sq, refs, ele):
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=list(refs), tags={'ele': str(ele)})
    return sq.ways[i]


@pytest.fixture
def touching(window, qtbot):
    sq = window.working_set.squares[NORTH]
    a, b, c = nodes(sq, [(125.30, LAT), (125.31, LAT), (125.32, LAT)])
    line = way(sq, [a, b, c], 100)
    v = way(sq, [nodes(sq, [(125.305, LAT + 0.01)])[0], b, nodes(sq, [(125.315, LAT + 0.01)])[0]], 125)
    window.contours.set_working_set(window.working_set)
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.touch_index is not None, timeout=5000)
    return window, sq, line, v, b


def rows(dock):
    items = [dock.touches_tree.topLevelItem(i) for i in range(dock.touches_tree.topLevelItemCount())]
    return [it.text(0) for it in items if it.data(0, 256).a[0] == NORTH]


def choose(w):
    dock = w.checks_dock
    item = next(dock.touches_tree.topLevelItem(i) for i in range(dock.touches_tree.topLevelItemCount())
                if dock.touches_tree.topLevelItem(i).data(0, 256).a[0] == NORTH)
    dock.touches_tree.setCurrentItem(item)


def test_the_panel_lists_a_node_two_levels_share(touching):
    w, sq, line, v, b = touching
    (row,) = rows(w.checks_dock)
    assert f'share node {b}' in row
    assert '1 node two levels share' in w.checks_dock.touches_summary.text()


def test_choosing_it_selects_the_contour_at_the_node_and_u_unglues_it(touching, qtbot):
    w, sq, line, v, b = touching
    before = edits.snapshot(sq)
    choose(w)
    sel = w.editor.selection
    assert sel.node == b and sel.way.id in (line.id, v.id)
    assert 'U unglues it' in w.statusBar().currentMessage()
    w.edit_actions['edit.unglue'].trigger()
    assert 'unglued 1 contour from the node' in w.statusBar().currentMessage()
    assert len({id(x) for x in sq.ways.values() if b in x.refs}) == 1
    qtbot.waitUntil(lambda: rows(w.checks_dock) == [], timeout=2000)
    assert 'two levels share' not in w.checks_dock.touches_summary.text()
    w.editor.undo()
    assert edits.snapshot(sq) == before
    qtbot.waitUntil(lambda: len(rows(w.checks_dock)) == 1, timeout=2000)


def test_a_stretch_of_one_level_on_another_is_listed(window, qtbot):
    sq = window.working_set.squares[NORTH]
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT + 0.05) for j in range(4)]), 175)
    way(sq, nodes(sq, [(125.30 + 0.005 * j, LAT + 0.05 + 0.3 * M_LAT) for j in range(4)]), 150)
    window.contours.set_working_set(window.working_set)
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.touch_index is not None, timeout=5000)
    (row,) = rows(window.checks_dock)
    assert 'on top of' in row
    assert '1 stretch of one level on another' in window.checks_dock.touches_summary.text()


def test_u_with_no_node_chosen_says_how(window):
    window.editor.selection = None
    window.edit_actions['edit.unglue'].trigger()
    assert 'choose a node contours share' in window.statusBar().currentMessage()


def test_u_is_the_key(window):
    assert window.edit_actions['edit.unglue'].shortcut().toString() == 'U'
