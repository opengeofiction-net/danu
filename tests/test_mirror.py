"""danu.core.mirror: a zone's squares mirrored from the server's index (H6g),
against a stand-in for the server - a dict of URL to bytes, read through
the same opener interface urllib's is."""

import io

import pytest

from danu.core import mirror

BASE = 'https://data.example/dem/osm-squares'


def index(rows: dict[str, bytes]) -> bytes:
    """nginx's autoindex, as the server writes it."""
    lines = ['<html><body><h1>Index</h1><hr><pre><a href="../">../</a>']
    for name, data in rows.items():
        lines.append(f'<a href="{name}">{name}</a>{" " * 20}20-Jul-2026 13:51{" " * 10}{len(data)}')
    lines.append('</pre><hr></body></html>')
    return '\n'.join(lines).encode()


class Server:
    def __init__(self, zones: dict[str, dict[str, bytes]]):
        self.zones = zones
        self.asked: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append(url)
        if url == f'{BASE}/':
            body = ('<pre><a href="../">../</a>\n' + '\n'.join(
                f'<a href="{z}/">{z}/</a>   20-Jul-2026 13:51   -' for z in self.zones) + '</pre>').encode()
        else:
            zone, _, name = url[len(BASE) + 1:].partition('/')
            body = index(self.zones[zone]) if not name else self.zones[zone][name]
        return io.BytesIO(body)


def run(server, root, overwrite=(), keep=()):
    f = mirror.fetch('gobras', root, BASE, opener=server)
    return f, mirror.settle(f, set(overwrite), set(keep))


@pytest.fixture
def server():
    return Server({'gobras': {'N20E086_Gobras_City.osm.xz': b'city v1', 'N20E087_Artana.osm.xz': b'artana v1',
                              'EMPTY.osm.xz': b'empty'},
                   'alved': {}})


def test_the_index_is_read_for_its_zones_and_its_squares(server):
    assert mirror.list_zones(BASE, opener=server) == ['alved', 'gobras']
    listed = mirror.files(index({'a.osm.xz': b'xyz', 'notes.txt': b'n'}).decode())
    assert listed == {'a.osm.xz': (3, '20-Jul-2026 13:51')}


def test_the_real_servers_index_is_read():
    html = ('<html>\n<head><title>Index of /dem/osm-squares/gobras/</title></head>\n<body>\n'
            '<h1>Index of /dem/osm-squares/gobras/</h1><hr><pre><a href="../">../</a>\n'
            '<a href="EMPTY.osm.xz">EMPTY.osm.xz</a>                                       20-Jul-2026 13:51'
            '                 156\n<a href="N20E086_Gobras_City.osm.xz">N20E086_Gobras_City.osm.xz</a>   '
            '                      18-Sep-2026 08:32             1729040\n</pre><hr></body>\n</html>\n')
    assert mirror.files(html) == {'EMPTY.osm.xz': (156, '20-Jul-2026 13:51'),
                                  'N20E086_Gobras_City.osm.xz': (1729040, '18-Sep-2026 08:32')}
    assert mirror.zones('<a href="../">../</a>\n<a href="alved/">alved/</a>   28-Aug-2026 20:03   -') == ['alved']


def test_a_first_mirror_fetches_every_square(server, tmp_path):
    f, done = run(server, tmp_path)
    assert sorted(done['new']) == ['EMPTY.osm.xz', 'N20E086_Gobras_City.osm.xz', 'N20E087_Artana.osm.xz']
    assert (tmp_path / 'gobras' / 'N20E087_Artana.osm.xz').read_bytes() == b'artana v1'
    assert mirror.read_manifest(tmp_path / 'gobras')['EMPTY.osm.xz']['sha256'] == mirror.sha256(
        tmp_path / 'gobras' / 'EMPTY.osm.xz')
    assert not list((tmp_path / 'gobras').glob(mirror.PART + '*')), 'a part left behind'


def test_again_with_nothing_new_fetches_nothing(server, tmp_path):
    run(server, tmp_path)
    server.asked.clear()
    _f, done = run(server, tmp_path)
    assert sorted(done['current']) == ['EMPTY.osm.xz', 'N20E086_Gobras_City.osm.xz', 'N20E087_Artana.osm.xz']
    assert server.asked == [f'{BASE}/gobras/'], 'a square fetched though it was the same'


def test_a_square_newer_there_and_untouched_here_is_replaced_without_asking(server, tmp_path):
    run(server, tmp_path)
    server.zones['gobras']['N20E087_Artana.osm.xz'] = b'artana v2 - longer'
    f, done = run(server, tmp_path)
    assert done['updated'] == ['N20E087_Artana.osm.xz'] and not f.changed
    assert (tmp_path / 'gobras' / 'N20E087_Artana.osm.xz').read_bytes() == b'artana v2 - longer'


def test_a_square_changed_here_is_asked_about_and_kept_unless_overwritten(server, tmp_path):
    run(server, tmp_path)
    mine = tmp_path / 'gobras' / 'N20E086_Gobras_City.osm.xz'
    mine.write_bytes(b'my edits')
    server.zones['gobras']['N20E086_Gobras_City.osm.xz'] = b'city v2'
    f, done = run(server, tmp_path)
    assert list(f.changed) == ['N20E086_Gobras_City.osm.xz'] and done['kept'] == ['N20E086_Gobras_City.osm.xz']
    assert mine.read_bytes() == b'my edits'
    f, done = run(server, tmp_path, overwrite={'N20E086_Gobras_City.osm.xz'})
    assert done['overwritten'] == ['N20E086_Gobras_City.osm.xz'] and mine.read_bytes() == b'city v2'


