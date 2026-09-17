#!/usr/bin/env python3
#
# Report a zone's elevation distribution, against the previous build - see
# Admin:Elevation process
#
#   demZoneStats.py <dem.tif> <stats-file> [--quiet]
#
# Exists because the errors this pipeline actually produces are invisible to an
# aggregate error figure. Three separate faults in the land and sea handling of
# zone-roantra each moved its RMS against the published DEM by under 0.1 m,
# while one of them turned every low lying coastal peninsula into ocean and
# another turned two thirds of the ocean into land. All three were obvious in
# one line of distribution:
#
#   land at 1..9 m     2.86% expected, 0.37% built    coastal land missing
#   land at 1..9 m     2.86% expected, 67.41% built   the sea clamped to land
#
# So each build records its distribution and compares against the last one for
# the same zone. A zone's terrain does not change much between builds, so a
# large shift means the pipeline changed, not the map.

import argparse
import json
import os
import sys

from osgeo import gdal

gdal.UseExceptions()

# How far a share may move between builds of one zone before it is called out.
# Percentage points, absolute - a zone gaining a few squares moves these a
# little, so the thresholds are loose enough not to cry wolf over real edits
TOLERANCE = {
    'sea': 5.0,
    'low_land': 2.0,
    'land': 5.0,
}


def measure(path):
    """A strip at a time. A zone whose squares come in separated clusters covers
    a mostly empty bounding box - zone-axian is 2.1 gigapixels - and reading that
    whole is gigabytes for a handful of counts."""
    ds = gdal.Open(path)
    band = ds.GetRasterBand(1)
    cols, rows = ds.RasterXSize, ds.RasterYSize
    step = max(1, min(rows, (64 << 20) // max(cols * 2, 1)))

    total = rows * cols
    n_sea = n_low = n_land = n_neg = 0
    lo, hi, acc = None, None, 0.0
    for y in range(0, rows, step):
        h = min(step, rows - y)
        a = band.ReadAsArray(0, y, cols, h)
        n_sea += int((a == 0).sum())
        n_low += int(((a > 0) & (a < 10)).sum())
        n_land += int((a > 0).sum())
        n_neg += int((a < 0).sum())
        amin, amax = int(a.min()), int(a.max())
        lo = amin if lo is None else min(lo, amin)
        hi = amax if hi is None else max(hi, amax)
        acc += float(a.sum())

    return {
        'width': cols,
        'height': rows,
        'sea': 100 * n_sea / total,
        'low_land': 100 * n_low / total,
        'land': 100 * n_land / total,
        'min': lo,
        'max': hi,
        'mean': acc / total,
        # a DEM should hold no negative elevations unless the zone maps a
        # depression, and none of ours do, so below zero is a fault not terrain
        'below_zero': 100 * n_neg / total,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dem')
    ap.add_argument('stats')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    now = measure(args.dem)
    was = None
    if os.path.exists(args.stats):
        try:
            was = json.load(open(args.stats))
        except (ValueError, OSError):
            was = None

    rows = [('size', f"{now['width']}x{now['height']}", ''),
            ('sea', f"{now['sea']:.2f}%", f"{was['sea']:.2f}%" if was else '-'),
            ('land 1..9 m', f"{now['low_land']:.2f}%",
             f"{was['low_land']:.2f}%" if was else '-'),
            ('land', f"{now['land']:.2f}%", f"{was['land']:.2f}%" if was else '-'),
            ('min..max', f"{now['min']}..{now['max']} m",
             f"{was['min']}..{was['max']} m" if was else '-'),
            ('mean', f"{now['mean']:.1f} m",
             f"{was['mean']:.1f} m" if was else '-')]
    if not args.quiet:
        print(f"  {'':14} {'this build':>14}  {'previous':>14}")
        for name, a, b in rows:
            print(f'  {name:14} {a:>14}  {b:>14}')

    warnings = []
    if now['below_zero'] > 0:
        warnings.append(f"{now['below_zero']:.2f}% of the zone is below sea "
                        f"level, which no OGF zone maps")
    if was:
        for key, limit in TOLERANCE.items():
            shift = now[key] - was[key]
            if abs(shift) > limit:
                warnings.append(f'{key} moved {shift:+.2f} points, over the '
                                f'{limit:.0f} point tolerance')
        if (was['width'], was['height']) != (now['width'], now['height']):
            warnings.append(f"grid changed from {was['width']}x{was['height']} "
                            f"to {now['width']}x{now['height']}")

    os.makedirs(os.path.dirname(os.path.abspath(args.stats)), exist_ok=True)
    with open(args.stats, 'w') as f:
        json.dump(now, f, indent=1, sort_keys=True)

    for w in warnings:
        print(f'  WARNING: {w}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
