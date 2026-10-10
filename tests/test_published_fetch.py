"""Fetching the published DEM (H3c): once a build, kept when the server is not
there. Against a server on the loopback, not the real one."""

import http.server
import os
import threading
import time

import pytest

from danu.core.published import fetch


@pytest.fixture
def server(tmp_path):
    root = tmp_path / 'served'
    (root / 'gobras').mkdir(parents=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *_):
            pass
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f'http://127.0.0.1:{httpd.server_address[1]}'
    httpd.shutdown()


def test_fetched_once_then_unchanged_until_the_server_has_another(server, tmp_path):
    root, base = server
    served = root / 'gobras' / 'dem-gobras.tif'
    served.write_bytes(b'first')
    t = time.time() - 86400
    os.utime(served, (t, t))
    into = tmp_path / 'cache' / 'gobras' / 'dem-gobras.tif'
    url = f'{base}/gobras/dem-gobras.tif'
    assert fetch(url, into) == (into, 'fetched') and into.read_bytes() == b'first'
    assert abs(into.stat().st_mtime - t) < 2, 'the server\'s date kept, to ask again by'
    assert fetch(url, into) == (into, 'unchanged')
    served.write_bytes(b'second')                     # the server built again
    assert fetch(url, into)[1] == 'fetched' and into.read_bytes() == b'second'


def test_a_zone_with_none_published_says_so(server, tmp_path):
    _, base = server
    with pytest.raises(FileNotFoundError, match='no published DEM'):
        fetch(f'{base}/nowhere/dem-nowhere.tif', tmp_path / 'c' / 'x.tif')


def test_a_server_not_there_keeps_the_copy_held(server, tmp_path):
    into = tmp_path / 'cache' / 'dem-gobras.tif'
    into.parent.mkdir(parents=True)
    into.write_bytes(b'held')
    path, what = fetch('http://127.0.0.1:9/dem-gobras.tif', into, timeout=2)
    assert path == into and what.startswith('kept:') and into.read_bytes() == b'held'
    with pytest.raises(OSError):
        fetch('http://127.0.0.1:9/dem-gobras.tif', tmp_path / 'none.tif', timeout=2)
