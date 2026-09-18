"""The map canvas: one QGraphicsView over the whole world in Web Mercator.

The scene never changes size or position; a zoom is a view scale and a pan is
a scroll. Integer zooms only for now, matching the tiles, with the mouse wheel
stepping between them about the cursor. Fractional zoom can come when there is
something to want it for.

The graticule is the only thing drawn here. It is not decoration: degree lines
are the squares' edges, and a viewer with nothing else loaded still shows a
mapper which degree they are looking at.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from . import mercator as m


def visible_rect(painter: QPainter, option, bounding: QRectF) -> QRectF:
    """What this paint can actually show: the painter's device, mapped back
    into the scene, intersected with the exposed rect and the item's bounds.

    option.exposedRect is clipped to the exposed region only in a real
    paintEvent. Under QGraphicsView.render() - a screenshot, a test - it is
    the whole boundingRect, and an item that trusted it would draw, or
    request tiles for, the entire world. The device rect is the truth in
    both cases.

    Everything here is in item coordinates: inside paint() the painter's
    world transform is the item's device transform, so the device rect
    mapped back through it lands in the same space as exposedRect and the
    bounding rect, whatever the item's position or transform."""
    dev = painter.device()
    device_rect = QRectF(0, 0, dev.width(), dev.height())
    inv, ok = painter.worldTransform().inverted()
    if not ok:
        return QRectF()
    return inv.mapRect(device_rect).intersected(option.exposedRect).intersected(bounding)


class Graticule(QGraphicsItem):
    """Lines of longitude and latitude at a spacing chosen for the current
    scale, so they neither crowd at world view nor vanish when zoomed in.
    Whole degrees are always among them once a degree is wide enough to see,
    because those are the square boundaries."""

    STEPS = (30.0, 10.0, 5.0, 1.0)
    MIN_PX = 48.0

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setZValue(1000)
        self._pen_minor = QPen(QColor(0, 0, 0, 40))
        self._pen_minor.setCosmetic(True)
        self._pen_degree = QPen(QColor(0, 0, 0, 90))
        self._pen_degree.setCosmetic(True)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, m.WORLD, m.WORLD)

    @classmethod
    def step_for(cls, scale: float) -> float:
        """Degrees between lines: the finest of STEPS that stays MIN_PX apart
        at the equator for this view scale."""
        px_per_degree = m.WORLD / 360.0 * scale
        # STEPS runs coarse to fine; the finest that still keeps its distance
        fits = [s for s in cls.STEPS if s * px_per_degree >= cls.MIN_PX]
        return fits[-1] if fits else cls.STEPS[0]

    def paint(self, painter: QPainter, option, widget=None):
        scale = painter.worldTransform().m11()
        step = self.step_for(scale)
        rect = visible_rect(painter, option, self.boundingRect())
        if rect.isEmpty():
            return
        lon0, lat1 = m.scene_to_lonlat(rect.left(), rect.top())
        lon1, lat0 = m.scene_to_lonlat(rect.right(), rect.bottom())
        lon_a = math.floor(lon0 / step) * step
        lat_a = math.floor(max(lat0, -m.MAX_LAT) / step) * step
        lon = lon_a
        while lon <= lon1:
            x, _ = m.lonlat_to_scene(lon, 0)
            painter.setPen(self._pen_degree if step == 1.0 or lon % 10 == 0 else self._pen_minor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            lon += step
        lat = lat_a
        while lat <= min(lat1, m.MAX_LAT):
            _, y = m.lonlat_to_scene(0, lat)
            painter.setPen(self._pen_degree if step == 1.0 or lat % 10 == 0 else self._pen_minor)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            lat += step


class MapView(QGraphicsView):
    zoomChanged = Signal(int)
    cursorMoved = Signal(float, float)      # lon, lat

    def __init__(self, parent=None):
        super().__init__(parent)
        # a world of margin on every side. Without it centerOn clamps at the
        # world's edge, and a zoom-out anchored near the antimeridian or a pole
        # then lands hundreds of pixels from where it was asked - the residual
        # correction below cannot survive the scrollbar recalculation the clamp
        # causes. With it nothing clamps until a whole world past the edge,
        # and a view straddling the antimeridian has room to draw both sides
        self._scene = QGraphicsScene(-m.WORLD, -m.WORLD, 3 * m.WORLD, 3 * m.WORLD, self)
        self.setScene(self._scene)
        self._scene.addItem(Graticule())
        self._zoom = 2
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # anchoring is done by hand in zoom_about, not by AnchorUnderMouse:
        # that reads the real cursor through QCursor::pos(), which is not the
        # event's position offscreen or under a synthetic event, and a zoom
        # that lands somewhere other than where it was asked for is not
        # something to leave to the platform
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor(235, 235, 235))
        self._apply_zoom()

    # ------------------------------------------------------------- zoom
    @property
    def zoom(self) -> int:
        return self._zoom

    def set_zoom(self, zoom: int):
        zoom = max(0, min(m.MAX_ZOOM, int(zoom)))
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self._apply_zoom()
        self.zoomChanged.emit(zoom)

    def _apply_zoom(self):
        s = m.scale_for_zoom(self._zoom)
        self.resetTransform()
        self.scale(s, s)

    def zoom_about(self, zoom: int, view_pos: QPointF):
        """Change zoom keeping the scene point under view_pos where it is."""
        anchor = self.mapToScene(view_pos.toPoint())
        before = self._zoom
        self.set_zoom(zoom)
        if self._zoom == before:
            return
        moved = self.mapToScene(view_pos.toPoint()) - anchor
        centre = self.mapToScene(self.viewport().rect().center())
        self.centerOn(centre - moved)
        # centerOn scrolls in whole pixels, which leaves up to a pixel of
        # drift per step and it compounds; the remainder goes into the view
        # transform, which is not so limited. Measured: exactly zero after
        residual = self.mapToScene(view_pos.toPoint()) - anchor
        self.translate(residual.x(), residual.y())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self.zoom_about(self._zoom + (1 if delta > 0 else -1), event.position())
        event.accept()

    # --------------------------------------------------------- position
    def center_lonlat(self) -> tuple[float, float]:
        c = self.mapToScene(self.viewport().rect().center())
        return m.scene_to_lonlat(c.x(), c.y())

    def center_on_lonlat(self, lon: float, lat: float):
        x, y = m.lonlat_to_scene(lon, lat)
        self.centerOn(QPointF(x, y))

    def fit_bounds(self, west: float, south: float, east: float, north: float):
        """Show a lon/lat box whole: the largest integer zoom that fits, then
        centred on it."""
        x0, y0 = m.lonlat_to_scene(west, north)
        x1, y1 = m.lonlat_to_scene(east, south)
        vp = self.viewport().rect()
        self.set_zoom(m.zoom_to_fit(vp.width(), vp.height(), x0, y0, x1, y1))
        self.centerOn(QPointF((x0 + x1) / 2, (y0 + y1) / 2))

    def visible_scene_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        lon, lat = m.scene_to_lonlat(p.x(), p.y())
        self.cursorMoved.emit(lon, lat)
        super().mouseMoveEvent(event)
