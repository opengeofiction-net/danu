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
from danu.ui.contours import INDEX_EVERY_N, ZOOM_ALL, ZOOM_INDEX, ZOOM_LABELS, ZOOM_SPOTS, ContourLayer
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
    # the zones asked of the drop as the window opened: answered first, or on
    # a slow runner its "not reached" lands on the status bar after the levels
    qtbot.waitUntil(lambda: 'drop not reached' in w.zone_editor.dock.status.text(), timeout=10000)
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
        assert tuple(xy) == layer.node_xy(square, ref), f'ref {ref} is at another node'


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


def test_a_square_projected_in_one_call_is_each_way_projected_alone(ws):
    """``_project_all`` - a square's ways in one numpy call, as a set opens -
    keeps and drops the ways ``_project`` does, with their levels, refs and
    points."""
    import numpy as np

    from danu.ui.contours import _water_members

    for square in ws.squares.values():
        members = _water_members(square)
        many = {g.way.id: g for g in ContourLayer._project_all(square, square.ways.values(), members)}
        one = {w.id: g for w in square.ways.values() if (g := ContourLayer._project(square, w, members))}
        assert many.keys() == one.keys()
        for wid, g in one.items():
            assert (many[wid].ele, many[wid].refs) == (g.ele, g.refs)
            assert np.allclose(many[wid].pts, g.pts, rtol=0, atol=1e-9)


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
                    piece.pts = None                 # and drawn whole, not in parts
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


def test_a_long_way_is_drawn_in_view_by_its_parts_as_it_is_whole(view, ws):
    """A contour of thousands of vertices across the square, at zooms where
    the view is a sliver of it: drawn by its parts in view, a line a run of
    them, the picture is the one drawn whole - and a repaint of the same view
    builds no line again."""
    import math

    from danu.core import edits
    from danu.ui import contours
    sq = ws.squares[SquareName(125, -24)]
    alloc = edits.IdAllocator(sq)
    n = 4000
    pts = [(125.1 + 0.8 * k / n, -23.5 + 0.01 * math.sin(k / 15)) for k in range(n)]
    wid = alloc.take()
    edits.AddWay(wid, [alloc.take() for _ in pts], pts, {'ele': '7'}).apply(sq)
    layer = ContourLayer()
    layer.set_working_set(ws)
    view.scene().addItem(layer)
    (piece,) = layer.paths[7.0]

    def inner(img):
        return img.copy(2, 2, img.width() - 4, img.height() - 4)
    checked = 0
    for zoom, k in ((ZOOM_ALL + 3, 1000), (ZOOM_ALL + 6, 2100), (ZOOM_ALL + 8, 3999)):
        view.set_zoom(zoom)
        view.center_on_lonlat(*pts[k])
        img = render(view)
        assert piece.runs[0] and sum(b - a for a, b in piece.runs[0]) < len(piece.parts) / 4, (
            f'at zoom {zoom} the way was drawn whole or nearly: {piece.runs[0]}')
        lines = piece.runs[1]
        assert render(view) == img and piece.runs[1] is lines, 'the same view built its lines again'
        keep, piece.pts = piece.pts, None
        # but for the image's outer two pixels: the whole way runs 40 km off
        # it, and Qt draws where so long a path leaves the image a pixel or
        # two apart from where a run of its parts does, its ends as far out
        whole = render(view)
        assert inner(whole) == inner(img), f'drawn in parts, the picture changed at zoom {zoom}'
        piece.pts = keep
        checked += 1
    assert checked == 3 and contours.PART_N < n
    view.scene().removeItem(layer)


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

    # an edit that only moves points patches them in place
    n = sq.nodes[way.refs[1]]
    n.lon, n.lat = n.lon + 0.001, n.lat + 0.001
    layer.refresh(sq, {way.id})
    layer.pick(0.0, 0.0, 1.0)
    assert len(built) == 1, 'an edit that moved no node in or out built them again'

    # and one that changes a way's nodes makes them stale again
    way.refs.pop(1)
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

    FLAT = {'_seg_a', '_seg_b', '_seg_lo', '_seg_hi', '_seg_ele', '_seg_way', '_seg_i', '_node_xy', '_node_ref'}
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

    # _patch_arrays writes them in place, and refuses when they are stale
    builders = {'__init__', '_rebuild_arrays', '_patch_arrays'}
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


