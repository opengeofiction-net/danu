"""A way id is unique within its square, not across a working set.

The editor mints new ids below the lowest in the squares it has open, so two
working sets that share some squares and not others mint the same ids in
different squares. roantra had 973 such ids, and the preview - keying each
contour by id alone - refused the whole working set: every edit waited for a
whole rebuild. The build now writes each feature's square, and the preview
keys by square and id.

Two squares here, each with a ring whose way id is the other's, which is what
an allocator starting afresh in each mints.
"""

import math
import shutil

import pytest

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def ring(name, lon, lat, ele, spot=None):
    """A square holding one contour ring, and a spot height if asked - each
    with the ids a fresh allocator gives, the same in every square."""
    import numpy as np

    from danu.core import edits
    from danu.core.square import Node, Square

    sq = Square(name=name, present=True, attrs={'version': '0.6', 'upload': 'never'})
    alloc = edits.IdAllocator(sq)
    pts = [(lon + 0.2 * math.cos(t), lat + 0.2 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 37)]
    ids = [alloc.take() for _ in pts[:-1]]
    way = alloc.take()
    edits.AddWay(way, ids + [ids[0]], pts[:-1] + [pts[0]], {'ele': str(ele)}).apply(sq)
    if spot is not None:
        nid = alloc.take()
        sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat, tags={'ele': str(spot)})
    return sq, way


@pytest.fixture
def twins(tmp_path):
    from danu.core.square import SquareName, write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    west, wid = ring(SquareName(125, -24), 125.5, -23.5, 100, spot=150)
    east, eid = ring(SquareName(126, -24), 126.5, -23.5, 200, spot=250)
    assert wid == eid, 'the two squares were meant to share the way id'
    write_square(west, zone / 'S24E125.osm.xz')
    write_square(east, zone / 'S24E126.osm.xz')
    result = build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3))
    assert result.dem is not None
    return result, wid


def test_the_build_names_each_features_square(twins):
    from osgeo import ogr
    result, wid = twins
    ds = ogr.Open(str(result.contours_gpkg))
    for table in ('contour', 'spot'):
        rows = sorted((f.GetField('square'), f.GetField('osm_id'), f.GetField('ele'))
                      for f in ds.GetLayerByName(table))
        assert [r[0] for r in rows] == ['S24E125', 'S24E126'], (table, rows)
        assert rows[0][1] == rows[1][1], f'{table}: the ids were meant to be the same'


def test_the_same_id_in_two_squares_is_two_contours_to_the_preview(twins):
    from danu.surface import preview
    result, wid = twins
    contours = preview.Contours(result.contours_gpkg)
    assert contours.collided == [], 'two squares sharing an id refused the preview'
    assert set(contours._fid) == {('S24E125', str(wid)), ('S24E126', str(wid))}
    eles = sorted(f.GetField('ele') for f in contours.layer)
    assert eles == [100, 200]
    # an edit to the eastern one replaces it and leaves the western alone
    contours.apply('S24E126', wid, [(126.4, -23.5), (126.6, -23.5)], 210.0)
    eles = sorted(f.GetField('ele') for f in contours.layer)
    assert eles == [100, 210], 'the edit reached the other square\'s contour'
    assert contours.remove('S24E125', wid)
    assert [f.GetField('ele') for f in contours.layer] == [210]


def test_a_square_with_no_spot_height_between_two_that_have_one(tmp_path):
    """A square that adds no rows to a layer has an empty range there, and
    the square after it keeps its own name."""
    from osgeo import ogr

    from danu.core.square import SquareName, write_square
    from danu.surface import build
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    for lon, spot in ((125, 150), (126, None), (127, 250)):
        sq, _ = ring(SquareName(lon, -24), lon + 0.5, -23.5, 100, spot=spot)
        write_square(sq, zone / f'{sq.name}.osm.xz')
    result = build.build_dem(zone, tmp_path / 'w', sp.load().with_arcsec(3))
    ds = ogr.Open(str(result.contours_gpkg))
    spots = sorted((f.GetField('square'), f.GetField('ele')) for f in ds.GetLayerByName('spot'))
    assert spots == [('S24E125', '150'), ('S24E127', '250')], spots
    lines = sorted(f.GetField('square') for f in ds.GetLayerByName('contour'))
    assert lines == ['S24E125', 'S24E126', 'S24E127']


