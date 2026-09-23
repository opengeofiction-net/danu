"""``python -m danu.surface.build``: what danu-build-zone gets back from it.

The shell hands the whole surface to this command and carries on from the DEM,
so what it says - the grid for the .hgt slicing, whether there was anything to
build at all - is an interface, not a log line.
"""

import lzma
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')


def read_assignments(path: pathlib.Path) -> dict[str, str]:
    """The shell file as a dict, parsed the way `.` would read it."""
    out = {}
    for line in path.read_text().splitlines():
        name, _, value = line.partition('=')
        out[name] = value.strip('"')
    return out


def write_square(path: pathlib.Path, ele: str | None) -> None:
    """A square with one closed way, with or without an elevation on it."""
    tag = f'<tag k="ele" v="{ele}"/>' if ele is not None else ''
    nodes = ''.join(
        f'<node id="-{i + 1}" lat="{-23.8 + 0.1 * (i in (2, 3))}" '
        f'lon="{125.2 + 0.1 * (i in (1, 2))}"/>' for i in range(4))
    refs = ''.join(f'<nd ref="-{i + 1}"/>' for i in (1, 2, 3, 4, 1))
    xml = (f'<?xml version="1.0"?>\n<osm version="0.6" generator="test">'
           f'{nodes}<way id="-1">{refs}{tag}</way></osm>')
    with lzma.open(path, 'wb') as fh:
        fh.write(xml.encode())


def run_cli(zone: pathlib.Path, work: pathlib.Path, *args: str):
    return subprocess.run(
        [sys.executable, '-m', 'danu.surface.build', str(zone), str(work), *args],
        capture_output=True, text=True, cwd=ROOT, timeout=900)


# --------------------------------------------------------------- the grid

def test_the_grid_it_reports_is_the_grid_the_hgt_slicing_needs(tmp_path):
    """TE_HGT is the degree extent at 3 arcseconds, not at the master's
    resolution. SRTMHGT insists on exactly 1201 samples square, so half a cell
    of the wrong size makes every slice fractional and the archive empty."""
    from danu.surface.build import Grid
    g = Grid(west=125, east=126, south=-24, north=-23, arcsec=1)
    assert g.te == (124.999861111, -24.000138889, 126.000138889, -22.999861111)
    assert g.te_at(3) == (124.999583333, -24.000416667, 126.000416667, -22.999583333)
    assert g.te != g.te_at(3), 'the master and the archive are on different grids'
    assert g.size == (3601, 3601)
    assert Grid(125, 126, -24, -23, 3).size == (1201, 1201)


@pytest.mark.skipif(not (ROOT / 'tests' / 'golden' / 'expected.tif').exists(),
                    reason='no golden fixture')
def test_the_shell_file_says_where_the_dem_is_and_what_ground_it_covers(tmp_path):
    if shutil.which('isofill') is None:
        pytest.skip('isofill not on PATH')
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    run = run_cli(zone, tmp_path / 'work', '--arcsec', '3', '--zone', 'golden',
                  '--shell', str(tmp_path / 'surface.sh'))
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    a = read_assignments(tmp_path / 'surface.sh')
    assert a['SQUARES'] == '1' and a['BLANK'] == '0'
    assert (a['WEST'], a['EAST'], a['SOUTH'], a['NORTH']) == ('125', '126', '-24', '-23')
    assert a['TE_HGT'] == '124.999583333 -24.000416667 126.000416667 -22.999583333'
    assert pathlib.Path(a['DEM']).exists()
    # the log is the log; nothing on stdout is ever evaluated by the caller
    assert '=== golden: interpolate' in run.stdout


def test_an_overridden_archive_spacing_reaches_the_grid_it_is_reported_on(tmp_path):
    """HGT_ARCSEC can be overridden in the shell's environment, and the shell
    slices the .hgt archive at whatever it ends up being. TE_HGT has to follow
    it rather than the file, or the warp and the slicing are on different
    grids - and SRTMHGT, which insists on exactly 1201 samples square, then
    refuses every slice."""
    if shutil.which('isofill') is None:
        pytest.skip('isofill not on PATH')
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Drawn.osm.xz', ele='100')
    for arcsec, half in (('3', '124.999583333'), ('1', '124.999861111')):
        out = tmp_path / f'surface-{arcsec}.sh'
        run = run_cli(zone, tmp_path / f'work{arcsec}', '--arcsec', '30',
                      '--hgt-arcsec', arcsec, '--shell', str(out))
        assert run.returncode == 0, run.stderr[-2000:]
        assert read_assignments(out)['TE_HGT'].startswith(half), read_assignments(out)


def test_a_zone_of_blank_templates_builds_nothing_and_says_so(tmp_path):
    """Templates are laid out before the drawing starts, so a zone with
    nothing in it yet is not a failure - but the caller has to be able to tell
    that from a build that produced a DEM."""
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Blank.osm.xz', ele=None)
    run = run_cli(zone, tmp_path / 'work', '--arcsec', '3',
                  '--shell', str(tmp_path / 'surface.sh'))
    assert run.returncode == 0, run.stderr[-2000:]
    a = read_assignments(tmp_path / 'surface.sh')
    assert a['SQUARES'] == '0' and a['BLANK'] == '1' and a['DEM'] == ''
    assert 'WEST' not in a, 'there is no grid to report when there is nothing to build'


