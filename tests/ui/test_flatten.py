"""Flattening a lake from the editor - G7a, R26.

In the fixture's blank square to the north: a lake as a relation, a contour
in its water, one crossing its shore and one beside it, so what F proposes,
what Enter does and what Ctrl+Z takes back can each be counted.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Member, Node, Relation, SquareName, Way
from danu.ui import mercator as m
from danu.ui.tools import Selection
from danu.water import flatten

NORTH = SquareName(125, -23)
_ids = iter(range(-9000, -5001))


def node(sq, lon, lat):
    i = next(_ids)
    sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
    return i


def way(sq, pts, tags, closed=False):
    refs = [node(sq, lon, lat) for lon, lat in pts]
    if closed:
        refs.append(refs[0])
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags=dict(tags))
    return sq.ways[i]


def box(lon0, lat0, d):
    return [(lon0, lat0), (lon0 + d, lat0), (lon0 + d, lat0 + d), (lon0, lat0 + d)]


@pytest.fixture
def lake(window):
    sq = window.working_set.squares[NORTH]
    ring = way(sq, box(125.50, -22.50, 0.04), {}, closed=True)
    rel = Relation(id=next(_ids), tags={'natural': 'water', 'name': 'Kinser', 'ele': '100'},
                   members=[Member('way', ring.id, 'outer')])
    sq.relations[rel.id] = rel
    way(sq, box(125.51, -22.49, 0.01), {'ele': '90'}, closed=True)         # in the water
    way(sq, [(125.45, -22.48), (125.59, -22.48)], {'ele': '120'})           # across the shore
    way(sq, [(125.45, -22.60), (125.59, -22.60)], {'ele': '75'})            # nowhere near
    window.contours.set_working_set(window.working_set)
    return window, sq, rel, ring


def select(w, sq, rel):
    w.editor.selection = Selection(sq, None, relation=rel)


def test_f_proposes_and_enter_flattens_as_one_step(lake):
    w, sq, rel, ring = lake
    before = edits.snapshot(sq)
    select(w, sq, rel)
    w.editor.flatten()
    p = w.editor.proposal
    assert p is not None and p.acceptable
    assert 'Kinser flattened at 100 m' in p.summary and '1 contour in the water removed' in p.summary
    assert '1 crossing its shore drawn back 100 m' in p.summary and 'fill lines' in p.summary
    assert w.selection_panel.pull_back_row.isVisible() and w.selection_panel.pull_back.value() == 100
    assert edits.snapshot(sq) == before, 'proposing changed the square'
    w.editor.accept_proposal()
    assert sq.ways[ring.id].tags['ele'] == '100'
    assert [x for x in sq.ways.values() if x.tags.get('ele') == '90'] == []
    assert flatten.fills(sq, rel)
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not take the whole flatten back'


def test_the_draw_back_distance_is_tried_before_it_is_accepted(lake):
    w, sq, rel, _ = lake
    select(w, sq, rel)
    w.editor.flatten()
    w.selection_panel.pull_back.setValue(300)
    assert 'drawn back 300 m' in w.editor.proposal.summary
    w.editor.accept_proposal()
    west = min((x for x in sq.ways.values() if x.tags.get('ele') == '120'),
               key=lambda x: sq.nodes[x.refs[0]].lon)
    end = max(sq.nodes[r].lon for r in west.refs)
    assert (125.50 - end) * 111320 * 0.9235 == pytest.approx(300, abs=2)


def test_a_lake_with_no_level_is_refused_with_the_way_to_give_it_one(lake):
    w, sq, rel, _ = lake
    del rel.tags['ele']
    select(w, sq, rel)
    w.editor.flatten()
    assert w.editor.proposal is None
    assert 'no level yet' in w.statusBar().currentMessage()


def test_a_flattened_lake_is_still_water_and_its_fill_lines_are_not_contours(lake):
    w, sq, rel, ring = lake
    select(w, sq, rel)
    w.editor.flatten()
    w.editor.accept_proposal()
    layer = w.contours
    assert (NORTH, ring.id) in layer.water, 'its shore became a contour'
    lines = flatten.fills(sq, rel)
    assert all((NORTH, x.id) in layer.fills for x in lines), 'the fill lines are not drawn'
    assert not any((NORTH, x.id) in layer.water for x in lines), 'a fill line is pickable as water'
    # a click on the shore is the lake; one on a fill line is not a contour
    x, y = m.lonlat_to_scene(125.50, -22.48)
    hit = layer.pick_water(x, y, 50)
    assert hit is not None and hit[1].id == ring.id
    a = sq.nodes[lines[0].refs[0]]
    fx, fy = m.lonlat_to_scene(a.lon + 0.01, a.lat)
    picked = layer.pick(fx, fy, 5)
    assert picked is None or picked[1].id not in {x.id for x in lines}
    assert all(x.id not in {c.id for c in sq.contours()} for x in lines)


def test_a_new_level_carries_to_the_outline_and_fill_lines_in_one_step(lake):
    w, sq, rel, ring = lake
    select(w, sq, rel)
    w.editor.flatten()
    w.editor.accept_proposal()
    assert w.editor.set_ele(110.0)
    assert sq.ways[ring.id].tags['ele'] == '110'
    assert {x.tags['ele'] for x in flatten.fills(sq, rel)} == {'110'}
    assert 'F flattens it again' in w.statusBar().currentMessage()
    w.editor.undo()
    assert rel.tags['ele'] == '100' and sq.ways[ring.id].tags['ele'] == '100'
    assert {x.tags['ele'] for x in flatten.fills(sq, rel)} == {'100'}


def test_clearing_the_level_takes_the_outline_level_and_the_fill_lines(lake):
    w, sq, rel, ring = lake
    select(w, sq, rel)
    w.editor.flatten()
    w.editor.accept_proposal()
    assert w.editor.set_ele(None)
    assert 'ele' not in rel.tags and 'ele' not in sq.ways[ring.id].tags
    assert flatten.fills(sq, rel) == []


def test_the_flatten_button_is_for_lakes(lake):
    w, sq, rel, _ = lake
    p = w.selection_panel
    select(w, sq, rel)
    assert p.flatten_btn.isVisible()
    p.flatten_btn.click()
    assert w.editor.proposal is not None and 'flattened' in w.editor.proposal.summary
    w.editor.selection = Selection(sq, next(x for x in sq.ways.values() if x.tags.get('ele') == '75'))
    assert not p.flatten_btn.isVisible()
    assert w.edit_actions['edit.flatten'].shortcut().toString() == 'F'


# --------------------------------------------- a re-import reshapes, G7a-bis

def lake_answer(dx=0.0):
    """Upstream's answer: a lake as a relation, ids positive as imported."""
    from danu.water import overpass
    water = overpass.Water()
    for k, (lon, lat) in enumerate(box(125.50, -22.50, 0.04), 1):
        water.nodes[k] = Node(id=k, lon=lon + (dx if k == 2 else 0.0), lat=lat)
    water.ways[100] = Way(id=100, refs=[1, 2, 3, 4, 1])
    water.relations[300] = Relation(id=300, tags={'natural': 'water', 'name': 'Kinser'},
                                    members=[Member('way', 100, 'outer')])
    return water


