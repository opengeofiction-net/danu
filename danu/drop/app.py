"""The data drop's HTTP API (#190): plain WSGI, run by gunicorn on util
behind nginx at ``data.opengeofiction.net``. ``docs/data-drop.md`` is the
plan; ``docs/implementation.md``, N2, the calls.

Reading needs no sign-in. Everything else carries the OGF token the editor
signed in with, as ``Authorization: Bearer``: an upload, a rename and a
delete are checked against the square's permission, and the zone calls are
an administrator's. Every answer but a square's bytes is JSON, and every
refusal says why in ``error``.

    GET    /zones[?held=1]               the zones, their squares, inactive or not - and the squares held, with each one's class
    GET    /zones/<zone>                 a zone's squares: file, label, size, sha256
    GET    /zones/<zone>/<file>          a square's bytes, its sha256 the ETag
    GET    /squares/<square>             its zone, what is held, and - signed in - its permission
    PUT    /squares/<square>[?label=L]   a new version; If-Match, or If-None-Match: * for a new square
    PATCH  /squares/<square>             {"label": L}, with If-Match
    DELETE /squares/<square>             with If-Match
    PUT    /zones/<zone>                 {"squares": ["N18E086-N21E089", ...]}, an admin's
    POST   /zones/<zone>/split           {"name": N, "squares": [...]}: those squares a new zone, an admin's
    PUT    /zones/<zone>/inactive        {"reason": R, "note": N}, an admin's
    DELETE /zones/<zone>/inactive        an admin's
"""

from __future__ import annotations

import json
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .. import __version__
from ..core import territory as T
from ..core import zones as Z
from ..core.square import LABEL, SquareName
from .sources import OgfUsers, Territories, Unknown, User
from .store import Refused, Store, check_square_file

MAX_MB = 64     # the largest square on 2026-10-18 was 24 MB


@dataclass
class Config:
    base: Path
    pubroot: Path | None
    max_bytes: int = MAX_MB << 20

    @property
    def zones_file(self) -> Path:
        return self.base / 'zones'

    @property
    def inactive_file(self) -> Path:
        return self.base / 'inactive'


def _json(start, status: int, body, headers=()):
    data = json.dumps(body).encode()
    start(f'{status} {_REASONS.get(status, "")}'.rstrip(),
          [('Content-Type', 'application/json'), ('Content-Length', str(len(data))), *headers])
    return [data]


_REASONS = {200: 'OK', 201: 'Created', 204: 'No Content', 400: 'Bad Request', 401: 'Unauthorized',
            403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed', 409: 'Conflict',
            411: 'Length Required', 412: 'Precondition Failed', 413: 'Content Too Large',
            422: 'Unprocessable Content', 428: 'Precondition Required', 502: 'Bad Gateway',
            503: 'Service Unavailable'}


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.part')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


