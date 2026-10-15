"""What this Danu is - J1: its version, and the versions of what it runs on,
for the About box and for any report of a fault. A bug reported against
"the latest" cannot be reproduced; one against 0.2.0 on GDAL 3.13.3 and
isofill 0.12.0 can.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import PySide6
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout

from .. import __version__

HOME = 'https://github.com/opengeofiction-net/danu'
PRIVACY = f'{HOME}/blob/main/PRIVACY.md'          # the Store's privacy policy URL too (J8)


def basics() -> dict[str, str]:
    """What costs nothing to ask: no library loaded for it. The usage log's
    first line carries these."""
    return {'danu': __version__,
            'python': platform.python_version(),
            'qt': QtCore.qVersion(),
            'pyside6': PySide6.__version__,
            'platform': platform.platform()}


def versions() -> dict[str, str]:
    """Everything, GDAL and isofill among it - each tried, and where one
    cannot be had, why, since that is often the fault being reported."""
    out = basics()
    try:
        from osgeo import gdal
        out['gdal'] = gdal.__version__
    except ImportError as e:
        out['gdal'] = f'not available ({e})'
    try:
        from ..surface import isofill_lib
        lib = isofill_lib.Isofill.load()
        out['isofill'] = f'{lib.version} ({lib.path})'
    except (ImportError, RuntimeError) as e:     # IsofillError is a RuntimeError
        out['isofill'] = f'not available ({str(e).splitlines()[0]})'
    return out


def text(v: dict[str, str] | None = None) -> str:
    v = versions() if v is None else v
    return '\n'.join(f'{k}: {val}' for k, val in v.items())


class AboutDialog(QDialog):
    """What Danu is, and the versions, selectable, with a button to copy them
    for a report - which leaves the box open, as a message box's would not."""

    def __init__(self, parent=None, v: dict[str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle('About Danu')
        self.versions = text(v)
        head = QLabel(f'<b>Danu {__version__}</b><br>the OpenGeofiction contour editor<br>'
                      f'<a href="{HOME}">{HOME}</a><br><br>'
                      'Free software under the GNU General Public Licence, version 3 or later.<br>'
                      f'<a href="{PRIVACY}">Privacy policy</a>')
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setOpenExternalLinks(True)
        body = QPlainTextEdit(self.versions)
        body.setReadOnly(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy = buttons.addButton('Copy versions', QDialogButtonBox.ButtonRole.ActionRole)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.versions))
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(body)
        lay.addWidget(buttons)
        self.resize(560, 320)


def show(parent) -> AboutDialog:
    dlg = AboutDialog(parent)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dlg.open()
    return dlg


def icon() -> QIcon:
    """Danu's icon at every size it is drawn at - packaging/icon/make_icon.py."""
    out = QIcon()
    for png in sorted((Path(__file__).parent / 'icons').glob('danu-*.png')):
        out.addFile(str(png))
    return out


def title(centre=None, dirty: bool = False) -> str:
    """The window's title: the version always, the working set's centre when
    there is one, and a star while it has edits not saved."""
    t = f'Danu {__version__}'
    if centre is not None:
        t += f' - {centre}'
    return t + (' *' if dirty else '')


if __name__ == '__main__':                # python -m danu.ui.about: the versions, for a terminal report
    print(text())
    sys.exit(0)
