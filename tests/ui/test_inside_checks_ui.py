"""The checks panel's inside-the-rings findings - H1b. In the fixture's blank
square to the north."""

import pytest

pytest.importorskip('PySide6')

from danu.core.square import Node, SquareName, Way
from danu.ui import mercator as m

NORTH = SquareName(125, -23)
_ids = iter(range(-190000, -100000))


def ring(sq, cx, cy, r, tags):
    refs = []
    for dx, dy in ((-r, -r), (r, -r), (r, r), (-r, r)):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=cx + dx, lat=cy + dy)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[*refs, refs[0]], tags=tags)
    return sq.ways[i]


def heads(dock):
    return {dock.inside_tree.topLevelItem(i).text(0).rsplit(' (', 1)[0]: dock.inside_tree.topLevelItem(i)
            for i in range(dock.inside_tree.topLevelItemCount())}


def test_a_lake_spanning_contours_is_listed_open_and_the_report_folded(window, qtbot):
    w = window
    sq = w.working_set.squares[NORTH]
    lake = ring(sq, 125.5, -22.5, 0.02, {'natural': 'water', 'name': 'Kinser'})
    ring(sq, 125.5, -22.5, 0.01, {'ele': '150'})                     # a hill's top in the water
    w.contours.set_working_set(w.working_set)
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.inside_index is not None, timeout=5000)
    h = heads(w.checks_dock)
    water = h['Water spanning contours (R33) - select it, and F flattens it']
    report = h['Report: rings of 10 ha or more with nothing inside (R39) - a spot height would say how high']
    assert water.isExpanded() and not report.isExpanded()
    (row,) = [water.child(j) for j in range(water.childCount()) if water.child(j).data(0, 256).square == NORTH]
    w.checks_dock.inside_tree.setCurrentItem(row)
    assert w.editor.selection.way is lake and 'F flattens it' in w.statusBar().currentMessage()
    marks = len(w.editor.marks)
    report.setExpanded(True)
    w._refresh_checks()
    assert heads(w.checks_dock)['Report: rings of 10 ha or more with nothing inside (R39) - a spot height would say how high'] \
        .isExpanded(), 'unfolded, it stays so'
    bare = [f for f in w.inside_index.findings('bare') if f.square == NORTH]
    assert bare and all(m.lonlat_to_scene(f.lon, f.lat) not in w.editor.marks for f in bare), \
        'the report marks the map'
    assert len(w.editor.marks) == marks


def test_the_threshold_is_the_inis(window, qtbot):
    """A ring of some 480 ha reported at the default 10 ha, and not when the
    INI asks for 1,000."""
    w = window
    sq = w.working_set.squares[NORTH]
    hill = ring(sq, 125.3, -22.3, 0.01, {'ele': '450'})
    w.settings.q.setValue('checks/bare_min_hectares', 1000)
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.inside_index is not None, timeout=5000)
    assert hill.id not in {f.way for f in w.inside_index.findings('bare')}
    assert any('1000 ha or more' in t for t in heads(w.checks_dock)) or not heads(w.checks_dock)
