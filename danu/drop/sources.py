"""What the data drop asks of others (#190): who a token is, from OGF, and
whose ground a square is, from the territories.

A token is asked of OGF's ``user/details`` - the call the editor makes when
it signs in - and the answer kept for a few minutes, keyed by the token's
hash: the token itself is never held. The territories are the two files
``danu.core.territory`` joins, the geometry read again when it changes and
the attributes fetched from the wiki every few minutes. A fetch that fails
keeps what was had; with nothing ever had, permission can't be answered.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .. import USER_AGENT
from ..core import territory as T

WHO_FOR = 300            # seconds a token's answer is kept
ATTRIBUTES_EVERY = 600   # seconds between fetches of the wiki's attributes
RETRY = 60               # seconds after a failed fetch before another


@dataclass(frozen=True)
class User:
    name: str
    roles: tuple[str, ...] = ()

    @property
    def admin(self) -> bool:
        return 'administrator' in self.roles


class Unknown(Exception):
    """A token OGF doesn't take, or OGF not answering."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status, self.why = status, why


def _get(url: str, token: str | None = None, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class OgfUsers:
    def __init__(self, server: str, fetch=_get, clock=time.monotonic):
        self.server = server.rstrip('/')
        self.fetch, self.clock = fetch, clock
        self._seen: dict[str, tuple[float, User]] = {}
        self._lock = threading.Lock()

    def __call__(self, token: str) -> User:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = self.clock()
        with self._lock:
            hit = self._seen.get(key)
            if hit and hit[0] > now:
                return hit[1]
        try:
            data = json.loads(self.fetch(f'{self.server}/api/0.6/user/details.json', token))
            u = data['user']
            user = User(str(u['display_name']), tuple(str(r) for r in u.get('roles', [])))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise Unknown(401, 'OGF does not take this sign-in: sign in again') from e
            raise Unknown(502, f'OGF answered {e.code}') from e
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise Unknown(502, f'OGF could not be asked who this is: {e}') from e
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v[0] > now}
            self._seen[key] = (now + WHO_FOR, user)
        return user


class Territories:
    """The index, kept current. ``geometry`` is a path or a URL; the
    attributes a URL."""

    def __init__(self, geometry: str, attributes: str, fetch=_get, clock=time.monotonic):
        self.geometry_src, self.attributes_src = geometry, attributes
        self.fetch, self.clock = fetch, clock
        self._geometry: dict | None = None
        self._geometry_mtime: float | None = None
        self._geometry_at = -1e18
        self._attributes: dict | None = None
        self._attributes_at = -1e18
        self._index: T.TerritoryIndex | None = None
        self._lock = threading.Lock()

    def _read_geometry(self, now: float) -> bool:
        src = self.geometry_src
        if src.startswith(('http://', 'https://')):
            if now - self._geometry_at < ATTRIBUTES_EVERY:
                return False
            # a failure is tried again in a minute, not at once - each try
            # holds a request up - and not in ten, with nothing to answer from
            self._geometry_at = now - ATTRIBUTES_EVERY + RETRY
            self._geometry = T.parse_geometry(self.fetch(src).decode())
            self._geometry_at = now
            return True
        mtime = os.stat(src).st_mtime
        if mtime == self._geometry_mtime:
            return False
        with open(src, encoding='utf-8') as f:
            self._geometry = T.parse_geometry(f.read())
        self._geometry_mtime = mtime
        return True

    def _read_attributes(self, now: float) -> bool:
        if now - self._attributes_at < ATTRIBUTES_EVERY:
            return False
        self._attributes_at = now - ATTRIBUTES_EVERY + RETRY
        self._attributes = T.parse_attributes(self.fetch(self.attributes_src).decode())
        self._attributes_at = now
        return True

    def index(self) -> T.TerritoryIndex:
        """Raises Unknown (503) if the territories have never been read."""
        now = self.clock()
        with self._lock:
            changed = False
            for read in (self._read_geometry, self._read_attributes):
                try:
                    changed |= read(now)
                except (OSError, ValueError) as e:
                    if self._index is None and (self._geometry is None or self._attributes is None):
                        raise Unknown(503, f'the territories could not be read: {e}') from e
            if changed or self._index is None:
                if self._geometry is None or self._attributes is None:
                    raise Unknown(503, 'the territories have not been read yet')
                self._index = T.TerritoryIndex(self._geometry, self._attributes)
            return self._index
