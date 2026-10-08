"""The checks panel's fourth list - a spot height the rings round it
contradict (R38). In the fixture's blank square to the north."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way

NORTH = SquareName(125, -23)


_ids = iter(range(-9000, -5001))


def ring(sq, cx, cy, r, ele):
    """A closed contour, built in the square as the touches tests build theirs."""
    refs = []
    for dx, dy in ((-r, -r), (r, -r), (r, r), (-r, r)):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=cx + dx, lat=cy + dy)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[*refs, refs[0]], tags={'ele': str(ele)})


def rows(dock):
    items = [dock.spots_tree.topLevelItem(i) for i in range(dock.spots_tree.topLevelItemCount())]
    return [it.text(0) for it in items if it.data(0, 256).square == NORTH]


@pytest.fixture
def peak(window, qtbot):
    w = window
    sq = w.working_set.squares[NORTH]
    for r, ele in ((0.03, 100), (0.02, 125), (0.01, 150)):
        ring(sq, 125.5, -22.5, r, ele)
    w.contours.set_working_set(w.working_set)
    nid = w.editor.history.alloc(sq).take()
    w.editor.do(sq, edits.AddNode(nid, (125.5, -22.5), {'ele': '149', 'name': 'Nate Peak'}))
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.spot_index is not None, timeout=5000)
    return w, sq, nid


def test_the_panel_lists_it_and_choosing_it_selects_it(peak):
    w, sq, nid = peak
    assert rows(w.checks_dock) == ['Nate Peak 149 m - below the 150 m ring round it']
    dock = w.checks_dock
    item = next(dock.spots_tree.topLevelItem(i) for i in range(dock.spots_tree.topLevelItemCount())
                if dock.spots_tree.topLevelItem(i).data(0, 256).square == NORTH)
    dock.spots_tree.setCurrentItem(item)
    sel = w.editor.selection
    assert sel.way is None and sel.node == nid
    assert 'set its height' in w.statusBar().currentMessage()


def test_setting_its_height_takes_it_off_the_list(peak, qtbot):
    w, sq, nid = peak
    n = sq.nodes[nid]
    w.editor.do(sq, edits.SetNodeTags(nid, dict(n.tags), {**n.tags, 'ele': '160'}))
    qtbot.waitUntil(lambda: rows(w.checks_dock) == [], timeout=2000)
    w.editor.undo()
    qtbot.waitUntil(lambda: len(rows(w.checks_dock)) == 1, timeout=2000)
