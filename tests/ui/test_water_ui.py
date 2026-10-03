"""The water import in the editor - G4c, without the network.

The fetch is injected, as the tile and territory fetchers' are. What is under
test is the queue, the one-step history across several squares, and the
drawing.
"""

import copy

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QPointF

from danu.core.square import Member, Node, Relation, SquareName, Way, WorkingSet
from danu.ui import mercator as m
from danu.ui.contours import ContourLayer
from danu.ui.mapview import MapView
from danu.ui.water import WaterImporter, commands

TEN = SquareName(126, -24)
HERE = SquareName(125, -24)


@pytest.fixture
def water_ws(zone):
    """A working set of this suite's own fixture squares. Its own rather than
    ``test_contours``' - importing a fixture by name shadows the parameter
    that uses it, and conftest's ``zone`` is already a set of two squares
    centred where these tests want one."""
    return WorkingSet.open(zone, HERE)


@pytest.fixture
def map_view(qtbot):
    v = MapView()
    v.resize(900, 700)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    return v


def render(view):
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    p = QPainter(img)
    view.render(p)
    p.end()
    return img


class FakeWater:
    def __init__(self, ways=(), relations=(), nodes=()):
        self.ways = {w.id: w for w in ways}
        self.relations = {r.id: r for r in relations}
        self.nodes = {n.id: n for n in nodes}

    def __len__(self):
        return len(self.ways) + len(self.relations)


def a_river(wid=9001, lon=126.5, lat=-23.7):
    nodes = [Node(id=wid * 10 + i, lon=lon + i * 0.01, lat=lat) for i in range(3)]
    way = Way(id=wid, refs=[n.id for n in nodes], tags={'waterway': 'river', 'name': 'Bosco'})
    return FakeWater(ways=[way], nodes=nodes)


# ------------------------------------------------------------------- queue

def test_the_importer_runs_one_at_a_time_and_the_newest_wins():
    jobs, got, started = [], [], []
    imp = WaterImporter(fetch=lambda bounds: b'<osm/>', runner=jobs.append)
    imp.finished.connect(lambda placed, ws: got.append((placed, ws)))
    imp.started.connect(started.append)

    class Set:
        bounds = (0.0, 0.0, 1.0, 1.0)
        squares = {}

        def at(self, lon, lat):
            return None

    first, second = Set(), Set()
    assert imp.request(first) == 1
    assert imp.busy and len(jobs) == 1
    assert imp.request(second) == 2, 'a second request did not displace the first'
    assert len(jobs) == 1, 'it queued behind rather than replacing'

    jobs.pop(0).run()                 # the first answers, for a serial nobody wants
    assert got == [], 'a superseded answer was shown'
    assert len(jobs) == 1, 'the newest was not started'
    jobs.pop(0).run()
    assert len(got) == 1


def test_a_failure_is_reported_and_the_queue_moves_on():
    jobs, bad = [], []

    def no(bounds):
        raise OSError('overpass did not answer')

    class Set:
        bounds = (0.0, 0.0, 1.0, 1.0)
        squares = {}

    imp = WaterImporter(fetch=no, runner=jobs.append)
    imp.failed.connect(bad.append)
    imp.request(Set())
    jobs.pop(0).run()
    assert bad and 'overpass did not answer' in bad[0]
    assert not imp.busy


# ----------------------------------------------------------- the one step

def test_an_import_across_squares_is_one_undo(window):
    w = window
    here, east = HERE, TEN
    placed = {here: a_river(9001, 125.5), east: a_river(9002, 126.5)}

    before = {n: len(w.working_set.squares[n].ways) for n in (here, east)}
    w._water_imported(placed, w.working_set)
    assert len(w.working_set.squares[here].ways) == before[here] + 1
    assert len(w.working_set.squares[east].ways) == before[east] + 1
    assert 'imported 2 water features' in w.statusBar().currentMessage()
    # named per square, because the share is not even
    assert str(here) in w.statusBar().currentMessage()

    w.editor.undo()
    assert len(w.working_set.squares[here].ways) == before[here]
    assert len(w.working_set.squares[east].ways) == before[east], (
        'one Ctrl+Z took back one square of a two-square import'
    )
    w.editor.redo()
    assert len(w.working_set.squares[here].ways) == before[here] + 1
    assert len(w.working_set.squares[east].ways) == before[east] + 1


