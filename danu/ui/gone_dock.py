"""The gone-from-upstream dock - R40's report, G5c.

*A feature gone from upstream is reported rather than deleted.* G5b worked out
the report; this is where a mapper works through it. A list rather than a
status line, which could only count, or a dialog, which is dismissed and gone:
the features want looking at one at a time, and the list outlives the moment
the import finished.

Choosing a row selects the feature on the map and brings it into view - the
selection the map would have made, so what follows is the editor's own: Shift+
Delete takes a river away, and a lake with the untagged rings that are nothing
without it; Ctrl+Z puts either back. Keeping a feature is doing nothing.

A lake's rings are listed under the lake, when the lake is gone too: deleting
it deals with them, and listing them beside it would ask the mapper to work
out which three rows are one thing. A ring whose lake is still upstream - a
ring upstream replaced under a new id - has nothing to sit under, and stands
on its own.

A row whose feature has since been deleted stays, struck through: the report
is of what the import found, and a list that rearranged itself under the
mapper's hand while they worked down it would lose their place.

Below those, the spot heights whose height the main map now gives otherwise
(G9): the square's is kept, and the mapper decides - one button takes the
main map's for the row chosen, the other for every row, either one step.

Below them, the lakes flattened here whose outline the import changed (G7a-bis):
their fill lines and clipped contours were laid against the old shore, and F
flattens them again. Not gone - still upstream, and still held - but the same
kind of thing a mapper has to look at after an import, so the same list.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.square import Way
from ..water.gone import Gone
from ..water.peaks import Differs

_GONE = Qt.ItemDataRole.UserRole


class GoneDock(QDockWidget):
    chosen = Signal(object)            # the Gone a row stands for
    takeHeights = Signal(object)       # the Differs to take the main map's height for

    def __init__(self, parent=None):
        super().__init__('Gone from upstream', parent)
        self.setObjectName('gone')
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setRootIsDecorated(True)
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.take_btn = QPushButton("Take the main map's height")
        self.take_btn.setToolTip("the row chosen: the square's height replaced by the main map's")
        self.take_all_btn = QPushButton()
        self.take_all_btn.setToolTip("every row listed: the squares' heights replaced by the main map's")
        buttons = QHBoxLayout()
        buttons.addWidget(self.take_btn)
        buttons.addWidget(self.take_all_btn)
        self.listed = QWidget()
        box = QVBoxLayout(self.listed)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.tree)
        box.addLayout(buttons)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.listed)
        self.setWidget(self.stack)
        self.report: list[Gone] = []
        self.reshaped: list = []
        self.differs: list[Differs] = []
        self._taken: set = set()
        self.take_btn.clicked.connect(lambda: self.takeHeights.emit([self.current_differs()]))
        self.take_all_btn.clicked.connect(
            lambda: self.takeHeights.emit([d for d in self.differs if (d.square, d.id) not in self._taken]))
        self._items: dict[tuple, QTreeWidgetItem] = {}
        # a click and a keyboard move both choose, so the list can be walked
        # with the arrow keys as well as the mouse
        self.tree.currentItemChanged.connect(self._current)

    NOTHING_GONE = 'Nothing: the last import found everything held\nstill upstream.'
    NOT_IMPORTED = 'No import yet for this working set.'

    def show_report(self, report: list[Gone], imported: bool = True, reshaped=(), differs=()) -> None:
        """The last import's report, replacing whatever was listed.

        ``imported`` False is a set opened and not yet imported into. An
        empty list then says that, and not that an import found everything
        still upstream - which, of a set nobody has imported, would be a
        claim about an answer that was never asked for."""
        self.report = list(report)
        self.reshaped = list(reshaped)
        self.differs = list(differs)
        self._taken = set()
        self.empty.setText(self.NOTHING_GONE if imported else self.NOT_IMPORTED)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        lakes = {(g.square, g.id): g for g in self.report if g.kind == 'relation'}
        for g in self.report:
            if g.kind == 'relation':
                self._items[(g.square, g.kind, g.id)] = self._item(g)
        for g in self.report:
            if g.kind == 'relation':
                continue
            under = self._items.get((g.square, 'relation', g.of)) if (g.square, g.of) in lakes else None
            self._items[(g.square, g.kind, g.id)] = self._item(g, under)
        if self.differs:
            head = QTreeWidgetItem([f'Height differs from the main map ({len(self.differs)})'])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(head)
            for d in self.differs:
                item = QTreeWidgetItem([d.describe()])
                item.setData(0, _GONE, d)
                item.setToolTip(0, "the square's height is kept - the main map fixed since, or\n"
                                   "set here; the button takes the main map's")
                head.addChild(item)
                self._items[(d.square, 'node', d.id, 'differs')] = item
        if self.reshaped:
            head = QTreeWidgetItem([f'Flattened, and reshaped upstream since ({len(self.reshaped)})'])
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(head)
            for r in self.reshaped:
                item = QTreeWidgetItem([r.describe()])
                item.setData(0, _GONE, r)
                item.setToolTip(0, 'its fill lines and clipped contours were laid against the\n'
                                   'outline it had - select it and F flattens it again')
                head.addChild(item)
                self._items[(r.square, r.kind, r.id, 'reshaped')] = item
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._buttons()
        self.stack.setCurrentWidget(self.listed if self.report or self.reshaped or self.differs
                                    else self.empty)

    def current_differs(self) -> Differs | None:
        item = self.tree.currentItem()
        d = item.data(0, _GONE) if item is not None else None
        return d if isinstance(d, Differs) and (d.square, d.id) not in self._taken else None

    def _buttons(self) -> None:
        left = sum((d.square, d.id) not in self._taken for d in self.differs)
        self.take_btn.setVisible(bool(self.differs))
        self.take_all_btn.setVisible(bool(self.differs))
        self.take_btn.setEnabled(self.current_differs() is not None)
        self.take_all_btn.setText(f"Take the main map's for all {left}")
        self.take_all_btn.setEnabled(left > 0)

    def _item(self, g: Gone, under: QTreeWidgetItem | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([g.describe()])
        item.setData(0, _GONE, g)
        item.setToolTip(0, 'not in the last answer: deleted upstream, or no longer\n'
                           'tagged as the water the import asks for. Kept here.')
        if under is None:
            self.tree.addTopLevelItem(item)
        else:
            under.addChild(item)
        return item

    def mark_deleted(self, working_set) -> int:
        """Strike through the rows whose feature the square no longer holds.
        Answers how many rows are still open, for whoever wants to say so."""
        open_ = 0
        for g in self.report:
            item = self._items.get((g.square, g.kind, g.id))
            if item is None:
                continue
            square = working_set.squares.get(g.square) if working_set else None
            held = square is not None and g.id in (
                square.relations if g.kind == 'relation' else square.ways)
            font = item.font(0)
            font.setStrikeOut(not held)
            item.setFont(0, font)
            item.setToolTip(0, 'deleted here since the import' if not held else
                            'not in the last answer: deleted upstream, or no longer\n'
                            'tagged as the water the import asks for. Kept here.')
            open_ += held
        # a height differing is settled once the square's is the main map's -
        # taken with the button, or set by hand - or the spot height is gone;
        # and unsettled again by the undo that puts it back
        self._taken = set()
        for d in self.differs:
            item = self._items.get((d.square, 'node', d.id, 'differs'))
            square = working_set.squares.get(d.square) if working_set else None
            node = square.nodes.get(d.id) if square is not None else None
            took = d.settled(node)
            if node is None or took:
                self._taken.add((d.square, d.id))
            if item is None:
                continue
            font = item.font(0)
            font.setStrikeOut(node is None or took)
            item.setFont(0, font)
            item.setToolTip(0, 'deleted here since the import' if node is None else
                            "the main map's height, now" if took else
                            "the square's height is kept - the main map fixed since, or\n"
                            "set here; the button takes the main map's")
        self._buttons()
        for r in self.reshaped:
            item = self._items.get((r.square, r.kind, r.id, 'reshaped'))
            square = working_set.squares.get(r.square) if working_set else None
            if item is None or square is None:
                continue
            if r.id not in (square.relations if r.kind == 'relation' else square.ways):
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setToolTip(0, 'deleted here since the import')
        return open_

    def mark_flattened(self, square, feature) -> None:
        """A reshaped lake flattened again: its row struck through, so the
        list can be worked down. Kept rather than removed, for the same reason
        a deleted feature's row is."""
        kind = 'way' if isinstance(feature, Way) else 'relation'
        item = self._items.get((square, kind, feature.id, 'reshaped'))
        if item is not None:
            font = item.font(0)
            font.setStrikeOut(True)
            item.setFont(0, font)
            item.setToolTip(0, 'flattened again since the import')

    def _current(self, item, _previous):
        self._buttons()
        if item is not None and item.data(0, _GONE) is not None:
            self.chosen.emit(item.data(0, _GONE))
