"""The surface as a WMS (H5): what a GetMap shows is what the map shows, and
JOSM is asked to add it as a layer.

The surface is the fixture's Tenmetre ground, rising north from 10 m at
-23.9 to 50 at -23.5, 500 m cells - as the measure tests have it.
"""

import http.server
import math
import threading
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import numpy as np
import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QImage

from danu.ui import wms
from danu.ui.surface import _composed_now
from tests.ui.test_measure import rising_north

R = 6378137.0


def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


@pytest.fixture
def w(window):
    window.surface.set_runner(None)
    window.surface.set_shaded(rising_north())
    window.surface.set_preview(False)
    return window


def snap(w):
    return w.surface.shaded, w.surface.style, w.surface.stretch


def served_snap(w):
    return (*snap(w), w.surface.revision)


def cell_rgba(w, lon, lat):
    """The map's own colour for the cell under a point."""
    s = w.surface.shaded
    rgba, _ = _composed_now(s, w.surface.style)
    x, y = merc(lon, lat)
    gt = s.geotransform
    return rgba[int((y - gt[3]) / gt[5]), int((x - gt[0]) / gt[1])]


def test_a_tile_is_the_maps_colours_and_clear_off_the_surface(w):
    x0, y0 = merc(126.4, -23.8)
    x1, y1 = merc(126.6, -23.6)
    img = wms.render(*snap(w), (x0, y0, x1, y1), 64, 64)
    assert img.shape == (64, 64, 4) and (img[..., 3] > 0).all()
    # the middle pixel is the middle cell's colour, as the layer composed it
    assert tuple(img[32, 32]) == tuple(cell_rgba(w, 126.5 + 0.2 / 128, -23.7 - 0.0014))
    off = wms.render(*snap(w), (*merc(130.0, -23.8), *merc(130.2, -23.6)), 16, 16)
    assert (off == 0).all(), 'no surface there: clear'


def test_a_tile_over_the_whole_set_strides_and_keeps_the_colours(w):
    """A pixel spanning many cells takes one: the colour still the map's for
    a cell under it, north darker or lighter as the map has it."""
    x0, y0 = merc(126.0, -24.3)
    x1, y1 = merc(127.0, -23.0)
    img = wms.render(*snap(w), (x0, y0, x1, y1), 8, 8)
    s = w.surface.shaded
    rgba, _ = _composed_now(s, w.surface.style)
    for i in range(8):
        y = y1 - (i + 0.5) * (y1 - y0) / 8
        r = int((y - s.geotransform[3]) / s.geotransform[5])
        if 0 <= r < rgba.shape[0]:
            near = rgba[max(r - 12, 0):r + 12, 100]
            assert any((img[i, 4, :3] == c[:3]).all() for c in near), i


def test_slope_is_the_grounds_not_the_resamplings(w):
    """Asked at a hundred pixels a cell, the slope is the cells' gentle
    one - not zero between steps and steep at them."""
    w.surface_panel.mode.setCurrentText('slope')
    x0, y0 = merc(126.50, -23.705)
    x1, y1 = merc(126.51, -23.695)
    img = wms.render(*snap(w), (x0, y0, x1, y1), 200, 200)
    colours = {tuple(c) for c in img.reshape(-1, 4)}
    assert len(colours) <= 3, 'one slope, the ground\'s, with no steps in it'
    assert tuple(img[100, 100]) == tuple(cell_rgba(w, 126.505, -23.70))


def test_in_4326_the_same_ground(w):
    a = wms.render(*snap(w), (126.4, -23.8, 126.6, -23.6), 32, 32, srs='EPSG:4326')
    assert tuple(a[16, 16]) == tuple(cell_rgba(w, 126.5 + 0.2 / 64, -23.7 - 0.2 / 64))


def test_the_png_reads_back(w):
    rgba = wms.render(*snap(w), (*merc(126.8, -23.8), *merc(127.2, -23.6)), 20, 10)   # half off: alpha both ways
    assert (rgba[..., 3] == 0).any() and (rgba[..., 3] == 255).any()
    img = QImage.fromData(wms.png(rgba), 'PNG').convertToFormat(QImage.Format.Format_RGBA8888)
    assert img.width() == 20 and img.height() == 10
    back = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(10, 20, 4)
    assert (back == rgba).all()


