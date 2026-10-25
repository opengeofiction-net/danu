"""Contours an import has doubled: a negative way - drawn here, or recovered -
lying wholly on top of a positive one at its level, the main map's own way,
which an import of water or coastline has just brought in - or on a ring of
a water relation at the relation's level.

Recovered squares carry their own copies of the coastline and the lakes'
shores, negative ways tagged like the real ones; the import then lays the
main map's way over each, and the touches check lists every pair as a
duplicate - 151 in roantra's N45E026, each the whole of a negative way on a
coastline. The main map's way is the one kept: it is what an upload
reconciles against, and its direction is the sea's.

Only a way every node of which is within ``NEAR_M`` of a positive way at its
level goes; one doubled in part is left to the Validation panel, as is one a
relation names. No Qt and no GDAL.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from . import edits
from .ladder import format_ele
from .square import parse_ele, water_tags

NEAR_M = 1.0
FILL = 'danu:fill'          # a flattened lake's fill line - water.flatten.FILL


def _metres(lat: float) -> np.ndarray:
    return np.array([111320.0 * math.cos(math.radians(lat)), 110540.0])


def commands(working_set) -> list:
    """The step that deletes every negative way wholly on top of a positive
    one at its level, across the set and the squares read alongside it:
    (square, Compound) a square.

    And a negative way with a level wholly on the rings - those the square
    holds - of exactly one water relation with none - the sea, r470432,
    imported in N46E030 with no level, and 254
    recovered copies of its shore at 0 m lying on it, which matched nothing
    and stood between a click and the sea. The copies go, and the relation
    and its rings take the level they held: the shore stays at 0 m, and is
    the sea's. Only where every copy on the relation says the same level."""
    squares = [*working_set.squares.values(), *getattr(working_set, 'extra', {}).values()]
    if not squares:
        return []
    k = _metres(sum(sq.name.lat + 0.5 for sq in squares) / len(squares))
    # the positive ways' segments, by level, in metres. A ring of a water
    # relation is at the relation's level when it carries none of its own:
    # roantra's estuary, relation 470435, has ele=0 on the relation and on 5
    # of its 248 rings, and its islands' recovered copies were left doubled
    segs: dict = defaultdict(list)
    unlevelled: dict = {}                  # (square name, relation id): its rings' (lo, hi, A, B)
    for sq in squares:
        ringed = {}
        for rel in sq.relations.values():
            if not water_tags(rel.tags):
                continue
            e = parse_ele(rel.tags.get('ele'))
            refs = [m.ref for m in rel.members if m.type == 'way']
            if e is not None:
                ringed.update({r: e for r in refs})
                continue
            rings = [_metres_of(sq.ways[r], sq, k) for r in refs if r in sq.ways and r > 0]
            rings = [P for P in rings if P is not None]
            if rings:
                A = np.concatenate([P[:-1] for P in rings])
                B = np.concatenate([P[1:] for P in rings])
                unlevelled[(sq.name, rel.id)] = (np.minimum(A, B).min(axis=0), np.maximum(A, B).max(axis=0),
                                                 _Segments(A, B))
        for w in sq.ways.values():
            e = w.ele if w.ele is not None else ringed.get(w.id)
            P = _metres_of(w, sq, k) if w.id > 0 and e is not None else None
            if P is not None:
                segs[e].append((P[:-1], P[1:]))
    level = {e: _Segments(np.concatenate([a for a, _ in s]), np.concatenate([b for _, b in s]))
             for e, s in segs.items()}
    # a square is read alongside only when the set has none of that name
    by_name = {sq.name: sq for sq in squares}
    gone: dict = defaultdict(list)          # square: [DeleteWay]
    given: dict = defaultdict(set)          # relation: the levels the copies on it carry
    on_rel: dict = defaultdict(list)        # relation: (square, copy's id)
    for sq in squares:
        named = {m.ref for r in sq.relations.values() for m in r.members if m.type == 'way'}
        for w in list(sq.ways.values()):
            if w.id > 0 or w.ele is None or w.id in named or FILL in w.tags:
                continue
            P = _metres_of(w, sq, k)
            if P is None:
                continue
            if w.ele in level and level[w.ele].under(P):
                gone[sq.name].append(edits.DeleteWay(w.id))
                continue
            lo, hi = P.min(axis=0), P.max(axis=0)
            under = [key for key, (rlo, rhi, segs_of) in unlevelled.items()
                     if (lo >= rlo - NEAR_M).all() and (hi <= rhi + NEAR_M).all() and segs_of.under(P)]
            if len(under) == 1:
                given[under[0]].add(w.ele)
                on_rel[under[0]].append((sq.name, w.id))
    levels: dict = defaultdict(list)
    for (name, rid), eles in given.items():
        if len(eles) != 1:
            continue                       # copies that disagree: the mapper's to say
        text = format_ele(next(iter(eles)))
        sq = by_name[name]
        rel = sq.relations[rid]
        levels[name].append(edits.SetRelationTags(rid, dict(rel.tags), {**rel.tags, 'ele': text}))
        for m in rel.members:
            ring = sq.ways.get(m.ref) if m.type == 'way' else None
            if ring is not None and ring.tags.get('ele') != text:
                levels[name].append(edits.SetTags(ring.id, dict(ring.tags), {**ring.tags, 'ele': text}))
        for cname, cid in on_rel[(name, rid)]:
            gone[cname].append(edits.DeleteWay(cid))
    out = []
    for name in sorted(set(gone) | set(levels), key=str):
        cmds = [*levels.get(name, []), *gone.get(name, [])]
        n = len(gone.get(name, []))
        what = (f'remove {n} doubled contour{"s" * (n != 1)}' if n else
                'level water from its recovered shore')          # its copies in another square
        out.append((by_name[name], edits.Compound(cmds, name=what)))
    return out


