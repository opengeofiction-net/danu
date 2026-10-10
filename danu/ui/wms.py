"""Danu's surface as a WMS on the loopback - H5, so the ground JOSM shows
under the water and the peaks being fixed there is the ground Danu built.

``http://127.0.0.1:<port>/wms``: GetCapabilities, and GetMap in PNG for one
layer, ``danu``, in EPSG:3857 - what JOSM's Mercator asks for - and
EPSG:4326. JOSM's remote control adds it with ``/imagery`` (``J`` with shift,
or the Edit menu); the port is ``josm/wms_port`` in the INI, 8115 unless said,
so a layer JOSM keeps from one day to the next finds Danu again.

**What a tile shows is what the map shows**: the surface the layer draws,
coloured by its style and over the colour scale its last whole recolour
worked out, so a tile matches the map beside it - preview patches included,
since they are in the surface the layer holds. The layer keeps no array of
its colours (0.88 GB at 1 arcsecond), so each request colours its own: the
cells under the requested pixels, nearest, taken a stride apart where a pixel
spans many, and composed - work in proportion to the pixels asked for, not to
the surface. Slope is worked out on that window of cells, so it is the slope
of the ground and not of the resampling.

Served from a thread of its own, reading the layer's surface and style as
they stand; nothing on the UI thread waits for JOSM. Each answer carries an
ETag of what the layer has drawn - its revision, which every new surface,
recolour and preview patch counts up - and the style, and ``no-cache``, so
JOSM asks again and is told 304 until the map has changed.

Loopback only: the server binds 127.0.0.1, and nothing is served to anything
else.
"""

from __future__ import annotations

import hashlib
import http.server
import math
import struct
import threading
import zlib
from urllib.parse import parse_qs, urlparse

import numpy as np

from ..surface import difference as surface_difference
from ..surface import shade

PORT = 8115
LAYER = 'danu'
R = 6378137.0
MAX_PIXELS = 4096 * 4096                     # a GetMap larger than this is refused


# ------------------------------------------------------------------ render

def _pixel_xy(bbox, width, height, srs: str):
    """Each output pixel's centre in EPSG:3857 metres, as (x, y) arrays."""
    x0, y0, x1, y1 = bbox
    u = x0 + (np.arange(width) + 0.5) * (x1 - x0) / width
    v = y1 - (np.arange(height) + 0.5) * (y1 - y0) / height
    if srs == 'EPSG:4326':
        lon, lat = u, np.clip(v, -85.05112878, 85.05112878)
        return R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return u, v


