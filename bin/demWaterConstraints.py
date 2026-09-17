#!/usr/bin/env python3
#
# Add the drawn water to the elevation constraints - see Admin:Elevation process
#
#   demWaterConstraints.py <cont.tif> --bbox W,S,E,N [--mask drawn-mask.tif]
#
# Contours describe the ground every 25 m of height and say nothing between,
# which is where a river is: at the bottom of a valley the contours only
# bracket. The interpolator has no reason to put the valley floor under the
# river rather than anywhere else in the band, so it does not, and the published
# DEM ends up with water running along a hillside. On gobras that was 12,438 m
# of ascent which no reversal of the drawn ways can remove.
#
# So the water is read as a constraint in its own right:
#
# A waterway is sampled against the rasterised contours; where it crosses one it
# takes that contour's value, and between crossings it is graded from one to the
# next and forced to descend. That is what the old Perl did per tile in
# StreamShape, done here on the whole zone at once against the vectors.
#
# A water body is flat, and is burned flat across its whole surface. Its level
# is its outlet: a graded river descends, so the lowest graded river elevation
# inside the body is the point water leaves it. Failing that - no river touches
# it - the lowest contour its outline touches, which is cruder, because the rim
# need not agree with whatever drains the hollow. The surface matters more than
# the outline: Lake Kinser is 37.5 km², some 41,000 cells at 1 arcsecond, which
# is more constraint than every waterway in gobras put together.
#
# Geometry comes from GDAL's OSM driver rather than from parsing the XML here,
# because a lake is as likely to be a multipolygon relation as a closed way -
# gobras has 120 water relations, Lake Kinser among them - and the driver
# assembles rings and holes properly where hand-rolled parsing did not.
#
# Two rules keep it honest:
#
# Contours win over a river. A cell which already carries a contour is never
# written from a waterway, so a river only speaks where the contours are silent
# and a bad one cannot drag a drawn contour with it.
#
# A water body wins over the contours inside it. A lake surface is flat by
# definition, so a contour crossing one is describing ground that is under
# water. Lake Kinser had the 150 m contour and a little of the 175 m across it,
# and honouring those left 11.6% of its surface stepped above the rest. The
# elevation a body is pinned at still comes from the contours its outline
# touches, so the contours decide the height and only lose inside the water.
# Overridden cells are counted, because a lake spanning three contours is a
# disagreement in the drawn data and worth knowing about.
#
# Nothing is written outside the envelope the contours describe. A graded river
# reaching past the last contour has nothing to blend into, and came out as a
# 4.7 km strip of 449 m ground standing in a void held at zero - a wall in the
# hillshade exactly where the mapped contours stop.

import argparse
import collections
import json
import math
import os
import sys
import urllib.request
import warnings

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
np.seterr(invalid='ignore')
warnings.filterwarnings('ignore', category=RuntimeWarning)

OVERPASS_URL = 'https://overpass.opengeofiction.net/api/interpreter'
NODATA = -9999
LINE_KINDS = ('river', 'stream')
MAX_RETRIES = 3
# a graded segment longer than this crosses too much unseen ground to trust
MAX_SEGMENT_M = 5000.0
M_PER_DEG = 111320.0


def fetch(bbox, path):
    w, s, e, n = bbox
    box = f'{s},{w},{n},{e}'
    kinds = '|'.join(LINE_KINDS)
    q = (f'[timeout:600][maxsize:1000000000];('
         f'way["waterway"~"^({kinds})$"]({box});'
         f'way["natural"="water"]({box});way["landuse"="reservoir"]({box});'
         f'relation["natural"="water"]({box});'
         f'relation["landuse"="reservoir"]({box});'
         f');(._;>>;);out body;')
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(OVERPASS_URL, data=q.encode())
            with urllib.request.urlopen(req, timeout=900) as resp, \
                    open(path, 'wb') as fh:
                while chunk := resp.read(1 << 20):
                    fh.write(chunk)
            return True
        except Exception as exc:                      # noqa: BLE001
            print(f'  overpass attempt {attempt} failed ({exc})', file=sys.stderr)
    return False


def ring_points(geom):
    """Vertices of every exterior ring, flattened."""
    pts = []
    if geom.GetGeometryType() in (ogr.wkbMultiPolygon, ogr.wkbMultiPolygon25D,
                                  ogr.wkbGeometryCollection):
        for i in range(geom.GetGeometryCount()):
            pts.extend(ring_points(geom.GetGeometryRef(i)))
    elif geom.GetGeometryType() in (ogr.wkbPolygon, ogr.wkbPolygon25D):
        r = geom.GetGeometryRef(0)
        pts.extend((r.GetX(i), r.GetY(i)) for i in range(r.GetPointCount()))
    else:
        pts.extend((geom.GetX(i), geom.GetY(i))
                   for i in range(geom.GetPointCount()))
    return pts


