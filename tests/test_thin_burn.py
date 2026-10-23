"""A contour burned thin still stops the fill's sight test (#253).

Burned as the cells it runs through, a diagonal line is a staircase whose
cells touch only at their corners - the gaps rasterise() burned all touched to
close. Three such lines at 0, 100 and 200 m, the 200 close behind the 100: a
cell between the first two that saw the third through the middle one's gaps
would take the steeper 0-200 pair and come off the straight ramp the 0 and
100 lines give. With the build's barrier it keeps to it, as it does with none
at all - and a line with real holes in it does not, which the last test shows
the first two are able to tell.
"""

import shutil
import subprocess

import numpy as np
import pytest

gdal = pytest.importorskip('osgeo.gdal')

from danu.surface import params as P  # noqa: E402

ISOFILL = shutil.which('isofill')


def fill(tmp_path, barrier, holes=False):
    """The strip between the 0 and 100 lines, filled: how many of its cells
    rose past 100, and how far they come off the ramp, worst and mean."""
    n = 90
    y, x = np.mgrid[0:n, 0:n]
    c = np.full((n, n), -9999, np.int16)
    for k, ele in ((15, 0), (35, 100), (38, 200)):
        line = x - y == k
        if holes and ele == 100:
            line &= x % 3 != 0
        c[line] = ele
    cont, out = tmp_path / 'cont.tif', tmp_path / 'dem.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(cont), n, n, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((0, 1, 0, n, 0, -1))
    ds.GetRasterBand(1).SetNoDataValue(-9999)
    ds.GetRasterBand(1).WriteArray(c)
    ds = None
    subprocess.run([ISOFILL, '--radius', '60', '--barrier', str(barrier), '--no-pass2', str(cont), str(out)],
                   check=True, capture_output=True)
    z = gdal.Open(str(out)).ReadAsArray().astype(float)
    # the strip between the 0 and 100 lines, clear of the raster's edges
    strip = (x - y > 15) & (x - y < 35) & (y > 10) & (y < n - 10) & (x < n - 10) & (z > -30000)
    assert strip.sum() > 500
    off = np.abs(z - 100 * (x - y - 15) / 20)[strip]
    return int((z[strip] > 100.5).sum()), float(off.max()), float(off.mean())


@pytest.mark.skipif(ISOFILL is None, reason='no isofill binary on PATH')
@pytest.mark.parametrize('barrier', [0, P.load().barrier_cells])
def test_a_thin_diagonal_contour_is_a_wall_to_the_sight_test(tmp_path, barrier):
    above, worst, mean = fill(tmp_path, barrier)
    assert above == 0, f'{above} cells between 0 and 100 rose past the 100 line'
    assert mean < 1.0 and worst < 5.0, f'off the ramp by {worst:.2f} m, mean {mean:.3f}'


@pytest.mark.skipif(ISOFILL is None, reason='no isofill binary on PATH')
def test_a_line_with_holes_is_not(tmp_path):
    """The same, the 100 line with every third cell gone: the test above
    sees the difference, so its passing means something."""
    above, worst, mean = fill(tmp_path, 0, holes=True)
    assert worst > 5.0 or above > 0, f'holes made no difference: {worst:.2f} m worst, {above} above 100'