def render(shaded, style, stretch, bbox, width: int, height: int, srs: str = 'EPSG:3857') -> np.ndarray:
    """RGBA uint8 (height, width, 4) for a GetMap: the surface under the
    pixels, coloured as the layer colours it; clear where there is none."""
    from .surface import RAMPS
    out = np.zeros((height, width, 4), np.uint8)
    if shaded is None:
        return out
    gt = shaded.geotransform
    rows, cols = shaded.dem.shape
    xs, ys = _pixel_xy(bbox, width, height, srs)
    c = np.floor((xs - gt[0]) / gt[1]).astype(np.int64)
    r = np.floor((ys - gt[3]) / gt[5]).astype(np.int64)
    cin, rin = (c >= 0) & (c < cols), (r >= 0) & (r < rows)
    if not cin.any() or not rin.any():
        return out
    # the window of cells the pixels fall in, a stride apart where a pixel
    # spans several - the stride the pixels' own spacing gives, so the work is
    # the pixels', not the surface's
    c0, c1 = int(c[cin].min()), int(c[cin].max()) + 1
    r0, r1 = int(r[rin].min()), int(r[rin].max()) + 1
    k = max(1, int(min((c1 - c0) / max(cin.sum(), 1), (r1 - r0) / max(rin.sum(), 1))))
    # a cell of halo either side for slope's gradient
    a0, a1 = max(r0 - k, 0), min(r1 + k, rows)
    b0, b1 = max(c0 - k, 0), min(c1 + k, cols)
    sl = (slice(a0, a1, k), slice(b0, b1, k))
    wgt = (gt[0] + b0 * gt[1], gt[1] * k, 0.0, gt[3] + a0 * gt[5], 0.0, gt[5] * k)
    window = shade.Shaded(dem=np.ascontiguousarray(shaded.dem[sl]),
                          shade=np.ascontiguousarray(shaded.shade[sl]), geotransform=wgt,
                          metres=shaded.metres * k)
    if style.mode == 'difference':
        diff = shaded.difference[sl] if shaded.difference is not None else None
        rgba = surface_difference.rgba(diff, shaded.difference_span, window.dem.shape)
    else:
        ramp = None if style.mode == 'hillshade' else RAMPS[style.ramp]()
        rgba = shade.compose(window, ramp, style.scaling, style.mode, style.shade_strength,
                             stretch=stretch if ramp is not None else None)
    wr = np.clip((r - a0) // k, 0, rgba.shape[0] - 1)
    wc = np.clip((c - b0) // k, 0, rgba.shape[1] - 1)
    inside = rin[:, None] & cin[None, :]
    out[inside] = rgba[wr[:, None], wc[None, :]][inside]
    return out


def png(rgba: np.ndarray) -> bytes:
    """RGBA as a PNG, by zlib - no Qt on the server's thread."""
    h, w = rgba.shape[:2]
    raw = np.zeros((h, w * 4 + 1), np.uint8)
    raw[:, 1:] = rgba.reshape(h, w * 4)            # filter byte 0 on every row

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw.tobytes(), 6)) + chunk(b'IEND', b''))


# ------------------------------------------------------------- capabilities

def capabilities(base: str, shaded) -> str:
    if shaded is not None:
        left, top, right, bottom = shaded.geotransform[0], shaded.geotransform[3], None, None
        rows, cols = shaded.dem.shape
        right = left + cols * shaded.geotransform[1]
        bottom = top + rows * shaded.geotransform[5]
        w, e = math.degrees(left / R), math.degrees(right / R)
        s = math.degrees(2 * math.atan(math.exp(bottom / R)) - math.pi / 2)
        n = math.degrees(2 * math.atan(math.exp(top / R)) - math.pi / 2)
    else:
        w, s, e, n = -180.0, -85.0, 180.0, 85.0
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<WMT_MS_Capabilities version='1.1.1'>
  <Service><Name>OGC:WMS</Name><Title>Danu surface</Title></Service>
  <Capability>
    <Request>
      <GetCapabilities><Format>application/vnd.ogc.wms_xml</Format>
        <DCPType><HTTP><Get><OnlineResource xlink:href='{base}' xmlns:xlink='http://www.w3.org/1999/xlink'/></Get></HTTP></DCPType>
      </GetCapabilities>
      <GetMap><Format>image/png</Format>
        <DCPType><HTTP><Get><OnlineResource xlink:href='{base}' xmlns:xlink='http://www.w3.org/1999/xlink'/></Get></HTTP></DCPType>
      </GetMap>
    </Request>
    <Exception><Format>application/vnd.ogc.se_xml</Format></Exception>
    <Layer>
      <Title>Danu</Title>
      <SRS>EPSG:3857</SRS><SRS>EPSG:4326</SRS>
      <Layer queryable='0' opaque='0'>
        <Name>{LAYER}</Name><Title>Danu surface</Title>
        <SRS>EPSG:3857</SRS><SRS>EPSG:4326</SRS>
        <LatLonBoundingBox minx='{w:.6f}' miny='{s:.6f}' maxx='{e:.6f}' maxy='{n:.6f}'/>
      </Layer>
    </Layer>
  </Capability>
