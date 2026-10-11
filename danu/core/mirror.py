"""A zone's squares mirrored from the server (H6g): what
``data.opengeofiction.net/dem/osm-squares/<zone>/`` holds, copied to
``<root>/<zone>/``, which is where the open dialog looks.

Two phases, so the one question it has to ask is asked on the UI thread:

1. ``fetch`` (a worker): the zone's index read, and every file the server
   has that the copy here does not match fetched into the zone's directory
   under a temporary name. Nothing in place is touched.
2. ``settle`` (the UI thread, with the answers): the fetched files put in
   place - all of them, but where a file here has been changed since it was
   last mirrored, only if the mapper says so.

**Changed here** is told by a manifest beside the files, ``.danu-mirror.json``:
for each file, the size and SHA-256 it had when it was mirrored, and the
server's size and date then. A file that still hashes as the manifest says
was not touched here, and is replaced by a newer one without asking; one
that does not, or that the manifest does not know, was - and a file the
server has the same bytes of is no question at all. A file the server no
longer has is left, and said. Nothing here is Qt's.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

URL = 'https://data.opengeofiction.net/dem/osm-squares'
MANIFEST = '.danu-mirror.json'
PART = '.part-'                       # a fetched file's prefix until it is put in place
TIMEOUT_S = 60

# nginx's autoindex: a link, then the date and the size in bytes
_ROW = re.compile(r'<a href="([^"?/]+)">[^<]*</a>\s+(\S+ \S+)\s+(\d+|-)')
_DIR = re.compile(r'<a href="([^"?/.][^"?/]*)/">')


def zones(html: str) -> list[str]:
    """The zones a directory index lists: its subdirectories."""
    return sorted({urllib.parse.unquote(m.group(1)) for m in _DIR.finditer(html)})


def files(html: str) -> dict[str, tuple[int, str]]:
    """The files a zone's index lists, as name: (size, date) - the squares,
    ``.osm.xz``, and nothing else."""
    out = {}
    for m in _ROW.finditer(html):
        name = urllib.parse.unquote(m.group(1))
        if name.endswith('.osm.xz') and m.group(3) != '-':
            out[name] = (int(m.group(3)), m.group(2))
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(zone_dir: Path) -> dict:
    try:
        data = json.loads((zone_dir / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(zone_dir: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=zone_dir, prefix='.manifest-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, zone_dir / MANIFEST)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class Fetched:
    """What the worker found and fetched for a zone."""
    zone: str
    zone_dir: Path
    server: dict[str, tuple[int, str]]            # name: (size, date), as listed
    new: dict[str, Path] = field(default_factory=dict)        # not here: fetched, to put in place
    updated: dict[str, Path] = field(default_factory=dict)    # unchanged here, newer there
    changed: dict[str, Path] = field(default_factory=dict)    # changed here, and different there: asked
    current: list[str] = field(default_factory=list)          # here as there
    gone: list[str] = field(default_factory=list)             # mirrored before, no longer there
    hashes: dict[str, str] = field(default_factory=dict)      # name: sha256 of what was fetched or matched

    def discard(self) -> None:
        """The fetched files not put in place, deleted."""
        for part in (*self.new.values(), *self.updated.values(), *self.changed.values()):
            part.unlink(missing_ok=True)


def _get(url: str, opener, timeout: float) -> bytes:
    with opener(urllib.request.Request(url, headers={'User-Agent': 'danu'}), timeout=timeout) as r:
        return r.read()


def list_zones(base: str = URL, opener=urllib.request.urlopen, timeout: float = TIMEOUT_S) -> list[str]:
    return zones(_get(f'{base.rstrip("/")}/', opener, timeout).decode('utf-8', 'replace'))


def fetch(zone: str, root: Path, base: str = URL, opener=urllib.request.urlopen, report=None,
          timeout: float = TIMEOUT_S) -> Fetched:
    """Phase one, on a worker: the zone's index, and what differs fetched
    beside the copy here as ``.part-`` files. ``report((done, of, name))``
    as it goes."""
    zone_url = f'{base.rstrip("/")}/{urllib.parse.quote(zone)}/'
    server = files(_get(zone_url, opener, timeout).decode('utf-8', 'replace'))
    zone_dir = root / zone
    zone_dir.mkdir(parents=True, exist_ok=True)
    for stale in (*zone_dir.glob(PART + '*'), *zone_dir.glob('.manifest-*')):    # a mirror killed part way
        stale.unlink(missing_ok=True)
    manifest = read_manifest(zone_dir)
    out = Fetched(zone, zone_dir, server)
    try:
        _fetch_files(out, zone_url, manifest, opener, report, timeout)
    except BaseException:
        out.discard()
        raise
    # only what a mirror put here: a square of the mapper's own is not the server's to have dropped
    out.gone = sorted(p.name for p in zone_dir.glob('*.osm.xz') if p.name not in server and p.name in manifest)
    if report is not None:
        report((len(server), len(server), ''))
    return out


def _fetch_files(out: Fetched, zone_url: str, manifest: dict, opener, report, timeout: float) -> None:
    server, zone_dir = out.server, out.zone_dir
    for k, (name, (size, date)) in enumerate(sorted(server.items())):
        if report is not None:
            report((k, len(server), name))
        here = zone_dir / name
        known = manifest.get(name) or {}
        mine = _hash_here(here, known)
        untouched = mine is not None and mine == known.get('sha256')
        if untouched and known.get('server') == [size, date]:
            out.current.append(name)                       # as it was mirrored, and the server's the same
            out.hashes[name] = mine
            continue
        part = _download(zone_url + urllib.parse.quote(name), zone_dir, opener, timeout)
        theirs = sha256(part)
        out.hashes[name] = theirs
        if mine is None:
            out.new[name] = part
        elif theirs == mine:
            part.unlink()                                  # the same bytes: nothing to put in place
            out.current.append(name)
        elif untouched:
            out.updated[name] = part
        else:
            out.changed[name] = part


def _stat(path: Path) -> list[int]:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


def _hash_here(here: Path, known: dict) -> str | None:
    """The square here's SHA-256 - taken as the manifest's when its size
    and time are as the manifest has them, so a zone checked again is not
    read again square by square."""
    if not here.exists():
        return None
    if known.get('sha256') and known.get('stat') == _stat(here):
        return known['sha256']
    return sha256(here)


def _download(url: str, into: Path, opener, timeout: float) -> Path:
    # opened as any file is, so it takes the umask's permissions - mkstemp's
    # are the owner's alone, and a square put in place kept them
    tmp = into / f'{PART}{secrets.token_hex(8)}'
    try:
        with open(tmp, 'xb') as f, opener(urllib.request.Request(url, headers={'User-Agent': 'danu'}),
                                          timeout=timeout) as r:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Path(tmp)


def settle(f: Fetched, overwrite: set[str], keep: set[str] = frozenset()) -> dict[str, list[str]]:
    """Phase two: the fetched files put in place - the new and the updated,
    and of the changed only those in ``overwrite``, the rest ``kept``;
    ``keep`` ``held`` back whatever they are (a square open with unsaved
    edits). The manifest records each file put in place or found the same,
    with its size and time here. Answers what was done, by kind."""
    manifest = read_manifest(f.zone_dir)
    done: dict[str, list[str]] = {'new': [], 'updated': [], 'overwritten': [], 'kept': [], 'held': [],
                                  'current': [], 'gone': list(f.gone)}
    for kind, parts in (('new', f.new), ('updated', f.updated), ('overwritten', f.changed)):
        for name, part in parts.items():
            if name in keep or (kind == 'overwritten' and name not in overwrite):
                part.unlink(missing_ok=True)
                done['held' if name in keep else 'kept'].append(name)
                continue
            os.replace(part, f.zone_dir / name)
            manifest[name] = _entry(f, name)
            done[kind].append(name)
    for name in f.current:
        manifest[name] = _entry(f, name)
        done['current'].append(name)
    write_manifest(f.zone_dir, manifest)
    return done


def _entry(f: Fetched, name: str) -> dict:
    return {'sha256': f.hashes[name], 'server': list(f.server[name]), 'stat': _stat(f.zone_dir / name)}
