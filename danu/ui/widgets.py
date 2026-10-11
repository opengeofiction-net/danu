"""Small pieces the panels share (H6c): a unit beside a field rather than in
it, an "i" that holds an explanation until it is hovered over, and the
clipboard.

The unit was a suffix inside the field - "375.0 m" - which the review found
in the way: a mapper selecting the value to type over it took the unit too,
and the fields elsewhere carry none. It is a small "m" to the right now.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle, QWidget


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
    panel until it is asked for."""
    label = QLabel()
    size = label.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize)
    icon = label.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
    label.setPixmap(icon.pixmap(QSize(size, size)))
    label.setToolTip(text)
    return label


def copy(text: str) -> None:
    QGuiApplication.clipboard().setText(text)
