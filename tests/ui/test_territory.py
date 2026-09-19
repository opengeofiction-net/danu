"""The territory fetcher and the status line: whose ground is the set on."""

import pytest

pytest.importorskip('PySide6')

from danu.core.square import SquareName                              # noqa: E402
from danu.ui.territory import TerritoryFetcher                       # noqa: E402


def test_the_fetcher_reads_both_files_caches_them_and_serves_the_cache_while_fresh(qtbot, tmp_path, territory_files, qapp):
    cache = tmp_path / 'tcache'
    f = TerritoryFetcher(cache, geometry_url=(territory_files / 'territory.json').as_uri(),
                         attributes_url=(territory_files / 'admin.json').as_uri(), parent=qapp)
    with qtbot.waitSignal(f.ready, timeout=5000):
        f.refresh()
    qtbot.waitUntil(lambda: f.complete, timeout=5000)
    assert (cache / 'territory-geometry.json').exists() and (cache / 'territory-attributes.json').exists()
    assert [t.name for t in f.index.under(SquareName(125, -24).bounds)] == ['Pizarrales']
    # fresh on disk: a second fetcher serves it without the network
    g = TerritoryFetcher(cache, geometry_url='file:///nowhere/geometry.json', attributes_url='file:///nowhere/admin.json', parent=qapp)
    with qtbot.waitSignal(g.ready, timeout=5000):
        g.refresh()
    assert g.complete and not g._inflight
    # stale on disk and the network gone: the copy on disk is used, and said so
    import os, time
    old = time.time() - 10 * 24 * 3600
    for p in cache.iterdir():
        os.utime(p, (old, old))
    h = TerritoryFetcher(cache, geometry_url='file:///nowhere/geometry.json', attributes_url='file:///nowhere/admin.json', parent=qapp)
    failures = []
    h.failed.connect(failures.append)
    with qtbot.waitSignal(h.ready, timeout=5000):
        h.refresh()
    qtbot.waitUntil(lambda: len(failures) == 2, timeout=5000)
    assert all('using the copy on disk' in t for t in failures) and h.complete


def test_the_window_names_the_ground_and_warns_when_it_is_somebody_elses(window, qtbot):
    w = window
    qtbot.waitUntil(lambda: 'Pizarrales' in w._territory.text(), timeout=5000)
    assert w._territory.text() == 'Pizarrales (AR031), owned by Luciano'      # no user set: told, not warned
    assert w._territory.styleSheet() == ''
    w.settings.user = 'wangi'
    w.show_territory()
    assert w._territory.text().startswith('not yours to draw: Pizarrales') and 'bold' in w._territory.styleSheet()
    assert 'opening it anyway' in w.statusBar().currentMessage()
    w.settings.user = 'Luciano'
    w.show_territory()
    assert w._territory.styleSheet() == ''
    # the square east straddles two territories, one of them collaborative
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.open_working_set(w.zone_dir, SquareName(126, -24))
    qtbot.waitUntil(lambda: 'Tenmetre' in w._territory.text(), timeout=5000)
    # the centre, 126.5, is exactly on the fixture's border and falls east; both are named
    assert w._territory.text() == 'Tenmetre (AR032), collaborative; Pizarrales (AR031), owned by Luciano'
    # north: a polygon with no record
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.open_working_set(w.zone_dir, SquareName(125, -22))
    qtbot.waitUntil(lambda: 'unknown' in w._territory.text(), timeout=5000)
    assert w._territory.text() == 'unknown territory (relation 103)'