def densify(pts, step):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out.extend((x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k)
                   for i in range(1, k + 1))
    return out


def to_cells(pts, inv_gt, cols, rows):
    cells, seen = [], set()
    for x, y in pts:
        cx, cy = gdal.ApplyGeoTransform(inv_gt, x, y)
        ci, ri = int(cx), int(cy)
        if 0 <= ci < cols and 0 <= ri < rows and (ri, ci) not in seen:
            seen.add((ri, ci))
            cells.append((ri, ci))
    return cells


def seg_lengths(pts):
    lat = np.radians([p[1] for p in pts[:-1]])
    dx = np.diff([p[0] for p in pts]) * M_PER_DEG * np.cos(lat)
    dy = np.diff([p[1] for p in pts]) * M_PER_DEG
    return np.hypot(dx, dy)


def grade(values, seg_m):
    """Contour values where the way crosses one, graded between, descending
    only. OGF::Terrain::RiverProfile::setLinearElev, on a whole way."""
    known = [i for i, v in enumerate(values) if v is not None]
    if len(known) < 2:
        return {}, 0
    out, rejected = {}, 0
    for a, b in zip(known, known[1:]):
        ea, eb = values[a], values[b]
        if eb > ea or sum(seg_m[a:b]) > MAX_SEGMENT_M:
            rejected += 1
            continue
        for i in range(a, b + 1):
            out[i] = ea + (eb - ea) * ((i - a) / (b - a) if b > a else 0.0)
    return out, rejected


