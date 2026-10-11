"""Signing in to OGF (H6f), against a stand-in for the server: a thread
answering /oauth2/token, /api/0.6/user/details.json and /oauth2/revoke as
openstreetmap-website does, and the browser played by a GET to the loopback
listener with what the server would have sent it back with."""

import json
import os
import stat
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip('PySide6')
from PySide6.QtNetwork import QHostAddress, QTcpServer

from danu.ui import oauth


class FakeOgf:
    """The server's three ends. ``tokens`` the ones it takes; the code it
    hands the browser is CODE, good once, against the challenge it was given."""
    CODE = 'the-code'

    def __init__(self):
        self.challenge = None
        self.tokens = {'tok-1': 'wangi'}
        self.roles: list[str] = []
        self.revoked: list[str] = []
        self.refuse_token = False
        outer = self

        class H(BaseHTTPRequestHandler):
            # a connection opened and never written to - Qt's, on Windows,
            # held the one-at-a-time server and so its shutdown for ever
            timeout = 5

            def log_message(self, *a):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode()).items()}
                if self.path == '/oauth2/token':
                    ok = (not outer.refuse_token and form.get('code') == outer.CODE
                          and form.get('client_id') == oauth.CLIENT_ID
                          and oauth.challenge(form.get('code_verifier', '')) == outer.challenge)
                    self._send(200, {'access_token': 'tok-1', 'token_type': 'Bearer'}) if ok \
                        else self._send(400, {'error': 'invalid_grant'})
                elif self.path == '/oauth2/revoke':
                    outer.revoked.append(form.get('token'))
                    self._send(200, {})

            def do_GET(self):
                if self.path == '/api/0.6/user/details.json':
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    if token in outer.tokens:
                        self._send(200, {'user': {'id': 1, 'display_name': outer.tokens[token], 'roles': outer.roles}})
                    else:
                        self._send(401, {})
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.http.daemon_threads = True
        self.closed = False
        self.url = f'http://127.0.0.1:{self.http.server_port}'
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        if not self.closed:
            self.closed = True
            self.http.shutdown()
            self.http.server_close()


@pytest.fixture
def ogf():
    f = FakeOgf()
    yield f
    f.close()


@pytest.fixture
def w(window, ogf):
    window.settings.set_url('ogf/server', ogf.url)
    opened = []
    window._signin_options = {'port': 0, 'open_url': opened.append}
    window.opened = opened
    return window


def browse(url):
    """The browser, back at the loopback with what the server sent it: on a
    thread, the listener answering on the window's."""
    out = {}

    def go():
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                out['status'], out['body'] = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            out['status'], out['body'] = e.code, e.read().decode()
    t = threading.Thread(target=go)
    t.start()
    return t, out


def sign_in(w, ogf, qtbot, **back):
    w.account_action.trigger()
    assert len(w.opened) == 1
    url = urlsplit(w.opened[0])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    ogf.challenge = q['code_challenge']
    params = {'code': ogf.CODE, 'state': q['state'], **back}
    t, out = browse(f'{q["redirect_uri"]}?' + '&'.join(f'{k}={v}' for k, v in params.items()))
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=10000)
    return q, out


def test_the_browser_is_sent_to_authorize_with_pkce(w, ogf, qtbot):
    w.account_action.trigger()
    url = urlsplit(w.opened[0])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f'{url.scheme}://{url.netloc}{url.path}' == f'{ogf.url}/oauth2/authorize'
    assert q['client_id'] == oauth.CLIENT_ID and q['scope'] == 'read_prefs' and q['response_type'] == 'code'
    assert q['code_challenge_method'] == 'S256' and q['code_challenge'] == oauth.challenge(w.signin.verifier)
    assert q['redirect_uri'] == f'http://127.0.0.1:{w.signin.port}/oauth_authorization'
    assert len(q['state']) >= 24
    w.signin.stop()


def test_the_registered_redirect_is_8116():
    assert oauth.SignIn('https://x').redirect == 'http://127.0.0.1:8116/oauth_authorization'


def test_signing_in_keeps_the_servers_name_and_the_token(w, ogf, qtbot):
    _q, out = sign_in(w, ogf, qtbot)
    assert out['status'] == 200 and 'Signed in' in out['body']
    qtbot.waitUntil(lambda: w.settings.token == 'tok-1', timeout=10000)
    assert w.settings.user == 'wangi'
    assert w.account_action.text().replace('&', '') == 'Sign out (wangi)'
    assert 'signed in to OGF as wangi' in w.statusBar().currentMessage()
    assert w.signin.listener is None, 'still listening'
    if os.name == 'posix':
        assert stat.S_IMODE(os.stat(w.settings.file).st_mode) == 0o600


def test_the_signed_in_name_is_whose_ground_it_is(w, ogf, qtbot):
    qtbot.waitUntil(lambda: 'Pizarrales' in w._territory.text(), timeout=5000)
    ogf.tokens['tok-1'] = 'Luciano'
    sign_in(w, ogf, qtbot)
    qtbot.waitUntil(lambda: w.settings.token == 'tok-1', timeout=10000)
    assert not w._territory.text().startswith('not yours'), 'Luciano owns it'


def test_a_state_not_the_one_sent_is_refused(w, ogf, qtbot):
    _q, out = sign_in(w, ogf, qtbot, state='forged')
    assert out['status'] == 400 and not w.settings.token
    assert w.signin.listener is not None, 'the real one may still come'
    w.signin.stop()


