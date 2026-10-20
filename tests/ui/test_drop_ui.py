"""The data drop in the editor (#190, N4): the status line from the API's
answer, and a shared square's ground shaded."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip('PySide6')

from danu.core.square import SquareName
from danu.ui import drop

SERVER = 'https://ogf.example'


def test_the_line_for_each_answer():
    d = lambda status, body: drop.describe(status, body, SERVER)  # noqa: E731
    line, warn = d(404, {'error': 'N30E086 is in no zone', 'square': 'N30E086'})
    assert warn and 'N30E086 is in no zone' in line
    assert '<a href="https://ogf.example/message/new/admin">message admin</a>' in line
    assert d(200, {'square': 'N20E086', 'zone': 'gobras', 'held': None}) == \
        ('zone gobras - sign in to see whether it is yours to upload', False)
    perm = lambda level, others=(): {'level': level, 'mine': [], 'others': [{'name': n} for n in others]}  # noqa: E731
    base = {'square': 'N20E086', 'zone': 'gobras', 'user': 'wangi', 'admin': False}
    assert d(200, {**base, 'permission': perm('yes')}) == ('zone gobras - yours to upload', False)
    line, warn = d(200, {**base, 'permission': perm('partial', ['Elsewhere', 'Beyond'])})
    assert not warn and 'shared with Elsewhere, Beyond' in line and '10 km' in line
    assert d(200, {**base, 'permission': perm('no', ['Elsewhere'])}) == ('zone gobras - not yours to upload: Elsewhere', True)
    assert d(200, {**base, 'admin': True, 'permission': perm('no', ['Elsewhere'])}) == \
        ('zone gobras - not your territory (Elsewhere), yours to upload as an administrator', False)
    # an administrator whose territory it is is its owner first
    owned = {'level': 'yes', 'mine': [{'name': 'Gobrassanya', 'ogfId': 'UL05a'}], 'others': []}
    assert d(200, {**base, 'admin': True, 'permission': owned}) == ('zone gobras - yours to upload: Gobrassanya', False)
    shared = {**perm('partial', ['Elsewhere']), 'mine': [{'name': 'Gobrassanya'}]}
    assert 'shared with Elsewhere' in d(200, {**base, 'admin': True, 'permission': shared})[0]
    assert d(200, {**base, 'zone': '<b>', 'permission': perm('yes')})[0] == 'zone &lt;b&gt; - yours to upload'
    line, warn = d(200, {**base, 'blocked': True, 'permission': perm('yes')})
    assert warn and '<a href="https://ogf.example/user/wangi/blocks">blocked on OGF</a>' in line
    line, _ = d(200, {**base, 'user': 'Aaron Trott', 'blocked': True})
    assert 'href="https://ogf.example/user/Aaron%20Trott/blocks"' in line
    assert d(503, {'error': 'the territories have not been read yet'}) == \
        ('upload: the territories have not been read yet', False)


class _Api(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):
        _Api.seen.append((self.path, self.headers.get('Authorization'), self.headers.get('User-Agent')))
        if self.path == '/api/squares/N30E086':
            status, body = 404, {'error': 'in no zone', 'square': 'N30E086'}
        elif self.headers.get('Authorization') == 'Bearer tok':
            status, body = 200, {'square': 'S24E125', 'zone': 'pizarrales', 'user': 'Luciano', 'admin': False,
                                 'permission': {'level': 'yes', 'mine': [], 'others': []}}
        else:
            status, body = 200, {'square': 'S24E125', 'zone': 'pizarrales'}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def api():
    _Api.seen = []
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _Api)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{httpd.server_address[1]}/api'
    httpd.shutdown()
    httpd.server_close()


def test_the_client_asks_with_the_token_and_the_last_question_wins(qtbot, qapp, api):
    c = drop.DropClient(api, SERVER, parent=qapp)
    got = []
    c.answered.connect(lambda *a: got.append(a))
    with qtbot.waitSignal(c.answered, timeout=5000):
        c.ask(SquareName.parse('S24E125'), 'tok')
    assert got[-1] == ('S24E125', 'zone pizarrales - yours to upload', False)
    path, auth, agent = _Api.seen[-1]
    assert path == '/api/squares/S24E125' and auth == 'Bearer tok' and agent.startswith('Danu/')
    with qtbot.waitSignal(c.answered, timeout=5000):
        c.ask(SquareName.parse('N30E086'))
    assert got[-1][0] == 'N30E086' and got[-1][2] and _Api.seen[-1][1] is None
    got.clear()
    c.ask(SquareName.parse('S24E125'))
    with qtbot.waitSignal(c.answered, timeout=5000):
        c.ask(SquareName.parse('N30E086'))
    qtbot.wait(200)
    assert [a[0] for a in got] == ['N30E086'], 'the first, asked over, never answers'


def test_the_service_not_reached_is_said_quietly(qtbot, qapp):
    c = drop.DropClient('http://127.0.0.1:9/api', SERVER, parent=qapp)
    with qtbot.waitSignal(c.answered, timeout=10000) as sig:
        c.ask(SquareName.parse('S24E125'))
    assert sig.args == ['S24E125', 'upload service not reached', False]


def test_the_window_says_the_open_squares_zone(window, qtbot, api):
    w = window
    w.drop.base_url = api
    w._drop_asked = None
    w.show_ground()
    qtbot.waitUntil(lambda: 'pizarrales' in w._drop.text(), timeout=5000)
    assert w._drop.text() == 'zone pizarrales - sign in to see whether it is yours to upload'
    w.settings.user, w.settings.token = 'Luciano', 'tok'
    w.show_ground()
    qtbot.waitUntil(lambda: 'yours to upload' in w._drop.text() and 'sign in' not in w._drop.text(), timeout=5000)
    asked = len(_Api.seen)
    w.show_ground()
    qtbot.wait(300)
    assert len(_Api.seen) == asked, 'the same square and token: not asked again'


def test_the_window_shades_a_shared_square_for_its_mapper(window, qtbot):
    pytest.importorskip('osgeo.ogr', reason='the shading is GDAL\'s')
    w = window
    qtbot.waitUntil(lambda: w.territory.complete, timeout=5000)
    w.show_ground()
    assert not w.ground.shaded(), 'nobody signed in'
    # S24E126, east of the open square, is half Luciano's and half admin's
    w.settings.user, w.settings.token = 'Luciano', 'tok'
    w.show_ground()
    assert w.ground.shaded()
    w.view_actions['view.ground'].setChecked(False)
    assert not w.ground.shaded() and not w.surface_panel.show_ground.isChecked()
    w.surface_panel.show_ground.setChecked(True)
    assert w.ground.shaded() and w.view_actions['view.ground'].isChecked()
    w.settings.roles = ['administrator']
    w.show_ground()
    assert w.ground.shaded(), 'an administrator is shown whose ground it is too'
    w.settings.token = ''
    w.show_ground()
    assert not w.ground.shaded(), 'signed out'


def test_whose_ground_off_is_kept_with_the_session(window):
    from danu.ui import session
    window.surface_panel.show_ground.setChecked(False)
    data = session.capture(window)
    assert data['surface']['ground'] is False
    window.surface_panel.show_ground.setChecked(True)
    session.restore(window, {**data, 'set': None})
    assert not window.surface_panel.show_ground.isChecked()
