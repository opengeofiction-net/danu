"""What the surface cannot say, drawn over it - R20 and R21.

The envelope: the outline of the ground the contours describe, one rectangle
per square as ``drawn_mask`` computes it, from the GeoJSON the build wrote.
Beyond it the fill does not reach, and the surface stops.

The unreached ground: where the first pass found no answer, in three shades of
warning - nothing within reach, a pair too flat to trust, a single level in
sight - on the surface's own Mercator grid. R20 calls this the most useful
thing the editor can tell a mapper: here is ground your contours do not
describe.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from ..surface import shade
from . import mercator as m


def envelope_rings(geojson: Path) -> list[list[tuple[float, float]]]:
    """The polygons' outer rings as (lon, lat) lists, from drawn.geojson."""
    data = json.loads(Path(geojson).read_text(encoding='utf-8'))
    rings = []
    for feat in data.get('features', []):
        geom = feat.get('geometry') or {}
        if geom.get('type') == 'Polygon' and geom.get('coordinates'):
            rings.append([(float(x), float(y)) for x, y in geom['coordinates'][0]])
        elif geom.get('type') == 'MultiPolygon':
            for poly in geom.get('coordinates', []):
                if poly:
                    rings.append([(float(x), float(y)) for x, y in poly[0]])
    return rings


class EnvelopeItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setZValue(96)          # over the surface and the unreached ground, under the squares
        self._path = QPainterPath()
        self._rect = QRectF()
        self.rings: list[list[tuple[float, float]]] = []

    def set_rings(self, rings: list[list[tuple[float, float]]]):
        self.prepareGeometryChange()
        self.rings = rings
        path = QPainterPath()
        for ring in rings:
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in ring]
            if len(pts) < 2:
                continue
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
        self._path = path
        self._rect = path.controlPointRect()
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._path.isEmpty():
            return
        pen = QPen(QColor(120, 30, 160, 220), 1.6, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)


class UnreachedLayer(QGraphicsItem):
    """The first-pass classes as a pixmap on the surface's rectangle."""

    def __init__(self):
        super().__init__()
        self.setZValue(55)          # just over the surface
        self._pixmap: QPixmap | None = None
        self._rect = QRectF()
        self.reading: dict | None = None
        self.one_level = False
        self.stale = False
        self._shaded: shade.Shaded | None = None

    def set_stale(self, stale: bool = True):
        """The surface has moved under this overlay without the classes being
        recomputed - which is what a preview does: it reruns the first pass for
        a box and brings back the DEM and the hillshade, not the classes. Left
        alone the overlay goes on calling ground unreached that the contour
        just drawn reaches, in red, over the surface that shows it does.

        Faded rather than hidden, because what it says is still true of most of
        the raster and hiding it would be a bigger lie than dimming it."""
        if stale != self.stale:
            self.stale = stale
            self.update()

    def set_shaded(self, shaded: shade.Shaded | None):
        self.stale = False
        self.prepareGeometryChange()
        self._shaded = shaded
        if shaded is None or shaded.classes is None:
            self._pixmap, self._rect, self.reading = None, QRectF(), None
            self.update()
            return
        l, t, r, b = shaded.scene_rect
        self._rect = QRectF(l, t, r - l, b - t)
        self._repaint_classes()
        self.reading = shaded.reading
        self.update()

    def set_one_level(self, on: bool):
        self.one_level = bool(on)
        if self._shaded is not None and self._shaded.classes is not None:
            self._repaint_classes()
            self.update()

    def _repaint_classes(self):
        shaded = self._shaded
        rgba = np.ascontiguousarray(shade.unreached_rgba(shaded.classes, self.one_level))
        rows, cols = rgba.shape[:2]
        img = QImage(rgba.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(img.copy())

    def summary(self) -> str:
        """Area and fraction, as the validation table asks - the build's own
        reading, measured on the lat/lon grid, not recounted on the Mercator
        pixels this is drawn on."""
        r = self.reading
        if not r or not r.get('inside_cells'):
            return 'no first-pass reading'
        km2 = r['km2']['1'] + r['km2']['2']
        pct = r['percent']['1'] + r['percent']['2']
        return (f'{km2:,.1f} km² the contours do not describe, {pct:.1f}% of the drawn area: '
                f'{r["cells"]["1"]:,} cells nothing in reach, {r["cells"]["2"]:,} too flat to trust; '
                f'and {r["cells"]["3"]:,} seeing one level, mostly the contours\' own edges')

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap is None:
            return
        # faded while the surface under it has moved and these classes have
        # not been recomputed - see set_stale
        was = painter.opacity()
        if self.stale:
            painter.setOpacity(was * 0.35)
        painter.drawPixmap(self._rect, self._pixmap, QRectF(self._pixmap.rect()))
        painter.setOpacity(was)
