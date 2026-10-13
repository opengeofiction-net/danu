"""J1: the version where a mapper reporting a fault will look for it - the
title, Help › About and the usage log - and the versions of what Danu runs
on, which a report needs as much."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QGuiApplication

from danu import __version__
from danu.ui import about


def test_the_title_carries_the_version_with_or_without_a_working_set(window):
    assert window.windowTitle().startswith(f'Danu {__version__} - ')
    assert about.title() == f'Danu {__version__}'
    assert about.title('N20E086', True) == f'Danu {__version__} - N20E086 *'


def test_help_about_names_the_version_and_what_it_runs_on(window, qtbot):
    help_ = next(a.menu() for a in window.menuBar().actions() if a.text().replace('&', '') == 'Help')
    assert window.about_action in help_.actions()
    v = {'danu': __version__, 'python': '3.x', 'qt': '6.x', 'pyside6': '6.x', 'platform': 'p',
         'gdal': 'not available (No module named osgeo)', 'isofill': '0.12.0 (/lib/libisofill.so)'}
    dlg = about.AboutDialog(window, v)
    qtbot.addWidget(dlg)
    assert f'danu: {__version__}' in dlg.versions and 'gdal: not available' in dlg.versions
    dlg.show()
    dlg.copy.click()
    assert QGuiApplication.clipboard().text() == dlg.versions
    assert dlg.isVisible(), 'copying leaves the box open'


def test_the_versions_say_why_a_library_is_missing(monkeypatch):
    from danu.surface import isofill_lib

    def refuse():
        raise isofill_lib.IsofillError('no libisofill could be loaded:\n  libisofill.so: not found')
    monkeypatch.setattr(isofill_lib.Isofill, 'load', staticmethod(refuse))
    v = about.versions()
    assert v['danu'] == __version__
    assert v['isofill'] == 'not available (no libisofill could be loaded:)'
    assert v['gdal']


def test_the_icon_is_there_at_every_size_it_was_drawn_at():
    sizes = {s.width() for s in about.icon().availableSizes()}
    assert sizes == {16, 24, 32, 48, 64, 128, 256}
