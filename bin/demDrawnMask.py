#!/usr/bin/env python3
#
# The area a zone's contours actually describe - see Admin:Elevation process
#
#   demDrawnMask.py <cont.tif> <out.geojson>
#
# A zone's raster is the bounding box of the degree squares holding contours,
# and a bounding box is not the shape of the data in it: zone-gobras is five
# drawn squares in a four by four box, and even inside those five only 37% of
# the area has contours anywhere near it.
#
# The second pass interpolates every row and column between its known values and
# anchors at zero beyond their ends, so across undescribed ground there is
# nothing to stop a value carrying - the result is streaks the length of
# whatever region it is allowed to cross. Masking to the drawn degree squares
# stops them at a square boundary, which is better than the raster edge and
# still wrong: they simply run to the edge of the square instead.
#
# So the mask is the envelope of the contours in each degree square. Per square
# rather than per zone, so a zone described in different corners does not get one
# box spanning the lot.
#
# An envelope rather than a buffer around the contours. Both exclude the
# undescribed ground, but a buffer has to be wide enough to close the gaps
# *inside* a described region - zone-makaska's reach 2.9 km - and anything that
# wide also reaches far outside it. An envelope contains its own holes by
# construction and has nothing to tune.
#
# An envelope rather than a convex hull, which was tried first. A hull follows
# the contours more closely, and that is the problem: where they stop short of a
# square's corner it cuts the corner off diagonally, and the ground there loses
# its terrain even though the square is described. The envelope is more generous
# and the generosity is in the right direction.
#
# Read from the rasterised constraints rather than the contour geometry. The
# mask is rasterised onto this same grid, so an envelope taken at cell resolution
# is the same answer, and it costs one pass over a raster already built instead
# of reading a few hundred thousand ways.
#
# The box runs along the outer edges of the extreme cells, not through their
# centres. gdal_rasterize burns a cell when its centre falls inside the polygon,
# so a box through centres leaves the outermost ring of contour cells sitting on
# the boundary and loses them: 3,106 of zone-ellarca's, 99.9% of them directly
# against a cell the mask did keep.
#
import sys
import numpy as np
from osgeo import gdal

gdal.UseExceptions()


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: demDrawnMask.py <cont.tif> <out.geojson>')
    src_path, out_path = sys.argv[1], sys.argv[2]

    ds = gdal.Open(src_path)
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    W, H = ds.RasterXSize, ds.RasterYSize

    # the degree squares the raster covers
    lon0 = int(np.floor(gt[0])); lon1 = int(np.ceil(gt[0] + W * gt[1]))
    lat1 = int(np.ceil(gt[3])); lat0 = int(np.floor(gt[3] + H * gt[5]))

    feats = []
    for lat in range(lat0, lat1):
        for lon in range(lon0, lon1):
            x0 = int(round((lon - gt[0]) / gt[1]))
            x1 = int(round((lon + 1 - gt[0]) / gt[1]))
            y0 = int(round((lat + 1 - gt[3]) / gt[5]))
            y1 = int(round((lat - gt[3]) / gt[5]))
            x0, x1 = max(x0, 0), min(x1, W)
            y0, y1 = max(y0, 0), min(y1, H)
            if x1 <= x0 or y1 <= y0:
                continue
            a = band.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
            m = a != nodata
            if not m.any():
                continue
            rows = np.flatnonzero(m.any(axis=1))
            cols = np.flatnonzero(m.any(axis=0))
            # outer edges of the extreme cells, so every contour cell is inside
            west = gt[0] + (x0 + cols[0]) * gt[1]
            east = gt[0] + (x0 + cols[-1] + 1) * gt[1]
            north = gt[3] + (y0 + rows[0]) * gt[5]
            south = gt[3] + (y0 + rows[-1] + 1) * gt[5]
            coords = [(west, south), (east, south), (east, north),
                      (west, north), (west, south)]
            feats.append('{"type":"Feature","properties":{},"geometry":'
                         '{"type":"Polygon","coordinates":[[%s]]}}'
                         % ','.join('[%.9f,%.9f]' % c for c in coords))

    if not feats:
        sys.exit('demDrawnMask.py: no constraints in %s' % src_path)
    with open(out_path, 'w') as f:
        f.write('{"type":"FeatureCollection","features":[%s]}' % ','.join(feats))
    print(f'  drawn area: {len(feats)} square envelopes', file=sys.stderr)


if __name__ == '__main__':
    main()
