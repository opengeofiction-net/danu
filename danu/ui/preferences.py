"""The preferences (H6e): what the INI holds, edited in a dialog rather than
in the file - the elevation steps and the checks' threshold, a key for each
action, and the servers Danu talks to.

Three tabs. **General**: the small and big steps, which the Elevation panel
also sets, the area a bare ring is reported from, and where File › Import
puts a zone's squares. **Keys**: every
rebindable action, by where it is in the menus, its key edited in place; a
key two actions share, or one Open, Quit or Rebuild has, is refused on OK and
said under the table. **Servers**: the addresses, each empty for its default,
and the port the surface is served to JOSM on.

The dialog writes the settings and nothing else; the window puts them to use
(``MainWindow.apply_settings``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .settings import DEFAULT_KEYS, REBUILD_KEY, URLS, Settings, default_url
from .widgets import unit


def fixed() -> dict[str, str]:
    """The keys that are not rebound here, and so not to be taken - asked
    of the platform, so with an application running."""
    return {'Open square': QKeySequence(QKeySequence.StandardKey.Open).toString(),
            'Quit': QKeySequence(QKeySequence.StandardKey.Quit).toString(),
            'Preferences': QKeySequence(QKeySequence.StandardKey.Preferences).toString(),
            'Rebuild surface': REBUILD_KEY}


class PreferencesDialog(QDialog):
    def __init__(self, settings: Settings, labels: dict[str, str], parent=None):
        """``labels``: each action's name as the menus give it, by key."""
        super().__init__(parent)
        self.setWindowTitle('Preferences')
        self.settings = settings
        tabs = QTabWidget()

        general = QWidget()
        form = QFormLayout(general)
        self.small = QDoubleSpinBox()
        self.small.setRange(0.1, 1000.0)
        self.small.setDecimals(1)
        self.small.setValue(settings.small_step)
        self.big = QDoubleSpinBox()
        self.big.setRange(0.1, 5000.0)
        self.big.setDecimals(1)
        self.big.setValue(settings.big_step)
        self.bare = QDoubleSpinBox()
        self.bare.setRange(0.0, 100000.0)
        self.bare.setDecimals(0)
        self.bare.setValue(settings.bare_min_hectares)
        self.bare.setToolTip('Bare rings are reported from this area up')
        form.addRow('Small step', unit(self.small))
        form.addRow('Big step', unit(self.big))
        form.addRow('Bare rings from', unit(self.bare, 'ha'))
        # where File › Import puts a zone's squares (H6g)
        self.import_root = QLineEdit(settings.q.value('squares/import_root', '') or '')
        self.import_root.setPlaceholderText(str(settings.import_root) if not self.import_root.text() else '')
        self.import_root.setToolTip('Where File › Import puts a zone\'s squares, a directory a zone; '
                                    'empty for the default')
        form.addRow('Import squares to', self.import_root)
        tabs.addTab(general, 'General')

        keys = QWidget()
        box = QVBoxLayout(keys)
        # in the menus' order, as the labels come
        self.names = [n for n in labels if n in DEFAULT_KEYS] + [n for n in DEFAULT_KEYS if n not in labels]
        self.table = QTableWidget(len(self.names), 2)
        self.table.setHorizontalHeaderLabels(['Action', 'Key'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.edits: dict[str, QKeySequenceEdit] = {}
        for row, name in enumerate(self.names):
            item = QTableWidgetItem(labels.get(name, name))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            edit = QKeySequenceEdit(QKeySequence(settings.key(name)))
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            self.table.setCellWidget(row, 1, edit)
            self.edits[name] = edit
        self.labels = {n: labels.get(n, n) for n in self.names}
        defaults = QPushButton('Defaults')
        defaults.setToolTip('Every key back to the one Danu came with')
        defaults.clicked.connect(self.default_keys)
        self.clash = QLabel()
        self.clash.setWordWrap(True)
        self.clash.setStyleSheet('color: #b04000')
        self.clash.setVisible(False)
        box.addWidget(self.table, 1)
        box.addWidget(self.clash)
        box.addWidget(defaults, 0, Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(keys, 'Keys')

        servers = QWidget()
        form = QFormLayout(servers)
        self.urls: dict[str, QLineEdit] = {}
        for key, label in URLS.items():
            default = default_url(key)
            edit = QLineEdit(settings.q.value(key, '') or '')
            edit.setPlaceholderText(default)
            edit.setToolTip(f'Empty for {default}')
            form.addRow(label, edit)
            self.urls[key] = edit
        self.wms_port = QSpinBox()
        self.wms_port.setRange(1024, 65535)
        self.wms_port.setValue(settings.wms_port)
        self.wms_port.setToolTip('The port the surface is served to JOSM on, from its next start')
        form.addRow('Surface to JOSM, port', self.wms_port)
        tabs.addTab(servers, 'Servers')

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.tabs = tabs
        self.resize(560, 520)

    def default_keys(self) -> None:
        for name, edit in self.edits.items():
            edit.setKeySequence(QKeySequence(DEFAULT_KEYS[name]))

    def clashes(self) -> list[str]:
        """Each key two actions share, or that a fixed one has, said."""
        out, seen = [], {k: label for label, k in fixed().items() if k}
        for name in self.names:
            key = self.edits[name].keySequence().toString()
            if not key:
                continue
            if key in seen:
                out.append(f'{key} is both {seen[key]} and {self.labels[name]}')
            else:
                seen[key] = self.labels[name]
        return out

    def accept(self) -> None:
        clashes = self.clashes()
        if clashes:
            self.clash.setText('; '.join(clashes))
            self.clash.setVisible(True)
            self.tabs.setCurrentIndex(1)
            return
        s = self.settings
        s.small_step, s.big_step = self.small.value(), self.big.value()
        s.bare_min_hectares = self.bare.value()
        s.import_root = Path(self.import_root.text().strip()) if self.import_root.text().strip() else None
        for name, edit in self.edits.items():
            key = edit.keySequence().toString()
            if key == DEFAULT_KEYS[name]:
                s.q.remove(f'keys/{name}')
            else:
                s.set_key(name, key)
        for key, edit in self.urls.items():
            s.set_url(key, edit.text())
        s.wms_port = self.wms_port.value()
        super().accept()
