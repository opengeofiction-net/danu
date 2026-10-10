"""Fetching a zone's published DEM, for the difference (H3c).

`data.opengeofiction.net/dem/<zone>/dem-<zone>.tif`, the server's last build:
6 MB for gobras. Asked again with If-Modified-Since, so it is downloaded once
a build rather than once a look; a server that cannot be reached leaves the
copy held in use, and says so. Not in `danu.surface`, which the build runs
and which fetches nothing. No Qt.
"""

from __future__ import annotations

import email.utils
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

URL = 'https://data.opengeofiction.net/dem/{zone}/dem-{zone}.tif'
TIMEOUT_S = 60


def fetch(url: str, into: Path, timeout: float = TIMEOUT_S) -> tuple[Path, str]:
    """``url`` into the file ``into``, unless it is no newer than the copy
    there. Returns the file and what was done - 'fetched', 'unchanged', or
    'kept: <why>' when the server could not be asked and a copy is held."""
    into.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url)
    if into.exists():
        req.add_header('If-Modified-Since', email.utils.formatdate(into.stat().st_mtime, usegmt=True))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            fd, tmp = tempfile.mkstemp(dir=into.parent, prefix='.fetch-')
            try:
                with os.fdopen(fd, 'wb') as f:
                    while chunk := resp.read(1 << 20):
                        f.write(chunk)
                os.replace(tmp, into)          # whole, or the copy held stays as it was
            except BaseException:
                os.unlink(tmp)
                raise
            stamp = resp.headers.get('Last-Modified')
            if stamp:
                t = email.utils.parsedate_to_datetime(stamp).timestamp()
                os.utime(into, (t, t))
            return into, 'fetched'
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return into, 'unchanged'
        if e.code == 404:
            raise FileNotFoundError(f'no published DEM at {url}') from None
        if into.exists():
            return into, f'kept: the server answered {e.code}'
        raise
    except (urllib.error.URLError, OSError) as e:
        if into.exists():
            return into, f'kept: {getattr(e, "reason", e)}'
        raise