class DropApp:
    def __init__(self, config: Config, users, territories):
        self.config = config
        self.store = Store(config.base, config.pubroot)
        self.users = users              # token -> User, raising Unknown
        self.territories = territories  # -> TerritoryIndex, raising Unknown

    # ---------------------------------------------------------------- plumbing

    def __call__(self, environ, start):
        try:
            return self.route(environ, start)
        except Refused as e:
            headers = [('ETag', e.extra['etag'])] if e.extra.get('etag') else []
            return _json(start, e.status, {'error': e.why, **{k: v for k, v in e.extra.items() if v}}, headers)
        except Unknown as e:
            return _json(start, e.status, {'error': e.why})

    def zones(self) -> Z.Zones:
        try:
            return Z.Zones.read(self.config.zones_file)
        except Z.ZoneError as e:
            raise Refused(503, f'the zones file is wrong: {e}') from e

    def user(self, environ, required: bool = True) -> User | None:
        auth = environ.get('HTTP_AUTHORIZATION', '')
        if not auth:
            if required:
                raise Refused(401, 'sign in to OGF first')
            return None
        kind, _, token = auth.partition(' ')
        if kind.lower() != 'bearer' or not token.strip():
            raise Refused(401, 'Authorization: Bearer <token>')
        return self.users(token.strip())

    def admin(self, environ) -> User:
        user = self.user(environ)
        if not user.admin:
            raise Refused(403, 'an administrator\'s')
        return user

    @staticmethod
    def body_json(environ) -> dict:
        try:
            n = int(environ.get('CONTENT_LENGTH') or 0)
            data = json.loads(environ['wsgi.input'].read(n) or b'{}')
        except (ValueError, KeyError) as e:
            raise Refused(400, f'the body is not JSON: {e}') from e
        if not isinstance(data, dict):
            raise Refused(400, 'the body is a JSON object')
        return data

    def square_and_zone(self, text: str) -> tuple[SquareName, str]:
        try:
            square = SquareName.parse(text)
        except ValueError as e:
            raise Refused(404, str(e)) from e
        zone = self.zones().zone_of(square)
        if zone is None:
            raise Refused(404, f'{square} is in no zone: ask an administrator to set one up', square=square.name)
        return square, zone

    def permission(self, user: User, square: SquareName) -> T.Permission:
        return self.territories.index().permission(square.bounds, user.name)

    def allowed(self, user: User, square: SquareName, levels: tuple[str, ...]) -> None:
        if user.admin:
            return
        p = self.permission(user, square)
        if p.level not in levels:
            raise Refused(403, f'{square} is not yours to change ({p.level})', permission=_permission(p))

    # ---------------------------------------------------------------- routes

    def route(self, environ, start):
        method = environ['REQUEST_METHOD']
        parts = [urllib.parse.unquote(p) for p in environ.get('PATH_INFO', '/').strip('/').split('/') if p]
        query = urllib.parse.parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)
        match parts:
            case []:
                self.only(method, 'GET')
                return _json(start, 200, {'service': 'danu data drop', 'version': __version__})
            case ['zones']:
                self.only(method, 'GET')
                return self.list_zones(start, query)
            case ['zones', zone]:
                if method == 'PUT':
                    return self.put_zone(environ, start, zone)
                self.only(method, 'GET')
                return self.zone(start, zone)
            case ['zones', zone, 'inactive']:
                self.only(method, 'PUT', 'DELETE')
                return self.inactive(environ, start, zone, method)
            case ['zones', zone, 'split']:
                self.only(method, 'POST')
                return self.split_zone(environ, start, zone)
            case ['zones', zone, file]:
                self.only(method, 'GET')
                return self.file(environ, start, zone, file)
            case ['squares', text]:
                if method == 'GET':
                    return self.square(environ, start, text)
                if method == 'PUT':
                    return self.upload(environ, start, text, query)
                if method == 'PATCH':
                    return self.rename(environ, start, text)
                self.only(method, 'DELETE')
                return self.delete(environ, start, text)
        raise Refused(404, 'no such call')

    @staticmethod
    def only(method: str, *allowed: str) -> None:
        if method not in allowed:
            raise Refused(405, f'{method}: this takes {", ".join(allowed)}')

    def list_zones(self, start, query=None):
        """The zones; with ``held=1`` each zone's squares too, and their
        class, for the zone map's colours - hashed and classed once a file."""
        inactive = Z.Inactive.read(self.config.inactive_file).reasons()
        held = bool(query) and query.get('held', [''])[0].lower() in ('1', 'true', 'yes')
        out = []
        for z in self.zones().zones.values():
            row = {'name': z.name, 'squares': [str(r) for r in z.rects], 'inactive': inactive.get(z.name)}
            if held:
                row['held'] = [{'square': h.square.name, 'file': h.path.name, 'class': h.kind}
                               for h in self.store.listing(z.name)]
            out.append(row)
        return _json(start, 200, {'zones': out})

    def known_zone(self, zone: str) -> Z.Zone:
        z = self.zones().zones.get(zone)
        if z is None:
            raise Refused(404, f'no zone {zone}')
        return z

    def zone(self, start, zone: str):
        z = self.known_zone(zone)
        inactive = Z.Inactive.read(self.config.inactive_file).reasons().get(zone)
        return _json(start, 200, {'name': zone, 'squares': [str(r) for r in z.rects], 'inactive': inactive,
                                  'held': [h.describe() for h in self.store.listing(zone)]})

    def file(self, environ, start, zone: str, file: str):
        self.known_zone(zone)
        held = next((h for h in self.store.listing(zone) if h.path.name == file), None)
        if held is None:
            raise Refused(404, f'{zone} holds no {file}')
        etag = f'"{held.sha256}"'
        if environ.get('HTTP_IF_NONE_MATCH', '').strip() == etag:
            start('304 Not Modified', [('ETag', etag)])
            return [b'']
        start('200 OK', [('Content-Type', 'application/x-xz'), ('Content-Length', str(held.size)),
                         ('ETag', etag)])
        f = open(held.path, 'rb')
        wrapper = environ.get('wsgi.file_wrapper')
        return wrapper(f, 1 << 20) if wrapper else _chunks(f)

    def square(self, environ, start, text: str):
        square, zone = self.square_and_zone(text)
        user = self.user(environ, required=False)
        held = self.store.held(zone, square)
        body = {'square': square.name, 'zone': zone, 'held': held and held.describe()}
        if user is not None:
            body['user'] = user.name
            body['admin'] = user.admin
            body['permission'] = _permission(self.permission(user, square))
        headers = [('ETag', f'"{held.sha256}"')] if held else []
        return _json(start, 200, body, headers)

    def upload(self, environ, start, text: str, query):
        user = self.user(environ)
        square, zone = self.square_and_zone(text)
        self.allowed(user, square, (T.YES, T.PARTIAL))
        label = query['label'][0] if 'label' in query else None
        if label and not LABEL.fullmatch(label):
            raise Refused(422, f'{label!r}: a label is letters, digits, _ and -, up to 64')
        try:
            length = int(environ['CONTENT_LENGTH'])
        except (KeyError, ValueError) as e:
            raise Refused(411, 'say how long the upload is: Content-Length') from e
        if length > self.config.max_bytes:
            raise Refused(413, f'over {self.config.max_bytes >> 20} MB')
        spooled = self.store.spool(zone, environ['wsgi.input'], length)
        try:
            check_square_file(spooled)
        except Refused:
            spooled.unlink(missing_ok=True)
            raise
        existed = self.store.held(zone, square) is not None
        done = self.store.put(zone, square, spooled, label, environ.get('HTTP_IF_MATCH'),
                              environ.get('HTTP_IF_NONE_MATCH'), user.name)
        return _json(start, 200 if existed else 201, done.describe(), [('ETag', f'"{done.sha256}"')])

    def rename(self, environ, start, text: str):
        user = self.user(environ)
        square, zone = self.square_and_zone(text)
        self.allowed(user, square, (T.YES, T.PARTIAL))
        label = self.body_json(environ).get('label')
        if not isinstance(label, str) or (label and not LABEL.fullmatch(label)):
            raise Refused(422, 'label: letters, digits, _ and -, up to 64; "" for none')
        done = self.store.rename(zone, square, label, environ.get('HTTP_IF_MATCH'), user.name)
        return _json(start, 200, done.describe(), [('ETag', f'"{done.sha256}"')])

    def delete(self, environ, start, text: str):
        user = self.user(environ)
        square, zone = self.square_and_zone(text)
        # yes only: a partial square's deletion would take a neighbour's ground
        self.allowed(user, square, (T.YES,))
        self.store.delete(zone, square, environ.get('HTTP_IF_MATCH'), user.name)
        start('204 No Content', [])
        return [b'']

    def put_zone(self, environ, start, zone: str):
        user = self.admin(environ)
        squares = self.body_json(environ).get('squares')
        if not isinstance(squares, list) or not all(isinstance(s, str) for s in squares):
            raise Refused(422, 'squares: a list of rectangles, "N18E086-N21E089"')
        with self.store.locked():
            before = self.zones()
            try:
                after = before.put(zone, squares)
            except Z.ZoneError as e:
                raise Refused(422, str(e)) from e
            left = self._left_out(before, after, zone)
            # what it leaves out retired before the change is written: stopped
            # between - or the write refused, a full disk - only blank and
            # coastline-only squares are in kept, each logged with where, for
            # an admin to put back; never a zone naming squares its directory
            # still holds
            retired = [self.store.retire(zone, h, user.name, 'left out of its zone') for h in left]
            # its directory first: a zone named is a zone that can be listed
            self.store.zone_dir(zone).mkdir(parents=True, exist_ok=True)
            _write(self.config.zones_file, after.text)
            self.store.log_admin(user.name, 'zone', zone=zone, squares=[str(r) for r in after.zones[zone].rects])
        created = zone not in before.zones
        return _json(start, 201 if created else 200, {'name': zone, 'squares': [str(r) for r in after.zones[zone].rects],
                                                      'retired': [h.path.name for h in left], 'kept': retired})

    def _left_out(self, before: Z.Zones, after: Z.Zones, zone: str) -> list:
        """The squares a zone change leaves in no zone. Refused (409) if any
        holds contours - the report's own test - for its mapper's work would
        be built where nobody could upload it again; the blank and the
        coastline-only are returned, to be retired."""
        if zone not in before.zones:
            return []
        gone = before.zones[zone].cells() - after.zones[zone].cells()
        out = [h for h in self.store.listing(zone) if h.square in gone and after.zone_of(h.square) is None]
        drawn = [h.square.name for h in out if h.kind == 'contour']
        if drawn:
            raise Refused(409, f'{", ".join(drawn)} hold{"s" if len(drawn) == 1 else ""} contours, and would be '
                          'in no zone: keep them in the zone, or move them to another first', squares=drawn)
        return out

    def split_zone(self, environ, start, zone: str):
        """Some of a zone's squares a new zone: the rectangles of both
        written, the squares' files moved with them, the old zone's inactive
        entry copied - one step, under the lock. One step for the drop, not
        for the disk: the files can't change at once, and a server stopped
        in the milliseconds between leaves the moves for an admin to finish
        by hand - each move is a line of the log as it is made. The zones
        file first: the build finds zones by their directories, so squares
        moved before it was written would be built as a zone no file names,
        and none could upload to."""
        user = self.admin(environ)
        body = self.body_json(environ)
        name, squares = body.get('name'), body.get('squares')
        if not isinstance(name, str) or not isinstance(squares, list) or not all(isinstance(s, str) for s in squares):
            raise Refused(422, 'name, and squares: a list of rectangles')
        with self.store.locked():
            before = self.zones()
            old = before.zones.get(zone)
            if old is None:
                raise Refused(404, f'no zone {zone}')
            if name in before.zones:
                raise Refused(409, f'{name} is a zone already')
            try:
                moving = set().union(*(Z.Rect.parse(r).cells() for r in squares)) if squares else set()
            except Z.ZoneError as e:
                raise Refused(422, str(e)) from e
            if not moving or not moving <= old.cells():
                raise Refused(422, f'the new zone takes squares of {zone}\'s own: not none, and not others')
            if moving == old.cells():
                raise Refused(422, f'that is all of {zone}: rename it, or make a new zone')
            staying = old.cells() - moving
            try:
                after = before.put(zone, [str(r) for r in Z.rects_for(staying)])
                after = after.put(name, [str(r) for r in Z.rects_for(moving)])
            except Z.ZoneError as e:
                raise Refused(422, str(e)) from e
            inactive = Z.Inactive.read(self.config.inactive_file)
            reason = inactive.reasons().get(zone)
            self.store.zone_dir(name).mkdir(parents=True, exist_ok=True)
            _write(self.config.zones_file, after.text)
            moved = [h for h in self.store.listing(zone) if h.square in moving]
            for h in moved:
                self.store.move(h, zone, name, user.name)
            if reason:
                _write(self.config.inactive_file, inactive.set(name, reason, f'split from {zone}').text)
            self.store.log_admin(user.name, 'split', zone=zone, new=name,
                                 squares=[str(r) for r in after.zones[name].rects], inactive=reason)
        return _json(start, 201, {'name': name, 'squares': [str(r) for r in after.zones[name].rects],
                                  'from': {'name': zone, 'squares': [str(r) for r in after.zones[zone].rects]},
                                  'moved': [h.path.name for h in moved], 'inactive': reason})

    def inactive(self, environ, start, zone: str, method: str):
        user = self.admin(environ)
        self.known_zone(zone)
        body = self.body_json(environ) if method == 'PUT' else {}
        with self.store.locked():
            now = Z.Inactive.read(self.config.inactive_file)
            was = now.reasons().get(zone)
            try:
                after = (now.set(zone, str(body.get('reason', '')), str(body.get('note', '')))
                         if method == 'PUT' else now.clear(zone))
            except Z.ZoneError as e:
                raise Refused(422, str(e)) from e
            _write(self.config.inactive_file, after.text)
            self.store.log_admin(user.name, 'inactive' if method == 'PUT' else 'active', zone=zone,
                                 reason=body.get('reason'), was=was)
        return _json(start, 200, {'name': zone, 'inactive': after.reasons().get(zone)})


