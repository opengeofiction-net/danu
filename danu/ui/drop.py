"""The data drop, as the editor sees it (#190, N4): which zone a square is in,
and whether it is the mapper's to upload - asked of the drop's API, which
answers from the zones and the territories on the server.

The answer is a line in the status bar. A square in no zone can't be
uploaded at all, and the line says whom to ask: a link to message the
project's admin account on OGF. Not signed in, the zone alone; the API not
reached - it is not there yet, or the network isn't - a quiet line that says
so, and nothing in the way of drawing.
"""

from __future__ import annotations

import html
import json

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import USER_AGENT
from ..core.square import SquareName
from ..core.territory import REACH_M

URL = 'https://data.opengeofiction.net/dem/api'
# whom a mapper asks for a zone: OGF's message page for the account
ADMIN = 'admin'


def admin_link(server: str) -> str:
    return f'{server.rstrip("/")}/message/new/{ADMIN}'


def describe(status: int, body: dict, server: str) -> tuple[str, bool]:
    """The status bar's line for an answer, as rich text, and whether it is
    a warning - a square the mapper can't upload."""
    square = html.escape(str(body.get('square', '')))
    if status == 404 and 'square' in body:
        link = f'<a href="{html.escape(admin_link(server))}">message {ADMIN}</a>'
        return f'{square} is in no zone, so it can\'t be uploaded - {link} to set one up', True
    if status != 200:
        return f'upload: {html.escape(str(body.get("error", status)))}', False
    zone = html.escape(str(body.get('zone', '')))
    if body.get('blocked'):
        name = html.escape(str(body.get('user', '')))
        link = f'<a href="{html.escape(server.rstrip("/"))}/user/{name}/blocks">blocked on OGF</a>'
        return f'zone {zone} - your account is {link}, so nothing can be uploaded while it is', True
    p = body.get('permission')
    if p is None:
        return f'zone {zone} - sign in to see whether it is yours to upload', False
    # the mapper's own ground first: an administrator who owns the territory
    # is its owner, and the administrator only where the ground is another's
    named = lambda ts: ', '.join(html.escape(t.get('name') or t.get('ogfId') or '?') for t in ts)  # noqa: E731
    mine, others = named(p.get('mine', [])), named(p.get('others', []))
    if p.get('level') == 'yes':
        return f'zone {zone} - yours to upload' + (f': {mine}' if mine else ''), False
    if p.get('level') == 'partial':
        return (f'zone {zone} - yours to upload, shared with {others}: keep to your own ground, '
                f'and within {REACH_M / 1000:g} km of it in theirs'), False
    if body.get('admin'):
        return (f'zone {zone} - not your territory' + (f' ({others})' if others else '')
                + ', yours to upload as an administrator'), False
    return f'zone {zone} - not yours to upload' + (f': {others}' if others else ''), True


class DropClient(QObject):
    """Asks the API about a square. ``answered(square, line, warn)``."""

    answered = Signal(str, str, bool)

    def __init__(self, base_url: str = URL, server: str = 'https://opengeofiction.net', parent=None):
        super().__init__(parent)
        self.base_url, self.server = base_url.rstrip('/'), server
        self.nam = QNetworkAccessManager(self)
        self._inflight: QNetworkReply | None = None

    def ask(self, square: SquareName, token: str = '') -> None:
        """The last asked is the one answered: an earlier question still out
        is dropped."""
        self.abort()
        req = QNetworkRequest(QUrl(f'{self.base_url}/squares/{square.name}'))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        if token:
            req.setRawHeader(b'Authorization', f'Bearer {token}'.encode())
        reply = self.nam.get(req)
        self._inflight = reply
        reply.finished.connect(lambda: self._finished(reply, square))

    def abort(self) -> None:
        if self._inflight is not None:
            reply, self._inflight = self._inflight, None
            reply.abort()
            reply.deleteLater()

    def _finished(self, reply: QNetworkReply, square: SquareName) -> None:
        if reply is not self._inflight:
            return
        self._inflight = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            data = bytes(reply.readAll())
            try:
                body = json.loads(data) if status else None
            except ValueError:
                body = None
            if not status or not isinstance(body, dict):
                self.answered.emit(square.name, 'upload service not reached', False)
                return
            line, warn = describe(int(status), body, self.server)
            self.answered.emit(square.name, line, warn)
        finally:
            reply.deleteLater()
