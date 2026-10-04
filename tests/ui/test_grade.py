"""Grading water from the contours, proposed before it lands - R24, G6b.

Built in the fixture's blank square to the north, where nothing else is: a
river running east across north-south contours at known places, so every
level the grade proposes can be worked out by hand.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QPointF, Qt
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
    assert p is not None and p.acceptable
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
    assert not p.acceptable and "nothing to change" in p.summary
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
    # the span's own pixels, found from its vertices rather than assumed at a
    # fixed offset from the middle: on Windows the docks are wider, the map
    # narrower, and a fixed window ran off the image and counted 42 where
    # Linux counted 300. Vertices 6 to 8 lie in the climbing span
    from danu.ui import mercator as m

    def px(i):
        n = sq.nodes[r.refs[i]]
        return window.map.mapFromScene(QPointF(*m.lonlat_to_scene(n.lon, n.lat)))
    a, b = px(6), px(8)
    cols = [x for x in range(min(a.x(), b.x()) + 3, max(a.x(), b.x()) - 3) if 0 <= x < img.width()]
    row = a.y()
    assert len(cols) >= 20, f'the span is not in view ({len(cols)} columns)'
    # measured down a column through it: the core comes out (189, 50, 44)
    # with the red over the halo and (207, 87, 34) with it under - which the
    # eye reads as orange. Green tells them apart. "Any reddish pixel" passed
    # with the order reversed; the commonest colours missed the core
    over = sum(1 for x in cols
               if any((c := img.pixelColor(x, y)).red() > 180 and c.green() < 75
                      and c.blue() < 70 for y in range(row - 3, row + 4)))
    assert over >= 0.8 * len(cols), (
        f'the rejected span is under the halo ({over} of {len(cols)} columns red over it)'
    )
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


def test_a_river_area_mapped_as_a_relation_is_refused_too(window, sq):
    """R27 held for a river area drawn as one closed way; one mapped as a
    relation went down the lake path and was proposed one flat level - the
    Bosco River's area, flattened at its mouth's height, is how R27 came to
    be written."""
    k = lake(sq)
    k.tags.update({'water': 'river'})
    contour(sq, 125.51, 45, -22.80, -22.60)
    rebuild(window)
    assert grade(window, sq, k) is None, 'a river area was proposed one level'
    assert 'R27' in window.statusBar().currentMessage()


def test_only_water_is_offered_a_grade(window, sq):
    i = next(_ids)
    rel = Relation(id=i, tags={'type': 'boundary', 'name': 'a district'}, members=[])
    sq.relations[i] = rel
    rebuild(window)
    window.editor.selection = Selection(sq, None, relation=rel)
    assert not window.selection_panel.grade_btn.isVisible()
    window.editor.grade()
    assert window.editor.proposal is None
    assert 'grading is for water' in window.statusBar().currentMessage()


# ------------------------------------------------------------- chains (G6d)

def test_a_way_with_no_crossings_of_its_own_is_graded_as_part_of_its_chain(window, sq):
    """Graded way by way it would get nothing; the next pieces have the
    crossings. On the gobras set the 149 chains of three or more ways level
    7,478 points this way instead of 4,090."""
    three_contours(sq)                                   # at 125.325, 125.355, 125.385
    a = river(sq, [125.30, 125.31, 125.32, 125.33])      # crosses 100
    b = river(sq, [125.33, 125.34, 125.35])              # crosses nothing
    c = river(sq, [125.35, 125.36, 125.37, 125.38, 125.39])   # crosses 75 and 50
    b.refs[0], c.refs[0] = a.refs[-1], b.refs[-1]        # end to end, sharing nodes
    rebuild(window)
    p = grade(window, sq, b)
    assert 'a chain of 3 ways' in p.summary
    window.editor.accept_proposal()
    assert levels(sq, b)[1] == '87.5', 'the middle piece was not graded from its neighbours'
    window.editor.undo()
    assert all(v is None for w_ in (a, b, c) for v in levels(sq, w_)), 'not one step'


def test_a_chain_across_two_squares_is_one_step_and_its_junction_level_is_in_both(window, sq):
    """An import puts each way whole into one square, nodes and all, so the
    node two ways in two squares share is in both files under one OSM id -
    and a level on it has to be in both, or the squares disagree."""
    here = window.working_set.squares[SquareName(125, -24)]
    junction = 7_000_001
    for s_, lat in ((here, -23.0), (sq, -23.0)):
        s_.nodes[junction] = Node(id=junction, lon=125.35, lat=lat)
    for s_, ids, lats in ((here, [7_000_002, 7_000_003], (-23.06, -23.03)),
                          (sq, [7_000_004, 7_000_005], (-22.97, -22.94))):
        for i, la in zip(ids, lats, strict=True):
            s_.nodes[i] = Node(id=i, lon=125.35, lat=la)
    here.ways[7_000_010] = Way(id=7_000_010, refs=[7_000_002, 7_000_003, junction],
                               tags={'waterway': 'stream'})
    sq.ways[7_000_011] = Way(id=7_000_011, refs=[junction, 7_000_004, 7_000_005],
                             tags={'waterway': 'stream'})
    # one contour crosses each piece, so neither grades alone - and 4.4 km
    # apart, inside the 5 km a span may run (the first layout put them 10 km
    # apart and graded nothing, rightly)
    for s_, la, ele in ((here, -23.02, 100), (sq, -22.98, 50)):
        i = next(_ids)
        s_.ways[i] = Way(id=i, refs=[node(s_, 125.30, la), node(s_, 125.40, la)],
                         tags={'ele': str(ele)})
    rebuild(window)
    p = grade(window, sq, sq.ways[7_000_011])
    assert p is not None and 'a chain of 2 ways' in p.summary
    window.editor.accept_proposal()
    a, b = here.nodes[junction].tags.get('ele'), sq.nodes[junction].tags.get('ele')
    assert a is not None and a == b, f'the junction disagrees between the squares: {a} / {b}'
    window.editor.undo()
    assert 'ele' not in here.nodes[junction].tags and 'ele' not in sq.nodes[junction].tags


def test_a_gap_walked_across_is_reported_with_where_it_is(window, sq):
    three_contours(sq)
    river(sq, [125.30, 125.31, 125.32, 125.33])
    gap = river(sq, [125.33, 125.34, 125.35, 125.36, 125.37, 125.38, 125.39], lat=LAT + 2.5 / 110540)
    rebuild(window)
    p = grade(window, sq, gap)
    assert 'walked across 1 gap' in p.summary and 'a mapping error' in p.summary
    # placed where the piece that stops short ends - 2.5 m north of the other
    assert '-22.69998, 125.33000' in p.summary, 'the gap is not placed'
    assert len(p.joins) == 1 and p.chain_paths and len(p.chain_paths) == 2


def test_a_point_a_way_passes_through_twice_is_counted_once(window, sq):
    three_contours(sq)
    r = river(sq, EAST)
    r.refs.insert(6, r.refs[4])                         # back through its own node
    rebuild(window)
    p = grade(window, sq, r)
    assert '11 points' in p.summary, p.summary


def test_the_whole_chain_is_drawn_not_only_the_way_clicked(window, sq):
    """Read from pixels on a piece that was not clicked. Measured: the chain's
    halo comes out (242, 201, 152) beside the line; without it the ground is
    (235, 235, 235)."""
    three_contours(sq)
    a = river(sq, [125.30, 125.31, 125.32, 125.33])
    b = river(sq, [125.33, 125.34, 125.35])
    c = river(sq, [125.35, 125.36, 125.37, 125.38, 125.39])
    b.refs[0], c.refs[0] = a.refs[-1], b.refs[-1]
    rebuild(window)
    grade(window, sq, b)
    n = sq.nodes[a.refs[1]]
    window.map.set_zoom(15)
    window.map.center_on_lonlat(n.lon + 0.004, n.lat)
    img = QImage(window.map.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    painter = QPainter(img)
    window.map.render(painter)
    painter.end()
    cx, cy = img.width() // 2, img.height() // 2
    halo = sum(1 for x in range(cx - 10, cx + 11) for y in range(cy - 5, cy + 6)
               if (c_ := img.pixelColor(x, y)).red() > 230 and 180 < c_.green() < 220
               and c_.blue() < 170)
    assert halo >= 40, f'the rest of the chain is not shown ({halo} px)'


def test_a_gap_counts_as_distance_and_a_shared_node_counts_once(window, sq):
    """The chain's distances, read straight from the proposal: across a join
    by a shared node the next piece starts where the last ended, once; across
    a gap the distance steps by the gap."""
    three_contours(sq)
    a = river(sq, [125.30, 125.31, 125.32, 125.33])
    b = river(sq, [125.33, 125.34, 125.35])
    c = river(sq, [125.35, 125.36, 125.37, 125.38, 125.39])
    b.refs[0], c.refs[0] = a.refs[-1], b.refs[-1]
    rebuild(window)
    p = grade(window, sq, b)
    assert len(p.dist) == 4 + 3 + 5 - 2, 'a shared node was walked twice'
    assert all(d2 > d1 for d1, d2 in zip(p.dist, p.dist[1:], strict=False))

    sq.ways.clear()
    three_contours(sq)
    river(sq, [125.30, 125.31, 125.32, 125.33])
    gap = river(sq, [125.33, 125.34, 125.35, 125.36, 125.37, 125.38, 125.39],
                lat=LAT + 2.5 / 110540)
    rebuild(window)
    p = grade(window, sq, gap)
    steps = [d2 - d1 for d1, d2 in zip(p.dist, p.dist[1:], strict=False)]
    assert any(abs(st - 2.5) < 0.3 for st in steps), 'the gap is not distance'


def test_two_nodes_on_one_spot_are_said_as_that_not_as_a_gap(window, sq):
    three_contours(sq)
    a = river(sq, [125.30, 125.31, 125.32, 125.33])
    b = river(sq, [125.33, 125.34, 125.35, 125.36, 125.37, 125.38, 125.39])
    assert a.refs[-1] != b.refs[0]                       # two nodes, one place
    rebuild(window)
    p = grade(window, sq, b)
    assert 'two nodes on one spot, not merged' in p.summary


def test_a_gap_ahead_of_the_way_clicked_counts_as_distance_too(window, sq):
    """The other direction from the test above: grading the first piece, the
    gap is walked across going forward rather than back."""
    three_contours(sq)
    first = river(sq, [125.30, 125.31, 125.32, 125.33])
    river(sq, [125.33, 125.34, 125.35, 125.36, 125.37, 125.38, 125.39], lat=LAT + 2.5 / 110540)
    rebuild(window)
    p = grade(window, sq, first)
    steps = [d2 - d1 for d1, d2 in zip(p.dist, p.dist[1:], strict=False)]
    assert any(abs(st - 2.5) < 0.3 for st in steps), 'the gap ahead is not distance'


def test_a_junction_node_another_square_holds_gets_the_level_too(window, sq):
    """A node a square outside the chain also holds - a contour there snapped
    to it - is the same OSM node in that file, and the level goes there too,
    or the files disagree."""
    three_contours(sq)
    r = river(sq, EAST)
    shared = 7_100_001
    n = sq.nodes.pop(r.refs[4])
    sq.nodes[shared] = Node(id=shared, lon=n.lon, lat=n.lat)
    r.refs[4] = shared
    other = window.working_set.squares[SquareName(126, -24)]
    other.nodes[shared] = Node(id=shared, lon=n.lon, lat=n.lat)
    rebuild(window)
    grade(window, sq, r)
    window.editor.accept_proposal()
    assert other.nodes[shared].tags.get('ele') == sq.nodes[shared].tags.get('ele') == '87.5'
