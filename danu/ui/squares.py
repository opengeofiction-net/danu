"""The working set's squares, drawn as squares.

An outline round each degree in the set, the centre one heavier, and the
squares nobody has drawn hatched, so the grid is always the full grid and a
gap in it is visible as a gap rather than as nothing.

The outlines are in the wiki's colours for a square (``danu.core.topo_style``,
drawn as ``danu.ui.topo_style``'s pens, as OpenGeofiction:Topo layer has
them): green with contours, orange a coastline only, grey blank - and an
absent square grey and hatched. The wiki's outlines, not its fills: a wash
over every square would colour the ground and the contours drawn in their
level's colour.

Names are written in each square's top-left corner while a degree has room
for them: the grid's, and under it the square's own, its file's -
``N46E028_Taxhatro.osm.xz``, Taxhatro. The zones map writes its squares' the
same way, in grey.

Pattern brushes in Qt are drawn in device pixels regardless of the view
transform, which is what makes hatching usable at every zoom.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import QGraphicsItem

from ..core.square import WorkingSet
from ..core.topo_style import SQUARE_BLANK, square_class
from . import mercator as m
from . import topo_style as style
from .mapview import visible_rect

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
        self._classes: dict[int, tuple[tuple[int, int], str]] = {}

    def set_working_set(self, ws: WorkingSet | None):
        self.prepareGeometryChange()
        self.working_set = ws
        self._classes.clear()                # ids are reused once a set's squares go
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
        hatch = QBrush(QColor(120, 120, 120, 110), Qt.BrushStyle.BDiagPattern)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        for name, sq in ws.squares.items():
            r = self.square_rect(ws, name)
            if not r.intersects(rect):
                continue
            cls = self._class(sq)
            if not sq.present:
                painter.fillRect(r, hatch)
            painter.setPen(style.pen(cls, 2.0 if name == ws.centre else 0.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            if degree_px >= NAME_MIN_PX:
                self._name(painter, r, name, sq.present, scale, degree_px, font, sq.label)

    def _class(self, sq) -> str:
        """The square's class, worked out again only when its ways or nodes
        come or go: a coastline-only square is read to the end to know it."""
        if not sq.present:
            return SQUARE_BLANK
        key = (len(sq.ways), len(sq.nodes))
        hit = self._classes.get(id(sq))
        if hit is None or hit[0] != key:
            hit = (key, square_class(sq))
            self._classes[id(sq)] = hit
        return hit[1]

    def _name(self, painter, r: QRectF, name, present: bool, scale: float, degree_px: float, font: QFont,
              label: str = ''):
        text = str(name) + ('' if present or degree_px < ABSENT_WORD_MIN_PX else '  (absent)')
        draw_name(painter, r, text, label, scale, font, QColor(40, 40, 40) if present else QColor(110, 110, 110))
        self.drawn_names += 1


def draw_name(painter, r: QRectF, text: str, label: str, scale: float, font: QFont, colour: QColor) -> None:
    """A square's grid name, and under it the name its file gives it, in
    its top-left corner, in pixels whatever the zoom - the open set's and
    the zones map's alike, clear of a zone's own name in its middle."""
    painter.save()
    # clipped to the square, so nothing is drawn outside boundingRect - which
    # is what Qt culls and repaints by - and a name never strays into the
    # neighbour it does not belong to
    painter.setClipRect(r)
    painter.translate(QPointF(r.left(), r.top()))
    painter.scale(1.0 / scale, 1.0 / scale)          # pixels, whatever the zoom
    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    small = QFont(font)
    small.setBold(False)
    small.setPointSize(max(1, font.pointSize() - 1))
    lines = [(text, font)] + ([(label, small)] if label else [])
    y = 4
    for line, f in lines:
        painter.setFont(f)
        h = painter.fontMetrics().height()
        box = QRectF(6, y, 400, h)
        painter.setPen(QColor(255, 255, 255, 230))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(box.translated(dx, dy), align, line)
        painter.setPen(colour)
        painter.drawText(box, align, line)
        y += h
    painter.restore()
