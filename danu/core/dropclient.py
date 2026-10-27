"""The editor's half of sending a square to the data drop (#190, N5b):
upload, rename and delete, each made from the version the mapper last had
from the server.

That version is the mirror's (``danu.core.mirror``): the manifest beside a
zone's squares records each one's SHA-256 as imported, and the upload sends
it as ``If-Match``. A square the server doesn't hold goes up with
``If-None-Match: *``. One the server holds that was never imported here -
edited before Danu 1.3, or brought from elsewhere - has no version to say: it
is refused unsent, marked ``unimported``, with the server's copy, and the
editor asks whether to replace that copy. Asked yes, ``over`` is that copy's
version, sent as ``If-Match``, so it is that copy which is replaced and no
later one.

After a change the manifest says what the server now holds - the bytes
uploaded, under the name the server gave - so the next upload is made from
it, and the next import finds nothing to fetch. A square renamed with its
upload is renamed here too.

Refused because the square changed, ``keep_mine`` puts the mapper's copy
beside it as ``<square>.mine.osm.xz`` - a name no listing reads as a square
- for the editor to show while they redo their changes on the server's.

Nothing here is Qt's: the window runs these on a worker.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .. import USER_AGENT
from . import mirror
from .square import SquareName, label_of, list_squares

TIMEOUT_S = 300                 # the largest square takes a while to go up, and to be read through there
MINE = '.mine.osm.xz'


@dataclass
class Answer:
    """What the drop said: its status, its JSON, and the square's version."""
    status: int
    body: dict = field(default_factory=dict)
    etag: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def why(self) -> str:
        return str(self.body.get('error') or f'the server answered {self.status}')


def _ask(method: str, url: str, token: str, opener, data: bytes | None = None,
         headers: dict | None = None, timeout: float = TIMEOUT_S) -> Answer:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'User-Agent': USER_AGENT, **(headers or {})})
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with opener(req, timeout=timeout) as r:
            status, raw, etag = r.status, r.read(), r.headers.get('ETag')
    except urllib.error.HTTPError as e:
        status, raw, etag = e.code, e.read(), e.headers.get('ETag') if e.headers else None
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    return Answer(status, body if isinstance(body, dict) else {}, etag)


def mine_path(path: Path) -> Path:
    """``N20E086_Gobras_City.osm.xz`` -> ``N20E086_Gobras_City.mine.osm.xz``."""
    return path.with_name(path.name.removesuffix('.osm.xz') + MINE)


def mine_for(zone_dir: Path, square: SquareName) -> Path | None:
    """The mapper's refused copy of a square, if one is kept here."""
    found = sorted(Path(zone_dir).glob(f'{square.name}*{MINE}'))
    return found[0] if found else None


def keep_mine(path: Path) -> Path:
    """The mapper's copy of a refused square, kept beside it."""
    dest = mine_path(path)
    shutil.copy2(path, dest)
    return dest


def _version(zone_dir: Path, path: Path) -> str | None:
    """The square's version as last had from the server, if it still is."""
    known = mirror.read_manifest(zone_dir).get(path.name) or {}
    return known.get('sha256')


def unsent(zone_dir: Path) -> dict[SquareName, tuple[Path, bool]]:
    """The squares here the server doesn't have as they are: each one's file,
    and True when it was had from the server and saved since, False when the
    manifest doesn't know it - new here, deleted there, or edited before
    Danu 1.3. A file as the manifest has it is not read again. A folder
    never imported to has no manifest and nothing to say: it is not a copy
    of the server's."""
    zone_dir = Path(zone_dir)
    if not (zone_dir / mirror.MANIFEST).exists():
        return {}
    manifest = mirror.read_manifest(zone_dir)
    out = {}
    for square, path in list_squares(zone_dir, compressed_only=True).items():
        known = manifest.get(path.name) or {}
        if not known.get('sha256'):
            out[square] = (path, False)
        elif mirror._hash_here(path, known) != known['sha256']:
            out[square] = (path, True)
    return out


def _record(zone_dir: Path, old: Path, new_name: str, sha: str, size: int, stat: list[int]) -> Path:
    """The manifest, and the file's name here, as the server now has them.
    ``stat`` is the file's as its bytes were read: a save landing while they
    went up leaves a file that doesn't match it, still to send - taken
    after, it vouched for edits the server never had, and an import would
    overwrite them unasked."""
    new = zone_dir / new_name
    if new != old:
        os.replace(old, new)
    manifest = mirror.read_manifest(zone_dir)
    manifest.pop(old.name, None)
    manifest[new_name] = {'sha256': sha, 'server': [size, sha], 'stat': stat}
    mirror.write_manifest(zone_dir, manifest)
    return new


def zones(api: str, opener=urllib.request.urlopen, held: bool = False) -> Answer:
    """The zones, their rectangles, and the reason any is inactive; with
    ``held`` each zone's squares too, and their class."""
    return _ask('GET', f'{api.rstrip("/")}/zones' + ('?held=1' if held else ''), '', opener, timeout=60)


