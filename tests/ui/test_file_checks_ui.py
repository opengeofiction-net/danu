"""The checks panel's file findings - H1a. In the fixture's blank square to
the north."""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way

NORTH = SquareName(125, -23)
_ids = iter(range(-90000, -10000))


def line(sq, n, tags, lat):
    refs = []
    for k in range(n):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=125.1 + k * 0.8 / n, lat=lat)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags=tags)
    return sq.ways[i]


def rows(dock):
    return {dock.node(k).text(0): dock.rows(k) for k in ('long', 'ele', 'ladder')}


@pytest.fixture
def north(window, qtbot):
    w = window
    sq = w.working_set.squares[NORTH]
    for k, ele in enumerate((100, 100, 125, 125, 150, 150, 175, 175)):
        line(sq, 3, {'ele': str(ele)}, -22.95 + k * 0.05)
    long_ = line(sq, 2001, {'ele': '150'}, -22.3)
    lake = line(sq, 4, {'natural': 'water', 'name': 'Kettle Lake', 'ele': '1,853 Ft'}, -22.2)
    odd = line(sq, 3, {'ele': '113'}, -22.1)
    w.contours.set_working_set(w.working_set)
    w.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: w.file_index is not None, timeout=5000)
    return w, sq, long_, lake, odd


def test_the_panel_lists_them_under_a_heading_a_kind(north):
    w, sq, long_, lake, odd = north
    heads = rows(w.checks_dock)
    assert [h.rsplit(' (', 1)[0] for h in heads] == ['Ways too long', 'Ele not a number', 'Off the ladder']
    mine = {h.rsplit(' (', 1)[0]: [r.data(0, 256).way or r.data(0, 256).node for r in v
                                    if r.data(0, 256).square == NORTH] for h, v in heads.items()}
    assert list(mine.values()) == [[long_.id], [lake.id], [odd.id]]
    assert 'save splits them' in w.checks_dock.node('long').toolTip(0)


def test_choosing_a_row_selects_it_and_an_edit_takes_it_off(north):
    w, sq, long_, lake, odd = north
    (row,) = [r for h, v in rows(w.checks_dock).items() if h.startswith('Off the ladder')
              for r in v if r.data(0, 256).square == NORTH]
    w.checks_dock.tree.setCurrentItem(row)
    assert w.editor.selection.way is odd and 'mistyped' in w.statusBar().currentMessage()
    w.editor.do(sq, edits.SetTags(odd.id, dict(odd.tags), {'ele': '125'}))
    w._refresh_checks()
    assert not [r for h, v in rows(w.checks_dock).items() if h.startswith('Off the ladder')
                for r in v if r.data(0, 256).square == NORTH]
