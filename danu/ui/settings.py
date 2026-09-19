"""What the editor remembers between runs: where the squares are, what was
open last. QSettings in INI form at ~/.config/danu/danu.ini - the directory
the spec names, beside layers.toml. Nothing here is required to exist."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from ..core.square import SquareName

RECENT_MAX = 8


class Settings:
    def __init__(self, path: Path | None = None):
        if path is None:
            self.q = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, 'danu', 'danu')
        else:
            self.q = QSettings(str(path), QSettings.Format.IniFormat)

    @property
    def file(self) -> Path:
        return Path(self.q.fileName())

    # ----------------------------------------------------------- squares
    @property
    def squares_root(self) -> Path | None:
        v = self.q.value('squares/root', '')
        return Path(v) if v else None

    @squares_root.setter
    def squares_root(self, path: Path | None):
        self.q.setValue('squares/root', str(path) if path else '')

    @property
    def size(self) -> int:
        try:
            n = int(self.q.value('squares/size', 3))
        except (TypeError, ValueError):
            return 3
        return n if n in (1, 3, 5) else 3

    @size.setter
    def size(self, n: int):
        self.q.setValue('squares/size', int(n))

    # ------------------------------------------------------------ recent
    # One string, entries separated by newlines, rather than a QSettings list.
    # Qt's INI backend has been known to hand a list of one back as a plain
    # string, which a loop would walk character by character. Measured on
    # PySide6 6.11 it does not - a one-item list came back a list - but the
    # encoding here is under our control on every Qt and costs nothing, so it
    # does not lean on that
    def _entries(self) -> list[str]:
        raw = self.q.value('recent/squares', '')
        return [e for e in str(raw or '').split('\n') if e]

    def recent(self) -> list[tuple[Path, SquareName, int]]:
        out = []
        for entry in self._entries():
            try:
                d, name, size = entry.split('|')
                out.append((Path(d), SquareName.parse(name), int(size)))
            except ValueError:
                continue
        return out

    def remember(self, zone_dir: Path, name: SquareName, size: int):
        entry = f'{zone_dir}|{name}|{size}'
        items = [e for e in self._entries() if e != entry]
        self.q.setValue('recent/squares', '\n'.join([entry] + items[:RECENT_MAX - 1]))
        self.q.sync()
