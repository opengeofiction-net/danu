"""The selection panel: what is selected, and its elevation, editable.

A dock beside Elevation that says what the selection is - a contour, a point
on one, a spot height, a point on a river, a river, a river area, a lake, or a
lake ring two lakes share - its name, its
elevation, where it is, and its other tags. **Only `ele` is editable.** Danu
is not a general OSM editor; it edits elevation constraints. And on imported
water upstream owns `name` and the rest (G5a), so an edit to them here would
be undone by the next import.

The elevation field closes the gap phase 2 left: there was no way to change a
contour's elevation once drawn, and a spot height's was delete-and-place-again.
An edit goes through ``EditController.set_ele``, the rules L follows - one step
on the history, the same refusals: a river is levelled at points because it
descends, a river area not at all (R27), and a contour or spot height cannot
be left with no elevation, because then it is not one.

Enter commits, Escape puts the field back, and either hands the keys back to
the map: the tools are keys, and a mapper who typed a level should not then
find Q typed into the field.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..core.chains import LINE_KINDS
from ..core.ladder import format_ele
from ..core.square import parse_ele
from ..water.overpass import flows
from .contours import water_tags


@dataclass(frozen=True)
class Info:
    """What the panel shows for one selection."""
    kind: str
    name: str = ''
    ele: float | None = None
    editable: bool = False
    why_not: str = ''            # why the elevation cannot be edited, when it cannot
    where: str = ''
    tags: str = ''               # the rest of the tags, read-only

NOTHING = Info('Nothing selected', why_not='select something to see it here')


def _ident(kind: str, i: int) -> str:
    # local, not "drawn here": a square is a JOSM file never uploaded, so a
    # contour drawn there years ago carries a negative id as surely as one
    # drawn in Danu this morning. What the sign says is that it was never
    # upstream - which is also why G5b never counts one as gone from there
    return f'{kind} {i}' + (' (local)' if i < 0 else '')


def _others(tags: dict) -> str:
    rest = [f'{k}={v}' for k, v in tags.items() if k not in ('name', 'ele')]
    return '\n'.join(rest)


def describe(sel, layer) -> Info:
    """The selection, as the panel shows it. No widgets - so every case is a
    test of a function rather than of a form."""
    if sel is None:
        return NOTHING
    sq = sel.square
    if sel.relation is not None:
        rel = sel.relation
        flowing = flows(rel.tags)
        members = sum(1 for mem in rel.members if mem.type == 'way')
        return Info(kind='river area' if flowing else rel.tags.get('water', 'lake'),
                    name=rel.tags.get('name', ''), ele=rel.ele, editable=not flowing,
                    why_not='a river area descends, so it has no one level (R27)' if flowing else '',
                    where=f'{sq.name} · {_ident("relation", rel.id)} · {members} ways',
                    tags=_others(rel.tags))
    if sel.spot:
        node = sq.nodes.get(sel.node)
        tags = node.tags if node else {}
        return Info(kind='spot height', name=tags.get('name', ''),
                    ele=parse_ele(tags.get('ele')), editable=node is not None,
                    where=f'{sq.name} · {_ident("node", sel.node)}', tags=_others(tags))
    way = sel.way
    if way is None:
        return NOTHING
    where = f'{sq.name} · {_ident("way", way.id)} · {len(way.refs)} nodes'
    if (sq.name, way.id) in layer.water:
        name = way.tags.get('name', '')
        kind = way.tags.get('waterway') or way.tags.get('water') or 'water'
        if sel.node is not None and sel.node in sq.nodes:
            node = sq.nodes[sel.node]
            return Info(kind=f'point on a {kind}' if way.tags.get('waterway') else 'point on water',
                        name=name, ele=parse_ele(node.tags.get('ele')), editable=True,
                        where=f'{sq.name} · {_ident("node", sel.node)} of way {way.id}',
                        tags=_others(node.tags))
        if way.closed and flows(way.tags):
            # a river area: closed, so a click never lands on one of its
            # points, and flowing, so there is no one level to give it
            return Info(kind='river area', name=name, editable=False,
                        why_not='a river area descends, so it has no one level (R27)',
                        where=where, tags=_others(way.tags))
        if flows(way.tags) or not way.closed:
            levelled = sum(1 for r in way.refs
                           if r in sq.nodes and 'ele' in sq.nodes[r].tags)
            return Info(kind=kind, name=name, editable=False,
                        why_not='a river descends: select one of its points to set a level there',
                        where=f'{where} · levels at {levelled} of {len(way.refs)} points',
                        tags=_others(way.tags))
        if not water_tags(way.tags):
            return Info(kind='lake ring', name=name, editable=False,
                        why_not='more than one water relation names this ring; '
                                'the level belongs to the lake',
                        where=where, tags=_others(way.tags))
        return Info(kind=kind, name=name, ele=way.ele, editable=True, where=where,
                    tags=_others(way.tags))
    # a contour, or a node of one, which is the contour
    node_note = f' · node {sel.node}' if sel.node is not None else ''
    return Info(kind='contour', name=way.tags.get('name', ''), ele=way.ele, editable=True,
                where=where + node_note, tags=_others(way.tags))


# the profile's shading, the map's colours lighter: a climb red, a level a
# contour beside it contradicts orange, unknown grey
SPAN_FILL = {'climb': QColor(220, 40, 40, 60), 'steep': QColor(230, 120, 0, 70),
             'far': QColor(120, 120, 120, 70)}


class ProfileView(QWidget):
    """A river's grade, along it - G6b's "shown before it lands".

    Distance along the river across, elevation up. Where a contour crosses
    it, a dark dot at the contour's value; the proposed levels, amber, joined;
    the levels it has now, grey; and the spans left ungraded, shaded - red
    where the contours climb as the river is drawn, the thing a list of
    numbers hides and a line shows at once, and grey where no contour comes
    for over 5 km. A span says which on hover, and a click on one takes the
    map to it (G6d-3).
    """

    issueClicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proposal = None
        self._x = None                    # metres along to pixels, as last painted
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def show_proposal(self, proposal) -> None:
        self.proposal = proposal
        self._x = None
        self.setVisible(proposal is not None and proposal.dist is not None)
        self.update()

    def spans(self) -> list:
        p = self.proposal
        return [i for i in (p.issues or ()) if i.span is not None] if p is not None else []

    def span_at(self, px: float):
        """The span under a pixel column - within 3 px, since a climb a
        hundred metres long on an 86 km river is one pixel wide."""
        if self._x is None:
            return None
        best = None
        for issue in self.spans():
            a, b = self._x(issue.span[0]) - 3, self._x(issue.span[1]) + 3
            if a <= px <= b and (best is None or b - a < best[0]):
                best = (b - a, issue)              # the narrowest, inside a wide one
        return best[1] if best else None

    def mouseMoveEvent(self, event):
        issue = self.span_at(event.position().x())
        if issue is None:
            QToolTip.hideText()
            self.unsetCursor()
        else:
            d0, d1 = issue.span
            QToolTip.showText(event.globalPosition().toPoint(),
                              f'{d0 / 1000:.1f} to {d1 / 1000:.1f} km along - {issue.text}. '
                              'Click to show it on the map.', self)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        issue = self.span_at(event.position().x())
        if issue is not None and event.button() == Qt.MouseButton.LeftButton:
            self.issueClicked.emit(issue)
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        p = self.proposal
        if p is None or not p.dist:
            return
        values = [e for _, e in p.known or ()] + [v for v in p.levels or () if v is not None] \
            + [v for v in p.current or () if v is not None]
        if not values:
            return
        lo, hi = min(values), max(values)
        pad = max(1.0, (hi - lo) * 0.08)
        lo, hi = lo - pad, hi + pad
        length = p.dist[-1] or 1.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(34, 6, -6, -16)
        painter.fillRect(r, self.palette().base())
        x = lambda d: r.left() + r.width() * d / length            # noqa: E731
        y = lambda e: r.bottom() - r.height() * (e - lo) / (hi - lo)  # noqa: E731
        self._x = x
        for issue in self.spans():
            d0, d1 = issue.span
            painter.fillRect(QRectF(x(d0), r.top(), max(1.0, x(d1) - x(d0)), r.height()),
                             SPAN_FILL[issue.kind])
        painter.setPen(QPen(QColor(150, 150, 150), 3.0))
        for d, v in zip(p.dist, p.current or (), strict=False):
            if v is not None:
                painter.drawPoint(QPointF(x(d), y(v)))
        pen = QPen(QColor(220, 140, 0), 2.0)
        painter.setPen(pen)
        path, open_ = QPainterPath(), False
        for d, v in zip(p.dist, p.levels or (), strict=False):
            if v is None:
                open_ = False
                continue
            if open_:
                path.lineTo(x(d), y(v))
            else:
                path.moveTo(x(d), y(v))
                open_ = True
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 70, 140))
        for d, e in p.known or ():
            painter.drawEllipse(QPointF(x(d), y(e)), 2.6, 2.6)
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(0, r.top() - 6, 32, 14), Qt.AlignmentFlag.AlignRight,
                         f'{hi - pad:g}')
        painter.drawText(QRectF(0, r.bottom() - 8, 32, 14), Qt.AlignmentFlag.AlignRight,
                         f'{lo + pad:g}')
        painter.drawText(QRectF(r.left(), r.bottom() + 1, r.width(), 14),
                         Qt.AlignmentFlag.AlignRight, f'{length / 1000:.1f} km')
        painter.end()


def _mark(kind: str) -> QIcon:
    """A swatch in the colour the map and the profile give the kind: red a
    climb, orange a level a contour beside it contradicts, grey a span no
    contour reaches, brown a gap - its ring's colour."""
    pix = QPixmap(12, 12)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    colour = {'climb': QColor(200, 30, 30), 'steep': QColor(230, 120, 0),
              'far': QColor(110, 110, 110)}.get(kind, QColor(120, 60, 0))
    if kind in ('climb', 'steep', 'far'):
        painter.fillRect(1, 4, 10, 4, colour)
    else:
        painter.setPen(QPen(colour, 2.0))
        painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QIcon(pix)


