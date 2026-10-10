"""The published DEM of a zone, fetched for the difference (H3c).

`data.opengeofiction.net/dem/<zone>/dem-<zone>.tif`, the server's last build:
6 MB for gobras. Kept under the cache directory and asked again with
If-Modified-Since, so it is downloaded once a build rather than once a look;
a server that cannot be reached leaves the copy kept in use, and says so.
Fetched on a worker, and only when the difference is asked for.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.published import URL, fetch
from .background import Job


class PublishedDem(QObject):
    """One fetch at a time; ``ready`` with the zone and the file."""

    ready = Signal(str, object, str)     # zone, path, what was done
    failed = Signal(str, str)            # zone, why

    def __init__(self, cache: Path | None, url: str = URL, runner=None, parent=None):
        super().__init__(parent)
        self._cache = cache                           # None: a directory of its own, made when first needed
        self.url = url
        self.runner = runner
        self._job = None
        self._zone = None

    @property
    def cache(self) -> Path:
        if self._cache is None:
            self._cache = Path(tempfile.mkdtemp(prefix='danu-published-'))
        return self._cache

    @cache.setter
    def cache(self, path: Path) -> None:
        self._cache = path

    def path(self, zone: str) -> Path:
        return self.cache / zone / f'dem-{zone}.tif'

    @property
    def busy(self) -> bool:
        return self._job is not None

    def request(self, zone: str) -> None:
        if self._job is not None and self._zone == zone:
            return                                     # already on its way
        url, into = self.url.format(zone=zone), self.path(zone)
        self._zone = zone
        job = Job(lambda: fetch(url, into), lambda answer: self._done(job, zone, answer),
                  lambda why: self._failed(job, zone, why))
        self._job = job
        (self.runner or _pool_start)(job)

    def _done(self, job, zone, answer) -> None:
        if job is self._job:
            self._job = None
        path, what = answer
        self.ready.emit(zone, path, what)

    def _failed(self, job, zone, why) -> None:
        if job is self._job:
            self._job = None
        self.failed.emit(zone, why.splitlines()[0])


def _pool_start(job) -> None:
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().start(job)
