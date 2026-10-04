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
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QLabel, QStackedWidget, QTreeWidget, QTreeWidgetItem

from ..water.gone import Gone

_GONE = Qt.ItemDataRole.UserRole


class GoneDock(QDockWidget):
    chosen = Signal(object)            # the Gone a row stands for

    def __init__(self, parent=None):
        super().__init__('Gone from upstream', parent)
        self.setObjectName('gone')
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setRootIsDecorated(True)
        self.empty = QLabel('Nothing: the last import found everything held\n'
                            'still upstream.')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.tree)
        self.setWidget(self.stack)
        self.report: list[Gone] = []
        self._items: dict[tuple, QTreeWidgetItem] = {}
        # a click and a keyboard move both choose, so the list can be walked
        # with the arrow keys as well as the mouse
        self.tree.currentItemChanged.connect(self._current)

    def show_report(self, report: list[Gone]) -> None:
        """The last import's report, replacing whatever was listed."""
        self.report = list(report)
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
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.stack.setCurrentWidget(self.tree if self.report else self.empty)

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
        return open_

    def _current(self, item, _previous):
        if item is not None:
            self.chosen.emit(item.data(0, _GONE))
