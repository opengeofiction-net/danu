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

import sys

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

NODATA = -9999



def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__.strip().splitlines()[2].strip())
    dem_path, cont_path, out_path = sys.argv[1:4]
    water_path = sys.argv[4] if len(sys.argv) == 5 else None

    dem_ds = gdal.Open(dem_path)
    dem = dem_ds.GetRasterBand(1).ReadAsArray()
    # the dataset has to be held: reading through a band from a temporary
    # gdal.Open() lets the dataset be collected and the band goes with it
    cont_ds = gdal.Open(cont_path)
    cont = cont_ds.GetRasterBand(1).ReadAsArray()
    gt = dem_ds.GetGeoTransform()
    proj = dem_ds.GetProjection()
    rows, cols = dem.shape

    # Candidate sea: cells holding no elevation, and not burned from the squares.
    # That is both zero and nodata - the bounded fill never reaches open water
    # more than its reach from a coastline, so most of the ocean arrives here as
    # nodata rather than zero. Burned cells are left out so the coastline itself
    # forms the barrier the flood cannot cross.
    candidate = ((dem == 0) | (dem == NODATA)) & (cont == NODATA)

    mem = gdal.GetDriverByName('MEM')
    mask_ds = mem.Create('m', cols, rows, 1, gdal.GDT_Byte)
    mask_ds.SetGeoTransform(gt)
    mask_ds.SetProjection(proj)
    mask_ds.GetRasterBand(1).WriteArray(candidate.astype('uint8'))

    # Polygonize to get connected regions - GDAL already does the connectivity,
    # so this needs no scipy
    drv = ogr.GetDriverByName('MEM')
    ds = drv.CreateDataSource('p')
    layer = ds.CreateLayer('poly', geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
    gdal.Polygonize(mask_ds.GetRasterBand(1), mask_ds.GetRasterBand(1), layer, 0)

    west, north = gt[0], gt[3]
    east = west + cols * gt[1]
    south = north + rows * gt[5]
    tol = abs(gt[1]) / 2

    # Only the regions which reach the edge of the zone are wanted, so they go
    # straight into a byte mask. Numbering every region and rasterising the
    # numbers instead would cost an Int32 array the size of the zone - 1.7 GB
    # for roantra at 1 arcsecond, on a server with 6 GB
    sea_ds = mem.Create('s', cols, rows, 1, gdal.GDT_Byte)
    sea_ds.SetGeoTransform(gt)
    sea_ds.SetProjection(proj)
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
    sea = sea_ds.GetRasterBand(1).ReadAsArray().astype(bool)
    sea_ds = mask_ds = None

    # Anything the water mask covers is water, whether or not it reaches the
    # edge of the zone
    if water_path:
        wds = gdal.Open(water_path)
        mask = wds.GetRasterBand(1).ReadAsArray().astype(bool)
        added = int((mask & ~sea).sum())
        sea |= mask
        print(f'  water mask adds {added:,} cells of enclosed water',
              file=sys.stderr)

    # Sea reads exactly zero. Land keeps its elevation but never reads zero, so
    # it cannot be mistaken for sea by a ramp which makes zero transparent.
    # Cells the fill never reached hold no information and become 1 m, which is
    # what they are: land of unknown low elevation.
    #
    # Done in place on the Int16 array. np.where against Python integers
    # promotes the result to Int64, which for roantra at 1 arcsecond is a 3.4 GB
    # array by itself
    out = dem
    np.maximum(out, np.int16(1), out=out)
    out[sea] = 0
    del sea
    # anything the squares burned is authoritative and goes back untouched, so a
    # contour or a coastline drawn at zero stays at zero
    burned = cont != NODATA
    out[burned] = cont[burned]
    del burned

    drv_tif = gdal.GetDriverByName('GTiff')
    out_ds = drv_tif.Create(out_path, cols, rows, 1, gdal.GDT_Int16,
                            options=['TILED=YES', 'COMPRESS=DEFLATE',
                                     'PREDICTOR=2'])
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_ds.GetRasterBand(1).WriteArray(out)
    out_ds = None

    low = ((out > 0) & (out < 10)).mean() * 100
    zero = (out == 0).mean() * 100
    print(f'  {kept} of {total} water regions kept as sea; '
          f'sea {zero:.2f}% of the zone, land at 1..9 m {low:.2f}%', file=sys.stderr)


if __name__ == '__main__':
    main()
