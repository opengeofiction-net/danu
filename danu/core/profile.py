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

import bisect
import math
from itertools import pairwise

import numpy as np

M_PER_DEG = 111320.0
# a graded segment longer than this crosses too much unseen ground to trust
MAX_SEGMENT_M = 5000.0


def densify(pts, step):
    """Insert points so no gap exceeds `step` degrees, keeping the drawn order."""
    out = [pts[0]]
    for (x0, y0), (x1, y1) in pairwise(pts):
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
    for a, b in pairwise(known):
        ea, eb = values[a], values[b]
        if eb > ea or sum(seg_m[a:b]) > MAX_SEGMENT_M:
            rejected += 1
            continue
        for i in range(a, b + 1):
            out[i] = ea + (eb - ea) * ((i - a) / (b - a) if b > a else 0.0)
    return out, rejected


def grade_along(known, vertex_d):
    """A waterway's level at each vertex, from the contour values where it
    crosses one - ``grade``'s rule over distance rather than index, for the
    editor (G6b).

    ``known`` is ``(d, elevation)`` for each crossing, ``d`` in metres along
    the way as drawn; ``vertex_d`` the same for each vertex. Between two
    crossings a vertex takes the value interpolated by distance. A span that
    climbs going downstream, or runs further than ``MAX_SEGMENT_M``, is left
    ungraded and reported, as ``grade`` leaves it - not forced down, which
    would invent ground nobody drew. Before the first crossing and after the
    last there is nothing to grade from.

    **Downstream is found, not assumed.** A way's direction carries no meaning
    for anything else in Danu, and mappers draw rivers either way round; the
    batch grader's `danu.checks.rivers` allows for exactly that. Water
    descends, so the end at the higher crossing is upstream: the spans are
    judged walking from it. The way is never reversed - only its levels are
    written.

    Answers (levels, rejected, reversed): a level or None per vertex, the
    rejected spans as (d0, d1, e0, e1) in drawn order, and whether downstream
    runs against the drawn direction.
    """
    known = sorted(known)
    levels = [None] * len(vertex_d)
    if len(known) < 2:
        return levels, [], False
    reversed_ = known[0][1] < known[-1][1]
    walk = list(reversed(known)) if reversed_ else known
    rejected = []
    order = sorted(range(len(vertex_d)), key=lambda i: vertex_d[i])
    ds = [vertex_d[i] for i in order]
    for (da, ea), (db, eb) in pairwise(walk):
        lo, hi = min(da, db), max(da, db)
        if eb > ea or hi - lo > MAX_SEGMENT_M:
            rejected.append((lo, hi, ea, eb) if not reversed_ else (lo, hi, eb, ea))
            continue
        for k in range(bisect.bisect_left(ds, lo), bisect.bisect_right(ds, hi)):
            d = ds[k]
            f = (d - da) / (db - da) if db != da else 0.0
            levels[order[k]] = ea + (eb - ea) * f
    rejected.sort()
    return levels, rejected, reversed_
