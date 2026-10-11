"""Signing in to OGF (H6f): OAuth 2 with PKCE against the server, so the
username the territory check uses is the server's own - wangi, not the
wiki's Wangi - and there is a token for what comes later, uploading.

Danu is a public client registered on OpenGeofiction: its client id is not a
secret, and PKCE stands in for the secret it cannot keep. The flow:

1. A verifier, its S256 challenge and a state are made, and the browser is
   sent to the server's ``/oauth2/authorize`` with them.
2. The server sends the browser back to ``http://127.0.0.1:8116/
   oauth_authorization`` - the redirect registered, so the port is fixed - and
   a loopback listener here takes the code, if the state is the one sent.
3. The code and the verifier are exchanged at ``/oauth2/token`` for a token.
4. ``/api/0.6/user/details.json``, with the token, gives the display name.

The token and the name are kept in the INI (``ogf/token``, ``user/name``),
the INI then readable by its owner alone; and the roles the server gives the
user (``user/roles``) - an administrator is told they are one beside a warning
that the ground is somebody else's. Signing out forgets both and asks
the server to revoke the token; whether it does is not waited on.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QHostAddress, QNetworkAccessManager, QNetworkReply, QNetworkRequest, QTcpServer

CLIENT_ID = 'y7vRkuN2vW_6JwIKeFmLsrOG3UUQWp1fppC8lzRAQUY'
PORT = 8116                     # the redirect registered with the server
PATH = '/oauth_authorization'
SCOPE = 'read_prefs'
WAIT_MS = 5 * 60 * 1000         # a browser not back in five minutes: given up

PAGE = ('<!doctype html><meta charset="utf-8"><title>Danu</title>'
        '<body style="font-family: sans-serif; margin: 3em">{}</body>')


def challenge(verifier: str) -> str:
    """PKCE's S256: the verifier hashed, base64url without padding."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def authorize_url(server: str, redirect: str, state: str, verifier: str) -> str:
    return f'{server}/oauth2/authorize?' + urlencode({
        'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': redirect, 'scope': SCOPE,
        'state': state, 'code_challenge': challenge(verifier), 'code_challenge_method': 'S256'})


def callback(request: bytes) -> tuple[str, dict[str, str]]:
    """The path and query of an HTTP request's first line."""
    line = request.split(b'\r\n', 1)[0].decode('latin-1')
    parts = line.split(' ')
    target = parts[1] if len(parts) > 1 else ''
    url = urlsplit(target)
    return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}


