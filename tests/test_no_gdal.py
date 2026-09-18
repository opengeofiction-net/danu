"""danu.core.profile must import without GDAL.

The CI comment claimed this before it was true. Both test modules imported
danu.checks.rivers and danu.water.constraints, which import osgeo at module
level, so every run of the tests job failed with ModuleNotFoundError and the
badge was red from the first push - unnoticed, because the tests passed on a
laptop that has GDAL.

The property is worth having: it is what lets the suite run on Windows, where
GDAL is not reasonably installable from PyPI, and it keeps the functions which
decide what a contour means separable from the ones which read rasters. So it
is asserted rather than asserted-in-a-comment.
"""

import builtins

import pytest


def test_profile_imports_without_gdal(monkeypatch):
    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split('.')[0] == 'osgeo':
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', blocked)
    for mod in ('danu.core.profile',):
        monkeypatch.delitem(__import__('sys').modules, mod, raising=False)
        importlib = __import__('importlib')
        importlib.import_module(mod)


def test_the_pure_module_names_no_raster_library():
    import pathlib
    src = pathlib.Path(__file__).parents[1] / 'danu' / 'core' / 'profile.py'
    text = src.read_text()
    for banned in ('osgeo', 'gdal', 'ogr.', 'urllib'):
        assert banned not in text, f'danu.core.profile should not mention {banned}'
