"""The contour layer, offscreen, over a working set built from the golden
square and a blank neighbour."""

import lzma
import shutil
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QColor, QImage, QPainter

from danu.core.square import SquareName, WorkingSet
from danu.surface.ramp import traditional
from danu.ui import mercator as m
from danu.ui.app import MainWindow
from danu.ui.config import load_layers
from danu.ui.contours import INDEX_EVERY_N, ZOOM_ALL, ZOOM_INDEX, ZOOM_LABELS, ContourLayer
from danu.ui.mapview import MapView

GOLDEN = Path(__file__).parents[1] / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


@pytest.fixture
def zone(tmp_path):
    from danu.core.make_square import write_square
    shutil.copy(GOLDEN, tmp_path / GOLDEN.name)
    write_square(tmp_path / 'S24E126.osm.xz', 126, -24, 'frame')
    with lzma.open(tmp_path / 'EMPTY.osm.xz', 'wt') as f:
        f.write("<osm version='0.6' upload='never'></osm>")
    return tmp_path


@pytest.fixture
def ws(zone):
    return WorkingSet.open(zone, SquareName(125, -24))


@pytest.fixture
def view(qtbot):
    v = MapView()
    v.resize(900, 700)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    return v


def render(view) -> QImage:
    img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    p = QPainter(img)
    view.render(p)
    p.end()
    return img


def test_the_set_becomes_one_path_per_level_and_a_label_per_way(ws):
    layer = ContourLayer()
    layer.set_working_set(ws)
    assert set(layer.paths) == set(ws.elevations()) and len(layer.paths) == 22
    assert len(layer.labels) == 94
    assert all(-90 < lab.angle <= 90 for lab in layer.labels)     # upright
    w, s, e, n = ws.bounds
    x0, y0 = m.lonlat_to_scene(w, n)
    x1, y1 = m.lonlat_to_scene(e, s)
    assert layer.boundingRect() == layer.boundingRect().__class__(x0, y0, x1 - x0, y1 - y0)


def test_the_default_ramp_is_spectral_over_the_sets_own_range(ws):
    layer = ContourLayer()
    layer.set_working_set(ws)
    lo, hi = ws.elevation_range()
    assert layer.ramp.name == 'spectral' and (layer.ramp.lo, layer.ramp.hi) == (lo, hi)
    assert layer.colour(lo).name() == QColor(43, 131, 186).name()
    assert layer.colour(hi).name() == QColor(215, 25, 28).name()
    layer.set_working_set(ws, traditional())
    assert layer.ramp.name == 'relief.ramp'
    # alpha is ignored for lines: sea level draws
    assert layer.colour(0).alpha() == 255


def test_index_contours_are_every_fifth_level_until_the_ladder_is_inferred(ws):
    """Not every 100 m: this square's levels are 101, 145, 149, 151, ... and
    there is no round hundred among them, so that rule drew nothing."""
    layer = ContourLayer()
    layer.set_working_set(ws)
    levels = ws.elevations()
    assert not any(e % 100 == 0 for e in levels)
    assert layer.index_levels == set(levels[::5]) and len(layer.index_levels) == 5
    assert layer.is_index(levels[0]) and not layer.is_index(levels[1])


