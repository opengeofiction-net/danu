#!/usr/bin/env python3
#
# Where the mapped rivers disagree with the published elevation - see
# Admin:Elevation process
#
#   rivers.py <dem.tif> --bbox W,S,E,N [--geojson out.json]
#
# Contours are the source of truth for elevation and the waterways are drawn
# separately, so nothing makes the two agree. Where they do not, the DEM has a
# river climbing a hill: the contours say the ground rises, the mapper drew
# water running down it, and the renderer draws both.
#
# This is the check the old Perl had and the current pipeline does not. It is
# OGF::Terrain::RiverProfile::getInvalidIntervals, which walked a river from
# source to mouth tracking the lowest elevation seen so far and flagged every
# run that climbed above it. That widget needed a host application which was
# never published, but the 30 lines that matter needed nothing from it.
#
# A waterway is drawn downstream - OSM orders the nodes source to mouth - so the
# way's own direction gives the expected flow without any guesswork. A way which
# ascends over most of its length is more likely drawn backwards than genuinely
# wrong, and is reported separately, because the fix is different: reverse the
# way, not rework the contours.
#
# Samples at the DEM's own resolution. Sampling only at the drawn nodes would
# miss the interesting case, which is a river crossing a spur between two nodes
# a kilometre apart.

import argparse
import math
import sys
import urllib.request
import warnings
import xml.etree.ElementTree as ET

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
# a way partly outside the raster samples as nan, which is expected
np.seterr(invalid='ignore')
warnings.filterwarnings('ignore', category=RuntimeWarning)

OVERPASS_URL = 'https://overpass.opengeofiction.net/api/interpreter'
# river and stream are the drawn drainage; canal and ditch are cut by hand and
# genuinely may not follow the ground, so they are fetched but reported apart
NATURAL = ('river', 'stream')
ARTIFICIAL = ('canal', 'ditch', 'drain')
M_PER_DEG_LAT = 111320.0
MAX_RETRIES = 3


def fetch_waterways(bbox, timeout=180):
    """Every waterway way in the box, as {id: (name, kind, [(lon,lat), ...])}."""
    w, s, e, n = bbox
    kinds = '|'.join(NATURAL + ARTIFICIAL)
    query = (f'[timeout:{timeout}][maxsize:200000000];'
             f'(way["waterway"~"^({kinds})$"]({s},{w},{n},{e}););'
             f'(._;>;);out body;')
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(OVERPASS_URL, data=query.encode())
            with urllib.request.urlopen(req, timeout=timeout + 60) as resp:
                return parse_osm(resp.read())
        except Exception as exc:                      # noqa: BLE001
            if attempt == MAX_RETRIES:
                raise
            print(f'  overpass attempt {attempt} failed ({exc}), retrying',
                  file=sys.stderr)
    return {}


def parse_osm(xml_bytes):
    root = ET.fromstring(xml_bytes)
    nodes = {n.get('id'): (float(n.get('lon')), float(n.get('lat')))
             for n in root.iter('node')}
    ways = {}
    for w in root.iter('way'):
        tags = {t.get('k'): t.get('v') for t in w.findall('tag')}
        kind = tags.get('waterway')
        if kind not in NATURAL + ARTIFICIAL:
            continue
        pts = [nodes[nd.get('ref')] for nd in w.findall('nd')
               if nd.get('ref') in nodes]
        if len(pts) >= 2:
            ways[w.get('id')] = (tags.get('name', ''), kind, pts)
    return ways


def densify(pts, step_deg):
    """Insert points so no gap exceeds step_deg, keeping the drawn order."""
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        for i in range(1, max(1, int(d / step_deg)) + 1):
            t = i / max(1, int(d / step_deg))
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def sample(ds, inv_gt, pts):
    """Elevation at each point, nan outside the raster."""
    cols, rows = ds.RasterXSize, ds.RasterYSize
    px = np.array([gdal.ApplyGeoTransform(inv_gt, x, y) for x, y in pts])
    xi = np.clip(px[:, 0].astype(int), 0, cols - 1)
    yi = np.clip(px[:, 1].astype(int), 0, rows - 1)
    inside = ((px[:, 0] >= 0) & (px[:, 0] < cols) &
              (px[:, 1] >= 0) & (px[:, 1] < rows))
    x0, x1, y0, y1 = xi.min(), xi.max(), yi.min(), yi.max()
    win = ds.GetRasterBand(1).ReadAsArray(
        int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)).astype('f8')
    v = win[yi - y0, xi - x0]
    v[~inside] = np.nan
    return v


def invalid_intervals(elev):
    """Runs which climb above the lowest elevation seen so far, walking the way
    in its drawn direction. OGF::Terrain::RiverProfile::getInvalidIntervals."""
    intervals, start, lowest = [], None, elev[0]
    for i, e in enumerate(elev):
        if np.isnan(e):
            continue
        if e <= lowest:
            if start is not None:
                intervals.append((start, i - 1))
                start = None
            lowest = e
        elif start is None:
            start = i
    if start is not None:
        intervals.append((start, len(elev) - 1))
    return intervals


