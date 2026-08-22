#!/usr/bin/env python3
#
# Recover editable contour squares from a DEM, for a zone whose source .osm
# squares have been lost - see Admin:Elevation process.
#
#   demRecoverSquares.py <dem.tif> <outdir> [--interval 10] [--simplify 0.0003]
#
# One .osm per degree square, named by its south west corner in the SRTM
# convention, holding contour ways tagged ele plus a frame way carrying the
# square name. JOSM format, negative ids, upload never.
#
# The zero metre boundary is written to a separate <square>_zeroline.osm rather
# than into the contours: it is where the DEM meets zero, which is a candidate
# coastline but not necessarily the coastline - inland seas are often
# natural=water instead, and only a mapper can say which is which.
#
# This is a lossy round trip. Everything between two contours is gone, and what
# comes back is the DEM's interpolation of the original drawing, not the
# drawing. It is a floor to edit up from, not a restoration.

import argparse
import math
import os
import shutil
import sys
import tempfile

from osgeo import gdal, ogr

try:
    import osmium
except ImportError:
    osmium = None

gdal.UseExceptions()
ogr.UseExceptions()


def square_name(lon, lat):
    """SRTM naming, by south west corner, always N/SxxE/Wxxx."""
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    return f'{ns}{abs(lat):02d}{ew}{abs(lon):03d}'


class OsmFile:
    """Minimal JOSM style .osm writer. Ids run negative, as for new data."""

    # Ids ascend from a large negative base rather than descending from -1.
    # They stay negative, as new data must, but the GDAL OSM driver rejects a
    # file whose node ids decrease ("Non increasing node id") and JOSM's own
    # files ascend too
    ID_BASE = -50_000_000

    def __init__(self, path, generator):
        # Nodes and ways are buffered separately so the file comes out as all
        # nodes then all ways, the way JOSM writes it. Interleaving the two -
        # even with ascending ids - trips the GDAL OSM driver's node index
        self.path = path
        self.generator = generator
        self.node_buf = tempfile.TemporaryFile('w+')
        self.way_buf = tempfile.TemporaryFile('w+')
        self.next_id = self.ID_BASE
        self.nodes = 0
        self.ways = 0

    def _id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def way(self, coords, tags, closed=False):
        """coords: [(lon, lat), ...]. Returns nothing; writes nodes then the way."""
        ids = []
        for lon, lat in coords:
            i = self._id()
            self.node_buf.write(f"  <node id='{i}' action='modify' "
                                f"lat='{lat:.7f}' lon='{lon:.7f}' />\n")
            ids.append(i)
            self.nodes += 1
        if closed and ids:
            ids.append(ids[0])
        w = self._id()
        self.way_buf.write(f"  <way id='{w}' action='modify'>\n")
        for i in ids:
            self.way_buf.write(f"    <nd ref='{i}' />\n")
        for k, v in tags.items():
            self.way_buf.write(f"    <tag k='{k}' v='{v}' />\n")
        self.way_buf.write("  </way>\n")
        self.ways += 1

    def close(self):
        # Ways are written after nodes, but their ids come from the same counter,
        # so a way id can be lower than a node id. That is fine: the two are
        # separate id spaces in OSM, and each is increasing within itself
        with open(self.path, 'w') as f:
            f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
            f.write("<osm version='0.6' upload='never' "
                    f"generator='{self.generator}'>\n")
            for buf in (self.node_buf, self.way_buf):
                buf.seek(0)
                shutil.copyfileobj(buf, f)
                buf.close()
            f.write('</osm>\n')


