"""Burn a river into the terrain, through the contours - G7b, R25.

Where a river climbs against the contours, the grade leaves the span ungraded
(G6b). On gobras, once the rogue contours were cleaned out, 120 of the 128
one-step climbs left are one shape: **a contour that crosses the same river
twice, with lower ground between** - a ridge's finger the river cuts across
the tip of, a hill's flank it runs into and out of, a bump of a contour a
stream runs along. The contour says the ground there is above its level; the
river says it is below.

The burn makes them agree the way the river says, without throwing away what
the mapper drew: **the contour is cut at its two crossings and each piece is
closed along its own bank, set back ``d`` from the river.** A closed contour
becomes two closed contours, the river in a notch between them - the hill cut
in two. An open one becomes its main line, now running along the near bank,
and a closed piece on the far side - the tip of the finger, a knoll the river
cut off. A piece too thin to survive the setback - narrower than twice ``d`` -
would close over itself, and is dropped, and said.

Not burned, and said: a contour that crosses the river only once in the wrong
place (a spur - eight on gobras), a climb of more than one step, and a
contour with more than one pair to cut - burn again for the next.

No Qt and no GDAL: metres on a local projection about the river.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core import edits, profile
from ..core.geometry import EPS, _orient

SETBACK_M = 50.0


@dataclass
class Plan:
    """What burning would do, before it is done."""
    steps: list = field(default_factory=list)       # (square, Compound)
    removed: list = field(default_factory=list)     # what goes, as [(lon, lat)] runs
    added: list = field(default_factory=list)       # what replaces it
    dropped: list = field(default_factory=list)     # pieces too thin to keep
    burned: int = 0                                 # climbs burned
    contours_cut: int = 0                           # the contours cut to burn them
    pushed: int = 0                                 # contours near it pushed back
    skipped: list = field(default_factory=list)     # (why, lon, lat)


class _Projection:
    def __init__(self, lat0: float):
        self.k = np.array([111320.0 * math.cos(math.radians(lat0)), 110540.0])

    def to(self, lonlat) -> np.ndarray:
        return np.asarray(lonlat, dtype=float) * self.k

    def back(self, xy) -> tuple[float, float]:
        return float(xy[0] / self.k[0]), float(xy[1] / self.k[1])


def _hits(a1, b1, a2, b2):
    """Proper crossings of one set of segments with another: for each, the
    segment of each and the fraction along it."""
    d1 = _orient(a2[None, :], b2[None, :], a1[:, None])
    d2 = _orient(a2[None, :], b2[None, :], b1[:, None])
    d3 = _orient(a1[:, None], b1[:, None], a2[None, :])
    d4 = _orient(a1[:, None], b1[:, None], b2[None, :])
    hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
          (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
    ii, jj = np.nonzero(hit)
    r = b1[ii] - a1[ii]
    s = b2[jj] - a2[jj]
    w = a2[jj] - a1[ii]
    den = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
    t = (w[:, 0] * s[:, 1] - w[:, 1] * s[:, 0]) / den
    u = (w[:, 0] * r[:, 1] - w[:, 1] * r[:, 0]) / den
    return ii, jj, t, u


@dataclass(frozen=True)
class _Crossing:
    r: float                 # metres along the river
    ele: float
    key: tuple               # (square name, way id)
    s: float                 # position along the contour: vertex i + fraction


def _along(pts) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])


def _at(pts, dist, r):
    """The point ``r`` metres along a run."""
    i = int(np.clip(np.searchsorted(dist, r) - 1, 0, len(pts) - 2))
    seg = dist[i + 1] - dist[i]
    t = 0.0 if seg == 0 else (r - dist[i]) / seg
    return pts[i] + (pts[i + 1] - pts[i]) * t


def _section(pts, dist, r0, r1):
    """The river between two distances along it, its ends included."""
    lo, hi = min(r0, r1), max(r0, r1)
    inner = [p for p, d in zip(pts, dist, strict=True) if lo < d < hi]
    run = [_at(pts, dist, lo), *inner, _at(pts, dist, hi)]
    return np.asarray(run if r0 <= r1 else run[::-1])


def _offset(run, d):
    """A run moved ``d`` to its left (negative: right), by the normal at each
    vertex - the bank line the burn closes a piece along."""
    seg = np.diff(run, axis=0)
    seg /= np.maximum(np.hypot(*seg.T), 1e-9)[:, None]
    normals = np.column_stack([-seg[:, 1], seg[:, 0]])
    at = np.vstack([normals[:1], (normals[:-1] + normals[1:]) / 2, normals[-1:]])
    at /= np.maximum(np.hypot(*at.T), 1e-9)[:, None]
    return run + at * d


def _side(river, p) -> float:
    """Which side of the river a point is: positive left of its direction."""
    a, b = river[:-1], river[1:]
    ab = b - a
    t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    near = a + ab * t[:, None]
    i = int(np.argmin(np.hypot(*(near - p).T)))
    return float(_orient(a[i], b[i], p))


def _distance(run, pts) -> np.ndarray:
    """Each point's distance from a run of segments."""
    if not len(pts):
        return np.zeros(0)
    a, b = run[:-1], run[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    w = pts[:, None, :] - a[None]
    t = np.clip((w * ab[None]).sum(2) / L2[None], 0.0, 1.0)
    return np.hypot(*(a[None] + ab[None] * t[..., None] - pts[:, None, :]).transpose(2, 0, 1)).min(1)


def climbs(working_set, river: list) -> list:
    """The climbs along ``river``, each as the (lon, lat) of its middle -
    what ``only`` takes."""
    found = _crossings(working_set, river, 0.0)
    if found is None:
        return []
    _, _, _, crossings, dist = found
    if len(crossings) < 2:
        return []
    proj, R = found[0], found[1]
    _, rejected, upstream = profile.grade_along([(c.r, c.ele) for c in crossings], list(dist))
    return [proj.back(_at(R, dist, (d0 + d1) / 2)) for d0, d1, e0, e1 in rejected
            if (e0 > e1 if upstream else e1 > e0)]


def _crossings(working_set, river, margin):
    """The river in metres, the contours near it and where they cross it."""
    if len(river) < 2:
        return None
    proj = _Projection(float(np.mean([lat for _, lat in river])))
    R = proj.to(river)
    dist = _along(R)
    lo, hi = R.min(0) - 2 * margin, R.max(0) + 2 * margin
    contours, crossings = {}, []
    for sq in working_set.squares.values():
        for way in sq.contours():
            pts = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs if r in sq.nodes]
            if len(pts) != len(way.refs) or len(pts) < 2:
                continue
            P = proj.to(pts)
            if (P.max(0) < lo).any() or (P.min(0) > hi).any():
                continue
            key = (sq.name, way.id)
            contours[key] = (sq, way, P)
            here = []
            ii, jj, t, u = _hits(R[:-1], R[1:], P[:-1], P[1:])
            for i, j, tt, uu in zip(ii, jj, t, u, strict=True):
                here.append((float(dist[i] + tt * (dist[i + 1] - dist[i])), float(j + uu)))
            # and where one passes through the other's vertex - a contour
            # snapped to the river shares a node with it, which the proper
            # test does not count and the grade does
            here += _on_vertices(R, dist, P)
            seen = []
            for r, sp in sorted(here):
                if seen and abs(r - seen[-1]) < 0.01:
                    continue
                seen.append(r)
                crossings.append(_Crossing(r, float(way.ele), key, sp))
    crossings.sort(key=lambda c: c.r)
    return proj, R, contours, crossings, dist