def test_a_square_left_uncompressed_is_reported_and_not_quietly_skipped(tmp_path):
    """The squares are held as .osm.xz. A bare .osm beside them is somebody's
    drop that never got packed, and building the zone without their work in it
    silently is the outcome worth avoiding."""
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Drawn.osm.xz', ele='100')
    (zone / 'S23E125_Dropped.osm').write_text('<osm version="0.6"/>')
    run = run_cli(zone, tmp_path / 'work', '--arcsec', '3',
                  '--shell', str(tmp_path / 'surface.sh'))
    assert 'S23E125_Dropped.osm' in run.stdout
    assert 'xz these' in run.stdout
    # and the extent is the drawn square's alone, the loose one not read
    a = read_assignments(tmp_path / 'surface.sh')
    assert a.get('NORTH') == '-23', run.stdout


def test_the_blank_count_is_the_zones_and_not_a_working_sets(tmp_path):
    """BLANK is how many of the zone's squares are still templates. A working
    set is a handful of named squares out of a zone, so the ones it did not
    ask for are not blank - they are somewhere else, and counting them as
    blank made the number negative."""
    from danu.core.square import SquareName
    from danu.surface import build, params
    if shutil.which('isofill') is None:
        pytest.skip('isofill not on PATH')
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Drawn.osm.xz', ele='100')
    write_square(zone / 'S23E125_Drawn.osm.xz', ele='100')
    write_square(zone / 'S22E125_Blank.osm.xz', ele=None)
    p = params.load().with_arcsec(30)          # 121x121, so the fill is instant
    whole = build.build_dem(zone, tmp_path / 'w1', p)
    assert whole.blank == 1 and len(whole.squares) == 2
    one = build.build_dem(zone, tmp_path / 'w2', p, names=[SquareName(125, -24)])
    assert one.blank == 0 and len(one.squares) == 1
    # and an empty working set does not report the zone's blank count at it
    lines = []
    empty = build.build_dem(zone, tmp_path / 'w3', p, names=[SquareName(125, -22)],
                            log=lines.append)
    assert empty.dem is None
    assert any('working set' in l for l in lines), lines
    assert not any('squares, none with contours' in l for l in lines), lines


def test_a_different_parameter_file_can_be_given_for_one_run(tmp_path):
    """PARAMS is what FILL_METRES, BARRIER_CELLS and MAX_MEM used to be three
    separate environment overrides for. Trying a change on one zone before it
    becomes the default is the reason those existed, and a whole file covers
    every parameter rather than the three somebody thought to expose."""
    from danu.surface import params
    packaged = pathlib.Path(str(params.resources.files('danu.params')
                                .joinpath('elevation.toml'))).read_text()
    other = tmp_path / 'elevation.toml'
    other.write_text(packaged.replace('metres = 1850', 'metres = 925'))
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Drawn.osm.xz', ele='100')
    run = run_cli(zone, tmp_path / 'work', '--arcsec', '3', '--params', str(other),
                  '--shell', str(tmp_path / 'surface.sh'))
    assert 'fill bounded to 925 m = 10 cells' in run.stdout, run.stdout + run.stderr


# ------------------------------------------------------------ the guards

def test_a_square_that_converts_to_nothing_stops_the_build(tmp_path, monkeypatch):
    """The OSM driver hands back an empty layer rather than an error when its
    temporary file cannot be written. That cost liberian 81% of its constraint
    lines across every build, and nothing in the run said so."""
    from danu.core.square import SquareName
    from danu.surface import build
    zone = tmp_path / 'zone'
    zone.mkdir()
    write_square(zone / 'S24E125_Drawn.osm.xz', ele='100')
    work = tmp_path / 'work'
    work.mkdir()
    monkeypatch.setattr(build.gdal, 'VectorTranslate', lambda *a, **k: None)
    with pytest.raises(ValueError, match='converted to none'):
        build.collect({SquareName(125, -24): zone / 'S24E125_Drawn.osm.xz'}, work)


def test_extra_isofill_flags_take_the_binary_rather_than_the_library(tmp_path):
    """The escape hatch for trying a change on one zone before it is the
    default. The library has no flags to give them to, so asking for both is
    refused rather than quietly dropping the flags."""
    from danu.surface import build, params
    with pytest.raises(ValueError, match='need the binary'):
        build.interpolate(tmp_path / 'cont.tif', tmp_path / 'mask.tif', None,
                          params.load(), tmp_path, library=True, extra=['--no-pass2'])


# -------------------------------------------------------------- water areas

def test_a_curated_water_file_becomes_a_mask_of_its_areas(tmp_path):
    """natural=water states that its interior is water, which a closed
    coastline ring does not - it is equally able to describe an island. The
    branch has no zone using it, so this is what says it still works."""
    from danu.surface import build
    osm = tmp_path / 'zone-water.osm'
    nodes = ''.join(f'<node id="-{i + 1}" lat="{lat}" lon="{lon}"/>' for i, (lat, lon) in
                    enumerate([(-23.8, 125.2), (-23.8, 125.8), (-23.2, 125.8), (-23.2, 125.2)]))
    refs = ''.join(f'<nd ref="-{i}"/>' for i in (1, 2, 3, 4, 1))
    osm.write_text(f'<?xml version="1.0"?>\n<osm version="0.6" generator="test">{nodes}'
                   f'<way id="-1">{refs}<tag k="natural" v="water"/></way></osm>')
    grid = build.Grid(west=125, east=126, south=-24, north=-23, arcsec=30)
    lines = []
    mask_path = build.water_areas(osm, grid, tmp_path, log=lines.append)
    ds = gdal.Open(str(mask_path))                 # held: the band outlives it otherwise
    mask = ds.GetRasterBand(1).ReadAsArray()
    assert mask.shape == (grid.size[1], grid.size[0])
    assert mask.max() == 1, f'nothing was burnt: {lines}'
    assert mask.min() == 0, 'the whole grid was burnt, not the area'
    assert any('1 water areas' in l for l in lines), lines