def test_both_squares_are_dirty_after_an_import(window):
    w = window
    here, east = HERE, TEN
    w._water_imported({here: a_river(9001, 125.5), east: a_river(9002, 126.5)},
                      w.working_set)
    dirty = {sq.name for sq in w.editor.history.dirty_squares()}
    assert {here, east} <= dirty, 'a square an import wrote is not offered for saving'


def test_an_import_of_nothing_says_so(window):
    window._water_imported({}, window.working_set)
    assert 'no water' in window.statusBar().currentMessage()


def test_an_answer_for_a_set_no_longer_open_is_refused(window):
    """The fetch is a second and a half, and a mapper can move in it. The
    names of another set's grid can match these, and its ``Square`` objects
    cannot, so applying the features would write into squares nobody is
    looking at."""
    w = window
    stale, w.working_set = w.working_set, copy.copy(w.working_set)
    before = len(w.working_set.squares[HERE].ways)
    w._water_imported({HERE: a_river(9001, 125.5)}, stale)
    assert len(w.working_set.squares[HERE].ways) == before, (
        'features from a set no longer open were applied'
    )
    assert w.editor.history.dirty_squares() == [], 'a refused import dirtied a square'
    assert 'working set changed' in w.statusBar().currentMessage()


def test_commands_skip_a_square_the_set_does_not_hold(window):
    """``place`` files by the square a feature's anchor is in, and a set only
    holds its own nine."""
    steps = commands({SquareName(99, 9): a_river()}, window.working_set)
    assert steps == []


# -------------------------------------------------------------- the canvas

def test_water_is_drawn_though_it_has_no_elevation(map_view, water_ws):
    layer = ContourLayer()
    layer.set_working_set(water_ws)
    map_view.scene().addItem(layer)
    sq = water_ws.squares[HERE]
    river = a_river(9001, 125.5, -23.5)
    sq.nodes.update(river.nodes)
    sq.ways.update(river.ways)
    layer.refresh(sq, {9001})
    assert (sq.name, 9001) in layer.water, 'a river was not kept to draw'

    map_view.set_zoom(14)
    map_view.center_on_lonlat(125.51, -23.5)
    render(map_view)
    assert layer.drawn_water == 1, 'the river was not drawn'


def test_a_multipolygons_rings_are_water_though_they_carry_no_tags(water_ws):
    """A lake's outer ring carries no tagging of its own - the relation holds
    it - so a layer that asked the way alone would draw the lake as nothing."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    nodes = [Node(id=-900 - i, lon=125.4 + 0.01 * i, lat=-23.5) for i in range(3)]
    sq.nodes.update({n.id: n for n in nodes})
    sq.ways[-950] = Way(id=-950, refs=[n.id for n in nodes], tags={})
    sq.relations[-960] = Relation(id=-960, members=[Member('way', -950, 'outer')],
                                  tags={'natural': 'water'})
    layer.set_working_set(water_ws)
    assert (sq.name, -950) in layer.water, 'an untagged ring of a lake was not drawn'

    # and on the edit path as well as the open path
    layer.water.clear()
    layer.refresh(sq, {-950})
    assert (sq.name, -950) in layer.water


def test_a_waterway_relations_members_are_water_too(water_ws):
    """The import only asks for natural=water relations, but a type=waterway
    one can be drawn or already be in a square, and its members carry no
    tagging of their own either. The way test and the relation test are the
    same function so the two cannot answer differently."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    nodes = [Node(id=-800 - i, lon=125.3 + 0.01 * i, lat=-23.4) for i in range(3)]
    sq.nodes.update({n.id: n for n in nodes})
    sq.ways[-850] = Way(id=-850, refs=[n.id for n in nodes], tags={})
    sq.relations[-860] = Relation(id=-860, members=[Member('way', -850, 'main_stream')],
                                  tags={'type': 'waterway', 'waterway': 'river'})
    layer.set_working_set(water_ws)
    assert (sq.name, -850) in layer.water, (
        'a member of a waterway relation was dropped, though the same tags on '
        'the way itself would have been kept'
    )


def test_a_layer_can_be_painted_before_it_has_a_working_set(map_view):
    """_paint_water reads self.water to decide there is none, so the empty
    dict has to exist from construction and not from the first set."""
    layer = ContourLayer()
    assert layer.water == {}
    map_view.scene().addItem(layer)
    render(map_view)              # no AttributeError
    assert layer.drawn_water == 0


