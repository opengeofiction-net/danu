"""The working set's squares, drawn as squares.

An outline round each degree in the set, the centre one heavier, and the
squares nobody has drawn hatched, so the grid is always the full grid and a
gap in it is visible as a gap rather than as nothing. Names are written in
each square while a degree is small enough on screen to need naming, and
move to the corner once it is not.

Pattern brushes in Qt are drawn in device pixels regardless of the view
transform, which is what makes hatching usable at every zoom.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core.square import WorkingSet
from . import mercator as m
from .mapview import visible_rect

NAME_CENTRED_BELOW_PX = 420.0     # a degree narrower than this gets its name in the middle
NAME_MIN_PX = 80.0                # narrower than this, no name at all: it would not fit
ABSENT_WORD_MIN_PX = 170.0        # narrower than this the hatching says it, the word would not fit


class SquaresItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        # over the contours: the outlines are a pixel wide and the hatching only
        # falls where there are no contours, while a name under a dense square's
        # contours is unreadable - seen on gobras
        self.setZValue(110)
        self.working_set: WorkingSet | None = None
        self._bounds = QRectF()
        self.drawn_names = 0

    def set_working_set(self, ws: WorkingSet | None):
        self.prepareGeometryChange()
        self.working_set = ws
        if ws is None:
            self._bounds = QRectF()
        else:
            w, s, e, n = ws.bounds
            x0, y0 = m.lonlat_to_scene(w, n)
            x1, y1 = m.lonlat_to_scene(e, s)
            self._bounds = QRectF(x0, y0, x1 - x0, y1 - y0)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def square_rect(self, ws: WorkingSet, name) -> QRectF:
        """The square's rect on the set's continuous longitude axis, so one
        across the seam sits beside its neighbours rather than a world away."""
        w, s, e, n = name.bounds
        lon = ws.unwrap(w + 0.5) - 0.5
        x0, y0 = m.lonlat_to_scene(lon, n)
        x1, y1 = m.lonlat_to_scene(lon + 1, s)
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def paint(self, painter: QPainter, option, widget=None):
        self.drawn_names = 0
        ws = self.working_set
        if ws is None:
            return
        rect = visible_rect(painter, option, self._bounds)
        if rect.isEmpty():
            return
        scale = painter.worldTransform().m11()
        degree_px = m.WORLD / 360.0 * scale
        outline = QPen(QColor(60, 60, 60, 160), 1.0)
        outline.setCosmetic(True)
        centre_pen = QPen(QColor(20, 20, 20, 220), 2.2)
        centre_pen.setCosmetic(True)
        hatch = QBrush(QColor(120, 120, 120, 110), Qt.BrushStyle.BDiagPattern)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        for name, sq in ws.squares.items():
            r = self.square_rect(ws, name)
            if not r.intersects(rect):
                continue
            if not sq.present:
                painter.fillRect(r, hatch)
            painter.setPen(centre_pen if name == ws.centre else outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            if degree_px >= NAME_MIN_PX:
                self._name(painter, r, name, sq.present, scale, degree_px, font)

    def _name(self, painter, r: QRectF, name, present: bool, scale: float, degree_px: float, font: QFont):
        text = str(name) + ('' if present or degree_px < ABSENT_WORD_MIN_PX else '  (absent)')
        painter.save()
        # clipped to the square, so nothing is drawn outside boundingRect - which
        # is what Qt culls and repaints by - and a name never strays into the
        # neighbour it does not belong to
        painter.setClipRect(r)
        if degree_px < NAME_CENTRED_BELOW_PX:
            anchor = r.center()
            align = Qt.AlignmentFlag.AlignCenter
        else:
            anchor = QPointF(r.left(), r.top())
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        painter.translate(anchor)
        painter.scale(1.0 / scale, 1.0 / scale)          # pixels, whatever the zoom
        painter.setFont(font)
        box = QRectF(-200, -20, 400, 40) if align == Qt.AlignmentFlag.AlignCenter else QRectF(6, 4, 400, 40)
        painter.setPen(QColor(255, 255, 255, 230))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(box.translated(dx, dy), align, text)
        painter.setPen(QColor(40, 40, 40) if present else QColor(110, 110, 110))
        painter.drawText(box, align, text)
        painter.restore()
        self.drawn_names += 1