def split_zone(api: str, token: str, zone: str, name: str, rects: list[str],
               opener=urllib.request.urlopen) -> Answer:
    """Some of a zone's squares a new zone, ``name`` - an administrator's."""
    return _ask('POST', f'{api.rstrip("/")}/zones/{urllib.parse.quote(zone)}/split', token, opener,
                json.dumps({'name': name, 'squares': rects}).encode(), {'Content-Type': 'application/json'},
                timeout=60)


def put_zone(api: str, token: str, zone: str, rects: list[str], opener=urllib.request.urlopen) -> Answer:
    """A zone made, or its squares changed - an administrator's."""
    return _ask('PUT', f'{api.rstrip("/")}/zones/{urllib.parse.quote(zone)}', token, opener,
                json.dumps({'squares': rects}).encode(), {'Content-Type': 'application/json'}, timeout=60)


def set_inactive(api: str, token: str, zone: str, reason: str | None, note: str = '',
                 opener=urllib.request.urlopen) -> Answer:
    """A zone inactive for ``reason``, or with None active again."""
    url = f'{api.rstrip("/")}/zones/{urllib.parse.quote(zone)}/inactive'
    if reason is None:
        return _ask('DELETE', url, token, opener, timeout=60)
    return _ask('PUT', url, token, opener, json.dumps({'reason': reason, 'note': note}).encode(),
                {'Content-Type': 'application/json'}, timeout=60)


def square_info(api: str, square: SquareName, token: str = '', opener=urllib.request.urlopen) -> Answer:
    return _ask('GET', f'{api.rstrip("/")}/squares/{square.name}', token, opener, timeout=60)


def upload(api: str, token: str, path: Path, label: str | None = None,
           opener=urllib.request.urlopen, over: str | None = None) -> tuple[Answer, Path]:
    """The square at ``path`` uploaded, from the version the manifest has -
    or, ``over``, replacing that version of the server's, asked. ``label``
    None keeps the server's name for it; '' takes the label away. Answers
    what the drop said, and where the square is here now. A square new to
    the server keeps its name here unless ``label`` says otherwise."""
    path = Path(path)
    zone_dir, square = path.parent, SquareName.from_filename(path)
    base = over or _version(zone_dir, path)
    if base is not None:
        headers = {'If-Match': f'"{base}"'}
    else:
        info = square_info(api, square, token, opener)
        if not info.ok:
            return info, path
        if info.body.get('held'):
            # held there and never had here: no version to say it was made from
            return Answer(412, {'error': f'{square} is held on the server, and this copy was not imported from it',
                                'unimported': True, 'held': info.body['held']}, info.etag), path
        headers = {'If-None-Match': '*'}
        if label is None:
            label = label_of(path) or None      # new there: the name it has here, not none
    query = '' if label is None else '?' + urllib.parse.urlencode({'label': label})
    st = path.stat()
    data = path.read_bytes()
    answer = _ask('PUT', f'{api.rstrip("/")}/squares/{square.name}{query}', token, opener, data,
                  {**headers, 'Content-Type': 'application/x-xz'})
    if answer.ok:
        path = _record(zone_dir, path, str(answer.body['file']), str(answer.body['sha256']), len(data),
                       [st.st_size, st.st_mtime_ns])
    return answer, path


def rename(api: str, token: str, path: Path, label: str,
           opener=urllib.request.urlopen) -> tuple[Answer, Path]:
    """The square renamed on the server - its bytes there as they are - and
    here."""
    path = Path(path)
    zone_dir, square = path.parent, SquareName.from_filename(path)
    base = _version(zone_dir, path)
    if base is None:
        return Answer(412, {'error': f'{square} was not imported from the server: import it first'}), path
    answer = _ask('PATCH', f'{api.rstrip("/")}/squares/{square.name}', token, opener,
                  json.dumps({'label': label}).encode(), {'If-Match': f'"{base}"', 'Content-Type': 'application/json'})
    if answer.ok:
        # the server's bytes are as they were: the manifest's version kept,
        # though the copy here may have edits the server has not
        new = zone_dir / str(answer.body['file'])
        if new != path:
            os.replace(path, new)
        manifest = mirror.read_manifest(zone_dir)
        entry = manifest.pop(path.name, None)
        if entry is not None:
            # its stat as it was: a rename keeps a file's size and time, so an
            # untouched file still matches it, and one with edits still
            # doesn't - taking the edited file's would vouch for edits the
            # version never had, and an import would overwrite them unasked
            manifest[new.name] = entry
        mirror.write_manifest(zone_dir, manifest)
        path = new
    return answer, path


def delete(api: str, token: str, path: Path, opener=urllib.request.urlopen) -> Answer:
    """The square deleted from the server. The copy here stays, the mapper's
    own now: the manifest forgets it, so no import calls it gone."""
    path = Path(path)
    zone_dir, square = path.parent, SquareName.from_filename(path)
    base = _version(zone_dir, path)
    if base is None:
        return Answer(412, {'error': f'{square} was not imported from the server: import it first'})
    answer = _ask('DELETE', f'{api.rstrip("/")}/squares/{square.name}', token, opener,
                  headers={'If-Match': f'"{base}"'})
    if answer.ok:
        manifest = mirror.read_manifest(zone_dir)
        manifest.pop(path.name, None)
        mirror.write_manifest(zone_dir, manifest)
    return answer