class SelectionPanel(QDockWidget):
    def __init__(self, editor, parent=None):
        super().__init__('Selected', parent)
        self.setObjectName('selected')
        self.editor = editor
        body = QWidget()
        form = QFormLayout(body)
        self.kind = QLabel()
        self.name = QLabel()
        self.ele = QLineEdit()
        self.ele.setPlaceholderText('no level')
        # why the elevation cannot be edited, said where it can be read - a
        # tooltip on a greyed field is found only by someone already hovering
        # over the thing they were told they could not use
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.why.setStyleSheet('color: palette(mid);')
        self.where = QLabel()
        self.where.setWordWrap(True)
        self.tags = QLabel()
        self.tags.setWordWrap(True)
        self.tags.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow('What', self.kind)
        form.addRow('Name', self.name)
        form.addRow('Elevation (m)', self.ele)
        form.addRow('', self.why)
        form.addRow('Where', self.where)
        form.addRow('Tags', self.tags)
        # grading, for water - G6b: the action, findable without its key, and
        # the proposal it makes, shown before it lands
        self.grade_btn = QPushButton('Grade from the contours (G)')
        self.grade_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grade_btn.clicked.connect(editor.grade)
        form.addRow('', self.grade_btn)
        self.network_btn = QPushButton('Grade the river network (Shift+G)')
        self.network_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.network_btn.clicked.connect(editor.grade_network)
        form.addRow('', self.network_btn)
        self.flatten_btn = QPushButton('Flatten the lake (F)')
        self.flatten_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.flatten_btn.clicked.connect(lambda: editor.flatten())
        form.addRow('', self.flatten_btn)
        self.proposal_box = QWidget()
        box = QVBoxLayout(self.proposal_box)
        box.setContentsMargins(0, 6, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.profile = ProfileView()
        buttons = QHBoxLayout()
        self.accept_btn = QPushButton('Accept (Enter)')
        self.drop_btn = QPushButton('Drop (Esc)')
        for b in (self.accept_btn, self.drop_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            buttons.addWidget(b)
        self.accept_btn.clicked.connect(editor.accept_proposal)
        self.drop_btn.clicked.connect(editor.cancel_proposal)
        # what the grade found, each a click from the map
        self.issues = QListWidget()
        self.issues.setWordWrap(True)
        self.issues.setMaximumHeight(140)
        self.issues.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.issues.itemClicked.connect(
            lambda item: editor.show_issue(item.data(Qt.ItemDataRole.UserRole)))
        self.profile.issueClicked.connect(editor.show_issue)
        # a flatten's strength: how far it draws contours back from the shore
        self.pull_back = QSpinBox()
        self.pull_back.setRange(0, 2000)
        self.pull_back.setSingleStep(25)
        self.pull_back.setSuffix(' m')
        self.pull_back.setToolTip('How far a contour crossing the shore at another level is '
                                  'drawn back from the water')
        self.pull_back.valueChanged.connect(self._pull_back_changed)
        self.pull_back_row = QWidget()
        row = QHBoxLayout(self.pull_back_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.pull_back_label = QLabel('Draw back from the shore')
        row.addWidget(self.pull_back_label)
        row.addWidget(self.pull_back)
        box.addWidget(self.summary)
        box.addWidget(self.pull_back_row)
        box.addWidget(self.issues)
        box.addWidget(self.profile)
        box.addLayout(buttons)
        form.addRow(self.proposal_box)
        self.setWidget(body)
        editor.proposalChanged.connect(self.refresh_proposal)
        self.info = NOTHING
        self.ele.returnPressed.connect(self._commit)
        editor.selectionChanged.connect(self.refresh)
        editor.edited.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.info = info = describe(self.editor.selection, self.editor.layer)
        self.kind.setText(info.kind)
        self.name.setText(info.name or '—')
        self.ele.setText(format_ele(info.ele) if info.ele is not None else '')
        self.ele.setEnabled(info.editable)
        self.why.setText(info.why_not if not info.editable else '')
        self.why.setVisible(bool(info.why_not) and not info.editable)
        self.ele.setToolTip(info.why_not or 'Enter to set it; empty and Enter to clear a '
                            "water level. Escape puts it back.")
        self.where.setText(info.where or '—')
        self.tags.setText(info.tags or '—')
        sel = self.editor.selection
        water = sel is not None and (
            (sel.relation is not None and water_tags(sel.relation.tags))
            or (sel.relation is None and sel.way is not None
                and (sel.square.name, sel.way.id) in self.editor.layer.water))
        self.grade_btn.setVisible(water)
        self.flatten_btn.setVisible(
            sel is not None and (
                (sel.relation is not None and water_tags(sel.relation.tags) and not flows(sel.relation.tags))
                or (sel.relation is None and sel.way is not None and sel.way.closed
                    and sel.way.tags.get('natural') == 'water' and not flows(sel.way.tags))))
        # a network is of lines: a river or a stream, not a lake
        self.network_btn.setVisible(
            sel is not None and sel.relation is None and sel.way is not None
            and sel.way.tags.get('waterway') in LINE_KINDS)
        self.refresh_proposal()

    def refresh_proposal(self) -> None:
        p = getattr(self.editor, 'proposal', None)
        self.proposal_box.setVisible(p is not None)
        if p is None:
            self.profile.show_proposal(None)
            return
        self.summary.setText(p.summary)
        self.pull_back_row.setVisible(p.pull_back_m is not None)
        self.pull_back_label.setText(p.strength_label or 'Draw back from the shore')
        if p.pull_back_m is not None and self.pull_back.value() != round(p.pull_back_m):
            self.pull_back.blockSignals(True)
            self.pull_back.setValue(round(p.pull_back_m))
            self.pull_back.blockSignals(False)
        self.issues.clear()
        for issue in p.issues or ():
            item = QListWidgetItem(_mark(issue.kind), issue.text)
            item.setData(Qt.ItemDataRole.UserRole, issue)
            item.setToolTip(issue.text + ' - click to show it on the map')
            self.issues.addItem(item)
        self.issues.setVisible(bool(p.issues))
        self.accept_btn.setEnabled(p.acceptable)
        self.profile.show_proposal(p)

    def _pull_back_changed(self, value: int) -> None:
        """The flatten proposed again at the new distance - the strength
        tried before it is accepted."""
        p = getattr(self.editor, 'proposal', None)
        if p is None or p.pull_back_m is None:
            return
        if p.kind == 'burn':
            self.editor.burn(setback_m=value, again=True)
        else:
            self.editor.flatten(pull_back_m=value)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.ele.hasFocus():
            self.refresh()
            self._hand_back()
            return
        super().keyPressEvent(event)

    def _commit(self) -> None:
        text = self.ele.text().strip()
        if text:
            value = parse_ele(text)
            if value is None:
                self.editor.message.emit(f'not an elevation: {text}')
                self.refresh()
                self._hand_back()
                return
        else:
            value = None
        if (value is None and self.info.ele is None) or (
                value is not None and self.info.ele is not None
                and format_ele(value) == format_ele(self.info.ele)):
            self._hand_back()                   # nothing changed: no step on the history
            return
        self.editor.set_ele(value)
        self.refresh()
        self._hand_back()

    def _hand_back(self) -> None:
        self.editor.view.setFocus()
