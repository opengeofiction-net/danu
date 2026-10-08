"""Show in JOSM - its remote control's /zoom, for the water and peaks fixed on
the main map. JOSM is a server on a port of the loopback each test picks,
answering as JOSM does; nothing leaves the machine."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip('PySide6')

from danu.core.square import Node, SquareName, Way
from danu.ui import josm
from danu.ui.tools import Selection

NORTH = SquareName(125, -23)


class FakeJosm:
    def __init__(self, status=200, body=b'OK\r\n'):
        asked = self.asked = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                asked.append(self.path)
                self.send_response(status)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    f = FakeJosm()
    yield f
    f.close()


def test_the_url_is_the_box_and_the_main_maps_objects():
    url = josm.zoom_url('http://127.0.0.1:8111/', (86.9, 20.3, 87.0, 20.4), ['node103957807', 'way5'])
    assert url == ('http://127.0.0.1:8111/zoom?left=86.9000000&right=87.0000000&top=20.4000000'
                   '&bottom=20.3000000&select=node103957807,way5')
    assert 'select' not in josm.zoom_url(josm.DEFAULT_URL, (0, 0, 1, 1))


def test_only_what_came_from_the_main_map_is_selected():
    w = Way(id=-5, refs=[], tags={})
    assert josm.selected_ids(Selection(None, w, -3)) == []
    river = Way(id=77, refs=[], tags={'waterway': 'river'})
    assert josm.selected_ids(Selection(None, river, 12)) == ['node12', 'way77']
    assert josm.selected_ids(Selection(None, None, 103957807)) == ['node103957807']
    assert josm.selected_ids(None) == []


def test_j_shows_the_place_and_selects_the_spot_height_in_josm(window, fake, qtbot):
    w = window
    w.josm.base = fake.url
    sq = w.working_set.squares[NORTH]
    sq.nodes[103957807] = Node(id=103957807, lon=125.5, lat=-22.5,
                               tags={'natural': 'peak', 'name': 'Colonie Hill', 'ele': '698'})
    w.editor.selection = Selection(sq, None, 103957807)
    w.map.center_on_lonlat(125.5, -22.5)
    assert w.edit_actions['view.josm'].shortcut().toString() == 'J'
    w.edit_actions['view.josm'].trigger()
    qtbot.waitUntil(lambda: 'JOSM: ' in w.statusBar().currentMessage(), timeout=5000)
    (path,) = fake.asked
    q = parse_qs(urlparse(path).query)
    assert urlparse(path).path == '/zoom' and q['select'] == ['node103957807']
    left, right, top, bottom = (float(q[k][0]) for k in ('left', 'right', 'top', 'bottom'))
    assert left < 125.5 < right and bottom < -22.5 < top, 'not the place shown'
    assert 'selecting node103957807' in w.statusBar().currentMessage()


def test_a_contour_drawn_here_is_the_place_alone(window, fake, qtbot):
    w = window
    w.josm.base = fake.url
    sq = w.working_set.squares[NORTH]
    w.editor.selection = Selection(sq, Way(id=-42, refs=[], tags={'ele': '100'}))
    w.checks_dock.josm_btn.click()
    qtbot.waitUntil(lambda: bool(fake.asked), timeout=5000)
    assert 'select' not in fake.asked[0]
    qtbot.waitUntil(lambda: 'not in JOSM' in w.statusBar().currentMessage(), timeout=5000)


def test_josm_not_running_is_said(window, qtbot):
    w = window
    f = FakeJosm()
    url = f.url
    f.close()                                      # the port is free again: nothing listens
    w.josm.base = url
    w.gone_dock.josm_btn.click()
    qtbot.waitUntil(lambda: 'JOSM is not answering' in w.statusBar().currentMessage(), timeout=5000)
    assert 'Remote Control in its preferences' in w.statusBar().currentMessage()


def test_josms_refusal_is_said_in_its_words(window, qtbot):
    w = window
    f = FakeJosm(400, b'Bad Request: The following keys are mandatory, but have not been given: left')
    try:
        w.josm.base = f.url
        w.show_in_josm()
        qtbot.waitUntil(lambda: 'JOSM refused it' in w.statusBar().currentMessage(), timeout=5000)
        assert 'mandatory' in w.statusBar().currentMessage()
    finally:
        f.close()