def test_a_square_read_once_is_not_read_again_until_it_changes(tmp_path, monkeypatch):
    """collect's own Python reading of a square - its lakes, its coasts, its
    way counts - is kept by the square's contents: the editor builds the same
    unchanged squares again for every edit, and reading them was 12 s of a
    31 s build on roantra, all of it holding the GIL."""
    from danu.core.square import SquareName, write_square
    from danu.surface import build

    zone = tmp_path / 'zone'
    zone.mkdir()
    sq, wid = ring(SquareName(125, -24), 125.5, -23.5, 100)
    write_square(sq, zone / 'S24E125.osm.xz')
    read = []
    real = build.lake_rings
    monkeypatch.setattr(build, 'lake_rings', lambda path, name=None: read.append(name) or real(path, name))
    squares = {SquareName(125, -24): zone / 'S24E125.osm.xz'}
    for n in range(2):
        (tmp_path / f'w{n}').mkdir()
        build.collect(squares, tmp_path / f'w{n}')
    assert len(read) == 1, 'an unchanged square was read again'
    sq.nodes[next(iter(sq.nodes))].lon += 0.001
    write_square(sq, zone / 'S24E125.osm.xz')
    (tmp_path / 'w2').mkdir()
    build.collect(squares, tmp_path / 'w2')
    assert len(read) == 2, 'a changed square was not read again'


def test_the_contour_layer_comes_with_the_build_loaded_on_its_worker(tmp_path):
    """Loading it as the build landed was most of the 3 s the editor stood
    still for with each of roantra's builds; build_surface runs on the
    worker, and hands it over loaded."""
    pytest.importorskip('PySide6')
    from danu.core.square import SquareName, write_square
    from danu.surface import params as sp
    from danu.surface import preview
    from danu.ui.surface import build_surface

    zone = tmp_path / 'zone'
    zone.mkdir()
    sq, wid = ring(SquareName(125, -24), 125.5, -23.5, 100)
    write_square(sq, zone / 'S24E125.osm.xz')
    built = build_surface(zone, [SquareName(125, -24)], sp.load().with_arcsec(3), tmp_path / 'w')
    assert isinstance(built.rasters.contours, preview.Contours)
    assert ('S24E125', str(wid)) in built.rasters.contours._fid


def test_a_square_kept_translated_gives_the_same_constraints_and_is_not_expanded(tmp_path, monkeypatch):
    """collect's cache keeps each square's translated constraints by its
    contents: built again unchanged, the GeoPackage is the same row for row
    and the square is not even decompressed; changed, it is translated anew."""
    import lzma

    from osgeo import ogr

    from danu.core.square import SquareName, write_square
    from danu.surface import build

    zone = tmp_path / 'zone'
    zone.mkdir()
    for lon, spot in ((125, 150), (126, None)):
        sq, _ = ring(SquareName(lon, -24), lon + 0.5, -23.5, 100 + lon, spot=spot)
        write_square(sq, zone / f'{sq.name}.osm.xz')
    squares = {SquareName(lon, -24): zone / f'S24E{lon}.osm.xz' for lon in (125, 126)}

    def rows(gpkg):
        ds = ogr.Open(str(gpkg))
        return {t: [(f.GetFID(), f.GetField('osm_id'), f.GetField('ele'), f.GetField('square'),
                     f.GetGeometryRef().ExportToWkt()) for f in ds.GetLayerByName(t)]
                for t in ('contour', 'spot')}

    (tmp_path / 'plain').mkdir()
    want = rows(build.collect(squares, tmp_path / 'plain'))
    cache = tmp_path / 'cache'
    opened = []
    real = lzma.open
    monkeypatch.setattr(build.lzma, 'open', lambda *a, **k: opened.append(a[0]) or real(*a, **k))
    for n in range(2):
        (tmp_path / f'w{n}').mkdir()
        assert rows(build.collect(squares, tmp_path / f'w{n}', cache=cache)) == want
    assert len(list(cache.glob('*.gpkg'))) == 2, 'one piece a square'
    opened.clear()
    (tmp_path / 'w2').mkdir()
    build.collect(squares, tmp_path / 'w2', cache=cache)
    assert opened == [], 'an unchanged square was decompressed'
    # one square changed: its piece is made again, the old one goes
    sq, _ = ring(SquareName(126, -24), 126.5, -23.4, 300)
    write_square(sq, zone / 'S24E126.osm.xz')
    (tmp_path / 'w3').mkdir()
    got = rows(build.collect(squares, tmp_path / 'w3', cache=cache))
    assert [r[2] for r in got['contour']] == ['225', '300']
    assert len(list(cache.glob('S24E126-*.gpkg'))) == 1


