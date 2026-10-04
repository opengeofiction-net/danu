"""Grading water from the contours, proposed before it lands - R24, G6b.

Built in the fixture's blank square to the north, where nothing else is: a
river running east across north-south contours at known places, so every
level the grade proposes can be worked out by hand.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter

from danu.core import edits
from danu.core.square import Member, Node, Relation, SquareName, Way
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)
LAT = -22.70
_ids = iter(range(-5000, -1, 1))


def node(sq, lon, lat, tags=None):
    i = next(_ids)
    sq.nodes[i] = Node(id=i, lon=lon, lat=lat, tags=dict(tags or {}))
    return i


def contour(sq, lon, ele, lat0=-22.75, lat1=-22.65):
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[node(sq, lon, lat0), node(sq, lon, lat1)], tags={'ele': str(ele)})
    return i


def river(sq, lons, lat=LAT, tags=None):
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[node(sq, lon, lat) for lon in lons],
                     tags=dict(tags or {'waterway': 'river', 'name': 'Bosco'}))
    return sq.ways[i]


def rebuild(w):
    w.contours.set_working_set(w.working_set)


@pytest.fixture
def sq(window):
    return window.working_set.squares[NORTH]


EAST = [round(125.30 + 0.01 * k, 2) for k in range(11)]      # 125.30 .. 125.40


def three_contours(sq, values=(100, 75, 50)):
    for lon, ele in zip((125.325, 125.355, 125.385), values, strict=True):
        contour(sq, lon, ele)


def grade(w, sq, feature):
    w.editor.selection = (Selection(sq, None, relation=feature) if isinstance(feature, Relation)
                          else Selection(sq, feature))
    w.editor.grade()
    return w.editor.proposal


def levels(sq, way):
    return [sq.nodes[r].tags.get('ele') for r in way.refs]


# ------------------------------------------------------------------ rivers

def test_a_river_is_graded_between_its_crossings_by_distance(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    p = grade(window, sq, r)
    assert p is not None and p.command is not None
    assert '3 crossings' in p.summary and '6 of 11 points' in p.summary
    window.editor.accept_proposal()
    got = levels(sq, r)
    # 125.34 lies halfway between the 100 m and 75 m crossings
    assert got[4] == '87.5'
    assert got[:3] == [None, None, None], 'graded before the first crossing'
    assert got[-2:] == [None, None], 'graded after the last crossing'
    assert all(float(a) >= float(b) for a, b in zip(got[3:9], got[4:9], strict=False)), 'it climbs'


def test_a_grade_is_one_step(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    window.editor.undo()
    assert levels(sq, r) == [None] * 11, 'Ctrl+Z did not take the whole grade back'


def test_levels_are_written_to_the_decimetre(window, sq):
    contour(sq, 125.305, 100)
    contour(sq, 125.335, 99)
    r = river(sq, [125.30, 125.31, 125.32, 125.33, 125.34])
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    for v in levels(sq, r):
        if v is not None:
            assert len(v.split('.')[-1]) <= 1 or '.' not in v, f'{v} is finer than 0.1 m'


def test_a_river_drawn_upstream_is_graded_from_its_higher_end(window, sq):
    three_contours(sq)
    r = river(sq, list(reversed(EAST)))
    rebuild(window)
    p = grade(window, sq, r)
    assert 'drawn upstream' in p.summary
    window.editor.accept_proposal()
    assert levels(sq, r)[6] == '87.5', 'a river drawn upstream was not graded'


def test_a_span_that_climbs_is_left_ungraded_and_said(window, sq):
    three_contours(sq, (100, 50, 75))
    r = river(sq, EAST)
    rebuild(window)
    p = grade(window, sq, r)
    assert 'where the contours climb' in p.summary
    assert p.rejected_paths, 'the climbing span is not drawn on the map'
    window.editor.accept_proposal()
    got = levels(sq, r)
    assert got[6] is None and got[7] is None, 'the climbing span was graded'


def test_a_span_too_long_is_told_apart_from_a_climb(window, sq):
    contour(sq, 125.30, 100)
    contour(sq, 125.36, 50)                       # some 6.2 km apart
    r = river(sq, [125.29, 125.31, 125.33, 125.35, 125.37])
    rebuild(window)
    p = grade(window, sq, r)
    assert 'running over 5 km' in p.summary and 'climb' not in p.summary


def test_too_few_crossings_is_said_and_nothing_proposed(window, sq):
    contour(sq, 125.325, 100)
    r = river(sq, EAST)
    rebuild(window)
    assert grade(window, sq, r) is None
    assert 'not enough to grade from' in window.statusBar().currentMessage()


def test_a_grade_replaces_levels_set_by_hand_and_says_so(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    sq.nodes[r.refs[4]].tags['ele'] = '90'
    rebuild(window)
    p = grade(window, sq, r)
    assert 'replaces 1 level' in p.summary


def test_a_river_already_graded_has_nothing_to_accept(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    p = grade(window, sq, r)
    assert p.command is None and 'nothing to change' in p.summary
    assert not window.selection_panel.accept_btn.isEnabled()


def test_a_neighbours_contours_count(window, sq):
    """A river near a degree line crosses contours its neighbour holds."""
    here = window.working_set.squares[SquareName(125, -24)]
    contour(here, 125.325, 100, -23.05, -22.65)        # held next door, reaching north
    contour(sq, 125.355, 75)
    contour(sq, 125.385, 50)
    r = river(sq, EAST)
    rebuild(window)
    assert '3 crossings' in grade(window, sq, r).summary


def test_a_node_shared_with_a_contour_is_a_crossing(window, sq):
    """A contour snapped to a river is a touch to geometry.crossings, and
    the clearest crossing there is."""
    r = river(sq, EAST)
    for k, ele in ((2, 100), (8, 50)):
        i = next(_ids)
        sq.ways[i] = Way(id=i, refs=[node(sq, EAST[k], -22.75), r.refs[k],
                                     node(sq, EAST[k], -22.65)], tags={'ele': str(ele)})
    rebuild(window)
    p = grade(window, sq, r)
    assert p is not None and '2 crossings' in p.summary


# ------------------------------------------------------------- refusals

def test_a_river_area_is_refused(window, sq):
    i = next(_ids)
    ring = [node(sq, lon, lat) for lon, lat in ((125.5, -22.5), (125.6, -22.5), (125.6, -22.4))]
    sq.ways[i] = Way(id=i, refs=[*ring, ring[0]], tags={'waterway': 'riverbank'})
    rebuild(window)
    assert grade(window, sq, sq.ways[i]) is None
    assert 'R27' in window.statusBar().currentMessage()


def test_a_contour_is_not_graded(window, sq):
    three_contours(sq)
    rebuild(window)
    c = next(x for x in sq.ways.values() if 'ele' in x.tags)
    assert grade(window, sq, c) is None
    assert 'grading is for water' in window.statusBar().currentMessage()


# ----------------------------------------------------------------- lakes

def lake(sq, lon0=125.50, lat0=-22.72, d=0.04):
    ring = [node(sq, lon0 + dx * d, lat0 + dy * d) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))]
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[*ring, ring[0]])
    rel = Relation(id=next(_ids), tags={'natural': 'water', 'water': 'lake', 'name': 'Kinser'},
                   members=[Member('way', i, 'outer')])
    sq.relations[rel.id] = rel
    return rel


def test_a_lake_takes_the_level_a_river_through_it_leaves_at(window, sq):
    """The outlet: a river mapped through the lake, graded between a contour
    upstream and one downstream, is lowest where it leaves."""
    k = lake(sq)                                   # 125.50 to 125.54
    # either side of the lake and some 4.7 km apart, inside the 5 km a span
    # may run - the first layout put them 8 km apart and graded nothing
    contour(sq, 125.497, 60)
    contour(sq, 125.543, 40)
    r = river(sq, [125.47, 125.49, 125.51, 125.53, 125.55, 125.57], lat=-22.70)
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    p = grade(window, sq, k)
    assert 'from its outlet' in p.summary
    inside = [float(sq.nodes[x].tags['ele']) for x in r.refs[2:4]]
    window.editor.accept_proposal()
    assert sq.relations[k.id].tags['ele'] == f'{min(inside):g}'


def test_a_lake_with_no_river_takes_its_rim(window, sq):
    k = lake(sq)
    contour(sq, 125.51, 45, -22.80, -22.60)        # crosses the shore twice
    rebuild(window)
    p = grade(window, sq, k)
    assert 'from its rim' in p.summary
    window.editor.accept_proposal()
    assert sq.relations[k.id].tags['ele'] == '45'


def test_an_inflow_above_the_rim_cannot_lift_the_lake(window, sq):
    """Lake Therran, on the gobras set: graded alone, the creek flowing in
    made the "outlet" 10 m above the contour crossing the lake's own shore.
    The rim is where it would spill, so a ceiling."""
    k = lake(sq)                                   # 125.50 to 125.54, -22.72 to -22.68
    contour(sq, 125.52, 15, -22.69, -22.67)        # the rim: crosses the north shore only
    contour(sq, 125.47, 60)
    contour(sq, 125.512, 30, -22.71, -22.69)       # crosses the inflow, inside the lake
    # the inflow ends inside the lake, graded 60 -> 30 across its shore
    r = river(sq, [125.46, 125.48, 125.505, 125.51, 125.515], lat=-22.70)
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    p = grade(window, sq, k)
    assert 'from its rim' in p.summary and 'flows in rather than out' in p.summary
    window.editor.accept_proposal()
    assert sq.relations[k.id].tags['ele'] == '15'


def test_a_lake_with_nothing_to_grade_from_says_so(window, sq):
    k = lake(sq)
    rebuild(window)
    assert grade(window, sq, k) is None
    assert 'nothing to grade from' in window.statusBar().currentMessage()


# ------------------------------------------------- the proposal's life

def test_a_proposal_is_dropped_by_an_edit_and_by_a_new_selection(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    window.editor.selection = None
    assert window.editor.proposal is None, 'a new selection kept the proposal'
    grade(window, sq, r)
    window.editor.do(sq, edits.SetTags(r.id, dict(r.tags), {**r.tags, 'note': 'x'}))
    assert window.editor.proposal is None, 'an edit kept the proposal'


def test_enter_accepts_and_escape_drops(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    window.editor.key_press(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                      Qt.KeyboardModifier.NoModifier))
    assert window.editor.proposal is None and levels(sq, r)[4] is None
    assert window.editor.selection is not None, 'Escape dropped the selection with the grade'
    grade(window, sq, r)
    window.editor.key_press(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                      Qt.KeyboardModifier.NoModifier))
    assert levels(sq, r)[4] == '87.5'


def test_the_panel_shows_the_proposal_and_its_profile(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    rebuild(window)
    p = window.selection_panel
    window.editor.selection = Selection(sq, r)
    assert p.grade_btn.isVisible() and not p.proposal_box.isVisible()
    p.grade_btn.click()
    assert p.proposal_box.isVisible() and p.profile.isVisible()
    assert '3 crossings' in p.summary.text() and p.accept_btn.isEnabled()
    p.accept_btn.click()
    assert not p.proposal_box.isVisible() and levels(sq, r)[4] == '87.5'


def test_the_grade_button_is_for_water_only(window, sq):
    three_contours(sq)
    rebuild(window)
    c = next(x for x in sq.ways.values() if 'ele' in x.tags)
    window.editor.selection = Selection(sq, c)
    assert not window.selection_panel.grade_btn.isVisible()


def test_a_rejected_span_shows_through_the_selection_and_marks_mean_one_thing(window, sq):
    """Read from pixels. Drawn under the selection's halo, the red of a
    rejected span was hidden by the orange of the very river being graded;
    and the selection's vertex marks looked like proposed levels."""
    three_contours(sq, (100, 50, 75))
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    mid = sq.nodes[r.refs[6]]
    window.map.set_zoom(14)
    window.map.center_on_lonlat(mid.lon, mid.lat)
    img = QImage(window.map.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    painter = QPainter(img)
    window.map.render(painter)
    painter.end()
    cx, cy = img.width() // 2, img.height() // 2
    # inside the rejected span, which starts just east of the middle vertex.
    # Measured down a column through it: the core rows come out (189, 50, 44)
    # with the red over the halo, (207, 87, 34) with it under - and the eye
    # reads the second as orange. Green is what tells them apart. The first
    # threshold accepted any reddish pixel and passed with the order reversed;
    # the second was set from the commonest colours, which missed the core
    red = sum(1 for x in range(cx + 20, cx + 120) for y in range(cy - 3, cy + 4)
              if (c := img.pixelColor(x, y)).red() > 180 and c.green() < 75 and c.blue() < 70)
    assert red >= 100, f'the rejected span is under the halo ({red} red pixels)'
    assert window.editor.proposal is not None


def test_while_a_grade_is_proposed_a_mark_on_the_river_is_a_proposed_level(window, sq):
    """The selection's vertex marks, the same size as a proposed level and
    close in colour, made a river whole at z12 look graded at both ends when
    it was graded at one. Hidden while a grade is open. Read from pixels at a
    vertex inside the climbing span, where no level is proposed: measured,
    the selection's mark under the red comes out (212, 54, 24), and nothing
    else there has blue below 49."""
    three_contours(sq, (100, 50, 75))
    r = river(sq, EAST)
    rebuild(window)
    grade(window, sq, r)
    v = sq.nodes[r.refs[7]]
    window.map.set_zoom(15)
    window.map.center_on_lonlat(v.lon, v.lat)
    img = QImage(window.map.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    painter = QPainter(img)
    window.map.render(painter)
    painter.end()
    cx, cy = img.width() // 2, img.height() // 2
    marks = sum(1 for x in range(cx - 4, cx + 5) for y in range(cy - 4, cy + 5)
                if (c := img.pixelColor(x, y)).red() > 190 and c.blue() < 35)
    assert marks == 0, f'the selection marked a vertex while a grade was open ({marks} px)'
