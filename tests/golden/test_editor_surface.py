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
    stages = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
              and not n.name.startswith('_') and n.name not in ('Result', 'build_dem', 'grid_for')]
    assert len(stages) >= 9
    missing = [n.name for n in stages if 'shell:' not in (ast.get_docstring(n) or '')]
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
