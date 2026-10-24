"""Where the autosave keeps a square's change - H4.

Under ``~/.local/share/danu/autosave/``, never beside the mapper's files: a
directory a zone, named for the zone and a hash of its path, holding per
dirty square its change as an ``.osc`` and a manifest - the square, the file
the change is against as it was read (size and modified time), when it was
written, and the order of what ends the square (see ``danu.core.change``).

Written so that a kill at any moment leaves a whole pair. The change goes
under a name of its own, ``N20E086.7.osc``, then the manifest naming it is
moved into place over the last one, and only then is the old change removed:
the manifest on disk always names a change that is all there.

A recovery reads the square from its file and puts the change on it, and
refuses when that file is not the one the change was taken against.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .change import Change, change_text, read_change
from .square import Square, SquareName, list_squares

VERSION = 1


def zone_key(zone_dir: str | os.PathLike) -> str:
    """A zone's directory name here: readable, and its path's hash so two
    zones of one name in two places do not share one."""
    p = Path(zone_dir).resolve()
    return f'{p.name}-{hashlib.sha1(str(p).encode()).hexdigest()[:8]}'


def _replace(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class Entry:
    """One square's autosave: its manifest, read."""
    manifest: Path
    data: dict
    # the change, once read: a recovery reads it before its dialog shows, so
    # nothing done while the mapper chooses can take the file from under it
    _change: Change | None = field(default=None, compare=False, repr=False)

    @property
    def square(self) -> SquareName:
        return SquareName.parse(self.data['square'])

    @property
    def zone(self) -> Path:
        return Path(self.data['zone'])

    @property
    def file(self) -> Path | None:
        return Path(self.data['file']) if self.data.get('file') else None

    @property
    def change_path(self) -> Path:
        return self.manifest.parent / self.data['change']

    @property
    def written(self) -> float:
        return float(self.data['written'])

    def change(self) -> Change:
        if self._change is None:
            self._change = read_change(self.change_path.read_text(encoding='utf-8'),
                                       {k: list(v) for k, v in self.data.get('tail', {}).items()})
        return self._change

    def refused(self) -> str | None:
        """Why this change cannot go back onto its square, or None: the file
        it was taken against is not the file there now."""
        f = self.file
        if f is None:
            there = list_squares(self.zone).get(self.square)
            return f'{there.name} has been made since' if there is not None else None
        if not f.exists():
            return f'{f.name} is not there any more'
        st = f.stat()
        if [st.st_size, st.st_mtime_ns] != self.data.get('stamp'):
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))
            return f'{f.name} has changed since, at {when}'
        return None


class Store:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def _dir(self, zone_dir) -> Path:
        return self.root / zone_key(zone_dir)

    def write(self, zone_dir, square: Square, change: Change) -> Entry:
        """The square's change, replacing the one held for it."""
        d = self._dir(zone_dir)
        d.mkdir(parents=True, exist_ok=True)
        name = square.name.name
        manifest = d / f'{name}.json'
        old = self._read(manifest)
        seq = (old.data.get('seq', 0) + 1) if old else 1
        osc = d / f'{name}.{seq}.osc'
        _replace(osc, change_text(change))
        data = {'version': VERSION, 'zone': str(Path(zone_dir).resolve()), 'square': name,
                'file': str(square.path.resolve()) if square.path else None,
                'stamp': list(square.stamp) if square.stamp else None,
                'written': time.time(), 'seq': seq, 'change': osc.name,
                'counts': change.counts(), 'tail': change.tail}
        _replace(manifest, json.dumps(data))
        if old and old.change_path != osc:
            old.change_path.unlink(missing_ok=True)
        return Entry(manifest, data)

    def remove(self, zone_dir, name: SquareName) -> None:
        """The square's autosave gone - saved, or its edits thrown away."""
        manifest = self._dir(zone_dir) / f'{name.name}.json'
        entry = self._read(manifest)
        manifest.unlink(missing_ok=True)
        if entry is not None:
            entry.change_path.unlink(missing_ok=True)

    def set_aside(self, entry: Entry) -> Path:
        """An autosave not recovered, moved out of the way rather than
        deleted: ``set-aside/`` beside it, the change still an ``.osc`` JOSM
        can open. Returns where the change went."""
        aside = entry.manifest.parent / 'set-aside'
        aside.mkdir(exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(entry.written))
        to = aside / f'{entry.square.name}-{stamp}.osc'
        if entry.change_path.exists():
            os.replace(entry.change_path, to)
        os.replace(entry.manifest, aside / f'{entry.square.name}-{stamp}.json')
        return to

    def held(self, name: SquareName, zone_dir) -> Entry | None:
        return self._read(self._dir(zone_dir) / f'{name.name}.json')

    def entries(self, zone_dir=None) -> list[Entry]:
        """Every autosave held, or a zone's, newest first."""
        dirs = [self._dir(zone_dir)] if zone_dir is not None else (
            sorted(p for p in self.root.iterdir() if p.is_dir()) if self.root.exists() else [])
        out = [e for d in dirs if d.exists() for m in sorted(d.glob('*.json'))
               if (e := self._read(m)) is not None]
        return sorted(out, key=lambda e: -e.written)

    @staticmethod
    def _read(manifest: Path) -> Entry | None:
        try:
            data = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if data.get('version') != VERSION or not (manifest.parent / data.get('change', '')).is_file():
            return None
        return Entry(manifest, data)
