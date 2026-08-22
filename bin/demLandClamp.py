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

    # Number the regions and rasterise the numbers, so every per-region figure
    # below is one pass of bincount rather than a loop over six thousand polygons
    n = 0
    envelopes = {}
    for feat in layer:
        n += 1
        feat.SetField('v', n)
        layer.SetFeature(feat)
        envelopes[n] = feat.GetGeometryRef().GetEnvelope()

    label_ds = mem.Create('l', cols, rows, 1, gdal.GDT_Int32)
    label_ds.SetGeoTransform(gt)
    label_ds.SetProjection(proj)
    label_ds.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(label_ds, [1], layer, options=['ATTRIBUTE=v'])
    labels = label_ds.GetRasterBand(1).ReadAsArray()


    is_sea = np.zeros(n + 1, dtype=bool)
    for i, (x0, x1, y0, y1) in envelopes.items():
        is_sea[i] = (x0 <= west + tol or x1 >= east - tol
                     or y0 <= south + tol or y1 >= north - tol)
    sea = is_sea[labels]
    kept, total = int(is_sea[1:].sum()), n

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
    # Enclosed cells the fill never reached have no information at all and become
    # 1 m, which is what they are: land of unknown low elevation.
    out = np.where(sea, 0, np.maximum(np.where(dem == NODATA, 1, dem), 1))
    out = out.astype('int16')
    # anything the squares burned is authoritative and is put back untouched,
    # so a contour or coastline drawn at zero stays at zero
    burned = cont != NODATA
    out[burned] = cont[burned].astype('int16')

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
