"""The editor's surface path against the same reference the shell is held to.

Two ways to a surface exist now, and this is what lets them: the golden
fixture driven through danu.surface.build - the functions the editor calls -
must produce, cell for cell, the DEM that danu-build-zone produces from it,
which tests/golden/test_golden_surface.py holds to expected.tif.
"""

import ast
import pathlib
import shutil
import tomllib

import pytest

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'
EXPECTED = HERE / 'expected.tif'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def test_every_stage_names_the_shell_command_it_stands_for():
    """The requirement the spec makes of this path: each stage carries a
    shell: line, so when either side changes the other is findable."""
    src = (ROOT / 'danu' / 'surface' / 'build.py').read_text()
    tree = ast.parse(src)
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
            and not n.name.startswith('_')}
    # every stage, by name, so a new one added without a shell: line is caught
    # by the second assertion and a stage renamed away is caught by the first
    stages = ['Grid', 'squares_with_constraints', 'grid_for', 'lines_osmconf', 'check_long_ways',
              'collect', 'rasterise', 'drawn_area', 'water_constraints', 'water_mask',
              'interpolate', 'clamp']
    assert set(stages) <= set(defs), f'stages missing from build.py: {set(stages) - set(defs)}'
    not_stages = set(defs) - set(stages) - {'Result', 'build_dem'}
    assert not_stages == set(), f'new top-level names need a shell: line or listing here: {not_stages}'
    missing = [name for name in stages if 'shell:' not in (ast.get_docstring(defs[name]) or '')]
    assert missing == [], f'stages without a shell: line: {missing}'


def test_the_editors_surface_is_the_shells_surface(tmp_path):
    from danu.surface import build, params
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    zone = tmp_path / 'golden'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    p = params.load().with_arcsec(lock['arcsec'])
    lines = []
    result = build.build_dem(zone, tmp_path / 'work', p, water=bool(lock['water_constraints']),
                             log=lines.append)
    assert result.dem is not None, '\n'.join(lines)
    assert result.water_mask is None                   # the square has no coastline
    import numpy as np
    # the datasets are held: gdal.Open(p).GetRasterBand(1).ReadAsArray() frees
    # the dataset under the band and fails inside gdal_array
    ref_ds, new_ds = gdal.Open(str(EXPECTED)), gdal.Open(str(result.dem))
    a = ref_ds.GetRasterBand(1).ReadAsArray()
    b = new_ds.GetRasterBand(1).ReadAsArray()
    assert a.shape == b.shape, f'reference {a.shape}, editor {b.shape}'
    differing = int((a != b).sum())
    assert differing == 0, f'{differing} of {a.size} cells differ; worst {np.abs(a - b).max():.3f} m'
    # and the grids are the same grid, not merely the same shape
    ref_gt, new_gt = ref_ds.GetGeoTransform(), new_ds.GetGeoTransform()
    assert all(abs(x - y) < 1e-12 for x, y in zip(ref_gt, new_gt)), (ref_gt, new_gt)


def test_the_files_grad_min_is_the_binarys_default_which_both_paths_rely_on():
    """Neither path passes --grad-min: the shell never did, and the editor
    mirrors it. The file still carries the value, so it is held here to what
    isofill actually uses, read from the binary itself."""
    import re
    import subprocess
    from danu.surface import params
    usage = subprocess.run(['isofill'], capture_output=True, text=True).stdout + \
        subprocess.run(['isofill'], capture_output=True, text=True).stderr
    m = re.search(r'--grad-min F.*?\(default ([0-9.]+)\)', usage, re.S)
    assert m, 'isofill usage no longer states a --grad-min default'
    assert float(m.group(1)) == params.load().grad_min
