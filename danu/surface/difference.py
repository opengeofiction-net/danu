"""The working surface against the published DEM - H3c, "what have I actually
changed?".

The published DEM is the server's last build of the zone, `dem-<zone>.tif`
on `data.opengeofiction.net`. It is warped onto the grid the layer draws -
the Mercator grid of the exact build, bilinear, as the build's own DEM was -
and subtracted: higher than published is red, lower blue, a diverging ramp
symmetric about nothing changed. Under half a metre is clear, so what shows
is what moved and the map shows through the rest.

Of an exact build only, the spec's rule for a difference: worked out as one
lands, and a preview's patches leave it as it was.

No Qt, and no network: the build's package fetches nothing, which a test
holds it to. `danu.core.published` brings the published DEM in.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import strips
from .ramp import Ramp
from .shade import MERC, Shaded

UNCHANGED_M = 0.5                # a difference under this is clear: rounding, not an edit
SPAN_MIN_M = 5.0                 # the ramp's least half-width, so a few metres are not saturated
SPAN_PERCENTILE = 98             # the half-width: this percentile of what changed
NICE = (1, 1.5, 2, 3, 4, 5, 6, 8, 10)   # what the half-width is rounded up to, a decade at a time

# blue lower, white nothing, red higher - over -1..1, rescaled to the span
DIFF_RAMP = Ramp('difference', (-1.0, -0.5, 0.0, 0.5, 1.0),
                 ((33, 102, 172, 255), (146, 197, 222, 255), (247, 247, 247, 255),
                  (244, 165, 130, 255), (178, 24, 43, 255)))


def published_on(path: Path, shaded: Shaded) -> np.ndarray:
    """The published DEM on the layer's grid, float32, NaN where it has no
    value - outside its extent, or its nodata."""
    from osgeo import gdal
    gdal.UseExceptions()
    gt = shaded.geotransform
    rows, cols = shaded.dem.shape
    src = gdal.Open(str(path))
    nodata = src.GetRasterBand(1).GetNoDataValue()
    out = gdal.Warp('', src, options=gdal.WarpOptions(
        format='MEM', dstSRS=MERC, resampleAlg='bilinear', width=cols, height=rows,
        outputBounds=(gt[0], gt[3] + rows * gt[5], gt[0] + cols * gt[1], gt[3]),
        srcNodata=nodata, dstNodata=np.nan, outputType=gdal.GDT_Float32))
    return out.GetRasterBand(1).ReadAsArray().astype(np.float32)


def difference(dem: np.ndarray, published: np.ndarray) -> np.ndarray:
    """The working surface less the published one, NaN where either has no
    value; sea in both is no difference."""
    with np.errstate(invalid='ignore'):
        d = dem.astype(np.float32) - published
    d[(dem <= 0) & (published <= 0)] = 0.0
    return d


def span(diff: np.ndarray) -> float:
    """The ramp's half-width: the 98th percentile of the differences that
    are changes, rounded up to a figure that reads - so one bulldozed hill
    does not wash every other edit out to white - and never under 5 m."""
    a = np.abs(diff[~np.isnan(diff)])
    a = a[a >= UNCHANGED_M]
    if not a.size:
        return SPAN_MIN_M
    # to a tenth first: a warp leaves 10.02 where 10 was raised, and 20 is
    # not the figure that reads for it
    s = round(float(np.percentile(a, SPAN_PERCENTILE)), 1)
    if s <= SPAN_MIN_M:
        return SPAN_MIN_M
    step = 10 ** math.floor(math.log10(s))
    return next(k * step for k in NICE if k * step >= s)


def rgba(diff: np.ndarray | None, half: float, shape: tuple) -> np.ndarray:
    """RGBA uint8 for the layer: the diverging ramp over -half..+half, clear
    where nothing changed or nothing is known. No difference yet - the
    published DEM not in - is clear everywhere."""
    rows, cols = shape
    out = np.zeros((rows, cols, 4), np.uint8)
    if diff is None:
        return out
    ramp = DIFF_RAMP.rescaled(-half, half)
    for y, h in strips(rows, cols, itemsize=48, bands=1):
        d = diff[y:y + h]
        c = ramp.rgba(np.nan_to_num(d))
        c[..., 3] = np.where(np.isnan(d) | (np.abs(d) < UNCHANGED_M), 0, 255).astype(np.uint8)
        out[y:y + h] = c
    return out

