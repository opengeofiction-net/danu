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

The second check (G8c) is a contour crossing itself, or passing through one
of its nodes twice: one row a place, and O, or the button, proposes the loop
cut out. The third (G8e) is contours that touch or lie on one another: a node
two levels share, which U unglues, and a stretch of one within a metre of
another - a duplicate, or two levels in one place.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..checks.crossings import by_contour

_ROW = Qt.ItemDataRole.UserRole


class ChecksDock(QDockWidget):
    # (contour key, the crossings to show) for the row chosen
    chosen = Signal(object, object)
    # a contour crossing itself, chosen; and the loop to cut out
    loopChosen = Signal(object)
    cutLoop = Signal(object)
    # contours that touch or lie on one another, chosen (G8e)
    touchChosen = Signal(object)

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
        box.addWidget(self.tree, 3)
        self.loops_summary = QLabel()
        self.loops_summary.setWordWrap(True)
        self.loops_tree = QTreeWidget()
        self.loops_tree.setHeaderHidden(True)
        self.loops_tree.setColumnCount(1)
        self.cut_btn = QPushButton('Cut out the loop')
        self.cut_btn.setToolTip('the loop chosen, proposed cut out of its contour - O')
        self.cut_btn.setEnabled(False)
        box.addWidget(self.loops_summary)
        box.addWidget(self.loops_tree, 1)
        box.addWidget(self.cut_btn)
        self.touches_summary = QLabel()
        self.touches_summary.setWordWrap(True)
        self.touches_tree = QTreeWidget()
        self.touches_tree.setHeaderHidden(True)
        self.touches_tree.setColumnCount(1)
        box.addWidget(self.touches_summary)
        box.addWidget(self.touches_tree, 1)
        self.setWidget(body)
        self.groups: list = []
        self.tree.currentItemChanged.connect(self._current)
        self.loops_tree.currentItemChanged.connect(self._current_loop)
        self.cut_btn.clicked.connect(lambda: self.cutLoop.emit(self.current_loop()))
        self.touches_tree.currentItemChanged.connect(self._current_touch)

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
        self.tree.setVisible(bool(found))

    def _current(self, item, _previous):
        if item is not None and item.data(0, _ROW) is not None:
            key, found = item.data(0, _ROW)
            self.chosen.emit(key, found)

    def show_loops(self, found: list) -> None:
        """The contours crossing themselves, a row a place, replacing what
        was listed; the row that was current stays so where its contour and
        place are still listed."""
        was = self.current_loop()
        self.loops_summary.setText(
            'No contour crosses itself.' if not found else
            f'{len(found):,} place{"s" * (len(found) != 1)} where a contour crosses itself or passes '
            f'through a node twice, in {len({lp.contour for lp in found})} contours - choose one, '
            'and O cuts out the loop.')
        self.loops_tree.blockSignals(True)
        self.loops_tree.clear()
        keep = None
        for lp in sorted(found, key=lambda lp: (lp.contour[2], str(lp.contour[0]), lp.contour[1], lp.i)):
            row = QTreeWidgetItem([lp.describe()])
            row.setData(0, _ROW, lp)
            row.setToolTip(0, f'{lp.explain()}\nchoose it to see where; O proposes the loop cut out')
            self.loops_tree.addTopLevelItem(row)
            if was is not None and (lp.contour, lp.lon, lp.lat) == (was.contour, was.lon, was.lat):
                keep = row
        if keep is not None:
            self.loops_tree.setCurrentItem(keep)
        self.loops_tree.blockSignals(False)
        # an empty list is a box of nothing taking half the panel
        self.loops_tree.setVisible(bool(found))
        self.cut_btn.setVisible(bool(found))
        self.cut_btn.setEnabled(self.current_loop() is not None)

    def current_loop(self):
        item = self.loops_tree.currentItem()
        return item.data(0, _ROW) if item is not None else None

    def _current_loop(self, item, _previous):
        self.cut_btn.setEnabled(item is not None)
        if item is not None:
            self.loopChosen.emit(item.data(0, _ROW))

    def show_touches(self, found: list) -> None:
        """The contours that touch or lie on one another, a row a place; the
        row that was current stays so where it is still listed."""
        item = self.touches_tree.currentItem()
        was = item.data(0, _ROW) if item is not None else None
        shared = sum(t.kind == 'shared' for t in found)
        dupes = sum(t.kind == 'coincident' and t.a[2] == t.b[2] for t in found)
        on_top = len(found) - shared - dupes
        parts = [f'{shared:,} node{"s" * (shared != 1)} two levels share'] if shared else []
        if on_top:
            parts.append(f'{on_top:,} stretch{"es" * (on_top != 1)} of one level on another')
        if dupes:
            parts.append(f'{dupes:,} duplicate{"s" * (dupes != 1)}')
        self.touches_summary.setText(
            'No contour touches or lies on another.' if not found else
            ', '.join(parts) + ' - choose one to see it; U unglues a shared node.')
        self.touches_tree.blockSignals(True)
        self.touches_tree.clear()
        keep = None
        for t in found:
            row = QTreeWidgetItem([t.describe()])
            row.setData(0, _ROW, t)
            row.setToolTip(0, t.explain())
            self.touches_tree.addTopLevelItem(row)
            if was is not None and t == was:
                keep = row
        if keep is not None:
            self.touches_tree.setCurrentItem(keep)
        self.touches_tree.blockSignals(False)
        self.touches_tree.setVisible(bool(found))

    def _current_touch(self, item, _previous):
        if item is not None:
            self.touchChosen.emit(item.data(0, _ROW))
