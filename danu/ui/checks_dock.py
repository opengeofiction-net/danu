"""The Validation panel - the spec's validation panel, its first check (G8a).

One tree since H6d, as JOSM's validator has it: a node a check, its count in
its label and what it means in its tooltip, the places under it - a check
with nothing to say is a greyed node with nothing under it, not a sentence.
It was seven lists, each with a paragraph above it, and had grown past what
a panel holds.

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
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QHBoxLayout,
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
_CHECK = Qt.ItemDataRole.UserRole + 1         # the check a node or a row is of

# the checks, in the tree's order: the label, and what the tooltip says it is
CHECKS = {
    'crossings': ('Crossing contours', 'Contours that cross another - no surface satisfies them (R16). '
                                       'The contour crossing the most others is first'),
    'loops': ('Contours crossing themselves', 'A contour crossing itself, or passing through a node '
                                              'twice - choose one, and O cuts out the loop'),
    'touches': ('Touching contours', 'Contours that touch or lie on one another - a node two levels '
                                     'share, which U unglues, or a stretch of one on another'),
    'spots': ('Contradicted spot heights', 'Spot heights the contours round them contradict (R38) - '
                                           'set the height, or mend the contours'),
    'long': ('Ways too long', 'Ways too long for the API or GDAL (R30) - save splits them'),
    'ele': ('Ele not a number', 'An ele that is not a number (R31) - the build drops it'),
    'ladder': ('Off the ladder', 'A value off the ladder, used once or twice - a mistyped value?'),
    'lake': ('Lakes spanning contours', 'Water spanning contours (R33) - select it, and F flattens it'),
    'bare': ('Bare rings', 'A report: rings of {ha} ha or more with nothing inside (R39) - '
                           'a spot height would say how high'),
    'climb': ('Climbing rivers', 'Rivers which climb on the surface (R29) - B burns a climb'),
    'backwards': ('Rivers drawn backwards', 'Rivers that climb where they should fall - drawn '
                                            'backwards, likely (R29)'),
    'sea': ('Sea level off the shore', 'Sea level off the drawn coastline (R32)'),
    'unreached': ('Unreached ground', 'Ground the first pass did not reach (R20), a row a square'),
}
FILES = ('long', 'ele', 'ladder')
INSIDE = ('lake', 'bare')
SURFACE = ('climb', 'backwards', 'sea', 'unreached')


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
    # a finding of the files' (H1a), the rings' (H1b) or the surface's (H2)
    findingChosen = Signal(object)

    bare_min_ha = 10.0                     # the checks' threshold, said in the tooltip

    def __init__(self, parent=None):
        super().__init__('Validation', parent)
        self.setObjectName('checks')
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(4, 4, 4, 4)
        # the first scan's progress, a step a check: 13.8 s on the gobras 3x3
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        # said only when the scan could not be done
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        # the checks run over the whole set either way: a crossing at the
        # square's edge needs its neighbour to be found
        self.centre_only = QCheckBox('Centre square only')
        self.centre_only.setToolTip('List and mark what is found in the centre square, '
                                    'not in its neighbours as well')
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.nodes: dict[str, QTreeWidgetItem] = {}
        for check, (label, _tip) in CHECKS.items():
            node = QTreeWidgetItem([label])
            node.setData(0, _CHECK, check)
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(node)
            self.nodes[check] = node
        self.surface_state = ''               # what the surface's nodes say in place of a count
        self.groups: list = []
        box.addWidget(self.progress)
        box.addWidget(self.status)
        box.addWidget(self.centre_only)
        box.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.cut_btn = QPushButton('Cut out loop')
        self.cut_btn.setToolTip('The loop chosen, proposed cut out of its contour - O')
        self.cut_btn.setEnabled(False)
        self.josm_btn = QPushButton('Show in JOSM')
        self.josm_btn.setToolTip('The row chosen, shown in JOSM by its remote control - J')
        buttons.addWidget(self.cut_btn)
        buttons.addWidget(self.josm_btn)
        box.addLayout(buttons)
        self.setWidget(body)
        for check in CHECKS:
            self._fill(check, [], lambda f: None, lambda f: f)
        self.tree.currentItemChanged.connect(self._current)
        self.cut_btn.clicked.connect(lambda: self.cutLoop.emit(self.current_loop()))

    # ------------------------------------------------------------ reading
    def node(self, check: str) -> QTreeWidgetItem:
        return self.nodes[check]

    def rows(self, check: str) -> list[QTreeWidgetItem]:
        node = self.nodes[check]
        return [node.child(i) for i in range(node.childCount())]

    def current_finding(self):
        """The row chosen, as (check, what it holds), or None."""
        item = self.tree.currentItem()
        f = item.data(0, _ROW) if item is not None else None
        return (item.data(0, _CHECK), f) if f is not None else None

    def current_loop(self):
        item = self.tree.currentItem()
        return item.data(0, _ROW) if item is not None and item.data(0, _CHECK) == 'loops' else None

    # ------------------------------------------------------------ the scan
    def finding(self, steps: int = 1) -> None:
        """The first scan out, on a worker: a bar a check, the tree put away
        until there is something to put in it."""
        self.progress.setRange(0, steps)
        self.progress.setValue(0)
        self.progress.setFormat('Finding the checks - %v of %m')
        self.progress.setVisible(True)
        self.status.setVisible(False)
        self.tree.setVisible(False)
        for button in (self.cut_btn, self.josm_btn):
            button.setVisible(False)

    def finding_step(self, step: int, steps: int, name: str) -> None:
        self.progress.setRange(0, steps)
        self.progress.setValue(step)
        self.progress.setFormat(f'Finding the checks: {name} - %v of %m')

    def failed(self, why: str) -> None:
        self.progress.setVisible(False)
        self.status.setText(f'The checks could not be found: {why}. Close the panel and open it again '
                            'to try again.')
        self.status.setVisible(True)

    def _found(self) -> None:
        self.progress.setVisible(False)
        self.status.setVisible(False)
        self.tree.setVisible(True)
        for button in (self.cut_btn, self.josm_btn):
            button.setVisible(True)

    # ------------------------------------------------------------ the tree
    def _fill(self, check, rows, same, row, tip: str = '', count: str | None = None) -> None:
        """A check's node, its rows replaced: ``rows`` the findings, ``row``
        one's item, ``same`` the key the current row is kept by - a mapper
        working down the list after an edit keeps their place."""
        node = self.nodes[check]
        current = self.tree.currentItem()
        was = (same(current.data(0, _ROW)) if current is not None and current.data(0, _CHECK) == check
               and current.data(0, _ROW) is not None else None)
        self.tree.blockSignals(True)
        node.takeChildren()
        keep = None
        for f in rows:
            item = row(f)
            if not isinstance(item, QTreeWidgetItem):
                item = QTreeWidgetItem([item])
            item.setData(0, _CHECK, check)
            item.setData(0, _ROW, f)
            for i in range(item.childCount()):
                item.child(i).setData(0, _CHECK, check)
            node.addChild(item)
            if was is not None and same(f) == was:
                keep = item
        label, what = CHECKS[check]
        node.setText(0, f'{label} ({len(rows):,})' if count is None else f'{label} ({count})')
        node.setToolTip(0, (tip + '\n' if tip else '') + what.format(ha=f'{self.bare_min_ha:g}'))
        # nothing to say: greyed, and nothing under it
        node.setForeground(0, self.palette().brush(
            QPalette.ColorGroup.Disabled if not rows else QPalette.ColorGroup.Active, QPalette.ColorRole.Text))
        if keep is not None:
            self.tree.setCurrentItem(keep)
        self.tree.blockSignals(False)

    def _current(self, item, _previous) -> None:
        check = item.data(0, _CHECK) if item is not None else None
        self.cut_btn.setEnabled(check == 'loops')
        f = item.data(0, _ROW) if item is not None else None
        if f is None:
            return
        if check == 'crossings':
            self.chosen.emit(*f)
        elif check == 'loops':
            self.loopChosen.emit(f)
        elif check == 'touches':
            self.touchChosen.emit(f)
        elif check == 'spots':
            self.spotChosen.emit(f)
        else:
            self.findingChosen.emit(f)

    # ------------------------------------------------------------ the checks
    def show_crossings(self, found: list) -> None:
        """A row a contour, the one crossing the most others first, what it
        crosses under it."""
        self._found()
        self.groups = by_contour(found)
        n = len({id(c) for c in found})

        def row(g):
            top = QTreeWidgetItem([g.describe()])
            top.setToolTip(0, f'{g.describe()}\nchoose it to select the contour and see where it crosses')
            for other, times in sorted(g.partners.items(), key=lambda kv: (-kv[1], kv[0][2])):
                sq, wid, ele = other
                child = QTreeWidgetItem([f'crosses {ele:g} m contour, way {wid} in {sq}'
                                         + (f' - {times} times' if times > 1 else '')])
                child.setData(0, _ROW, (g.contour, [c for c in g.crossings if other in (c.a, c.b)]))
                top.addChild(child)
            return top
        self._fill('crossings', [(g.contour, g.crossings) for g in self.groups], lambda f: f[0][:2],
                   lambda f: row(next(g for g in self.groups if g.contour == f[0])),
                   tip=f'{n:,} crossing{"s" * (n != 1)} among {len(self.groups)} contours' if found else '')

    def show_loops(self, found: list) -> None:
        rows = sorted(found, key=lambda lp: (lp.contour[2], str(lp.contour[0]), lp.contour[1], lp.i))

        def row(lp):
            item = QTreeWidgetItem([lp.describe()])
            item.setToolTip(0, f'{lp.explain()}\nchoose it to see where; O proposes the loop cut out')
            return item
        self._fill('loops', rows, lambda lp: (lp.contour, lp.lon, lp.lat), row,
                   tip=f'in {len({lp.contour for lp in found})} contours' if found else '')
        self.cut_btn.setEnabled(self.current_loop() is not None)

    def show_touches(self, found: list) -> None:
        shared = sum(t.kind == 'shared' for t in found)
        forks = sum(t.kind == 'fork' for t in found)
        dupes = sum(t.kind == 'coincident' and t.a[2] == t.b[2] for t in found)
        on_top = len(found) - shared - forks - dupes
        parts = [f'{shared:,} node{"s" * (shared != 1)} two levels share'] if shared else []
        if forks:
            parts.append(f'{forks:,} fork{"s" * (forks != 1)}')
        if on_top:
            parts.append(f'{on_top:,} stretch{"es" * (on_top != 1)} of one level on another')
        if dupes:
            parts.append(f'{dupes:,} duplicate{"s" * (dupes != 1)}')

        def row(t):
            item = QTreeWidgetItem([t.describe()])
            item.setToolTip(0, t.explain())
            return item
        self._fill('touches', found, lambda t: t, row, tip=', '.join(parts))

    def show_spots(self, found: list) -> None:
        open_ = sum(c.open for c in found)
        below = sum(c.kind == 'below' and not c.open for c in found)
        above = len(found) - below - open_
        parts = [f'{below:,} below the ring round {"them" if below != 1 else "it"}'] if below else []
        if above:
            parts.append(f'{above:,} past the next contour')
        if open_:
            parts.append(f'{open_:,} in no ring and far off the contours nearest {"them" if open_ != 1 else "it"}')

        def row(c):
            item = QTreeWidgetItem([c.describe()])
            item.setToolTip(0, c.explain())
            return item
        self._fill('spots', found, lambda c: (c.square, c.node), row, tip=', '.join(parts))

    def _show_findings(self, checks, found, count=None, tip: str = '') -> None:
        def row(f):
            item = QTreeWidgetItem([f'{f.describe()} in {f.square}'])
            item.setToolTip(0, f.explain())
            return item
        for check in checks:
            self._fill(check, [f for f in found if f.kind == check], lambda f: f, row, tip=tip,
                       count=count(sum(f.kind == check for f in found)) if count else None)

    def show_files(self, found: list) -> None:
        """What the squares' files say (H1a)."""
        self._show_findings(FILES, found)

    def show_inside(self, found: list) -> None:
        """What lies inside the rings (H1b): lakes spanning contours, and the
        report of rings with nothing inside."""
        self._show_findings(INSIDE, found)

    def show_surface(self, found, at: str = '', stale: bool = False, pending: bool = False) -> None:
        """What the last build said (H2), from its grids: None is no build
        since the panel opened. The state goes on each node - no build,
        building, or the count and stale."""
        if found is None:
            self.surface_state = 'building…' if pending else 'no build'
            tip = ('The build now running will say them' if pending else
                   'Asked of the next build while this panel is open - Ctrl+R builds')
            for check in SURFACE:
                self._fill(check, [], lambda f: f, lambda f: f, tip=tip, count=self.surface_state)
            return
        self.surface_state = 'building…' if pending else 'stale' if stale else ''
        tip = (f'From the build at {at}'
               + (' - the build now running will say again' if pending else
                  ' - edits since, so the next build will say again' if stale else ''))
        self._show_findings(SURFACE, found, tip=tip,
                            count=lambda n: f'{n:,}, {self.surface_state}' if self.surface_state else f'{n:,}')