# ---------------------------------------------------------------- server

@pytest.fixture
def served(w):
    s = wms.SurfaceServer(lambda: served_snap(w), port=0)
    yield s
    s.stop()


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_capabilities_name_the_layer_over_the_surface(served):
    code, headers, body = get(served.base + '?SERVICE=WMS&REQUEST=GetCapabilities')
    assert code == 200
    root = ElementTree.fromstring(body)
    layer = root.find('.//Layer/Layer')
    assert layer.findtext('Name') == 'danu'
    assert {e.text for e in layer.findall('SRS')} == {'EPSG:3857', 'EPSG:4326'}
    box = layer.find('LatLonBoundingBox')
    assert float(box.get('minx')) == pytest.approx(126.0, abs=1e-6) and float(box.get('maxy')) == pytest.approx(-23.0, abs=1e-6)


def test_getmap_as_josm_asks_it_and_asked_again_unchanged_is_304(served, w):
    url = wms.getmap_url(served.base).format(
        proj='EPSG:3857', width=64, height=64, bbox=','.join(f'{v:.3f}' for v in (*merc(126.4, -23.8), *merc(126.6, -23.6))))
    code, headers, body = get(url)
    assert code == 200 and headers['Content-Type'] == 'image/png' and headers['Cache-Control'] == 'no-cache'
    img = QImage.fromData(body, 'PNG')
    assert img.width() == 64 and not img.isNull()
    code, _, _ = get(url, {'If-None-Match': headers['ETag']})
    assert code == 304
    w.surface_panel.mode.setCurrentText('relief')
    code, again, _ = get(url, {'If-None-Match': headers['ETag']})
    assert code == 200 and again['ETag'] != headers['ETag'], 'another style, another tag'
    w.surface.shaded.dem[100:110, 100:110] += 5                    # a preview's patch
    assert w.surface.recolour_box(100, 100, 10, 10)
    code, third, _ = get(url, {'If-None-Match': again['ETag']})
    assert code == 200 and third['ETag'] != again['ETag'], 'a preview, drawn, is a new tag'


def test_what_is_not_served_is_said(served):
    assert get(served.base.replace('/wms', '/other'))[0] == 404
    code, _, body = get(served.base + '?REQUEST=GetFeatureInfo')
    assert code == 400 and b'ServiceException' in body
    code, _, body = get(served.base + '?REQUEST=GetMap&WIDTH=10&HEIGHT=10&BBOX=0,0,1,1&SRS=EPSG:27700')
    assert code == 400 and b'EPSG:27700' in body
    assert get(served.base + '?REQUEST=GetMap&WIDTH=100000&HEIGHT=100000&BBOX=0,0,1,1')[0] == 400


def test_on_the_loopback_only(served):
    assert served.httpd.server_address[0] == '127.0.0.1'


# ------------------------------------------------------------------ JOSM

@pytest.fixture
def josm(window):
    """A JOSM's remote control on the loopback - not the mapper's."""
    asked = []

    class Remote(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            asked.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK\r\n')
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Remote)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    window.josm.base = f'http://127.0.0.1:{httpd.server_address[1]}'
    window.settings.q.setValue('josm/wms_port', 0)
    yield asked
    httpd.shutdown()


def test_shift_j_serves_the_surface_and_asks_josm_to_add_it(w, josm, qtbot):
    a = w.edit_actions['view.josm_surface']
    assert a.shortcut().toString() == 'Shift+J'
    a.trigger()
    qtbot.waitUntil(lambda: bool(josm), timeout=3000)
    u = urlparse(josm[0])
    q = parse_qs(u.query)
    assert u.path == '/imagery' and q['type'] == ['wms'] and q['title'] == ['Danu surface']
    layer = q['url'][0]
    assert layer.startswith(w.wms.base) and '{bbox}' in layer and '{proj}' in layer
    qtbot.waitUntil(lambda: 'JOSM: the surface, served at' in w.statusBar().currentMessage(), timeout=3000)
    # and the URL JOSM was given serves the map
    code, _, body = get(layer.format(proj='EPSG:3857', width=8, height=8,
                                     bbox=','.join(map(str, (*merc(126.4, -23.8), *merc(126.6, -23.6))))))
    assert code == 200 and body.startswith(b'\x89PNG')


