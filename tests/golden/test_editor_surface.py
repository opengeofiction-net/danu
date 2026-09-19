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
              'interpolate', 'clamp', 'first_pass_classes', 'first_pass_reading']
    assert set(stages) <= set(defs), f'stages missing from build.py: {set(stages) - set(defs)}'
    not_stages = set(defs) - set(stages) - {'Result', 'build_dem'}
    assert not_stages == set(), f'new top-level names need a shell: line or listing here: {not_stages}'
    missing = [name for name in stages if 'shell:' not in (ast.get_docstring(defs[name]) or '')]
    assert missing == [], f'stages without a shell: line: {missing}'


@pytest.mark.parametrize('library', [False, True], ids=['binary', 'library'])
def test_the_editors_surface_is_the_shells_surface(tmp_path, library):
    """Both ways the editor can call isofill - the binary, and the library
    whose function the binary's own path calls - held to the one reference."""
    from danu.surface import build, params
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    zone = tmp_path / 'golden'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    p = params.load().with_arcsec(lock['arcsec'])
    lines = []
    result = build.build_dem(zone, tmp_path / 'work', p, water=bool(lock['water_constraints']),
                             log=lines.append, library=library)
    assert result.dem is not None, '\n'.join(lines)
    assert any('as a library' in l for l in lines) == library, '\n'.join(lines)
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
    run = subprocess.run(['isofill'], capture_output=True, text=True)
    usage = run.stdout + run.stderr
    m = re.search(r'--grad-min F.*?\(default ([0-9.]+)\)', usage, re.S)
    assert m, 'isofill usage no longer states a --grad-min default'
    assert float(m.group(1)) == params.load().grad_min


def test_the_library_is_the_binary_on_a_raster_the_golden_square_does_not_cover(tmp_path):
    """A synthetic raster with a mask and water, filled by the binary and by
    the library from the same file, compared cell for cell. The golden
    square has no water and one drawn envelope; this has both."""
    import subprocess
    import numpy as np
    from danu.surface import isofill_lib, params
    lib = isofill_lib.Isofill.load()
    rows, cols = 96, 128
    cons = np.full((rows, cols), -9999, dtype=np.int16)
    cons[20, 10:118] = 100          # two contours and a coastline
    cons[70, 10:118] = 200
    cons[90, :] = 0
    mask = np.ones((rows, cols), np.uint8)
    mask[:, :6] = 0                 # a strip nobody drew
    water = np.zeros((rows, cols), np.uint8)
    water[92:, :] = 1               # the sea below the coastline

    def write(path, arr, dtype, nodata=None):
        ds = gdal.GetDriverByName('GTiff').Create(str(path), cols, rows, 1, dtype)
        ds.SetGeoTransform((10.0, 1 / 1200, 0, 20.0, 0, -1 / 1200))
        b = ds.GetRasterBand(1)
        if nodata is not None:
            b.SetNoDataValue(nodata)
        b.WriteArray(arr)
        ds = None
    write(tmp_path / 'cont.tif', cons, gdal.GDT_Int16, -9999)
    write(tmp_path / 'mask.tif', mask, gdal.GDT_Byte)
    write(tmp_path / 'water.tif', water, gdal.GDT_Byte)
    p = params.load().with_arcsec(3)
    subprocess.run(['isofill', '--radius', str(p.fill_cells), '--barrier', str(p.barrier_cells),
                    '--max-mem', str(p.max_mem_mb), '--mask', str(tmp_path / 'mask.tif'),
                    '--water', str(tmp_path / 'water.tif'), str(tmp_path / 'cont.tif'),
                    str(tmp_path / 'bin.tif')], check=True, capture_output=True)
    ds = gdal.Open(str(tmp_path / 'bin.tif'))
    from_binary = ds.GetRasterBand(1).ReadAsArray()
    from_library, filled = lib.run(cons.astype(np.float32), p, mask=mask, water=water, nodata=-9999)
    assert filled > 0
    assert from_library.shape == from_binary.shape
    differing = int((from_library != from_binary).sum())
    assert differing == 0, f'{differing} of {from_library.size} cells differ between library and binary'
    assert (from_library[92:, :] == 0).all()                      # water held at zero
    assert (from_library[20, 10:118] == 100).all()                # constraints as themselves


