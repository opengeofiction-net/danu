"""What a grade leaves: a river level a contour beside it contradicts - G7c.

The grade (G6b) gives a river the level of each contour where it crosses
one and grades between; the burn (G7b) mends the spans where the contours
climb. What neither sees is a contour that runs beside the river without
crossing it, at a level the river is nowhere near: on gobras the Merta River
runs 2 to 4 m from a contour 37 to 48 m above its graded level, and the Semes
touches one 29 m below. The surface has to put both in one or two cells - a
cliff the mapper did not draw, or a river perched above the ground beside it.

Found where a contour comes within one cell of the river - ``CELL_M``, the
build's 1 arcsecond - at a level more than ``LIMIT_M`` from the river's
there, more than a contour step either way. A cell away a contour a step
above or below is a steep bank, and there are dozens; more than a step is a
fault in the contour or the level, and on cleaned gobras there are 14
places. Each is one stretch of river and one contour, said with the
worst of it, for the mapper to move the contour or fix the level.

No Qt and no GDAL: metres on the burn's projection about the river.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import burn

# the server's build, 1 arcsecond, whatever the editor's own surface is set to:
# the server's is the surface that is published
CELL_M = 30.0
LIMIT_M = 25.0
STEP_M = 5.0                    # along the river between samples


@dataclass(frozen=True)
class Contradiction:
    d0: float                   # metres along the river, the stretch
    d1: float
    contour: tuple              # (square name, way id)
    ele: float                  # the contour's level
    level: float                # the river's, where it is worst
    apart_m: float              # how near the contour comes along the stretch
    lon: float                  # where it is worst, on the river
    lat: float

    @property
    def diff(self) -> float:
        """The contour's level less the river's: positive, a contour above."""
        return self.ele - self.level


@dataclass
class Contours:
    """Every contour of a set, read once for a network's stems rather than
    once a stem: keys, levels, lon/lat points, and their boxes stacked, so a
    stem's are picked out at once."""
    keys: list
    eles: list
    pts: list
    boxes: np.ndarray            # (n, 4): lon, lat low, lon, lat high


def gather(working_set) -> Contours:
    keys, eles, pts, boxes = [], [], [], []
    for sq in working_set.squares.values():
        for way in sq.contours():
            # a square holds every node of its ways; one that does not is broken
            # and skipped, as the burn and the crossings check skip it
            run = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs if r in sq.nodes]
            if len(run) == len(way.refs) and len(run) >= 2:
                run = np.asarray(run)
                keys.append((sq.name, way.id))
                eles.append(float(way.ele))
                pts.append(run)
                boxes.append((*run.min(0), *run.max(0)))
    return Contours(keys, eles, pts, np.asarray(boxes).reshape(-1, 4))


