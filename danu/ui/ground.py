"""Whose ground, shaded (#190, N4): over each square of the working set that
is shared with a neighbour, their ground within 10 km of the mapper's in
amber - in reach - and beyond it in red - not to be drawn. The mapper's own
ground and the sea are left clear. Drawn from the territories the editor
already holds (``danu.core.ground``), for the signed-in mapper -
administrators too, who may upload anything but are shown whose it is -
and nothing for nobody signed in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from . import mercator as m

if TYPE_CHECKING:                   # GDAL's, which the editor's import must not need
    from ..core.ground import Ground

NEAR = QColor(240, 160, 0, 70)
FAR = QColor(200, 30, 30, 80)


def _path(polygons) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for rings in polygons:
        for ring in rings:
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in ring]
            if len(pts) < 3:
                continue
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
    return path


class GroundItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setZValue(95)          # over the surface, under the envelope, the squares and contours
        self._near = QPainterPath()
        self._far = QPainterPath()
        self._rect = QRectF()

    def set_ground(self, grounds: list[Ground]) -> None:
        self.prepareGeometryChange()
        self._near, self._far = QPainterPath(), QPainterPath()
        self._near.setFillRule(Qt.FillRule.OddEvenFill)
        self._far.setFillRule(Qt.FillRule.OddEvenFill)
        for g in grounds:
            self._near.addPath(_path(g.near))
            self._far.addPath(_path(g.far))
        self._rect = self._near.controlPointRect().united(self._far.controlPointRect())
        self.update()

    def shaded(self) -> bool:
        return not (self._near.isEmpty() and self._far.isEmpty())

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        for path, colour in ((self._near, NEAR), (self._far, FAR)):
            if not path.isEmpty():
                painter.fillPath(path, QBrush(colour))
