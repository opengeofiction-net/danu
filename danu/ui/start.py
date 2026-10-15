"""The start page (J5a): a card over the map when nothing is open.

Danu starts by putting back the last session, or failing that by opening the
most recent square. Only when neither opens anything - a first run, or every
square gone from where it was - is there nothing to show but the map, and
then this says what to do: sign in, import a zone, open squares already
on disk, or start a square nobody has drawn (J5c). The map stays live behind
it, the territories on it, so a mapper can look for their zone before
importing it - or find the ground a new square is to be. It goes when a
working set is on screen.

Asked for - Help › Start page, or at every start by the preferences - it is
shown over the squares too, with a Close; opening others closes it as well.

Run from an AppImage with no place in the applications menu, it offers one,
once: whether taken or declined the question is not put again, and the
preferences have it after.

Each step's button triggers the File menu's own action, so the card and the
menu are one path, and the usage log has the step by the action's name.

A child of the **view**, not of its viewport, for the reason
``danu.ui.legend`` records: a scroll takes a viewport's children with it.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import __version__

WIDTH = 420                # the card's width where the map has room for it
NARROWEST = 260            # and the least it narrows to on a map that has not
MARGIN = 12                # between the card and the map's edge


class StartCard(QFrame):
    menuAnswered = Signal(bool)          # the applications menu offered: taken, or not
    closed = Signal()

    def __init__(self, view: QWidget, sign_in: QAction, import_: QAction, open_: QAction,
                 new: QAction):
        super().__init__(view)
        self.setObjectName('startCard')
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)              # the map does not show through the text
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        title = QLabel(f'<b>Danu</b> {__version__}')
        what = QLabel('Draw the contours of an OpenGeofiction territory and see the ground they make.')
        what.setWordWrap(True)

        steps = QGridLayout()
        steps.setColumnStretch(1, 1)
        steps.setHorizontalSpacing(12)
        steps.setVerticalSpacing(10)
        self.account = QLabel()
        self.account.setWordWrap(True)
        self.sign_in = self._step(steps, 0, '1', self.account, 'Sign in…', sign_in)
        imp = QLabel('Import your zone: its squares from the server, to work on here')
        imp.setWordWrap(True)
        self.import_ = self._step(steps, 1, '2', imp, 'Import…', import_)
        opn = QLabel('…or open squares already on this machine')
        opn.setWordWrap(True)
        self.open_ = self._step(steps, 2, '3', opn, 'Open…', open_)
        new_ = QLabel('…or start a square nobody has drawn: the one in the middle of the map')
        new_.setWordWrap(True)
        self.new = self._step(steps, 3, '', new_, 'New…', new)

        # the AppImage's place in the menu, asked once
        self.offer = QWidget()
        row = QHBoxLayout(self.offer)
        row.setContentsMargins(0, 0, 0, 0)
        ask = QLabel('Add Danu to your applications menu?')
        ask.setWordWrap(True)
        row.addWidget(ask, 1)
        self.offer_add = QPushButton('Add')
        self.offer_no = QPushButton('No thanks')
        for b, taken in ((self.offer_add, True), (self.offer_no, False)):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, t=taken: self._answer(t))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.offer.hide()

        self.close_ = QPushButton('Close')
        self.close_.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_.clicked.connect(self.closed)
        self.close_.hide()

        box = QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(10)
        box.addWidget(title)
        box.addWidget(what)
        box.addSpacing(4)
        box.addLayout(steps)
        box.addWidget(self.offer)
        box.addWidget(self.close_, 0, Qt.AlignmentFlag.AlignRight)
        # the viewport's resize, held by name: see danu.ui.legend
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.set_account('')

    def _step(self, grid: QGridLayout, row: int, n: str, text: QLabel, label: str,
              action: QAction) -> QPushButton:
        num = QLabel(f'<b>{n}</b>')
        num.setAlignment(Qt.AlignmentFlag.AlignTop)
        b = QPushButton(label)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # the map keeps the keys
        b.clicked.connect(action.trigger)
        action.changed.connect(lambda: b.setEnabled(action.isEnabled()))
        grid.addWidget(num, row, 0)
        grid.addWidget(text, row, 1)
        grid.addWidget(b, row, 2, Qt.AlignmentFlag.AlignTop)
        return b

    def set_account(self, user: str) -> None:
        """Who is signed in, if anyone. Signed in, Danu can say whether the
        territory under the squares is yours; signing in is not needed to
        import or to open."""
        if user:
            self.account.setText(f'Signed in to OGF as <b>{user}</b> ✓')
            self.sign_in.hide()
        else:
            self.account.setText('Sign in to OGF, so Danu can say which territories are yours')
            self.sign_in.show()
        self.place()

    def offer_menu(self, ask: bool) -> None:
        self.offer.setVisible(ask)
        self.place()

    def _answer(self, taken: bool) -> None:
        self.offer.hide()
        self.place()
        self.menuAnswered.emit(taken)

    def set_closable(self, closable: bool) -> None:
        """A Close, while it is over squares that are open."""
        self.close_.setVisible(closable)
        self.place()

    # ------------------------------------------------------------ layout
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.place()
        self.raise_()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._viewport and event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def place(self) -> None:
        """In the middle of the map, narrowed to fit it: a small window's map
        between the docks can be narrower than the card, and the view clips
        what overhangs it."""
        vp = self._viewport.geometry()
        self.setFixedWidth(max(NARROWEST, min(WIDTH, vp.width() - 2 * MARGIN)))
        self.adjustSize()
        self.move(vp.left() + max(0, (vp.width() - self.width()) // 2),
                  vp.top() + max(0, (vp.height() - self.height()) // 2))
