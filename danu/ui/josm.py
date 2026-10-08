"""JOSM's remote control: the place Danu shows, shown in JOSM - for the water
and the peaks, which are fixed on the main map and uploaded from JOSM.

``/zoom`` moves JOSM's view to a box and selects what it is told to, among the
data it already holds: nothing is downloaded, so JOSM shows the main map as
it was loaded there, edits and all. What it can select is what came from the
main map - a positive id. A contour, or anything else drawn here, has a
negative one and is in no layer of JOSM's; the box is sent, and the selection
says nothing of it.

The request goes out on Qt's network manager and answers on the UI thread, so
a JOSM that is not running costs the status line a message and nothing else.
"""

from __future__ import annotations

from urllib.parse import urlencode

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

DEFAULT_URL = 'http://127.0.0.1:8111'
TIMEOUT_MS = 3000


def selected_ids(selection) -> list[str]:
    """What of a selection JOSM can select: its main-map objects, as
    ``node123``, ``way45``, ``relation6`` - a node first, the most particular."""
    if selection is None:
        return []
    out = []
    if selection.node is not None and selection.node > 0:
        out.append(f'node{selection.node}')
    if selection.way is not None and selection.way.id > 0:
        out.append(f'way{selection.way.id}')
    if selection.relation is not None and selection.relation.id > 0:
        out.append(f'relation{selection.relation.id}')
    return out


def zoom_url(base: str, bounds, ids=()) -> str:
    """``/zoom`` over a (west, south, east, north) box, selecting ``ids``."""
    west, south, east, north = bounds
    query = {'left': f'{west:.7f}', 'right': f'{east:.7f}',
             'top': f'{north:.7f}', 'bottom': f'{south:.7f}'}
    if ids:
        query['select'] = ','.join(ids)
    return f'{base.rstrip("/")}/zoom?{urlencode(query, safe=",")}'


class JosmRemote(QObject):
    """One request at a time to JOSM's remote control; a newer one replaces
    one still out."""

    answered = Signal(str)             # what was asked, JOSM having done it
    failed = Signal(str)               # why not, for the status line

    def __init__(self, base: str = DEFAULT_URL, parent=None):
        super().__init__(parent)
        self.base = base
        self.nam = QNetworkAccessManager(self)
        self.timeout_ms = TIMEOUT_MS
        self._reply = None
        self._replaced: set = set()

    def zoom(self, bounds, ids=(), what: str = '') -> str:
        url = zoom_url(self.base, bounds, ids)
        if self._reply is not None:
            # said so before the abort: a reply cancelled by its own timeout
            # is cancelled too, and that one is a JOSM not answering
            self._replaced.add(id(self._reply))
            self._reply.abort()
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(self.timeout_ms)
        reply = self.nam.get(req)
        self._reply = reply
        reply.finished.connect(lambda: self._done(reply, what))
        return url

    def _done(self, reply, what: str) -> None:
        if reply is self._reply:
            self._reply = None
        err = reply.error()
        body = bytes(reply.readAll()).decode('utf-8', 'replace').strip()
        reply.deleteLater()
        if id(reply) in self._replaced:
            self._replaced.discard(id(reply))
            return                                       # replaced by a newer one
        if err == QNetworkReply.NetworkError.NoError:
            self.answered.emit(what)
        elif err in (QNetworkReply.NetworkError.ConnectionRefusedError,
                     QNetworkReply.NetworkError.HostNotFoundError,
                     QNetworkReply.NetworkError.TimeoutError,
                     QNetworkReply.NetworkError.OperationCanceledError):
            self.failed.emit(f'JOSM is not answering at {self.base} - start it, and turn on '
                             'Remote Control in its preferences')
        else:
            # JOSM's own refusal comes back as a 4xx with its reason in the body
            self.failed.emit(f'JOSM refused it: {body or reply.errorString()}')
