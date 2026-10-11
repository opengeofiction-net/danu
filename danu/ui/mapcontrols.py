"""Zoom and the tools, on the map.

The keys and the menus have them, but a hand on a map looks for them on the
map - the phase 3 review asked for zoom there, and for the mode beside it.
Down the top left of the view: in, out and the layers; select, draw, spot
height, measure; undo and redo; delete, split and unglue; magnify; and the
two imports.

H6b's review found the tool in use hard to tell from the rest, so a checked
button is filled with the palette's highlight and its icon drawn in the
highlight's text colour; and the edits a hand reaches for next to the tools
are buttons too, greyed while the selection gives them nothing to do.

A child of the **view**, not of its viewport, for the reason
``danu.ui.legend`` records: a scroll takes a viewport's children with it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QMenu, QToolButton, QWidget, QWidgetAction

from . import mercator as m
from .settings import DEFAULT_KEYS

MARGIN = 8
SIZE = 30                  # square: the tools are drawn, not named
SPACING = 2                # between the buttons of a group
GAP = 10                   # and between the groups
ICON = 18


# a checked button - the tool in use, the loupe on - filled with the
# highlight; the rest flat on the button colour, so the one stands out
STYLE = """
QToolButton { background: palette(button); color: palette(button-text);
              border: 1px solid palette(mid); border-radius: 3px; }
