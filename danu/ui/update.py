"""A newer release - J7: at most once a day, at start, GitHub is asked for
Danu's releases, and one newer than this is said in the status line with a
link to it.

GitHub's ``releases/latest`` leaves out a prerelease, and every release so
far is one, so the list is read instead and the newest that is not a draft
taken: a mapper on 0.2.0 is told of 0.3.0 whether or not it is marked a
prerelease. The answer is kept, so the starts on the day after the asking
still say it, and a release installed since says nothing.

It can be turned off in the preferences. Installed from the Microsoft Store
it never asks: the Store updates it. A Store install is a packaged process,
which Windows says by giving it a package name.
"""

from __future__ import annotations

import json
import re
import sys
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import __version__
from . import about

RELEASES = 'https://api.github.com/repos/opengeofiction-net/danu/releases?per_page=30'
DAY = 24 * 3600
APPMODEL_ERROR_NO_PACKAGE = 15700
USER_AGENT = f'Danu/{__version__} (+{about.HOME})'

_VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|alpha|b|beta|rc)\.?(\d+))?')
_PRE = {'a': 0, 'alpha': 0, 'b': 1, 'beta': 1, 'rc': 2}


def parse(tag: str) -> tuple[int, ...] | None:
    """A tag as something to compare: v0.3.0 above v0.3.0rc1 above v0.3.0b2."""
    m = _VERSION.fullmatch(tag.strip())
    if not m:
        return None
    major, minor, patch, pre, n = m.groups()
    rank = (_PRE[pre], int(n)) if pre else (3, 0)
    return int(major), int(minor), int(patch), *rank


def newest(releases: list) -> tuple[str, str] | None:
    """The newest release that is not a draft, as (tag, its page); a page
    not on GitHub's Danu is not linked to."""
    best = None
    for r in releases:
        if not isinstance(r, dict) or r.get('draft'):
            continue
        tag, url = str(r.get('tag_name', '')), str(r.get('html_url', ''))
        v = parse(tag)
        if v is None or not url.startswith(f'{about.HOME}/releases/'):
            continue
        if best is None or v > best[0]:
            best = (v, tag, url)
    return None if best is None else (best[1], best[2])


def is_newer(tag: str, than: str = __version__) -> bool:
    a, b = parse(tag), parse(than)
    return a is not None and b is not None and a > b


def from_store() -> bool:
    """Running as a packaged (MSIX) app. Asked with no buffer,
    GetCurrentPackageFullName says APPMODEL_ERROR_NO_PACKAGE, 15700, for a
    process with no package, and ERROR_INSUFFICIENT_BUFFER, 122, for one
    with a name to give: anything but 15700 is a package."""
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    n = wintypes.UINT(0)
    try:
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None)
    except (AttributeError, OSError):
        return False                                   # older than Windows 8: no packages
    return rc != APPMODEL_ERROR_NO_PACKAGE


class UpdateCheck(QObject):
    """Asks, at most once a ``DAY``, and says what it found through ``found``
    - the cached answer first, if it is newer."""

    found = Signal(str, str)                           # the tag, its page

    def __init__(self, settings, parent=None, now=time.time):
        super().__init__(parent)
        self.settings = settings
        self.now = now
        self.nam: QNetworkAccessManager | None = None
        self.reply: QNetworkReply | None = None

    def start(self) -> bool:
        """True if GitHub was asked."""
        s = self.settings
        if from_store() or not s.update_check:
            return False
        tag, url = s.update_latest
        if tag and is_newer(tag):
            self.found.emit(tag, url)
        if 0 <= self.now() - s.update_checked < DAY:
            return False
        self.nam = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(RELEASES))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        req.setRawHeader(b'Accept', b'application/vnd.github+json')
        self.reply = self._send(req)
        self.reply.finished.connect(self._finished)
        return True

    def _send(self, req: QNetworkRequest) -> QNetworkReply:
        return self.nam.get(req)

    def _finished(self) -> None:
        reply, self.reply = self.reply, None
        if reply is None:
            return
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return                                     # offline, or GitHub not answering: the next start asks
        try:
            got = newest(json.loads(bytes(reply.readAll()).decode('utf-8')))
        except (ValueError, UnicodeDecodeError):
            return
        s = self.settings
        s.update_checked = self.now()
        had = s.update_latest
        if got is None:
            return
        s.update_latest = got
        if is_newer(got[0]) and got != had:
            self.found.emit(*got)                      # not said twice: the cached one was said at start
