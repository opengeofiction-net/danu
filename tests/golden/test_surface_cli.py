"""``python -m danu.surface.build``: what danu-build-zone gets back from it.

The shell hands the whole surface to this command and carries on from the DEM,
so what it says - the grid for the .hgt slicing, whether there was anything to
build at all - is an interface, not a log line.
"""

import lzma
import pathlib
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
    import shutil
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    if shutil.which('isofill') is None:
        pytest.skip('isofill not on PATH')
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