def load_zero_lines(path):
    """Every way in a water file, as OGR linestrings tagged for output.

    The file is the sea level constraint for the zone: natural=coastline for the
    ocean, plus natural=water for anything mapped as an area instead - inland
    seas usually are. Multipolygon members carry no tags of their own, so rather
    than resolving relations every way in the file is taken: it is a
    purpose-built water file, so nothing in it is anything but a water edge.

    What matters to the interpolation is only that the line reads zero. A closed
    ring of zeroes makes the fill read zero throughout the body inside it, which
    is why no polygon burning or planet lookup is needed.

    Two passes with a plain node dictionary rather than a locations index: a
    zone's water is a few hundred thousand nodes, so the simple way costs
    nothing and does not depend on the pyosmium version.
    """
    if osmium is None:
        sys.exit('pyosmium is needed for --water (apt install python3-pyosmium)')

    coords = {}
    wanted = set()

    class Ways(osmium.SimpleHandler):
        def way(self, w):
            wanted.update(n.ref for n in w.nodes)

    class Nodes(osmium.SimpleHandler):
        def node(self, n):
            if n.id in wanted:
                coords[n.id] = (n.location.lon, n.location.lat)

    class Build(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.lines = []
            self.kinds = {}

        def way(self, w):
            pts = [coords[n.ref] for n in w.nodes if n.ref in coords]
            if len(pts) < 2:
                return
            g = ogr.Geometry(ogr.wkbLineString)
            for lon, lat in pts:
                g.AddPoint_2D(lon, lat)
            natural = w.tags.get('natural')
            self.lines.append((g, natural))
            self.kinds[natural] = self.kinds.get(natural, 0) + 1

    Ways().apply_file(path)
    Nodes().apply_file(path)
    b = Build()
    b.apply_file(path)
    kinds = ', '.join(f'{v} {k or "untagged, multipolygon member"}'
                      for k, v in sorted(b.kinds.items(), key=lambda x: -x[1]))
    print(f'{path}: {len(b.lines)} water ways ({kinds})', file=sys.stderr)
    return b.lines


def clip_lines(lines, lon, lat):
    """Clip linestrings to one degree square, returning coordinate lists."""
    box = ogr.CreateGeometryFromWkt(
        f'POLYGON(({lon} {lat},{lon + 1} {lat},{lon + 1} {lat + 1},'
        f'{lon} {lat + 1},{lon} {lat}))')
    out = []
    for line, natural in lines:
        if not line.Intersects(box):
            continue
        part = line.Intersection(box)
        if part is None or part.IsEmpty():
            continue
        geoms = ([part.GetGeometryRef(i) for i in range(part.GetGeometryCount())]
                 if part.GetGeometryName() == 'MULTILINESTRING' else [part])
        for g in geoms:
            if g.GetPointCount() >= 2:
                out.append(([(g.GetX(i), g.GetY(i))
                             for i in range(g.GetPointCount())], natural))
    return out


def water_rings(dem_path, lon, lat, coast, min_cells=16):
    """Boundaries of water bodies in one square that no coastline way touches.

    An inland sea is often natural=water on the main map rather than
    natural=coastline (Roantra), so no coastline way exists to pin it to zero.
    Left unconstrained, interpolation drifts the whole body upward from the
    surrounding land contours. A closed ring tagged ele 0 fixes it: every
    constraint bounding the water reads zero, so the fill reads zero throughout,
    and no planet data is needed.

    Bodies which do have coastline are skipped - that geometry is authoritative
    and already in the square.
    """
    tmp = f'/vsimem/w_{square_name(lon, lat)}.tif'
    gdal.Translate(tmp, dem_path, projWin=[lon, lat + 1, lon + 1, lat],
                   projWinSRS='EPSG:4326')
    src = gdal.Open(tmp)
    band = src.GetRasterBand(1)
    a = band.ReadAsArray()

    mask_drv = gdal.GetDriverByName('MEM')
    mask = mask_drv.Create('m', src.RasterXSize, src.RasterYSize, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(src.GetGeoTransform())
    mask.SetProjection(src.GetProjection())
    mask.GetRasterBand(1).WriteArray((a <= 0).astype('uint8'))

    drv = ogr.GetDriverByName('MEM')
    ds = drv.CreateDataSource('p')
    layer = ds.CreateLayer('poly', geom_type=ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
    gdal.Polygonize(mask.GetRasterBand(1), mask.GetRasterBand(1), layer, 0)

    px = abs(src.GetGeoTransform()[1] * src.GetGeoTransform()[5])
    rings, skipped = [], 0
    for feat in layer:
        if feat.GetField('v') != 1:
            continue
        geom = feat.GetGeometryRef()
        if geom.GetArea() < min_cells * px:
            continue
        if any(line.Intersects(geom) for line in coast):
            skipped += 1
            continue
        for i in range(geom.GetGeometryCount()):
            r = geom.GetGeometryRef(i)
            pts = [(r.GetX(j), r.GetY(j)) for j in range(r.GetPointCount())]
            if len(pts) >= 4:
                rings.append(pts)

    src = None
    gdal.Unlink(tmp)
    return rings, skipped


def contours_for_square(dem, lon, lat, interval, simplify, min_vertices):
    """Contour one degree square of the DEM. Returns {elevation: [ring, ...]}.

    The square is cut on exact degree lines so that neighbouring squares share
    their boundary vertices, which is what stops the edges glitching when the
    squares are interpolated back into a surface.
    """
    tmp = f'/vsimem/sq_{square_name(lon, lat)}.tif'
    gdal.Translate(tmp, dem, projWin=[lon, lat + 1, lon + 1, lat],
                   projWinSRS='EPSG:4326')

    src = gdal.Open(tmp)
    band = src.GetRasterBand(1)
    lo, hi = band.ComputeRasterMinMax(False)

    drv = ogr.GetDriverByName('MEM')
    ds = drv.CreateDataSource('c')
    layer = ds.CreateLayer('contour', geom_type=ogr.wkbLineString)
    layer.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))

    gdal.ContourGenerate(band, interval, 0, [], 0, 0, layer, -1, 0)

    out = {}
    for feat in layer:
        ele = feat.GetField('ele')
        geom = feat.GetGeometryRef()
        if simplify:
            geom = geom.SimplifyPreserveTopology(simplify)
        if geom is None or geom.GetPointCount() < min_vertices:
            continue
        pts = [(geom.GetX(i), geom.GetY(i)) for i in range(geom.GetPointCount())]
        out.setdefault(int(round(ele)), []).append(pts)

    src = None
    gdal.Unlink(tmp)
    return out, lo, hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dem')
    ap.add_argument('outdir')
    ap.add_argument('--interval', type=float, default=10.0,
                    help='contour interval in metres (default 10)')
    ap.add_argument('--simplify', type=float, default=0.0002,
                    help='simplify tolerance in degrees, 0 to keep every vertex. '
                         'The default is about a quarter of a 3 arcsecond cell. '
                         'Do not raise it much: Douglas-Peucker lets the line '
                         'deviate by the whole tolerance, and topology is only '
                         'preserved per feature, so at cell scale neighbouring '
                         'contours facet badly and start crossing each other')
    ap.add_argument('--smooth', type=int, default=0, metavar='N',
                    help='box filter the DEM over N cells before contouring, '
                         'which gives smooth curves instead of raster stair '
                         'steps. Off by default: where the contours were drawn '
                         'programmatically the steps are in the original data, '
                         'and smoothing them is a change to it, not a fix')
    ap.add_argument('--min-vertices', type=int, default=4,
                    help='drop rings with fewer vertices than this: at a 10 m '
                         'interval they are interpolation speckle, not landform')
    ap.add_argument('--water', '--coastline', metavar='OSM', dest='water',
                    help='an .osm or .osm.pbf holding the sea level edges for '
                         'the zone - coastline and any water mapped as an area '
                         'instead. Clipped into each square as ele 0. Without '
                         'it the sea is unconstrained and the rebuilt DEM '
                         'drifts upward over water, by 30 m RMS in testing')
    ap.add_argument('--water-rings', action='store_true',
                    help='additionally derive ele 0 rings around water bodies '
                         'in the DEM which no --water line touches. A fallback '
                         'when no water file exists, and a crude one: bodies '
                         'joined to the sea by a river at zero come out as one, '
                         'so inland water gets missed')
    ap.add_argument('--suffix', default='recovered',
                    help="filename suffix after the square name")
    args = ap.parse_args()

    dem_path = args.dem
    if args.smooth:
        # Box filter through a VRT kernel: GDAL streams it block by block, so
        # this costs no memory however large the zone
        vrt = os.path.join(args.outdir if os.path.isdir(args.outdir) else '.',
                           '.smoothed.vrt')
        os.makedirs(args.outdir, exist_ok=True)
        vrt = os.path.join(args.outdir, '.smoothed.vrt')
        gdal.Translate(vrt, args.dem, format='VRT')
        n = args.smooth
        text = open(vrt).read()
        kernel = (f'<Kernel normalized="1"><Size>{n}</Size>'
                  f'<Coefs>{" ".join(["1"] * n * n)}</Coefs></Kernel>')
        text = (text.replace('<SimpleSource>', '<KernelFilteredSource>')
                    .replace('</SimpleSource>', kernel + '</KernelFilteredSource>'))
        open(vrt, 'w').write(text)
        dem_path = vrt
        print(f'smoothing over {n} cells before contouring', file=sys.stderr)

    dem = gdal.Open(dem_path)
    gt = dem.GetGeoTransform()
    w, h = dem.RasterXSize, dem.RasterYSize

    # Grid registered rasters sit half a pixel outside the degree line, so round
    # to the nearest whole degree rather than truncating
    west = math.floor(gt[0] + abs(gt[1]) / 2 + 1e-9)
    north = math.ceil(gt[3] - abs(gt[5]) / 2 - 1e-9)
    east = math.ceil(gt[0] + w * gt[1] - abs(gt[1]) / 2 - 1e-9)
    south = math.floor(gt[3] + h * gt[5] + abs(gt[5]) / 2 + 1e-9)

    water = load_zero_lines(args.water) if args.water else []

    os.makedirs(args.outdir, exist_ok=True)
    print(f'{args.dem}: {w}x{h}, covering {square_name(west, south)} '
          f'to {square_name(east - 1, north - 1)}', file=sys.stderr)

    total_sq = written = 0
    for lat in range(south, north):
        for lon in range(west, east):
            total_sq += 1
            name = square_name(lon, lat)
            rings, lo, hi = contours_for_square(dem_path, lon, lat, args.interval,
                                                args.simplify, args.min_vertices)
            levels = sorted(k for k in rings if k >= args.interval)
            path = os.path.join(args.outdir, f'{name}_{args.suffix}.osm')
            osm = OsmFile(path, 'demRecoverSquares.py')
            for ele in levels:
                for pts in rings[ele]:
                    osm.way(pts, {'contour': 'elevation', 'ele': str(ele)})
            shore = clip_lines(water, lon, lat) if water else []
            for pts, natural in shore:
                tags = {'ele': '0'}
                if natural:
                    tags['natural'] = natural
                osm.way(pts, tags)

            wrings, wskip = water_rings(
                dem_path, lon, lat, [ogr.CreateGeometryFromWkt(
                    'LINESTRING(' + ','.join(f'{x} {y}' for x, y in pts) + ')')
                    for pts, _ in shore]) if args.water_rings else ([], 0)
            for pts in wrings:
                osm.way(pts, {'ele': '0',
                              'note': 'water body edge, derived from the DEM'})
            # frame last, so it is easy to find in JOSM
            osm.way([(lon, lat), (lon + 1, lat), (lon + 1, lat + 1),
                     (lon, lat + 1)],
                    {'ref': name, 'note': 'degree square frame, not contour data'},
                    closed=True)
            osm.close()

            zero = rings.get(0, [])
            zpath = ''
            if zero:
                zpath = os.path.join(args.outdir, f'{name}_zeroline.osm')
                z = OsmFile(zpath, 'demRecoverSquares.py')
                for pts in zero:
                    z.way(pts, {'note': 'zero metre boundary, candidate coastline'})
                z.close()

            written += 1
            where = (f'{len(levels)} levels {levels[0]}..{levels[-1]} m'
                     if levels else f'no contours, {lo:.0f}..{hi:.0f} m')
            print(f'  {name}: {where}, {len(shore)} coast, '
                  f'{len(wrings)} water rings'
                  f'{f" ({wskip} bodies already had coastline)" if wskip else ""}, '
                  f'{osm.ways} ways, {osm.nodes} nodes'
                  f'{f", zeroline {len(zero)} ways" if zero else ""}',
                  file=sys.stderr)

    print(f'{written} of {total_sq} squares written to {args.outdir}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