def imported(window, water):
    from danu.ui.water import Answer
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways),
                                  frozenset(water.relations)), window.working_set)


def test_a_reimport_that_reshapes_a_flattened_lake_lists_it_to_flatten_again(window):
    sq = window.working_set.squares[NORTH]
    imported(window, lake_answer())
    rel = sq.relations[300]
    select(window, sq, rel)
    assert window.editor.set_ele(100.0)
    window.editor.flatten()
    window.editor.accept_proposal()
    imported(window, lake_answer())                     # the same shore again
    assert window.reshaped == []
    imported(window, lake_answer(dx=0.002))             # upstream moved a corner
    assert [(r.kind, r.id) for r in window.reshaped] == [('relation', 300)]
    assert 'reshaped, to flatten again' in window.statusBar().currentMessage()
    dock = window.gone_dock
    head = next(dock.tree.topLevelItem(i) for i in range(dock.tree.topLevelItemCount())
                if 'reshaped upstream' in dock.tree.topLevelItem(i).text(0))
    row = head.child(0)
    assert 'Kinser' in row.text(0)
    dock.tree.setCurrentItem(row)
    assert window.editor.selection is not None and window.editor.selection.relation.id == 300
    assert 'F flattens it again' in window.statusBar().currentMessage()
    window.editor.flatten()
    window.editor.accept_proposal()
    assert row.font(0).strikeOut(), 'flattened again, and the row did not say so'


def test_a_reimport_with_nothing_flattened_reports_no_reshaping(window):
    imported(window, lake_answer())
    imported(window, lake_answer(dx=0.002))
    assert window.reshaped == []


def test_f_from_the_menu_flattens_at_the_distance_set_not_at_none(lake):
    """The action's triggered signal passes checked=False, and connected to
    flatten directly it was taken for a pull-back of 0 m."""
    w, sq, rel, _ = lake
    select(w, sq, rel)
    w.edit_actions['edit.flatten'].trigger()
    assert w.editor.pull_back_m == 100 and 'drawn back 100 m' in w.editor.proposal.summary
