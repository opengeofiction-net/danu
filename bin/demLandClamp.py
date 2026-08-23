#!/usr/bin/env python3
#
# Separate land at sea level from the sea itself - see Admin:Elevation process
#
#   demLandClamp.py <dem.tif> <constraints.tif> <out.tif> [water-mask.tif]
#
# Flat coastal land whose nearest constraint is the coastline interpolates to
# zero, which is indistinguishable from sea: the relief ramp makes zero fully
# transparent, so those areas disappear from the map. Comparing a rebuild of
# zone-roantra against the DEM the old process publishes, 2.86% of the zone is
# land at 1 to 9 m, and 64% of it was coming back as exactly zero - whole
# low lying peninsulas rendering as ocean.
#
# The pipeline has no land/sea mask and does not need a new data source for one.
# The constraint raster records which cells were burned from the squares, so the
# coastline is a barrier: the sea is whatever runs from the edge of the zone
# through unburned zero cells without crossing it. Everything else at zero is
# land, and is clamped to 1 m so it reads as land.
#
# Connectivity settles the ocean but not water enclosed by its own shore - an
# inland sea, 10.8% of zone-roantra by area - which never reaches the edge and
# would be clamped to land, then coloured as ground by a ramp that should leave
# it transparent.
#
# That part cannot be answered from the rasters. Whether a region enclosed by a
# shoreline is a lake or an island is a question about which side of a polygon
# you are on, and adjacency to lines cannot answer it: measured against the
# existing dataset, enclosed regions run 2% to 89% sea depending only on their
# size, with no threshold separating them. So the water areas are supplied as a
# mask, built from natural=water multipolygons, which state outright that their
# interior is water where a closed coastline ring does not.
#
# Without a mask the ocean is still correct and enclosed water is clamped to
# 1 m - wrong but harmless for hillshade, visible in relief.
#
# Everything here is done a strip at a time, through temporary rasters on disk,
# rather than by holding the zone in memory. A zone's raster covers the bounding
# box of its squares, and a zone whose squares come in separated clusters is
# mostly empty box: zone-axian is 22 squares of data in 162 square degrees, or
# 2.1 gigapixels, which as whole arrays wanted about 12 GB on a server with 11.

import os
import sys

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

NODATA = -9999




def ogr_memory_driver():
    """The OGR in-memory driver, by whichever name this GDAL calls it.

    Renamed from Memory to MEM in GDAL 3.11. Trixie, and so the servers, ship
    3.10, where MEM does not exist and GetDriverByName returns None rather than
    raising - so asking for the wrong one fails later and elsewhere, as an
    AttributeError on None.
    """
    for name in ('MEM', 'Memory'):
        drv = ogr.GetDriverByName(name)
        if drv is not None:
            return drv
    raise RuntimeError('no OGR in-memory driver: tried MEM and Memory')


# Rows per strip, chosen so one strip of one band is tens of megabytes whatever
# the width of the zone
STRIP_BYTES = 64 << 20


