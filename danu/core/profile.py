"""Pure geometry and grading, with no GDAL and no network.

These are the functions which decide what a contour means: how a way is
densified, how long its segments are, where a river climbs, and what elevation
a waterway takes between the contours it crosses. They are separated from the
modules which read and write rasters so they can be imported, and tested,
without GDAL - which is what lets the test suite run on Windows, where GDAL is
not reasonably installable from PyPI.

`densify` and the segment lengths existed twice, once in `danu.checks.rivers`
and once in `danu.water.constraints`, with different names and different
spellings of the same arithmetic. They were checked against each other over
three hundred random ways before being merged: the coordinates agreed to 4e-14
and the lengths exactly.
"""

import math

import numpy as np

M_PER_DEG = 111320.0
# a graded segment longer than this crosses too much unseen ground to trust
MAX_SEGMENT_M = 5000.0


def densify(pts, step):
    """Insert points so no gap exceeds `step` degrees, keeping the drawn order."""
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out.extend((x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k)
                   for i in range(1, k + 1))
    return out


def seg_lengths(pts):
    """Length in metres of each step along a way."""
    lat = np.radians([p[1] for p in pts[:-1]])
    dx = np.diff([p[0] for p in pts]) * M_PER_DEG * np.cos(lat)
    dy = np.diff([p[1] for p in pts]) * M_PER_DEG
    return np.hypot(dx, dy)


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


def grade(values, seg_m):
    """Contour values where a way crosses one, graded between, descending only.
    OGF::Terrain::RiverProfile::setLinearElev, applied to a whole way."""
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
