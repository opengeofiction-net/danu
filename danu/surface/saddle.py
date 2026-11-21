"""A saddle read as a saddle - #191, from #370.

A spot height is a point, and a point can only ever be a peak or a pit: the
fill takes it for the top or the bottom of the ground round it. A saddle is
neither. It is the top of a pass and the bottom of a ridge, and burned as a
point it came out as a one-cell pit in a hump - castellan's 504 m saddle
between two 500 m contours, the pass reading 500, 516, 500 without it and 504,
511, 505, 507, 500 with it.

So a saddle is read from the contours round it. Rays from it meet the nearest
contour in each direction; the directions whose contour is lower than the
saddle are the pass, falling away on two opposite sides, and those whose
contour is higher are the ridge, rising on the other two. Two short lines are
burned as constraints, the pass: each from the saddle at its height down to
the nearest contour of its sector, at that contour's level. The saddle is
then the top of the pass; it is the bottom of the ridge already, as a point.

Lines up the ridge as well were tried, on castellan's eight saddles that read
as saddles, and left out. They fixed nothing the pass lines had not - the 504 m
saddle's pass reads 500, 502, 503, 504, 503, 502, 500 either way - and drew a
crease down each ridge, and moved the ground up to 61 m against the pass lines'
15. A fan of lines along every ray was worse again: flat facets and wedges.

A saddle the contours round it do not show as one - not two sectors down and
two up, or too few rays meeting a contour - is left a spot height, as it was.

No Qt and no GDAL.
"""

from __future__ import annotations

import math

import numpy as np

RAYS = 72                    # five degrees apart
# nothing to look for in a square that never says it: collect's byte guard
WORDS = (b"'saddle'", b'"saddle"')
RANGE_M = 3000.0             # how far a ray looks for a contour, as the R38 check does
LEAST_RAYS = 48              # meeting fewer, the ground round it is too little described to read


def hits(segments, lon: float, lat: float, rays: int = RAYS, range_m: float = RANGE_M) -> list:
    """The first contour each ray from a point meets, as (level, metres,
    lon, lat) - None for a ray that meets none within ``range_m``.
    ``segments`` is ``(A, B, L)``: segment starts and ends as lon/lat arrays
    and each one's level, as ``checks.spots._Segments.arrays`` gives them."""
    A, B, L = segments
    out: list = [None] * rays
    if not len(L):
        return out
    k = 111320 * math.cos(math.radians(lat))
    ax, ay = (A[:, 0] - lon) * k, (A[:, 1] - lat) * 110540
    bx, by = (B[:, 0] - lon) * k, (B[:, 1] - lat) * 110540
    ex, ey = bx - ax, by - ay
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.clip(np.nan_to_num(-(ax * ex + ay * ey) / (ex * ex + ey * ey)), 0.0, 1.0)
    near = np.hypot(ax + t * ex, ay + t * ey) <= range_m
    ax, ay, ex, ey, lv = ax[near], ay[near], ex[near], ey[near], L[near]
    for i in range(rays):
        th = 2 * math.pi * i / rays
        dx, dy = math.cos(th), math.sin(th)
        den = dx * ey - dy * ex
        with np.errstate(divide='ignore', invalid='ignore'):
            along = (ax * ey - ay * ex) / den
            on = (ax * dy - ay * dx) / den
        hit = (den != 0) & (along > 0) & (along <= range_m) & (on >= 0) & (on <= 1)
        if hit.any():
            j = np.flatnonzero(hit)[np.argmin(along[hit])]
            d = float(along[j])
            out[i] = (float(lv[j]), d, lon + d * dx / k, lat + d * dy / 110540)
    return out


def _sectors(signs: list) -> list[tuple[int, list[int]]]:
    """Runs of equal sign round the circle, as (sign, ray indices); rays that
    met nothing (sign 0) break a run but belong to none."""
    n = len(signs)
    start = next((i for i in range(n) if signs[i] != signs[i - 1]), None)
    if start is None:
        return [(signs[0], list(range(n)))] if signs[0] else []
    out: list = []
    run: list[int] = []
    for k in range(n):
        i = (start + k) % n
        if run and signs[i] != signs[run[0]]:
            out.append((signs[run[0]], run))
            run = []
        run.append(i)
    if run:
        out.append((signs[run[0]], run))
    return [(s, r) for s, r in out if s]


def lines(segments, lon: float, lat: float, ele: float) -> list | None:
    """The saddle's pass, as two ((lon, lat, ele), (lon, lat, level)) lines
    from the saddle to the nearest contour of each of its two sectors down -
    or None where the contours round it do not show a saddle: two sectors
    down and two up."""
    got = hits(segments, lon, lat)
    if sum(h is not None for h in got) < LEAST_RAYS:
        return None
    signs = [0 if h is None else (-1 if h[0] < ele else 1 if h[0] > ele else 0) for h in got]
    sectors = _sectors(signs)
    downs = [r for s, r in sectors if s < 0]
    ups = [r for s, r in sectors if s > 0]
    if len(downs) != 2 or len(ups) != 2:
        return None
    out = []
    for run in downs:
        level, _d, x, y = min((got[i] for i in run), key=lambda h: h[1])
        out.append(((lon, lat, ele), (x, y, level)))
    return out


def is_saddle(node) -> bool:
    """Whether a node is tagged a saddle."""
    return node.tags.get('natural') == 'saddle'


def features(defn, lines_, node_id, square=None) -> list:
    """A saddle's pass as features of the ``saddle`` layer, each line with
    its heights for Z. The build's layer and the preview's are made of these
    alike."""
    from osgeo import ogr
    out = []
    for a, b in lines_:
        g = ogr.Geometry(ogr.wkbLineString25D)
        g.AddPoint(float(a[0]), float(a[1]), float(a[2]))
        g.AddPoint(float(b[0]), float(b[1]), float(b[2]))
        f = ogr.Feature(defn)
        f.SetGeometry(g)
        f.SetField('osm_id', str(node_id))
        if square is not None and defn.GetFieldIndex('square') >= 0:
            f.SetField('square', square)
        out.append(f)
    return out
