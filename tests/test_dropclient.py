"""danu.core.dropclient against the real service (#190, N5b): the drop's WSGI
app in-process, reached through an opener as urllib's is - an import, then
uploads, renames and deletes as the editor makes them."""

import email.message
import io
import urllib.error

import pytest

pytest.importorskip('fcntl', reason='the data drop is the server\'s: no fcntl here')

from danu.core import dropclient as C
from danu.core import mirror
from danu.core.square import SquareName
from danu.drop import app as A
from tests.test_drop import FakeTerritories, fake_users, osm, sha

API = 'https://drop.example/dem/api'


class InProcess:
    """urllib's opener, answered by the app."""

    def __init__(self, app):
        self.app = app

    def __call__(self, req, timeout=None):
        path, _, query = req.full_url[len(API):].partition('?')
        body = req.data or b''
        environ = {'REQUEST_METHOD': req.get_method(), 'PATH_INFO': path, 'QUERY_STRING': query,
                   'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
        for k, v in req.header_items():
            environ['HTTP_' + k.upper().replace('-', '_')] = v
        got = {}
        data = b''.join(self.app(environ, lambda s, h: got.update(status=int(s.split()[0]), headers=h)))
        headers = email.message.Message()
        for k, v in got['headers']:
            headers[k] = v
        if got['status'] >= 400:
            raise urllib.error.HTTPError(req.full_url, got['status'], '', headers, io.BytesIO(data))
        r = io.BytesIO(data)
        r.status, r.headers = got['status'], headers
        return r


@pytest.fixture
def world(tmp_path):
    """The server's zone, with Gobras City, and the mapper's import of it."""
    base, pub = tmp_path / 'elevation', tmp_path / 'publish'
    (base / 'osm-squares' / 'gobras').mkdir(parents=True)
    (base / 'zones').write_text('gobras          N20E086-N20E089\n')
    (base / 'osm-squares' / 'gobras' / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(1))
    app = A.DropApp(A.Config(base, pub), fake_users, FakeTerritories())
    opener = InProcess(app)
    here = tmp_path / 'import'
    f = mirror.fetch('gobras', here, 'https://unused.example', opener=opener, api=API)
    mirror.settle(f, set())
    return opener, here / 'gobras', base / 'osm-squares' / 'gobras'


def test_an_upload_from_an_import(world):
    opener, here, there = world
    mine = here / 'N20E086_Gobras_City.osm.xz'
    mine.write_bytes(osm(2))
    answer, path = C.upload(API, 't-wangi', mine, opener=opener)
    assert answer.status == 200 and path == mine
    assert (there / mine.name).read_bytes() == osm(2)
    assert mirror.read_manifest(here)[mine.name]['sha256'] == sha(osm(2)), 'the next made from this'
    mine.write_bytes(osm(3))
    answer, _ = C.upload(API, 't-wangi', mine, opener=opener)
    assert answer.status == 200 and (there / mine.name).read_bytes() == osm(3)
    # and the next import has nothing to fetch
    f = mirror.fetch('gobras', here.parent, 'https://unused.example', opener=opener, api=API)
    assert f.current == [mine.name] and not f.new and not f.changed


def test_an_upload_from_a_version_since_changed_is_refused_and_the_copy_kept(world):
    opener, here, there = world
    (there / 'N20E086_Gobras_City.osm.xz').write_bytes(osm(4))          # somebody else's, since
    mine = here / 'N20E086_Gobras_City.osm.xz'
    mine.write_bytes(osm(2))
    answer, path = C.upload(API, 't-wangi', mine, opener=opener)
    assert answer.status == 412 and 'changed' in answer.why
    assert (there / mine.name).read_bytes() == osm(4)
    kept = C.keep_mine(path)
    assert kept.name == 'N20E086_Gobras_City.mine.osm.xz' and kept.read_bytes() == osm(2)
    assert C.mine_for(here, SquareName.parse('N20E086')) == kept
    from danu.core.square import list_squares
    assert list_squares(here) == {SquareName.parse('N20E086'): mine}, 'the copy is not a square'
    # an import overwriting the square leaves the copy, which no listing reads as a square
    f = mirror.fetch('gobras', here.parent, 'https://unused.example', opener=opener, api=API)
    mirror.settle(f, {mine.name})
    assert mine.read_bytes() == osm(4) and kept.read_bytes() == osm(2) and not f.gone


def test_a_new_square_goes_up_with_its_label(world):
    opener, here, there = world
    new = here / 'N20E087_Artana.osm.xz'
    new.write_bytes(osm(1))
    answer, path = C.upload(API, 't-wangi', new, label='Artana', opener=opener)
    assert answer.status == 201 and (there / 'N20E087_Artana.osm.xz').exists() and path == new


def test_a_square_held_there_never_imported_here_is_refused_unsent(world):
    opener, here, there = world
    (here / '.danu-mirror.json').unlink()
    mine = here / 'N20E086_Gobras_City.osm.xz'
    mine.write_bytes(osm(2))
    answer, _ = C.upload(API, 't-wangi', mine, opener=opener)
    assert answer.status == 412 and 'not imported' in answer.why
    assert (there / mine.name).read_bytes() == osm(1)


def test_renamed_with_an_upload_and_alone_here_as_there(world):
    opener, here, there = world
    mine = here / 'N20E086_Gobras_City.osm.xz'
    answer, path = C.upload(API, 't-wangi', mine, label='Gobras', opener=opener)
    assert answer.ok and path.name == 'N20E086_Gobras.osm.xz' and not mine.exists()
    assert sorted(mirror.read_manifest(here)) == ['N20E086_Gobras.osm.xz']
    path.write_bytes(osm(5))                                            # edits here, not yet sent
    answer, path = C.rename(API, 't-wangi', path, '', opener=opener)
    assert answer.ok and path.name == 'N20E086.osm.xz' and path.read_bytes() == osm(5)
    assert (there / 'N20E086.osm.xz').read_bytes() == osm(1), 'the server\'s bytes as they were'
    answer, _ = C.upload(API, 't-wangi', path, opener=opener)
    assert answer.ok and (there / 'N20E086.osm.xz').read_bytes() == osm(5), 'made from the renamed version'


def test_deleting_leaves_the_copy_here_the_mappers_own(world):
    opener, here, there = world
    mine = here / 'N20E086_Gobras_City.osm.xz'
    assert C.delete(API, 't-luciano', mine, opener=opener).status == 403
    answer = C.delete(API, 't-wangi', mine, opener=opener)
    assert answer.status == 204 and not (there / mine.name).exists() and mine.exists()
    assert mine.name not in mirror.read_manifest(here)
    f = mirror.fetch('gobras', here.parent, 'https://unused.example', opener=opener, api=API)
    assert not f.gone, 'its own now: not said gone'


def test_not_signed_in_and_not_yours_say_why(world):
    opener, here, _ = world
    mine = here / 'N20E086_Gobras_City.osm.xz'
    answer, _ = C.upload(API, '', mine, opener=opener)
    assert answer.status == 401 and 'sign in' in answer.why
    answer, _ = C.upload(API, 't-luciano', mine, opener=opener)
    assert answer.status == 403 and 'not yours' in answer.why
