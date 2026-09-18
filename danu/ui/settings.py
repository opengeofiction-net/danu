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
        return int(self.q.value('squares/size', 3))

    @size.setter
    def size(self, n: int):
        self.q.setValue('squares/size', int(n))

    # ------------------------------------------------------------ recent
    def recent(self) -> list[tuple[Path, SquareName, int]]:
        out = []
        for entry in self.q.value('recent/squares', []) or []:
            try:
                d, name, size = entry.split('|')
                out.append((Path(d), SquareName.parse(name), int(size)))
            except (ValueError, AttributeError):
                continue
        return out

    def remember(self, zone_dir: Path, name: SquareName, size: int):
        entry = f'{zone_dir}|{name}|{size}'
        items = [e for e in (self.q.value('recent/squares', []) or []) if e != entry]
        self.q.setValue('recent/squares', [entry] + items[:RECENT_MAX - 1])
        self.q.sync()
