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
# So the mask is the convex hull of the contours in each degree square, clipped
# to that square. Per square rather than per zone, so a zone described in
# different corners does not get one hull spanning the lot.
#
# A hull rather than a buffer around the contours. Both exclude the undescribed
# ground, but a buffer has to be wide enough to close the gaps *inside* a
# described region - zone-makaska's reach 2.9 km - and anything that wide also
# reaches far outside it. A hull contains its own holes by construction and has
# nothing to tune.
#
# Read from the rasterised constraints rather than the contour geometry. The
# mask is rasterised onto this same grid, so a hull taken at cell resolution is
# the same answer, and it costs one pass over a raster already built instead of
# cloning a few hundred thousand ways into the squares they touch. Only the
# extreme cells can be hull vertices, so each square is reduced to the first and
# last set cell of every row and column before the hull is taken - a few
# thousand points rather than millions.
#
import sys
import numpy as np
from osgeo import gdal

gdal.UseExceptions()


def hull(points):
    """Convex hull of an (N,2) integer array, monotone chain. Returns the
    vertices anticlockwise, without the closing repeat."""
    p = np.unique(points, axis=0)          # sorts by x then y as a side effect
    if len(p) < 3:
        return p
    cross = lambda o, a, b: ((a[0]-o[0]) * (b[1]-o[1]) -
                             (a[1]-o[1]) * (b[0]-o[0]))
    lower = []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in p[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def extremes(mask):
    """The cells that could be hull vertices: first and last set cell of every
    row and of every column. A hull vertex is extreme along some axis, so this
    is a superset, and it is small."""
    pts = []
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size:
        first = mask[rows].argmax(axis=1)
        last = mask.shape[1] - 1 - mask[rows][:, ::-1].argmax(axis=1)
        pts.append(np.stack([first, rows], axis=1))
        pts.append(np.stack([last, rows], axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if cols.size:
        m = mask[:, cols]
        top = m.argmax(axis=0)
        bot = mask.shape[0] - 1 - m[::-1].argmax(axis=0)
        pts.append(np.stack([cols, top], axis=1))
        pts.append(np.stack([cols, bot], axis=1))
    return np.concatenate(pts) if pts else np.empty((0, 2), int)


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
            v = hull(extremes(m))
            if len(v) < 3:
                continue
            # cell centres to lon/lat, then clipped to the square by the
            # rasterise that follows - the hull cannot leave its own square
            coords = [(gt[0] + (x0 + px + 0.5) * gt[1],
                       gt[3] + (y0 + py + 0.5) * gt[5]) for px, py in v]
            coords.append(coords[0])
            feats.append('{"type":"Feature","properties":{},"geometry":'
                         '{"type":"Polygon","coordinates":[[%s]]}}'
                         % ','.join('[%.9f,%.9f]' % c for c in coords))

    if not feats:
        sys.exit('demDrawnMask.py: no constraints in %s' % src_path)
    with open(out_path, 'w') as f:
        f.write('{"type":"FeatureCollection","features":[%s]}' % ','.join(feats))
    print(f'  drawn area: {len(feats)} square hulls', file=sys.stderr)


if __name__ == '__main__':
    main()
