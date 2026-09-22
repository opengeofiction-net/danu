"""Zoom and the tools, on the map.

The keys and the menus have them, but a hand on a map looks for them on the
map - the phase 3 review asked for zoom there, and for the mode beside it.
Four buttons down the top left of the view: in, out, select, draw.

A child of the **view**, not of its viewport, for the reason
``danu.ui.legend`` records: a scroll takes a viewport's children with it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from . import mercator as m

MARGIN = 8
WIDE, HIGH = 46, 28        # wide enough for 'Draw', which 30 square clipped to 'D...w'


class MapControls(QWidget):
    def __init__(self, view, editor=None):
        super().__init__(view)
        self.view, self.editor = view, editor
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        self.zoom_in = self._button('+', 'Zoom in', column)
        self.zoom_out = self._button('−', 'Zoom out', column)
        column.addSpacing(8)
        self.select = self._button('Sel', 'Select (Q)', column, checkable=True)
        self.draw = self._button('Draw', 'Draw a contour (A)', column, checkable=True)
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

    def _button(self, text: str, tip: str, column: QVBoxLayout, checkable: bool = False) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFixedSize(QSize(WIDE, HIGH))
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
