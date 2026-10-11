"""Small pieces the panels share (H6c): a unit beside a field rather than in
it, an "i" that holds an explanation until it is hovered over, and the
clipboard.

The unit was a suffix inside the field - "375.0 m" - which the review found
in the way: a mapper selecting the value to type over it took the unit too,
and the fields elsewhere carry none. It is a small "m" to the right now.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


def unit(field: QWidget, text: str = 'm') -> QWidget:
    """``field`` with ``text`` small to its right."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(field, 1)
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.85)
    label.setFont(font)
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    row.addWidget(label)
    box.unit = label
    return box


def info(text: str) -> QLabel:
    """An "i" whose tooltip is ``text`` - an explanation kept out of the
    panel until it is asked for. Drawn flat in the text colour, as the map's
    icons are: the style's own information icon is a blue disc, and stood
    out from everything round it."""
    label = QLabel()
    label.setPixmap(_info_pixmap(label.palette().color(QPalette.ColorRole.WindowText)))
    label.setToolTip(text)
    return label


def _info_pixmap(colour: QColor, size: int = 16) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(colour, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8, 8), 6.6, 6.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(colour)
    p.drawEllipse(QPointF(8, 4.9), 1.0, 1.0)
    p.drawRect(QRectF(7.2, 6.8, 1.6, 5.2))
    p.end()
    return pm


def copy(text: str) -> None:
    QGuiApplication.clipboard().setText(text)
