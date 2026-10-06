"""The checks panel - the spec's validation panel, its first check (G8a).

*Checks run continuously over the working set and populate one panel. Each
entry is a location, so clicking it goes there.* The first check is R16 asked
of what the squares already hold: contours that cross. Gobras holds 6,714
crossings between 279 contours, nearly all from a few dozen rogue ways.

One row per contour, the one that crosses the most others first, with what it
crosses under it - so a rogue contour is one row at the top, not hundreds
spread through the list. A crossing does not say which of its two contours is
wrong; one that crosses thirty-six others usually does. The fix is the
mapper's: delete it, or redraw over it. Choosing a row selects that contour
and brings its crossings into view; the map marks every crossing while the
panel is open.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDockWidget, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..checks.crossings import by_contour

_ROW = Qt.ItemDataRole.UserRole


class ChecksDock(QDockWidget):
    # (contour key, the crossings to show) for the row chosen
    chosen = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__('Checks', parent)
        self.setObjectName('checks')
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(4, 4, 4, 4)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        box.addWidget(self.summary)
        box.addWidget(self.tree)
        self.setWidget(body)
        self.groups: list = []
        self.tree.currentItemChanged.connect(self._current)

    def show_crossings(self, found: list) -> None:
        """The crossings as they stand, replacing what was listed. The row
        that was current stays current where its contour is still listed, so
        a mapper working down the list after an edit keeps their place."""
        was = self.tree.currentItem()
        was_key = was.data(0, _ROW)[0] if was is not None and was.data(0, _ROW) else None
        self.groups = by_contour(found)
        n = len({id(c) for c in found})
        self.summary.setText(
            'No contour crosses another in this working set.' if not found else
            f'{n:,} crossing{"s" * (n != 1)} between contours, among {len(self.groups)} contours '
            '- no surface satisfies them (R16). The contour crossing the most others is first.')
        self.tree.blockSignals(True)
        self.tree.clear()
        keep = None
        for g in self.groups:
            top = QTreeWidgetItem([g.describe()])
            top.setData(0, _ROW, (g.contour, g.crossings))
            top.setToolTip(0, f'{g.describe()}\nchoose it to select the contour and see where it crosses')
            for other, times in sorted(g.partners.items(), key=lambda kv: (-kv[1], kv[0][2])):
                sq, wid, ele = other
                child = QTreeWidgetItem([f'crosses the {ele:g} m contour, way {wid} in {sq}'
                                         + (f' - {times} times' if times > 1 else '')])
                child.setData(0, _ROW, (g.contour, [c for c in g.crossings if other in (c.a, c.b)]))
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            if was_key is not None and g.contour[:2] == was_key[:2]:
                keep = top
        if keep is not None:
            self.tree.setCurrentItem(keep)
        self.tree.blockSignals(False)

    def _current(self, item, _previous):
        if item is not None and item.data(0, _ROW) is not None:
            key, found = item.data(0, _ROW)
            self.chosen.emit(key, found)
