"""The zones on the map, and for administrators their editing (#190, N6).

**View › Zones** opens the panel, and while it is open the map draws each
zone's squares outlined, with its name, in the
wiki's colours (``danu.core.topo_style``, OpenGeofiction:Topo layer) - blue,
an inactive one grey and filled - the one chosen in the panel thicker, from
the drop's ``GET /zones``. Anyone can look.

The **Zones** panel lists them, and while it is open the zones map is a way
in: outside the open set - or anywhere, nothing open - a click on a zone
chooses it, and a double-click on a square opens it - its zone imported
first if the square is not among the zone's here; **Import** imports the
zone chosen. Inside the
open set the map is the editor's, as ever.

An administrator signed in gets its buttons:
**New zone…** asks a name and starts it empty; **Edit squares** makes the
map a painter of whole degree squares - a click or a drag adds the squares
under it, ctrl and a drag takes them away, and squares another zone holds
show red and are never taken - until **Save**, which sends the squares as
the fewest rectangles (``zones.rects_for``), or **Cancel**. **Inactive…**
asks a reason and a note, as danu-build's ``inactive`` takes them, and
**Active** clears it. **Split…** asks the new zone's name and paints which of
the chosen zone's squares go to it - nothing outside the zone is taken - and
Save moves them, their files with them. A resize that would leave a square
with contours in no zone is refused, the squares named; the blank and the
coastline-only it leaves out are retired to the drop's kept files.

Each zone's squares are drawn too, outside the open set, in the wiki's
colours for a square (``danu.core.topo_style``): green with contours,
orange a coastline only, grey blank - the drop's listing says which. The server checks everything again: an overlap, a bad
name, a reason it doesn't know, are refused there with the reason said.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QGraphicsItem,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import dropclient
from ..core import zones as Z
from ..core.square import SquareName, label_of, list_squares
from ..core.topo_style import SQUARE, SQUARE_BLANK, SQUARE_COASTLINE, ZONE, ZONE_INACTIVE
from . import mercator as m
from . import topo_style as style
from .background import Job
from .squares import NAME_MIN_PX, draw_name

# while a zone is edited: its squares as they will be, and those the drag can't have
ADDED = QColor(31, 120, 180, 90)
TAKEN = QColor(210, 30, 30, 110)


def _cell_rect(c: SquareName) -> QRectF:
    x0, y0 = m.lonlat_to_scene(c.lon, c.lat + 1)
    x1, y1 = m.lonlat_to_scene(c.lon + 1, c.lat)
    return QRectF(x0, y0, x1 - x0, y1 - y0)


def _outline(cells) -> QPainterPath:
    path = QPainterPath()
    for c in cells:
        path.addRect(_cell_rect(c))
    return path.simplified()


class ZonesItem(QGraphicsItem):
    """Every zone's outline and name; while one is edited, its squares as
    they will be, and the squares the drag can't have."""

    def __init__(self):
        super().__init__()
        self.setZValue(97)              # over the surface's overlays, under the squares' frames
        self.zones: list[dict] = []
        self.chosen: str | None = None
        self.here: str | None = None
        self.editing: set[SquareName] | None = None
        self.refused: set[SquareName] = set()
        self._paths: dict[str, QPainterPath] = {}
        self.squares: dict[SquareName, str] = {}     # the squares held, by class
        self.labels: dict[SquareName, str] = {}      # and the names their files give them
        self.skip: set[SquareName] = set()           # the open set's: its own frames draw those

    def set_zones(self, zones: list[dict]) -> None:
        self.prepareGeometryChange()
        self.zones = zones
        self._paths = {z['name']: _outline(cells_of(z)) for z in zones}
        self.squares, self.labels = {}, {}
        for z in zones:
            for h in z.get('held', []):
                try:
                    c = SquareName.parse(h['square'])
                    self.squares[c] = _CLASS.get(h.get('class'), SQUARE_BLANK)
                    self.labels[c] = label_of(h.get('file', '')).replace('_', ' ')
                except (KeyError, ValueError):
                    continue
        self.update()

    def set_editing(self, cells: set[SquareName] | None, refused: set[SquareName] = frozenset()) -> None:
        self.prepareGeometryChange()
        self.editing = None if cells is None else set(cells)
        self.refused = set(refused)
        self.update()

    def boundingRect(self) -> QRectF:
        # the world, as the graticule's: a name is drawn at a size in pixels,
        # and reaches past a small zone's squares - Qt clips and repaints an
        # item by its rect, and cut the name short
        return QRectF(0, 0, m.WORLD, m.WORLD) if self.zones or self.editing is not None else QRectF()

    def paint(self, painter: QPainter, option, widget=None):
        scale = painter.worldTransform().m11()
        degree_px = m.WORLD / 360.0 * scale
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        for c, cls in self.squares.items():
            if c in self.skip:
                continue
            painter.setPen(style.pen(cls))
            painter.setBrush(style.brush(cls))
            painter.drawRect(_cell_rect(c))
            # each square's grid name and its own, where a degree has room:
            # the square found by what its mapper calls it
            if degree_px >= NAME_MIN_PX:
                draw_name(painter, _cell_rect(c), str(c), self.labels.get(c, ''), scale, font, QColor(110, 110, 110))
        for z in self.zones:
            path = self._paths.get(z['name'])
            if path is None or path.isEmpty():
                continue
            cls = ZONE_INACTIVE if z.get('inactive') else ZONE
            painter.setPen(style.pen(cls, 3.0 if z['name'] == self.chosen else 0.0))
            painter.setBrush(style.brush(cls))
            painter.drawPath(path)
            self._label(painter, z['name'], path.boundingRect(), style.colour(cls))
        if self.editing is not None:
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            for cells, colour in ((self.editing, ADDED), (self.refused, TAKEN)):
                for c in cells:
                    painter.fillRect(_cell_rect(c), QBrush(colour))

    @staticmethod
    def _label(painter: QPainter, text: str, rect: QRectF, colour: QColor) -> None:
        """The name at the zone's middle, the same size at any zoom."""
        t = painter.worldTransform()
        centre = t.map(rect.center())
        painter.save()
        painter.resetTransform()
        f = QFont()
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(colour))
        painter.drawText(QRectF(centre.x() - 100, centre.y() - 10, 200, 20), Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


# the drop's classes - the report's - as the topo layer's square styles
_CLASS = {'contour': SQUARE, 'coastline': SQUARE_COASTLINE, 'blank': SQUARE_BLANK}


def cells_of(zone: dict) -> set[SquareName]:
    out: set[SquareName] = set()
    for r in zone.get('squares', []):
        out |= Z.Rect.parse(r).cells()
    return out


class ZonePainter:
    """The map's tool while a zone's squares are edited: a press and a drag
    mark a rectangle of whole squares, added - or with ctrl taken away - as
    the button lets go. Squares another zone holds are refused. Anything but
    the left button is left to the map."""

    def __init__(self, item: ZonesItem, cells: set[SquareName], others: set[SquareName], changed,
                 within: set[SquareName] | None = None):
        self.item, self.cells, self.others, self.changed = item, set(cells), set(others), changed
        self.within = within                # a split: only these may be taken
        self._from: SquareName | None = None
        self._remove = False
        self.item.set_editing(self.cells)

    @staticmethod
    def _cell(p: QPointF) -> SquareName | None:
        lon, lat = m.scene_to_lonlat(p.x(), p.y())
        try:
            return SquareName(int(lon // 1), int(lat // 1))
        except ValueError:
            return None

    def _span(self, to: SquareName) -> set[SquareName]:
        a = self._from
        return {SquareName(lon, lat) for lon in range(min(a.lon, to.lon), max(a.lon, to.lon) + 1)
                for lat in range(min(a.lat, to.lat), max(a.lat, to.lat) + 1)}

    def _preview(self, to: SquareName | None) -> None:
        if self._from is None or to is None:
            self.item.set_editing(self.cells)
            return
        span = self._span(to)
        if self._remove:
            self.item.set_editing(self.cells - span)
        else:
            refused = self._refused(span)
            self.item.set_editing((self.cells | span) - refused, refused)

    def _refused(self, span: set[SquareName]) -> set[SquareName]:
        return span & self.others if self.within is None else span - self.within

    def mouse_press(self, event, p) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        self._from = self._cell(p)
        self._remove = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._preview(self._from)
        return True

    def mouse_move(self, event, p) -> bool:
        if self._from is None:
            return False
        self._preview(self._cell(p))
        return True

    def mouse_release(self, event, p) -> bool:
        if self._from is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        to = self._cell(p)
        if to is not None:
            span = self._span(to)
            self.cells = self.cells - span if self._remove else (self.cells | span) - self._refused(span)
        self._from = None
        self.item.set_editing(self.cells)
        self.changed(self.cells)
        return True

    def mouse_double_click(self, event, p) -> bool:
        return event.button() == Qt.MouseButton.LeftButton

    def key_press(self, event) -> bool:
        return False


class ZoneBrowser:
    """The zones map's clicks, outside the open set (``MapView.browse``). A
    click - a press and a release on the same spot - picks the zone under it;
    a double-click opens the square. Never a press or a drag: those are the
    tool's, so a lasso begun outside the set still sweeps into it."""

    SLOP_PX = 4

    def __init__(self, editor: 'ZoneEditor'):
        self.editor = editor
        self._pressed = None

    @staticmethod
    def _cell(p: QPointF) -> SquareName | None:
        return ZonePainter._cell(p)

    def _outside(self, cell: SquareName) -> bool:
        ws = self.editor.window.working_set
        return ws is None or cell not in ws.squares

    def press(self, event) -> None:
        self._pressed = None
        if event.button() == Qt.MouseButton.LeftButton:
            view = self.editor.window.map
            self._pressed = (event.position(), view.mapToScene(event.position().toPoint()))

    def click(self, event, p) -> None:
        pressed, self._pressed = self._pressed, None
        if pressed is None or event.button() != Qt.MouseButton.LeftButton:
            return
        at, where = pressed
        if (event.position() - at).manhattanLength() > self.SLOP_PX:
            return
        cell = self._cell(where)            # the press's square: a click over an edge is still the first's
        if cell is not None and self._outside(cell):
            self.editor.pick(cell)

    def double_click(self, event, p) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        cell = self._cell(p)
        if cell is None or not self._outside(cell):
            return False
        return self.editor.open_square(cell)


class InactiveDialog(QDialog):
    def __init__(self, zone: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{zone} inactive')
        self.reason = QComboBox()
        self.reason.addItems(Z.REASONS)
        self.note = QLineEdit()
        self.note.setPlaceholderText('why, for whoever reads the inactive file next')
        form = QFormLayout(self)
        form.addRow(QLabel(f'{zone} stays built, published and uploaded to, and off the tile servers.'))
        form.addRow('Reason', self.reason)
        form.addRow('Note', self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ZonesDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__('Zones', parent)
        self.setObjectName('zones')
        body = QWidget()
        box = QVBoxLayout(body)
        self.list = QListWidget()
        self.list.setToolTip('the zones on the server; choose one to see it on the map')
        box.addWidget(self.list)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.reload = QPushButton('Reload')
        self.import_ = QPushButton('Import')
        self.import_.setToolTip('the zone chosen, its squares copied to this machine - as File › Import')
        self.new = QPushButton('New zone…')
        self.edit = QPushButton('Edit squares')
        self.save = QPushButton('Save')
        self.cancel = QPushButton('Cancel')
        self.split = QPushButton('Split…')
        self.split.setToolTip('some of the chosen zone\'s squares a new zone, their files moved with them')
        self.inactive = QPushButton('Inactive…')
        self.active = QPushButton('Active')
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        for b in (self.reload, self.import_, self.new, self.edit):
            row1.addWidget(b)
        for b in (self.split, self.save, self.cancel, self.inactive, self.active):
            row2.addWidget(b)
        box.addLayout(row1)
        box.addLayout(row2)
        self.setWidget(body)


class ZoneEditor(QObject):
    """The panel, the map item and the drop, for the window. ``ask_name``,
    ``ask_inactive`` and ``runner`` are the tests' to replace."""

    message = Signal(str)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.item = ZonesItem()
        self.item.setVisible(False)
        self.dock = ZonesDock(window)
        self.runner = QThreadPool.globalInstance().start
        self.opener = None
        self.ask_name = lambda: _ask_name(window)
        self.ask_inactive = lambda zone: _ask_inactive(window, zone)
        self.zones: list[dict] = []
        self.splitting: str | None = None   # the zone a split takes squares from
        self._frame_pending = False
        self.painter: ZonePainter | None = None
        self.editing: str | None = None
        self._jobs: list[Job] = []
        d = self.dock
        d.reload.clicked.connect(self.load)
        d.import_.clicked.connect(lambda: self.import_zone(self.chosen()))
        self.browser = ZoneBrowser(self)
        d.new.clicked.connect(self.new_zone)
        d.edit.clicked.connect(lambda: self.start_edit(self.chosen()))
        d.save.clicked.connect(self.save)
        d.split.clicked.connect(self._split_chosen)
        d.cancel.clicked.connect(self.stop_edit)
        d.inactive.clicked.connect(self.make_inactive)
        d.active.clicked.connect(self.make_active)
        d.list.currentItemChanged.connect(lambda *_: self._chose())
        # the outlines go with the panel: open, even tabbed behind another, or closed
        d.toggleViewAction().toggled.connect(self.show)
        self.update_buttons()

    # ------------------------------------------------------------ plumbing
    def _kw(self) -> dict:
        return {} if self.opener is None else {'opener': self.opener}

    def _api(self) -> str:
        return self.window.settings.url('drop/url')

    def _token(self) -> str:
        return self.window.settings.token

    @property
    def admin(self) -> bool:
        s = self.window.settings
        return bool(s.token) and s.admin

    def _run(self, fn, done) -> None:
        """``fn`` on a worker, ``done`` with its answer. Every job is kept,
        done or not, for ``detach`` to let go of when the window closes."""
        def failed(why):
            self.say(f'the drop not reached: {why.splitlines()[0]}')
        job = Job(fn, done, failed)
        self._jobs.append(job)
        self.runner(job)

    def say(self, text: str) -> None:
        self.dock.status.setText(text)
        self.message.emit(text)

    def chosen(self) -> str | None:
        it = self.dock.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def update_buttons(self) -> None:
        d, admin, editing = self.dock, self.admin, self.editing is not None
        chosen = self.chosen()
        z = next((z for z in self.zones if z['name'] == chosen), None)
        for b in (d.new, d.edit, d.split, d.save, d.cancel, d.inactive, d.active):
            b.setVisible(admin)
        # overlaps are judged against the zones: none read, nothing to judge
        d.new.setEnabled(admin and not editing and bool(self.zones))
        d.edit.setEnabled(admin and not editing and z is not None)
        d.split.setEnabled(admin and not editing and z is not None and len(cells_of(z)) > 1)
        d.save.setEnabled(editing)
        d.cancel.setEnabled(editing)
        d.inactive.setEnabled(admin and not editing and z is not None and not z.get('inactive'))
        d.active.setEnabled(admin and not editing and z is not None and bool(z.get('inactive')))
        d.list.setEnabled(not editing)
        d.import_.setEnabled(not editing and z is not None)
        # the squares refused are the other zones' as editing began
        d.reload.setEnabled(not editing)

    # ------------------------------------------------------------ showing
    def detach(self) -> None:
        """The window closing: every job asked of the drop let go of, as the
        window lets go of the territories' and the tiles'. The global
        QThreadPool keeps a reference to each job it ran - Job is not
        auto-deleted - and a job's ``fn`` and its signals' slots hold this
        editor and its window. So a window was never freed once it had read
        the zones; open from the first run, the panel reads them as every
        window opens, and every test's window was kept, the suite running
        three times as long, collections walking all of them (#229). Each
        job's ``fn`` and connections are dropped here, which leaves the pool
        holding nothing of the window's."""
        for job in self._jobs:
            job.fn = None                   # QThreadPool keeps a job it ran; what it ran held this
            for signal in (job.signals.done, job.signals.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
        self._jobs.clear()
        self.window.map.browse = None

    def show(self, on: bool) -> None:
        self.item.setVisible(on)
        self._browse()
        if on and not self.zones:
            self.load()

    def _browse(self) -> None:
        """The map's clicks are the zones map's while it shows and no zone is
        being painted."""
        self.window.map.browse = self.browser if self.item.isVisible() and self.editing is None else None

    # ------------------------------------------------------------ the way in
    def frame_all(self) -> None:
        """The map framed on every zone - now, or once they have been read."""
        if not self.zones:
            self._frame_pending = True
            self.load()
            return
        self._frame_pending = False
        cells = [c for z in self.zones for c in cells_of(z)]
        if cells:
            self.window.map.fit_bounds(min(c.lon for c in cells), min(c.lat for c in cells),
                                       max(c.lon for c in cells) + 1, max(c.lat for c in cells) + 1)

    def zone_of(self, cell: SquareName) -> str | None:
        return next((z['name'] for z in self.zones if cell in cells_of(z)), None)

    def pick(self, cell: SquareName) -> None:
        """The zone under a click, chosen in the panel."""
        zone = self.zone_of(cell)
        if zone is None:
            return              # nothing to pick: the editor's word on the click stands
        for i in range(self.dock.list.count()):
            if self.dock.list.item(i).data(Qt.ItemDataRole.UserRole) == zone:
                self.dock.list.blockSignals(True)
                self.dock.list.setCurrentRow(i)
                self.dock.list.blockSignals(False)
        self.item.chosen = zone
        self.item.update()
        self.update_buttons()
        self.say(f'{zone} - double-click a square to open it, or Import')

    def import_zone(self, zone: str | None) -> None:
        if zone is not None and self.window.importer.import_zone(zone):
            self.say(f'importing {zone}…')

    def open_square(self, cell: SquareName) -> bool:
        """A square opened from the map: from here if its zone is, or the
        zone imported first. True if the double-click was this map's."""
        zone = self.zone_of(cell)
        if zone is None:
            self.say(f'{cell} is in no zone')
            return True
        w = self.window
        zone_dir = w.settings.import_root / zone
        if zone_dir.is_dir() and cell in list_squares(zone_dir):
            w.open_working_set(zone_dir, cell, w.settings.size)
        else:
            w.import_then_open(zone_dir, cell, f'importing {zone} to open {cell}…')
        return True

    def load(self, quiet: bool = False) -> None:
        """The zones from the drop; ``quiet`` after a change, whose own word
        stands."""
        if not quiet:
            self.say('asking the drop for its zones…')

        def done(answer):
            if not answer.ok:
                self.say(f'zones: {answer.why}')
                return
            self.set_zones(answer.body.get('zones', []))
            self.show_here()
            if self._frame_pending:
                self.frame_all()
            if not quiet:
                self.say(f'{len(self.zones)} zones')
        api, kw = self._api(), self._kw()
        self._run(lambda: dropclient.zones(api, held=True, **kw), done)

    def set_zones(self, zones: list[dict]) -> None:
        keep = self.chosen()
        self.zones = sorted(zones, key=lambda z: z['name'])
        self.item.set_zones(self.zones)
        lst = self.dock.list
        lst.blockSignals(True)
        lst.clear()
        for z in self.zones:
            n = len(cells_of(z))
            text = f"{z['name']} - {n} square{'s' if n != 1 else ''}"
            if z.get('inactive'):
                text += f" (inactive: {z['inactive']})"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, z['name'])
            lst.addItem(it)
            if z['name'] == keep:
                lst.setCurrentItem(it)
        lst.blockSignals(False)
        self.show_here()
        self.update_buttons()

    def show_here(self) -> None:
        ws = self.window.working_set
        self.item.here = None
        self.item.skip = set(ws.squares) if ws is not None else set()
        if ws is not None:
            self.item.here = next((z['name'] for z in self.zones if ws.centre in cells_of(z)), None)
        self.item.update()

    def _chose(self) -> None:
        self.item.chosen = self.chosen()
        self.item.update()
        self.update_buttons()
        z = next((z for z in self.zones if z['name'] == self.item.chosen), None)
        if z is not None and self.item.isVisible():
            r = self.item._paths[z['name']].boundingRect()
            w, n = m.scene_to_lonlat(r.left(), r.top())
            e, s = m.scene_to_lonlat(r.right(), r.bottom())
            self.window.map.fit_bounds(w, s, e, n)

    # ------------------------------------------------------------ editing
    def new_zone(self) -> None:
        name = self.ask_name()
        if not name:
            return
        if not Z.ZONE.fullmatch(name):
            self.say(f'{name!r}: a zone is lowercase letters, digits, _ and -, starting with a letter')
            return
        if any(z['name'] == name for z in self.zones):
            self.say(f'{name} is a zone already: choose it and edit its squares')
            return
        self.zones.append({'name': name, 'squares': [], 'inactive': None})
        self.start_edit(name)

    def _split_chosen(self) -> None:
        zone = self.chosen()
        if zone is None or not self.admin:
            return
        name = self.ask_name()
        if not name:
            return
        if not Z.ZONE.fullmatch(name) or any(z['name'] == name for z in self.zones):
            self.say(f'{name!r}: a new zone\'s name - lowercase letters, digits, _ and -, and not one there is')
            return
        z = next(z for z in self.zones if z['name'] == zone)
        self.editing, self.splitting = name, zone
        self.dock.show()
        self.show(True)
        self.window.map.browse = None
        self.painter = ZonePainter(self.item, set(), set(),
                                   lambda cells: self.say(f'{len(cells)} of {zone}\'s squares to {name} - Save to split'),
                                   within=cells_of(z))
        self._tool, self.window.map.tool = self.window.map.tool, self.painter
        self.say(f'{zone} into {name}: click or drag over the squares that go to {name}; then Save')
        self.update_buttons()

    def start_edit(self, name: str | None) -> None:
        if name is None or not self.admin:
            return
        z = next(z for z in self.zones if z['name'] == name)
        others = set().union(*(cells_of(o) for o in self.zones if o['name'] != name))
        self.editing = name
        self.dock.show()
        self.show(True)
        self.window.map.browse = None
        self.painter = ZonePainter(self.item, cells_of(z), others,
                                   lambda cells: self.say(f'{name}: {len(cells)} squares - Save to send them'))
        self._tool, self.window.map.tool = self.window.map.tool, self.painter
        self.say(f'{name}: click or drag to add squares, ctrl and drag to take them away; then Save')
        self.update_buttons()

    def stop_edit(self) -> None:
        if self.editing is None:
            return
        if not any(cells_of(z) for z in self.zones if z['name'] == self.editing):
            self.zones = [z for z in self.zones if z['name'] != self.editing or z['squares']]
        self.window.map.tool = self._tool
        self.editing, self.painter, self.splitting = None, None, None
        self._browse()
        self.item.set_editing(None)
        self.say('')
        self.update_buttons()

    def save(self) -> None:
        if self.editing is None or self.painter is None:
            return
        name, cells = self.editing, self.painter.cells
        if not cells:
            self.say(f'{name} needs at least one square')
            return
        rects = [str(r) for r in Z.rects_for(cells)]
        api, token, kw, source = self._api(), self._token(), self._kw(), self.splitting

        def done(answer):
            if not answer.ok:
                self.say(f'{name} not saved: {answer.why}')
                return
            self.stop_edit()
            if source is not None:
                moved = answer.body.get('moved', [])
                self.say(f'{source} split: {name} is {", ".join(rects)}, {len(moved)} square'
                         f'{"" if len(moved) == 1 else "s"} moved with it')
            else:
                retired = answer.body.get('retired', [])
                self.say(f'{name} saved: {", ".join(rects)}'
                         + (f' - left out and retired: {", ".join(retired)}' if retired else ''))
            self.load(quiet=True)
        if source is not None:
            self._run(lambda: dropclient.split_zone(api, token, source, name, rects, **kw), done)
        else:
            self._run(lambda: dropclient.put_zone(api, token, name, rects, **kw), done)

    def make_inactive(self) -> None:
        name = self.chosen()
        got = self.ask_inactive(name) if name else None
        if got is None:
            return
        self._inactive(name, *got)

    def make_active(self) -> None:
        name = self.chosen()
        if name:
            self._inactive(name, None, '')

    def _inactive(self, name: str, reason: str | None, note: str) -> None:
        api, token = self._api(), self._token()

        def done(answer):
            if not answer.ok:
                self.say(f'{name}: {answer.why}')
                return
            self.say(f'{name} inactive: {reason}' if reason else f'{name} active again')
            self.load(quiet=True)
        self._run(lambda: dropclient.set_inactive(api, token, name, reason, note, **self._kw()), done)


def _ask_name(parent) -> str | None:
    text, ok = QInputDialog.getText(parent, 'New zone', 'Its name - lowercase letters, digits, _ and -:')
    return text.strip() if ok else None


def _ask_inactive(parent, zone: str) -> tuple[str, str] | None:
    dlg = InactiveDialog(zone, parent)
    if not dlg.exec():
        return None
    return dlg.reason.currentText(), dlg.note.text().strip()