def test_access_refused_in_the_browser_says_so(w, ogf, qtbot):
    _q, out = sign_in(w, ogf, qtbot, error='access_denied')
    assert out['status'] == 200 and not w.settings.token
    assert 'not signed in: the server said access_denied' in w.statusBar().currentMessage()


def test_a_token_refused_says_so(w, ogf, qtbot):
    ogf.refuse_token = True
    sign_in(w, ogf, qtbot)
    qtbot.waitUntil(lambda: 'not signed in' in w.statusBar().currentMessage(), timeout=10000)
    assert 'the token was refused' in w.statusBar().currentMessage() and not w.settings.token


def test_signing_out_forgets_and_revokes(w, ogf, qtbot):
    sign_in(w, ogf, qtbot)
    qtbot.waitUntil(lambda: w.settings.token == 'tok-1', timeout=10000)
    w.account_action.trigger()
    assert not w.settings.token and not w.settings.user
    assert w.account_action.text().replace('&', '') == 'Sign in to OGF…'
    qtbot.waitUntil(lambda: ogf.revoked == ['tok-1'], timeout=10000)


def test_a_kept_token_the_server_no_longer_takes_is_forgotten_at_start(w, ogf, qtbot):
    w.settings.token, w.settings.user = 'tok-old', 'wangi'
    w._check_signed_in()
    qtbot.waitUntil(lambda: not w.settings.token, timeout=10000)
    assert not w.settings.user and 'signed out of OGF' in w.statusBar().currentMessage()


def test_a_kept_token_is_kept_when_the_server_cannot_be_reached(w, ogf, qtbot):
    w.settings.token, w.settings.user = 'tok-1', 'wangi'
    ogf.close()
    w._check_signed_in()
    qtbot.waitUntil(lambda: 'OGF: could not ask' in w.statusBar().currentMessage(), timeout=10000)
    assert w.settings.token == 'tok-1' and w.settings.user == 'wangi'


def test_a_kept_token_renamed_on_the_server_takes_the_new_name(w, ogf, qtbot):
    w.settings.token, w.settings.user = 'tok-1', 'Wangi'
    w._check_signed_in()
    qtbot.waitUntil(lambda: w.settings.user == 'wangi', timeout=10000)
    assert w.account_action.text().replace('&', '') == 'Sign out (wangi)'


def test_the_port_taken_says_so(w, qtbot):
    held = QTcpServer()
    assert held.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0)
    w._signin_options['port'] = held.serverPort()
    w.account_action.trigger()
    assert 'cannot listen on 127.0.0.1' in w.statusBar().currentMessage() and not w.opened
    held.close()


def test_the_manual_username_is_gone(window):
    texts = [a.text().replace('&', '') for a in window.menuBar().actions()[0].menu().actions()]
    assert 'Your OGF username…' not in texts and 'Sign in to OGF…' in texts


def test_a_request_in_two_reads_is_put_together():
    path, q = oauth.callback(b'GET /oauth_authorization?code=a&state=b HTTP/1.1\r\nHost: x\r\n\r\n')
    assert path == '/oauth_authorization' and q == {'code': 'a', 'state': 'b'}


def test_an_administrator_is_warned_as_anyone_and_told_they_are_one(w, ogf, qtbot):
    """So that it is seen: an administrator may draw anywhere, but needs to
    know when it is somebody else's ground."""
    qtbot.waitUntil(lambda: 'Pizarrales' in w._territory.text(), timeout=5000)
    ogf.roles = ['administrator']
    sign_in(w, ogf, qtbot)
    qtbot.waitUntil(lambda: w.settings.token == 'tok-1', timeout=10000)
    assert w.settings.roles == ['administrator'] and w.settings.admin
    assert w._territory.text() == 'not yours to draw: Pizarrales (AR031), owned by Luciano (administrator)'
    assert 'an administrator' in w.statusBar().currentMessage()
    w.account_action.trigger()                                          # signed out: no longer
    assert not w.settings.admin


def test_a_moderator_is_warned_as_anyone(w, ogf, qtbot):
    qtbot.waitUntil(lambda: 'Pizarrales' in w._territory.text(), timeout=5000)
    ogf.roles = ['moderator']
    sign_in(w, ogf, qtbot)
    qtbot.waitUntil(lambda: w.settings.token == 'tok-1', timeout=10000)
    assert w._territory.text().startswith('not yours to draw')


def test_roles_changed_on_the_server_are_taken_at_start(w, ogf, qtbot):
    w.settings.token, w.settings.user = 'tok-1', 'wangi'
    ogf.roles = ['administrator']
    w._check_signed_in()
    qtbot.waitUntil(lambda: w.settings.admin, timeout=10000)


def test_roles_left_without_a_token_are_no_one(w, qtbot):
    qtbot.waitUntil(lambda: 'Pizarrales' in w._territory.text(), timeout=5000)
    w.settings.user, w.settings.roles = 'wangi', ['administrator']
    w.show_territory()
    assert '(administrator)' not in w._territory.text()


def test_a_request_anywhere_else_on_the_listener_is_not_found(w, ogf, qtbot):
    w.account_action.trigger()
    t, out = browse(f'http://127.0.0.1:{w.signin.port}/elsewhere')
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=10000)
    assert out['status'] == 404 and w.signin.listener is not None
    w.signin.stop()


def test_the_challenge_is_unpadded_base64url_of_sha256():
    """SHA-256 of "abc" is ba7816bf...f20015ad, the standard's test vector."""
    assert oauth.challenge('abc') == 'ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0'
