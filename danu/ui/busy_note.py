"""A note at the top of the map while the squares under it are being
replaced: an import or a revert fetching from the server, and the set read
again after it. The status line says the same, but the map itself is still
live and drawn from the squares as they were, and a mapper looking at it
had no sign that what they saw was about to change."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QLabel, QWidget

MARGIN = 10


class BusyNote(QLabel):
    """Shown over the top middle of ``view`` with ``say``, gone with ``clear``.
    Clicks pass through it to the map."""

    def __init__(self, view: QWidget):
        super().__init__(view)
        self.view = view
        self.setObjectName('busyNote')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('#busyNote { background: rgba(32, 32, 32, 200); color: white;'
                           ' border-radius: 6px; padding: 4px 12px; }')
        view.installEventFilter(self)
        self.hide()

    def say(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def clear(self) -> None:
        self.hide()

    def _place(self) -> None:
        width = min(self.sizeHint().width(), max(self.view.width() - 2 * MARGIN, 0))
        self.resize(width, self.sizeHint().height())
        self.move((self.view.width() - width) // 2, MARGIN)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.view and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False