def test_with_no_surface_there_is_nothing_to_give(window, josm):
    assert window.show_surface_in_josm() is None
    assert 'build a surface first' in window.statusBar().currentMessage() and window.wms is None


def test_closing_stops_the_server(w, josm, qtbot):
    w.show_surface_in_josm()
    base = w.wms.base
    w.close()
    assert w.wms is None
    with pytest.raises(OSError):
        urllib.request.urlopen(base + '?REQUEST=GetCapabilities', timeout=2)


def test_1_3_0_in_4326_is_latitude_first(served):
    a = served.answer('/wms?REQUEST=GetMap&VERSION=1.1.1&SRS=EPSG:4326&WIDTH=8&HEIGHT=8&BBOX=126.4,-23.8,126.6,-23.6')
    b = served.answer('/wms?REQUEST=GetMap&VERSION=1.3.0&CRS=EPSG:4326&WIDTH=8&HEIGHT=8&BBOX=-23.8,126.4,-23.6,126.6')
    assert a[0] == b[0] == 200 and a[2] == b[2]


def per_cell(w, r0, r1, c0, c1):
    """A GetMap with a pixel a cell over rows r0..r1 and columns c0..c1, and
    the map's own colours for those cells."""
    s = w.surface.shaded
    gt = s.geotransform
    bbox = (gt[0] + c0 * gt[1], gt[3] + r1 * gt[5], gt[0] + c1 * gt[1], gt[3] + r0 * gt[5])
    img = wms.render(*snap(w), bbox, c1 - c0, r1 - r0)
    rgba, _ = _composed_now(s, w.surface.style)
    return img, rgba[r0:r1, c0:c1]


def test_coloured_over_the_whole_surfaces_scale_not_the_tiles(w):
    w.surface_panel.mode.setCurrentText('relief')
    img, want = per_cell(w, 120, 130, 100, 110)
    assert (img == want).all(), 'a tile stretched over its own few metres would be another colour'


def test_slope_at_a_tiles_edge_has_the_cells_beyond_it(w):
    """Ground in ripples a few cells long: the slope of a tile's first and
    last rows takes in the rows beyond it, as the map's does - a gradient
    taken one-sided at the edge would be another."""
    s = w.surface.shaded
    rows = np.arange(s.dem.shape[0], dtype=np.float32)[:, None]
    s.dem[:] = 200 + 100 * np.sin(rows * 1.3)
    w.surface_panel.mode.setCurrentText('slope')
    img, want = per_cell(w, 100, 110, 50, 60)
    assert (img == want).all()


def test_slope_over_the_whole_set_is_the_slope_not_the_stride(w):
    w.surface_panel.mode.setCurrentText('slope')
    x0, y0 = merc(126.0, -24.0)
    x1, y1 = merc(127.0, -23.0)
    img = wms.render(*snap(w), (x0, y0, x1, y1), 16, 16)
    assert tuple(img[8, 8]) == tuple(cell_rgba(w, 126.5, -23.5)), 'one slope, at any stride'


def test_half_off_the_surface_the_off_half_is_clear(w):
    x0, y0 = merc(126.8, -23.8)
    x1, y1 = merc(127.2, -23.6)                      # the surface ends at 127
    img = wms.render(*snap(w), (x0, y0, x1, y1), 40, 20)
    assert (img[:, :15, 3] == 255).all() and (img[:, 25:] == 0).all()


def test_the_difference_as_the_map_shows_it(w):
    s = w.surface.shaded
    s.difference = np.zeros(s.dem.shape, np.float32)
    s.difference[:, 115:] = 12.0
    s.difference_span = 20.0
    w.surface_panel.mode.setCurrentText('difference')
    img, want = per_cell(w, 120, 130, 110, 120)
    assert (img == want).all() and img[0, 9, 3] == 255 and img[0, 0, 3] == 0