def test_a_square_changed_here_but_the_server_unchanged_is_still_asked(server, tmp_path):
    """The manifest says what was mirrored; the file no longer hashes so."""
    run(server, tmp_path)
    (tmp_path / 'gobras' / 'N20E087_Artana.osm.xz').write_bytes(b'mine')
    f, _done = run(server, tmp_path)
    assert list(f.changed) == ['N20E087_Artana.osm.xz']


def test_a_square_here_before_any_mirror_with_the_same_bytes_is_no_question(server, tmp_path):
    (tmp_path / 'gobras').mkdir()
    (tmp_path / 'gobras' / 'N20E087_Artana.osm.xz').write_bytes(b'artana v1')
    (tmp_path / 'gobras' / 'N20E086_Gobras_City.osm.xz').write_bytes(b'something else')
    f, done = run(server, tmp_path)
    assert 'N20E087_Artana.osm.xz' in done['current']
    assert list(f.changed) == ['N20E086_Gobras_City.osm.xz'], 'no manifest: changed here, asked'


def test_a_square_gone_from_the_server_is_left_and_said(server, tmp_path):
    run(server, tmp_path)
    del server.zones['gobras']['EMPTY.osm.xz']
    _f, done = run(server, tmp_path)
    assert done['gone'] == ['EMPTY.osm.xz'] and (tmp_path / 'gobras' / 'EMPTY.osm.xz').exists()


def test_a_square_held_back_is_kept_whatever_it_is(server, tmp_path):
    _f, done = run(server, tmp_path, keep={'N20E086_Gobras_City.osm.xz'})
    assert done['held'] == ['N20E086_Gobras_City.osm.xz'] and not done['kept']
    assert not (tmp_path / 'gobras' / 'N20E086_Gobras_City.osm.xz').exists()
    assert 'N20E086_Gobras_City.osm.xz' not in mirror.read_manifest(tmp_path / 'gobras')


def test_a_fetch_that_fails_leaves_nothing_in_place(server, tmp_path):
    def broken(req, timeout=None):
        if req.full_url.endswith('Artana.osm.xz'):
            raise OSError('connection reset')
        return server(req, timeout)
    with pytest.raises(OSError):
        mirror.fetch('gobras', tmp_path, BASE, opener=broken)
    assert not list((tmp_path / 'gobras').glob(mirror.PART + '*'))


def test_discard_takes_the_parts_away(server, tmp_path):
    f = mirror.fetch('gobras', tmp_path, BASE, opener=server)
    assert list((tmp_path / 'gobras').glob(mirror.PART + '*'))
    f.discard()
    assert not list((tmp_path / 'gobras').glob(mirror.PART + '*'))


def test_progress_is_said_a_square_at_a_time(server, tmp_path):
    seen = []
    mirror.fetch('gobras', tmp_path, BASE, opener=server, report=seen.append)
    assert [s[:2] for s in seen] == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_parts_a_killed_mirror_left_are_cleared(server, tmp_path):
    (tmp_path / 'gobras').mkdir()
    (tmp_path / 'gobras' / (mirror.PART + 'old')).write_bytes(b'half')
    run(server, tmp_path)
    assert not list((tmp_path / 'gobras').glob(mirror.PART + '*'))


def test_a_square_put_in_place_has_the_permissions_any_file_would(server, tmp_path):
    import os
    import stat
    run(server, tmp_path)
    probe = tmp_path / 'probe'
    probe.write_bytes(b'')
    assert stat.S_IMODE(os.stat(tmp_path / 'gobras' / 'EMPTY.osm.xz').st_mode) == stat.S_IMODE(os.stat(probe).st_mode)


def test_a_square_of_the_mappers_own_is_not_said_gone(server, tmp_path):
    run(server, tmp_path)
    (tmp_path / 'gobras' / 'N22E086_Mine.osm.xz').write_bytes(b'mine')
    _f, done = run(server, tmp_path)
    assert done['gone'] == []


def test_a_square_unchanged_here_is_not_read_again(server, tmp_path, monkeypatch):
    run(server, tmp_path)
    hashed = []
    real = mirror.sha256
    monkeypatch.setattr(mirror, 'sha256', lambda p: (hashed.append(p.name), real(p))[1])
    run(server, tmp_path)
    assert hashed == [], 'a square read though its size and time were as mirrored'
    (tmp_path / 'gobras' / 'EMPTY.osm.xz').write_bytes(b'touched')
    f, _done = run(server, tmp_path)
    assert 'EMPTY.osm.xz' in hashed and 'EMPTY.osm.xz' in f.changed, 'a change here not seen'


def test_a_manifest_a_killed_write_left_is_cleared(server, tmp_path):
    (tmp_path / 'gobras').mkdir()
    (tmp_path / 'gobras' / '.manifest-xyz').write_text('{')
    run(server, tmp_path)
    assert not list((tmp_path / 'gobras').glob('.manifest-*'))