def linear_fix(elev, intervals):
    """What setLinearElev would write: each bad run replaced by a ramp between
    the good points either side. Returns the corrected profile, for measuring
    how much the ground would have to move."""
    out = elev.astype('f8').copy()
    n = len(out)
    for i0, i1 in intervals:
        a, b = max(0, i0 - 1), min(n - 1, i1 + 1)
        if b <= a:
            continue
        # the mouth is never lowered - setLinearElev guards this explicitly
        if b == n - 1 and out[b] > out[a]:
            b = a
            continue
        out[a:b + 1] = np.linspace(out[a], out[b], b - a + 1)
    return out


def seg_len_m(pts):
    """Length in metres of each step along the way."""
    lat = np.radians([p[1] for p in pts[:-1]])
    dx = np.diff([p[0] for p in pts]) * M_PER_DEG_LAT * np.cos(lat)
    dy = np.diff([p[1] for p in pts]) * M_PER_DEG_LAT
    return np.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dem')
    ap.add_argument('--bbox', required=True, help='W,S,E,N')
    ap.add_argument('--geojson', help='write the offending runs for QGIS')
    ap.add_argument('--top', type=int, default=25)
    ap.add_argument('--min-ascent', type=float, default=1.0,
                    help='ignore ways whose total ascent is under this (m)')
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(','))
    ds = gdal.Open(args.dem)
    gt = ds.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    step = abs(gt[1])

    print(f'  fetching waterways for {args.bbox}', file=sys.stderr)
    ways = fetch_waterways(bbox)
    print(f'  {len(ways)} ways', file=sys.stderr)

    rows, backwards, features = [], [], []
    for wid, (name, kind, pts) in ways.items():
        dense = densify(pts, step)
        elev = sample(ds, inv_gt, dense)
        if np.all(np.isnan(elev)):
            continue
        seg = seg_len_m(dense)
        length = float(seg.sum())
        d = np.diff(elev)
        up = np.nansum(d[d > 0])
        down = -np.nansum(d[d < 0])
        intervals = invalid_intervals(elev)
        bad_m = sum(float(seg[i0:i1 + 1].sum())
                    for i0, i1 in intervals if i1 < len(seg))
        fixed = linear_fix(elev, intervals)
        moved = float(np.nanmax(np.abs(fixed - elev))) if intervals else 0.0
        # A river drawn the wrong way round climbs in the direction it is
        # drawn and falls in the other, so its ascent is large but its descent
        # is not. Reversing cannot remove min(ascent, descent): that part is the
        # ground disagreeing with the line whichever way the water runs, and it
        # is the only figure here that says something about the contours rather
        # than about how somebody drew a way.
        irreducible = min(up, down)
        rec = dict(id=wid, name=name, kind=kind, length=length, ascent=up,
                   descent=down, irred=irreducible, bad_m=bad_m,
                   runs=len(intervals), moved=moved,
                   drop=float(np.nanmax(elev) - np.nanmin(elev)))
        if up > down and length > 200 and irreducible < 0.25 * up:
            backwards.append(rec)          # reversing would largely fix it
        elif irreducible >= args.min_ascent:
            rows.append(rec)
        if args.geojson and intervals:
            for i0, i1 in intervals:
                seg_pts = dense[i0:i1 + 2]
                if len(seg_pts) >= 2:
                    features.append({
                        'type': 'Feature',
                        'geometry': {'type': 'LineString',
                                     'coordinates': [list(p) for p in seg_pts]},
                        'properties': {'way': wid, 'name': name, 'kind': kind,
                                       'rise_m': float(np.nanmax(elev[i0:i1 + 1])
                                                       - elev[max(0, i0 - 1)])}})

    rows.sort(key=lambda r: r['irred'], reverse=True)
    backwards.sort(key=lambda r: r['ascent'], reverse=True)

    print(f'\n  {len(rows)} ways disagree with the ground in both directions; '
          f'{len(backwards)} would be largely fixed by reversing\n')
    print(f'  {"irred":>8} {"ascent":>8} {"descent":>8} {"runs":>5} '
          f'{"len_m":>9} {"fix_m":>7}  {"kind":<7} name / id')
    for r in rows[:args.top]:
        print(f'  {r["irred"]:8.1f} {r["ascent"]:8.1f} {r["descent"]:8.1f} '
              f'{r["runs"]:5d} {r["length"]:9.0f} {r["moved"]:7.1f}  '
              f'{r["kind"]:<7} {r["name"] or "(unnamed)"} [{r["id"]}]')
    if backwards:
        print('\n  probably drawn backwards (ascends overall):')
        for r in backwards[:10]:
            print(f'  {r["ascent"]:8.1f} {"":8} {"":5} {r["length"]:9.0f} '
                  f'{"":7}  {r["kind"]:<7} {r["name"] or "(unnamed)"} [{r["id"]}]')

    tot_bad = sum(r['bad_m'] for r in rows)
    tot_len = sum(r['length'] for r in rows) or 1
    tot_irr = sum(r['irred'] for r in rows)
    print(f'\n  total ascending length {tot_bad/1000:.1f} km of '
          f'{tot_len/1000:.1f} km on affected ways ({100*tot_bad/tot_len:.1f}%)')
    print(f'  irreducible ascent, summed: {tot_irr:.0f} m across {len(rows)} ways')

    if args.geojson:
        import json
        with open(args.geojson, 'w') as fh:
            json.dump({'type': 'FeatureCollection', 'features': features}, fh)
        print(f'  wrote {len(features)} runs to {args.geojson}')


if __name__ == '__main__':
    main()
