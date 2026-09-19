"""From a DEM to what is drawn: the shell's raster stages, as functions.

``danu-build-zone`` publishes hillshades and reliefs from the DEM by smoothing
it, warping the copy to spherical Mercator at a cell size in metres, and running
gdaldem over that. The editor draws the same things on a Mercator canvas, so it
runs the same stages - each with a ``shell:`` line naming the command it stands
for, as ``build.py``'s have - and a golden test holds the editor's hillshade
to the one the shell publishes, cell for cell.

The relief here is not gdaldem's: the shell colours a raster once with the
hypsometric ramp, and the editor colours the same warped array through any
Ramp, scaled three ways (R11), and composes it with the hillshade. That part is
display, and is not held to the shell; the arrays it colours are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .params import Params
from .ramp import Ramp

# GDAL is imported where it is used, in the stages that read and write
# rasters, and not here: Shaded, Scaling and compose() are numpy over arrays
# the layer already holds, and the editor must import without GDAL - "GDAL
# is not needed to look" is a README sentence with a test behind it. It is
# needed to build a surface, and the stages say so when it is missing.


def _gdal():
    from osgeo import gdal
    gdal.UseExceptions()
    return gdal

# what danu-build-zone passes to gdalwarp, verbatim; tests/test_mercator_proj
# reads the shell for it, and the canvas's own projection is held to it
MERC = '+proj=merc +ellps=sphere +R=6378137 +a=6378137 +units=m'
R = 6378137.0
HALF = math.pi * R
CREATE = ['TILED=YES', 'COMPRESS=DEFLATE']
# gdaldem writes 0 for nodata and never for a lit or shadowed cell: full shadow
# comes out as 1. Measured on a 3 km west-facing wall under the default light,
# 199 cells in complete shadow, every one of them 1. So transparent-where-zero
# is exactly gdaldem's own meaning, not a hole in the shading
HILLSHADE_NODATA = 0


def smooth(dem: Path, params: Params, work: Path) -> Path:
    """A box filter over the DEM, for the hillshade only: a hillshade is a
    derivative, and the cell-scale steps the fill leaves would render as
    terracing. Done as the shell does it, through a VRT with a normalised
    kernel, so the array is the shell's array.
    shell: gdal_translate -of VRT dem.tif smooth.vrt; <SimpleSource> -> <KernelFilteredSource> with <Kernel normalized="1"><Size>${SMOOTH_CELLS}</Size>; gdal_translate -ot Float32 smooth.vrt smooth.tif"""
    gdal = _gdal()
    n = params.smooth_cells
    vrt = work / 'smooth.vrt'
    out = work / 'smooth.tif'
    gdal.Translate(str(vrt), str(dem), options=gdal.TranslateOptions(format='VRT'))
    text = vrt.read_text()
    kernel = (f'<Kernel normalized="1"><Size>{n}</Size>'
              f'<Coefs>{" ".join(["1"] * n * n)}</Coefs></Kernel>')
    text = (text.replace('<SimpleSource>', '<KernelFilteredSource>')
                .replace('</SimpleSource>', kernel + '</KernelFilteredSource>'))
    vrt.write_text(text)
    gdal.Translate(str(out), str(vrt), options=gdal.TranslateOptions(
        outputType=gdal.GDT_Float32, creationOptions=CREATE))
    return out


def fine_metres(params: Params) -> int:
    """The Mercator cell for the fine hillshade, from the DEM's resolution.
    shell: FINE=$(python3 -c "print(round(${ARCSEC} * 30.87))")"""
    return round(params.arcsec * 30.87)


def warp_mercator(src: Path, metres: float, out: Path) -> Path:
    """The raster in spherical Mercator at a cell size in metres, bilinear.
    shell: gdalwarp -q -overwrite -t_srs "${MERC}" -r bilinear -tr ${m} ${m} -co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER src out"""
    gdal = _gdal()
    gdal.Warp(str(out), str(src), options=gdal.WarpOptions(
        dstSRS=MERC, resampleAlg='bilinear', xRes=metres, yRes=metres,
        creationOptions=CREATE + ['BIGTIFF=IF_SAFER']))
    return out


def hillshade(src: Path, zfactor: float, out: Path) -> Path:
    """gdaldem's hillshade of a Mercator raster, edges computed.
    shell: gdaldem hillshade -q -z ${zfactor} -compute_edges -co TILED=YES -co COMPRESS=DEFLATE src out"""
    gdal = _gdal()
    gdal.DEMProcessing(str(out), str(src), 'hillshade', options=gdal.DEMProcessingOptions(
        zFactor=zfactor, computeEdges=True, creationOptions=CREATE))
    return out


@dataclass
class Shaded:
    """What the layer draws: the warped DEM and its hillshade as arrays, and
    where they sit on the canvas."""
    dem: np.ndarray            # Float32, Mercator grid
    shade: np.ndarray          # uint8 hillshade, same grid
    geotransform: tuple        # of the Mercator grid, in metres
    metres: float

    @property
    def scene_rect(self) -> tuple[float, float, float, float]:
        """(left, top, right, bottom) in scene units - Web Mercator pixels at
        SCENE_ZOOM - from the Mercator extent in metres.
        shell: none; this is the canvas's, and tests/test_mercator_proj holds
        the canvas to the shell's projection"""
        from ..ui import mercator as m
        gt = self.geotransform
        rows, cols = self.dem.shape
        x0, y1 = gt[0], gt[3]
        x1, y0 = x0 + cols * gt[1], y1 + rows * gt[5]
        to_x = lambda mx: (mx + HALF) / (2 * HALF) * m.WORLD          # noqa: E731
        to_y = lambda my: (HALF - my) / (2 * HALF) * m.WORLD          # noqa: E731
        return to_x(x0), to_y(y1), to_x(x1), to_y(y0)


