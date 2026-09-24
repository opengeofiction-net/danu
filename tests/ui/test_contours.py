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
    assert layer.drawn_levels == 0 and layer.drawn_labels == 0
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
    # and the node index is the contour's own points, not a second projection
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
