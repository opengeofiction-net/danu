"""The layer panel: one row per tile layer, on or off, and how opaque.

Presentation only. It holds the TileLayer items and turns their visibility and
opacity; nothing here knows what a tile is.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDockWidget, QGridLayout, QLabel, QSlider, QWidget

from .tiles import TileLayer


class LayerRow:
    def __init__(self, item: TileLayer, grid: QGridLayout, row: int):
        self.item = item
        self.check = QCheckBox(item.layer.title or item.layer.name)
        self.check.setChecked(item.isVisible())
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(round(item.opacity() * 100))
        self.slider.setEnabled(item.isVisible())
        self.pct = QLabel(f'{self.slider.value():3d}%')
        grid.addWidget(self.check, row, 0)
        grid.addWidget(self.slider, row, 1)
        grid.addWidget(self.pct, row, 2)
        self.check.toggled.connect(self._toggled)
        self.slider.valueChanged.connect(self._slid)

    def _toggled(self, on: bool):
        self.item.setVisible(on)
        self.slider.setEnabled(on)

    def _slid(self, value: int):
        self.item.setOpacity(value / 100.0)
        self.pct.setText(f'{value:3d}%')


class LayersPanel(QDockWidget):
    def __init__(self, items: list[TileLayer], parent=None):
        super().__init__('Layers', parent)
        self.setObjectName('layers')
        body = QWidget()
        grid = QGridLayout(body)
        grid.setColumnStretch(1, 1)
        self.rows = [LayerRow(item, grid, i) for i, item in enumerate(items)]
        grid.setRowStretch(len(items), 1)
        self.setWidget(body)