def _chunks(f):
    with f:
        while chunk := f.read(1 << 20):
            yield chunk


def _permission(p: T.Permission) -> dict:
    who = lambda ts: [{'ogfId': t.ogf_id, 'name': t.name, 'rel': t.rel} for t in ts]  # noqa: E731
    return {'level': p.level, 'mine': who(p.mine), 'others': who(p.others)}


def create() -> DropApp:
    """The app as gunicorn runs it, configured from the environment that
    ``/etc/danu/danu.conf`` gives the unit: BASE and PUBROOT as danu-build
    has them, and DROP_OGF, DROP_TERRITORY_GEOMETRY (a path or a URL),
    DROP_TERRITORY_ATTRIBUTES and DROP_MAX_MB."""
    env = os.environ
    base = Path(env.get('BASE', '/var/lib/danu'))
    config = Config(base, Path(env.get('PUBROOT', '/var/lib/danu/publish')),
                    int(env.get('DROP_MAX_MB', MAX_MB)) << 20)
    users = OgfUsers(env.get('DROP_OGF', 'https://opengeofiction.net'))
    territories = Territories(env.get('DROP_TERRITORY_GEOMETRY', T.GEOMETRY_URL),
                              env.get('DROP_TERRITORY_ATTRIBUTES', T.ATTRIBUTES_URL))
    return DropApp(config, users, territories)