def test_the_status_line_names_the_bounds_being_fetched(window):
    """A queued request starts when the one before it answers, by which time
    the mapper may be looking at somewhere else."""
    w = window
    asked = w.working_set
    w.working_set = copy.copy(asked)
    w.working_set.centre = SquareName(99, 9)
    w._water_starting(asked)
    west = f'{asked.bounds[0]:g}'
    assert west in w.statusBar().currentMessage()


# --------------------------------------------------------------- the fill

def a_lake(sq, wid=-700, base=-700, lon=125.3, lat=-23.6, size=0.04):
    """A square lake as one closed way."""
    corners = [(lon, lat), (lon + size, lat), (lon + size, lat + size), (lon, lat + size)]
    ids = [base - i for i in range(4)]
    for nid, (x, y) in zip(ids, corners, strict=True):
        sq.nodes[nid] = Node(id=nid, lon=x, lat=y)
    sq.ways[wid] = Way(id=wid, refs=ids + [ids[0]], tags={'natural': 'water'})
    return wid


def test_a_closed_water_way_is_filled_and_a_river_is_not(water_ws):
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq)
    river = a_river(9001, 125.5, -23.5)
    sq.nodes.update(river.nodes)
    sq.ways.update(river.ways)
    layer.set_working_set(water_ws)
    assert (sq.name, 'way', -700) in layer.water_fills, 'a lake was left as an outline'
    assert (sq.name, 'way', 9001) not in layer.water_fills, 'a river has no inside'
    # and it keeps its shore: the fill is a second pass, not a replacement
    assert (sq.name, -700) in layer.water


def test_an_island_in_a_lake_is_a_hole_and_not_a_blue_island(water_ws):
    """The case relations were grown for. Both rings go in one path with an
    odd-even fill, so the island is where the lake is not."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700, lon=125.3, lat=-23.6, size=0.06)
    a_lake(sq, wid=-710, base=-720, lon=125.32, lat=-23.58, size=0.02)
    sq.ways[-710].tags = {}                       # the island ring carries nothing
    sq.ways[-700].tags = {}
    sq.relations[-730] = Relation(
        id=-730, tags={'type': 'multipolygon', 'natural': 'water'},
        members=[Member('way', -700, 'outer'), Member('way', -710, 'inner')])
    layer.set_working_set(water_ws)

    key = (sq.name, 'rel', -730)
    assert key in layer.water_fills, 'the lake was not filled'
    assert (sq.name, 'way', -700) not in layer.water_fills, (
        'the outer ring was filled a second time on its own'
    )
    path = layer.water_fills[key].path
    mid = m.lonlat_to_scene(125.33, -23.57)       # inside the island
    shore = m.lonlat_to_scene(125.305, -23.595)   # inside the lake, outside the island
    assert not path.contains(QPointF(*mid)), 'the island was painted as water'
    assert path.contains(QPointF(*shore)), 'the lake was not painted as water'


def test_a_lake_cut_by_the_square_edge_is_outlined_and_not_filled(water_ws):
    """Half a ring is not a ring. Closing it would draw a shore along the
    square edge that nobody mapped."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    # five nodes, so it fails the test for coming back and not the one for
    # being long enough to be a shape at all
    nodes = [Node(id=-600 - i, lon=125.2 + 0.02 * i, lat=-23.3 + 0.01 * (i % 2))
             for i in range(5)]
    sq.nodes.update({n.id: n for n in nodes})
    sq.ways[-650] = Way(id=-650, refs=[n.id for n in nodes], tags={})
    sq.relations[-660] = Relation(
        id=-660, tags={'type': 'multipolygon', 'natural': 'water'},
        members=[Member('way', -650, 'outer'), Member('way', -651, 'outer')])
    layer.set_working_set(water_ws)
    assert not [k for k in layer.water_fills if k[1] == 'rel'], (
        'a ring the square edge cut was closed and filled'
    )
    assert (sq.name, -650) in layer.water, 'and it lost its outline as well'


