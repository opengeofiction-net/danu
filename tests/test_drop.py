"""danu.drop: the data drop's API (#190), against a fake OGF and a zone on disk."""

import hashlib
import io
import json
import lzma
import os
import threading

import pytest

# the drop runs on the server, which is Linux, and locks with fcntl
pytest.importorskip('fcntl', reason='the data drop is the server\'s: no fcntl here')

from danu.core import territory as T
from danu.core import zones as Z
from danu.core.square import SquareName as S
from danu.drop import app as A
from danu.drop.sources import OgfUsers, Territories, Unknown, User

# lon 86..87 is wangi's; 87..88 is half wangi's, half Luciano's; 88..89
# Luciano's, delegated to Mie as well; 89..90 is nobody's, the sea
GEOMETRY = {
    '1': [[20, 86], [21, 86], [21, 87.5], [20, 87.5]],
    '2': [[20, 87.5], [21, 87.5], [21, 89], [20, 89]],
}
ATTRIBUTES = [
    {'ogfId': 'UL05a', 'name': 'Gobrassanya', 'rel': 1, 'status': 'owned', 'owner': 'wangi'},
    {'ogfId': 'UL05b', 'name': 'Elsewhere', 'rel': 2, 'status': 'owned', 'owner': 'Luciano',
     'constraints': ['dem:Mie']},
]
USERS = {'t-wangi': User('wangi'), 't-luciano': User('Luciano'), 't-mie': User('Mie'),
         't-admin': User('Admin', ('administrator',)), 't-nobody': User('nobody')}

ZONES = 'gobras          N20E086-N20E089   # the test zone\n'


def osm(n: int = 1) -> bytes:
    nodes = ''.join(f"<node id='-{i}' lat='20.5' lon='86.5'><tag k='ele' v='{i}'/></node>" for i in range(1, n + 1))
    return lzma.compress(f"<?xml version='1.0'?><osm version='0.6' upload='never'>{nodes}</osm>".encode())


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeTerritories:
    def __init__(self):
        self.idx = T.TerritoryIndex(T.parse_geometry(json.dumps(GEOMETRY)), T.parse_attributes(json.dumps(ATTRIBUTES)))

    def index(self):
        return self.idx


def fake_users(token):
    if token not in USERS:
        raise Unknown(401, 'OGF does not take this sign-in: sign in again')
    return USERS[token]


@pytest.fixture
def drop(tmp_path):
    base, pub = tmp_path / 'elevation', tmp_path / 'publish'
    (base / 'osm-squares' / 'gobras').mkdir(parents=True)
    (base / 'zones').write_text(ZONES)
    (base / 'inactive').write_text('# hand comments\nteirolask   wip        # kept\n')
    sq = base / 'osm-squares' / 'gobras'
    (sq / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(1))
    (sq / 'EMPTY.osm.xz').write_bytes(osm(0))
    app = A.DropApp(A.Config(base, pub, max_bytes=1 << 20), fake_users, FakeTerritories())
    app.base, app.pub = base, pub
    return app


