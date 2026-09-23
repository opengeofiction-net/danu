"""danu.surface.build against the reference, and the shell held to calling it.

One implementation of the stages up to the DEM, shared by the editor and the
nightly build: the golden fixture driven through danu.surface.build must
produce, cell for cell, the DEM that danu-build-zone publishes from it, which
tests/golden/test_golden_surface.py holds to expected.tif. Until phase 4 the
shell had its own copy of every one of those stages and this file's job was to
pin the two together; its job now is to say the copy has not come back.
"""

import ast
import pathlib
import re
import shutil
import tomllib

import pytest

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'
EXPECTED = HERE / 'expected.tif'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


SHELL = ROOT / 'server' / 'bin' / 'danu-build-zone'


def shell_code() -> list[str]:
    """danu-build-zone with its comments removed, so that a stage named in
    prose is not mistaken for one being run."""
    return [l for l in SHELL.read_text().splitlines() if not l.lstrip().startswith('#')]


def test_the_shell_runs_the_surface_build_rather_than_its_own_copy():
    """Phase 4 left one implementation of the stages up to the DEM. This is
    what says so: the shell calls the module, and none of the commands its
    copy was made of are still being run here. A second copy is how the editor
    and the nightly build come to disagree about what a contour means, which
    the golden reference can only catch after the fact."""
    code = '\n'.join(shell_code())
    assert 'python -m danu.surface.build' in code.replace('${PYTHON}', 'python')
    retired = ['gdal_rasterize', 'ogr2ogr', 'ogrinfo', 'zone_extent', 'drawn_mask',
               'sea_mask', 'land_clamp', 'closed_ways_are_polygons', 'xz -dc']
    still_there = [name for name in retired if name in code]
    assert still_there == [], f'danu-build-zone still runs its own copy of: {still_there}'
    # and isofill itself, which needs the word rather than a path fragment
    assert not re.search(r'(^|\s)isofill\s+--', code, re.M), 'danu-build-zone still calls isofill'


def test_the_shell_hands_a_replacement_parameter_file_to_both_commands():
    """PARAMS is the override that FILL_METRES, BARRIER_CELLS and MAX_MEM used
    to have one each of. The parameters the shell reads and the ones the
    surface reads have to come from the same file, or a run with PARAMS set
    builds at one resolution and slices the archive at another."""
    code = '\n'.join(shell_code())
    assert 'params_args+=(--params "${PARAMS}")' in code
    assert code.count('"${params_args[@]}"') == 2, \
        'both danu.surface.params and danu.surface.build need the same file'


def test_the_shell_takes_the_surfaces_answer_by_its_exit_status():
    """``eval "$(cmd)"`` takes eval's status and not the command's, so under
    ``set -e`` a surface build that died would be carried on from silently -
    which is what the old extent step did. The assignments come back in a file
    that is sourced after the command has been allowed to fail."""
    code = '\n'.join(shell_code())
    assert 'eval "$(' not in code
    assert re.search(r'^\. \$\{SURFACE\}$', code, re.M), 'the surface assignments are not sourced'


def test_the_shell_reads_the_shared_parameters_rather_than_copying_them():
    """The values were ${VAR:-default} constants here and a test held them
    equal to elevation.toml. The file is read now, so the parameters the
    surface owns have no spelling in the shell at all."""
    code = '\n'.join(shell_code())
    assert 'danu.surface.params --shell' in code
    for gone in ('FILL_METRES', 'BARRIER_CELLS', 'MAX_MEM', 'FILL_CELLS'):
        assert gone not in code, f'{gone} is still a constant in danu-build-zone'
    for name in ('ARCSEC', 'HGT_ARCSEC', 'SMOOTH_CELLS'):
        assert f'{name}=${{{name}:-${{DANU_{name}}}}}' in code, \
            f'{name} should come from the file with an environment override'


def test_every_stage_is_named_and_documented():
    """build.py is the only place these stages live now, so the check that
    used to hold each one to its shell counterpart holds it to a docstring
    instead - and still catches a stage added or renamed without anyone
    saying so here."""
    src = (ROOT / 'danu' / 'surface' / 'build.py').read_text()
    tree = ast.parse(src)
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
            and not n.name.startswith('_')}
    stages = ['Grid', 'squares_with_constraints', 'grid_for', 'lines_osmconf', 'check_long_ways',
              'collect', 'rasterise', 'drawn_area', 'water_constraints', 'water_areas',
              'water_mask', 'interpolate', 'clamp', 'first_pass_classes', 'first_pass_reading']
    assert set(stages) <= set(defs), f'stages missing from build.py: {set(stages) - set(defs)}'
    not_stages = set(defs) - set(stages) - {'Result', 'build_dem', 'main'}
    assert not_stages == set(), f'new top-level names need listing here: {not_stages}'
    undocumented = [name for name in stages if not ast.get_docstring(defs[name])]
    assert undocumented == [], f'stages with no docstring: {undocumented}'
    # The reasoning the shell's comments carried came across with the code. Each
    # of these is a measurement that cost a rebuild to get and is not derivable
    # from the code: why the coastline is read as a line, why the barrier is 2,
    # why the second pass is masked, why the memory budget is what it is.
    for measured in ('a median of 1,693 m',          # coastline as an area, on axian
                     '54.88, 54.71, 49.29 and 46.46%',  # the barrier sweep on ellarca
                     '100% cells the first pass never reached',  # the unmasked streaks
                     'zone-yuethon at 18104 MB'):     # the memory budget
        assert measured in src, f'the reasoning for this was lost: {measured!r}' 


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