def test_an_edit_that_closes_a_way_fills_it(water_ws):
    """The fill has to follow the edit, and the unit is the square: a way can
    be a relation's ring, and one way's change remakes that relation's path."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    wid = a_lake(sq, wid=-700, base=-700)
    sq.ways[wid].refs = sq.ways[wid].refs[:-1]            # opened
    layer.set_working_set(water_ws)
    assert (sq.name, 'way', wid) not in layer.water_fills

    sq.ways[wid].refs.append(sq.ways[wid].refs[0])        # closed again
    layer.refresh(sq, {wid})
    assert (sq.name, 'way', wid) in layer.water_fills, 'closing a lake did not fill it'


def test_the_fill_is_fainter_than_the_shore(water_ws, map_view):
    """Water is drawn over the surface preview and over the tiles. A body
    filled at the edge's own alpha blanks the ground the mapper is working
    against."""
    from danu.ui.contours import WATER, WATER_FILL
    assert WATER_FILL.alpha() < WATER.alpha() / 2
    assert (WATER_FILL.red(), WATER_FILL.green(), WATER_FILL.blue()) == \
           (WATER.red(), WATER.green(), WATER.blue()), 'it should be the same water'

    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, lon=125.4, lat=-23.5)
    layer.set_working_set(water_ws)
    map_view.scene().addItem(layer)
    map_view.set_zoom(12)
    map_view.center_on_lonlat(125.42, -23.48)
    render(map_view)
    assert layer.drawn_water_fills == 1, 'the lake was not filled when painted'


def test_an_edit_rebuilds_only_the_fills_its_ways_can_have_changed(water_ws):
    """Redoing the square costs 50 ms on the gobras square that holds seventy
    per cent of the water - a frame, on the UI thread, on every edit near a
    river. A way can only change its own fill and the relations that name it."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700, lon=125.3, lat=-23.6)
    a_lake(sq, wid=-800, base=-800, lon=125.6, lat=-23.2)
    sq.ways[-800].tags = {}
    sq.relations[-810] = Relation(id=-810, tags={'natural': 'water'},
                                  members=[Member('way', -800, 'outer')])
    layer.set_working_set(water_ws)
    assert (sq.name, 'way', -700) in layer.water_fills
    assert (sq.name, 'rel', -810) in layer.water_fills

    redone = []
    layer._relation_fill = lambda square, rel: redone.append(rel.id)
    layer.refresh(sq, {-700})
    assert redone == [], 'an edit to a lone lake rebuilt a relation that does not name it'

    layer.refresh(sq, {-800})
    assert redone == [-810], 'the relation holding the edited way was not rebuilt'


def test_a_way_that_stops_being_water_takes_its_fill_with_it(water_ws):
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    layer.set_working_set(water_ws)
    assert (sq.name, 'way', -700) in layer.water_fills

    sq.ways[-700].tags = {'ele': '120'}          # retagged as a contour
    layer.refresh(sq, {-700})
    assert (sq.name, 'way', -700) not in layer.water_fills, (
        'a lake retagged as a contour kept its blue fill'
    )


def test_a_deleted_lake_takes_its_fill_with_it(water_ws):
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    layer.set_working_set(water_ws)
    del sq.ways[-700]
    layer.refresh(sq, {-700})
    assert (sq.name, 'way', -700) not in layer.water_fills


def test_a_ring_missing_a_node_is_not_filled_across_the_gap(water_ws):
    """A way can be in a square whose nodes are not all in it. A line may stop
    short where a shape may not: joining the two sides of the gap draws a
    shore nobody mapped."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    del sq.nodes[-702]                            # one corner is in the next square
    layer.set_working_set(water_ws)
    assert (sq.name, 'way', -700) not in layer.water_fills, (
        'a lake was filled across a node the square does not hold'
    )
    assert (sq.name, -700) in layer.water, 'and it lost its outline as well'


def test_a_relation_that_stops_naming_a_ring_loses_the_fill(water_ws):
    """G5's reconciliation replaces superseded features, which rewrites member
    lists. A relation that loses its outer ring names no changed way id at
    all, so the changed ids alone cannot say the fill is stale."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    a_lake(sq, wid=-800, base=-800, lon=125.6, lat=-23.2)
    sq.ways[-700].tags = sq.ways[-800].tags = {}
    sq.relations[-900] = Relation(id=-900, tags={'natural': 'water'},
                                  members=[Member('way', -700, 'outer')])
    layer.set_working_set(water_ws)
    key = (sq.name, 'rel', -900)
    assert key in layer.water_fills

    # the relation drops its ring, and the edit that is reported names
    # neither the ring it lost nor any ring it gained - a river nearby. The
    # changed way ids cannot say the fill is stale; only the member list can
    river = a_river(9001, 125.5, -23.5)
    sq.nodes.update(river.nodes)
    sq.ways.update(river.ways)
    sq.relations[-900].members = []
    layer.refresh(sq, {9001})
    assert key not in layer.water_fills, (
        'the relation still fills a ring it no longer names'
    )

    # and it takes one up again the same way
    sq.relations[-900].members = [Member('way', -800, 'outer')]
    layer.refresh(sq, {9001})
    assert key in layer.water_fills, 'a ring the relation gained was not taken up'
    assert layer.water_fills[key].path.contains(
        QPointF(*m.lonlat_to_scene(125.62, -23.18)))