def strips(rows, cols, itemsize=2, bands=4):
    """Row ranges covering the raster, sized to a bounded amount of memory."""
    per_row = cols * itemsize * bands
    step = max(1, min(rows, STRIP_BYTES // max(per_row, 1)))
    for y in range(0, rows, step):
        yield y, min(step, rows - y)


def open_band(path):
    """Dataset and band together. Taking a band off a temporary gdal.Open() lets
    the dataset be collected and the band dies with it - which surfaces later as
    a TypeError deep inside ReadAsArray, nowhere near the open."""
    ds = gdal.Open(path)
    return ds, ds.GetRasterBand(1)


def temp_raster(path, cols, rows, gt, proj, dtype=gdal.GDT_Byte):
    ds = gdal.GetDriverByName('GTiff').Create(
        path, cols, rows, 1, dtype,
        options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    return ds


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    dem_path, cont_path, out_path = sys.argv[1:4]
    water_path = sys.argv[4] if len(sys.argv) == 5 else None

    dem_ds, dem_band = open_band(dem_path)
    cont_ds, cont_band = open_band(cont_path)
    gt = dem_ds.GetGeoTransform()
    proj = dem_ds.GetProjection()
    cols, rows = dem_ds.RasterXSize, dem_ds.RasterYSize

    work = os.path.dirname(os.path.abspath(out_path))
    cand_path = os.path.join(work, '.candidate.tif')
    sea_path = os.path.join(work, '.sea.tif')
    for p in (cand_path, sea_path):
        if os.path.exists(p):
            os.unlink(p)

    # Candidate sea: cells holding no elevation, and not burned from the squares.
    # That is both zero and nodata - the bounded fill never reaches open water
    # more than its reach from a coastline, so most of the ocean arrives here as
    # nodata rather than zero. Burned cells are left out so the coastline itself
    # forms the barrier the flood cannot cross.
    cand_ds = temp_raster(cand_path, cols, rows, gt, proj)
    cand_band = cand_ds.GetRasterBand(1)
    for y, h in strips(rows, cols):
        d = dem_band.ReadAsArray(0, y, cols, h)
        c = cont_band.ReadAsArray(0, y, cols, h)
        cand_band.WriteArray((((d == 0) | (d == NODATA)) &
                              (c == NODATA)).astype('uint8'), 0, y)
    cand_band.FlushCache()

    # Polygonize to get connected regions - GDAL does the connectivity, reading
    # the mask off disk, so this needs no scipy and no whole-raster array
    drv = ogr_memory_driver()
    ds = drv.CreateDataSource('p')
    layer = ds.CreateLayer('poly', geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
    gdal.Polygonize(cand_band, cand_band, layer, 0)

    west, north = gt[0], gt[3]
    east = west + cols * gt[1]
    south = north + rows * gt[5]
    tol = abs(gt[1]) / 2

    # Only the regions which reach the edge of the zone are wanted, so they go
    # straight into a byte mask on disk
    sea_ds = temp_raster(sea_path, cols, rows, gt, proj)
    sea_layer_ds = drv.CreateDataSource('sl')
    sea_layer = sea_layer_ds.CreateLayer('sea', geom_type=ogr.wkbPolygon)

    kept = total = 0
    for feat in layer:
        total += 1
        x0, x1, y0, y1 = feat.GetGeometryRef().GetEnvelope()
        if (x0 <= west + tol or x1 >= east - tol
                or y0 <= south + tol or y1 >= north - tol):
            out_feat = ogr.Feature(sea_layer.GetLayerDefn())
            out_feat.SetGeometry(feat.GetGeometryRef().Clone())
            sea_layer.CreateFeature(out_feat)
            kept += 1
    if kept:
        gdal.RasterizeLayer(sea_ds, [1], sea_layer, burn_values=[1])
    sea_ds.GetRasterBand(1).FlushCache()
    layer = ds = sea_layer = sea_layer_ds = None
    cand_ds = cand_band = None

    # Anything the water mask covers is water, whether or not it reaches the
    # edge of the zone
    water_ds = water_band = None
    if water_path:
        water_ds, water_band = open_band(water_path)

    sea_ds, sea_band = open_band(sea_path)

    out_ds = gdal.GetDriverByName('GTiff').Create(
        out_path, cols, rows, 1, gdal.GDT_Int16,
        options=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=2',
                 'BIGTIFF=IF_SAFER'])
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)

    added = n_sea = n_low = 0
    for y, h in strips(rows, cols):
        d = dem_band.ReadAsArray(0, y, cols, h)
        c = cont_band.ReadAsArray(0, y, cols, h)
        sea = sea_band.ReadAsArray(0, y, cols, h).astype(bool)
        if water_band is not None:
            wm = water_band.ReadAsArray(0, y, cols, h).astype(bool)
            added += int((wm & ~sea).sum())
            sea |= wm

        # Sea reads exactly zero. Land keeps its elevation but never reads zero,
        # so it cannot be mistaken for sea by a ramp which makes zero
        # transparent. Cells the fill never reached hold no information and
        # become 1 m, which is what they are: land of unknown low elevation.
        np.maximum(d, np.int16(1), out=d)
        d[sea] = 0
        # anything the squares burned is authoritative and goes back untouched,
        # so a contour or a coastline drawn at zero stays at zero
        burned = c != NODATA
        d[burned] = c[burned]

        out_band.WriteArray(d, 0, y)
        n_sea += int((d == 0).sum())
        n_low += int(((d > 0) & (d < 10)).sum())

    out_band.FlushCache()
    out_ds = sea_ds = water_ds = None
    for p in (cand_path, sea_path):
        os.unlink(p)

    cells = rows * cols
    if water_path:
        print(f'  water mask adds {added:,} cells of enclosed water',
              file=sys.stderr)
    print(f'  {kept} of {total} water regions kept as sea; '
          f'sea {100 * n_sea / cells:.2f}% of the zone, '
          f'land at 1..9 m {100 * n_low / cells:.2f}%', file=sys.stderr)


if __name__ == '__main__':
    main()
