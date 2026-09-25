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


def warp_mercator(src: Path, metres: float, out: Path, resample: str = 'bilinear') -> Path:
    """The raster in spherical Mercator at a cell size in metres, bilinear -
    or nearest, for a raster of classes, which must not be averaged.
    shell: gdalwarp -q -overwrite -t_srs "${MERC}" -r bilinear -tr ${m} ${m} -co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER src out"""
    gdal = _gdal()
    gdal.Warp(str(out), str(src), options=gdal.WarpOptions(
        dstSRS=MERC, resampleAlg=resample, xRes=metres, yRes=metres,
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
    classes: np.ndarray | None = None   # first-pass classes on the same grid, or None
    reading: dict | None = None         # first_pass_reading(), measured on the lat/lon grid

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


def shade_dem(dem: Path, params: Params, work: Path, zfactor: float = 2.0,
              classes: Path | None = None) -> Shaded:
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
    cls, reading = None, None
    if classes is not None:
        import json
        j = Path(classes).with_suffix('.json')
        if j.exists():
            reading = json.loads(j.read_text(encoding='utf-8'))
        # the same grid, forced: the classes are warped onto the hillshade's
        # extent and size rather than to a size of their own, so a cell of the
        # overlay is a cell of the surface
        gt = h_ds.GetGeoTransform()
        c_out = work / 'merc-first-pass.tif'
        gdal.Warp(str(c_out), str(classes), options=gdal.WarpOptions(
            dstSRS=MERC, resampleAlg='near', width=h_ds.RasterXSize, height=h_ds.RasterYSize,
            outputBounds=(gt[0], gt[3] + h_ds.RasterYSize * gt[5], gt[0] + h_ds.RasterXSize * gt[1], gt[3]),
            # 255 is OUTSIDE in the source and nodata in the destination, and
            # the two must be the same thing: told only the destination, GDAL
            # rewrites a valid source 255 to 254 to keep it clear of nodata,
            # and the outside of the drawn area would count as inside it
            srcNodata=255, dstNodata=255, creationOptions=CREATE))
        c_ds = gdal.Open(str(c_out))     # held, for the same reason as every dataset here
        cls = c_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8)
    return Shaded(dem=d_ds.GetRasterBand(1).ReadAsArray().astype(np.float32),
                  shade=h_ds.GetRasterBand(1).ReadAsArray().astype(np.uint8),
                  geotransform=tuple(h_ds.GetGeoTransform()), metres=metres, classes=cls, reading=reading)


def _snapped(gdal, src, align_to: tuple) -> dict:
    """Output bounds and size that put a warp on ``align_to``'s own grid.

    GDAL is asked where this window lands in Mercator, and the answer is grown
    outward to whole cells of the target. The warp is then told exactly that,
    rather than a resolution and a free hand."""
    vrt = gdal.AutoCreateWarpedVRT(src, None, MERC)
    gt = vrt.GetGeoTransform()
    west, north = gt[0], gt[3]
    east, south = west + vrt.RasterXSize * gt[1], north + vrt.RasterYSize * gt[5]
    x0, res, y0 = align_to[0], align_to[1], align_to[3]
    c0 = math.floor((west - x0) / res)
    c1 = math.ceil((east - x0) / res)
    r0 = math.floor((north - y0) / align_to[5])
    r1 = math.ceil((south - y0) / align_to[5])
    return dict(outputBounds=(x0 + c0 * res, y0 + r1 * align_to[5],
                              x0 + c1 * res, y0 + r0 * align_to[5]),
                width=c1 - c0, height=r1 - r0)


def shade_window(dem: np.ndarray, geotransform: tuple, projection: str,
                 params: Params, zfactor: float = 2.0, align_to: tuple | None = None) -> tuple:
    """``shade_dem``'s stages for one window of a DEM held as an array, in
    memory: the box filter, the Mercator warp, the hillshade, and the second
    warp of the unsmoothed DEM the relief colours.

    Returns (merc_dem, hillshade, geotransform, metres) on the Mercator grid,
    which is what ``Shaded`` holds.

    ``align_to`` is the geotransform of the Mercator raster the result will be
    spliced into - the one the last whole build produced. Given it, the warp is
    put on exactly that grid, so the patch lands on whole cells of the array it
    replaces and the two can be compared cell for cell. Without it GDAL snaps
    the output to the window's own extent, which lands up to half a cell off
    the display's grid: enough to put the interior three grey levels out
    against the whole raster's shading, which is invisible on screen and wrong
    in a test that is meant to be exact.

    The caller passes a window grown by a halo and crops what comes back. Every
    stage here reads its neighbours - the box filter over ``smooth_cells``, the
    hillshade over its three by three, the warp over whatever bilinear touches -
    so the outermost cells of the window are computed against an edge that is
    not really there. Inside the halo they are computed against real ground and
    are the whole raster's own answer.

    The box filter is numpy here and a VRT ``KernelFilteredSource`` in
    ``shade_dem``, because a VRT wants a file and this is meant to run between
    two keystrokes. Same kernel, same normalisation; they differ only in how
    they treat the raster's own edge, which is what the halo covers.

    14.4 ms for a 215 by 215 window and 19.8 for 411 by 411, against 2804 ms
    for the whole of the gobras 3x3 at 3 arcseconds.
    """
    gdal = _gdal()
    rows, cols = dem.shape
    a = dem.astype(np.float32)

    def raster(values):
        ds = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform(geotransform)
        ds.SetProjection(projection)
        ds.GetRasterBand(1).WriteArray(values)
        return ds

    n = params.smooth_cells
    pad = n // 2
    padded = np.pad(a, pad, mode='edge')
    acc = np.zeros_like(a)
    for dy in range(n):
        for dx in range(n):
            acc += padded[dy:dy + rows, dx:dx + cols]
    smoothed = acc / np.float32(n * n)

    metres = fine_metres(params)
    warp = dict(format='MEM', dstSRS=MERC, resampleAlg='bilinear', xRes=metres, yRes=metres)
    if align_to is not None:
        # the size and extent replace the resolution rather than joining it:
        # gdalwarp's own -tr and -outsize are mutually exclusive, and asking
        # for both leaves it unclear which the binding acts on - and so
        # whether the alignment happened at all
        warp.pop('xRes'), warp.pop('yRes')
        warp.update(_snapped(gdal, raster(a), align_to))
    merc_fine = gdal.Warp('', raster(smoothed), options=gdal.WarpOptions(**warp))
    hs = gdal.DEMProcessing('', merc_fine, 'hillshade', options=gdal.DEMProcessingOptions(
        format='MEM', zFactor=zfactor, computeEdges=True))
    # the relief colours the unsmoothed DEM on the same grid, as shade_dem
    # does: the smoothing is for the derivative, and a coloured plateau should
    # not bleed. Forced onto the hillshade's own grid rather than warped to a
    # size of its own, so the two arrays pair cell for cell
    gt = hs.GetGeoTransform()
    merc_dem = gdal.Warp('', raster(a), options=gdal.WarpOptions(
        format='MEM', dstSRS=MERC, resampleAlg='bilinear',
        width=hs.RasterXSize, height=hs.RasterYSize,
        outputBounds=(gt[0], gt[3] + hs.RasterYSize * gt[5],
                      gt[0] + hs.RasterXSize * gt[1], gt[3])))
    return (merc_dem.GetRasterBand(1).ReadAsArray().astype(np.float32),
            hs.GetRasterBand(1).ReadAsArray().astype(np.uint8),
            tuple(gt), metres)


# ------------------------------------------------------------------ display

@dataclass(frozen=True)
class Scaling:
    """R11: how a ramp is laid over the elevations. ``auto`` stretches the
    ramp over the land in view; ``manual`` over lo..hi; ``pinch`` over a
    window of ``width`` metres about ``centre``, so local relief reads on
    ground that is otherwise all one colour. The hypsometric ramp ignores all
    of this: its colours mean metres."""
    mode: str = 'auto'          # 'auto' | 'manual' | 'pinch'
    lo: float = 0.0
    hi: float = 1000.0
    centre: float = 100.0
    width: float = 50.0

    def range_for(self, dem: np.ndarray) -> tuple[float, float]:
        if self.mode == 'manual':
            return (self.lo, self.hi) if self.hi > self.lo else (self.lo, self.lo + 1.0)
        if self.mode == 'pinch':
            return self.centre - self.width / 2.0, self.centre + self.width / 2.0
        land = dem[dem > 0]
        if land.size == 0:
            return 0.0, 1.0
        lo, hi = float(land.min()), float(land.max())
        return (lo, hi) if hi > lo else (lo, lo + 1.0)


def ramp_rgba(ramp: Ramp, values: np.ndarray, scaling: Scaling, dem: np.ndarray) -> np.ndarray:
    """Colours for elevations through a scaling, exactly as compose() lays
    them on the DEM: the ramp stretched over ``scaling.range_for(dem)``, the
    one place the range is decided. The legend draws itself with this so it
    cannot show one thing and the map another; it hands over the DEM, not a
    range it worked out itself."""
    lo, hi = scaling.range_for(dem)
    return ramp.rescaled(lo, hi).rgba(np.asarray(values, dtype=float))


def compose(shaded: Shaded, ramp: Ramp | None, scaling: Scaling, mode: str = 'shaded relief',
            shade_strength: float = 1.0, stretch: tuple | None = None) -> np.ndarray:
    """RGBA uint8 for the layer. ``mode`` is 'hillshade' (grey only),
    'relief' (colour only) or 'shaded relief' (colour lit by the hillshade).
    A ramp named 'relief.ramp' is the tiles' hypsometric one and is applied in
    absolute metres, alpha and all, so sea stays transparent; any other ramp
    is stretched over ``scaling``'s range and is opaque where there is land.

    ``stretch`` overrides the range ``scaling`` would work out. It exists for
    composing one rectangle of a surface: in ``auto`` the range comes from the
    land in the whole array, so a rectangle asked to work it out for itself
    gets a different one and comes out a different colour from the ground it
    sits in. The caller passes the whole surface's range instead."""
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
        lo, hi = stretch if stretch is not None else scaling.range_for(shaded.dem)
        rgba = ramp.rescaled(lo, hi).rgba(shaded.dem)
        rgba[..., 3] = np.where(shaded.dem > 0, 255, 0).astype(np.uint8)
    colour = rgba[..., :3].astype(np.float32)
    if mode == 'shaded relief':
        colour = colour * lit[..., None]
    out[..., :3] = np.clip(np.rint(colour), 0, 255).astype(np.uint8)
    out[..., 3] = rgba[..., 3]
    return out


# the overlay's colours for first_pass_classes()'s codes: what the contours
# do not describe, in three shades of warning, everything else see-through
UNREACHED_RGBA = {1: (200, 30, 30, 150), 2: (230, 120, 20, 140), 3: (235, 200, 40, 130)}


def unreached_rgba(classes: np.ndarray, one_level: bool = False) -> np.ndarray:
    """RGBA for the first-pass overlay. Nothing-in-reach and too-flat are
    always drawn; one-level-only is drawn only when asked, because on real
    ground it is mostly the cells inside the barrier beside every contour,
    which see that contour and nothing else - expected, not undescribed. On
    gobras it outnumbered the unreached ground two to one and buried it."""
    out = np.zeros(classes.shape + (4,), np.uint8)
    for code, rgba in UNREACHED_RGBA.items():
        if code == 3 and not one_level:
            continue
        out[classes == code] = rgba
    return out
