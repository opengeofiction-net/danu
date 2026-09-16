#!/usr/bin/env python3
#
# Add the drawn water to the elevation constraints - see Admin:Elevation process
#
#   demWaterConstraints.py <cont.tif> --bbox W,S,E,N [--report out.json]
#
# Contours describe the ground every 25 m of height and say nothing between,
# which is where a river is: at the bottom of a valley the contours only bracket.
# The interpolator has no reason to put the valley floor under the river rather
# than anywhere else in the band, so it does not, and the published DEM ends up
# with water running along a hillside. On gobras that is 12,438 m of ascent
# which no reversal of the drawn ways can remove.
#
# So the water is read as a constraint in its own right. A waterway is sampled
# against the rasterised contours; where it crosses one it takes that contour's
# value, and between crossings it is graded from one to the next and forced to
# descend. That is what the old Perl did per tile in StreamShape, done here on
# the whole zone at once, against the vectors rather than a 256 px window.
#
# Two rules keep it honest:
#
# Contours win. A cell which already carries a contour is never written. The
# water only speaks where the contours are silent, so a bad river cannot drag a
# drawn contour with it - at worst it adds a constraint nobody asked for, in a
# band the interpolator was guessing at anyway.
#
# A waterway which disagrees with the contours is dropped, not forced. If the
# graded profile has to climb to reach the next crossing, the line and the
# ground are describing different terrain, and pinning the ground to it would
# make a trench where the contours say there is a hill. Those are counted and
# reported, and they are the ones demRiverCheck.py ranks.
#
# Lakes are flat. A closed water body takes the lowest contour value its outline
# touches, because a lake sits in the hollow, not on its rim.

import argparse
import collections
import json
import math
import sys
import urllib.request
import warnings
import xml.etree.ElementTree as ET

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
np.seterr(invalid='ignore')
warnings.filterwarnings('ignore', category=RuntimeWarning)

OVERPASS_URL = 'https://overpass.opengeofiction.net/api/interpreter'
NODATA = -9999
LINE_KINDS = ('river', 'stream')
AREA_TAGS = (('natural', 'water'), ('landuse', 'reservoir'))
MAX_RETRIES = 3
# a graded segment longer than this crosses too much unseen ground to trust
MAX_SEGMENT_M = 5000.0


def overpass(query, timeout=240):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(OVERPASS_URL, data=query.encode())
            with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
                return resp.read()
        except Exception as exc:                      # noqa: BLE001
            if attempt == MAX_RETRIES:
                raise
            print(f'  overpass attempt {attempt} failed ({exc})', file=sys.stderr)
    return b''


def fetch_water(bbox):
    w, s, e, n = bbox
    kinds = '|'.join(LINE_KINDS)
    sel = ''.join(f'way["{k}"="{v}"]({s},{w},{n},{e});' for k, v in AREA_TAGS)
    q = (f'[timeout:240][maxsize:400000000];'
         f'(way["waterway"~"^({kinds})$"]({s},{w},{n},{e});{sel});'
         f'(._;>;);out body;')
    root = ET.fromstring(overpass(q))
    nodes = {n_.get('id'): (float(n_.get('lon')), float(n_.get('lat')))
             for n_ in root.iter('node')}
    lines, areas = [], []
    for way in root.iter('way'):
        tags = {t.get('k'): t.get('v') for t in way.findall('tag')}
        pts = [nodes[nd.get('ref')] for nd in way.findall('nd')
               if nd.get('ref') in nodes]
        if len(pts) < 2:
            continue
        rec = (way.get('id'), tags.get('name', ''), pts)
        if tags.get('waterway') in LINE_KINDS:
            lines.append(rec)
        elif any(tags.get(k) == v for k, v in AREA_TAGS):
            if pts[0] == pts[-1] and len(pts) >= 4:
                areas.append(rec)
    return lines, areas


def densify(pts, step):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out.extend((x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k)
                   for i in range(1, k + 1))
    return out


def to_cells(pts, inv_gt, cols, rows):
    """Distinct in-range raster cells along the path, in order."""
    cells, seen = [], set()
    for x, y in pts:
        cx, cy = gdal.ApplyGeoTransform(inv_gt, x, y)
        ci, ri = int(cx), int(cy)
        if 0 <= ci < cols and 0 <= ri < rows and (ri, ci) not in seen:
            seen.add((ri, ci))
            cells.append((ri, ci))
    return cells


