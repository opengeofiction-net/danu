"""The usage log - H4c: what a mapper did, so a reported bug can be replayed
rather than described.

Two findings of the phase 3 review were misread from a description, and both
were found only by printing what each click of the real gesture snapped to.
This is that print, kept: a JSON line an event under
``~/.local/share/danu/usage/``, one file a run, the last ``KEEP`` kept.

Each press, release and double click on the map, each move while a button is
held - a stroke is its path - each wheel turn and each key the map is given,
and the cursor's last place before each of them, since the tools keep the
cursor and a press can read it: of the moves in between, only that one,
with where it was on the ground, the view's zoom and centre, and the tool;
for a press, what it could snap to - the node within the snap radius, the
contour within the pick radius, the spot height - so the log says what the
click meant without the squares. Each action by name, whether from a key, a
menu or a button. And what came of them: each step done, undone or redone,
with what it touched, and each message the tools put in the status line.

Written a line at a time and flushed, so a crash leaves the log whole up to
its last event. ``danu.ui.replay`` plays one back into a window.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, Qt

from . import mercator as m
from .tools import PICK_PX, SNAP_PX  # what a press would snap to, as the tools find it

KEEP = 20                      # runs whose logs are kept

_MOUSE = {QEvent.Type.MouseButtonPress: 'press', QEvent.Type.MouseButtonRelease: 'release',
          QEvent.Type.MouseButtonDblClick: 'double', QEvent.Type.MouseMove: 'move'}


def _buttons(b) -> int:
    return int(b.value) if hasattr(b, 'value') else int(b)


class UsageLog(QObject):
    def __init__(self, window, directory: Path, parent=None):
        super().__init__(parent)
        self.window = window
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._prune()
        self.path = self.directory / time.strftime(f'%Y%m%d-%H%M%S-{os.getpid()}.jsonl')
        self._f = open(self.path, 'a', encoding='utf-8', buffering=1)
        self._hover: dict | None = None               # the cursor's last place, written before the next input
        self._t0 = time.monotonic()
        self.write('start', pid=os.getpid())
        # held by name: the filter must not ask the view for anything, since
        # Qt still sends its viewport events as a window comes down and by
        # then the view can be gone - see danu.ui.legend
        self._view, self._viewport = window.map, window.map.viewport()
        self._viewport.installEventFilter(self)
        self._view.installEventFilter(self)           # the keys go to the view, not its viewport
        ed = window.editor
        ed.message.connect(lambda text: self.write('said', text=text))
        window.loader.finished.connect(self._opened)

    # ------------------------------------------------------------ writing
    def write(self, kind: str, **fields) -> None:
        if self._f is None:
            return
        if kind not in ('said', 'did', 'undid', 'redid', 'hover') and self._hover is not None:
            hover, self._hover = self._hover, None
            self.write('hover', **hover)
        rec = {'t': round(time.monotonic() - self._t0, 3), 'kind': kind, **fields}
        try:
            # default=str: a value json does not know is written as text, not
            # the end of the log
            self._f.write(json.dumps(rec, default=str) + '\n')
        except OSError:
            self._f = None                            # a full disk stops the log, not the editor

    def close(self) -> None:
        if self._f is not None:
            self.write('end')
            self._f.close()
            self._f = None
        for w in (self._viewport, self._view):
            w.removeEventFilter(self)

    def _prune(self) -> None:
        logs = sorted(self.directory.glob('*.jsonl'))
        for p in logs[:max(0, len(logs) - (KEEP - 1))]:
            p.unlink(missing_ok=True)

    # ------------------------------------------------------------- events
    def _opened(self, ws) -> None:
        w = self.window
        self.write('open', zone=str(w.zone_dir), centre=str(ws.centre), size=ws.size,
                   files={str(sq.name): [str(sq.path), *(sq.stamp or ())] for sq in ws.squares.values()
                          if sq.path is not None})

    def action(self, name: str) -> None:
        self.write('action', name=name, **self._state())

    def stepped(self, verb: str, step) -> None:
        """A step done, undone or redone: what it was and what it touched."""
        out = []
        for sq, cmd in step:
            n, wy, r = cmd.touched(sq)
            out.append({'square': str(sq.name), 'what': cmd.describe(),
                        'nodes': len(n), 'ways': sorted(wy)[:50], 'relations': sorted(r)})
        self.write(verb, step=out)

    def _state(self) -> dict:
        w = self.window
        lon, lat = w.map.center_lonlat()
        return {'tool': w.editor.tool, 'zoom': w.map.zoom, 'centre': [lon, lat],
                'elevation': w.elevation.value}

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind not in _MOUSE and kind not in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
            return False
        view = self._view
        if obj is self._viewport and kind in _MOUSE:
            if kind == QEvent.Type.MouseMove and event.buttons() == Qt.MouseButton.NoButton:
                p = view.mapToScene(event.position().toPoint())
                self._hover = {'at': list(m.scene_to_lonlat(p.x(), p.y())), 'button': 0, 'buttons': 0,
                               'mods': _buttons(event.modifiers()), **self._state()}
                return False
            self._mouse(_MOUSE[kind], event)
        elif obj is self._viewport and kind == QEvent.Type.Wheel:
            p = view.mapToScene(event.position().toPoint())
            d = event.angleDelta()
            self.write('wheel', at=list(m.scene_to_lonlat(p.x(), p.y())), delta=d.y() or d.x(),
                       mods=_buttons(event.modifiers()), **self._state())
        elif obj is view and kind == QEvent.Type.KeyPress:
            self.write('key', key=int(event.key()), mods=_buttons(event.modifiers()), text=event.text(),
                       **self._state())
        return False

    def _mouse(self, what: str, event) -> None:
        view = self._view
        pos = event.position()
        p = view.mapToScene(pos.toPoint())
        rec = {'at': list(m.scene_to_lonlat(p.x(), p.y())), 'button': _buttons(event.button()),
               'buttons': _buttons(event.buttons()), 'mods': _buttons(event.modifiers()), **self._state()}
        if what == 'press' and self.window.working_set is not None:
            rec['snap'] = self._snap(p)
        self.write(what, **rec)

    def _snap(self, p: QPointF) -> dict:
        """What a press here could mean, as the tools would find it."""
        layer, zoom = self.window.contours, self.window.map.zoom
        px = 1.0 / m.scale_for_zoom(zoom)
        out = {}
        node = layer.pick_node(p.x(), p.y(), SNAP_PX * px)
        if node is not None:
            sq, nid, d = node
            out['node'] = {'square': str(sq.name), 'id': nid, 'px': round(d / px, 1),
                           'ways': sorted(w.id for w in sq.ways.values() if nid in w.refs)[:8]}
        way = layer.pick(p.x(), p.y(), PICK_PX * px)
        if way is not None:
            sq, w, d, seg = way
            out['way'] = {'square': str(sq.name), 'id': w.id, 'ele': w.tags.get('ele'), 'px': round(d / px, 1),
                          'segment': seg, 'nodes': len(w.refs)}
        spot = layer.pick_spot(p.x(), p.y(), SNAP_PX * px, zoom)
        if spot is not None:
            sq, nid, _ = spot
            out['spot'] = {'square': str(sq.name), 'id': nid}
        return out
