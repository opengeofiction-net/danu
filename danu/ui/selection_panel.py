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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QFormLayout, QLabel, QLineEdit, QWidget

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
        self.setWidget(body)
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
