"""Open a square: which zone, which square, how many around it.

The squares live where the mapper put their mirror of the published
``osm-squares/`` tree - a root with one directory per zone - and that root is
remembered. Zones are the directories under it that hold a square; squares
are what ``list_squares`` finds, shown by name and label.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from ..core.square import SquareName, list_squares

SIZES = (1, 3, 5)


def zones_under(root: Path) -> list[Path]:
    """Directories under root holding at least one square file."""
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            if list_squares(d):
                out.append(d)
        except OSError:
            out.append(d)          # a zone with a problem is still a zone; opening it says what
    return out


class OpenDialog(QDialog):
    def __init__(self, root: Path | None, size: int = 3, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Open a square')
        self.setMinimumWidth(520)
        self.result_: tuple[Path, SquareName, int] | None = None

        self.root_edit = QLineEdit(str(root) if root else '')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.root_edit, 1)
        row.addWidget(browse)

        self.zone = QComboBox()
        self.squares = QListWidget()
        self.squares.setMinimumHeight(220)
        self.size = QComboBox()
        for n in SIZES:
            self.size.addItem(f'{n}×{n}', n)
        self.size.setCurrentIndex(SIZES.index(size) if size in SIZES else 1)
        self.hint = QLabel('')
        self.hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow('Squares root', row)
        form.addRow('Zone', self.zone)
        form.addRow('Square', self.squares)
        form.addRow('Working set', self.size)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        self.open_button = buttons.button(QDialogButtonBox.StandardButton.Open)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.hint)
        lay.addWidget(buttons)

        self.root_edit.editingFinished.connect(self.refresh_zones)
        self.zone.currentIndexChanged.connect(self.refresh_squares)
        self.squares.itemSelectionChanged.connect(self._selection_changed)
        self.squares.itemDoubleClicked.connect(lambda _: self.accept())
        self.refresh_zones()

    # -------------------------------------------------------------- lists
    @property
    def root(self) -> Path:
        return Path(self.root_edit.text().strip()).expanduser()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, 'The osm-squares directory', str(self.root))
        if d:
            self.root_edit.setText(d)
            self.refresh_zones()

    def refresh_zones(self):
        self.zone.blockSignals(True)
        self.zone.clear()
        for d in zones_under(self.root):
            self.zone.addItem(d.name, d)
        self.zone.blockSignals(False)
        if self.zone.count() == 0:
            self.hint.setText('No zone directories with squares under that root. It should be a '
                              'mirror of the published osm-squares/ tree: one directory per zone.')
        else:
            self.hint.setText('')
        self.refresh_squares()

    def refresh_squares(self):
        self.squares.clear()
        d = self.zone.currentData()
        if d is None:
            self._selection_changed()
            return
        try:
            found = list_squares(d)
        except OSError as e:            # FileExistsError for two files one square, or unreadable
            self.hint.setText(str(e))
            self._selection_changed()
            return
        for name, path in sorted(found.items()):
            label = path.name[len(name.name):].removesuffix('.osm.xz').removesuffix('.osm').lstrip('_')
            item = QListWidgetItem(f'{name}   {label.replace("_", " ")}'.rstrip())
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.squares.addItem(item)
        if self.squares.count():
            self.squares.setCurrentRow(0)
        self._selection_changed()

    def _selection_changed(self):
        self.open_button.setEnabled(bool(self.squares.selectedItems()))

    # ------------------------------------------------------------- result
    def selection(self) -> tuple[Path, SquareName, int] | None:
        items = self.squares.selectedItems()
        d = self.zone.currentData()
        if not items or d is None:
            return None
        return Path(d), items[0].data(Qt.ItemDataRole.UserRole), int(self.size.currentData())

    def accept(self):
        self.result_ = self.selection()
        if self.result_ is None:
            return
        super().accept()
