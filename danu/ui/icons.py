"""The panels' buttons drawn, not named, with what they do in the tooltip.

The side panels were as wide as their longest button - "Grade the river
network (Shift+G)" the left column's, a row of five named buttons the
right's - and the map paid for it: on a laptop it had little more than half
the window. A button here is an icon and a tooltip, the key in the tooltip
built from the binding, as the map's tools have theirs (``mapcontrols``).

Drawn in the palette's button-text colour, like the map's, and drawn again
as the palette changes - the theme set in the preferences, or the desktop's
turned dark.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QToolButton

from .mapcontrols import ICON, _icon, _split
from .settings import DEFAULT_KEYS

Paint = Callable[[QPainter, QColor], None]


class PaintedButton(QToolButton):
    """A tool button with a drawn icon, its tooltip ``what`` and the key
    bound to ``action``, if it has one."""

    def __init__(self, paint: Paint, what: str, action: str | None = None, keys=None,
                 checkable: bool = False, parent=None):
        super().__init__(parent)
        self.paint, self.what, self.action = paint, what, action
        self.setIconSize(QSize(ICON, ICON))
        self.setCheckable(checkable)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)        # the map keeps the keys
        self.retip(keys)
        self._draw()

    def retip(self, keys=None) -> None:
        """The tooltip again, a key rebound in the preferences."""
        key = (keys or DEFAULT_KEYS.get)(self.action) if self.action else None
        self.setToolTip(f'{self.what} ({key})' if key else self.what)

    def _draw(self) -> None:
        self.setIcon(_icon(self.paint, self.palette().color(QPalette.ColorRole.ButtonText)))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._draw()


def _pen(p: QPainter, colour: QColor, width: float = 1.6) -> None:
    pen = QPen(colour, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _head(p: QPainter, colour: QColor, tip: QPointF, dx: float, dy: float) -> None:
    """An arrowhead at ``tip``, pointing along (dx, dy), a unit vector."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    nx, ny = -dy, dx
    back = QPointF(tip.x() - 4.5 * dx, tip.y() - 4.5 * dy)
    p.drawPolygon([tip, QPointF(back.x() + 3.0 * nx, back.y() + 3.0 * ny),
                   QPointF(back.x() - 3.0 * nx, back.y() - 3.0 * ny)])
    p.restore()


# ------------------------------------------------------------ the proposal
def tick(p: QPainter, colour: QColor):
    """Accept."""
    _pen(p, colour, 2.0)
    p.drawPolyline([QPointF(3.0, 9.5), QPointF(7.5, 14.0), QPointF(15.5, 4.5)])


def cross(p: QPainter, colour: QColor):
    """Drop, or cancel."""
    _pen(p, colour, 2.0)
    p.drawLine(QPointF(4.0, 4.0), QPointF(14.0, 14.0))
    p.drawLine(QPointF(14.0, 4.0), QPointF(4.0, 14.0))


# ------------------------------------------------------------ the selected
def grade(p: QPainter, colour: QColor):
    """A river stepping down: its levels read from the contours it crosses."""
    _pen(p, colour)
    p.drawPolyline([QPointF(2.0, 3.5), QPointF(6.5, 3.5), QPointF(6.5, 9.0), QPointF(11.5, 9.0),
                    QPointF(11.5, 14.5), QPointF(16.0, 14.5)])


def network(p: QPainter, colour: QColor):
    """A river and the streams that join it, graded together."""
    _pen(p, colour)
    p.drawLine(QPointF(9.0, 16.5), QPointF(9.0, 9.5))
    p.drawPolyline([QPointF(2.5, 2.0), QPointF(9.0, 9.5), QPointF(15.5, 2.0)])
    p.drawLine(QPointF(9.0, 9.5), QPointF(9.0, 3.0))
    p.drawLine(QPointF(12.3, 5.8), QPointF(16.0, 7.5))


