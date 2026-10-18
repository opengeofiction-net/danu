"""``danu.core.topo_style`` as Qt pens and brushes: the wiki's map of the
topo layer's zones and squares, drawn alike in the editor (#190)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen

from ..core.topo_style import STYLES


def _colour(hex_: str, opacity: float) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(float(opacity))
    return c


def pen(cls: str, extra: float = 0.0, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> QPen:
    s = STYLES[cls]
    p = QPen(_colour(s['color'], s['opacity']), float(s['weight']) + extra, style)
    p.setCosmetic(True)
    return p


def brush(cls: str) -> QBrush:
    s = STYLES[cls]
    if not s['fillOpacity']:
        return QBrush(Qt.BrushStyle.NoBrush)
    return QBrush(_colour(s['fillColor'], s['fillOpacity']))


def colour(cls: str) -> QColor:
    s = STYLES[cls]
    return _colour(s['color'], s['opacity'])