def test_a_spot_height_is_drawn_from_its_own_zoom_up(view, ws):
    """Not with the index contours, which is where these went first: a working
    set holds a spot height per hilltop, and at z8 to z11 they are a scatter of
    dots over contours too coarse to place them against."""
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

    for zoom in (ZOOM_INDEX, ZOOM_ALL, ZOOM_SPOTS - 1):
        view.set_zoom(zoom)
        view.center_on_lonlat(lon, lat)
        render(view)
        assert layer.drawn_spots == 0, f'a spot height was drawn at z{zoom}'
    for zoom in (ZOOM_SPOTS, ZOOM_LABELS, 16):
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
    wide = m.lonlat_to_scene(125.6, -23.5)[0] - m.lonlat_to_scene(125.5, -23.5)[0]
    hit = layer.pick_spot(x, y, wide, ZOOM_SPOTS)
    assert hit is not None and hit[1] == near
    assert layer.pick_spot(x, y, 0.001, ZOOM_SPOTS) is None, (
        'a spot height was picked from far outside the tolerance')
    # and nothing at all below the zoom they are drawn at
    assert layer.pick_spot(x, y, wide, ZOOM_SPOTS - 1) is None, (
        'a spot height was picked where it is not drawn')


def _line_pixel(view, img):
    """The pixel nearest the view's centre that a line drew - darker than
    the background around it."""
    cx, cy = view.viewport().rect().center().x(), view.viewport().rect().center().y()
    best = None
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            c = img.pixelColor(cx + dx, cy + dy)
            if best is None or c.value() < best.value():
                best = c
    return best


def a_ground(rect=None):
    """A surface layer drawn under everything - or under ``rect`` - which is
    what 'height' burns into."""
    from PySide6.QtCore import QRectF

    from danu.ui.surface import SurfaceLayer
    g = SurfaceLayer()
    g.shaded = object()
    g._rect = rect if rect is not None else QRectF(-m.WORLD, -m.WORLD, 3 * m.WORLD, 3 * m.WORLD)
    return g


