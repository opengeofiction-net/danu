#!/usr/bin/env python3
#
# A water mask from the coastline's own direction - see Admin:Elevation process
#
#   demSeaMask.py <contours.gpkg> <reference.tif> <out.tif>
#
# Produces exactly what water/<zone>.osm produces by hand for zone-roantra: a
# Byte raster, 1 where there is water, for demLandClamp.py to force to zero.
# The difference is where it comes from. A coastline is directed - land on the
# left, water on the right - so the squares already say which side is which, and
# no separate file is needed.
#
# The rule holds in the data: across zone-axian 199 of 199 closed coastline
# rings wind counter-clockwise, and the one which did not turned out to be drawn
# backwards.
#
# Sides rather than rings, because a square's coastline is usually open ways
# running edge to edge rather than closed rings, and open ways enclose nothing.
# Every segment still has a left and a right:
#
#   * seed a cell a little to the left of every segment as land, and one a
#     little to the right as water
#   * every other cell takes the side of whichever seed is nearest
#
# Which side of the nearest coastline you are on, in other words - a side field
# rather than a flood fill. Connectivity was tried first and does not work here:
# a square's coastline ends where the next square has not been drawn, so you can
# walk around the end of it from sea to land. On zone-alved that left the whole
# 2 degree box as seven regions with land and water seeds in the same ones.
#
# Bounded by MAX_CELLS from the coastline, because far from any coast the
# nearest-seed answer means nothing and this must never zero real terrain. The
# plumes it exists to remove all sit within the fill radius of land, so a couple
# of times that is reach enough.

import os
import sys

import multiprocessing
import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

# how far to step off the line to sample a side, in cells. Far enough to clear
# an all-touched barrier, which can be two cells thick where a line runs
# diagonally, and near enough not to step over something narrow
SIDE_STEP = 2.5
# how far the mask may reach from a coastline, in cells - twice the fill radius
MAX_CELLS = 120


def ogr_memory_driver():
    """The OGR in-memory driver, by whichever name this GDAL calls it."""
    for name in ('MEM', 'Memory'):
        drv = ogr.GetDriverByName(name)
        if drv is not None:
            return drv
    raise RuntimeError('no OGR in-memory driver')