def test_another_windows_unfinished_piece_is_left_alone(tmp_path):
    """The cache outlives a session, so two windows may share it: a piece
    being written by another process is named by its pid, and neither taken
    for an old piece nor overwritten."""
    from danu.core.square import SquareName, write_square
    from danu.surface import build

    zone = tmp_path / 'zone'
    zone.mkdir()
    sq, _ = ring(SquareName(125, -24), 125.5, -23.5, 200)
    write_square(sq, zone / 'S24E125.osm.xz')
    cache = tmp_path / 'cache'
    cache.mkdir()
    theirs = cache / 'S24E125-0123.999999.part.gpkg'
    theirs.write_bytes(b'being written')
    (tmp_path / 'w').mkdir()
    build.collect({SquareName(125, -24): zone / 'S24E125.osm.xz'}, tmp_path / 'w', cache=cache)
    assert theirs.read_bytes() == b'being written'
    assert len([p for p in cache.glob('S24E125-*.gpkg') if not p.name.endswith('.part.gpkg')]) == 1
    assert not [p for p in cache.glob('*.part.gpkg') if p != theirs], 'its own part left behind'
    # one left an hour and more by a build that died goes
    import os
    import time
    dead = cache / 'S24E125-0456.999998.part.gpkg'
    dead.write_bytes(b'died here')
    old = time.time() - 7200
    os.utime(dead, (old, old))
    sq, _ = ring(SquareName(125, -24), 125.5, -23.5, 300)
    write_square(sq, zone / 'S24E125.osm.xz')
    (tmp_path / 'w2').mkdir()
    build.collect({SquareName(125, -24): zone / 'S24E125.osm.xz'}, tmp_path / 'w2', cache=cache)
    assert not dead.exists() and theirs.exists()


def test_a_new_session_builds_from_the_pieces_the_last_one_kept(tmp_path, monkeypatch):
    """The editor's builds keep each square's pieces in SQUARE_CACHE, which
    the window sets to the user's cache: a session's first build no longer
    translates every square again."""
    pytest.importorskip('PySide6')            # the editor's; the golden job has none

    from danu.core.square import SquareName, write_square
    from danu.surface import build
    from danu.surface import params as sp
    from danu.ui import surface

    zone = tmp_path / 'zone'
    zone.mkdir()
    sq, _ = ring(SquareName(125, -24), 125.5, -23.5, 200)
    write_square(sq, zone / 'S24E125.osm.xz')
    monkeypatch.setattr(surface, 'SQUARE_CACHE', surface.square_cache(tmp_path / 'user-cache'))
    p = sp.load().with_arcsec(3)
    surface.build_surface(zone, [SquareName(125, -24)], p, tmp_path / 'session1' / 'build-1')
    [piece] = surface.SQUARE_CACHE.glob('S24E125-*.gpkg')
    made = piece.stat().st_mtime_ns
    translated = []
    real = build.gdal.VectorTranslate
    monkeypatch.setattr(build.gdal, 'VectorTranslate', lambda *a, **k: translated.append(a[0]) or real(*a, **k))
    # a new session: a new work directory, the same user cache
    surface.build_surface(zone, [SquareName(125, -24)], p, tmp_path / 'session2' / 'build-1')
    assert [x for x in translated if 'S24E125-' in str(x)] == [], 'the square was translated again'
    assert piece.stat().st_mtime_ns == made


def test_the_square_cache_is_this_versions_and_others_go(tmp_path):
    pytest.importorskip('PySide6')            # the editor's; the golden job has none
    import os
    import time

    from danu import __version__
    from danu.ui import surface

    root = tmp_path / 'user-cache'
    for v in ('0.0.1', '0.0.2'):
        (root / 'square-cache' / v).mkdir(parents=True)
        (root / 'square-cache' / v / 'S24E125-ab.gpkg').write_bytes(b'old')
    # 0.0.1 unused for a week and more; 0.0.2 open now in another window
    week = time.time() - surface.OTHER_VERSIONS_KEPT_S - 60
    os.utime(root / 'square-cache' / '0.0.1', (week, week))
    got = surface.square_cache(root)
    assert got == root / 'square-cache' / __version__
    assert not (root / 'square-cache' / '0.0.1').exists()
    assert (root / 'square-cache' / '0.0.2' / 'S24E125-ab.gpkg').exists()
    # this version's marked used as a session starts, whatever it writes
    assert time.time() - got.stat().st_mtime < 60


def test_shading_leaves_no_intermediate_behind_and_matches_the_compressed_shading(tmp_path, monkeypatch):
    """The editor's shading writes its intermediates uncompressed and removes
    them once read - the same arrays as written compressed."""
    import numpy as np

    from danu.core.square import SquareName, write_square
    from danu.surface import build, shade
    from danu.surface import params as sp

    zone = tmp_path / 'zone'
    zone.mkdir()
    sq, _ = ring(SquareName(125, -24), 125.5, -23.5, 100, spot=150)
    write_square(sq, zone / 'S24E125.osm.xz')
    p = sp.load().with_arcsec(3)
    result = build.build_dem(zone, tmp_path / 'w', p)
    got = shade.shade_dem(result.dem, p, tmp_path / 'w')
    left = [f.name for f in (tmp_path / 'w').iterdir()
            if f.name.startswith(('merc-', 'hillshade-', 'smooth'))]
    assert left == [], left
    monkeypatch.setattr(shade, 'SCRATCH', shade.CREATE)
    want = shade.shade_dem(result.dem, p, tmp_path / 'w')
    assert np.array_equal(got.dem, want.dem) and np.array_equal(got.shade, want.shade)
