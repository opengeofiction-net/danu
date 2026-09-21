"""Fetching the two territory files, and telling the mapper whose ground the
set is on - R7.

The polygons are stable and a megabyte and a half, so they are kept on disk for a day,
the daily rebuild being their natural refresh. The attribute record is 217 KB
and changes the moment an admin saves the wiki page, so it is re-read after
ten minutes. Either fetch failing falls back to whatever the disk holds, and
holding nothing is reported as not known rather than as no territory. The
network is Qt's, asynchronous on the main thread as the tiles are; the parse
and the index take twenty milliseconds.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..core import territory as T

GEOMETRY_URL = 'https://data.opengeofiction.net/utility/territory.json'
ATTRIBUTES_URL = 'https://wiki.opengeofiction.net/index.php?title=OpenGeofiction:Territory_administration&action=raw'
GEOMETRY_MAX_AGE = 24 * 3600.0
ATTRIBUTES_MAX_AGE = 600.0
USER_AGENT = 'danu (+https://github.com/opengeofiction-net/danu)'


class TerritoryFetcher(QObject):
    """Both files, from disk when fresh enough and from the network when
    not; ``ready`` fires with the index once both halves are in hand, and
    again whenever a half is refreshed.

    Give it a parent. An unparented fetcher with replies in flight is
    collected by Python with its QNetworkAccessManager, and Qt then finishes
    a reply into freed memory - measured as a segfault in the tests."""

    ready = Signal(object)          # TerritoryIndex
    failed = Signal(str)

    def __init__(self, cache_dir: Path | None, parent: QObject | None = None,
                 geometry_url: str | None = None, attributes_url: str | None = None):
        super().__init__(parent)
        self.cache_dir = cache_dir
        # read here rather than defaulted in the signature: a default binds at
        # import and could not then be pointed elsewhere, which is how the
        # tests keep off the network
        self.urls = {'geometry': geometry_url or GEOMETRY_URL,
                     'attributes': attributes_url or ATTRIBUTES_URL}
        self.max_age = {'geometry': GEOMETRY_MAX_AGE, 'attributes': ATTRIBUTES_MAX_AGE}
        self.nam = QNetworkAccessManager(self)
        self.text: dict[str, str | None] = {'geometry': None, 'attributes': None}
        self.stale: dict[str, float] = {}        # which -> mtime of the disk copy standing in for a failed fetch
        self.index: T.TerritoryIndex | None = None
        self._inflight: dict[str, QNetworkReply] = {}

    # ------------------------------------------------------------ cache
    def _file(self, which: str) -> Path | None:
        return None if self.cache_dir is None else self.cache_dir / f'territory-{which}.json'

    def _fresh(self, which: str) -> bool:
        f = self._file(which)
        return f is not None and f.exists() and time.time() - f.stat().st_mtime < self.max_age[which]

    def _read(self, which: str) -> str | None:
        f = self._file(which)
        try:
            return f.read_text(encoding='utf-8') if f is not None and f.exists() else None
        except OSError:
            return None

    def _write(self, which: str, text: str):
        f = self._file(which)
        if f is None:
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix('.tmp')
        tmp.write_text(text, encoding='utf-8')
        tmp.replace(f)

    # ------------------------------------------------------------ fetch
    def refresh(self, force: bool = False):
        """Serve what is fresh from disk; fetch the rest."""
        for which in ('geometry', 'attributes'):
            if not force and self._fresh(which):
                self.text[which] = self._read(which)
            elif which not in self._inflight:
                req = QNetworkRequest(QUrl(self.urls[which]))
                req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
                reply = self.nam.get(req)
                self._inflight[which] = reply
                # the reply is looked up, not captured: a slot holding the
                # object it is a slot of is the lifetime tangle PySide crashes on
                reply.finished.connect(lambda w=which: self._finished(w))
        self._rebuild()

    def _finished(self, which: str):
        reply = self._inflight.pop(which, None)
        if reply is None:
            return
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                text = bytes(reply.readAll()).decode('utf-8', 'replace')
                try:
                    (T.parse_geometry if which == 'geometry' else T.parse_attributes)(text)
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    self.failed.emit(f'territory {which}: not the JSON expected ({e})')
                    text = None
                if text is not None:
                    self.text[which] = text
                    self._write(which, text)
                    self.stale.pop(which, None)
            else:
                stale = self._read(which)
                self.failed.emit(f'territory {which}: {reply.errorString()}'
                                 + ('; using the copy on disk' if stale else ''))
                if stale:
                    self.text[which] = stale
                    self.stale[which] = self._file(which).stat().st_mtime
        finally:
            reply.deleteLater()
        self._rebuild()

    def _rebuild(self):
        if self.text['geometry'] is None:
            return                          # nothing to place; attributes alone say nothing about where
        try:
            geometry = T.parse_geometry(self.text['geometry'])
            attributes = T.parse_attributes(self.text['attributes']) if self.text['attributes'] else {}
        except (ValueError, TypeError, KeyError, IndexError) as e:
            self.failed.emit(f'territory files: {e}')
            return
        self.index = T.TerritoryIndex(geometry, attributes)
        self.ready.emit(self.index)

    def abort(self):
        """Give up whatever is in flight. A window closing has no use for the
        territory files, and a reply finishing into a fetcher that is being
        taken down with it is a crash rather than a wasted request; signals
        are blocked first so nothing tries to report the abort."""
        replies, self._inflight = list(self._inflight.values()), {}
        for reply in replies:
            reply.blockSignals(True)
            reply.abort()

    @property
    def complete(self) -> bool:
        return self.text['geometry'] is not None and self.text['attributes'] is not None