def test_a_square_the_editor_wrote_builds_to_the_same_surface(tmp_path):
    """Phase 3's ground rule, tested from the other side: the fixture read
    by the editor, written by the editor - a different file from JOSM's,
    byte for byte - and built by the shell, gives expected.tif exactly. So
    what the editor saves is a square the server builds, and builds to the
    same ground."""
    import os
    import subprocess
    from danu.core.square import read_square, write_square
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    base = tmp_path / 'base'
    (base / 'osm-squares' / 'golden').mkdir(parents=True)
    write_square(read_square(SQUARE), base / 'osm-squares' / 'golden' / SQUARE.name)
    assert (base / 'osm-squares' / 'golden' / SQUARE.name).read_bytes() != SQUARE.read_bytes()
    env = dict(os.environ, PYTHONPATH=str(ROOT), CONF=str(ROOT / 'server' / 'etc'), BASE=str(base),
               WORKBASE=str(tmp_path / 'work'), PUBROOT=str(tmp_path / 'pub'), ARCSEC=str(lock['arcsec']),
               WATER_CONSTRAINTS='0' if not lock['water_constraints'] else '1')
    run = subprocess.run(['bash', str(ROOT / 'server' / 'bin' / 'danu-build-zone'), 'golden'],
                         capture_output=True, text=True, env=env, timeout=900)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    ref_ds, new_ds = gdal.Open(str(EXPECTED)), gdal.Open(str(tmp_path / 'pub' / 'golden' / 'dem-golden.tif'))
    a, b = ref_ds.GetRasterBand(1).ReadAsArray(), new_ds.GetRasterBand(1).ReadAsArray()
    assert a.shape == b.shape and int((a != b).sum()) == 0


def test_a_square_drawn_from_blank_saved_by_the_editor_builds_on_the_server_path(tmp_path):
    """Phase 3's exit criterion, as the spec states it: a square can be drawn
    from blank and built by the server unchanged. A square nobody has drawn
    gets a hill through the edit commands, is saved as the editor saves -
    frame added, split if needed, written with upload='never' - and the
    shell pipeline builds the zone it lands in. The editor's own path builds
    the same zone to the same cells, and the DEM has the hill in it."""
    import os
    import subprocess
    from danu.core import edits, save
    from danu.core.square import Square, SquareName
    from danu.surface import build, params
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    # a hill: four concentric closed contours, the innermost 251 m
    sq = Square(name=SquareName(126, -24))
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    for i in range(4):
        ele, d = 101 + 50 * i, 0.4 - 0.09 * i
        pts = [(126.5 - d, -23.5 - d), (126.5 + d, -23.5 - d), (126.5 + d, -23.5 + d), (126.5 - d, -23.5 + d)]
        ids = [alloc.take() for _ in pts]
        hist.do(sq, edits.AddWay(alloc.take(), ids, pts, {'ele': str(ele)}))
        hist.do(sq, edits.ExtendWayWithExisting(min(sq.ways), True, ids[0]))
    base = tmp_path / 'base'
    zone = base / 'osm-squares' / 'blank'
    zone.mkdir(parents=True)
    report = save.save_square(sq, hist, save.default_path(zone, sq.name))
    assert report.framed and not hist.dirty(sq)
    # the server's path
    env = dict(os.environ, PYTHONPATH=str(ROOT), CONF=str(ROOT / 'server' / 'etc'), BASE=str(base),
               WORKBASE=str(tmp_path / 'work'), PUBROOT=str(tmp_path / 'pub'), ARCSEC=str(lock['arcsec']),
               WATER_CONSTRAINTS='0' if not lock['water_constraints'] else '1')
    run = subprocess.run(['bash', str(ROOT / 'server' / 'bin' / 'danu-build-zone'), 'blank'],
                         capture_output=True, text=True, env=env, timeout=900)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    # the editor's path, on the same zone
    p = params.load().with_arcsec(lock['arcsec'])
    result = build.build_dem(zone, tmp_path / 'ework', p, water=bool(lock['water_constraints']))
    assert result.dem is not None
    shell_ds, editor_ds = gdal.Open(str(tmp_path / 'pub' / 'blank' / 'dem-blank.tif')), gdal.Open(str(result.dem))
    a, b = shell_ds.GetRasterBand(1).ReadAsArray(), editor_ds.GetRasterBand(1).ReadAsArray()
    assert a.shape == b.shape and int((a != b).sum()) == 0
    # and it is the hill that was drawn: the summit plateau at the top contour,
    # the ground outside the lowest one below it
    gt = shell_ds.GetGeoTransform()
    col, row = int((126.5 - gt[0]) / gt[1]), int((-23.5 - gt[3]) / gt[5])
    assert a[row, col] == 251
    col, row = int((126.05 - gt[0]) / gt[1]), int((-23.95 - gt[3]) / gt[5])
    assert a[row, col] < 101
