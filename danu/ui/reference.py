"""The mapper's refused version of a square, drawn over the server's (#190,
N5b): an upload refused because somebody else's went up first leaves the
mapper's copy beside the square as ``.mine.osm.xz``, and the server's is
imported in its place. This draws the copy's ways - dashed, magenta, and
not to be edited - so the mapper can redo their changes on the server's
version where the other mapper didn't draw. It is shown whenever the open
square has such a copy, until File › Discard refused version.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core.square import Square
from . import mercator as m

INK = QColor(210, 0, 170, 200)


class ReferenceItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setZValue(105)                 # over the contours, under the squares' frames
        self._path = QPainterPath()
        self._rect = QRectF()
        self.square: Square | None = None

    def set_square(self, square: Square | None) -> None:
        self.prepareGeometryChange()
        self.square = square
        path = QPainterPath()
        if square is not None:
            for way in square.ways.values():
                pts = [square.nodes[r] for r in way.refs if r in square.nodes]
                if len(pts) < 2:
                    continue
                path.moveTo(*m.lonlat_to_scene(pts[0].lon, pts[0].lat))
                for n in pts[1:]:
                    path.lineTo(*m.lonlat_to_scene(n.lon, n.lat))
        self._path = path
        self._rect = path.controlPointRect()
        self.update()

    def shown(self) -> bool:
        return self.square is not None and self.isVisible()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._path.isEmpty():
            return
        pen = QPen(INK, 1.6, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)
