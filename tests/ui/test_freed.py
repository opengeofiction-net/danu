"""A closed window is freed: anything that keeps one keeps every test's,
and the suite slows as it goes - from 4 to 12 minutes on CI (#229, and the
water read alongside a set as it opens)."""
import gc
import weakref

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from danu.core.square import SquareName


@pytest.mark.parametrize('pooled', [False, True], ids=['in place', 'on the pool'])
def test_a_closed_window_with_a_set_open_is_freed(qtbot, zone, tmp_path, territory_files, pooled):
    """In place, as the tests run the checks; on the pool, as the app does -
    which keeps each job it ran. Two sets opened, so the first's is let go."""
    from danu.ui.app import MainWindow
    from danu.ui.config import load_layers
    from danu.ui.settings import Settings
    from danu.ui.territory import TerritoryFetcher
    fetcher = TerritoryFetcher(tmp_path / 'tcache', geometry_url=(territory_files / 'territory.json').as_uri(),
                               attributes_url=(territory_files / 'admin.json').as_uri())
    settings = Settings(tmp_path / 'danu.ini')
    settings.import_root = tmp_path / 'import'
    w = MainWindow(load_layers(), cache_dir=None, settings=settings, territory_fetcher=fetcher)
    w.prompt_on_close = False
    if not pooled:
        w._write_runner = w._checks_runner = lambda job: job.run()
    w.show()
    qtbot.waitExposed(w)
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(125, -24))
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(zone, SquareName(126, -24))
    QThreadPool.globalInstance().waitForDone(10000)
    QApplication.processEvents()
    gone = weakref.ref(w)
    w.close()
    w.deleteLater()
    del w, fetcher
    QApplication.processEvents()
    qtbot.wait(50)
    gc.collect()
    assert gone() is None