@pytest.mark.parametrize('style', ['dark', 'height'])
def test_the_lines_meet_the_ground_as_the_style_says(view, ws, style):
    """Dark: multiplied, over the view's grey the dark itself times the grey.
    Height colour, over a surface: the level's own colour burned into it -
    darker than the colour drawn plain, and of its hue. (The grey stands in
    for the surface here; burned, it is what the test can work the answer
    out from.)"""
    from danu.ui.contours import DARK
    layer = ContourLayer()
    layer.set_working_set(ws)
    layer.ground = a_ground()
    layer.set_style(style)
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    way = next(w for w in sq.contours() if len(w.refs) > 20 and not layer.is_index(w.ele))
    lon, lat = sq.coords(way)[len(way.refs) // 2]
    view.set_zoom(14)
    view.center_on_lonlat(lon, lat)
    img = render(view)
    c = _line_pixel(view, img)
    grey = 235 / 255
    if style == 'dark':
        want = [round(255 * v * grey) for v in (DARK.redF(), DARK.greenF(), DARK.blueF())]
        assert max(abs(a - b) for a, b in zip((c.red(), c.green(), c.blue()), want, strict=True)) < 40, (c.name(), want)
    else:
        s = layer.colour(way.ele)
        burn = [round(255 * (1 - min(1, (1 - grey) / max(v, 1e-6)))) for v in (s.redF(), s.greenF(), s.blueF())]
        assert max(abs(a - b) for a, b in zip((c.red(), c.green(), c.blue()), burn, strict=True)) < 60, (c.name(), burn)
        assert c.value() < s.value() or s.value() < 60, 'not burned'


@pytest.mark.parametrize('style', ['dark', 'height'])
@pytest.mark.parametrize('zoom', [12, 16])
def test_each_line_is_drawn_in_the_mode_and_colour_its_style_asks(view, ws, zoom, style, monkeypatch):
    """Read from the painter: the mode each line is drawn under and its pen,
    at whatever zoom, and the mode put back before what goes over them."""
    from PySide6.QtGui import QPainter

    from danu.ui.contours import DARK
    seen = []
    real_mode, real_path = QPainter.setCompositionMode, QPainter.drawPath
    monkeypatch.setattr(QPainter, 'setCompositionMode', lambda p, m: (seen.append(('mode', m)), real_mode(p, m))[1])
    monkeypatch.setattr(QPainter, 'drawPath', lambda p, path: (seen.append(('line', p.pen().color().name(),
                                                                            p.compositionMode(), p.pen().widthF())),
                                                               real_path(p, path))[1])
    layer = ContourLayer()
    layer.set_working_set(ws)
    layer.ground = a_ground()
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    way = next(w for w in sq.contours() if len(w.refs) > 20)
    layer.set_active(way.ele)                      # the level the view is on
    layer.set_style(style)
    view.set_zoom(zoom)
    view.center_on_lonlat(*sq.coords(way)[len(way.refs) // 2])
    render(view)
    M = QPainter.CompositionMode
    lines = [e for e in seen if e[0] == 'line']
    want_mode = M.CompositionMode_Multiply if style == 'dark' else M.CompositionMode_ColorBurn
    blended = [e for e in lines if e[2] == want_mode]
    assert blended, "no line drawn in the style's mode"
    if style == 'dark':
        assert {e[1] for e in blended} == {DARK.name()}
    else:
        assert DARK.name() not in {e[1] for e in blended} and len({e[1] for e in blended}) > 1, "not the levels' colours"
    from danu.ui.contours import line_width
    assert {round(e[3], 2) for e in blended} <= {line_width(zoom, False), line_width(zoom, True)}
    assert any(e[3] == pytest.approx(line_width(zoom, False)) for e in blended), 'no ordinary contour at its width'
    # the active level, heavier, drawn plain over the rest
    from danu.ui.contours import ACTIVE, ACTIVE_WIDTH
    active = [e for e in lines if e[3] == pytest.approx(ACTIVE_WIDTH)]
    assert active and all(e[2] == M.CompositionMode_SourceOver for e in active)
    assert {e[1] for e in active} == {ACTIVE.name()} == {'#000000'}, 'the active level not black'
    assert ACTIVE_WIDTH > 1.5 * line_width(zoom, True), 'not plainly heavier than an index contour'


def test_contours_are_thinner_where_dense_and_heavier_where_few():
    from danu.ui.contours import line_width
    assert [line_width(z, False) for z in (11, 12, 13, 15, 16, 19)] == [0.7, 0.7, 1.0, 1.0, 1.2, 1.2]
    assert (line_width(12.4, False), line_width(12.6, False)) == (0.7, 1.0), 'a zoom between, to the nearer'
    assert all(line_width(z, True) > line_width(z, False) * 1.7 for z in (12, 14, 16)), 'index not heavier'


def test_height_with_no_surface_under_it_is_its_own_colour(view, ws):
    """Burned into the map's near-white, a colour is near-white again: before
    a surface was built, height drew nothing that could be seen. With nothing
    to burn into, a line is its level's colour laid on as it is."""
    layer = ContourLayer()
    layer.set_working_set(ws)
    layer.set_style('height')
    view.scene().addItem(layer)
    sq = ws.squares[SquareName(125, -24)]
    # a level of a definite colour: the ramp's palest are as pale as the
    # background, which is the ramp's and not this
    way = next(w for w in sq.contours() if len(w.refs) > 20 and not layer.is_index(w.ele)
               and layer.colour(w.ele).value() < 200)
    lon, lat = sq.coords(way)[len(way.refs) // 2]
    view.set_zoom(14)
    view.center_on_lonlat(lon, lat)
    c = _line_pixel(view, render(view))
    s = layer.colour(way.ele)
    grey = 235 / 255
    burned = [round(255 * (1 - min(1, (1 - grey) / max(v, 1e-6)))) for v in (s.redF(), s.greenF(), s.blueF())]
    got = (c.red(), c.green(), c.blue())

    def far(a, b):
        return max(abs(x - y) for x, y in zip(a, b, strict=True))
    # seen, and as its own colour rather than as the burn of it - measured
    # against which it is nearer, since antialiasing differs between
    # platforms by more than a fixed tolerance allows (Windows: 41)
    assert far(got, (235, 235, 235)) > 40, ('not seen against the background', c.name())
    assert far(got, (s.red(), s.green(), s.blue())) < far(got, burned), (c.name(), s.name(), burned)


def test_height_burns_only_where_a_surface_is_drawn():
    """Burned under the surface, laid on as itself beside it - and as itself
    everywhere with none built, the surface hidden or faded to nothing."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    M = QPainter.CompositionMode
    layer = ContourLayer()
    view_rect = QRectF(0, 0, 100, 100)
    assert layer.blends(True, view_rect) == [(M.CompositionMode_Multiply, None)], 'dark is dark'
    assert layer.blends(False, view_rect) == [(M.CompositionMode_SourceOver, None)], 'no surface'
    layer.ground = a_ground()
    assert layer.blends(False, view_rect) == [(M.CompositionMode_ColorBurn, None)]
    layer.ground.shaded = None                          # the window's own, before a build
    assert layer.blends(False, view_rect) == [(M.CompositionMode_SourceOver, None)], 'nothing built'
    layer.ground = a_ground()
    layer.ground.setOpacity(0.0)
    assert layer.blends(False, view_rect) == [(M.CompositionMode_SourceOver, None)], 'faded to nothing'
    layer.ground.setOpacity(1.0)
    layer.ground.setVisible(False)
    assert layer.blends(False, view_rect) == [(M.CompositionMode_SourceOver, None)], 'hidden'
    layer.ground = a_ground(QRectF(0, 0, 50, 100))     # the west half of the view
    (burn, inside), (plain, outside) = layer.blends(False, view_rect)
    assert (burn, plain) == (M.CompositionMode_ColorBurn, M.CompositionMode_SourceOver)
    assert inside.contains(QRectF(10, 10, 30, 80)) and not inside.intersects(QRectF(60, 10, 30, 80))
    assert outside.contains(QRectF(60, 10, 30, 80)) and not outside.intersects(QRectF(10, 10, 30, 80))
    layer.ground = a_ground(QRectF(200, 200, 50, 50))  # off to one side
    assert layer.blends(False, view_rect) == [(M.CompositionMode_SourceOver, None)]


def test_a_style_it_does_not_know_is_refused():
    with pytest.raises(ValueError):
        ContourLayer().set_style('neon')



def test_the_windows_contours_burn_into_its_surface(window):
    """What was seen: a window opened with no surface built, height chosen,
    and no contours to be seen. The layer has to be told which surface it is
    over, and is - and, with nothing built yet, draws as itself."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    assert window.contours.ground is window.surface
    assert window.contours.blends(False, QRectF(0, 0, 1, 1)) == [
        (QPainter.CompositionMode.CompositionMode_SourceOver, None)]


def test_a_coastlines_marks_point_the_way_it_runs_with_the_sea_on_their_right(view, ws):
    """West to east, the sea is to the south - +y on a scene whose y runs
    down - and the marks are COAST_SPACING_PX apart on screen at any zoom.
    Turned round, they turn with it. A coastline with no ele, which no level
    draws, is drawn by the marks' pass too."""
    from danu.core.square import Node, Way
    from danu.ui.contours import COAST_SPACING_PX
    sq = ws.squares[SquareName(126, -24)]
    for i in range(5):
        sq.nodes[-900 - i] = Node(id=-900 - i, lat=-23.5, lon=126.1 + 0.05 * i)
    sq.ways[-990] = Way(id=-990, refs=[-900 - i for i in range(5)], tags={'natural': 'coastline', 'ele': '0'})
    sq.ways[-991] = Way(id=-991, refs=[-900, -901], tags={'natural': 'coastline'})
    layer = ContourLayer()
    layer.set_working_set(ws)
    key = (sq.name, -990)
    assert key in layer.coasts and (sq.name, -991) in layer.coasts
    for scale in (0.05, 0.5):
        marks = layer.coast_marks(key, scale)
        assert len(marks) > 2
        assert all(dx == pytest.approx(1) and dy == pytest.approx(0, abs=1e-9) for _, _, dx, dy in marks)
        gaps = {round((b[0] - a[0]) * scale, 6) for a, b in zip(marks, marks[1:], strict=False)}
        assert gaps == {COAST_SPACING_PX}
    sq.ways[-990].refs.reverse()
    layer.refresh(sq, {-990})
    assert all(dx == pytest.approx(-1) for _, _, dx, _ in layer.coast_marks(key, 0.5))
    view.scene().addItem(layer)
    view.set_zoom(14)
    view.center_on_lonlat(126.2, -23.5)
    img = render(view)
    assert layer.drawn_coast_marks > 0
    # the ticks on the sea side - north of the line now it runs east to
    # west, and never south of it
    from danu.ui.contours import COAST_SEA
    line_y = view.mapFromScene(*m.lonlat_to_scene(126.2, -23.5)).y()

    def sea_pixels(y0, y1):
        return sum(1 for y in range(y0, y1) for x in range(img.width())
                   if QColor(img.pixel(x, y)).getRgb()[:3] == COAST_SEA.getRgb()[:3])
    assert sea_pixels(line_y - 20, line_y - 4) > 0 and sea_pixels(line_y + 3, line_y + 20) == 0
    sq.ways[-990].tags.pop('natural')
    sq.ways[-991].tags.pop('natural')
    layer.refresh(sq, {-990, -991})
    render(view)
    assert key not in layer.coasts and layer.drawn_coast_marks == 0
