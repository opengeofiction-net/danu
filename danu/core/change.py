"""A square's unsaved edits as a change file - H4, not losing work.

What the edits since a square's last save created, modified and deleted,
against the file it was read from, as an OSM change file: an ``.osc`` that
JOSM opens too. Its cost is the size of the edit, not of the square, where
writing the whole square is seconds of xz.

What was touched comes from the history's journal (``SetUndoStack.journal``),
which every command feeds by naming its nodes, ways and relations; whether the
file holds each is the journal's too, read the first time it was touched.
Each element is written as it now stands.

**The order is part of the change.** The build burns contours in the order
the square holds its ways, and the last to touch a cell wins it, so a square
put back with the same ways in another order is a different surface - see
``square_text``. A way an edit replaces goes to the end of the square, and so
does one created; the rest keep their place in the file. So the change says
which ways, nodes and relations end the square and in what order, its
``tail``, and a recovery applies them there: the square comes back in the
order it had, not merely with what it had.

The tail is found from the end of the square backwards, as long as what is
met was touched. Everything an edit has not touched is where the file had it,
ahead of everything it put at the end, so that run holds the whole of what
moved - and a touched element met in it that never moved is where it would be
put again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree

from .edits import Command
from .square import Member, Node, Relation, Square, Way, xml_degrees, xml_quote

KINDS = ('node', 'way', 'relation')


def _holder(square: Square, kind: str) -> dict:
    return {'node': square.nodes, 'way': square.ways, 'relation': square.relations}[kind]


@dataclass
class Change:
    """Created and modified elements by kind and id, the ids deleted, and the
    tail: kind -> the ids that end the square, in order."""
    create: dict[str, dict[int, object]] = field(default_factory=lambda: {k: {} for k in KINDS})
    modify: dict[str, dict[int, object]] = field(default_factory=lambda: {k: {} for k in KINDS})
    delete: dict[str, list[int]] = field(default_factory=lambda: {k: [] for k in KINDS})
    tail: dict[str, list[int]] = field(default_factory=lambda: {k: [] for k in KINDS})

    @property
    def empty(self) -> bool:
        return not any(self.create[k] or self.modify[k] or self.delete[k] for k in KINDS)

    def counts(self) -> dict[str, int]:
        return {action: sum(len(getattr(self, action)[k]) for k in KINDS)
                for action in ('create', 'modify', 'delete')}

    def describe(self) -> str:
        c = self.counts()
        return ', '.join(f'{n} {what}' for what, n in
                         (('created', c['create']), ('modified', c['modify']), ('deleted', c['delete'])) if n) \
            or 'nothing'


def change_of(square: Square, journal: dict[str, dict[int, bool]]) -> Change:
    """The square's change against its file, from the journal of what its
    edits touched and whether the file holds each."""
    out = Change()
    for kind in KINDS:
        holder, entries = _holder(square, kind), journal.get(kind, {})
        tail = []
        for i in reversed(holder):
            if i not in entries:
                break
            tail.append(i)
        out.tail[kind] = tail[::-1]
        for i, held in entries.items():
            obj = holder.get(i)
            if obj is not None:
                (out.modify if held else out.create)[kind][i] = obj
            elif held:
                out.delete[kind].append(i)
    return out


# ----------------------------------------------------------------- text

def _element(kind: str, obj) -> list[str]:
    q, deg = xml_quote, xml_degrees
    if kind == 'node':
        head = f"    <node id='{obj.id}' lat='{deg(obj.lat)}' lon='{deg(obj.lon)}'"
        if not obj.tags:
            return [head + ' />']
        return [head + '>', *(f'      <tag k={q(k)} v={q(v)} />' for k, v in obj.tags.items()), '    </node>']
    lines = [f"    <{kind} id='{obj.id}'>"]
    if kind == 'way':
        lines += [f"      <nd ref='{r}' />" for r in obj.refs]
    else:
        for mem in obj.members:
            role = f' role={q(mem.role)}' if mem.role else ''
            lines.append(f"      <member type={q(mem.type)} ref='{mem.ref}'{role} />")
    lines += [f'      <tag k={q(k)} v={q(v)} />' for k, v in obj.tags.items()]
    lines.append(f'    </{kind}>')
    return lines


def change_text(change: Change, generator: str = 'danu') -> str:
    """The change as an OSM change file: what was created, then modified,
    then deleted - nodes before the ways that name them, and relations last,
    deletions the other way round."""
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             f"<osmChange version='0.6' generator={xml_quote(generator)}>"]
    for action in ('create', 'modify'):
        block = getattr(change, action)
        if any(block[k] for k in KINDS):
            lines.append(f'  <{action}>')
            for kind in KINDS:
                for obj in block[kind].values():
                    lines += _element(kind, obj)
            lines.append(f'  </{action}>')
    if any(change.delete[k] for k in KINDS):
        lines.append('  <delete>')
        for kind in reversed(KINDS):
            lines += [f"    <{kind} id='{i}' />" for i in change.delete[kind]]
        lines.append('  </delete>')
    lines.append('</osmChange>')
    return '\n'.join(lines) + '\n'


def _tags(elem) -> dict[str, str]:
    return {t.get('k'): t.get('v', '') for t in elem.iter('tag')}


def read_change(text: str, tail: dict[str, list[int]] | None = None) -> Change:
    """A change file's text back into a Change, with the tail its manifest
    kept."""
    out = Change()
    root = ElementTree.fromstring(text)
    for block in root:
        action = block.tag
        if action not in ('create', 'modify', 'delete'):
            continue
        for elem in block:
            kind, i = elem.tag, int(elem.get('id'))
            if kind not in KINDS:
                continue
            if action == 'delete':
                out.delete[kind].append(i)
                continue
            if kind == 'node':
                obj = Node(id=i, lat=float(elem.get('lat')), lon=float(elem.get('lon')), tags=_tags(elem))
            elif kind == 'way':
                obj = Way(id=i, refs=[int(nd.get('ref')) for nd in elem.iter('nd')], tags=_tags(elem))
            else:
                obj = Relation(id=i, members=[Member(m.get('type'), int(m.get('ref')), m.get('role') or '')
                                              for m in elem.iter('member')], tags=_tags(elem))
            getattr(out, action)[kind][i] = obj
    for kind in KINDS:
        out.tail[kind] = list((tail or {}).get(kind, []))
    return out


# ---------------------------------------------------------------- apply

@dataclass
class ApplyChange(Command):
    """A change put onto the square it was taken from - a recovery, as one
    step a mapper can take back.

    Deletions first; then what was modified where it stands; then the tail,
    each taken out and put at the end in its order. Created and modified
    alike are put whether or not the square holds them, so a change read
    against the file as it was before an edit made during a save still puts
    the square right.

    The undo puts the ways and relations back in the order they had, which
    is the order the build reads; the nodes come back with what they held,
    and a node the change moved to the end stays there, which nothing reads."""
    change: Change
    name: str = 'recover autosaved edits'
    before: dict = field(default_factory=dict, repr=False)
    _redraw: set[int] = field(default_factory=set, repr=False)

    def touched(self, square: Square) -> tuple[set[int], set[int], set[int]]:
        c = self.change
        return tuple({*c.create[k], *c.modify[k], *c.delete[k]} for k in KINDS)

    def ways(self, square: Square) -> set[int]:
        """Its ways, and every way through a node it moved or retagged -
        found as it is applied, in one pass over the square's ways, and kept
        for the undo's redraw."""
        return self.touched(square)[1] | self._redraw

    def spots(self, square: Square) -> set[int]:
        return self.touched(square)[0]

    def apply(self, square: Square) -> None:
        c = self.change
        self.before = {}
        for kind in KINDS:
            holder = _holder(square, kind)
            ids = {*c.create[kind], *c.modify[kind], *c.delete[kind]}
            self.before[kind] = ({i: holder.get(i) for i in ids},
                                 list(holder) if kind != 'node' else None)
        nodes = {*c.modify['node'], *c.delete['node']}
        self._redraw = {wid for wid, w in square.ways.items() if nodes.intersection(w.refs)} if nodes else set()
        for kind in reversed(KINDS):
            holder = _holder(square, kind)
            for i in c.delete[kind]:
                holder.pop(i, None)
        for kind in KINDS:
            holder, tail = _holder(square, kind), c.tail[kind]
            at_end = set(tail)
            put = {**c.create[kind], **c.modify[kind]}
            for i, obj in put.items():
                if i not in at_end:
                    holder[i] = _copy(kind, obj)
            for i in tail:
                if i in put:
                    holder.pop(i, None)
                    holder[i] = _copy(kind, put[i])

    def undo(self, square: Square) -> None:
        for kind in KINDS:
            holder = _holder(square, kind)
            was, order = self.before[kind]
            for i, obj in was.items():
                if obj is None:
                    holder.pop(i, None)
                else:
                    holder[i] = obj
            if order is not None:
                rebuilt = {i: holder[i] for i in order if i in holder}
                holder.clear()
                holder.update(rebuilt)
        self.before = {}

    def describe(self) -> str:
        return self.name


def _copy(kind: str, obj):
    """An element of its own, so a change applied twice - an undo and a redo
    - never shares a list or a dict with the square."""
    if kind == 'node':
        return Node(id=obj.id, lat=obj.lat, lon=obj.lon, tags=dict(obj.tags))
    if kind == 'way':
        return Way(id=obj.id, refs=list(obj.refs), tags=dict(obj.tags))
    return Relation(id=obj.id, members=list(obj.members), tags=dict(obj.tags))
