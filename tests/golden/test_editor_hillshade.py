"""The editor's hillshade against the shell's, from the same DEM.

The shell publishes hillshade-z2.tif; the editor draws a hillshade on its
canvas. Both come from the DEM by smoothing, a warp to spherical Mercator at a
cell size in metres, and gdaldem. This runs the shell build once - as the
golden surface test does - takes the DEM it produced, shades it the editor's
way, and asserts the shell's published hillshade cell for cell. "Showing the
same hillshade on screen demonstrates it once"; this demonstrates it every run.
"""

import ast
import os
import pathlib
import shutil
import subprocess
import tomllib

import pytest

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def test_every_shade_stage_names_the_shell_command_it_stands_for():
    src = (ROOT / 'danu' / 'surface' / 'shade.py').read_text()
    tree = ast.parse(src)
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
            and not n.name.startswith('_')}
    stages = ['smooth', 'fine_metres', 'warp_mercator', 'hillshade', 'shade_dem']
    display = {'Shaded', 'Scaling', 'compose', 'unreached_rgba'}   # the canvas's, not the shell's
    assert set(stages) <= set(defs), set(stages) - set(defs)
    assert set(defs) - set(stages) - display == set(), set(defs) - set(stages) - display
    missing = [n for n in stages if 'shell:' not in (ast.get_docstring(defs[n]) or '')]
    assert missing == []


@pytest.fixture(scope='module')
def shell_run(tmp_path_factory):
    """One shell build of the fixture; its DEM and its published hillshade."""
    tmp = tmp_path_factory.mktemp('shell')
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    base = tmp / 'base'
    (base / 'osm-squares' / 'golden').mkdir(parents=True)
    shutil.copy(SQUARE, base / 'osm-squares' / 'golden' / SQUARE.name)
    env = dict(os.environ, PYTHONPATH=str(ROOT), CONF=str(ROOT / 'server' / 'etc'), BASE=str(base),
               WORKBASE=str(tmp / 'work'), PUBROOT=str(tmp / 'pub'), ARCSEC=str(lock['arcsec']),
               WATER_CONSTRAINTS='0' if not lock['water_constraints'] else '1', KEEP_WORK='1')
    run = subprocess.run(['bash', str(ROOT / 'server' / 'bin' / 'danu-build-zone'), 'golden'],
                         capture_output=True, text=True, env=env, timeout=900)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    pub = tmp / 'pub' / 'golden'
    return {'dem': pub / 'dem-golden.tif', 'hillshade_z2': pub / 'hillshade-z2.tif',
            'hillshade_z5': pub / 'hillshade-z5.tif', 'arcsec': lock['arcsec']}


@pytest.mark.parametrize('zfactor', [2.0, 5.0])
def test_the_editors_hillshade_is_the_shells(tmp_path, shell_run, zfactor):
    import numpy as np
    from danu.surface import params, shade
    p = params.load().with_arcsec(shell_run['arcsec'])
    shaded = shade.shade_dem(shell_run['dem'], p, tmp_path, zfactor=zfactor)
    ref_ds = gdal.Open(str(shell_run[f'hillshade_z{zfactor:g}']))
    ref = ref_ds.GetRasterBand(1).ReadAsArray()
    assert shaded.shade.shape == ref.shape, f'editor {shaded.shade.shape}, shell {ref.shape}'
    differing = int((shaded.shade != ref).sum())
    assert differing == 0, f'{differing} of {ref.size} hillshade cells differ; worst {np.abs(shaded.shade.astype(int) - ref.astype(int)).max()}'
    assert all(abs(a - b) < 1e-6 for a, b in zip(shaded.geotransform, ref_ds.GetGeoTransform()))


def test_the_shaded_relief_composes_where_there_is_land(tmp_path, shell_run):
    import numpy as np
    from danu.surface import params, ramp, shade
    p = params.load().with_arcsec(shell_run['arcsec'])
    shaded = shade.shade_dem(shell_run['dem'], p, tmp_path)
    # land as the clamp made it, a metre or more; the bilinear warp leaves
    # sub-metre values along the coast where the hypsometric ramp fades out
    # between 0 and 1 m, which is its design and not a hole
    land = shaded.dem >= 1
    sea = shaded.dem <= 0
    assert land.any() and sea.any()
    for r in (ramp.traditional(), ramp.spectral()):
        rgba = shade.compose(shaded, r, shade.Scaling('auto'))
        assert rgba.shape == shaded.dem.shape + (4,) and rgba.dtype == np.uint8
        assert (rgba[land][:, 3] > 0).all()                 # land is drawn
        assert (rgba[sea][:, 3] == 0).all()                 # sea is see-through
    grey = shade.compose(shaded, None, shade.Scaling(), mode='hillshade')
    assert (grey[..., 0] == grey[..., 1]).all() and (grey[..., 1] == grey[..., 2]).all()
    pitch = shade.compose(shaded, ramp.spectral(), shade.Scaling('pitch', centre=150, width=20))
    # a pitch window of 140..160: everything above 160 saturates to the top colour
    top = ramp.spectral().colour(1.0)[:3]
    high = (shaded.dem > 165) & land
    if high.any():
        flat = shade.compose(shaded, ramp.spectral(), shade.Scaling('pitch', centre=150, width=20), mode='relief')
        assert (flat[high][:, :3] == np.array(top, np.uint8)).all()
    assert pitch.shape == rgba.shape
