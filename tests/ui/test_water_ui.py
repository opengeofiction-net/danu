"""The water import in the editor - G4c, without the network.

The fetch is injected, as the tile and territory fetchers' are. What is under
test is the queue, the one-step history across several squares, and the
drawing.
"""

import copy

import pytest

pytest.importorskip('PySide6')

from danu.core.square import Member, Node, Relation, SquareName, Way, WorkingSet
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