def coastline(p: QPainter, colour: QColor):
    """The shore: land filled above a wave, the sea below."""
    path = QPainterPath(QPointF(1.0, 10.0))
    path.cubicTo(QPointF(4.0, 6.5), QPointF(6.0, 13.5), QPointF(9.0, 10.0))
    path.cubicTo(QPointF(12.0, 6.5), QPointF(14.0, 13.5), QPointF(17.0, 10.0))
    land = QPainterPath(path)
    land.lineTo(QPointF(17.0, 2.0))
    land.lineTo(QPointF(1.0, 2.0))
    land.closeSubpath()
    fill = QColor(colour)
    fill.setAlphaF(0.35)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(land)
    _pen(p, colour)
    p.drawPath(path)
    p.drawLine(QPointF(4.0, 15.5), QPointF(7.0, 15.5))
    p.drawLine(QPointF(11.0, 15.5), QPointF(14.0, 15.5))


def reverse(p: QPainter, colour: QColor):
    """Turned round: one arrow each way."""
    _pen(p, colour)
    p.drawLine(QPointF(2.0, 5.5), QPointF(12.5, 5.5))
    _head(p, colour, QPointF(16.5, 5.5), 1.0, 0.0)
    p.drawLine(QPointF(5.5, 12.5), QPointF(16.0, 12.5))
    _head(p, colour, QPointF(1.5, 12.5), -1.0, 0.0)


def flatten(p: QPainter, colour: QColor):
    """Pressed down to one level: arrows onto a flat line."""
    _pen(p, colour)
    p.drawLine(QPointF(1.5, 14.5), QPointF(16.5, 14.5))
    for x in (5.0, 13.0):
        p.drawLine(QPointF(x, 2.0), QPointF(x, 7.0))
        _head(p, colour, QPointF(x, 11.0), 0.0, 1.0)


# ------------------------------------------------------------ the zones
def reload(p: QPainter, colour: QColor):
    """Read again: an arrow coming round."""
    _pen(p, colour)
    p.drawArc(QRectF(3.0, 3.0, 12.0, 12.0), 90 * 16, 280 * 16)
    _head(p, colour, QPointF(11.5, 3.2), 1.0, 0.0)


def download(p: QPainter, colour: QColor):
    """Import: down into a tray."""
    _pen(p, colour)
    p.drawLine(QPointF(9.0, 1.5), QPointF(9.0, 8.0))
    _head(p, colour, QPointF(9.0, 12.0), 0.0, 1.0)
    p.drawPolyline([QPointF(2.5, 11.0), QPointF(2.5, 16.0), QPointF(15.5, 16.0), QPointF(15.5, 11.0)])


def new_zone(p: QPainter, colour: QColor):
    """A zone's outline, and a plus."""
    pen = QPen(colour, 1.2, Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(1.5, 1.5, 15.0, 15.0))
    _pen(p, colour, 2.0)
    p.drawLine(QPointF(9.0, 5.0), QPointF(9.0, 13.0))
    p.drawLine(QPointF(5.0, 9.0), QPointF(13.0, 9.0))


def edit_squares(p: QPainter, colour: QColor):
    """Squares, and a pencil at their corner."""
    _pen(p, colour, 1.0)
    for x, y in ((1.5, 12.0), (6.0, 12.0), (1.5, 7.5)):
        p.drawRect(QRectF(x, y, 4.5, 4.5))
    _pen(p, colour, 1.3)
    p.drawPolygon([QPointF(13.9, 3.9), QPointF(16.1, 6.1), QPointF(11.6, 10.6), QPointF(8.5, 11.5),
                   QPointF(9.4, 8.4)])


def save(p: QPainter, colour: QColor):
    """A disk."""
    _pen(p, colour, 1.4)
    p.drawPolygon([QPointF(2.5, 2.5), QPointF(13.0, 2.5), QPointF(15.5, 5.0), QPointF(15.5, 15.5),
                   QPointF(2.5, 15.5)])
    p.drawRect(QRectF(5.5, 2.5, 6.0, 4.0))
    p.drawRect(QRectF(5.0, 10.0, 8.0, 5.5))


def split(p: QPainter, colour: QColor):
    """Scissors, as the map's split."""
    _split(p, colour)


def pause(p: QPainter, colour: QColor):
    """Inactive: built, and kept off the tile servers."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawRoundedRect(QRectF(4.0, 3.0, 3.5, 12.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(10.5, 3.0, 3.5, 12.0), 1.0, 1.0)


def play(p: QPainter, colour: QColor):
    """Active again: on the tile servers."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawPolygon([QPointF(5.0, 3.0), QPointF(15.0, 9.0), QPointF(5.0, 15.0)])
