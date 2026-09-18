"""danu.ui.mercator agrees with PROJ about where things are.

The server warps the DEM to Mercator with gdalwarp - a spherical Mercator on
R = 6378137, which is EPSG:3857 - for the hillshades the tile styles expect.
The editor projects contours to the same Mercator for the canvas, in its own
arithmetic. Two implementations of one projection is a place where the editor
and the build could disagree about where a contour is, so this asserts they do
not: the canvas's forward projection matches PROJ's to under a millionth of a
pixel at zoom 19, on points across the whole world.

Needs GDAL, so it runs in the golden job, which has it.
"""

import pytest

import math
import re
from pathlib import Path

osr = pytest.importorskip('osgeo.osr')
gdal = pytest.importorskip('osgeo.gdal')
# GDAL 4 will raise by default; asking for it now keeps the warning out of the run
gdal.UseExceptions()

from danu.ui import mercator as m   # noqa: E402

BUILD_ZONE = Path(__file__).parents[1] / 'server' / 'bin' / 'danu-build-zone'


def server_merc() -> str:
    """The proj string danu-build-zone passes to gdalwarp, read from the script
    rather than copied into this file. A copy would let the build change its
    projection while this test went on agreeing with the old one - which is
    the one way this guard could stop guarding without anyone noticing."""
    text = BUILD_ZONE.read_text()
    found = re.findall(r'^MERC="([^"]+)"', text, re.M)
    assert len(found) == 1, f'expected one MERC= line in danu-build-zone, found {found}'
    assert '-t_srs "${MERC}"' in text, 'danu-build-zone no longer warps with ${MERC}'
    return found[0]


SERVER_MERC = server_merc()
R = 6378137.0
HALF = math.pi * R                   # the Mercator extent in metres

POINTS = [(0, 0), (87.018, 20.482), (125.5, -23.5), (-179.999, 0), (179.999, 0),
          (0, 84.9), (0, -84.9), (-45.123, 67.89), (170.0, -60.0), (-120.0, 45.0)]


@pytest.fixture(scope='module')
def to_merc():
    src = osr.SpatialReference(); src.ImportFromEPSG(4326)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst = osr.SpatialReference(); dst.ImportFromProj4(SERVER_MERC)
    return osr.CoordinateTransformation(src, dst)


@pytest.mark.parametrize('lon,lat', POINTS)
def test_the_canvas_projection_is_the_servers_projection(to_merc, lon, lat):
    mx, my, _ = to_merc.TransformPoint(lon, lat)
    # metres to scene pixels: the scene spans -HALF..HALF across WORLD pixels,
    # y downward
    px = (mx + HALF) / (2 * HALF) * m.WORLD
    py = (HALF - my) / (2 * HALF) * m.WORLD
    x, y = m.lonlat_to_scene(lon, lat)
    assert abs(x - px) < 1e-6 and abs(y - py) < 1e-6, f'{(x, y)} vs PROJ {(px, py)}'


def test_the_string_read_from_the_build_is_the_one_expected():
    # if this changes, the test above still holds the canvas to whatever the
    # build now does; this one makes the change itself visible
    assert SERVER_MERC == '+proj=merc +ellps=sphere +R=6378137 +a=6378137 +units=m'


def test_the_servers_mercator_is_spherical_on_the_web_radius(to_merc):
    # the two facts the agreement rests on, checked rather than assumed
    mx, _, _ = to_merc.TransformPoint(180.0, 0.0)
    assert abs(mx - HALF) < 1e-3
    _, my, _ = to_merc.TransformPoint(0.0, m.MAX_LAT)
    assert abs(my - HALF) < 1e-3
