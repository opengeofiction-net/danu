"""The layer panel: which tile layer is under the map, and how opaque.

One layer at a time - the review found two backdrops at once is never what a
mapper wants, and one opacity is what they reach for - so the rows are radio
buttons and there is a single slider. Presentation only: it turns the
TileLayer items' visibility and opacity; nothing here knows what a tile is.

The panel is the only thing that changes a layer's visibility or opacity after
start-up. If something else ever writes them - a session file, a shortcut -
the rows need telling, and that is a signal on the item rather than a poll here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QDockWidget, QGridLayout, QLabel, QRadioButton, QSlider, QWidget

from .tiles import TileLayer


class LayersPanel(QDockWidget):
    def __init__(self, items: list[TileLayer], parent=None):
        super().__init__('Layers', parent)
        self.setObjectName('layers')
        self.items = items
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(1, 1)
        self.group = QButtonGroup(self)
        self.radios: list[QRadioButton] = []
        # the first visible layer in config order is the active one; the rest go
        active = next((i for i, item in enumerate(items) if item.isVisible()), 0 if items else None)
        for i, item in enumerate(items):
            radio = QRadioButton(item.layer.title or item.layer.name)
            self.group.addButton(radio, i)
            grid.addWidget(radio, i, 0, 1, 2)
            self.radios.append(radio)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.pct = QLabel('')
        row = len(items)
        grid.addWidget(QLabel('Opacity'), row, 0)
        grid.addWidget(self.slider, row, 1)
        grid.addWidget(self.pct, row, 2)
        grid.setRowStretch(row + 1, 1)
        self.setWidget(body)
        self.group.idToggled.connect(self._toggled)
        self.slider.valueChanged.connect(self._slid)
        if active is not None:
            self.slider.setValue(round(items[active].opacity() * 100))
            self.radios[active].setChecked(True)
            self._toggled(active, True)
        self._slid(self.slider.value())

    @property
    def active(self) -> TileLayer | None:
        i = self.group.checkedId()
        return self.items[i] if i >= 0 else None

    def _toggled(self, i: int, on: bool):
        if not on:
            return
        for j, item in enumerate(self.items):
            item.setVisible(j == i)
        self.items[i].setOpacity(self.slider.value() / 100.0)

    def _slid(self, value: int):
        self.pct.setText(f'{value:3d}%')
        if self.active is not None:
            self.active.setOpacity(value / 100.0)