def find(working_set, river: list, dist: list, levels: list, contours: Contours | None = None,
         cell_m: float = CELL_M, limit_m: float = LIMIT_M) -> list[Contradiction]:
    """Along ``river`` - (lon, lat) points, each ``dist`` metres along it and
    graded to ``levels`` (None where it is not) - every stretch where a
    contour within ``cell_m`` is more than ``limit_m`` from the river's
    level. Only between two graded vertices: an ungraded span says why
    already. ``contours`` is what ``gather`` gives, read once by a caller
    with many rivers."""
    if len(river) < 2:
        return []
    proj = burn._Projection(float(np.mean([lat for _, lat in river])))
    R = proj.to(river)
    d = np.asarray(dist, dtype=float)
    lv = np.array([np.nan if v is None else float(v) for v in levels])
    samples = np.arange(float(d[0]), float(d[-1]) + 1e-9, STEP_M)      # from where the river starts
    i = np.clip(np.searchsorted(d, samples, side='right') - 1, 0, len(d) - 2)
    graded = ~np.isnan(lv[i]) & ~np.isnan(lv[i + 1])
    if not graded.any():
        return []
    samples, i = samples[graded], i[graded]
    span = np.maximum(d[i + 1] - d[i], 1e-9)
    t = np.clip((samples - d[i]) / span, 0.0, 1.0)
    h = lv[i] + (lv[i + 1] - lv[i]) * t
    # the sample's place: the same fraction along the river's own segment -
    # ``dist`` runs across the gaps a chain was walked over, its points do not
    P = R[i] + (R[i + 1] - R[i]) * t[:, None]
    out = []
    lo, hi = P.min(0) - cell_m, P.max(0) + cell_m
    lo_ll, hi_ll = np.array(proj.back(lo)), np.array(proj.back(hi))
    held = gather(working_set) if contours is None else contours
    box = held.boxes
    meet = np.flatnonzero(((box[:, 2:] >= lo_ll) & (box[:, :2] <= hi_ll)).all(1))
    # the samples by x, so a contour's are found by halves and not by
    # looking at every one of a long river's thousands
    order = np.argsort(P[:, 0], kind='stable')
    xs = P[order, 0]
    for n in meet:
        key, ele = held.keys[n], held.eles[n]
        C = proj.to(held.pts[n])
        lo_c, hi_c = C.min(0) - cell_m, C.max(0) + cell_m
        cand = order[np.searchsorted(xs, lo_c[0]):np.searchsorted(xs, hi_c[0], side='right')]
        cand = cand[(P[cand, 1] >= lo_c[1]) & (P[cand, 1] <= hi_c[1])]
        if not len(cand):
            continue
        apart = _within(C, P, cell_m, cand)
        diff = ele - h
        bad = (apart < cell_m) & (np.abs(diff) > limit_m)
        if not bad.any():
            continue
        # each run of samples one stretch, said with its worst
        k = np.flatnonzero(bad)
        breaks = np.flatnonzero(np.diff(k) > 1)
        for run in np.split(k, breaks + 1):
            # the most apart in level, and of those, the nearest
            worst = run[np.lexsort((apart[run], -np.round(np.abs(diff[run]), 1)))[0]]
            lon, lat = proj.back(P[worst])
            out.append(Contradiction(float(samples[run[0]]), float(samples[run[-1]]), key, ele,
                                     round(float(h[worst]), 1), float(apart[run].min()), lon, lat))
    out.sort(key=lambda c: c.d0)
    return out


def _within(C, P, cell_m, k) -> np.ndarray:
    """Each sample's distance from a contour, where it is within ``cell_m``
    of it, and infinity where not - of the samples ``k`` in reach of its box.
    Only the pairs whose boxes come within a cell are measured: a contour
    wrapping a valley has a box over most of a river, and measuring every
    sample against every segment was 150 s for a network of 211 stems."""
    out = np.full(len(P), np.inf)
    a, b = C[:-1], C[1:]
    lo, hi = np.minimum(a, b) - cell_m, np.maximum(a, b) + cell_m
    q = P[k]
    segs = np.flatnonzero(((hi >= q.min(0)) & (lo <= q.max(0))).all(1))
    if not len(segs):
        return out
    # in chunks of samples - ``k`` comes in order of x, so a chunk is a strip
    # and only the segments reaching it are paired with it
    for start in range(0, len(k), 64):
        kk = k[start:start + 64]
        q = P[kk]
        sj = segs[((hi[segs] >= q.min(0)) & (lo[segs] <= q.max(0))).all(1)]
        if not len(sj):
            continue
        inbox = ((q[:, None] >= lo[sj][None]) & (q[:, None] <= hi[sj][None])).all(2)
        pi, pj = np.nonzero(inbox)
        if not len(pi):
            continue
        s_, j = kk[pi], sj[pj]
        ab = b[j] - a[j]
        t = np.clip(((P[s_] - a[j]) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0.0, 1.0)
        d = np.hypot(*(a[j] + ab * t[:, None] - P[s_]).T)
        np.minimum.at(out, s_, d)
    return out
