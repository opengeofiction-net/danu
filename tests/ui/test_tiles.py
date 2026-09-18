"""Tile layers, without a network: a fetcher whose sending is recorded rather
than done, pixmaps handed to it directly, and the view rendered offscreen."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QRectF                                   # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap         # noqa: E402
from PySide6.QtNetwork import QNetworkRequest                       # noqa: E402

from danu import __version__                                        # noqa: E402
from danu.ui import mercator as m                                   # noqa: E402
from danu.ui.app import MainWindow                                  # noqa: E402
from danu.ui.config import Layer, load_layers                       # noqa: E402
from danu.ui.mapview import MapView                                 # noqa: E402
from danu.ui.tiles import USER_AGENT, TileFetcher, TileLayer        # noqa: E402


class RecordingFetcher(TileFetcher):
    """Records what would have been sent; sends nothing."""

    def __init__(self, **kw):
        super().__init__(cache_dir=None, **kw)
        self.sent: list[QNetworkRequest] = []

    def _send(self, req):
        self.sent.append(req)
        return None


def solid(colour: str) -> QPixmap:
    pm = QPixmap(256, 256)
    pm.fill(QColor(colour))
    return pm


LAYER = Layer(name='t', url='https://tiles.test/t/{z}/{x}/{y}.png', max_zoom=10)


@pytest.fixture
def view(qtbot):
    v = MapView()
    v.resize(800, 600)
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


# ----------------------------------------------------------- the request

def test_the_request_names_danu_takes_x_as_given_and_prefers_the_cache():
    f = RecordingFetcher()
    req = f.request_for(LAYER, 3, 9, 2)         # x=9 is off the world at z3
    assert req.url().toString() == 'https://tiles.test/t/3/9/2.png'   # request_for does not wrap; paint does
    assert req.header(QNetworkRequest.KnownHeaders.UserAgentHeader) == USER_AGENT
    assert USER_AGENT.startswith(f'Danu/{__version__} (+https://')
    assert 'Chrome' not in USER_AGENT and 'Mozilla' not in USER_AGENT
    assert req.attribute(QNetworkRequest.Attribute.CacheLoadControlAttribute) == \
        QNetworkRequest.CacheLoadControl.PreferCache


def test_a_tile_is_asked_for_again_while_nothing_is_in_flight_and_never_once_refused():
    f = RecordingFetcher()
    f.request(LAYER, 5, 1, 1)
    f.request(LAYER, 5, 1, 1)
    assert len(f.sent) == 2         # _send returned None so nothing was in flight
    f.failed.add(('t', 5, 1, 1))
    f.request(LAYER, 5, 1, 1)
    assert len(f.sent) == 2


class Reply:
    """Just enough of a QNetworkReply for _finished."""
    def __init__(self, error, data=b''):
        self._error, self._data = error, data
    def error(self): return self._error
    def readAll(self): return self._data
    def deleteLater(self): pass


def test_the_server_refusing_is_final_but_a_fault_on_the_way_is_retried_later():
    from PySide6.QtNetwork import QNetworkReply
    E = QNetworkReply.NetworkError
    f = RecordingFetcher()
    f._finished(('t', 5, 1, 1), Reply(E.ContentNotFoundError))
    assert ('t', 5, 1, 1) in f.failed
    f._finished(('t', 5, 2, 2), Reply(E.TimeoutError))
    assert ('t', 5, 2, 2) not in f.failed and ('t', 5, 2, 2) in f.retry_at
    f.request(LAYER, 5, 2, 2)
    assert len(f.sent) == 0                     # too soon
    f.retry_at[('t', 5, 2, 2)] = 0.0            # the wait is over
    f.request(LAYER, 5, 2, 2)
    assert len(f.sent) == 1
    # a 200 that is not an image is the server's doing
    f._finished(('t', 5, 3, 3), Reply(E.NoError, b'<html>not a tile</html>'))
    assert ('t', 5, 3, 3) in f.failed


def test_the_pixmap_ring_evicts_the_oldest():
    f = RecordingFetcher(ring=3)
    for i in range(5):
        f.put('t', 1, i, 0, solid('red'))
    assert f.pixmap(LAYER, 1, 0, 0) is None and f.pixmap(LAYER, 1, 1, 0) is None
    assert f.pixmap(LAYER, 1, 4, 0) is not None
    f.pixmap(LAYER, 1, 2, 0)                    # touched, so it survives the next put
    f.put('t', 1, 9, 0, solid('red'))
    assert f.pixmap(LAYER, 1, 3, 0) is None and f.pixmap(LAYER, 1, 2, 0) is not None


# ------------------------------------------------------------- the layer

def test_painting_asks_for_exactly_the_visible_tiles_wrapped(view, qtbot):
    f = RecordingFetcher()
    item = TileLayer(LAYER, f)
    view.scene().addItem(item)
    view.set_zoom(6)
    view.center_on_lonlat(87.5, 20.5)
    render(view)
    r = view.visible_scene_rect()
    want = {(6, m.wrap_x(x, 6), y) for _, x, y in m.tiles_in_rect(r.left(), r.top(), r.right(), r.bottom(), 6)}
    got = {(z, int(r.url().path().split('/')[-2]), int(r.url().path().split('/')[-1][:-4]))
           for r in f.sent for z in [int(r.url().path().split('/')[-3])]}
    assert got == want and len(want) > 4
    assert len(f.sent) == len(want)
    render(view)
    assert len(f.sent) == 2 * len(want)         # nothing arrived, nothing in flight: asked again


def sent_keys(f):
    out = set()
    for r in f.sent:
        z, x, y = r.url().path().split('/')[-3:]
        out.add((int(z), int(x), int(y[:-4])))
    return out


def test_a_tile_the_ring_evicted_is_fetched_again_not_left_a_hole(view):
    """The first version kept a record of every tile ever asked for and
    never asked twice - so a tile the ring evicted stayed blank for the
    session. Every paint asks now, and the fetcher decides."""
    f = RecordingFetcher(ring=4)
    item = TileLayer(LAYER, f)
    view.scene().addItem(item)
    view.set_zoom(6)
    view.center_on_lonlat(87.5, 20.5)
    render(view)
    keys = sorted(sent_keys(f))
    for z, x, y in keys:
        f.put('t', z, x, y, solid('red'))        # more than the ring holds: the first are evicted
    still_held = [k for k in keys if f.pixmap(LAYER, *k) is not None]
    assert 0 < len(still_held) < len(keys)
    f.sent.clear()
    render(view)
    asked_again = sent_keys(f)
    assert asked_again == set(keys) - set(still_held)


def test_across_the_antimeridian_both_sides_are_asked_for_by_wrapped_x(view):
    f = RecordingFetcher()
    item = TileLayer(LAYER, f)
    view.scene().addItem(item)
    view.set_zoom(4)
    view.center_on_lonlat(179.9, 0)
    render(view)
    xs = {x for (z, x, y) in sent_keys(f)}
    assert xs <= set(range(16))                # every x is a real tile
    assert 15 in xs and 0 in xs                # the last column and the first


def test_a_layer_draws_its_top_zoom_scaled_above_its_ceiling(view):
    f = RecordingFetcher()
    item = TileLayer(LAYER, f)                 # max_zoom 10
    view.scene().addItem(item)
    view.set_zoom(13)
    view.center_on_lonlat(87.5, 20.5)
    render(view)
    zs = {z for (z, x, y) in sent_keys(f)}
    assert zs == {10}


def test_tiles_that_arrive_are_drawn_with_the_layers_opacity(view, qtbot):
    f = RecordingFetcher()
    item = TileLayer(LAYER, f)
    view.scene().addItem(item)
    view.set_zoom(6)
    view.center_on_lonlat(87.5, 20.5)
    render(view)
    for z, x, y in sent_keys(f):
        f.put('t', z, x, y, solid('#ff0000'))
    img = render(view)
    c = img.pixelColor(400, 300)
    assert (c.red(), c.green(), c.blue()) == (255, 0, 0)
    item.setOpacity(0.5)
    c = render(view).pixelColor(400, 300)
    # half red over the view's own background, which is not white
    bg = view.backgroundBrush().color()
    assert abs(c.red() - (255 + bg.red()) / 2) <= 2
    assert abs(c.green() - bg.green() / 2) <= 2
    item.setVisible(False)
    c = render(view).pixelColor(400, 300)
    assert (c.red(), c.green(), c.blue()) != (255, 0, 0)


def test_zoom_for_clamps_to_the_layers_range():
    item = TileLayer(Layer(name='n', url='x{z}{x}{y}', min_zoom=3, max_zoom=8), RecordingFetcher())
    assert item.zoom_for(m.scale_for_zoom(0)) == 3
    assert item.zoom_for(m.scale_for_zoom(5)) == 5
    assert item.zoom_for(m.scale_for_zoom(19)) == 8


# ------------------------------------------------------------- the panel

def test_the_window_has_a_layer_per_config_and_the_panel_drives_them(qtbot):
    w = MainWindow(load_layers(), cache_dir=None)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert [i.layer.name for i in w.tile_items] == ['ogf-carto', 'ttopo', 'cyclogf']
    assert [i.isVisible() for i in w.tile_items] == [True, False, False]
    assert [i.zValue() for i in w.tile_items] == [0, 1, 2]
    row = w.panel.rows[1]
    assert not row.slider.isEnabled()
    row.check.setChecked(True)
    assert w.tile_items[1].isVisible() and row.slider.isEnabled()
    row.slider.setValue(40)
    assert abs(w.tile_items[1].opacity() - 0.4) < 1e-9
    assert row.pct.text().strip() == '40%'
    row.check.setChecked(False)
    assert not w.tile_items[1].isVisible()