QToolButton:hover { border-color: palette(highlight); }
QToolButton:checked { background: palette(highlight); border-color: palette(highlight); }
QToolButton:disabled { color: palette(mid); }
QToolButton::menu-indicator { image: none; }
"""


def _pixmap(paint, colour: QColor, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint(p, colour)
    p.end()
    return pm


def _icon(paint, colour: QColor, size: int = ICON, on: QColor | None = None) -> QIcon:
    """An icon drawn here rather than shipped: small marks need no files,
    and taking the colour from the palette keeps them legible whether the
    desktop is light or dark. ``on`` is the colour it is drawn in while its
    button is checked, over the highlight."""
    icon = QIcon(_pixmap(paint, colour, size))
    if on is not None:
        icon.addPixmap(_pixmap(paint, on, size), QIcon.Mode.Normal, QIcon.State.On)
    return icon


def _arrow_round(p: QPainter, colour: QColor, mirror: bool = False):
    """An arrow turning back over itself - undo, or mirrored, redo."""
    if mirror:
        p.translate(p.device().width(), 0)
        p.scale(-1, 1)
    pen = QPen(colour, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(5.0, 7.5))
    path.lineTo(QPointF(10.5, 7.5))
    path.cubicTo(QPointF(17.0, 7.5), QPointF(17.0, 15.5), QPointF(10.5, 15.5))
    path.lineTo(QPointF(6.5, 15.5))
    p.drawPath(path)
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon([QPointF(1.5, 7.5), QPointF(6.0, 3.6), QPointF(6.0, 11.4)])


def _undo(p: QPainter, colour: QColor):
    _arrow_round(p, colour)


def _redo(p: QPainter, colour: QColor):
    _arrow_round(p, colour, mirror=True)


def _delete(p: QPainter, colour: QColor):
    """A bin - delete what is selected."""
    pen = QPen(colour, 1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(3.0, 4.5), QPointF(15.0, 4.5))
    p.drawLine(QPointF(7.0, 4.5), QPointF(7.5, 2.5))
    p.drawLine(QPointF(7.5, 2.5), QPointF(10.5, 2.5))
    p.drawLine(QPointF(10.5, 2.5), QPointF(11.0, 4.5))
    p.drawPolygon([QPointF(4.5, 6.0), QPointF(13.5, 6.0), QPointF(12.6, 16.0), QPointF(5.4, 16.0)])
    for x in (7.3, 9.0, 10.7):
        p.drawLine(QPointF(x, 8.0), QPointF(x, 14.0))


def _split(p: QPainter, colour: QColor):
    """Scissors - cut the contour at the node. A broken line with its two
    new nodes was drawn first, and read as a crosshair."""
    pen = QPen(colour, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(4.8, 13.8), 2.6, 2.6)
    p.drawEllipse(QPointF(13.2, 13.8), 2.6, 2.6)
    p.drawLine(QPointF(6.4, 11.8), QPointF(13.0, 1.8))
    p.drawLine(QPointF(11.6, 11.8), QPointF(5.0, 1.8))
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(9.0, 7.9), 1.1, 1.1)


def _unglue(p: QPainter, colour: QColor):
    """Two contours that met at a node, drawn back from it, each to a node
    of its own."""
    pen = QPen(colour, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(1.5, 3.0), QPointF(6.5, 9.0), QPointF(1.5, 15.0)])
    p.drawPolyline([QPointF(16.5, 3.0), QPointF(11.5, 9.0), QPointF(16.5, 15.0)])
    p.setBrush(colour)
    p.setPen(Qt.PenStyle.NoPen)
    for q in (QPointF(6.5, 9.0), QPointF(11.5, 9.0)):
        p.drawRect(QRectF(q.x() - 1.7, q.y() - 1.7, 3.4, 3.4))


def _layers(p: QPainter, colour: QColor):
    """Two sheets, one over the other - the tile layers."""
    pen = QPen(colour, 1.4)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline([QPointF(3.0, 11.5), QPointF(9.0, 15.0), QPointF(15.0, 11.5)])
    p.setBrush(colour)
    p.drawPolygon([QPointF(9.0, 3.0), QPointF(15.0, 6.8), QPointF(9.0, 10.6), QPointF(3.0, 6.8)])


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


def _ruler(p: QPainter, colour: QColor):
    """A ruler laid across - measure, H3b."""
    pen = QPen(colour, 1.4)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.save()
    p.translate(9, 9)
    p.rotate(-35)
    p.drawRect(QRectF(-8, -2.6, 16, 5.2))
    for i, x in enumerate(range(-6, 7, 2)):
        p.drawLine(QPointF(x, -2.6), QPointF(x, -0.6 if i % 2 else 0.6))
    p.restore()


def _magnifier(p: QPainter, colour: QColor):
    """A lens and its handle - magnify, H3d."""
    pen = QPen(colour, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(7.5, 7.5), 5.0, 5.0)
    p.setPen(QPen(colour, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(11.3, 11.3), QPointF(15.8, 15.8))


class _Column:
    """The buttons in their groups, as they are made. MapControls.place lays
    them out, GAP between the groups."""

    def __init__(self):
        self.groups: list[list[QToolButton]] = [[]]

    def addWidget(self, b: QToolButton) -> None:
        self.groups[-1].append(b)

    def end_group(self) -> None:
        self.groups.append([])


class MapControls(QWidget):
    """The tools, the loupe that goes over any of them, and the imports.

    ``importWater`` is a signal rather than a call on the editor: the import
    reaches the network and lands on the window's history across the whole
    working set, which is the window's business and not the canvas's.
    """

    importWater = Signal()
    importHeights = Signal()

    def __init__(self, view, editor=None, settings=None, layers=None):
        super().__init__(view)
        self.setStyleSheet(STYLE)
        self.view, self.editor = view, editor
        # the keys are the mapper's to rebind, so the tooltips are built from
        # the binding rather than written out: a rebound action used to be
        # named by the key it no longer had
        self.keys = settings.key if settings is not None else DEFAULT_KEYS.get
        self._tips: list[tuple[str, str]] = []        # each keyed tip, what and action
        self._tipped: list[QToolButton] = []          # and the button it is on
        column = self.column = _Column()

        ink = self.palette().color(QPalette.ColorRole.ButtonText)
        lit = self.palette().color(QPalette.ColorRole.HighlightedText)
        self.zoom_in = self._button('+', 'Zoom in', column)
        self.zoom_out = self._button('−', 'Zoom out', column)
        # the layers: a popup holding the chooser, which the panel was
        self.layers = None
        if layers is not None:
            self.layers = self._button('', 'Layers - the map under the contours, and how opaque', column,
                                       icon=_icon(_layers, ink))
            menu = QMenu(self.layers)
            held = QWidgetAction(menu)
            held.setDefaultWidget(layers)
            menu.addAction(held)
            self.layers.setMenu(menu)
            self.layers.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        column.end_group()
        self.select = self._button('', self._tip('Select - pick a contour or a node',
                                                 'tool.select'), column,
                                   checkable=True, icon=_icon(_pointer, ink, on=lit))
        self.draw = self._button('', self._tip('Draw a contour', 'tool.draw'), column,
                                 checkable=True, icon=_icon(_polyline, ink, on=lit))
        self.spot = self._button('', self._tip('Place a spot height at the active elevation',
                                               'tool.spot'), column,
                                 checkable=True, icon=_icon(_spot, ink, on=lit))
        self.measure = self._button('', self._tip('Measure - a line, and the ground along it',
                                                  'tool.measure'), column,
                                    checkable=True, icon=_icon(_ruler, ink, on=lit))
        self.modes = QButtonGroup(self)
        self.modes.addButton(self.select)
        self.modes.addButton(self.draw)
        self.modes.addButton(self.spot)
        self.modes.addButton(self.measure)
        self.select.setChecked(True)
        column.end_group()
        # the edits, by the window's actions - see bind - and greyed by the
        # history and the selection
        self.undo = self._button('', self._tip('Undo', 'edit.undo'), column, icon=_icon(_undo, ink))
        self.redo = self._button('', self._tip('Redo', 'edit.redo'), column, icon=_icon(_redo, ink))
        column.end_group()
        self.delete = self._button('', self._tip('Delete what is selected', 'edit.delete'), column,
                                   icon=_icon(_delete, ink))
        self.split = self._button('', self._tip('Split the contour at the node selected', 'edit.split'),
                                  column, icon=_icon(_split, ink))
        self.unglue = self._button('', self._tip('Unglue the node selected from the other contours',
                                                 'edit.unglue'), column, icon=_icon(_unglue, ink))
        self.edits = {'edit.undo': self.undo, 'edit.redo': self.redo, 'edit.delete': self.delete,
                      'edit.split': self.split, 'edit.unglue': self.unglue}
        column.end_group()
        # not a tool: the loupe is over whichever tool is in use
        self.magnify = self._button('', self._tip('Magnify - a loupe at the cursor; shift and the wheel '
                                                  'for more or less', 'view.magnify'), column,
                                    checkable=True, icon=_icon(_magnifier, ink, on=lit))
        column.end_group()
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
            self.measure.clicked.connect(lambda: editor.set_tool('measure'))
            editor.toolChanged.connect(self.tool_changed)
            editor.selectionChanged.connect(self.refresh_edits)
            editor.edited.connect(self.refresh_edits)
        self.refresh_edits()
        # the viewport's resize, held by name: see danu.ui.legend
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.place()
        self.raise_()
        self._zoom_changed(view.zoom)

    def bind(self, actions: dict) -> None:
        """The edit buttons pressed as the window's actions are triggered -
        so the usage log has them by name, as it has a key or the menu."""
        for name, b in self.edits.items():
            b.clicked.connect(actions[name].trigger)

    def refresh_edits(self) -> None:
        """Undo and redo by the history; delete, split and unglue by whether
        the selection gives them something to do."""
        ed = self.editor
        if ed is None:
            for b in self.edits.values():
                b.setEnabled(False)
            return
        self.undo.setEnabled(ed.history.can_undo)
        self.redo.setEnabled(ed.history.can_redo)
        for name in ('edit.delete', 'edit.split', 'edit.unglue'):
            self.edits[name].setEnabled(ed.applies(name))

    def _tip(self, what: str, action: str) -> str:
        key = self.keys(action)
        self._tips.append((what, action))
        return f'{what} ({key})' if key else what

    def retip(self) -> None:
        """The tooltips again, a key rebound in the preferences (H6e)."""
        tips, self._tips = self._tips, []
        for b, (what, action) in zip(self._tipped, tips, strict=True):
            b.setToolTip(self._tip(what, action))

    def _button(self, text: str, tip: str, column: _Column, checkable: bool = False,
                icon: QIcon | None = None) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        if len(self._tipped) < len(self._tips):       # this tip was a keyed one
            self._tipped.append(b)
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
        """Down the left of the map, a group at a time; a group that would
        run off the bottom starts a column beside it - a short window holds
        the buttons in two."""
        vp = self._viewport.geometry()
        room = max(vp.height() - 2 * MARGIN, SIZE)
        x = y = 0
        for group in self.column.groups:
            tall = len(group) * (SIZE + SPACING) - SPACING
            if y and y + tall > room:
                x, y = x + SIZE + SPACING, 0
            for b in group:
                b.move(x, y)
                y += SIZE + SPACING
            y += GAP - SPACING
        self.setFixedSize(x + SIZE, max(b.geometry().bottom() + 1 for g in self.column.groups for b in g))
        self.move(vp.left() + MARGIN, vp.top() + MARGIN)

    # ------------------------------------------------------------- state
    def _zoom_changed(self, zoom: int):
        self.zoom_in.setEnabled(zoom < m.MAX_ZOOM)
        self.zoom_out.setEnabled(zoom > 0)

    def tool_changed(self, name: str):
        self.select.setChecked(name == 'select')
        self.draw.setChecked(name == 'draw')
        self.spot.setChecked(name == 'spot')
        self.measure.setChecked(name == 'measure')