def grade(cells, values, seg_m):
    """Elevations along a waterway: contour values where it crosses one, graded
    between, and only where the grade descends. Returns {index: elevation}."""
    known = [i for i, v in enumerate(values) if v is not None]
    if len(known) < 2:
        return {}, 'too few crossings'
    out, rejected = {}, 0
    for a, b in zip(known, known[1:]):
        ea, eb = values[a], values[b]
        if eb > ea:                      # climbing: the line and the ground differ
            rejected += 1
            continue
        if sum(seg_m[a:b]) > MAX_SEGMENT_M:
            rejected += 1
            continue
        for i in range(a, b + 1):
            t = (i - a) / (b - a) if b > a else 0.0
            out[i] = ea + (eb - ea) * t
    return out, (f'{rejected} of {len(known)-1} segments rejected'
                 if rejected else '')


def seg_lengths(pts):
    lat = np.radians([p[1] for p in pts[:-1]])
    dx = np.diff([p[0] for p in pts]) * 111320.0 * np.cos(lat)
    dy = np.diff([p[1] for p in pts]) * 111320.0
    return np.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cont')
    ap.add_argument('--bbox', required=True)
    ap.add_argument('--report')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(','))
    ds = gdal.Open(args.cont, gdal.GA_ReadOnly if args.dry_run
                   else gdal.GA_Update)
    band = ds.GetRasterBand(1)
    gt = ds.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    cols, rows = ds.RasterXSize, ds.RasterYSize
    step = abs(gt[1])

    arr = band.ReadAsArray()
    have = arr != NODATA
    print(f'  contour cells: {have.sum():,} of {arr.size:,} '
          f'({100 * have.mean():.2f}%)')

    lines, areas = fetch_water(bbox)
    print(f'  drawn water: {len(lines)} waterways, {len(areas)} closed bodies')

    written = np.zeros_like(have)
    stats = collections.Counter()
    notes = []

    for wid, name, pts in lines:
        dense = densify(pts, step)
        cells = to_cells(dense, inv_gt, cols, rows)
        if len(cells) < 2:
            stats['outside'] += 1
            continue
        vals = [int(arr[r, c]) if have[r, c] else None for r, c in cells]
        seg = seg_lengths(dense)[:max(0, len(cells) - 1)]
        if len(seg) < len(cells) - 1:
            seg = np.pad(seg, (0, len(cells) - 1 - len(seg)), constant_values=0)
        graded, note = grade(cells, vals, seg)
        if not graded:
            stats['no grade'] += 1
            continue
        n = 0
        for i, elev in graded.items():
            r, c = cells[i]
            if not have[r, c] and not written[r, c]:
                arr[r, c] = int(round(elev))
                written[r, c] = True
                n += 1
        stats['graded'] += 1
        stats['cells'] += n
        if note:
            notes.append({'way': wid, 'name': name, 'note': note})

    for wid, name, pts in areas:
        dense = densify(pts, step)
        cells = to_cells(dense, inv_gt, cols, rows)
        vals = [int(arr[r, c]) for r, c in cells if have[r, c]]
        if not vals:
            stats['lake no contour'] += 1
            continue
        elev = min(vals)                 # a lake sits in the hollow, not on its rim
        for r, c in cells:
            if not have[r, c] and not written[r, c]:
                arr[r, c] = elev
                written[r, c] = True
                stats['cells'] += 1
        stats['lakes'] += 1

    print(f'  waterways graded {stats["graded"]}, '
          f'no usable grade {stats["no grade"]}, outside {stats["outside"]}')
    print(f'  lakes pinned {stats["lakes"]}, '
          f'without a contour {stats["lake no contour"]}')
    print(f'  constraint cells added: {stats["cells"]:,} '
          f'({100 * stats["cells"] / max(1, have.sum()):.2f}% more than the contours)')
    print(f'  waterways with rejected segments: {len(notes)}')

    if not args.dry_run and stats['cells']:
        band.WriteArray(arr)
        band.FlushCache()
        ds = None
        print(f'  written back to {args.cont}')

    if args.report:
        with open(args.report, 'w') as fh:
            json.dump({'stats': dict(stats), 'rejected': notes}, fh, indent=1)


if __name__ == '__main__':
    main()
