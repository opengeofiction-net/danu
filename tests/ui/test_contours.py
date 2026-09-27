"""The contour layer, offscreen, over a working set built from the golden
square and a blank neighbour."""

import lzma
import shutil
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QColor, QImage, QPainter                       # noqa: E402

from danu.core.square import SquareName, WorkingSet, read_square           # noqa: E402
from danu.surface.ramp import spectral, traditional                        # noqa: E402
from danu.ui import mercator as m                                          # noqa: E402
from danu.ui.app import MainWindow                                         # noqa: E402
from danu.ui.config import load_layers                                     # noqa: E402
from danu.ui.contours import ZOOM_ALL, ZOOM_INDEX, ZOOM_LABELS, ContourLayer  # noqa: E402
from danu.ui.mapview import MapView                                        # noqa: E402

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
    for (square, ref), xy in zip(layer._node_ref, layer._node_xy):
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

    `_rebuild_levels` pops each level before refilling it, and `refresh` puts
    both the elevation a way had and the one it has into that set. This is what
    says so, because the shape that would break it is one line away: the
    previous structure was a path per level and appending to it had the same
    hazard, so neither spelling protects itself."""
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
    from danu.core import edits

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
    import numpy as np
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

    render(view)
    assert layer.drawn_labels > 0, 'no labels were drawn, so nothing was cached'
    after_one = dict(layer._text)
    assert after_one, 'no outline was kept'
    assert len(after_one) <= len(layer.paths), 'more outlines than elevations'

    render(view)
    assert layer._text.keys() == after_one.keys(), 'a repaint built new outlines'
    for text, path in after_one.items():
        assert layer._text[text] is path, f'the outline for {text} was rebuilt'