def burn_lakes(feats, template, inv_gt, cols, rows, arr, have, step, graded):
    """Each water body flat across its whole surface.

    The level is the outlet: a graded river only descends, so the lowest graded
    elevation inside the body is where water leaves it. With no river touching
    it, the lowest contour the outline crosses, which is cruder - the rim need
    not agree with whatever drains the hollow.
    """
    drv = ogr.GetDriverByName('MEM') or ogr.GetDriverByName('Memory')
    if drv is None:
        raise RuntimeError('no OGR in-memory driver available')
    src = drv.CreateDataSource('lakes')
    srs = osr.SpatialReference()
    srs.SetFromUserInput(template.GetProjection() or 'EPSG:4326')
    lyr = src.CreateLayer('lakes', srs=srs, geom_type=ogr.wkbMultiPolygon)
    lyr.CreateField(ogr.FieldDefn('lid', ogr.OFTInteger))

    # the rim value per body, kept as the fallback, and the id of each
    rim = {}
    for n, (geom, _name) in enumerate(feats, start=1):
        pts = ring_points(geom)
        if len(pts) < 3:
            continue
        cells = to_cells(densify(pts, step), inv_gt, cols, rows)
        vals = [int(arr[r, c]) for r, c in cells if have[r, c]]
        rim[n] = min(vals) if vals else None
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField('lid', n)
        f.SetGeometry(geom.Clone())
        lyr.CreateFeature(f)
    if not rim:
        return None, {}

    # one rasterise pass for every body, each carrying its own id, so the
    # surfaces can be looked at per body without a pass per lake
    dtype = gdal.GDT_UInt16 if len(feats) < 65535 else gdal.GDT_UInt32
    mem = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, dtype)
    mem.SetGeoTransform(template.GetGeoTransform())
    mem.SetProjection(template.GetProjection())
    mem.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(mem, [1], lyr, options=['ATTRIBUTE=lid'])
    labels = mem.GetRasterBand(1).ReadAsArray()

    # the outlet, found by walking the graded river cells rather than the
    # surfaces: there are tens of thousands of the former and millions of the
    # latter
    outlet = {}
    for (r, c), elev in graded.items():
        lid = int(labels[r, c])
        if lid and (lid not in outlet or elev < outlet[lid]):
            outlet[lid] = elev

    level, how = {}, collections.Counter()
    for lid in rim:
        if lid in outlet:
            level[lid] = outlet[lid]
            how['outlet'] += 1
        elif rim[lid] is not None:
            level[lid] = rim[lid]
            how['rim'] += 1
        else:
            how['no level'] += 1
    return (labels, level), how


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cont')
    ap.add_argument('--bbox', required=True)
    ap.add_argument('--mask', help='only write inside this mask')
    ap.add_argument('--report')
    ap.add_argument('--osm', help='keep the fetched OSM here instead of a temp file')
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(','))
    work = os.path.dirname(os.path.abspath(args.cont))
    # the OSM driver spills to CPL_TMPDIR past OSM_MAX_TMPFILE_SIZE and returns
    # an empty layer, silently, if it cannot write there
    os.environ.setdefault('CPL_TMPDIR', work)
    os.environ['OSM_USE_CUSTOM_INDEXING'] = 'NO'

    osm = args.osm or os.path.join(work, 'water.osm')
    if not fetch(bbox, osm):
        sys.exit('could not fetch the water')
    print(f'  fetched {os.path.getsize(osm) / 1048576:.1f} MB of drawn water')

    ds = gdal.Open(args.cont, gdal.GA_Update)
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    cols, rows = ds.RasterXSize, ds.RasterYSize
    step = abs(gt[1])
    arr = band.ReadAsArray()
    have = arr != NODATA
    print(f'  contour cells: {have.sum():,} of {arr.size:,} '
          f'({100 * have.mean():.2f}%)')

    if args.mask:
        allow = gdal.Open(args.mask).ReadAsArray() > 0
        if allow.shape != arr.shape:
            sys.exit(f'mask is {allow.shape}, raster is {arr.shape}')
        print(f'  drawn mask covers {100 * allow.mean():.2f}% of the zone')
    else:
        allow = np.ones(arr.shape, dtype=bool)

    osm_ds = ogr.Open(osm)
    stats = collections.Counter()
    notes = []
    river_elev = {}
    writable = (~have) & allow

    # ---- waterways
    lines = osm_ds.GetLayerByName('lines')
    lines.SetAttributeFilter("waterway IN ('%s')" % "','".join(LINE_KINDS))
    for feat in lines:
        geom = feat.GetGeometryRef()
        if geom is None or geom.GetPointCount() < 2:
            continue
        pts = [(geom.GetX(i), geom.GetY(i)) for i in range(geom.GetPointCount())]
        dense = densify(pts, step)
        cells = to_cells(dense, inv_gt, cols, rows)
        if len(cells) < 2:
            stats['outside'] += 1
            continue
        vals = [int(arr[r, c]) if have[r, c] else None for r, c in cells]
        seg = seg_lengths(dense)
        seg = np.pad(seg, (0, max(0, len(cells) - 1 - len(seg))))
        graded, rejected = grade(vals, seg)
        if not graded:
            stats['no grade'] += 1
            continue
        for i, elev in graded.items():
            r, c = cells[i]
            # every graded cell is remembered, written or not: a cell which
            # lost to a contour still says what height the water is there,
            # which is what a lake's outlet needs
            if (r, c) not in river_elev or elev < river_elev[(r, c)]:
                river_elev[(r, c)] = elev
            if writable[r, c]:
                arr[r, c] = int(round(elev))
                writable[r, c] = False
                stats['river cells'] += 1
        stats['graded'] += 1
        if rejected:
            notes.append({'way': feat.GetField('osm_id'),
                          'name': feat.GetField('name') or '',
                          'rejected': rejected})

    # ---- water bodies
    polys = osm_ds.GetLayerByName('multipolygons')
    polys.SetAttributeFilter("natural = 'water' OR landuse = 'reservoir'")
    feats = []
    for feat in polys:
        g = feat.GetGeometryRef()
        if g is not None:
            feats.append((g.Clone(), feat.GetField('name') or ''))
    burnt, how = burn_lakes(feats, ds, inv_gt, cols, rows,
                            arr, have, step, river_elev)
    if burnt is not None:
        labels, level = burnt
        lut = np.zeros(max(level) + 1 if level else 1, dtype='f4')
        known = np.zeros(lut.shape, dtype=bool)
        for lid, elev in level.items():
            lut[lid] = elev
            known[lid] = True
        # inside the mask, but not limited to cells the contours left empty:
        # a flat surface means the contours crossing it give way
        sel = (labels > 0) & allow
        sel &= known[np.clip(labels, 0, len(known) - 1)]
        stats['lake over contour'] = int((sel & have).sum())
        arr[sel] = np.round(lut[labels[sel]]).astype(arr.dtype)
        stats['lake cells'] += int(sel.sum())
    stats['lakes'] = how['outlet'] + how['rim']
    stats['from outlet'] = how['outlet']
    stats['from rim'] = how['rim']
    stats['lake no level'] = how['no level']

    total = stats['river cells'] + stats['lake cells']
    print(f'  waterways graded {stats["graded"]}, no usable grade '
          f'{stats["no grade"]}, outside {stats["outside"]}')
    print(f'  water bodies {len(feats)}: pinned {stats["lakes"]} '
          f'({stats["from outlet"]} from an outlet, {stats["from rim"]} from '
          f'the rim), no level found {stats["lake no level"]}')
    print(f'  contour cells overridden by a water surface: '
          f'{stats["lake over contour"]:,}')
    print(f'  constraint cells added: {total:,} '
          f'({stats["river cells"]:,} river, {stats["lake cells"]:,} lake) '
          f'- {100 * total / max(1, have.sum()):.2f}% more than the contours')
    print(f'  waterways with rejected segments: {len(notes)}')

    if total:
        band.WriteArray(arr)
        band.FlushCache()
        ds = None
        print(f'  written back to {args.cont}')

    if args.report:
        with open(args.report, 'w') as fh:
            json.dump({'stats': dict(stats), 'rejected': notes}, fh, indent=1)
    if not args.osm:
        os.unlink(osm)


if __name__ == '__main__':
    main()