def call(app, method, path, body=b'', token=None, headers=None, query=''):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': query,
               'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
    if token:
        environ['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    for k, v in (headers or {}).items():
        environ['HTTP_' + k.upper().replace('-', '_')] = v
    got = {}

    def start(status, hdrs):
        got['status'], got['headers'] = int(status.split()[0]), dict(hdrs)
    data = b''.join(app(environ, start))
    ctype = got['headers'].get('Content-Type')
    return got['status'], (json.loads(data) if ctype == 'application/json' else data), got['headers']


# ------------------------------------------------------------------ reading

def test_reading_needs_no_sign_in(drop):
    status, body, _ = call(drop, 'GET', '/zones')
    assert status == 200 and body == {'zones': [{'name': 'gobras', 'squares': ['N20E086-N20E089'], 'inactive': None}]}
    status, body, _ = call(drop, 'GET', '/zones/gobras')
    (held,) = body['held']
    assert held['file'] == 'N20E086_Gobras_City.osm.xz' and held['label'] == 'Gobras_City'
    assert held['sha256'] == sha(osm(1)), 'EMPTY.osm.xz is not a square'
    status, data, headers = call(drop, 'GET', '/zones/gobras/N20E086_Gobras_City.osm.xz')
    assert status == 200 and data == osm(1) and headers['ETag'] == f'"{sha(osm(1))}"'
    status, _, _ = call(drop, 'GET', '/zones/gobras/N20E086_Gobras_City.osm.xz', headers={'If-None-Match': f'"{sha(osm(1))}"'})
    assert status == 304
    assert call(drop, 'GET', '/zones/gobras/../zones')[0] == 404
    assert call(drop, 'GET', '/zones/nowhere')[0] == 404


def test_a_square_says_its_zone_and_signed_in_its_permission(drop):
    status, body, headers = call(drop, 'GET', '/squares/N20E086')
    assert status == 200 and body['zone'] == 'gobras' and 'permission' not in body
    assert headers['ETag'] == f'"{sha(osm(1))}"'
    _, body, _ = call(drop, 'GET', '/squares/n20e087', token='t-wangi')
    assert body['held'] is None and body['permission']['level'] == 'partial'
    assert [t['ogfId'] for t in body['permission']['others']] == ['UL05b']
    _, body, _ = call(drop, 'GET', '/squares/N20E088', token='t-mie')
    assert body['permission']['level'] == 'yes', 'a dem: delegate'
    status, body, _ = call(drop, 'GET', '/squares/N30E086')
    assert status == 404 and 'in no zone' in body['error']
    assert call(drop, 'GET', '/squares/nonsense')[0] == 404
    assert call(drop, 'GET', '/squares/N20E086', token='t-forged')[0] == 401


# ------------------------------------------------------------------ uploading

def test_an_upload_replaces_the_square_in_both_copies(drop):
    new = osm(3)
    status, body, headers = call(drop, 'PUT', '/squares/N20E086', new, 't-wangi', {'If-Match': f'"{sha(osm(1))}"'})
    assert status == 200 and body['sha256'] == sha(new) and headers['ETag'] == f'"{sha(new)}"'
    work = drop.base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz'
    pub = drop.pub / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz'
    assert work.read_bytes() == new and pub.read_bytes() == new, 'the label kept'
    assert os.stat(work).st_mtime_ns == os.stat(pub).st_mtime_ns, 'the nightly copy finds nothing newer'
    (kept,) = (drop.base / 'drop' / 'kept' / 'gobras').iterdir()
    assert kept.read_bytes() == osm(1) and not str(kept).startswith(str(drop.base / 'osm-squares'))
    (line,) = (drop.base / 'drop' / 'log.jsonl').read_text().splitlines()
    log = json.loads(line)
    assert log['user'] == 'wangi' and log['action'] == 'put' and log['was'] == sha(osm(1)) and log['sha256'] == sha(new)
    assert not [p for p in work.parent.iterdir() if p.name.startswith('.')], 'nothing left spooled'


def test_a_stale_version_is_refused_with_the_one_held(drop):
    status, body, headers = call(drop, 'PUT', '/squares/N20E086', osm(2), 't-wangi', {'If-Match': '"0123"'})
    assert status == 412 and headers['ETag'] == f'"{sha(osm(1))}"' and 'changed' in body['error']
    status, body, _ = call(drop, 'PUT', '/squares/N20E086', osm(2), 't-wangi')
    assert status == 428, 'no version said'
    status, _, _ = call(drop, 'PUT', '/squares/N20E086', osm(2), 't-wangi', {'If-None-Match': '*'})
    assert status == 412, 'new, but it exists'
    assert (drop.base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz').read_bytes() == osm(1)


def test_a_new_square_with_a_label_and_one_nobody_may_upload(drop):
    status, body, _ = call(drop, 'PUT', '/squares/N20E087', osm(2), 't-luciano', {'If-None-Match': '*'}, 'label=Artana')
    assert status == 201 and body['file'] == 'N20E087_Artana.osm.xz', 'partial may upload'
    assert (drop.pub / 'osm-squares' / 'gobras' / 'N20E087_Artana.osm.xz').read_bytes() == osm(2)
    status, body, _ = call(drop, 'PUT', '/squares/N20E088', osm(2), 't-wangi', {'If-None-Match': '*'})
    assert status == 403 and body['permission']['level'] == 'no'
    status, _, _ = call(drop, 'PUT', '/squares/N20E089', osm(2), 't-wangi', {'If-None-Match': '*'})
    assert status == 403, 'the sea: an administrator\'s'
    status, _, _ = call(drop, 'PUT', '/squares/N20E089', osm(2), 't-admin', {'If-None-Match': '*'})
    assert status == 201
    assert call(drop, 'PUT', '/squares/N20E088', osm(2), None, {'If-None-Match': '*'})[0] == 401
    assert call(drop, 'PUT', '/squares/N30E086', osm(2), 't-admin', {'If-None-Match': '*'})[0] == 404


@pytest.mark.parametrize('body, why', [
    (b'plain text', 'not xz'),
    (lzma.compress(b'<html/>'), 'root is <html>'),
    (lzma.compress(b"<osm><node id='1'"), 'well-formed'),
    (osm(1)[:-20], 'whole'),
])
def test_what_is_not_a_square_file_is_refused(drop, body, why):
    status, got, _ = call(drop, 'PUT', '/squares/N20E087', body, 't-wangi', {'If-None-Match': '*'})
    assert status == 422 and why in got['error']
    assert not list((drop.base / 'osm-squares' / 'gobras').glob('N20E087*'))
    assert not [p for p in (drop.base / 'osm-squares' / 'gobras').iterdir() if p.name.startswith('.')]


def test_too_large_and_a_bad_label_are_refused(drop):
    big = b'x' * ((1 << 20) + 1)
    assert call(drop, 'PUT', '/squares/N20E087', big, 't-wangi', {'If-None-Match': '*'})[0] == 413
    status, body, _ = call(drop, 'PUT', '/squares/N20E087', osm(1), 't-wangi', {'If-None-Match': '*'}, 'label=a.b')
    assert status == 422 and 'label' in body['error']


def test_an_upload_cut_short_is_refused_and_nothing_left(drop):
    environ = {'REQUEST_METHOD': 'PUT', 'PATH_INFO': '/squares/N20E087', 'QUERY_STRING': '',
               'CONTENT_LENGTH': '5000', 'wsgi.input': io.BytesIO(osm(1)),
               'HTTP_AUTHORIZATION': 'Bearer t-wangi', 'HTTP_IF_NONE_MATCH': '*'}
    got = []
    body = json.loads(b''.join(drop(environ, lambda status, h: got.append(status))))
    assert got[0].startswith('400') and 'ended early' in body['error']
    assert not [p for p in (drop.base / 'osm-squares' / 'gobras').iterdir() if p.name.startswith('.')]


def test_renaming_with_an_upload_or_alone(drop):
    v1 = sha(osm(1))
    status, body, _ = call(drop, 'PUT', '/squares/N20E086', osm(2), 't-wangi', {'If-Match': v1}, 'label=Gobras')
    assert status == 200 and body['file'] == 'N20E086_Gobras.osm.xz'
    names = lambda d: sorted(p.name for p in d.iterdir() if p.name.startswith('N'))  # noqa: E731
    assert names(drop.base / 'osm-squares' / 'gobras') == ['N20E086_Gobras.osm.xz']
    assert names(drop.pub / 'osm-squares' / 'gobras') == ['N20E086_Gobras.osm.xz']
    status, body, _ = call(drop, 'PATCH', '/squares/N20E086', {'label': ''}, 't-wangi', {'If-Match': f'"{sha(osm(2))}"'})
    assert status == 200 and body['file'] == 'N20E086.osm.xz' and body['sha256'] == sha(osm(2))
    assert names(drop.pub / 'osm-squares' / 'gobras') == ['N20E086.osm.xz']
    assert call(drop, 'PATCH', '/squares/N20E086', {'label': 'X'}, 't-wangi', {'If-Match': v1})[0] == 412
    assert call(drop, 'PATCH', '/squares/N20E086', {'label': 'x y'}, 't-wangi', {'If-Match': sha(osm(2))})[0] == 422
    assert call(drop, 'PATCH', '/squares/N20E087', {'label': 'X'}, 't-wangi', {'If-Match': v1})[0] == 404
    actions = [json.loads(x)['action'] for x in (drop.base / 'drop' / 'log.jsonl').read_text().splitlines()]
    assert actions == ['put', 'rename']


def test_deleting_is_for_yes_and_administrators(drop):
    call(drop, 'PUT', '/squares/N20E087', osm(2), 't-wangi', {'If-None-Match': '*'})
    v = f'"{sha(osm(2))}"'
    assert call(drop, 'DELETE', '/squares/N20E087', token='t-wangi', headers={'If-Match': v})[0] == 403, 'partial'
    assert call(drop, 'DELETE', '/squares/N20E087', token='t-admin', headers={'If-Match': '"x"'})[0] == 412
    assert call(drop, 'DELETE', '/squares/N20E087', token='t-admin', headers={'If-Match': v})[0] == 204
    assert not list((drop.pub / 'osm-squares' / 'gobras').glob('N20E087*'))
    assert call(drop, 'DELETE', '/squares/N20E086', token='t-wangi', headers={'If-Match': sha(osm(1))})[0] == 204
    assert sorted(p.name for p in (drop.base / 'drop' / 'kept' / 'gobras').iterdir())[0].startswith('N20E086_Gobras_City')


def test_two_uploads_from_one_version_one_wins(drop):
    v = f'"{sha(osm(1))}"'
    results = []

    def go(n):
        results.append(call(drop, 'PUT', '/squares/N20E086', osm(n), 't-wangi', {'If-Match': v})[0])
    threads = [threading.Thread(target=go, args=(n,)) for n in (2, 3, 4, 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 412, 412, 412]


# ------------------------------------------------------------------ zones

def test_zones_are_an_administrators(drop):
    assert call(drop, 'PUT', '/zones/tekan', {'squares': ['N17E128-N21E130']}, 't-wangi')[0] == 403
    status, body, _ = call(drop, 'PUT', '/zones/tekan', {'squares': ['N17E128-N21E130']}, 't-admin')
    assert status == 201 and body['squares'] == ['N17E128-N21E130']
    assert (drop.base / 'osm-squares' / 'tekan').is_dir()
    status, _, _ = call(drop, 'PUT', '/zones/gobras', {'squares': ['N20E086-N20E090']}, 't-admin')
    assert status == 200
    assert (drop.base / 'zones').read_text().splitlines()[0] == 'gobras          N20E086-N20E090   # the test zone'
    status, body, _ = call(drop, 'PUT', '/zones/other', {'squares': ['N20E090']}, 't-admin')
    assert status == 422 and 'overlap' in body['error']
    assert call(drop, 'PUT', '/zones/Bad', {'squares': ['N0E0']}, 't-admin')[0] == 422
    assert call(drop, 'PUT', '/zones/x', {'squares': 'N20E086'}, 't-admin')[0] == 422


def test_inactive_through_the_api_keeps_the_files_comments(drop):
    status, body, _ = call(drop, 'PUT', '/zones/gobras/inactive', {'reason': 'wip', 'note': 'testing'}, 't-admin')
    assert status == 200 and body['inactive'] == 'wip'
    text = (drop.base / 'inactive').read_text()
    assert text.startswith('# hand comments\nteirolask   wip        # kept\n') and 'gobras      wip        # testing' in text
    assert call(drop, 'GET', '/zones')[1]['zones'][0]['inactive'] == 'wip'
    assert call(drop, 'PUT', '/zones/gobras/inactive', {'reason': 'bored'}, 't-admin')[0] == 422
    assert call(drop, 'DELETE', '/zones/gobras/inactive', token='t-mie')[0] == 403
    assert call(drop, 'DELETE', '/zones/gobras/inactive', token='t-admin')[0] == 200
    assert (drop.base / 'inactive').read_text() == '# hand comments\nteirolask   wip        # kept\n'


def test_odd_calls(drop):
    assert call(drop, 'GET', '/')[1]['service'] == 'danu data drop'
    assert call(drop, 'POST', '/zones')[0] == 405
    assert call(drop, 'GET', '/nothing/here/at/all')[0] == 404
    status, body, _ = call(drop, 'PUT', '/zones/x', b'{not json', 't-admin')
    assert status == 400
    (drop.base / 'zones').write_text('a N10E010\nb N10E010\n')
    assert call(drop, 'GET', '/zones')[0] == 503


# ------------------------------------------------------------------ sources

def test_ogf_is_asked_once_a_while_per_token():
    asked = []
    now = [0.0]

    def fetch(url, token=None):
        asked.append(token)
        return json.dumps({'user': {'display_name': 'wangi', 'roles': ['administrator']}}).encode()
    users = OgfUsers('https://ogf.example/', fetch, clock=lambda: now[0])
    assert users('tok') == User('wangi', ('administrator',)) and users('tok').admin
    now[0] = 299
    users('tok')
    assert asked == ['tok']
    now[0] = 301
    users('tok')
    assert asked == ['tok', 'tok']


def test_ogf_refusing_a_token_is_401_and_ogf_down_is_502():
    import urllib.error

    def refuse(url, token=None):
        raise urllib.error.HTTPError(url, 401, 'no', {}, None)

    def down(url, token=None):
        raise OSError('timed out')
    with pytest.raises(Unknown) as e:
        OgfUsers('https://ogf.example', refuse)('t')
    assert e.value.status == 401
    with pytest.raises(Unknown) as e:
        OgfUsers('https://ogf.example', down)('t')
    assert e.value.status == 502


def test_territories_reread_as_they_change_and_survive_a_failed_fetch(tmp_path):
    geo = tmp_path / 'territory.json'
    geo.write_text(json.dumps(GEOMETRY))
    now = [0.0]
    attrs = [json.dumps(ATTRIBUTES).encode()]

    def fetch(url, token=None):
        if isinstance(attrs[0], Exception):
            raise attrs[0]
        return attrs[0]
    t = Territories(str(geo), 'https://wiki.example/attrs', fetch, clock=lambda: now[0])
    assert t.index().permission((86.2, 20, 87.2, 21), 'wangi').level == T.YES
    attrs[0] = OSError('wiki down')
    now[0] = 1000
    assert t.index().permission((86.2, 20, 87.2, 21), 'wangi').level == T.YES, 'the last good kept'
    attrs[0] = json.dumps([{**ATTRIBUTES[0], 'owner': 'Luciano'}, ATTRIBUTES[1]]).encode()
    now[0] = 2000
    assert t.index().permission((86.2, 20, 87.2, 21), 'wangi').level == T.NO
    # a first fetch that fails is tried again in a minute, not ten
    attrs[0] = OSError('wiki down at start')
    t3 = Territories(str(geo), 'https://wiki.example/attrs', fetch, clock=lambda: now[0])
    with pytest.raises(Unknown):
        t3.index()
    attrs[0] = json.dumps(ATTRIBUTES).encode()
    now[0] += 30
    with pytest.raises(Unknown):
        t3.index()
    now[0] += 31
    assert t3.index().permission((86.2, 20, 87.2, 21), 'wangi').level == T.YES
    t2 = Territories(str(tmp_path / 'missing.json'), 'https://wiki.example/attrs', fetch)
    with pytest.raises(Unknown) as e:
        t2.index()
    assert e.value.status == 503


# ------------------------------------------------------------------ zones that keep their squares, and splits

def shore() -> bytes:
    """A coastline and nothing behind it: every elevation 0."""
    return lzma.compress(b"<?xml version='1.0'?><osm version='0.6'><way id='-1'><tag k='ele' v='0'/>"
                         b"<tag k='natural' v='coastline'/></way></osm>")


@pytest.fixture
def zoned(drop):
    """gobras N20E086-N20E089: drawn at 086, coastline only at 087, blank at 088,
    and its published copy as the nightly copy leaves it."""
    sq = drop.base / 'osm-squares' / 'gobras'
    (sq / 'N20E087_Artana.osm.xz').write_bytes(shore())
    (sq / 'N20E088_Laguna.osm.xz').write_bytes(osm(0))
    pub = drop.pub / 'osm-squares' / 'gobras'
    pub.mkdir(parents=True)
    for p in sq.glob('N*.osm.xz'):
        (pub / p.name).write_bytes(p.read_bytes())
    return drop


def test_the_listing_says_each_squares_class(zoned):
    _, body, _ = call(zoned, 'GET', '/zones/gobras')
    assert {h['square']: h['class'] for h in body['held']} == {
        'N20E086': 'contour', 'N20E087': 'coastline', 'N20E088': 'blank'}
    _, body, _ = call(zoned, 'GET', '/zones', query='held=1')
    (g,) = body['zones']
    assert sorted(h['class'] for h in g['held']) == ['blank', 'coastline', 'contour']
    assert 'held' not in call(zoned, 'GET', '/zones')[1]['zones'][0], 'asked for'
    assert 'held' not in call(zoned, 'GET', '/zones', query='held=false')[1]['zones'][0]


def test_a_resize_that_would_leave_a_drawn_square_in_no_zone_is_refused(zoned):
    before = (zoned.base / 'zones').read_text()
    status, body, _ = call(zoned, 'PUT', '/zones/gobras', {'squares': ['N20E087-N20E089']}, 't-admin')
    assert status == 409 and body['squares'] == ['N20E086'] and 'contours' in body['error']
    assert (zoned.base / 'zones').read_text() == before
    assert (zoned.base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz').exists()


def test_a_resize_retires_the_blank_and_the_coastline_only_it_leaves_out(zoned):
    status, body, _ = call(zoned, 'PUT', '/zones/gobras', {'squares': ['N20E086']}, 't-admin')
    assert status == 200 and sorted(body['retired']) == ['N20E087_Artana.osm.xz', 'N20E088_Laguna.osm.xz']
    for copy in (zoned.base / 'osm-squares' / 'gobras', zoned.pub / 'osm-squares' / 'gobras'):
        assert sorted(p.name for p in copy.glob('N*.osm.xz')) == ['N20E086_Gobras_City.osm.xz'], copy
    kept = sorted(p.name.split('.')[0] for p in (zoned.base / 'drop' / 'kept' / 'gobras').iterdir())
    assert kept == ['N20E087_Artana', 'N20E088_Laguna']
    log = [json.loads(x) for x in (zoned.base / 'drop' / 'log.jsonl').read_text().splitlines()]
    assert [e['action'] for e in log] == ['retire', 'retire', 'zone']


def test_a_resize_that_only_grows_moves_nothing(zoned):
    status, body, _ = call(zoned, 'PUT', '/zones/gobras', {'squares': ['N20E086-N21E089']}, 't-admin')
    assert status == 200 and body['retired'] == []


def test_a_split_moves_the_squares_and_their_files_to_the_new_zone(zoned):
    (zoned.base / 'inactive').write_text('gobras      wip        # being drawn\n')
    status, body, _ = call(zoned, 'POST', '/zones/gobras/split',
                           {'name': 'artana', 'squares': ['N20E087-N20E088']}, 't-admin')
    assert status == 201 and body['squares'] == ['N20E087-N20E088']
    assert body['from']['squares'] == ['N20E086', 'N20E089']
    assert sorted(body['moved']) == ['N20E087_Artana.osm.xz', 'N20E088_Laguna.osm.xz'] and body['inactive'] == 'wip'
    zones = Z.Zones((zoned.base / 'zones').read_text())
    assert zones.zone_of(S.parse('N20E087')) == 'artana' and zones.zone_of(S.parse('N20E086')) == 'gobras'
    for root in (zoned.base / 'osm-squares', zoned.pub / 'osm-squares'):
        assert sorted(p.name for p in (root / 'artana').glob('N*')) == ['N20E087_Artana.osm.xz', 'N20E088_Laguna.osm.xz']
        assert sorted(p.name for p in (root / 'gobras').glob('N*')) == ['N20E086_Gobras_City.osm.xz']
    assert 'artana      wip        # split from gobras' in (zoned.base / 'inactive').read_text()
    _, body, _ = call(zoned, 'GET', '/squares/N20E087', token='t-wangi')
    assert body['zone'] == 'artana' and body['held']['sha256'] == sha(shore()), 'uploadable where it went'


@pytest.mark.parametrize('body, status, why', [
    ({'name': 'gobras', 'squares': ['N20E087']}, 409, 'a zone already'),
    ({'name': 'artana', 'squares': ['N30E087']}, 422, 'of gobras\'s own'),
    ({'name': 'artana', 'squares': ['N20E086-N20E089']}, 422, 'all of gobras'),
    ({'name': 'Artana', 'squares': ['N20E087']}, 422, 'lowercase'),
    ({'name': 'artana', 'squares': []}, 422, 'not none'),
])
def test_a_split_refused_changes_nothing(zoned, body, status, why):
    before = (zoned.base / 'zones').read_text()
    got, answer, _ = call(zoned, 'POST', '/zones/gobras/split', body, 't-admin')
    assert got == status and why in answer['error']
    assert (zoned.base / 'zones').read_text() == before and not (zoned.base / 'osm-squares' / 'artana').exists()


def test_pruning_keeps_the_recent_and_each_squares_newest(tmp_path):
    from danu.drop.store import Store, main
    store = Store(tmp_path, None)
    kept = tmp_path / 'drop' / 'kept'
    names = {'gobras': ['N20E086_Gobras_City.osm.xz.20260101T000000Z.aaaaaaaaaaaa',
                        'N20E086_Gobras_City.osm.xz.20260301T000000Z.bbbbbbbbbbbb',
                        'N20E086.osm.xz.20261001T000000Z.cccccccccccc',          # relabelled: one square
                        'N21E086.osm.xz.20260101T000000Z.dddddddddddd',          # deleted: its only copy
                        'notes.txt'],
             'karang': ['N20E087_Artana.osm.xz.20260101T000000Z.eeeeeeeeeeee'],  # split away from gobras
             'gobras2': []}
    names['gobras'].append('N20E087_Artana.osm.xz.20260102T000000Z.ffffffffffff')
    for zone, files in names.items():
        (kept / zone).mkdir(parents=True)
        for n in files:
            (kept / zone / n).write_bytes(b'x')
    now = 1792454400.0      # 2026-10-20
    assert main(['prune', str(tmp_path), '--dry-run']) == 0
    assert sum(1 for _ in kept.glob('*/*')) == 7, 'a dry run keeps all'
    gone = store.prune(90, now=now)
    assert sorted(p.name[:30] for p in gone) == ['N20E086_Gobras_City.osm.xz.202', 'N20E086_Gobras_City.osm.xz.202',
                                                  'N20E087_Artana.osm.xz.20260101']
    left = sorted(p.name for p in kept.glob('*/*'))
    assert left == ['N20E086.osm.xz.20261001T000000Z.cccccccccccc', 'N20E087_Artana.osm.xz.20260102T000000Z.ffffffffffff',
                    'N21E086.osm.xz.20260101T000000Z.dddddddddddd', 'notes.txt']
    log = [json.loads(line) for line in (tmp_path / 'drop' / 'log.jsonl').read_text().splitlines()]
    assert [e['action'] for e in log] == ['prune'] * 3 and {e['zone'] for e in log} == {'gobras', 'karang'}
    assert store.prune(90, now=now) == [], 'nothing more'


def test_a_split_is_an_administrators(zoned):
    assert call(zoned, 'POST', '/zones/gobras/split', {'name': 'x', 'squares': ['N20E087']}, 't-wangi')[0] == 403
    assert call(zoned, 'POST', '/zones/nowhere/split', {'name': 'x', 'squares': ['N20E087']}, 't-admin')[0] == 404
