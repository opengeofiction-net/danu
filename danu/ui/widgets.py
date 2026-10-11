"""Small pieces the panels share (H6c): a unit beside a field rather than in
it, an "i" that holds an explanation until it is hovered over, and a button
that copies.

The unit was a suffix inside the field - "375.0 m" - which the review found
in the way: a mapper selecting the value to type over it took the unit too,
and the fields elsewhere carry none. It is a small "(m)" to the right now.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QStyle, QToolButton, QWidget


def unit(field: QWidget, text: str = '(m)') -> QWidget:
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
    label.setCursor(Qt.CursorShape.WhatsThisCursor)
    return label


def _copy_icon(colour: QColor, greyed: QColor) -> QIcon:
    """Two sheets, one over the other: copy - and the same in ``greyed`` for
    a button with nothing to copy, which Qt's own greying left as dark as
    the rest."""
    icon = QIcon(_copy_pixmap(colour))
    icon.addPixmap(_copy_pixmap(greyed), QIcon.Mode.Disabled)
    return icon


def _copy_pixmap(colour: QColor, size: int = 14) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(colour, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(1.5, 10.0), QPointF(1.5, 1.5), QPointF(9.5, 1.5)])      # the one behind
    p.drawRoundedRect(QRectF(4.5, 4.0, 8, 9), 1.2, 1.2)
    p.drawLine(QPointF(6.5, 7.0), QPointF(10.5, 7.0))
    p.drawLine(QPointF(6.5, 9.5), QPointF(10.5, 9.5))
    p.end()
    return pm


class CopyButton(QToolButton):
    """A small button that puts text on the clipboard - one text, or a menu
    of the forms it can take. ``set_texts`` with none greys it."""

    def __init__(self, tip: str, parent=None):
        super().__init__(parent)
        pal = self.palette()
        self.setIcon(_copy_icon(pal.color(QPalette.ColorRole.ButtonText), pal.color(QPalette.ColorRole.Mid)))
        self.setAutoRaise(True)
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.texts: list[str] = []
        self.clicked.connect(self._clicked)
        self.set_texts([])

    def set_texts(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.setEnabled(bool(self.texts))
        if len(self.texts) > 1:
            menu = QMenu(self)
            for t in self.texts:
                menu.addAction(t, lambda t=t: copy(t))
            self.setMenu(menu)
            self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        else:
            self.setMenu(None)
            self.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)

    def _clicked(self) -> None:
        if len(self.texts) == 1:
            copy(self.texts[0])


def copy(text: str) -> None:
    QGuiApplication.clipboard().setText(text)
