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
    assert (NORTH, 202) in c.cliffs
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
    pts, along, _, _ = c.cliffs[(NORTH, 202)]
    scale = 10 * TOOTH_SPACING_PX / along[-1]          # ten teeth along it
    teeth = c.cliff_teeth((NORTH, 202), scale)
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
    assert (NORTH, 202) not in w.contours.water and (NORTH, 202) in w.contours.cliffs
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
