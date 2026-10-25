"""Contours an import has doubled: a negative way - drawn here, or recovered -
lying wholly on top of a positive one at its level, the main map's own way,
which an import of water or coastline has just brought in - or on a ring of
a water relation at the relation's level.

Or on a bare one: a water relation held in a square outside the set - the
sea, r470432, anchored far to the south-west of roantra's N46E030 - is not
imported, and its member ways come in alone, with no tags and no level, under
the recovered copies of them. The copy goes, and its level goes onto the
main map's way, which then holds the ground as the copy did - where every
copy on it says the same level.

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
from .square import parse_ele, water_tags

NEAR_M = 1.0
FILL = 'danu:fill'          # a flattened lake's fill line - water.flatten.FILL


def _metres(lat: float) -> np.ndarray:
    return np.array([111320.0 * math.cos(math.radians(lat)), 110540.0])


def commands(working_set) -> list:
    """The step that deletes every negative way wholly on top of a positive
    one at its level, across the set: (square, Compound) a square."""
    squares = list(working_set.squares.values())
    if not squares:
        return []
    by_name = {sq.name: sq for sq in squares}
    k = _metres(sum(sq.name.lat + 0.5 for sq in squares) / len(squares))
    # the positive ways' segments, by level, in metres. A ring of a water
    # relation is at the relation's level when it carries none of its own:
    # roantra's estuary, relation 470435, has ele=0 on the relation and on 5
    # of its 248 rings, and its islands' recovered copies were left doubled
    segs: dict = defaultdict(list)
    for sq in squares:
        ringed = {}
        for rel in sq.relations.values():
            e = parse_ele(rel.tags.get('ele'))
            if e is not None and water_tags(rel.tags):
                ringed.update({m.ref: e for m in rel.members if m.type == 'way'})
        for w in sq.ways.values():
            e = w.ele if w.ele is not None else ringed.get(w.id)
            if w.id > 0 and e is not None and len(w.refs) >= 2 and all(r in sq.nodes for r in w.refs):
                P = np.array([(sq.nodes[r].lon, sq.nodes[r].lat) for r in w.refs]) * k
                segs[e].append((P[:-1], P[1:]))
    level = {e: (np.concatenate([a for a, _ in s]), np.concatenate([b for _, b in s])) for e, s in segs.items()}
    bare = _bare(squares, k)
    gone: dict = defaultdict(list)          # square: [DeleteWay]
    given: dict = defaultdict(set)          # (square, positive way id): the levels the copies on it carry
    on_bare: dict = defaultdict(list)       # (square, positive way id): (square, copy's id)
    for sq in squares:
        named = {m.ref for r in sq.relations.values() for m in r.members if m.type == 'way'}
        for w in list(sq.ways.values()):
            if (w.id > 0 or w.ele is None or w.id in named or FILL in w.tags
                    or len(w.refs) < 2 or any(r not in sq.nodes for r in w.refs)):
                continue
            P = np.array([(sq.nodes[r].lon, sq.nodes[r].lat) for r in w.refs]) * k
            if w.ele in level and _on(P, *level[w.ele]):
                gone[sq.name].append(edits.DeleteWay(w.id))
                continue
            under = _under(P, bare)
            if under is not None:
                given[under].add(w.ele)
                on_bare[under].append((sq.name, w.id))
    # a bare way of the main map's under a copy with a level takes the
    # level and the copy goes - where every copy on it says the same
    level_up: dict = defaultdict(list)
    for (name, pid), eles in given.items():
        if len(eles) != 1:
            continue
        way = by_name[name].ways[pid]
        level_up[name].append(edits.SetTags(pid, dict(way.tags), {**way.tags, 'ele': _text(next(iter(eles)))}))
        for cname, cid in on_bare[(name, pid)]:
            gone[cname].append(edits.DeleteWay(cid))
    by = {sq.name: sq for sq in squares}
    out = []
    for name in sorted(set(gone) | set(level_up), key=str):
        cmds = [*level_up.get(name, []), *gone.get(name, [])]
        n = len(gone.get(name, []))
        out.append((by[name], edits.Compound(cmds, name=f'remove {n} doubled contour{"s" * (n != 1)}')))
    return out


def _text(e: float) -> str:
    return f'{e:g}'


def _bare(squares, k) -> list:
    """The main map's ways with nothing on them: a water relation's member
    imported without it - the relation held in a square outside the set -
    as (square name, way id, envelope, start points, end points)."""
    out = []
    for sq in squares:
        ringed = {m.ref for r in sq.relations.values() if water_tags(r.tags) for m in r.members}
        for w in sq.ways.values():
            if (w.id > 0 and not w.tags and w.id not in ringed and len(w.refs) >= 2
                    and all(r in sq.nodes for r in w.refs)):
                P = np.array([(sq.nodes[r].lon, sq.nodes[r].lat) for r in w.refs]) * k
                lo, hi = P.min(axis=0), P.max(axis=0)
                out.append((sq.name, w.id, (lo, hi), P[:-1], P[1:]))
    return out


def _under(P, bare):
    """The one bare way all of P lies on, as (square name, way id), or None."""
    lo, hi = P.min(axis=0), P.max(axis=0)
    for name, wid, (blo, bhi), A, B in bare:
        if (lo >= blo - NEAR_M).all() and (hi <= bhi + NEAR_M).all() and _on(P, A, B):
            return name, wid
    return None


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
