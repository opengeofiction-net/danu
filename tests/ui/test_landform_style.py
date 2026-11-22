"""The landforms drawn, picked and given their heights in the editor - #191.

Imported from the main map, almost none has a height: 38,011 cliffs and 34 of
them with an ``ele``. So each is drawn and picked without one, styled after
JOSM's standard map style, to be selected and given it.
"""

import pytest

pytest.importorskip('PySide6')

from danu.core.square import Node, SquareName

from .test_heights_ui import LANDFORMS

NORTH = SquareName(125, -23)


def imported(w):
    w.landforms._fetch = lambda bounds: LANDFORMS
    w.landforms._runner = lambda job: job.run()
    w.heights._fetch = lambda bounds: b'<osm version="0.6"></osm>'
    w.heights._runner = lambda job: job.run()
    w.edit_actions['edit.import_landforms'].trigger()
    return w.working_set.squares[NORTH]


def select(w, sq, way=None, relation=None):
    from danu.ui.tools import Selection
    w.editor.selection = Selection(sq, way, relation=relation)


def test_a_cliff_and_a_dry_lake_with_no_heights_are_drawn_in_their_own_styles(window):
    """The cliff, with no ``ele``, is drawn as a cliff with its teeth; the
    dry lake's ring and its fill as a dry lake's; the ridge as a ridge."""
    w = window
    imported(w)
    c = w.contours
    assert c.water[(NORTH, 202)].landform == 'cliff'
    assert (NORTH, 202) in c.marked
    assert c.water[(NORTH, 203)].landform == 'dry_lake'
    assert c.water_fills[(NORTH, 'rel', 301)].landform == 'dry_lake'
    assert c.water[(NORTH, 201)].landform == 'ridge'


def test_a_cliffs_teeth_hang_on_its_right(window):
    """Every TOOTH_SPACING_PX along it, and its low side to the right of the
    way it runs - (-dy, dx) on a scene whose y runs down: the cliff runs east,
    so its teeth hang south, to larger y."""
    from danu.ui.contours import TOOTH_SPACING_PX
    w = window
    imported(w)
    c = w.contours
    pts, along, _, _ = c.marked[(NORTH, 202)]
    scale = 10 * TOOTH_SPACING_PX / along[-1]          # ten teeth along it
    teeth = c.line_marks((NORTH, 202), scale)
    assert len(teeth) == 10
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    _, _, dx, dy = teeth[0]
    nx, ny = -dy, dx
    # the cliff 23 -> 24 runs east along -22.6: its low side is south
    assert x1 > x0 and abs(y1 - y0) < 1e-9 and ny > 0.99 and abs(nx) < 1e-6


def test_a_floor_is_dashed_and_a_crest_solid(window):
    from PySide6.QtCore import Qt

    from danu.ui.contours import landform_pen
    assert landform_pen('ridge').style() == Qt.PenStyle.SolidLine
    assert landform_pen('arete').style() == Qt.PenStyle.SolidLine
    assert landform_pen('valley').style() == Qt.PenStyle.DashLine
    assert landform_pen('cliff').color() != landform_pen('earth_bank').color()


def test_a_cliff_selected_is_given_its_top_and_its_height(window):
    """Selected with no ``ele``: a cliff, its elevation and height editable.
    Given its top it is drawn as the contour that makes it, its teeth still
    on it; given back none, as a cliff again. Each one step."""
    from danu.ui.selection_panel import describe
    w = window
    sq = imported(w)
    way = sq.ways[202]
    select(w, sq, way)
    info = describe(w.editor.selection, w.contours)
    assert (info.kind, info.cliff, info.editable, info.ele, info.height) == ('cliff', True, True, None, 40)
    steps = len(w.editor.history._done)
    assert w.editor.set_ele(300)
    assert sq.ways[202].tags['ele'] == '300'
    assert (NORTH, 202) not in w.contours.water and (NORTH, 202) in w.contours.marked
    assert w.editor.set_height(55)
    assert sq.ways[202].tags['height'] == '55'
    assert not w.editor.set_height(-5)
    assert len(w.editor.history._done) == steps + 2
    select(w, sq, sq.ways[202])
    assert w.editor.set_ele(None)
    assert 'ele' not in sq.ways[202].tags
    assert w.contours.water[(NORTH, 202)].landform == 'cliff'


def test_a_cliff_and_a_dry_lake_are_not_graded(window):
    w = window
    sq = imported(w)
    select(w, sq, sq.ways[202])
    w.editor.grade()
    assert 'a cliff is not graded' in w.statusBar().currentMessage()
    select(w, sq, relation=sq.relations[301])
    w.editor.grade()
    assert 'held flat' in w.statusBar().currentMessage()


def test_a_dry_lake_selected_says_so_and_takes_a_level(window):
    from danu.ui.selection_panel import describe
    w = window
    sq = imported(w)
    select(w, sq, relation=sq.relations[301])
    info = describe(w.editor.selection, w.contours)
    assert info.kind == 'dry lake' and info.editable
    assert w.editor.set_ele(110)
    assert sq.relations[301].tags['ele'] == '110'


def test_a_click_on_a_dry_lakes_ring_is_the_dry_lake(window):
    from danu.ui.contours import water_feature
    w = window
    sq = imported(w)
    assert water_feature(sq, sq.ways[203]) is sq.relations[301]


def test_a_spot_height_is_drawn_as_what_it_is_said_to_be(window):
    w = window
    sq = w.working_set.squares[NORTH]
    for nid, kind in ((-901, 'saddle'), (-902, 'sinkhole'), (-903, 'hill')):
        sq.nodes[nid] = Node(id=nid, lon=125.5, lat=-22.5, tags={'natural': kind, 'ele': '100'})
    w.contours.refresh_spots(sq, [-901, -902, -903])
    assert [w.contours.spots[(NORTH, n)].kind for n in (-901, -902, -903)] == ['saddle', 'sinkhole', None]


