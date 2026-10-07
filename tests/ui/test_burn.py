"""Burning a climb from the editor - G7b, R25.

In the fixture's blank square to the north: a river imported as a mapper
would, running east and down across north-south contours, and a 100 m finger
it climbs onto. G grades it and lists the climb; B burns the one chosen.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core import edits
from danu.core.square import Node, SquareName, Way
from danu.ui.tools import Selection
from danu.ui.water import Answer
from danu.water import overpass

NORTH = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540


def draw(w, pts, ele):
    sq = w.working_set.squares[NORTH]
    alloc = w.editor.history.alloc(sq)
    wid = alloc.take()
    w.editor.do(sq, edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': str(ele)}))
    return sq.ways[wid]


@pytest.fixture
def climbing(window):
    water = overpass.Water()
    for k in range(41):
        water.nodes[k + 1] = Node(id=k + 1, lon=125.30 + 0.0025 * k + 0.0001, lat=LAT)
    water.ways[100] = Way(id=100, refs=list(range(1, 42)), tags={'waterway': 'river', 'name': 'Bosco'})
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways), frozenset()), window.working_set)
    for lon, ele in ((125.31, 100), (125.33, 75), (125.39, 50)):
        draw(window, [(lon, LAT - 0.02), (lon, LAT + 0.02)], ele)
    finger = draw(window, [(125.345, LAT + 0.02), (125.345, LAT - 0.01), (125.365, LAT - 0.01),
                           (125.365, LAT + 0.02)], 100)
    sq = window.working_set.squares[NORTH]
    window.editor.selection = Selection(sq, sq.ways[100])
    window.editor.grade()
    return window, sq, finger


def climb(w):
    return next(i for i in w.editor.proposal.issues if i.kind == 'climb')


def test_b_on_the_climb_chosen_proposes_the_burn_and_enter_does_it_in_one_step(climbing):
    w, sq, finger = climbing
    before = edits.snapshot(sq)
    w.editor.show_issue(climb(w))
    w.editor.burn()
    p = w.editor.proposal
    assert p.kind == 'burn' and p.acceptable
    assert p.summary.startswith('burn: 1 climb, 1 contour cut and closed along the river 50 m a step back')
    assert p.added and p.removed, 'the new lines and what goes are not shown'
    assert edits.snapshot(sq) == before, 'proposing changed the square'
    w.editor.accept_proposal()
    assert min(sq.nodes[r].lat for r in sq.ways[finger.id].refs) == pytest.approx(LAT + 50 * M_LAT, abs=1e-6)
    w.editor.undo()
    assert edits.snapshot(sq) == before, 'one Ctrl+Z did not take the burn back'


def test_the_setback_is_tried_before_it_is_accepted(climbing):
    w, sq, finger = climbing
    w.editor.show_issue(climb(w))
    w.editor.burn()
    panel = w.selection_panel
    assert panel.pull_back_row.isVisible() and panel.pull_back_label.text() == 'Setback per contour step'
    panel.pull_back.setValue(150)
    assert '150 m a step back' in w.editor.proposal.summary
    w.editor.accept_proposal()
    assert min(sq.nodes[r].lat for r in sq.ways[finger.id].refs) == pytest.approx(LAT + 150 * M_LAT, abs=1e-6)


def test_shift_b_burns_every_climb_the_grade_found(climbing):
    w, sq, finger = climbing
    w.edit_actions['edit.burn_all'].trigger()
    assert w.editor.proposal.kind == 'burn' and 'burn: 1 climb' in w.editor.proposal.summary


def test_b_with_no_climb_chosen_says_how(climbing):
    w, sq, finger = climbing
    w.editor.focused_issue = None
    w.edit_actions['edit.burn'].trigger()
    assert w.editor.proposal.kind != 'burn'
    assert 'choose a climb' in w.statusBar().currentMessage()


def test_a_climb_not_burnable_is_listed_with_why(window):
    """A contour crossing once in the wrong place - a spur - is not cut."""
    water = overpass.Water()
    for k in range(41):
        water.nodes[k + 1] = Node(id=k + 1, lon=125.30 + 0.0025 * k + 0.0001, lat=LAT)
    water.ways[100] = Way(id=100, refs=list(range(1, 42)), tags={'waterway': 'river'})
    window._water_imported(Answer({NORTH: water}, frozenset(water.ways), frozenset()), window.working_set)
    for lon, ele in ((125.31, 100), (125.33, 75), (125.35, 100), (125.39, 50)):
        draw(window, [(lon, LAT - 0.02), (lon, LAT + 0.02)], ele)
    sq = window.working_set.squares[NORTH]
    window.editor.selection = Selection(sq, sq.ways[100])
    window.editor.grade()
    window.edit_actions['edit.burn_all'].trigger()
    p = window.editor.proposal
    assert p.summary.startswith('nothing burned') and not p.acceptable
    (why,) = [i for i in p.issues if i.kind == 'unburned']
    assert 'crosses the river only here' in why.text


@pytest.fixture
def two_climbs(climbing):
    """A second finger downstream, a 75 m between the two."""
    w, sq, finger = climbing
    draw(w, [(125.3675, LAT - 0.02), (125.3675, LAT + 0.02)], 75)
    second = draw(w, [(125.37, LAT + 0.02), (125.37, LAT - 0.01), (125.38, LAT - 0.01),
                      (125.38, LAT + 0.02)], 100)
    w.editor.selection = Selection(sq, sq.ways[100])
    w.editor.grade()
    return w, sq, finger, second


def test_shift_b_burns_both_climbs_and_b_only_the_one_chosen(two_climbs):
    w, sq, finger, second = two_climbs
    w.editor.show_issue(climb(w))
    w.editor.burn()
    assert w.editor.proposal.summary.startswith('burn: 1 climb')
    w.editor.selection = Selection(sq, sq.ways[100])
    w.editor.grade()
    w.edit_actions['edit.burn_all'].trigger()
    assert w.editor.proposal.summary.startswith('burn: 2 climbs')


def test_a_second_shift_b_grades_again_rather_than_finding_nothing(two_climbs):
    """After a burn is accepted its grade is gone; two passes - the way a
    spur's neighbours are reached - should not need G between."""
    w, sq, finger, second = two_climbs
    w.editor.show_issue(climb(w))
    w.editor.burn()
    w.editor.accept_proposal()
    w.edit_actions['edit.burn_all'].trigger()
    p = w.editor.proposal
    assert p is not None and p.kind == 'burn', w.statusBar().currentMessage()
    assert p.summary.startswith('burn: 1 climb')
    w.editor.accept_proposal()
    for f in (finger, second):                   # each now stays north of the river
        assert min(sq.nodes[r].lat for r in sq.ways[f.id].refs) > LAT, 'a climb was left unburned'
