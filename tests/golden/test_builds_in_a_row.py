"""Two builds of the golden square in a row, through the editor's queue, the
first's grids still open in its preview as they are in the editor (#197,
#198). On Windows a file something has open cannot be removed or replaced,
and every rebuild after the first failed on `water-mask.tif`; Linux allows
both, so this is a test windows-stack answers. The Windows runner is an
administrator, so the symlink half of it (#196) is test_save's."""

import lzma
import shutil
from pathlib import Path

import pytest

pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytest.importorskip('PySide6')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')

from danu.core.square import SquareName, WorkingSet  # noqa: E402
from danu.surface import params as surface_params  # noqa: E402
from danu.ui.surface import SurfaceBuilder  # noqa: E402

GOLDEN = Path(__file__).parent / 'S24E125_Los_Pizarrales.osm.xz'
# a small island, anticlockwise - land on the left - so the build makes the
# water mask, whose removal is what Windows refused; the golden square has
# no coastline of its own
ISLAND = [(125.90, -23.90), (125.92, -23.90), (125.92, -23.88), (125.90, -23.88)]


def with_a_coastline(dst: Path) -> None:
    text = lzma.decompress(GOLDEN.read_bytes()).decode('utf-8')
    nodes = ''.join(f'  <node id="{-900001 - i}" version="1" lat="{lat}" lon="{lon}"/>\n'
                    for i, (lon, lat) in enumerate(ISLAND))
    refs = ''.join(f'    <nd ref="{-900001 - i}"/>\n' for i in [*range(len(ISLAND)), 0])
    way = (f'  <way id="-900001" version="1">\n{refs}'
           '    <tag k="natural" v="coastline"/>\n    <tag k="ele" v="0"/>\n  </way>\n')
    text = text.replace('</osm>', nodes + way + '</osm>')
    dst.write_bytes(lzma.compress(text.encode('utf-8')))


def test_a_rebuild_while_the_last_builds_grids_are_open(tmp_path, qapp):
    zone = tmp_path / 'zone'
    zone.mkdir()
    with_a_coastline(zone / GOLDEN.name)
    ws = WorkingSet.open(zone, SquareName(125, -24), 1)
    builder = SurfaceBuilder(runner=lambda job: job.run())
    built, failed = [], []
    builder.finished.connect(lambda b, stale, secs: built.append(b))
    builder.failed.connect(failed.append)
    p = surface_params.load().with_arcsec(3.0)
    try:
        builder.request(ws, p)
        assert not failed, failed[0]
        assert built and built[0].rasters is not None, 'the first build left nothing open'
        assert built[0].rasters.water is not None, 'no water mask, the file at issue'
        builder.request(ws, p)          # the first's rasters still held, as the preview holds them
        assert not failed, failed[0]
        assert len(built) == 2
    finally:
        built.clear()
        builder.cleanup()