def test_level_of_detail_follows_the_zoom(view, ws):
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    view.fit_bounds(*ws.squares[SquareName(125, -24)].bounds)
    view.set_zoom(ZOOM_INDEX - 1)
    render(view)
    assert layer.drawn_levels == 0 and layer.drawn_labels == 0 and layer.drawn_ways == 0
    view.set_zoom(ZOOM_INDEX)
    render(view)
    assert layer.drawn_levels == len(layer.index_levels) == 5      # index only
    # closer in, the window has to be over the drawing: this square is
    # sparse and its degree's centre has no contour in it at all
    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    lon, lat = sq.coords(way)[len(way.refs) // 2]
    view.set_zoom(ZOOM_ALL)
    view.center_on_lonlat(lon, lat)
    render(view)
    assert layer.drawn_levels > len(layer.index_levels) and layer.drawn_labels == 0
    view.set_zoom(ZOOM_LABELS)
    render(view)
    assert layer.drawn_labels > 0
    # and back out, after something has been drawn. Zooming out from nothing
    # cannot catch a counter that is not reset, because it is still zero from
    # __init__ - the count has to be made stale first
    assert layer.drawn_ways > 0
    view.set_zoom(ZOOM_INDEX - 1)
    render(view)
    assert layer.drawn_levels == 0 and layer.drawn_labels == 0, 'a counter survived zooming out'
    assert layer.drawn_ways == 0, 'drawn_ways kept the last paint\'s count'


def test_a_contour_is_drawn_where_its_nodes_are_in_its_colour(view, ws):
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    way = next(w for w in sq.contours() if len(w.refs) > 20)
    lon, lat = sq.coords(way)[len(way.refs) // 2]
    view.set_zoom(14)
    view.center_on_lonlat(lon, lat)
    img = render(view)
    want = layer.colour(way.ele)
    x, y = view.viewport().rect().center().x(), view.viewport().rect().center().y()
    # antialiased 1 px line: look in a small window around the node for the colour
    hit = False
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            c = img.pixelColor(x + dx, y + dy)
            if abs(c.red() - want.red()) < 60 and abs(c.green() - want.green()) < 60 and abs(c.blue() - want.blue()) < 60 \
                    and (c.red(), c.green(), c.blue()) not in ((255, 255, 255), (235, 235, 235)):
                hit = True
    assert hit, f'no pixel near the node in {want.name()}'


def test_the_window_shows_the_contours_of_what_it_opened(qtbot, zone, tmp_path):
    from danu.ui.settings import Settings
    w = MainWindow(load_layers(), cache_dir=None, settings=Settings(tmp_path / 'danu.ini'))
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.open_working_set(zone, SquareName(125, -24))
    qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
    assert len(w.contours.paths) == 22
    assert '22 levels' in w.statusBar().currentMessage()
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.open_working_set(zone, SquareName(125, -24), size=1)
    qtbot.waitUntil(lambda: '1 of 1' in w.statusBar().currentMessage(), timeout=5000)


def test_main_refuses_half_an_open_request():
    from danu.ui.app import main
    with pytest.raises(SystemExit):
        main(['danu', '/some/zone'])


def test_a_node_the_square_lost_does_not_shift_the_index_onto_its_neighbour(ws):
    """JOSM will save a way whose node was deleted under it, so a ref can have
    no node. The points come from the refs that are placed, so pairing the
    way's full ref list with them afterwards put every ref after the gap on
    the next node's position - and dropped the last one. A click then snapped
    to one node and dragged another."""
    from danu.core.square import Node, Square, Way

    sq = Square(name=SquareName(87, 20), present=True)
    places = {1: (87.1, 20.1), 3: (87.3, 20.3), 4: (87.4, 20.4)}     # no node 2
    for i, (lon, lat) in places.items():
        sq.nodes[i] = Node(id=i, lat=lat, lon=lon)
    sq.ways[10] = Way(id=10, refs=[1, 2, 3, 4], tags={'ele': '100'})

    layer = ContourLayer()
    layer.set_working_set(WorkingSet(centre=sq.name, size=1, squares={sq.name: sq}))

    geom = layer._geoms[(sq.name, 10)]
    assert geom.refs == [1, 3, 4] and len(geom.pts) == 3, 'the refs follow the points'
    # asked for: the flat arrays are built when something picks, not when an
    # edit lands, so a test that reads them has to say it wants them
    layer._ensure_arrays()
    assert [ref for _, ref in layer._node_ref] == [1, 3, 4], 'no ref is dropped'
    for (square, ref), xy in zip(layer._node_ref, layer._node_xy, strict=True):
        node = square.nodes[ref]
        assert tuple(xy) == m.lonlat_to_scene(node.lon, node.lat), f'ref {ref} is at another node'


def test_the_layer_projects_a_way_where_the_scalar_projection_puts_it(ws):
    """The whole working set is projected at once now - 342,000 points on the
    gobras 3x3, and a Python call per point was a third of the time that took.

    To a thousandth of a pixel rather than to the last bit: numpy's
    log, tan and cos are not always the libm math reaches. What has to be exact
    is the layer agreeing with itself, and it does by construction - a
    contour's points and the node index's are the same array."""
    import numpy as np

    layer = ContourLayer()
    layer.set_working_set(ws)
    checked = 0
    for geom in layer._geoms.values():
        nodes = geom.square.nodes
        want = np.array([m.lonlat_to_scene(nodes[r].lon, nodes[r].lat) for r in geom.refs])
        worst = float(np.abs(geom.pts - want).max())
        assert worst < 1e-3, f'way {geom.way.id} is {worst} scene units from where the scalar puts it'
        checked += len(want)
    assert checked > 1000, f'only {checked} points were compared'
    # and the node index is the contour's own points, not a second projection.
    # Asked for, as above.
    layer._ensure_arrays()
    for geom in layer._geoms.values():
        start = layer._node_ref.index((geom.square, geom.refs[0]))
        assert np.array_equal(layer._node_xy[start:start + len(geom.pts)], geom.pts)
        break


def test_the_node_index_cache_is_a_cache_and_not_part_of_the_geometry():
    """WayGeom's lazily built node index was an annotated attribute in a
    dataclass body, which makes it a field: a constructor parameter, and part
    of __repr__ and __eq__. What a WayGeom is should not depend on whether
    something has asked it for its node index yet."""
    import dataclasses
    import inspect

    from danu.ui.contours import WayGeom

    cache = {f.name: f for f in dataclasses.fields(WayGeom)}['_node_ref']
    assert not cache.init and not cache.repr and not cache.compare
    assert '_node_ref' not in str(inspect.signature(WayGeom.__init__))

    import numpy as np

    from danu.core.square import Square, Way
    sq = Square(name=SquareName(87, 20), present=True)
    way = Way(id=1, refs=[1, 2], tags={'ele': '100'})
    geom = WayGeom(sq, way, 100.0, np.zeros((2, 2)), [1, 2])
    before = repr(geom)
    assert geom.node_ref == [(sq, 1), (sq, 2)]
    assert geom.node_ref is geom.node_ref, 'built once, not per call'
    assert repr(geom) == before, 'asking for the index changed what the geometry is'


def test_a_geometry_whose_refs_and_points_disagree_is_refused():
    """The node index puts refs against points one for one, so a WayGeom whose
    two did not line up would file a node at another node's position - the bug
    this pairing replaced. _project keeps them aligned; this is what says so
    for anything else that ever builds one."""
    import numpy as np
    import pytest as _pytest

    from danu.core.square import Square, Way
    from danu.ui.contours import WayGeom

    sq = Square(name=SquareName(87, 20), present=True)
    way = Way(id=1, refs=[1, 2, 3], tags={'ele': '100'})
    with _pytest.raises(ValueError, match='3 refs against 2 points'):
        WayGeom(sq, way, 100.0, np.zeros((2, 2)), [1, 2, 3])
    WayGeom(sq, way, 100.0, np.zeros((2, 2)), [1, 2])          # aligned, accepted
    WayGeom(sq, way, 100.0, np.zeros((2, 2)))                  # and no refs at all


def test_the_cull_follows_the_viewport(view, ws):
    """A level's ways joined into one path have a rectangle that spans the
    working set, so culling by it culls nothing: the gobras 3x3 redrew 341,694
    points on every paint, 150.8 ms of a 153 ms repaint, on every pan and every
    edit. Per way the rectangle is the way's own.

    What is asserted is that the number drawn follows the window, not a
    fraction. This fixture is one dense square where a long sinuous contour's
    rectangle overlaps most of the others - 76 of 94 ways at two zooms in - so a
    threshold here would be a fact about the fixture. On the gobras 3x3 the same
    code draws 235 ways of 6,305 at zoom 12 and 5 at zoom 16.
    """
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    total = sum(len(pieces) for pieces in layer.paths.values())
    assert total > 50, f'the fixture has only {total} ways to cull'

    # the same centre at two zooms, so only the window differs
    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    lon, lat = sq.coords(way)[len(way.refs) // 2]

    view.set_zoom(ZOOM_ALL)
    view.center_on_lonlat(lon, lat)
    render(view)
    wide = layer.drawn_ways
    assert wide > 0, 'nothing was drawn over a contour with the square in view'

    view.set_zoom(ZOOM_ALL + 6)
    view.center_on_lonlat(lon, lat)
    render(view)
    close = layer.drawn_ways

    assert 0 < close < wide, (
        f'{close} ways drawn zoomed in against {wide} zoomed out - '
        f'the cull does not follow the window')


def test_the_cull_drops_nothing_that_should_be_seen(view, ws):
    """The picture has to be the same picture. Rendered against a layer whose
    pieces all carry a rectangle covering everything - so nothing is culled -
    the two must agree pixel for pixel."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    lon, lat = sq.coords(way)[len(way.refs) // 2]

    def shot(no_cull, zoom):
        layer = ContourLayer()
        layer.set_working_set(ws)
        if no_cull:
            everywhere = QRectF(-1e12, -1e12, 2e12, 2e12)
            for pieces in layer.paths.values():
                for piece in pieces:
                    piece.rect = everywhere
        view.scene().addItem(layer)
        view.set_zoom(zoom)
        view.center_on_lonlat(lon, lat)
        img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img); view.render(p); p.end()
        drawn = layer.drawn_ways
        view.scene().removeItem(layer)
        return img, drawn

    # at several zooms, not one. The rectangles are in scene units and the cull
    # is the only thing between them and the window, so a fault that depended
    # on scale - the growth swamped at one end, a rounding at the other - would
    # sit outside a single sample. ZOOM_ALL is where every level starts being
    # drawn, so this brackets it.
    checked = 0
    for zoom in (ZOOM_ALL, ZOOM_ALL + 1, ZOOM_ALL + 3, ZOOM_ALL + 6):
        culled, n_culled = shot(False, zoom)
        whole, n_whole = shot(True, zoom)
        assert n_whole > n_culled, (
            f'at zoom {zoom} the unculled layer drew {n_whole} and the culled one '
            f'{n_culled} - nothing was culled, so this compares two identical renders')
        assert culled == whole, f'culling changed the picture at zoom {zoom}'
        checked += 1
    assert checked == 4

    # and that the comparison can detect the difference this test is about.
    # QImage's == is a content comparison - identical images compare equal, a
    # single differing pixel does not - but an assertion of sameness that could
    # not detect a difference would pass on any implementation at all. Two
    # renders at different zooms would show that much; this drops one level
    # from the picture at the same zoom and centre, which is the shape of
    # "the cull let something through that it should not have".
    zoom = ZOOM_ALL + 1
    full, _ = shot(False, zoom)
    short = ContourLayer()
    short.set_working_set(ws)
    dropped = sorted(short.paths)[len(short.paths) // 2]
    short.paths[dropped] = []
    view.scene().addItem(short)
    view.set_zoom(zoom)
    view.center_on_lonlat(lon, lat)
    img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img); view.render(p); p.end()
    view.scene().removeItem(short)
    assert img != full, (
        f'dropping the ways at {dropped} m changed no pixel, so comparing '
        f'images cannot see a cull that drops something')


def test_a_contour_running_due_east_is_not_culled(view, ws):
    """Its rectangle has no height, and QRectF.intersects is false for an empty
    rectangle - so an east-west contour would be culled wherever the window
    was, and vanish. The rectangles are grown by a unit for that reason; this
    is what says so.

    The way is drawn here rather than taken from a fixture, because the
    geometry *is* the test: every point at one latitude, which no fixture in
    this file happens to contain.
    """
    from danu.core import edits
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)

    sq = ws.squares[SquareName(125, -24)]
    alloc = edits.IdAllocator(sq)
    lat = -23.5
    lon0, lon1 = 125.2, 125.8
    # an elevation nothing else in the set uses, so `paths[7.0]` is this way
    # and the count below fails for the reason it names
    assert 7.0 not in layer.paths, 'the fixture already draws at 7 m'
    wid = alloc.take()
    cmd = edits.AddWay(wid, [alloc.take(), alloc.take()],
                       [(lon0, lat), (lon1, lat)], {'ele': '7'})
    cmd.apply(sq)
    layer.refresh(sq, {wid})

    pieces = layer.paths[7.0]
    assert len(pieces) == 1, 'the way drawn here is not the only one at 7 m'
    assert pieces[0].rect.height() > 0, (
        'the rectangle was not grown, so this contour has no height and '
        'QRectF.intersects would cull it from every window')

    view.set_zoom(ZOOM_ALL)
    view.center_on_lonlat((lon0 + lon1) / 2, lat)
    render(view)
    assert layer.drawn_ways > 0, 'a contour running due east was culled away'


def test_refreshing_a_way_twice_does_not_draw_it_twice(view, ws):
    """Each level's pieces are a list appended to, so a rebuild that failed to
    clear the level first would append every way again - every contour drawn
    twice, at twice the cost, looking only slightly heavier.

    `refresh` drops the way's own piece before adding the new one, so the way
    it had is gone from the level whether or not it stays at that elevation.
    This is what says so, because the shape that would break it is one line
    away: two structures before this one appended to a shared list and had the
    same hazard, so no spelling of it protects itself."""
    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    way = next(iter(sq.contours()))
    before = {ele: len(pieces) for ele, pieces in layer.paths.items()}

    layer.refresh(sq, {way.id})
    once = {ele: len(pieces) for ele, pieces in layer.paths.items()}
    assert once == before, 'refreshing a way changed how many pieces exist'

    layer.refresh(sq, {way.id})
    layer.refresh(sq, {way.id})
    assert {ele: len(p) for ele, p in layer.paths.items()} == before, \
        'refreshing the same way again appended it a second time'

    # and a way moved to another elevation leaves nothing behind at the old
    # one. `was` is read before the tag changes: Way.ele reads the tag, so
    # afterwards it names the new level and the check would look at the wrong
    # list and pass
    was = way.ele
    n_old = len(layer.paths[was])
    moved_to = max(layer.paths) + 1000.0
    sq.ways[way.id].tags['ele'] = str(moved_to)
    layer.refresh(sq, {way.id})
    assert len(layer.paths.get(was, [])) == n_old - 1, 'the way stayed at its old level'
    assert len(layer.paths[moved_to]) == 1


def test_the_flat_arrays_are_built_when_something_picks_not_when_an_edit_lands(view, ws):
    """Nothing in paint reads them - they are for picking a contour, picking a
    node, and the crossing check - so building them on every edit spent 14.5 ms
    of each one on an answer usually wanted later or never. Drawing a contour
    node by node paid it once a node and used it on none of them."""

    layer = ContourLayer()
    built = []
    real = layer._rebuild_arrays
    layer._rebuild_arrays = lambda: built.append(True) or real()

    layer.set_working_set(ws)
    assert built == [], 'opening a working set built the arrays before anything asked'

    sq = ws.squares[SquareName(125, -24)]
    way = next(iter(sq.contours()))
    for _ in range(3):
        layer.refresh(sq, {way.id})
    assert built == [], 'three edits built the arrays three times over'

    # the first pick builds them, and only the first
    layer.pick(0.0, 0.0, 1.0)
    assert len(built) == 1, f'picking built them {len(built)} times'
    layer.pick(0.0, 0.0, 1.0)
    layer.pick_node(0.0, 0.0, 1.0)
    layer.crossings((0.0, 0.0), (1.0, 1.0), 100.0)
    assert len(built) == 1, 'a second pick rebuilt arrays that had not gone stale'

    # and an edit after that makes them stale again
    layer.refresh(sq, {way.id})
    layer.pick(0.0, 0.0, 1.0)
    assert len(built) == 2, 'an edit did not make the arrays stale'


def test_picking_finds_a_contour_moved_since_the_last_pick(view, ws):
    """The point of the laziness is that nothing notices it. A way moved and
    then picked has to be found where it now is - if the staleness flag were
    not set, the pick would answer from the geometry before the edit."""
    from danu.core import edits
    from danu.ui import mercator as m

    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    nid = way.refs[len(way.refs) // 2]
    node = sq.nodes[nid]

    x, y = m.lonlat_to_scene(node.lon, node.lat)
    found = layer.pick(x, y, 1e6)
    assert found is not None and found[1].id == way.id

    # move that node a long way north, then pick where it went
    edits.MoveNode(nid, way.id, (node.lon, node.lat + 0.4)).apply(sq)
    layer.refresh(sq, {way.id})
    nx, ny = m.lonlat_to_scene(node.lon, node.lat)
    moved = layer.pick(nx, ny, 1.0)
    assert moved is not None and moved[1].id == way.id, (
        'the pick did not find the contour where the edit put it - the flat '
        'arrays were not rebuilt')


def test_a_label_outline_is_built_once_per_elevation(view, ws):
    """There are as many distinct label strings as elevations, and the same
    ones on every repaint."""
    from danu.ui.contours import ZOOM_LABELS

    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    lon, lat = sq.coords(way)[len(way.refs) // 2]
    view.set_zoom(ZOOM_LABELS)
    view.center_on_lonlat(lon, lat)

    # what was asked for, recorded: the cache should hold exactly the strings
    # the paint asked about, and asking is once per label while holding is once
    # per string
    asked = []
    real = layer._text_path
    layer._text_path = lambda text, font: asked.append(text) or real(text, font)

    render(view)
    assert layer.drawn_labels > 0, 'no labels were drawn, so nothing was cached'
    after_one = dict(layer._text)
    assert after_one, 'no outline was kept'
    assert {text for text, _font in after_one} == set(asked), (
        f'the cache holds {sorted(t for t, _ in after_one)} and the paint asked '
        f'for {sorted(set(asked))}')
    assert len(asked) > len(set(asked)), (
        'every label wanted a different string, so this fixture cannot show '
        'one outline being reused')
    assert {text for text, _font in after_one} <= {f'{lab.ele:g}' for lab in layer.labels}, \
        'an outline was cached for something that is not a label'

    asked.clear()
    render(view)
    assert layer._text.keys() == after_one.keys(), 'a repaint built new outlines'
    assert asked, 'the second paint did not ask for any outline at all'
    for key, path in after_one.items():
        assert layer._text[key] is path, f'the outline for {key[0]} was rebuilt'


def test_only_the_picks_read_the_flat_arrays():
    """The arrays are built when something asks, so any method that reads them
    without asking reads whatever the last edit left.

    Two halves, because the claim has two: that nothing outside `contours.py`
    names them at all, and that inside it every reader asks first. The second
    was checked here from the start; the first was asserted in a comment and
    checked by hand, which is not the same thing.

    A fourth reader is the shape of this bug and it would be silent: the arrays
    are usually current, because something usually picked before the edit.
    """
    import ast
    from pathlib import Path

    FLAT = {'_seg_a', '_seg_b', '_seg_ele', '_seg_way', '_seg_i', '_node_xy', '_node_ref'}
    root = Path(__file__).parents[2]
    outside = {}
    for path in sorted((root / 'danu').rglob('*.py')):
        if path.name == 'contours.py':
            continue
        names = {a.attr for a in ast.walk(ast.parse(path.read_text()))
                 if isinstance(a, ast.Attribute) and a.attr in FLAT}
        if names:
            outside[path.relative_to(root).as_posix()] = sorted(names)
    assert outside == {}, (
        f'{outside} name the flat arrays outside contours.py, where nothing '
        f'calls _ensure_arrays for them')

    src = (root / 'danu' / 'ui' / 'contours.py').read_text()
    layer = next(n for n in ast.parse(src).body
                 if isinstance(n, ast.ClassDef) and n.name == 'ContourLayer')

    def touches(fn):
        return {a.attr for a in ast.walk(fn)
                if isinstance(a, ast.Attribute) and a.attr in FLAT}

    def asks(fn):
        return any(isinstance(c.func, ast.Attribute) and c.func.attr == '_ensure_arrays'
                   for c in ast.walk(fn) if isinstance(c, ast.Call))

    builders = {'__init__', '_rebuild_arrays'}
    readers = {fn.name for fn in layer.body
               if isinstance(fn, ast.FunctionDef) and touches(fn) and fn.name not in builders}
    assert readers, 'no method reads the flat arrays, so this guard is watching nothing'
    unguarded = {name for name in readers
                 if not asks(next(fn for fn in layer.body
                                  if isinstance(fn, ast.FunctionDef) and fn.name == name))}
    assert unguarded == set(), (
        f'{sorted(unguarded)} read the flat arrays without calling _ensure_arrays, '
        f'so they answer from whatever the last edit left')


def test_a_label_outline_is_not_reused_across_fonts(view, ws):
    """QFont() resolves to the application default family, which a theme or a
    display can change under a running editor - and the cache is deliberately
    never cleared, so there is no eviction. If the font were not in the key, an
    outline built before the change would be served after it for ever."""
    from PySide6.QtGui import QFont

    layer = ContourLayer()
    layer.set_working_set(ws)
    small, large = QFont(), QFont()
    small.setPointSize(9)
    large.setPointSize(22)
    assert small.key() != large.key()

    a = layer._text_path('100', small)
    b = layer._text_path('100', large)
    assert a is not b, 'the same outline was served for two different fonts'
    assert a.boundingRect().height() < b.boundingRect().height()
    assert layer._text_path('100', small) is a, 'the first font stopped hitting'


def test_labels_start_exactly_at_their_zoom(view, ws):
    """The threshold, pinned at wherever it is rather than at a number.

    The level-of-detail test above uses ZOOM_LABELS for both the zoom and the
    expectation, so it follows the constant and cannot see it move. This checks
    the step: none at one zoom below, some at it. An off-by-one either way -
    labels a zoom early, or a zoom late - changes what a pan costs by about a
    third and nothing would say so.
    """
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    way = max(sq.contours(), key=lambda w: len(w.refs))
    lon, lat = sq.coords(way)[len(way.refs) // 2]

    # drawn_labels is cleared at the top of paint, with drawn_ways and
    # drawn_levels, so each render answers for itself and the order here is
    # readability rather than load-bearing
    view.set_zoom(ZOOM_LABELS - 1)
    view.center_on_lonlat(lon, lat)
    render(view)
    assert layer.drawn_ways > 0, 'no contour is on screen, so this says nothing about labels'
    assert layer.drawn_labels == 0, 'a label was drawn a zoom below ZOOM_LABELS'

    view.set_zoom(ZOOM_LABELS)
    view.center_on_lonlat(lon, lat)
    render(view)
    assert layer.drawn_labels > 0, 'no label was drawn at ZOOM_LABELS'


def test_labels_start_at_z14_and_above_where_every_contour_does():
    """Both halves of the contract, because they are different contracts.

    The relationship - labels above where every contour draws, with a gap - is
    the reasoning: the contours are what a mapper reads at z12 and z13, and the
    labels were about a third of what it cost to draw them there.

    The number is a measurement. 14 is where 11 labels cost 3 ms rather than
    where 86 cost 10, and changing it moves what a pan costs by about a third
    at two zooms. The test above cannot see that: it takes both the zoom it
    sets and the expectation from `ZOOM_LABELS`, so moving the constant to 13
    or 15 leaves it passing. Pinned here, so a change to the number is a change
    someone made on purpose.
    """
    assert ZOOM_LABELS == 14, (
        f'labels now start at z{ZOOM_LABELS}; the measurements behind 14 are in '
        f'the constant\'s own comment and in F5c, and want re-taking if it moves')
    assert ZOOM_LABELS > ZOOM_ALL + 1, (
        f'labels start at z{ZOOM_LABELS} and every contour at z{ZOOM_ALL}; they '
        f'were adjacent when labels cost a third of a repaint at both')


def test_refreshing_one_way_leaves_every_other_way_alone(ws):
    """The point of a piece per way, rather than per level.

    `refresh` used to rebuild every way at the elevations the edited ways were
    and are at, because a piece was reachable only through the level that held
    it. On the gobras 3x3 that was 723 ways and 28,618 points re-projected to
    move one node - 27 ms of phase 4's 50 ms budget, on every edit, at every
    zoom.

    Asserted by identity, which is the only way to see it: the pieces are
    rebuilt to the same coordinates, so equality would pass on the behaviour
    this exists to prevent.
    """
    from danu.core import edits

    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    way = next(w for w in sq.contours() if w.ele is not None)

    # the objects, not their ids: a dropped Label is freed and the next
    # allocation can land on its address, so a set of ids compares equal to
    # itself after a replacement. Holding the old ones keeps that honest
    before_pieces = list(layer.paths[way.ele])
    before_labels = list(layer.labels)
    assert len(before_pieces) > 1, 'the edited way is the only one at its level; this proves nothing'
    mine = layer._pieces[(sq.name, way.id)]

    ref = way.refs[len(way.refs) // 2]
    node = sq.nodes[ref]
    edits.MoveNode(ref, (node.lon, node.lat), (node.lon + 0.001, node.lat)).apply(sq)
    layer.refresh(sq, {way.id})

    now = layer.paths[way.ele]
    assert len(now) == len(before_pieces)
    kept = [p for p in before_pieces if p is not mine]
    for p in kept:
        assert any(q is p for q in now), 'refreshing one way replaced another piece at its level'
    assert not any(q is mine for q in now), 'the edited way kept its old piece'

    # and the labels follow the pieces: one replaced, the rest untouched
    gone = [lab for lab in before_labels if not any(lab is x for x in layer.labels)]
    assert len(gone) == 1 and gone[0] is mine.label


def test_a_way_that_loses_its_level_takes_the_level_with_it(ws):
    """A level with no ways left is removed rather than left empty, because
    `index_levels` counts every fifth *drawn* level and an empty one would
    shift the index contours - and `paint` would iterate it for nothing."""
    from danu.core import edits

    layer = ContourLayer()
    layer.set_working_set(ws)
    alone = next(ele for ele, pieces in layer.paths.items() if len(pieces) == 1)
    # the way that owns the piece, not the first way at that elevation: a way
    # with fewer than two placed nodes is not projected and draws nothing, so
    # asking the square would be asking a different question
    piece = layer.paths[alone][0]
    name, wid = next(k for k, p in layer._pieces.items() if p is piece)
    sq = ws.squares[name]

    edits.DeleteWay(wid).apply(sq)
    layer.refresh(sq, {wid})
    assert alone not in layer.paths
    assert alone not in layer.index_levels


def test_a_new_level_moves_the_index_contours(ws):
    """`index_levels` is every fifth drawn level, so a level appearing renumbers
    the rest. An edit works it out again only when a level appeared or emptied -
    which is the only thing that can change it - so this is what says the
    condition is right rather than merely cheap.

    Asserted as which levels are index contours, not as the set having changed:
    a set that differs would also pass for a `_reindex` that had simply added
    the new level to the old answer, which is the plausible wrong version.
    """
    from danu.core import edits

    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    before = set(layer.index_levels)
    lowest = min(layer.paths)
    new = lowest - 1.0
    assert new not in layer.paths

    alloc = edits.IdAllocator(sq)
    wid = alloc.take()
    edits.AddWay(wid, [alloc.take(), alloc.take()],
                 [(125.2, -23.5), (125.8, -23.5)], {'ele': f'{new:g}'}).apply(sq)
    layer.refresh(sq, {wid})

    assert new in layer.paths
    # the new level sorts first, so it takes the place the old lowest had and
    # every index contour above it steps down one
    assert lowest in before, 'the fixture\'s lowest level was not an index contour'
    assert new in layer.index_levels, 'the level that now sorts first is not an index contour'
    assert lowest not in layer.index_levels, 'the index contours did not renumber'
    assert layer.index_levels == set(sorted(layer.paths)[::INDEX_EVERY_N])


def test_a_spot_height_is_drawn_at_every_zoom_the_layer_draws_at(view, ws):
    """A spot height is not a level - there is one of it - so hiding it with
    the intermediate contours would hide the only thing that says how high the
    hill goes, which is the whole of R37."""
    from danu.core import edits
    from danu.core.square import Node

    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    alloc = edits.IdAllocator(sq)
    nid = alloc.take()
    lon, lat = 125.5, -23.5
    sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat, tags={'ele': '243'})
    layer.refresh_spots(sq, {nid})
    assert (sq.name, nid) in layer.spots

    for zoom in (ZOOM_INDEX, ZOOM_ALL, ZOOM_LABELS, 16):
        view.set_zoom(zoom)
        view.center_on_lonlat(lon, lat)
        r = view.mapToScene(view.viewport().rect()).boundingRect()
        spot = layer.spots[(sq.name, nid)]
        render(view)
        assert layer.drawn_spots == 1, (
            f'not drawn at z{zoom}: spot ({spot.x:.0f},{spot.y:.0f}) in {r}')


def test_a_spot_height_outside_the_view_is_not_drawn(view, ws):
    from danu.core import edits
    from danu.core.square import Node

    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    nid = edits.IdAllocator(sq).take()
    sq.nodes[nid] = Node(id=nid, lon=125.1, lat=-23.1, tags={'ele': '243'})
    layer.refresh_spots(sq, {nid})

    view.set_zoom(16)
    view.center_on_lonlat(125.9, -23.9)
    render(view)
    assert layer.drawn_spots == 0, 'a spot height off the screen was drawn'


def test_a_node_that_stops_carrying_an_elevation_stops_being_drawn(view, ws):
    from danu.core import edits
    from danu.core.square import Node

    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    nid = edits.IdAllocator(sq).take()
    sq.nodes[nid] = Node(id=nid, lon=125.5, lat=-23.5, tags={'ele': '243'})
    layer.refresh_spots(sq, {nid})
    assert (sq.name, nid) in layer.spots

    sq.nodes[nid].tags = {}
    layer.refresh_spots(sq, {nid})
    assert (sq.name, nid) not in layer.spots
    del sq.nodes[nid]
    layer.refresh_spots(sq, {nid})               # and a node that is gone entirely
    assert (sq.name, nid) not in layer.spots


def test_the_nearest_spot_height_is_the_one_picked(view, ws):
    from danu.core import edits
    from danu.core.square import Node

    layer = ContourLayer()
    layer.set_working_set(ws)
    sq = ws.squares[SquareName(125, -24)]
    alloc = edits.IdAllocator(sq)
    near, far = alloc.take(), alloc.take()
    sq.nodes[near] = Node(id=near, lon=125.5, lat=-23.5, tags={'ele': '243'})
    sq.nodes[far] = Node(id=far, lon=125.6, lat=-23.5, tags={'ele': '250'})
    layer.refresh_spots(sq, {near, far})

    x, y = m.lonlat_to_scene(125.51, -23.5)
    hit = layer.pick_spot(x, y, m.lonlat_to_scene(125.6, -23.5)[0] - m.lonlat_to_scene(125.5, -23.5)[0])
    assert hit is not None and hit[1] == near
    assert layer.pick_spot(x, y, 0.001) is None, 'a spot height was picked from far outside the tolerance'