def test_a_deleted_relation_takes_its_fill_with_it(water_ws):
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    sq.ways[-700].tags = {}
    sq.relations[-900] = Relation(id=-900, tags={'natural': 'water'},
                                  members=[Member('way', -700, 'outer')])
    layer.set_working_set(water_ws)
    assert (sq.name, 'rel', -900) in layer.water_fills

    del sq.relations[-900]
    layer.refresh(sq, {-700})
    assert (sq.name, 'rel', -900) not in layer.water_fills, (
        'a deleted relation kept its fill'
    )


def test_a_relation_goes_stale_on_an_edit_that_touches_no_water_at_all(water_ws):
    """The staleness check has to be reachable. It used to sit behind a guard
    asking whether one of the changed ways had a fill or a line - false for an
    ordinary contour edit, which is precisely the edit that can have rewritten
    a member list and named no water way."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700)
    sq.ways[-700].tags = {}
    sq.relations[-900] = Relation(id=-900, tags={'natural': 'water'},
                                  members=[Member('way', -700, 'outer')])
    layer.set_working_set(water_ws)
    assert (sq.name, 'rel', -900) in layer.water_fills

    contour = next(w for w in sq.ways.values() if w.ele is not None)
    sq.relations[-900].members = []
    layer.refresh(sq, {contour.id})
    assert (sq.name, 'rel', -900) not in layer.water_fills, (
        'a relation that lost its ring kept the fill, because the edit that '
        'reported it touched no water'
    )


def test_a_closed_member_is_filled_though_the_rest_of_its_lake_is_cut(water_ws):
    """A member is skipped by `_way_fill` because its ring is in the
    relation's path. A review read that as losing the fill when the relation
    straddles the square edge and cannot be stitched - but a closed member
    *is* a ring, so `closed_rings` returns it whatever happens to the cut
    pieces around it, and the relation's path holds it. This is the test that
    was written to show the gap and showed the lake filled instead."""
    layer = ContourLayer()
    sq = water_ws.squares[HERE]
    a_lake(sq, wid=-700, base=-700, lon=125.3, lat=-23.6)
    sq.ways[-700].tags = {'natural': 'water'}
    nodes = [Node(id=-500 - i, lon=125.5 + 0.02 * i, lat=-23.3 + 0.01 * (i % 2))
             for i in range(5)]
    sq.nodes.update({n.id: n for n in nodes})
    sq.ways[-550] = Way(id=-550, refs=[n.id for n in nodes], tags={})
    sq.relations[-900] = Relation(
        id=-900, tags={'type': 'multipolygon', 'natural': 'water'},
        members=[Member('way', -700, 'outer'), Member('way', -550, 'outer'),
                 Member('way', -551, 'outer')])       # -551 is in the next square
    layer.set_working_set(water_ws)

    key = (sq.name, 'rel', -900)
    assert key in layer.water_fills, 'the ring that did close was not filled'
    assert layer.water_fills[key].path.contains(QPointF(*m.lonlat_to_scene(125.32, -23.58))), (
        'the closed member is not in the relation path that is meant to hold it'
    )
    assert (sq.name, 'way', -700) not in layer.water_fills, (
        'and it is not filled a second time on its own'
    )
    # the cut chain got nothing, which is the straddling answer
    assert (sq.name, 'way', -550) not in layer.water_fills
    assert (sq.name, -550) in layer.water, 'the cut piece lost its outline'