def test_the_library_refuses_a_version_it_was_not_written_for(monkeypatch):
    from danu.surface import isofill_lib
    try:
        isofill_lib.Isofill.load()
    except isofill_lib.IsofillError as e:
        pytest.skip(f'no loadable libisofill here: {str(e).splitlines()[0]}')
    monkeypatch.setattr(isofill_lib, 'EXPECTED_VERSION', '9.9.9')
    with pytest.raises(isofill_lib.IsofillError, match='wants 9.9.9'):
        isofill_lib.Isofill.load()


def test_the_files_grad_min_is_the_librarys_default_which_the_library_call_leaves_alone():
    """The library call sets radius, barrier and pass 2 and leaves grad_min as
    isofill_params_default() has it - so this is the value both editor paths
    and the shell all rely on, and the file must carry the same one."""
    from danu.surface import isofill_lib, params
    lib = isofill_lib.Isofill.load()
    assert lib.default_grad_min() == params.load().grad_min


def test_the_first_pass_reading_says_where_the_contours_do_not_describe_ground(tmp_path):
    """R20's overlay, from the fixture: every cell is classed, cells outside
    the drawn area are OUTSIDE, and a sparse square has ground its contours
    leave the first pass unable to answer."""
    import numpy as np
    from danu.surface import build, params, shade
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    zone = tmp_path / 'golden'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    p = params.load().with_arcsec(lock['arcsec'])
    r = build.build_dem(zone, tmp_path / 'work', p)
    assert r.envelopes is not None and r.envelopes.exists()
    classes_path = build.first_pass_classes(r.constraints, r.drawn_mask, p, tmp_path / 'work')
    c_ds, m_ds = gdal.Open(str(classes_path)), gdal.Open(str(r.drawn_mask))   # held
    classes = c_ds.GetRasterBand(1).ReadAsArray()
    mask = m_ds.GetRasterBand(1).ReadAsArray()
    assert classes.shape == mask.shape
    assert ((classes == build.OUTSIDE) == (mask == 0)).all()
    inside = classes[mask != 0]
    assert set(np.unique(inside).tolist()) <= {build.ANSWERED, build.UNREACHED, build.DECLINED, build.ONE_ONLY}
    assert (inside == build.UNREACHED).sum() > 0                     # ground the contours do not reach
    assert (inside == build.ANSWERED).sum() > 0                      # and some they do
    # the reading: measured on this grid, area by cos(lat), one number for log and panel
    import json
    reading = json.loads(classes_path.with_suffix('.json').read_text())
    assert reading['cells']['1'] == int((inside == build.UNREACHED).sum())
    assert reading['inside_cells'] == int((mask != 0).sum())
    cell_km2_equator = (abs(r.grid.res) * 111.32) ** 2
    assert 0 < reading['inside_km2'] < reading['inside_cells'] * cell_km2_equator   # cos(24 S) < 1
    assert abs(sum(reading['percent'].values()) - 100.0 * sum(reading['km2'].values()) / reading['inside_km2']) < 1e-6
    # and the overlay lands on the surface's grid
    shaded = shade.shade_dem(r.dem, p, tmp_path / 'work', classes=classes_path)
    assert shaded.classes is not None and shaded.classes.shape == shaded.shade.shape
    assert shaded.reading == reading                                 # carried, not recounted
    rgba = shade.unreached_rgba(shaded.classes)
    assert rgba.shape == shaded.shade.shape + (4,)
    assert (rgba[shaded.classes == build.OUTSIDE][:, 3] == 0).all()
    assert (rgba[shaded.classes == build.UNREACHED][:, 3] > 0).all()
