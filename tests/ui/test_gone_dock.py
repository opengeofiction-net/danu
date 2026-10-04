"""The gone-from-upstream dock - R40's report where a mapper can work it, G5c.

Choosing a row selects the feature as the map would and brings it into view;
the editor's own Shift+Delete does the rest, a lake with its untagged rings;
Ctrl+Z puts it back; the row strikes through and comes back with it.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtGui import QColor, QImage, QPainter

from danu.core.square import Member, Node, Relation, SquareName, Way
from danu.water.gone import Gone, gone

HERE = SquareName(125, -24)


def a_gone_lake(square):
    """A lake gone upstream, with an untagged outer ring, and a river gone
    with it - placed on ground the fixture square holds."""
    for i, (lon, lat) in enumerate(((125.40, -23.60), (125.46, -23.60),
                                    (125.46, -23.54), (125.40, -23.54)), 9101):
        square.nodes[i] = Node(id=i, lon=lon, lat=lat)
    square.ways[9200] = Way(id=9200, refs=[9101, 9102, 9103, 9104, 9101])
    square.relations[9300] = Relation(id=9300, tags={'natural': 'water', 'name': 'Kinser'},
                                      members=[Member('way', 9200, 'outer')])
    for i, lon in enumerate((125.20, 125.25, 125.30), 9111):
        square.nodes[i] = Node(id=i, lon=lon, lat=-23.30)
    square.ways[9400] = Way(id=9400, refs=[9111, 9112, 9113],
                            tags={'waterway': 'river', 'name': 'Old Bed'})


def reported(window):
    sq = window.working_set.squares[HERE]
    a_gone_lake(sq)
    report = gone(window.working_set, frozenset(), frozenset())
    window.gone_dock.show_report(report)
    return sq, report


def rows(dock):
    out = []
    for i in range(dock.tree.topLevelItemCount()):
        top = dock.tree.topLevelItem(i)
        out.append((top.text(0), [top.child(j).text(0) for j in range(top.childCount())]))
    return out


def choose(dock, kind, fid):
    for i in range(dock.tree.topLevelItemCount()):
        top = dock.tree.topLevelItem(i)
        for item in [top] + [top.child(j) for j in range(top.childCount())]:
            g = item.data(0, 256)
            if g.kind == kind and g.id == fid:
                dock.tree.setCurrentItem(item)
                return item
    raise AssertionError(f'no row for {kind} {fid}')


# ----------------------------------------------------------------- listing

def test_a_lakes_rings_are_listed_under_the_lake(window):
    _, report = reported(window)
    got = rows(window.gone_dock)
    lake = next(r for r in got if 'Kinser' in r[0])
    assert any('lake ring' in c for c in lake[1]), 'the ring is not under its lake'
    assert any('Old Bed' in r[0] for r in got)
    assert sum(len(c) for _, c in got) + len(got) == len(report), 'a row went missing'


def test_a_ring_whose_lake_is_still_upstream_stands_on_its_own(window):
    """A ring upstream replaced: its lake is not in the report, so there is
    nothing to put it under."""
    window.gone_dock.show_report([Gone(HERE, 'way', 9200, None, 'lake ring', 9300)])
    assert rows(window.gone_dock) == [(f'lake ring - way 9200 in {HERE}', [])]


def test_an_empty_report_says_so(window):
    window.gone_dock.show_report([])
    assert window.gone_dock.stack.currentWidget() is window.gone_dock.empty


# --------------------------------------------------------------- choosing

def test_choosing_a_river_selects_it_and_brings_it_into_view(window):
    w = window
    sq, _ = reported(w)
    w.map.set_zoom(5)
    choose(w.gone_dock, 'way', 9400)
    sel = w.editor.selection
    assert sel is not None and sel.way is sq.ways[9400] and sel.relation is None
    assert w.map.zoom > 5, 'the map did not come to it'
    lon, lat = w.map.center_lonlat()
    assert 125.15 < lon < 125.35 and -23.4 < lat < -23.2
    assert 'removes it' in w.statusBar().currentMessage()


def test_choosing_a_lake_selects_the_lake_and_it_is_drawn(window):
    """Read from pixels, not from the selection: a selected lake has to be
    seen. The halo is orange at alpha 140, which over this map's grey comes
    out (246, 183, 106) - measured from the rendering, after a first guess at
    the colour said the lake was not drawn when it plainly was."""
    w = window
    sq, _ = reported(w)
    choose(w.gone_dock, 'relation', 9300)
    sel = w.editor.selection
    assert sel is not None and sel.relation is sq.relations[9300] and sel.way is None
    img = QImage(w.map.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    p = QPainter(img)
    w.map.render(p)
    p.end()
    orange = sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
                 if (c := img.pixelColor(x, y)).red() > 230
                 and c.red() - c.blue() > 100 and 160 < c.green() < 205)
    assert orange > 50, f'the selected lake was not drawn ({orange} orange samples)'


def test_choosing_a_row_deleted_since_says_so(window):
    w = window
    sq, _ = reported(w)
    del sq.ways[9400]
    w.editor.selection = None
    choose(w.gone_dock, 'way', 9400)
    assert w.editor.selection is None
    assert 'deleted here since the import' in w.statusBar().currentMessage()


# ------------------------------------------------- the editor does the rest

@pytest.mark.parametrize('action', ['delete_way', 'delete_selected'])
def test_deleting_a_chosen_lake_takes_its_rings_and_ctrl_z_brings_them_back(window, action):
    """Both delete keys: Delete on a relation used to reach `sel.way.id` and
    raise, since a relation selection has no way."""
    w = window
    sq, _ = reported(w)
    choose(w.gone_dock, 'relation', 9300)
    getattr(w.editor, action)()
    assert 9300 not in sq.relations and 9200 not in sq.ways
    assert w.editor.selection is None
    assert 'Kinser' in w.statusBar().currentMessage() or 'Kinser' in w.editor.history.describe_undo()
    lake_row = choose(w.gone_dock, 'relation', 9300)
    assert lake_row.font(0).strikeOut(), 'the deleted lake was not struck through'

    w.editor.undo()
    assert 9300 in sq.relations and 9200 in sq.ways, 'Ctrl+Z did not put the lake back'
    assert not lake_row.font(0).strikeOut(), 'the row stayed struck through after the undo'


def test_undoing_away_a_selected_lake_clears_the_selection(window):
    """The selection must not outlive what it selected: a relation selection
    is cleared when an undo takes the relation, as a way selection is."""
    from danu.core import edits
    w = window
    sq, _ = reported(w)
    w.editor.do(sq, edits.DeleteRelation(9300))
    w.editor.undo()
    choose(w.gone_dock, 'relation', 9300)
    assert w.editor.selection is not None
    w.editor.redo()
    assert w.editor.selection is None, 'the selection outlived the relation'


# ------------------------------------------------- the import shows it

def test_an_import_that_finds_something_gone_raises_the_dock(window):
    from danu.ui.water import Answer
    w = window
    a_gone_lake(w.working_set.squares[HERE])
    assert not w.gone_dock.isVisible()
    w._water_imported(Answer({}, frozenset(), frozenset()), w.working_set)
    assert w.gone_dock.isVisible(), 'the report was made and not shown'
    assert len(w.gone_dock.report) == 3


def test_an_import_that_finds_nothing_gone_does_not(window):
    from danu.ui.water import Answer
    w = window
    w._water_imported(Answer({}, frozenset(), frozenset()), w.working_set)
    assert not w.gone_dock.isVisible()


def test_opening_another_set_clears_the_report(window):
    """The report names squares of the set it was made against."""
    w = window
    reported(w)
    w._loaded(w.working_set)
    assert w.gone_from_upstream == [] and w.gone_dock.report == []
