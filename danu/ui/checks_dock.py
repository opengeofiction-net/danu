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
another - a duplicate, or two levels in one place. The fourth (R38) is a spot
height which contradicts the ring it stands inside.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..checks.crossings import by_contour

_ROW = Qt.ItemDataRole.UserRole
_KIND = Qt.ItemDataRole.UserRole + 1          # a heading's kind, to keep it folded or open


class ChecksDock(QDockWidget):
    # (contour key, the crossings to show) for the row chosen
    chosen = Signal(object, object)
    # a contour crossing itself, chosen; and the loop to cut out
    loopChosen = Signal(object)
    cutLoop = Signal(object)
    # contours that touch or lie on one another, chosen (G8e)
    touchChosen = Signal(object)
    # a spot height the rings round it contradict, chosen (R38)
    spotChosen = Signal(object)
    # what a square's file says - a long way, an ele not a number, a value
    # off the ladder (H1a)
    findingChosen = Signal(object)

    def __init__(self, parent=None):
        super().__init__('Checks', parent)
        self.setObjectName('checks')
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(4, 4, 4, 4)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        # the first scan's progress, a step a check: 13.8 s on the gobras 3x3,
        # and a line of text alone over a stack of empty lists was missed
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        box.addWidget(self.summary)
        box.addWidget(self.progress)
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
        self.spots_summary = QLabel()
        self.spots_summary.setWordWrap(True)
        self.spots_tree = QTreeWidget()
        self.spots_tree.setHeaderHidden(True)
        self.spots_tree.setColumnCount(1)
        box.addWidget(self.spots_summary)
        box.addWidget(self.spots_tree, 1)
        self.files_summary = QLabel()
        self.files_summary.setWordWrap(True)
        self.files_tree = QTreeWidget()
        self.files_tree.setHeaderHidden(True)
        self.files_tree.setColumnCount(1)
        box.addWidget(self.files_summary)
        box.addWidget(self.files_tree, 1)
        self.inside_summary = QLabel()
        self.inside_summary.setWordWrap(True)
        self.inside_tree = QTreeWidget()
        self.inside_tree.setHeaderHidden(True)
        self.inside_tree.setColumnCount(1)
        box.addWidget(self.inside_summary)
        box.addWidget(self.inside_tree, 1)
        self.surface_summary = QLabel()
        self.surface_summary.setWordWrap(True)
        # a build that will say the surface's checks is running: no steps to
        # count from here, so a bar that only says it is busy
        self.surface_busy = QProgressBar()
        self.surface_busy.setRange(0, 0)
        self.surface_busy.setTextVisible(False)
        self.surface_busy.setMaximumHeight(8)
        self.surface_busy.setVisible(False)
        self.surface_tree = QTreeWidget()
        self.surface_tree.setHeaderHidden(True)
        self.surface_tree.setColumnCount(1)
        box.addWidget(self.surface_summary)
        box.addWidget(self.surface_busy)
        box.addWidget(self.surface_tree, 1)
        self.josm_btn = QPushButton('Show in JOSM')
        self.josm_btn.setToolTip('the row chosen, shown in JOSM by its remote control, what it\n'
                                 'is about selected if it came from the main map - J')
        box.addWidget(self.josm_btn)
        self.setWidget(body)
        self.groups: list = []
        self.tree.currentItemChanged.connect(self._current)
        self.loops_tree.currentItemChanged.connect(self._current_loop)
        self.cut_btn.clicked.connect(lambda: self.cutLoop.emit(self.current_loop()))
        self.touches_tree.currentItemChanged.connect(self._current_touch)
        self.spots_tree.currentItemChanged.connect(
            lambda item, _prev: item is not None and self.spotChosen.emit(item.data(0, _ROW)))
        self.files_tree.currentItemChanged.connect(
            lambda item, _prev: item is not None and item.data(0, _ROW) is not None
            and self.findingChosen.emit(item.data(0, _ROW)))
        self.surface_tree.currentItemChanged.connect(
            lambda item, _prev: item is not None and item.data(0, _ROW) is not None
            and self.findingChosen.emit(item.data(0, _ROW)))
        self.inside_tree.currentItemChanged.connect(
            lambda item, _prev: item is not None and item.data(0, _ROW) is not None
            and self.findingChosen.emit(item.data(0, _ROW)))

    def finding(self, steps: int = 1) -> None:
        """The first scan out, on a worker: said in place of the lists, with
        a bar a check - the lists, the buttons and their empty boxes put away
        until there is something to put in them."""
        self.summary.setText('Finding the checks over this working set…')
        self.progress.setRange(0, steps)
        self.progress.setValue(0)
        self.progress.setFormat('%v of %m done')
        self.progress.setVisible(True)
        for label in (self.loops_summary, self.touches_summary, self.spots_summary, self.files_summary,
                      self.inside_summary):
            label.setText('')
        for tree in (self.tree, self.loops_tree, self.touches_tree, self.spots_tree, self.files_tree,
                     self.inside_tree, self.surface_tree):
            tree.clear()
            tree.setVisible(False)
        for button in (self.cut_btn, self.josm_btn):
            button.setVisible(False)

    def finding_step(self, step: int, steps: int, name: str) -> None:
        self.summary.setText(f'Finding the checks over this working set: {name}…')
        self.progress.setRange(0, steps)
        self.progress.setValue(step)

    def show_crossings(self, found: list) -> None:
        """The crossings as they stand, replacing what was listed. The row
        that was current stays current where its contour is still listed, so
        a mapper working down the list after an edit keeps their place."""
        self.progress.setVisible(False)
        self.josm_btn.setVisible(True)
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

    def show_spots(self, found: list) -> None:
        """The spot heights the rings round them contradict, worst first; the
        row that was current stays so where it is still listed."""
        item = self.spots_tree.currentItem()
        was = item.data(0, _ROW) if item is not None else None
        open_ = sum(c.open for c in found)
        below = sum(c.kind == 'below' and not c.open for c in found)
        above = len(found) - below - open_
        parts = [f'{below:,} below the ring round {"them" if below != 1 else "it"}'] if below else []
        if above:
            parts.append(f'{above:,} past the next contour')
        if open_:
            parts.append(f'{open_:,} in no ring and far off the contours nearest {"them" if open_ != 1 else "it"}')
        self.spots_summary.setText(
            'No spot height contradicts the contours round it.' if not found else
            f'{len(found):,} spot height{"s" * (len(found) != 1)} the contours contradict (R38): '
            + ', '.join(parts) + ' - choose one, then set its height or mend the contours.')
        self.spots_tree.blockSignals(True)
        self.spots_tree.clear()
        keep = None
        for c in found:
            row = QTreeWidgetItem([c.describe()])
            row.setData(0, _ROW, c)
            row.setToolTip(0, c.explain())
            self.spots_tree.addTopLevelItem(row)
            if was is not None and (c.square, c.node) == (was.square, was.node):
                keep = row
        if keep is not None:
            self.spots_tree.setCurrentItem(keep)
        self.spots_tree.blockSignals(False)
        self.spots_tree.setVisible(bool(found))

    FILE_HEADS = {'long': 'Ways too long for the API or GDAL (R30) - save splits them',
                  'ele': 'An ele that is not a number (R31) - the build drops it',
                  'ladder': 'Off the ladder, used once or twice - a mistyped value?'}
    INSIDE_HEADS = {'lake': 'Water spanning contours (R33) - select it, and F flattens it',
                    'bare': 'Report: rings of {ha} ha or more with nothing inside (R39) - a spot height would say how high'}
    bare_min_ha = 10.0                     # the checks' threshold, said in the heading

    def show_files(self, found: list) -> None:
        """What the squares' files say (H1a)."""
        words = {'long': 'too long', 'ele': 'with an ele not a number', 'ladder': 'off the ladder'}
        self._show_findings(
            self.files_tree, self.files_summary, found, self.FILE_HEADS,
            'Nothing in the files: no way too long, every ele a number, no value off the ladder '
            'used once or twice.',
            lambda counts: 'In the files: ' + ', '.join(f'{n:,} {words[k]}' for k, n in counts.items() if n))

    def show_inside(self, found: list) -> None:
        """What lies inside the rings (H1b): lakes spanning contours, and the
        report of rings with nothing inside, its heading folded."""
        def said(counts):
            parts = []
            if counts['lake']:
                parts.append(f'{counts["lake"]:,} lake{"s" * (counts["lake"] != 1)} spanning contours')
            if counts['bare']:
                rings = (f'{counts["bare"]:,} ring{"s" * (counts["bare"] != 1)} of {self.bare_min_ha:g} ha '
                         'or more with nothing inside')
                parts.append(f'and, as a report, {rings}' if parts else f'as a report, {rings}')
            return 'Inside the rings: ' + ' '.join(parts)
        heads = {k: v.format(ha=f'{self.bare_min_ha:g}') for k, v in self.INSIDE_HEADS.items()}
        self._show_findings(self.inside_tree, self.inside_summary, found, heads,
                            'No lake spans a contour, and every ring holds something.', said,
                            folded=('bare',))

    SURFACE_HEADS = {'climb': 'Rivers which climb on the surface (R29) - B burns a climb',
                     'backwards': 'Drawn backwards? They climb where they should fall (R29)',
                     'sea': 'Sea level off the drawn coastline (R32)',
                     'unreached': 'Unreached ground (R20), a row a square'}

    def show_surface(self, found, at: str = '', stale: bool = False, pending: bool = False) -> None:
        """What the last build said (H2), from its grids: None is no build
        since the panel opened, which is what the line says. ``pending``, a
        build is running that will say them again: said, with a busy bar."""
        self.surface_busy.setVisible(pending)
        if found is None:
            self.surface_summary.setText(
                'From the surface: the build now running will say them…' if pending else
                'From the surface: nothing yet - the checks that need a surface are asked of the next '
                'build while this panel is open (Ctrl+R builds).')
            self.surface_tree.clear()
            self.surface_tree.setVisible(False)
            return
        words = {'climb': ('river climbing', 'rivers climbing'),
                 'backwards': ('drawn backwards, likely', 'drawn backwards, likely'),
                 'sea': ('stretch of sea level off the shore', 'stretches of sea level off the shore'),
                 'unreached': ('square with ground unreached', 'squares with ground unreached')}
        when = (f'From the build at {at}'
                + (' - the build now running will say again' if pending else
                   ' - edits since, so the next build will say again' if stale else ''))
        self._show_findings(
            self.surface_tree, self.surface_summary, found, self.SURFACE_HEADS,
            f'{when}: no river climbs, sea level meets the drawn shore, and the first pass reached '
            'all the drawn ground.',
            lambda counts: f'{when}: ' + ', '.join(f'{n:,} {words[k][n != 1]}' for k, n in counts.items() if n))

    def _show_findings(self, tree, label, found, heads, empty, said, folded=()) -> None:
        """Findings under a heading a kind, a row a way, node or relation;
        the row that was current stays so where it is still listed."""
        item = tree.currentItem()
        was = item.data(0, _ROW) if item is not None else None
        open_ = {tree.topLevelItem(i).data(0, _KIND): tree.topLevelItem(i).isExpanded()
                 for i in range(tree.topLevelItemCount())}
        counts = {k: sum(f.kind == k for f in found) for k in heads}
        label.setText(empty if not found else said(counts) + ' - choose one to see it.')
        tree.blockSignals(True)
        tree.clear()
        keep = None
        for kind, head in heads.items():
            rows = [f for f in found if f.kind == kind]
            if not rows:
                continue
            top = QTreeWidgetItem([f'{head} ({len(rows):,})'])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            top.setData(0, _KIND, kind)
            tree.addTopLevelItem(top)
            for f in rows:
                row = QTreeWidgetItem([f'{f.describe()} in {f.square}'])
                row.setData(0, _ROW, f)
                row.setToolTip(0, f.explain())
                top.addChild(row)
                if was is not None and f == was:
                    keep = row
            top.setExpanded(open_.get(kind, kind not in folded))
        if keep is not None:
            tree.setCurrentItem(keep)
        tree.blockSignals(False)
        tree.setVisible(bool(found))
