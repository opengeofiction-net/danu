"""Replay a usage log (H4c) into a window, and say where it does otherwise.

    python -m danu.ui.replay ~/.local/share/danu/usage/20261010-143200-4242.jsonl

Opens the set the log opened, then gives the map the same presses, moves,
releases, wheel turns and keys at the same places on the ground, with the
view at the zoom and centre the mapper had and the active elevation theirs;
and the same actions by name. After each, what the tools did - the steps and
what they said - is held against what the log says they did, and the first
place they part is reported: the bug, reproduced, or the place it stops
reproducing.

A log replays against the squares as they were: the files it opened are
compared with what it recorded of them, and a difference is said before
anything is played. Nothing is saved - file actions and the imports, which
reach the network, are passed over and said - so the squares are as the log
left them only in the window.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ..core.square import SquareName
from . import mercator as m

INPUT = {'press', 'release', 'double', 'move', 'hover', 'wheel', 'key', 'action', 'tool', 'magnify', 'open'}
OUTCOME = {'did', 'undid', 'redid', 'said'}
SKIPPED = ('file.', 'edit.import_')            # dialogs and the network: not replayed

_TYPE = {'press': QEvent.Type.MouseButtonPress, 'release': QEvent.Type.MouseButtonRelease,
         'double': QEvent.Type.MouseButtonDblClick, 'move': QEvent.Type.MouseMove,
         'hover': QEvent.Type.MouseMove}


def records(path: Path) -> list[dict]:
    """The log's records. A line that does not read - the last, cut short by
    the crash being looked into, as a rule - is passed over."""
    out: list[dict] = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def outcome(rec: dict):
    """What a logged outcome says, as the replay compares it."""
    if rec['kind'] == 'said':
        return ('said', rec['text'])
    return (rec['kind'], tuple(s['what'] for s in rec['step']))


@dataclass
class Report:
    played: int = 0
    skipped: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    parted: dict | None = None                        # the first input whose outcome differed

    def describe(self) -> str:
        lines = [f'played {self.played} events']
        lines += [f'files changed since the log: {s}' for s in self.stale]
        lines += [f'not replayed: {s}' for s in self.skipped]
        if self.parted:
            p = self.parted
            lines.append(f'parted at t={p["t"]}s, {p["kind"]}: the log says {p["logged"]}, the replay did {p["got"]}')
        else:
            lines.append('every outcome as the log has it')
        return '\n'.join(lines)


class Replayer:
    def __init__(self, win, recs: list[dict], wait=None):
        self.win, self.recs = win, recs
        # how to wait for a set to be read: the event loop, until the loader says
        self.wait = wait or self._wait
        self._got: list = []
        win.editor.stepped.connect(lambda verb, step: self._got.append(
            (verb, tuple(cmd.describe() for _, cmd in step))))
        win.editor.message.connect(lambda text: self._got.append(('said', text)))

    @staticmethod
    def _wait(win) -> None:
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        win.loader.finished.connect(loop.quit)
        win.loader.failed.connect(loop.quit)
        loop.exec()

    def run(self, stop_at_parting: bool = True) -> Report:
        report = Report()
        recs = self.recs
        i = 0
        while i < len(recs):
            rec = recs[i]
            j = i + 1
            while j < len(recs) and recs[j]['kind'] in OUTCOME:
                j += 1
            if rec['kind'] not in INPUT:
                i = j
                continue
            want = [outcome(r) for r in recs[i + 1:j]]
            self._got = []
            if not self._play(rec, report):
                i = j
                continue
            report.played += 1
            if self._got != want and report.parted is None:
                report.parted = {'t': rec['t'], 'kind': rec['kind'], 'logged': want, 'got': list(self._got)}
                if stop_at_parting:
                    break
            i = j
        return report

    # -------------------------------------------------------------- play
    def _play(self, rec: dict, report: Report) -> bool:
        win, kind = self.win, rec['kind']
        if kind == 'open':
            for name, (path, *stamp) in rec.get('files', {}).items():
                p = Path(path)
                st = p.stat() if p.exists() else None
                if st is None or (stamp and [st.st_size, st.st_mtime_ns] != stamp):
                    report.stale.append(name)
            win.prompt_on_close = False
            if win.open_working_set(Path(rec['zone']), SquareName.parse(rec['centre']), int(rec['size'])):
                self.wait(win)
            return True
        if kind == 'tool':
            win.editor.set_tool(rec['name'])
            return True
        if kind == 'magnify':
            win.edit_actions['view.magnify'].setChecked(bool(rec['on']))
            return True
        if kind == 'action' and rec['name'].startswith(SKIPPED):
            report.skipped.append(rec['name'])
            return False
        self._as_then(rec)
        if kind == 'action':
            name = rec['name']
            for table in (win.file_actions, win.edit_actions, win.elevation_actions, win.surface_actions):
                if name in table:
                    table[name].trigger()
                    return True
            report.skipped.append(name)
            return False
        view = win.map
        x, y = m.lonlat_to_scene(*rec['at']) if 'at' in rec else (0.0, 0.0)
        pos = view.viewportTransform().map(QPointF(x, y))
        mods = Qt.KeyboardModifier(rec.get('mods', 0))
        if kind in _TYPE:
            ev = QMouseEvent(_TYPE[kind], pos, view.viewport().mapToGlobal(pos), Qt.MouseButton(rec['button']),
                             Qt.MouseButton(rec['buttons']), mods)
            QApplication.sendEvent(view.viewport(), ev)
        elif kind == 'wheel':
            ev = QWheelEvent(pos, view.viewport().mapToGlobal(pos), QPoint(), QPoint(0, int(rec['delta'])),
                             Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(view.viewport(), ev)
        elif kind == 'key':
            QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, int(rec['key']), mods, rec.get('text', '')))
        return True

    def _as_then(self, rec: dict) -> None:
        """The view and the elevation as the mapper had them: a snap radius
        is in pixels, so the zoom decides what a press reaches."""
        win = self.win
        if 'zoom' in rec and win.map.zoom != rec['zoom']:
            win.map.set_zoom(int(rec['zoom']))
        if 'centre' in rec:
            lon, lat = win.map.center_lonlat()
            if abs(lon - rec['centre'][0]) > 1e-9 or abs(lat - rec['centre'][1]) > 1e-9:
                win.map.center_on_lonlat(*rec['centre'])
        if rec.get('elevation') is not None and win.elevation.value != rec['elevation']:
            win.elevation.set(float(rec['elevation']))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='danu-replay', description='replay a Danu usage log into a window')
    ap.add_argument('log', type=Path)
    ap.add_argument('--on', action='store_true', help='carry on past the first place the replay parts from the log')
    args = ap.parse_args(argv)
    from .app import APP_NAME, MainWindow, user_cache_dir
    from .config import load_layers
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    win = MainWindow(load_layers(), cache_dir=user_cache_dir() / 'tiles')
    win.show()
    report = Replayer(win, records(args.log)).run(stop_at_parting=not args.on)
    print(report.describe())
    win.statusBar().showMessage(report.describe().splitlines()[-1])
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