def test_a_cliff_is_reversed_and_its_teeth_turn_with_it(window):
    """R turns a cliff round as it does a coastline: its low side, and its
    teeth, on the other side; the panel offers it, one step, named so.
    A ridge, whose direction means nothing, is refused."""
    from danu.core import edits
    w = window
    sq = imported(w)
    way = sq.ways[202]
    refs = list(way.refs)
    select(w, sq, way)
    w.selection_panel.refresh()
    assert not w.selection_panel.reverse_btn.isHidden()
    _, _, dx, dy = w.contours.line_marks((NORTH, 202), 1.0)[0]
    w.edit_actions['edit.reverse_coastline'].trigger()
    assert sq.ways[202].refs == refs[::-1]
    assert 'cliff reversed: its low side is on the other side' in w.statusBar().currentMessage()
    _, _, dx2, dy2 = w.contours.line_marks((NORTH, 202), 1.0)[0]
    assert dx * dx2 + dy * dy2 < 0, 'its teeth did not turn'
    assert w.editor.history.describe_undo().endswith('reverse cliff')
    w.editor.undo()
    assert sq.ways[202].refs == refs
    select(w, sq, sq.ways[201])
    w.selection_panel.refresh()
    assert w.selection_panel.reverse_btn.isHidden()
    w.edit_actions['edit.reverse_coastline'].trigger()
    assert 'only a coastline, a cliff or an earth bank' in w.statusBar().currentMessage()
    assert edits.directed(sq.ways[201]) is None


def test_a_landforms_kind_is_changed_to_any_other(window):
    """The panel's Kind for a landform: a ridge made an arete, restyled, one
    step; a cliff a ridge, its other tags kept; a dry lake's relation a
    plateau. A contour has no Kind."""
    w = window
    sq = imported(w)
    p = w.selection_panel
    select(w, sq, sq.ways[201])
    p.refresh()
    assert not p.landform_kind.isHidden() and p.landform_kind.currentData() == 'ridge'
    p.landform_kind.setCurrentIndex(p.landform_kind.findData('arete'))
    p.landform_kind.activated.emit(p.landform_kind.currentIndex())
    assert sq.ways[201].tags['natural'] == 'arete'
    assert w.contours.water[(NORTH, 201)].landform == 'arete'
    assert 'ridge made an arete' in w.statusBar().currentMessage()
    w.editor.undo()
    assert sq.ways[201].tags['natural'] == 'ridge'
    select(w, sq, sq.ways[202])
    w.editor.set_height(40)
    assert w.editor.set_landform('ridge')
    assert sq.ways[202].tags['natural'] == 'ridge' and sq.ways[202].tags['height'] == '40'
    assert w.contours.water[(NORTH, 202)].landform == 'ridge'
    select(w, sq, relation=sq.relations[301])
    assert w.editor.set_landform('plateau')
    assert sq.relations[301].tags['natural'] == 'plateau'
    assert w.contours.water_fills[(NORTH, 'rel', 301)].landform == 'plateau'


def test_a_cliffs_elevation_typed_and_tabbed_past_is_kept(window, qtbot):
    """Typed into the panel and Tab to its height, not Enter: the elevation
    is set - it was lost - and then the height typed and Enter."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w = window
    sq = imported(w)
    select(w, sq, sq.ways[202])
    w.show()
    p = w.selection_panel
    p.refresh()
    assert p.height_row.isVisibleTo(p)
    p.ele.setFocus()
    p.ele.selectAll()
    QTest.keyClicks(p.ele, '300')
    p.height.setFocus()                          # what Tab does: the field left
    assert sq.ways[202].tags.get('ele') == '300'
    p.height.selectAll()
    QTest.keyClicks(p.height, '55')
    QTest.keyClick(p.height, Qt.Key.Key_Return)
    assert sq.ways[202].tags.get('height') == '55' and sq.ways[202].tags.get('ele') == '300'


def test_a_peak_with_no_height_is_drawn_hollow_picked_and_given_one(window):
    """A peak, a saddle or a sinkhole imported with no ``ele`` is drawn
    hollow and picked; given its height it is a spot height as any other,
    and taken back it is hollow again. A plain node with no ele is nothing."""
    from danu.ui import mercator as m
    from danu.ui.contours import ZOOM_SPOTS
    from danu.ui.tools import Selection
    w = window
    sq = w.working_set.squares[NORTH]
    sq.nodes[-911] = Node(id=-911, lon=125.5, lat=-22.5, tags={'natural': 'peak', 'name': 'Bare'})
    sq.nodes[-912] = Node(id=-912, lon=125.6, lat=-22.5, tags={'name': 'nothing'})
    w.contours.set_working_set(w.working_set)
    c = w.contours
    assert (NORTH, -911) in c.bare_spots and (NORTH, -911) not in c.spots
    assert (NORTH, -912) not in c.bare_spots
    x, y = m.lonlat_to_scene(125.5, -22.5)
    hit = c.pick_spot(x, y, 1.0, ZOOM_SPOTS)
    assert hit is not None and hit[1] == -911
    w.editor.selection = Selection(sq, None, -911)
    assert w.editor.set_ele(1200)
    assert sq.nodes[-911].tags['ele'] == '1200'
    assert c.spots[(NORTH, -911)].kind == 'peak' and (NORTH, -911) not in c.bare_spots
    w.editor.undo()
    assert (NORTH, -911) in c.bare_spots and (NORTH, -911) not in c.spots