def shade_dem(dem: Path, params: Params, work: Path, zfactor: float = 2.0) -> Shaded:
    """The shell's fine hillshade of a DEM, and the warped DEM it came from,
    read back as arrays for the canvas.
    shell: warp ${WORK}/smooth.tif ${FINE} merc-fine.tif; shade merc-fine.tif 2 hillshade-z2.tif; and warp dem.tif for the relief"""
    gdal = _gdal()
    work = Path(work)
    metres = fine_metres(params)
    sm = smooth(Path(dem), params, work)
    merc_fine = warp_mercator(sm, metres, work / 'merc-fine.tif')
    hs = hillshade(merc_fine, zfactor, work / f'hillshade-z{zfactor:g}.tif')
    # the relief colours the unsmoothed DEM on the same grid - the smoothing
    # is for the derivative, and a coloured plateau should not bleed
    merc_dem = warp_mercator(Path(dem), metres, work / 'merc-dem.tif')
    d_ds, h_ds = gdal.Open(str(merc_dem)), gdal.Open(str(hs))
    # two warps of two rasters on one grid at one cell size land on one grid;
    # said here rather than assumed, since the arrays are paired cell by cell
    if (d_ds.RasterXSize, d_ds.RasterYSize) != (h_ds.RasterXSize, h_ds.RasterYSize) or \
            any(abs(a - b) > 1e-6 for a, b in zip(d_ds.GetGeoTransform(), h_ds.GetGeoTransform())):
        raise RuntimeError('the warped DEM and its hillshade are not on one grid')
    return Shaded(dem=d_ds.GetRasterBand(1).ReadAsArray().astype(np.float32),
                  shade=h_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8),
                  geotransform=tuple(h_ds.GetGeoTransform()), metres=metres)


# ------------------------------------------------------------------ display

@dataclass(frozen=True)
class Scaling:
    """R11: how a ramp is laid over the elevations. ``auto`` stretches the
    ramp over the land in view; ``manual`` over lo..hi; ``pitch`` over a
    window of ``width`` metres about ``centre``, so local relief reads on
    ground that is otherwise all one colour. The hypsometric ramp ignores all
    of this: its colours mean metres."""
    mode: str = 'auto'          # 'auto' | 'manual' | 'pitch'
    lo: float = 0.0
    hi: float = 1000.0
    centre: float = 100.0
    width: float = 50.0

    def range_for(self, dem: np.ndarray) -> tuple[float, float]:
        if self.mode == 'manual':
            return (self.lo, self.hi) if self.hi > self.lo else (self.lo, self.lo + 1.0)
        if self.mode == 'pitch':
            return self.centre - self.width / 2.0, self.centre + self.width / 2.0
        land = dem[dem > 0]
        if land.size == 0:
            return 0.0, 1.0
        lo, hi = float(land.min()), float(land.max())
        return (lo, hi) if hi > lo else (lo, lo + 1.0)


def compose(shaded: Shaded, ramp: Ramp | None, scaling: Scaling, mode: str = 'shaded relief',
            shade_strength: float = 1.0) -> np.ndarray:
    """RGBA uint8 for the layer. ``mode`` is 'hillshade' (grey only),
    'relief' (colour only) or 'shaded relief' (colour lit by the hillshade).
    A ramp named 'relief.ramp' is the tiles' hypsometric one and is applied in
    absolute metres, alpha and all, so sea stays transparent; any other ramp
    is stretched over ``scaling``'s range and is opaque where there is land."""
    rows, cols = shaded.dem.shape
    out = np.zeros((rows, cols, 4), np.uint8)
    lit = shaded.shade.astype(np.float32) / 255.0
    lit = 1.0 - shade_strength * (1.0 - lit)          # strength 0: unlit, 1: full
    if mode not in ('hillshade', 'relief', 'shaded relief'):
        raise ValueError(f'compose: mode {mode!r}')
    if ramp is None and mode != 'hillshade':
        raise ValueError(f'compose: {mode} needs a ramp')
    if mode == 'hillshade':
        grey = np.clip(np.rint(shaded.shade.astype(np.float32)), 0, 255).astype(np.uint8)
        out[..., 0] = out[..., 1] = out[..., 2] = grey
        out[..., 3] = np.where(shaded.shade == HILLSHADE_NODATA, 0, 255).astype(np.uint8)
        return out
    if ramp.name == 'relief.ramp':
        rgba = ramp.rgba(shaded.dem)
    else:
        lo, hi = scaling.range_for(shaded.dem)
        rgba = ramp.rescaled(lo, hi).rgba(shaded.dem)
        rgba[..., 3] = np.where(shaded.dem > 0, 255, 0).astype(np.uint8)
    colour = rgba[..., :3].astype(np.float32)
    if mode == 'shaded relief':
        colour = colour * lit[..., None]
    out[..., :3] = np.clip(np.rint(colour), 0, 255).astype(np.uint8)
    out[..., 3] = rgba[..., 3]
    return out
