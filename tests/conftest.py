"""Shared by every test, the UI's too.

``DANU_CHECK_JOURNAL=1`` holds every edit the suite makes to the autosave's
promise (H4): after each step done, undone or redone, the change the
history's journal gives, put onto the square as it was at its last save,
is the square as it now is - every node, way and relation, and the order of
each. Off by default, because it copies the square at every step; run the
whole suite with it once a command is added or changed.
"""

import os
import weakref

if os.environ.get('DANU_CHECK_JOURNAL'):
    from danu.core import change as _change
    from danu.core import edits as _edits
    from danu.core.square import Node, Relation, Square, Way

    def _frozen(sq):
        return (tuple((i, n.lat, n.lon, tuple(n.tags.items())) for i, n in sq.nodes.items()),
                tuple((i, tuple(w.refs), tuple(w.tags.items())) for i, w in sq.ways.items()),
                tuple((i, tuple(r.members), tuple(r.tags.items())) for i, r in sq.relations.items()))

    def _thaw(name, frozen):
        nodes, ways, relations = frozen
        return Square(name=name,
                      nodes={i: Node(i, lat, lon, dict(t)) for i, lat, lon, t in nodes},
                      ways={i: Way(i, list(refs), dict(t)) for i, refs, t in ways},
                      relations={i: Relation(i, list(m), dict(t)) for i, m, t in relations})

    _base: dict[int, tuple] = {}
    _untracked: set[int] = set()

    def _track(squares):
        for sq in squares:
            held = _base.get(id(sq))
            if (held is None or held[0]() is not sq) and id(sq) not in _untracked:
                _base[id(sq)] = (weakref.ref(sq), _frozen(sq))

    def _check(history, squares):
        for sq in squares:
            if id(sq) not in _base or _base[id(sq)][0]() is not sq:
                continue
            put_back = _thaw(sq.name, _base[id(sq)][1])
            c = _change.change_of(sq, history.journal(sq))
            again = _change.read_change(_change.change_text(c), c.tail)
            _change.ApplyChange(again).apply(put_back)
            want, got = _frozen(sq), _frozen(put_back)
            for kind, a, b in zip(('nodes', 'ways', 'relations'), want, got, strict=True):
                if a != b:
                    raise AssertionError(f'{sq.name}: the autosave\'s change does not give back the {kind}: '
                                         f'{len(a)} held, {len(b)} put back, first difference '
                                         f'{next((x, y) for x, y in zip(a, b, strict=False) if x != y) if len(a) == len(b) else (set(a) ^ set(b))}')

    def _wrap(name):
        original = getattr(_edits.SetUndoStack, name)

        def wrapped(self, *args, **kwargs):
            if name == 'do_across':
                steps = list(args[0]) if args else list(kwargs['steps'])
                args = (steps,)
                _track(sq for sq, _ in steps)
            else:
                pending = self._done if name == 'undo_across' else self._undone
                if pending:
                    _track(sq for sq, _ in pending[-1])
            out = original(self, *args, **kwargs)
            step = steps if name == 'do_across' else out
            if step:
                _check(self, {id(sq): sq for sq, _ in step}.values())
            return out
        setattr(_edits.SetUndoStack, name, wrapped)

    for _name in ('do_across', 'undo_across', 'redo_across'):
        _wrap(_name)

    _mark_clean = _edits.SetUndoStack.mark_clean

    def _clean(self, square, *args, **kwargs):
        _mark_clean(self, square, *args, **kwargs)
        if any(self.journal(square).values()):
            # saved with an edit made during the write: its journal is read
            # against the file before, which the change's upsert puts right
            # but this exact comparison cannot follow
            _base.pop(id(square), None)
            _untracked.add(id(square))
        else:
            _base[id(square)] = (weakref.ref(square), _frozen(square))
    _edits.SetUndoStack.mark_clean = _clean