def _on_vertices(R, dist, P, tol=1e-3):
    """Crossings at a vertex of either line: (metres along the river,
    position along the contour) for each contour vertex on the river and
    each river vertex on the contour, to a millimetre. All the vertices of
    one against all the segments of the other at once."""
    out = []
    for pts, a, b, contour_vertex in ((P, R[:-1], R[1:], True), (R, P[:-1], P[1:], False)):
        ab = b - a
        L2 = np.maximum((ab * ab).sum(1), 1e-12)
        w = pts[:, None, :] - a[None, :, :]
        t = np.clip((w * ab[None]).sum(2) / L2[None], 0.0, 1.0)
        d = np.hypot(*(a[None] + ab[None] * t[..., None] - pts[:, None, :]).transpose(2, 0, 1))
        for k, j in zip(*np.nonzero(d <= tol), strict=True):
            if contour_vertex:                     # contour vertex k on river segment j
                out.append((float(dist[j] + t[k, j] * (dist[j + 1] - dist[j])), float(k)))
            else:                                  # river vertex k on contour segment j
                out.append((float(dist[k]), float(j + t[k, j])))
    return out


def plan(working_set, river: list, alloc, setback_m: float = SETBACK_M, only=None) -> Plan:
    """What burning the climbs along ``river`` - (lon, lat) points in walking
    order, a chain or a stem - would do. ``only`` is a (lon, lat): the climb
    nearest it is burned alone - the grade's list names a climb by its place. ``alloc(square)`` gives the id
    allocator for a square. ``setback_m`` is metres across per contour step:
    the first contour above the river's level is set back that far, the next
    twice as far - the steepness of the notch's sides."""
    out = Plan()
    found = _crossings(working_set, river, setback_m * 6)
    if found is None:
        return out
    proj, R, contours, crossings, dist = found
    if len(crossings) < 2:
        return out
    _, rejected, upstream = profile.grade_along([(c.r, c.ele) for c in crossings], list(dist))
    if only is not None:
        target = proj.to(only)
        ups = [sp for sp in rejected if (sp[2] > sp[3] if upstream else sp[3] > sp[2])]
        if not ups:
            return out
        rejected = [min(ups, key=lambda sp: float(np.hypot(*(_at(R, dist, (sp[0] + sp[1]) / 2) - target))))]
    used: set = set()
    cmds = []
    # one allocator a square for the whole plan: a spur's contours are cut
    # one after another, and each one's new nodes must not take another's ids
    allocs: dict = {}
    alloc_once = alloc

    def alloc(sq):
        return allocs.setdefault(sq.name, alloc_once(sq))
    for d0, d1, e0, e1 in rejected:
        if not (e0 > e1 if upstream else e1 > e0):
            continue                                    # a long span, not a climb
        base, top = min(e0, e1), max(e0, e1)
        r_hi = d1 if not upstream else d0
        where = proj.back(_at(R, dist, r_hi))
        c_hi = next((c for c in crossings if abs(c.r - r_hi) < 1e-6 and c.ele == top), None)
        if c_hi is None:
            continue
        if top - base > 25.0 + 1e-6:
            out.skipped.append((f'a climb of {top - base:g} m, more than one step', *where))
            continue
        same = [c for c in crossings if c.key == c_hi.key and c is not c_hi]
        if not same:
            out.skipped.append((f'the {top:g} m contour crosses the river only here', *where))
            continue
        partner = min(same, key=lambda c: abs(c.r - c_hi.r))
        lo, hi = sorted((c_hi.r, partner.r))
        # the spur: every contour crossing the river between the pair, the
        # pair's own included - each cut at its two crossings
        inside: dict = {}
        for c in crossings:
            if lo - 1e-6 <= c.r <= hi + 1e-6:
                inside.setdefault(c.key, []).append(c)
        why = None
        for key, cs in inside.items():
            level = cs[0].ele
            if level <= base:
                why = f'the {level:g} m contour crosses inside it - another climb, burn that first'
            elif len(cs) != 2:
                why = f'the {level:g} m contour crosses the river {len(cs)} times inside it'
            elif key in used:
                why = f'the {level:g} m contour is cut already - burn again'
            if why:
                break
        if why:
            out.skipped.append((why, *where))
            continue
        step = top - base
        group, failed = [], None
        for key, (c1, c2) in sorted(inside.items(), key=lambda kv: kv[1][0].ele):
            setback = setback_m * (c1.ele - base) / step
            cut = _cut(contours[key], c1, c2, R, dist, setback, proj, alloc)
            if isinstance(cut, str):
                failed = cut
                break
            group.append((key, cut))
        if failed:
            out.skipped.append((failed, *where))
            continue
        # and the contours above the river's level that do not cross it but
        # come nearer than their setback: pushed straight back to it, or the
        # cut lines run into them
        stretch = _section(R, dist, lo, hi)
        for key, (_, way_, P_) in contours.items():
            if key in inside or way_.ele <= base:
                continue
            setback = setback_m * (way_.ele - base) / step
            push = _push(stretch, P_, setback)
            if push is not None:
                moves = [edits.MoveNode(way_.refs[i], proj.back(P_[i]), proj.back(to))
                         for i, to in push.items()]
                Q = P_.copy()
                for i, to in push.items():
                    Q[i] = to
                group.append((key, {'cmd': edits.Compound(moves, name='push back'), 'lines': [Q],
                                    'added': [], 'dropped': [], 'removed': []}))
        clash = _clash(group, contours, set(inside) | {k for k, _ in group}, proj)
        if clash:
            out.skipped.append(clash)
            continue
        for key, cut in group:
            cmds.append((contours[key][0], cut['cmd']))
            if key not in inside:
                out.pushed += 1
            out.added += cut['added']
            out.dropped += cut['dropped']
            out.removed += cut['removed']
            used.add(key)
        out.burned += 1
        out.contours_cut += len(inside)
    # one Compound per square, the order kept
    by_sq: dict = {}
    for sq, cmd in cmds:
        by_sq.setdefault(sq.name, (sq, []))[1].append(cmd)
    out.steps = [(sq, edits.Compound(cs, name=f'burn: {len(cs)} contour' + 's' * (len(cs) != 1) + ' cut'))
                 for sq, cs in by_sq.values()]
    return out


