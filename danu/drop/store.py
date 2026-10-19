"""The squares on the server, as the data drop (#190) reads and changes them.

Two copies, as ``docs/data-drop.md`` sets out. The working copy,
``<BASE>/osm-squares/<zone>/``, is the one the build reads and the one
truth; a square's version is the SHA-256 of its bytes there. The published
copy, ``<PUBROOT>/osm-squares/<zone>/``, is what ``data.opengeofiction.net``
serves; every change made here is made to it at once as well, with the same
bytes and the same time, so danu-build's nightly copy - which copies what is
newer - finds nothing to do for it.

A change is checked against the version it was made from and made under one
lock, so two workers can't both pass the check. Every file is written under
a name the build doesn't read - a dot first, no ``.osm.xz`` last - and
renamed into place. The file a change replaces is kept, under
``<BASE>/drop/kept/``: outside ``osm-squares/``, which the build searches all
the way down. Each change is a line of ``<BASE>/drop/log.jsonl``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import lzma
import os
import shutil
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..core.square import SquareName, label_of, list_squares
from ..report.zones_to_multimap import classify_square

XZ_MAGIC = b'\xfd7zXZ\x00'


class Refused(Exception):
    """A change not made: the HTTP status to answer with, and why."""

    def __init__(self, status: int, why: str, **extra):
        super().__init__(why)
        self.status, self.why, self.extra = status, why, extra


@dataclass(frozen=True)
class Held:
    """A square as the working copy holds it."""
    square: SquareName
    path: Path
    size: int
    mtime: float
    sha256: str

    kind: str = ''                  # 'contour', 'coastline' or 'blank': the report's classify_square

    @property
    def label(self) -> str:
        return label_of(self.path)

    def describe(self) -> dict:
        return {'square': self.square.name, 'file': self.path.name, 'label': self.label,
                'size': self.size, 'mtime': self.mtime, 'sha256': self.sha256, 'class': self.kind}


def check_square_file(path: Path) -> None:
    """Refuses (422) what isn't a square file: xz, holding OSM XML. Streamed,
    so the largest square, 271 MB of XML, is read in bounded memory."""
    with open(path, 'rb') as f:
        if f.read(len(XZ_MAGIC)) != XZ_MAGIC:
            raise Refused(422, 'not an .osm.xz file: it is not xz')
    try:
        with lzma.open(path) as f:
            events = ET.iterparse(f, events=('start', 'end'))
            _, root = next(events)
            if root.tag != 'osm':
                raise Refused(422, f'not an OSM file: its root is <{root.tag}>')
            for event, elem in events:
                if event == 'end' and elem is not root:
                    elem.clear()
                    root.clear()
    except (lzma.LZMAError, EOFError) as e:
        raise Refused(422, f'not a whole .osm.xz file: {e}') from e
    except ET.ParseError as e:
        raise Refused(422, f'not well-formed OSM XML: {e}') from e
    except StopIteration as e:
        raise Refused(422, 'an empty file') from e


class Store:
    def __init__(self, base: str | Path, pubroot: str | Path | None):
        self.base = Path(base)
        self.squares = self.base / 'osm-squares'
        self.published = Path(pubroot) / 'osm-squares' if pubroot else None
        self.drop = self.base / 'drop'
        self._hashes: dict[str, tuple[int, int, str]] = {}    # path -> size, time, hash
        self._kinds: dict[str, str] = {}                      # hash -> the report's class

    # ---------------------------------------------------------------- reading

    def _sha256(self, path: Path, st: os.stat_result) -> str:
        hit = self._hashes.get(str(path))
        if hit and hit[:2] == (st.st_size, st.st_mtime_ns):
            return hit[2]
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        self._hashes[str(path)] = (st.st_size, st.st_mtime_ns, h.hexdigest())
        return h.hexdigest()

    def zone_dir(self, zone: str) -> Path:
        return self.squares / zone

    def listing(self, zone: str) -> list[Held]:
        d = self.zone_dir(zone)
        if not d.is_dir():
            return []
        try:
            found = list_squares(d, compressed_only=True)
        except ValueError as e:              # two files for one square: an admin's to sort
            raise Refused(409, str(e)) from e
        out = []
        for square, path in sorted(found.items()):
            st = path.stat()
            sha = self._sha256(path, st)
            if sha not in self._kinds:
                self._kinds[sha] = classify_square(path)
            out.append(Held(square, path, st.st_size, st.st_mtime, sha, self._kinds[sha]))
        return out

    def held(self, zone: str, square: SquareName) -> Held | None:
        return next((h for h in self.listing(zone) if h.square == square), None)

    # ---------------------------------------------------------------- changing

    @contextmanager
    def locked(self):
        self.drop.mkdir(parents=True, exist_ok=True)
        with open(self.drop / 'lock', 'w') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def spool(self, zone: str, body, length: int) -> Path:
        """The upload's bytes, to a file in the zone's directory the build
        doesn't read. The caller removes it if it isn't put in place."""
        d = self.zone_dir(zone)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f'.drop-{os.getpid()}-{time.monotonic_ns()}.part'
        left = length
        with open(tmp, 'wb') as f:
            while left > 0:
                chunk = body.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            tmp.unlink()
            raise Refused(400, 'the upload ended early')
        return tmp

    @staticmethod
    def check_version(current: Held | None, if_match: str | None, if_none_match: str | None) -> None:
        """The change was made from what is held now: If-Match its hash, or
        for a new square If-None-Match: *."""
        etag = current and f'"{current.sha256}"'
        if if_none_match is not None:
            if if_none_match.strip() != '*':
                raise Refused(400, 'If-None-Match takes only *')
            if current is not None:
                raise Refused(412, 'the square exists: send If-Match with its version', etag=etag)
            return
        if if_match is None:
            raise Refused(428, 'say which version this was made from: If-Match, or If-None-Match: * for a new square')
        if current is None:
            raise Refused(412, 'the square is not held: send If-None-Match: * for a new square')
        if if_match.strip() not in (etag, current.sha256, f'W/{etag}'):
            raise Refused(412, 'the square has changed since it was read', etag=etag)

    def _keep(self, zone: str, held: Held) -> str:
        """A copy of the file a change replaces, for an admin to recover."""
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        dest = self.drop / 'kept' / zone / f'{held.path.name}.{stamp}.{held.sha256[:12]}'
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(held.path, dest)
        return str(dest.relative_to(self.base))

    def _place(self, src: Path, dest: Path, move: bool) -> None:
        tmp = dest.parent / f'.drop-{os.getpid()}-{time.monotonic_ns()}.part'
        if move:
            os.replace(src, tmp)
        else:
            shutil.copy2(src, tmp)
        os.replace(tmp, dest)

    def _publish(self, zone: str, old: Held | None, new: Path | None) -> None:
        """The published copy changed as the working copy was: the new file
        in, by copy, its time kept; the old one out if it was renamed."""
        if self.published is None:
            return
        d = self.published / zone
        d.mkdir(parents=True, exist_ok=True)
        if new is not None:
            self._place(new, d / new.name, move=False)
        if old is not None and (new is None or old.path.name != new.name):
            (d / old.path.name).unlink(missing_ok=True)

    def _log(self, **entry) -> None:
        self.drop.mkdir(parents=True, exist_ok=True)
        entry = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **entry}
        with open(self.drop / 'log.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

    def put(self, zone: str, square: SquareName, spooled: Path, label: str | None,
            if_match: str | None, if_none_match: str | None, user: str) -> Held:
        """The spooled file in place as the square. ``label`` None keeps the
        one held; '' takes it away."""
        try:
            with self.locked():
                current = self.held(zone, square)
                self.check_version(current, if_match, if_none_match)
                if label is None:
                    label = current.label if current else ''
                name = square.filename(label)
                dest = self.zone_dir(zone) / name
                kept = self._keep(zone, current) if current else None
                # a renamed square: the old file goes first, so the build never
                # finds two files for it - at worst none, for a moment
                if current is not None and current.path.name != name:
                    current.path.unlink()
                self._place(spooled, dest, move=True)
                st = dest.stat()
                done = Held(square, dest, st.st_size, st.st_mtime, self._sha256(dest, st))
                # logged before publishing: a published copy that fails to
                # write is put right by the nightly copy, the change still told
                self._log(user=user, action='put', zone=zone, square=square.name, file=name,
                          sha256=done.sha256, was=current and current.sha256, kept=kept)
                self._publish(zone, current, dest)
                return done
        finally:
            spooled.unlink(missing_ok=True)

    def rename(self, zone: str, square: SquareName, label: str, if_match: str | None, user: str) -> Held:
        with self.locked():
            current = self.held(zone, square)
            if current is None:
                raise Refused(404, f'{square} is not held in {zone}')
            self.check_version(current, if_match, None)
            name = square.filename(label)
            if name == current.path.name:
                return current
            dest = self.zone_dir(zone) / name
            os.replace(current.path, dest)
            st = dest.stat()
            done = Held(square, dest, st.st_size, st.st_mtime, current.sha256)
            self._log(user=user, action='rename', zone=zone, square=square.name, file=name,
                      was_file=current.path.name, sha256=current.sha256)
            self._publish(zone, current, dest)
            return done

    def delete(self, zone: str, square: SquareName, if_match: str | None, user: str) -> None:
        with self.locked():
            current = self.held(zone, square)
            if current is None:
                raise Refused(404, f'{square} is not held in {zone}')
            self.check_version(current, if_match, None)
            kept = self._keep(zone, current)
            current.path.unlink()
            self._log(user=user, action='delete', zone=zone, square=square.name,
                      file=current.path.name, sha256=current.sha256, kept=kept)
            self._publish(zone, current, None)

    def retire(self, zone: str, held: Held, user: str, why: str) -> str:
        """A square out of the build: to ``drop/kept/`` from both copies,
        logged. A blank or coastline-only square a zone change leaves in no
        zone, which the build would still build from its old directory."""
        kept = self._keep(zone, held)
        held.path.unlink()
        self._hashes.pop(str(held.path), None)
        self._log(user=user, action='retire', zone=zone, square=held.square.name, file=held.path.name,
                  sha256=held.sha256, kept=kept, why=why)
        self._publish(zone, held, None)
        return kept

    def move(self, held: Held, from_zone: str, to_zone: str, user: str) -> None:
        """A square into another zone, both copies, its time kept."""
        d = self.zone_dir(to_zone)
        d.mkdir(parents=True, exist_ok=True)
        os.replace(held.path, d / held.path.name)
        self._hashes.pop(str(held.path), None)     # its new path hashes it again, once
        if self.published is not None:
            src, dst = self.published / from_zone / held.path.name, self.published / to_zone
            dst.mkdir(parents=True, exist_ok=True)
            if src.exists():
                os.replace(src, dst / held.path.name)
        self._log(user=user, action='move', zone=to_zone, was_zone=from_zone, square=held.square.name,
                  file=held.path.name, sha256=held.sha256)

    def log_admin(self, user: str, action: str, **what) -> None:
        self._log(user=user, action=action, **what)
