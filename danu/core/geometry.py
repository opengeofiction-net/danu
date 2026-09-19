"""Plane geometry over many segments at once - R16's crossing test.

Contours at one elevation may not cross each other, and a contour may not
cross one of a different elevation at all. The editor asks this of every
segment it is about to draw against every segment in the working set, on
each mouse move, so it is one vectorised orientation test in numpy rather
than a loop. Coordinates are whatever the caller projects to - the editor
uses scene units - and the answer is which segments are crossed.

Touching is not crossing: a continuation snapped onto an existing node of a
contour at the same elevation shares that node, and so does a way that
closes on itself. A shared endpoint is allowed at the same elevation and
reported at a different one, where R16 forbids even a touch.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-9


def _orient(a, b, p):
    """Sign of the turn a -> b -> p, for one a, b and many p (or all many)."""
    return (b[..., 0] - a[..., 0]) * (p[..., 1] - a[..., 1]) - (b[..., 1] - a[..., 1]) * (p[..., 0] - a[..., 0])


def crossings(p, q, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Which of the segments a[i]-b[i] the segment p-q properly crosses:
    the interiors meet at one point. A boolean mask over i. Segments that
    only touch at an endpoint, or lie along each other, are not crossings
    here; ``touches`` reports those."""
    if not len(a):
        return np.zeros(0, dtype=bool)
    p = np.asarray(p, dtype=float); q = np.asarray(q, dtype=float)
    d1 = _orient(a, b, p)
    d2 = _orient(a, b, q)
    d3 = _orient(p[None, :], q[None, :], a)
    d4 = _orient(p[None, :], q[None, :], b)
    return ((d1 > EPS) & (d2 < -EPS) | (d1 < -EPS) & (d2 > EPS)) & \
           ((d3 > EPS) & (d4 < -EPS) | (d3 < -EPS) & (d4 > EPS))


def touches(p, q, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Which segments p-q meets without properly crossing: an endpoint of
    one lies on the other (a shared node, a T-junction), or they overlap
    along a stretch."""
    if not len(a):
        return np.zeros(0, dtype=bool)
    p = np.asarray(p, dtype=float); q = np.asarray(q, dtype=float)
    d1 = _orient(a, b, p); d2 = _orient(a, b, q)
    d3 = _orient(p[None, :], q[None, :], a); d4 = _orient(p[None, :], q[None, :], b)

    def on(seg_a, seg_b, pt, d):
        # collinear and within the segment's box
        lo = np.minimum(seg_a, seg_b) - EPS
        hi = np.maximum(seg_a, seg_b) + EPS
        return (np.abs(d) <= EPS) & np.all((pt >= lo) & (pt <= hi), axis=-1)

    return on(a, b, p[None, :], d1) | on(a, b, q[None, :], d2) | \
        on(p[None, :], q[None, :], a, d3) | on(p[None, :], q[None, :], b, d4)


def nearest_point_on_segments(pt, a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For one point and many segments: the parameter t along each and the
    distance to the nearest point of each."""
    pt = np.asarray(pt, dtype=float)
    d = b - a
    length2 = np.einsum('ij,ij->i', d, d)
    t = np.clip(np.einsum('ij,ij->i', pt - a, d) / np.where(length2 > 0, length2, 1.0), 0.0, 1.0)
    nearest = a + t[:, None] * d
    return t, np.hypot(*(pt - nearest).T)
