"""Zoom and the tools, on the map.

The keys and the menus have them, but a hand on a map looks for them on the
map - the phase 3 review asked for zoom there, and for the mode beside it.
Four buttons down the top left of the view: in, out, select, draw.

A child of the **view**, not of its viewport, for the reason
``danu.ui.legend`` records: a scroll takes a viewport's children with it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from . import mercator as m

MARGIN = 8
SIZE = 30                  # square: the tools are drawn, not named
ICON = 18


def _icon(paint, colour: QColor, size: int = ICON) -> QIcon:
    """An icon drawn here rather than shipped: two small marks need no files,
    and taking the colour from the palette keeps them legible whether the
    desktop is light or dark."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint(p, colour)
    p.end()
    return QIcon(pm)


def _pointer(p: QPainter, colour: QColor):
    """The arrow every desktop uses for 'pick something'."""
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon([QPointF(4, 2), QPointF(4, 15), QPointF(7.6, 11.4), QPointF(10, 16.5),
                   QPointF(12, 15.6), QPointF(9.7, 10.8), QPointF(14.5, 10.2)])


def _polyline(p: QPainter, colour: QColor):
    """A line through its nodes, which is what drawing a contour is."""
    pen = QPen(colour, 1.6)
    p.setPen(pen)
    pts = [QPointF(3, 13.5), QPointF(7, 6.5), QPointF(11.5, 11.5), QPointF(15.5, 4)]
    p.drawPolyline(pts)
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    for q in pts:
        p.drawRect(QRectF(q.x() - 1.6, q.y() - 1.6, 3.2, 3.2))


class MapControls(QWidget):
    def __init__(self, view, editor=None):
        super().__init__(view)
        self.view, self.editor = view, editor
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        ink = self.palette().color(QPalette.ColorRole.ButtonText)
        self.zoom_in = self._button('+', 'Zoom in', column)
        self.zoom_out = self._button('−', 'Zoom out', column)
        column.addSpacing(8)
        self.select = self._button('', 'Select - pick a contour or a node (Q)', column,
                                   checkable=True, icon=_icon(_pointer, ink))
        self.draw = self._button('', 'Draw a contour (A)', column,
                                 checkable=True, icon=_icon(_polyline, ink))
        self.modes = QButtonGroup(self)
        self.modes.addButton(self.select)
        self.modes.addButton(self.draw)
        self.select.setChecked(True)

        self.zoom_in.clicked.connect(lambda: view.set_zoom(view.zoom + 1))
        self.zoom_out.clicked.connect(lambda: view.set_zoom(view.zoom - 1))
        view.zoomChanged.connect(self._zoom_changed)
        if editor is not None:
            self.select.clicked.connect(lambda: editor.set_tool('select'))
            self.draw.clicked.connect(lambda: editor.set_tool('draw'))
            editor.toolChanged.connect(self.tool_changed)
        # the viewport's resize, held by name: see danu.ui.legend
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.place()
        self.raise_()
        self._zoom_changed(view.zoom)

    def _button(self, text: str, tip: str, column: QVBoxLayout, checkable: bool = False,
                icon: QIcon | None = None) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        if icon is not None:
            b.setIcon(icon)
            b.setIconSize(QSize(ICON, ICON))
        b.setCheckable(checkable)
        b.setFixedSize(QSize(SIZE, SIZE))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # the map keeps the keys
        column.addWidget(b)
        return b

    # ------------------------------------------------------------ layout
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._viewport and event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def place(self):
        vp = self._viewport.geometry()
        self.adjustSize()
        self.move(vp.left() + MARGIN, vp.top() + MARGIN)

    # ------------------------------------------------------------- state
    def _zoom_changed(self, zoom: int):
        self.zoom_in.setEnabled(zoom < m.MAX_ZOOM)
        self.zoom_out.setEnabled(zoom > 0)

    def tool_changed(self, name: str):
        self.select.setChecked(name == 'select')
        self.draw.setChecked(name == 'draw')
