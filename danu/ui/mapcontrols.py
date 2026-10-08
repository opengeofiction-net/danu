"""Zoom and the tools, on the map.

The keys and the menus have them, but a hand on a map looks for them on the
map - the phase 3 review asked for zoom there, and for the mode beside it.
Five buttons down the top left of the view: in, out, select, draw, spot
height.

A child of the **view**, not of its viewport, for the reason
``danu.ui.legend`` records: a scroll takes a viewport's children with it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from . import mercator as m
from .settings import DEFAULT_KEYS

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


def _spot(p: QPainter, colour: QColor):
    """A triangle with a dot in it - the surveyor's mark for a measured
    height, and the one shape here that could not be read as either of the
    other two tools.

    Four were drawn and looked at before this one was kept. A dot beside two
    short rules, meaning *a point with a value written next to it*, reads as a
    dot beside an equals sign. A dot under an up arrow reads as *move up*. A
    ringed crosshair reads as *aim*. The triangle says height, and says it
    without a digit, which at eighteen pixels is the only way to say it.
    """
    p.setPen(QPen(colour, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon([QPointF(9, 4.0), QPointF(15.5, 14.5), QPointF(2.5, 14.5)])
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(9, 11.2), 1.9, 1.9)


def _water(p: QPainter, colour: QColor):
    """Two waves with an arrow coming down into them - fetch water, not draw
    it. The waves alone would read as a tool for drawing a river, which this
    is not; the arrow is what says the water comes from somewhere else."""
    pen = QPen(colour, 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for y in (11.5, 15.0):
        path = QPainterPath(QPointF(2.5, y))
        path.cubicTo(QPointF(5.2, y - 2.4), QPointF(6.8, y + 2.4), QPointF(9.0, y))
        path.cubicTo(QPointF(11.2, y - 2.4), QPointF(12.8, y + 2.4), QPointF(15.5, y))
        p.drawPath(path)
    p.drawLine(QPointF(9, 2.0), QPointF(9, 7.6))
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon([QPointF(6.4, 6.2), QPointF(11.6, 6.2), QPointF(9, 9.4)])


def _peak(p: QPainter, colour: QColor):
    """A peak with an arrow coming down onto it - fetch spot heights, as the
    water button fetches water, not place one."""
    pen = QPen(colour, 1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(2.0, 16.0), QPointF(7.0, 9.5), QPointF(9.5, 12.0), QPointF(12.5, 8.0),
                    QPointF(16.0, 16.0)])
    p.drawLine(QPointF(12.5, 1.5), QPointF(12.5, 4.6))
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon([QPointF(10.2, 3.8), QPointF(14.8, 3.8), QPointF(12.5, 6.6)])


class MapControls(QWidget):
    """The tools, and the one action that is not a tool.

    ``importWater`` is a signal rather than a call on the editor: the import
    reaches the network and lands on the window's history across the whole
    working set, which is the window's business and not the canvas's.
    """

    importWater = Signal()
    importHeights = Signal()

    def __init__(self, view, editor=None, settings=None):
        super().__init__(view)
        self.view, self.editor = view, editor
        # the keys are the mapper's to rebind, so the tooltips are built from
        # the binding rather than written out: a rebound action used to be
        # named by the key it no longer had
        self.keys = settings.key if settings is not None else DEFAULT_KEYS.get
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        ink = self.palette().color(QPalette.ColorRole.ButtonText)
        self.zoom_in = self._button('+', 'Zoom in', column)
        self.zoom_out = self._button('−', 'Zoom out', column)
        column.addSpacing(8)
        self.select = self._button('', self._tip('Select - pick a contour or a node',
                                                 'tool.select'), column,
                                   checkable=True, icon=_icon(_pointer, ink))
        self.draw = self._button('', self._tip('Draw a contour', 'tool.draw'), column,
                                 checkable=True, icon=_icon(_polyline, ink))
        self.spot = self._button('', self._tip('Place a spot height at the active elevation',
                                               'tool.spot'), column,
                                 checkable=True, icon=_icon(_spot, ink))
        self.modes = QButtonGroup(self)
        self.modes.addButton(self.select)
        self.modes.addButton(self.draw)
        self.modes.addButton(self.spot)
        self.select.setChecked(True)
        column.addSpacing(8)
        self.water = self._button(
            '', self._tip('Import water from Overpass for the working set',
                          'edit.import_water'),
            column, icon=_icon(_water, ink))
        self.water.clicked.connect(self.importWater)
        self.heights = self._button(
            '', self._tip("Import the main map's peaks and saddles as spot heights",
                          'edit.import_heights'),
            column, icon=_icon(_peak, ink))
        self.heights.clicked.connect(self.importHeights)

        self.zoom_in.clicked.connect(lambda: view.set_zoom(view.zoom + 1))
        self.zoom_out.clicked.connect(lambda: view.set_zoom(view.zoom - 1))
        view.zoomChanged.connect(self._zoom_changed)
        if editor is not None:
            self.select.clicked.connect(lambda: editor.set_tool('select'))
            self.draw.clicked.connect(lambda: editor.set_tool('draw'))
            self.spot.clicked.connect(lambda: editor.set_tool('spot'))
            editor.toolChanged.connect(self.tool_changed)
        # the viewport's resize, held by name: see danu.ui.legend
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.place()
        self.raise_()
        self._zoom_changed(view.zoom)

    def _tip(self, what: str, action: str) -> str:
        key = self.keys(action)
        return f'{what} ({key})' if key else what

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
        self.spot.setChecked(name == 'spot')