</WMT_MS_Capabilities>
"""


def _exception(text: str) -> bytes:
    return (f"<?xml version='1.0' encoding='UTF-8'?>\n<ServiceExceptionReport version='1.1.1'>"
            f"<ServiceException>{text}</ServiceException></ServiceExceptionReport>\n").encode()


# ------------------------------------------------------------------ serve

def getmap_url(base: str) -> str:
    """The GetMap template JOSM is given, its placeholders JOSM's own."""
    return (f'{base}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS={LAYER}&STYLES=&FORMAT=image/png'
            '&TRANSPARENT=TRUE&SRS={proj}&WIDTH={width}&HEIGHT={height}&BBOX={bbox}')


class SurfaceServer:
    """The WMS, over whatever ``snapshot()`` answers - (shaded, style,
    stretch, revision) as the layer has them."""

    def __init__(self, snapshot, port: int = PORT):
        self.snapshot = snapshot
        self.requests = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                outer.requests += 1
                code, headers, body = outer.answer(self.path, self.headers.get('If-None-Match'))
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        try:
            self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
        except OSError:
            # the port is taken - another Danu, as a rule: one of its own
            self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base = f'http://127.0.0.1:{self.port}/wms'
        self._thread = threading.Thread(target=self.httpd.serve_forever, name='danu-wms', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def answer(self, path: str, etag_asked: str | None = None):
        """(status, headers, body) for a request path - the server's whole
        logic, apart from the socket."""
        u = urlparse(path)
        if u.path.rstrip('/') != '/wms':
            return 404, {'Content-Type': 'text/plain'}, b'not here: /wms\n'
        q = {k.upper(): v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        shaded, style, stretch, revision = self.snapshot()
        req = q.get('REQUEST', '').lower()
        if req == 'getcapabilities':
            return 200, {'Content-Type': 'application/vnd.ogc.wms_xml'}, capabilities(self.base, shaded).encode()
        if req != 'getmap':
            return 400, {'Content-Type': 'application/vnd.ogc.se_xml'}, _exception('REQUEST is GetCapabilities or GetMap')
        try:
            width, height = int(q['WIDTH']), int(q['HEIGHT'])
            bbox = [float(v) for v in q['BBOX'].split(',')]
            srs = (q.get('SRS') or q.get('CRS') or 'EPSG:3857').upper()
        except (KeyError, ValueError):
            return 400, {'Content-Type': 'application/vnd.ogc.se_xml'}, _exception('WIDTH, HEIGHT and BBOX are needed')
        if srs in ('EPSG:900913', 'EPSG:3785', 'EPSG:102100'):
            srs = 'EPSG:3857'
        if srs not in ('EPSG:3857', 'EPSG:4326'):
            return 400, {'Content-Type': 'application/vnd.ogc.se_xml'}, _exception(f'{srs} is not served: EPSG:3857 or EPSG:4326')
        if len(bbox) != 4 or width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            return 400, {'Content-Type': 'application/vnd.ogc.se_xml'}, _exception('a BBOX of four and a size within 4096 square')
        if srs == 'EPSG:4326' and q.get('VERSION') == '1.3.0':
            bbox = [bbox[1], bbox[0], bbox[3], bbox[2]]          # 1.3.0's 4326 is lat, lon
        etag = self.etag(revision, style, stretch)
        headers = {'ETag': etag, 'Cache-Control': 'no-cache'}
        if etag_asked == etag:
            return 304, headers, b''
        rgba = render(shaded, style, stretch, bbox, width, height, srs)
        return 200, {**headers, 'Content-Type': 'image/png'}, png(rgba)

    @staticmethod
    def etag(revision, style, stretch) -> str:
        """What is drawn and how it is coloured: the layer's revision, which
        a new surface, a recolour and a preview's patch each count up, and the
        style and scale."""
        key = repr((revision, style, stretch))
        return '"' + hashlib.sha1(key.encode()).hexdigest()[:16] + '"'