def private(path) -> None:
    """The INI readable by its owner alone: it holds a token now."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class SignIn(QObject):
    """One sign-in at a time: ``start`` opens the browser and listens for it
    to come back; ``signedIn`` with the name and token, or ``failed`` with
    why. ``open_url`` and ``port`` are the tests' to hand in."""

    signedIn = Signal(str, str, list)    # display name, access token, roles
    failed = Signal(str)
    waiting = Signal(str)                # said while the browser is out

    def __init__(self, server: str, parent=None, port: int = PORT, open_url=None,
                 nam: QNetworkAccessManager | None = None):
        super().__init__(parent)
        self.server = server.rstrip('/')
        self.port = port
        self.open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.nam = nam or QNetworkAccessManager(self)
        self.listener: QTcpServer | None = None
        self.state = self.verifier = ''
        self._read: dict = {}                # what each connection has sent so far
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(WAIT_MS)
        self._timer.timeout.connect(lambda: self._fail('the browser did not come back - sign in again'))

    @property
    def redirect(self) -> str:
        return f'http://127.0.0.1:{self.port}{PATH}'

    def start(self) -> bool:
        self.stop()
        self.listener = QTcpServer(self)
        if not self.listener.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), self.port):
            why = self.listener.errorString()
            self.listener = None
            self.failed.emit(f'cannot listen on 127.0.0.1:{self.port} for the browser ({why}) - '
                             'is another sign-in open?')
            return False
        if self.port == 0:                   # the tests': whichever port was free
            self.port = self.listener.serverPort()
        self.listener.newConnection.connect(self._connected)
        self.state = secrets.token_urlsafe(24)
        self.verifier = secrets.token_urlsafe(64)
        self._timer.start()
        self.waiting.emit('signing in to OGF in the browser…')
        self.open_url(authorize_url(self.server, self.redirect, self.state, self.verifier))
        return True

    def stop(self) -> None:
        self._timer.stop()
        if self.listener is not None:
            self.listener.close()
            self.listener.deleteLater()
            self.listener = None

    # ---------------------------------------------------- the browser back
    def _connected(self) -> None:
        while self.listener is not None and self.listener.hasPendingConnections():
            sock = self.listener.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._request(s))

    def _request(self, sock) -> None:
        data = self._read.pop(sock, b'') + bytes(sock.readAll())
        if b'\r\n\r\n' not in data and b'\n\n' not in data:
            self._read[sock] = data                   # the rest to come
            return
        path, query = callback(data)
        if path != PATH:
            self._answer(sock, 404, 'Not here.')
            return
        if query.get('state') != self.state or not self.state:
            self._answer(sock, 400, 'This sign-in is not the one Danu started. Close this tab and sign in again.')
            return
        if 'error' in query:
            self._answer(sock, 200, 'Danu was not given access. You can close this tab.')
            self._fail(f'the server said {query.get("error_description") or query["error"]}')
            return
        code = query.get('code')
        if not code:
            self._answer(sock, 400, 'No code came back. Close this tab and sign in again.')
            return
        self._answer(sock, 200, 'Signed in to Danu. You can close this tab and go back to it.')
        self.stop()
        self._exchange(code)

    @staticmethod
    def _answer(sock, status: int, text: str) -> None:
        body = PAGE.format(text).encode('utf-8')
        reason = {200: 'OK', 400: 'Bad Request', 404: 'Not Found'}[status]
        sock.write(f'HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\n'
                   f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode('ascii') + body)
        sock.flush()
        sock.disconnectFromHost()

    # ------------------------------------------------------- the server
    def _exchange(self, code: str) -> None:
        req = QNetworkRequest(QUrl(f'{self.server}/oauth2/token'))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/x-www-form-urlencoded')
        body = urlencode({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.redirect,
                          'client_id': CLIENT_ID, 'code_verifier': self.verifier})
        reply = self.nam.post(req, QByteArray(body.encode('ascii')))
        reply.finished.connect(lambda: self._token(reply))

    def _token(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail(f'the token was refused: {reply.errorString()}')
            return
        try:
            token = json.loads(bytes(reply.readAll()))['access_token']
        except (ValueError, KeyError, TypeError):
            self._fail('the server answered with no token')
            return
        details(self.nam, self.server, token, lambda name, roles: self.signedIn.emit(name, token, roles), self._fail)

    def _fail(self, why: str) -> None:
        self.stop()
        self.failed.emit(why)


def details(nam: QNetworkAccessManager, server: str, token: str, ok, failed, refused=None) -> QNetworkReply:
    """The display name the token is for, and its roles on the server -
    ``administrator``, ``moderator`` - as ``ok(name, roles)``; ``refused(why)`` if
    the server no longer takes the token - expired, or revoked - and
    ``failed(why)`` for anything else, the server not reached among it."""
    req = QNetworkRequest(QUrl(f'{server.rstrip("/")}/api/0.6/user/details.json'))
    req.setRawHeader(b'Authorization', f'Bearer {token}'.encode('ascii'))
    reply = nam.get(req)

    def done():
        reply.deleteLater()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status == 401:
            (refused or failed)('the server no longer takes the token - sign in again')
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            failed(f'could not ask who is signed in: {reply.errorString()}')
            return
        try:
            user = json.loads(bytes(reply.readAll()))['user']
            name, roles = user['display_name'], [str(r) for r in user.get('roles', [])]
        except (ValueError, KeyError, TypeError):
            failed('the server did not say who is signed in')
            return
        ok(name, roles)
    reply.finished.connect(done)
    return reply


def revoke(nam: QNetworkAccessManager, server: str, token: str) -> QNetworkReply:
    """The token given back to the server: asked, not waited on."""
    req = QNetworkRequest(QUrl(f'{server.rstrip("/")}/oauth2/revoke'))
    req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/x-www-form-urlencoded')
    reply = nam.post(req, QByteArray(urlencode({'token': token, 'client_id': CLIENT_ID}).encode('ascii')))
    reply.finished.connect(reply.deleteLater)
    return reply