class _Segments:
    """Segments in metres, indexed by cell: a way is measured only against
    those near it. The 0 m level holds every coastline and ring of the set,
    and asking all of them of each of its 13,000 contours held the window
    for most of a minute after an import."""

    CELL_M = 1000.0

    def __init__(self, A, B):
        self.A, self.B = A, B
        lo = np.floor(np.minimum(A, B) / self.CELL_M).astype(np.int64)
        hi = np.floor(np.maximum(A, B) / self.CELL_M).astype(np.int64)
        cells = defaultdict(list)
        for i, ((x0, y0), (x1, y1)) in enumerate(zip(lo, hi, strict=True)):
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    cells[(cx, cy)].append(i)
        self.cells = {c: np.array(v) for c, v in cells.items()}

    def under(self, P) -> bool:
        """Whether every point of P is within NEAR_M of one of these."""
        lo = np.floor((P.min(axis=0) - NEAR_M) / self.CELL_M).astype(np.int64)
        hi = np.floor((P.max(axis=0) + NEAR_M) / self.CELL_M).astype(np.int64)
        near = [self.cells[(cx, cy)] for cx in range(lo[0], hi[0] + 1) for cy in range(lo[1], hi[1] + 1)
                if (cx, cy) in self.cells]
        if not near:
            return False
        idx = np.unique(np.concatenate(near))
        return _on(P, self.A[idx], self.B[idx])


def _metres_of(way, sq, k):
    """A way's points in metres, or None when it is not whole."""
    if len(way.refs) < 2 or any(r not in sq.nodes for r in way.refs):
        return None
    return np.array([(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs]) * k


def _on(P, A, B) -> bool:
    """Whether every point of P is within NEAR_M of a segment AB."""
    lo, hi = P.min(axis=0) - NEAR_M, P.max(axis=0) + NEAR_M
    keep = ~((np.maximum(A, B) < lo).any(axis=1) | (np.minimum(A, B) > hi).any(axis=1))
    if not keep.any():
        return False
    A, B = A[keep], B[keep]
    D = B - A
    L = (D * D).sum(axis=1)
    L[L == 0] = 1.0
    for p in P:
        t = np.clip(((p - A) * D).sum(axis=1) / L, 0.0, 1.0)
        if (np.hypot(*(A + t[:, None] * D - p).T) > NEAR_M).all():
            return False
    return True
