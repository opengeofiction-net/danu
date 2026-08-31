#!/usr/bin/env python3
#
# The area a zone's contours actually describe - see Admin:Elevation process
#
#   demDrawnMask.py <contours.gpkg> <out.geojson>
#
# A zone's raster is the bounding box of the degree squares holding contours,
# and a bounding box is not the shape of the data in it: zone-gobras is five
# drawn squares in a four by four box, and even inside those five only 37% of
# the area has contours anywhere near it.
#
# The second pass interpolates every row and column between its known values and
# anchors at zero beyond their ends, so across an undescribed gap there is
# nothing to stop a value carrying - the result is streaks the length of
# whatever region it is allowed to cross. Masking to the drawn degree squares
# stops it at a square boundary, which is better than the raster edge and still
# wrong: the streaks simply run to the edge of the square instead.
#
# So the mask is the convex hull of the contours in each degree square, clipped
# to that square, unioned across the zone. Per square rather than per zone, so a
# zone whose squares are described in different corners does not get one hull
# spanning the lot.
#
# A hull rather than a buffer around the contours. Both would exclude the
# undescribed ground, but a buffer has to be wide enough to close the gaps
# *inside* a described region - zone-makaska's reach as far as 2.9 km - and
# anything that wide also reaches far outside it. A hull contains its own holes
# by construction and has nothing to tune.
#
import sys
from osgeo import ogr, osr

ogr.UseExceptions()


def main():
    if len(sys.argv) != 3:
        sys.exit('usage: demDrawnMask.py <contours.gpkg> <out.geojson>')
    src_path, out_path = sys.argv[1], sys.argv[2]

    src = ogr.Open(src_path)
    if src is None:
        sys.exit(f'demDrawnMask.py: cannot open {src_path}')
    layer = src.GetLayer(0)

    # Which degree squares the contours touch, from the geometry rather than
    # from the filenames: a way is clipped to its square when it is drawn, so
    # its own extent says which square it belongs to
    xmin, xmax, ymin, ymax = layer.GetExtent()
    squares = {}
    for feat in layer:
        g = feat.GetGeometryRef()
        if g is None:
            continue
        gx0, gx1, gy0, gy1 = g.GetEnvelope()
        # a way can straddle a boundary, so it counts towards every square it
        # touches and is clipped to each
        import math
        for lon in range(int(math.floor(gx0)), int(math.floor(gx1)) + 1):
            for lat in range(int(math.floor(gy0)), int(math.floor(gy1)) + 1):
                squares.setdefault((lon, lat), []).append(g.Clone())

    if not squares:
        sys.exit('demDrawnMask.py: no contour geometry')

    out = ogr.GetDriverByName('GeoJSON').CreateDataSource(out_path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dst = out.CreateLayer('drawn', srs, ogr.wkbPolygon)
    defn = dst.GetLayerDefn()

    kept = 0
    for (lon, lat), geoms in sorted(squares.items()):
        box = ogr.CreateGeometryFromWkt(
            'POLYGON((%d %d,%d %d,%d %d,%d %d,%d %d))'
            % (lon, lat, lon + 1, lat, lon + 1, lat + 1, lon, lat + 1, lon, lat))
        coll = ogr.Geometry(ogr.wkbGeometryCollection)
        for g in geoms:
            coll.AddGeometry(g)
        hull = coll.ConvexHull()
        if hull is None or hull.IsEmpty():
            continue
        # clipped to the square, so a way straddling a boundary does not drag
        # the hull of one square across into its neighbour
        clipped = hull.Intersection(box)
        if clipped is None or clipped.IsEmpty():
            continue
        f = ogr.Feature(defn)
        f.SetGeometry(clipped)
        dst.CreateFeature(f)
        kept += 1
    out = None
    print(f'  drawn area: {kept} square hulls, contours span '
          f'{xmin:.3f}..{xmax:.3f} by {ymin:.3f}..{ymax:.3f}', file=sys.stderr)


if __name__ == '__main__':
    main()
