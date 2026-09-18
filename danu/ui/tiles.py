"""Tile layers: the map under the contours.

One TileFetcher for the application - a QNetworkAccessManager with Qt's own
disk cache under ~/.cache/danu/tiles, an in-memory ring of decoded pixmaps,
and one request in flight per tile at most. One TileLayer per configured
layer, a QGraphicsItem that asks the fetcher for what its exposed rectangle
needs and draws whatever has arrived.

The user agent is Danu's own name. The OGF servers' bot rules punish browser
strings that are not browsers - stale or rounded Chrome versions, impossible
Windows builds - and they serve an honest client without complaint; probed
both ways before this was written. A desktop application pretending to be a
browser is exactly the thing those rules exist to catch.

Zoom is taken from the painter, not stored: the view's scale says which zoom
is being looked at, and a layer with a lower ceiling draws its top tiles
scaled up rather than nothing. Tiles east or west of the world are asked for
by their wrapped x and drawn where the view has them, so a view across the
antimeridian shows both sides.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QUrl, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QGraphicsItem

from .. import __version__
from . import mercator as m
from .config import Layer
from .mapview import visible_rect

USER_AGENT = f'Danu/{__version__} (+https://github.com/opengeofiction-net/danu)'
DISK_CACHE_BYTES = 512 * 1024 * 1024
# decoded pixmaps kept in memory; a 1920x1200 view is about 50 tiles, so this
# is a dozen screens of panning before anything is decoded twice
PIXMAP_RING = 600

Key = tuple[str, int, int, int]     # layer name, z, x (wrapped), y


class TileFetcher(QObject):
    """Fetches and remembers tiles. ``ready`` fires once per tile that arrives,
    with the key it was asked for; layers redraw on it."""

    ready = Signal(str, int, int, int)

    def __init__(self, cache_dir: Path | None = None, parent: QObject | None = None,
                 ring: int = PIXMAP_RING):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        if cache_dir is not None:
            cache = QNetworkDiskCache(self)
            cache.setCacheDirectory(str(cache_dir))
            cache.setMaximumCacheSize(DISK_CACHE_BYTES)
            self.nam.setCache(cache)
        self._ring = ring
        self._pixmaps: OrderedDict[Key, QPixmap] = OrderedDict()
        self._inflight: dict[Key, QNetworkReply] = {}
        # a tile that failed is not asked for again this session: a server
        # that said 404 for it will say so again, and asking on every repaint
        # is how a client gets itself rate limited
        self.failed: set[Key] = set()

    # ----------------------------------------------------------- lookup
    def pixmap(self, layer: Layer, z: int, x: int, y: int) -> QPixmap | None:
        key = (layer.name, z, x, y)
        pm = self._pixmaps.get(key)
        if pm is not None:
            self._pixmaps.move_to_end(key)
        return pm

    def put(self, layer_name: str, z: int, x: int, y: int, pixmap: QPixmap):
        key = (layer_name, z, x, y)
        self._pixmaps[key] = pixmap
        self._pixmaps.move_to_end(key)
        while len(self._pixmaps) > self._ring:
            self._pixmaps.popitem(last=False)
        self.ready.emit(*key)

    # ---------------------------------------------------------- fetching
    def request_for(self, layer: Layer, z: int, x: int, y: int) -> QNetworkRequest:
        req = QNetworkRequest(QUrl(layer.tile_url(z, x, y)))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        # the disk cache decides by the server's Cache-Control, which the OGF
        # servers set to about a week; prefer it, and go to the network when
        # it has nothing or the entry has expired
        req.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                         QNetworkRequest.CacheLoadControl.PreferCache)
        return req

    def request(self, layer: Layer, z: int, x: int, y: int):
        key = (layer.name, z, x, y)
        if key in self._pixmaps or key in self._inflight or key in self.failed:
            return
        reply = self._send(self.request_for(layer, z, x, y))
        if reply is None:
            return
        self._inflight[key] = reply
        reply.finished.connect(lambda key=key, reply=reply: self._finished(key, reply))

    def _send(self, req: QNetworkRequest) -> QNetworkReply | None:
        """The one place a request leaves; a test replaces it."""
        return self.nam.get(req)

    def _finished(self, key: Key, reply: QNetworkReply):
        self._inflight.pop(key, None)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.add(key)
                return
            pm = QPixmap()
            if not pm.loadFromData(reply.readAll()):
                self.failed.add(key)
                return
            self.put(*key, pm)
        finally:
            reply.deleteLater()

    @property
    def inflight(self) -> int:
        return len(self._inflight)


class TileLayer(QGraphicsItem):
    """One configured layer, drawn from whatever the fetcher has."""

    def __init__(self, layer: Layer, fetcher: TileFetcher):
        super().__init__()
        self.layer = layer
        self.fetcher = fetcher
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setOpacity(layer.opacity)
        self.setVisible(layer.visible)
        fetcher.ready.connect(self._tile_ready)
        # the requests this item made, by wrapped key, so a redraw only asks
        # for what the last paint did not already ask for
        self.requested: set[Key] = set()

    def boundingRect(self) -> QRectF:
        # the world and one repeat each side, matching the scene's margin;
        # nothing above or below it, because there are no tiles there
        return QRectF(-m.WORLD, 0, 3 * m.WORLD, m.WORLD)

    def zoom_for(self, scale: float) -> int:
        """The tile zoom for a view scale, within this layer's range."""
        z = round(m.zoom_for_scale(scale))
        return max(self.layer.min_zoom, min(self.layer.max_zoom, z))

    def paint(self, painter: QPainter, option, widget=None):
        rect = visible_rect(painter, option, self.boundingRect())
        if rect.isEmpty():
            return
        z = self.zoom_for(painter.worldTransform().m11())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for _, x, y in m.tiles_in_rect(rect.left(), rect.top(), rect.right(), rect.bottom(), z):
            wx = m.wrap_x(x, z)
            pm = self.fetcher.pixmap(self.layer, z, wx, y)
            if pm is None:
                key = (self.layer.name, z, wx, y)
                if key not in self.requested:
                    self.requested.add(key)
                    self.fetcher.request(self.layer, z, wx, y)
                continue
            left, top, right, bottom = m.tile_rect(z, x, y)
            painter.drawPixmap(QRectF(left, top, right - left, bottom - top), pm, QRectF(pm.rect()))

    def _tile_ready(self, name: str, z: int, x: int, y: int):
        if name == self.layer.name:
            # the tile may be drawn at more than one x across the seam, so
            # the whole item rather than one rect; Qt clips to the viewport
            self.update()
