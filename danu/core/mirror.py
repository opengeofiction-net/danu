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

**From the data drop** (#190, N5a): given its API, the listing and the
files are the working copy's - the published copy can be a day behind it -
each square listed with its SHA-256, so a square whose bytes are here
already is not fetched at all. A square is matched by its cell: renamed on
the server, ``N20E086_Gobras_City`` to ``N20E086_Gobras``, the copy here
under the old name is replaced by - or, the same bytes, renamed to - the
new, and the old name goes. The API not reached, the published copy's
index is read as before, which is how Import works until the drop is up.
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

from .. import USER_AGENT
from .square import SquareName

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


def _cell(name: str) -> SquareName | None:
    try:
        return SquareName.from_filename(name)
    except ValueError:
        return None


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
    server: dict[str, tuple[int, str]]            # name: (size, date - or sha256 from the drop), as listed
    via: str = 'published'                         # 'drop' when the drop's API answered
    renamed: dict[str, str] = field(default_factory=dict)     # name: the name here, for a square renamed there
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
    with opener(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=timeout) as r:
        return r.read()


def list_zones(base: str = URL, opener=urllib.request.urlopen, timeout: float = TIMEOUT_S,
               api: str | None = None) -> list[str]:
    """The zones: the drop's, or not reached, the published index's."""
    if api:
        try:
            data = json.loads(_get(f'{api.rstrip("/")}/zones', opener, timeout))
            return sorted(str(z['name']) for z in data['zones'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return zones(_get(f'{base.rstrip("/")}/', opener, timeout).decode('utf-8', 'replace'))


def _drop_listing(api: str, zone: str, opener, timeout: float) -> tuple[dict[str, tuple[int, str]], str] | None:
    """A zone's squares from the drop - name: (size, sha256) - and where
    their files are; None if it isn't reached, or doesn't know the zone."""
    url = f'{api.rstrip("/")}/zones/{urllib.parse.quote(zone)}'
    try:
        held = json.loads(_get(url, opener, timeout))['held']
        return {str(h['file']): (int(h['size']), str(h['sha256'])) for h in held}, url + '/'
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fetch(zone: str, root: Path, base: str = URL, opener=urllib.request.urlopen, report=None,
          timeout: float = TIMEOUT_S, api: str | None = None) -> Fetched:
    """Phase one, on a worker: the zone's listing - the drop's, or the
    published index's - and what differs fetched beside the copy here as
    ``.part-`` files. ``report((done, of, name))`` as it goes."""
    listed = _drop_listing(api, zone, opener, timeout) if api else None
    if listed is not None:
        server, zone_url, via = *listed, 'drop'
    else:
        zone_url = f'{base.rstrip("/")}/{urllib.parse.quote(zone)}/'
        server, via = files(_get(zone_url, opener, timeout).decode('utf-8', 'replace')), 'published'
    zone_dir = root / zone
    zone_dir.mkdir(parents=True, exist_ok=True)
    for stale in (*zone_dir.glob(PART + '*'), *zone_dir.glob('.manifest-*')):    # a mirror killed part way
        stale.unlink(missing_ok=True)
    manifest = read_manifest(zone_dir)
    out = Fetched(zone, zone_dir, server, via=via)
    try:
        _fetch_files(out, zone_url, manifest, opener, report, timeout)
    except BaseException:
        out.discard()
        raise
    # only what a mirror put here: a square of the mapper's own is not the
    # server's to have dropped. Nor is one renamed there, nor - the drop
    # listing squares alone - the zone's EMPTY.osm.xz
    sources = set(out.renamed.values())
    out.gone = sorted(p.name for p in zone_dir.glob('*.osm.xz')
                      if p.name not in server and p.name in manifest and p.name not in sources
                      and (via == 'published' or _cell(p.name) is not None))
    if report is not None:
        report((len(server), len(server), ''))
    return out


def _fetch_files(out: Fetched, zone_url: str, manifest: dict, opener, report, timeout: float) -> None:
    server, zone_dir = out.server, out.zone_dir
    # the squares here by cell, for one renamed there
    by_cell = {c: p.name for p in zone_dir.glob('*.osm.xz') if p.name not in server and (c := _cell(p.name))}
    for k, (name, (size, stamp)) in enumerate(sorted(server.items())):
        if report is not None:
            report((k, len(server), name))
        here = zone_dir / name
        if not here.exists() and (old := by_cell.get(_cell(name))) is not None:
            out.renamed[name] = old
            here = zone_dir / old
        known = manifest.get(here.name) or {}
        mine = _hash_here(here, known)
        untouched = mine is not None and mine == known.get('sha256')
        # the drop says its hash: the same bytes here need nothing fetched
        theirs = stamp if out.via == 'drop' else None
        if (untouched and known.get('server') == [size, stamp]) or (theirs is not None and theirs == mine):
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
        with open(tmp, 'xb') as f, opener(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}),
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
                                  'current': [], 'renamed': [], 'gone': list(f.gone)}

    def drop_old(name: str) -> None:
        """A square renamed there: its old name here goes."""
        old = f.renamed.get(name)
        if old is not None and old != name:
            (f.zone_dir / old).unlink(missing_ok=True)
            manifest.pop(old, None)
            done['renamed'].append(name)

    for kind, parts in (('new', f.new), ('updated', f.updated), ('overwritten', f.changed)):
        for name, part in parts.items():
            held = name in keep or f.renamed.get(name) in keep
            if held or (kind == 'overwritten' and name not in overwrite):
                part.unlink(missing_ok=True)
                done['held' if held else 'kept'].append(name)
                continue
            os.replace(part, f.zone_dir / name)
            manifest[name] = _entry(f, name)
            drop_old(name)
            done[kind].append(name)
    for name in f.current:
        old = f.renamed.get(name)
        if old is not None:
            if old in keep:
                done['held'].append(name)
                continue
            os.replace(f.zone_dir / old, f.zone_dir / name)     # the same bytes, under the new name
            manifest.pop(old, None)
            done['renamed'].append(name)
        manifest[name] = _entry(f, name)
        done['current'].append(name)
    write_manifest(f.zone_dir, manifest)
    return done


def _entry(f: Fetched, name: str) -> dict:
    return {'sha256': f.hashes[name], 'server': list(f.server[name]), 'stat': _stat(f.zone_dir / name)}