def strips(rows, cols, itemsize=4, budget=256 << 20):
    """Row bands small enough to hold, as demLandClamp.py does."""
    per_row = max(1, cols * itemsize)
    height = max(1, min(rows, budget // per_row))
    for y in range(0, rows, height):
        yield y, min(height, rows - y)


def seed_points(layer, gt):
    """Points just off each side of every coastline segment.

    Returns (water, land) as lists of (col, row).

    Work in raster space throughout. Left of travel in map coordinates, where y
    is north, is (-dy, dx). Rows increase southward, so mapping that to (col,
    row) flips the y term and the left normal becomes (drow, -dcol) - not
    (-drow, -dcol), which is the sign error that put both seeds on one side.
    """
    water, land = [], []
    layer.ResetReading()
    for feat in layer:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        parts = ([geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
                 if geom.GetGeometryCount() else [geom])
        for part in parts:
            pts = [part.GetPoint_2D(i) for i in range(part.GetPointCount())]
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                c0, r0 = (x0 - gt[0]) / gt[1], (y0 - gt[3]) / gt[5]
                c1, r1 = (x1 - gt[0]) / gt[1], (y1 - gt[3]) / gt[5]
                dcol, drow = c1 - c0, r1 - r0
                length = np.hypot(dcol, drow)
                if length == 0:
                    continue
                dcol, drow = dcol / length, drow / length
                cx, cy = (c0 + c1) / 2, (r0 + r1) / 2
                for nc, nr, out in ((drow, -dcol, land),      # left  = land
                                    (-drow, dcol, water)):    # right = water
                    out.append((int(cx + nc * SIDE_STEP),
                                int(cy + nr * SIDE_STEP)))
    return water, land


def proximity_worker(seed_path, out_path, cols, rows, gt, proj):
    """One proximity pass, in its own process. Opens the seed raster by path
    rather than taking a band across the fork."""
    src = gdal.Open(seed_path)
    ds = gdal.GetDriverByName('GTiff').Create(
        out_path, cols, rows, 1, gdal.GDT_Float32,
        options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    gdal.ComputeProximity(src.GetRasterBand(1), ds.GetRasterBand(1),
                          ['VALUES=1', 'DISTUNITS=PIXEL'])
    ds.FlushCache()
    ds = src = None


def main():
    if len(sys.argv) != 4:
        sys.exit('usage: demSeaMask.py <contours.gpkg> <reference.tif> <out.tif>')
    src_path, ref_path, out_path = sys.argv[1:4]

    ref = gdal.Open(ref_path)
    gt, proj = ref.GetGeoTransform(), ref.GetProjection()
    cols, rows = ref.RasterXSize, ref.RasterYSize

    src = ogr.Open(src_path)
    layer = src.GetLayer(0)
    layer.SetAttributeFilter("natural = 'coastline'")
    if layer.GetFeatureCount() == 0:
        print('  no coastline in this zone, no water mask', file=sys.stderr)
        sys.exit(2)
    print(f'  {layer.GetFeatureCount()} coastline ways', file=sys.stderr)

    water_pts, land_pts = seed_points(layer, gt)
    print(f'  {len(water_pts)} seeds a side', file=sys.stderr)

    tmp = {}

    def seed_raster(name, points):
        path = f'{out_path}.{name}.tif'
        tmp[name] = path
        ds = gdal.GetDriverByName('GTiff').Create(
            path, cols, rows, 1, gdal.GDT_Byte,
            options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        band = ds.GetRasterBand(1)
        for y, h in strips(rows, cols, itemsize=1):
            band.WriteArray(np.zeros((h, cols), np.uint8), 0, y)
        for cx, cy in points:
            if 0 <= cx < cols and 0 <= cy < rows:
                band.WriteArray(np.ones((1, 1), np.uint8), cx, cy)
        band.FlushCache()
        return ds, band

    w_ds, w_band = seed_raster('water', water_pts)
    l_ds, l_band = seed_raster('land', land_pts)
    # closed before forking: a GDAL dataset handle does not survive one, and
    # the children open the seeds by path
    w_ds = l_ds = w_band = l_band = None

    # The two proximity passes are the bulk of this script - 439 s of a 1,805 s
    # zone build on makaska, the largest single cost outside isofill. They are
    # independent, one from the water seeds and one from the land, so they run
    # side by side rather than one after the other.
    #
    # Processes rather than threads: gdal.ComputeProximity is one call into C
    # and whether the binding releases the GIL for it is not something to bet
    # the stage on. A fork costs a few hundred milliseconds against minutes of
    # work, and each child holds only its own handles.
    for name in ('water', 'land'):
        tmp[name + 'dist'] = f'{out_path}.{name}dist.tif'
    jobs = [multiprocessing.Process(
                target=proximity_worker,
                args=(tmp[n], tmp[n + 'dist'], cols, rows, gt, proj))
            for n in ('water', 'land')]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()
    bad = [j.exitcode for j in jobs if j.exitcode != 0]
    if bad:
        sys.exit(f'demSeaMask: a proximity pass failed, exit {bad}')

    wd_ds = gdal.Open(tmp['waterdist'])
    ld_ds = gdal.Open(tmp['landdist'])
    wd_band, ld_band = wd_ds.GetRasterBand(1), ld_ds.GetRasterBand(1)

    out_ds = gdal.GetDriverByName('GTiff').Create(
        out_path, cols, rows, 1, gdal.GDT_Byte,
        options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)

    n_water = 0
    for y, h in strips(rows, cols):
        dw = wd_band.ReadAsArray(0, y, cols, h)
        dl = ld_band.ReadAsArray(0, y, cols, h)
        m = ((dw < dl) & (dw <= MAX_CELLS)).astype(np.uint8)
        out_band.WriteArray(m, 0, y)
        n_water += int(m.sum())
    out_band.FlushCache()
    out_ds = wd_ds = ld_ds = w_ds = l_ds = None
    for p in tmp.values():
        os.unlink(p)

    print(f'  water mask covers {100 * n_water / (rows * cols):.2f}% of the zone',
          file=sys.stderr)


if __name__ == '__main__':
    main()