def _push(bank, P, d):
    """A contour's vertices nearer the bank than ``d``, and where each goes:
    straight away from the nearest point of the bank to ``d``. None when none
    are."""
    a, b = bank[:-1], bank[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    w = P[:, None, :] - a[None]
    t = np.clip((w * ab[None]).sum(2) / L2[None], 0.0, 1.0)
    near = a[None] + ab[None] * t[..., None]
    dist = np.hypot(*(near - P[:, None, :]).transpose(2, 0, 1))
    j = dist.argmin(1)
    k = np.arange(len(P))
    close = dist[k, j] < d - 1e-6
    if not close.any():
        return None
    out = {}
    for i in np.flatnonzero(close):
        foot = near[i, j[i]]
        away = P[i] - foot
        length = float(np.hypot(*away))
        if length < 1e-6:
            return None                         # on the river: that is a crossing, not a push
        out[int(i)] = foot + away / length * d
    return out


def _clash(group, contours, cut_keys, proj):
    """Where the new lines of a spur's cut would cross a contour not being
    cut, or each other's - (why, lon, lat), or None."""
    for key, cut in group:
        level = contours[key][1].ele
        for pts in cut['lines']:
            others = [(contours[k][1], Q) for k, (_, _, Q) in contours.items() if k not in cut_keys]
            others += [(contours[k][1], q) for k, c in group if k != key for q in c['lines']]
            for other, Q in others:
                ii, _, _, _ = _hits(pts[:-1], pts[1:], Q[:-1], Q[1:])
                touch = _on_vertices(pts, _along(pts), Q)
                if len(ii) or touch:
                    at = pts[ii[0]] if len(ii) else _at(pts, _along(pts), touch[0][0])
                    return (f'cut back, the {level:g} m contour would cross the '
                            f'{other.ele:g} m contour, way {other.id}', *proj.back(at))
    return None


def _cut(held, c1, c2, R, dist, d, proj, alloc):
    """One contour cut at two crossings of the river and each piece closed
    along its own bank, set back ``d`` - its command, the lines it makes, and
    what it drops and removes; or why not, as a string."""
    sq, way, P = held
    closed = way.refs[0] == way.refs[-1] and len(way.refs) > 3
    a, b = sorted((c1, c2), key=lambda c: c.s)
    n = len(P) - 1
    bank = _section(R, dist, a.r, b.r)                 # the river from a's crossing to b's

    def run(s0, s1):
        """Vertex indices strictly between two contour positions, walking
        forward - round the ring when s1 < s0 on a closed contour."""
        first = math.floor(s0) + 1
        last = math.ceil(s1) - 1
        if s1 >= s0:
            return list(range(first, last + 1))
        return [i % n for i in range(first, last + 1 + n)]

    def kept(idx):
        """Of a piece's vertices, the ones set back from the river."""
        if not idx:
            return []
        far = _distance(bank, P[idx]) >= d
        return [i for i, f in zip(idx, far, strict=True) if f]

    pieces = []
    if closed:
        # the two arcs between the crossings, each closed along its own bank
        for s0, s1, rev in ((a.s, b.s, False), (b.s, a.s, True)):
            pieces.append(('ring', kept(run(s0, s1)), rev))
    else:
        pieces.append(('main', kept(list(range(0, math.floor(a.s) + 1))),
                       kept(list(range(math.ceil(b.s), n + 1)))))
        pieces.append(('ring', kept(run(a.s, b.s)), False))
    new_nodes: dict = {}
    ids = alloc(sq)
    built, lines, added, dropped = [], [], [], []

    def node(xy):
        nid = ids.take()
        new_nodes[nid] = proj.back(xy)
        return nid

    for piece in pieces:
        if piece[0] == 'main':
            head, tail = piece[1], piece[2]
            if not head or not tail:
                dropped.append([proj.back(p) for p in P])
                continue
            # judged against the bank line, which runs from a's crossing to
            # b's - against the river's own direction when a is downstream
            side = math.copysign(1.0, _side(bank, P[head[len(head) // 2]]))
            line = _offset(bank, side * d)              # a's end to b's end
            refs = [way.refs[i] for i in head] + [node(p) for p in line] + [way.refs[i] for i in tail]
            built.append(refs)
            lines.append(np.vstack([P[head], line, P[tail]]))
            added.append([proj.back(p) for p in line])
        else:
            idx, rev = piece[1], piece[2]
            if len(idx) < 2:
                gone = [proj.back(P[i]) for i in run(a.s, b.s)]
                dropped.append(gone or [proj.back(_at(R, dist, a.r)), proj.back(_at(R, dist, b.r))])
                continue
            side = math.copysign(1.0, _side(bank, P[idx[len(idx) // 2]]))
            line = _offset(bank, side * d)
            # the arc runs a -> b (or b -> a round the ring); its bank line
            # closes it back the other way
            line = line if rev else line[::-1]
            refs = [way.refs[i] for i in idx] + [node(p) for p in line]
            refs.append(refs[0])
            built.append(refs)
            lines.append(np.vstack([P[idx], line, P[idx[:1]]]))
            added.append([proj.back(p) for p in line])
    if not built:
        # wholly inside the notch: a narrow spur's inner contour, cut away
        # with it
        dropped.append([proj.back(p) for p in P])
        return {'cmd': edits.ReplaceWay(way.id, [], {}), 'lines': [], 'added': [],
                'dropped': dropped, 'removed': [[proj.back(p) for p in P]]}
    # what goes, for the proposal to strike through: the old line across the
    # river, from the vertex before its first crossing to the one after its
    # second - every vertex can be kept and the line still change
    removed = [[proj.back(P[i]) for i in range(math.floor(a.s), min(math.ceil(b.s), n) + 1)]]
    pieces_out = [(way.id if k == 0 else ids.take(), refs) for k, refs in enumerate(built)]
    return {'cmd': edits.ReplaceWay(way.id, pieces_out, new_nodes), 'lines': lines,
            'added': added, 'dropped': dropped, 'removed': [r for r in removed if r]}
