"""Burn a river into the terrain, through the contours - G7b, R25.

Where a river climbs against the contours, the grade leaves the span ungraded
(G6b). On gobras, once the rogue contours were cleaned out, most climbs are a
contour the river crosses twice with lower ground between - a ridge's finger
it cuts the tip from, a hill's flank it runs into and out of - and most of
those are one step of a **run**: the river leaves its level, climbs over a
spur through several contours, and comes back down to it. The Bosco River
goes 75 m to 225 m and back to 75 m over two kilometres; the grade sees six
climbs, and each cut alone runs into the next contour up.

So the run is the unit. It goes from the crossing the river climbs from to
the first downstream back at or below that level, and every contour above
that level is kept its setback from the whole stretch - ``d`` for the first
contour above, twice that for the next, the river burned down to the run's
level from one end to the other, in a notch whose sides rise a contour every
``d``. **What of a contour lies nearer is clipped out, and its ends joined
along the notch's rim on the side the ground is higher.** One rule covers it
all: a closed contour the river runs through becomes two; an open one, its
main line set back and a closed piece across the water; one weaving over the
river a pair of crossings at a time, as one; one that only comes near,
pushed back along the rim; one wholly inside, cut away. A piece of ground
the notch takes whole - a bump thinner than the setback - is dropped, and
said.

Not burned, and said: a run the river never comes back down from, a contour
crossing it an odd number of times inside the run (a spur), and a rim that
would cross another contour or the river.

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
    segment of each and the fraction along it. Only segments whose boxes
    overlap are tested."""
    lo1, hi1 = np.minimum(a1, b1), np.maximum(a1, b1)
    lo2, hi2 = np.minimum(a2, b2), np.maximum(a2, b2)
    s1 = np.flatnonzero(((hi1 >= lo2.min(0)) & (lo1 <= hi2.max(0))).all(1))
    s2 = np.flatnonzero(((hi2 >= lo1.min(0)) & (lo2 <= hi1.max(0))).all(1))
    none = np.zeros(0, dtype=int)
    if not len(s1) or not len(s2):
        return none, none, np.zeros(0), np.zeros(0)
    box = ((hi1[s1][:, None] >= lo2[s2][None]) & (lo1[s1][:, None] <= hi2[s2][None])).all(2)
    pi, pj = np.nonzero(box)
    i, j = s1[pi], s2[pj]
    A1, B1, A2, B2 = a1[i], b1[i], a2[j], b2[j]
    d1 = _orient(A2, B2, A1)
    d2 = _orient(A2, B2, B1)
    d3 = _orient(A1, B1, A2)
    d4 = _orient(A1, B1, B2)
    hit = (((d1 > EPS) & (d2 < -EPS)) | ((d1 < -EPS) & (d2 > EPS))) & \
          (((d3 > EPS) & (d4 < -EPS)) | ((d3 < -EPS) & (d4 > EPS)))
    order = np.lexsort((j[hit], i[hit]))
    ii, jj = i[hit][order], j[hit][order]
    r = b1[ii] - a1[ii]
    s_ = b2[jj] - a2[jj]
    w = a2[jj] - a1[ii]
    den = r[:, 0] * s_[:, 1] - r[:, 1] * s_[:, 0]
    t = (w[:, 0] * s_[:, 1] - w[:, 1] * s_[:, 0]) / den
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
    proj, R, _, crossings, dist = found
    if len(crossings) < 2:
        return []
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
    contours, crossings = _near(working_set, proj, R, margin), []
    for key, (_, way, P) in contours.items():
        here = []
        ii, jj, t, u = _hits(R[:-1], R[1:], P[:-1], P[1:])
        for i, j, tt, uu in zip(ii, jj, t, u, strict=True):
            here.append((float(dist[i] + tt * (dist[i + 1] - dist[i])), float(j + uu)))
        # and where one passes through the other's vertex - a contour snapped
        # to the river shares a node with it, which the proper test does not
        # count and the grade does
        here += _contacts(R, dist, P)
        seen = []
        for r, sp in sorted(here):
            if seen and abs(r - seen[-1]) < 0.01:
                continue
            seen.append(r)
            crossings.append(_Crossing(r, float(way.ele), key, sp))
    crossings.sort(key=lambda c: c.r)
    return proj, R, contours, crossings, dist


def _near(working_set, proj, R, margin):
    """The contours in the box about the river, ``2 * margin`` out, by
    (square name, way id): (square, way, points in metres)."""
    lo, hi = R.min(0) - 2 * margin, R.max(0) + 2 * margin
    out = {}
    for sq in working_set.squares.values():
        for way in sq.contours():
            pts = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs if r in sq.nodes]
            if len(pts) != len(way.refs) or len(pts) < 2:
                continue
            P = proj.to(pts)
            if (P.max(0) < lo).any() or (P.min(0) > hi).any():
                continue
            out[(sq.name, way.id)] = (sq, way, P)
    return out


def _contacts(R, dist, P):
    """Where a contour meets the river at a vertex of either line, as
    crossings: (metres along the river, position along the contour).

    A contour snapped to a river shares a node with it, and one snapped along
    it shares a run of them - each a contact, which would count it as crossing
    the river several times and have the burn refuse its spur. So a run of contacts next to each other along the contour is
    one, and it is a crossing only if the contour is on one side of the river
    before it and the other after; touching and turning back is not one."""
    hits = sorted(_on_vertices(R, dist, P), key=lambda h: h[1])
    n = len(P) - 1
    out, run = [], []

    def close_run():
        if not run:
            return
        s0, s1 = run[0][1], run[-1][1]
        if s0 <= 1e-9 or s1 >= n - 1e-9:
            return                              # the contour ends on the river
        # just before and just after the run, on the contour - half a segment
        # away, or half way to the end where the run is nearer it than that
        before, after = s0 - min(0.5, s0 / 2), s1 + min(0.5, (n - s1) / 2)
        sides = [_side(R, _point(P, x)) for x in (before, after)]
        if sides[0] * sides[1] < 0:
            # the middle of the run: the contour goes over somewhere along it,
            # and the middle is as good a place to cut as any
            out.append(run[len(run) // 2])

    for h in hits:
        if run and h[1] - run[-1][1] > 1.0 + 1e-9:
            close_run()
            run = []
        run.append(h)
    close_run()
    return out


def _point(P, s):
    """The point at a position along a contour."""
    i = int(np.clip(math.floor(s), 0, len(P) - 2))
    t = s - i
    return P[i] + (P[i + 1] - P[i]) * t


def _on_vertices(R, dist, P, tol=1e-3):
    """Crossings at a vertex of either line: (metres along the river,
    position along the contour) for each contour vertex on the river and
    each river vertex on the contour, to a millimetre. Only a vertex inside a
    segment's box is measured against it - a contour near a river is near it
    in few places."""
    out = []
    for pts, a, b, contour_vertex in ((P, R[:-1], R[1:], True), (R, P[:-1], P[1:], False)):
        lo, hi = np.minimum(a, b) - tol, np.maximum(a, b) + tol
        keep = ((pts >= lo.min(0)) & (pts <= hi.max(0))).all(1)
        if not keep.any():
            continue
        kk = np.flatnonzero(keep)
        q = pts[kk]
        seg = ((hi >= q.min(0)) & (lo <= q.max(0))).all(1)
        jj = np.flatnonzero(seg)
        if not len(jj):
            continue
        inbox = ((q[:, None, :] >= lo[jj][None]) & (q[:, None, :] <= hi[jj][None])).all(2)
        ki, ji = np.nonzero(inbox)
        if not len(ki):
            continue
        k, j = kk[ki], jj[ji]
        ab = b[j] - a[j]
        t = np.clip(((pts[k] - a[j]) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0.0, 1.0)
        d = np.hypot(*(a[j] + ab * t[:, None] - pts[k]).T)
        for k_, j_, t_ in zip(k[d <= tol], j[d <= tol], t[d <= tol], strict=True):
            if contour_vertex:                     # contour vertex k on river segment j
                out.append((float(dist[j_] + t_ * (dist[j_ + 1] - dist[j_])), float(k_)))
            else:                                  # river vertex k on contour segment j
                out.append((float(dist[k_]), float(j_ + t_)))
    return out


def plan(working_set, river: list, alloc, setback_m: float = SETBACK_M, only=None) -> Plan:
    """What burning the climbs along ``river`` - (lon, lat) points in walking
    order, a chain or a stem - would do. ``only`` is a (lon, lat): the run
    holding the climb nearest it is burned alone - the grade's list names a
    climb by its place. ``alloc(square)`` gives the id allocator for a square.
    ``setback_m`` is metres across per contour step: the first contour above
    the run's level is set back that far, the next twice as far - the
    steepness of the notch's sides.

    Each run is cut on the squares themselves, one pair of crossings at a
    time, the crossings found again after each cut - a contour weaving across
    the river has a pair for each time over, and a cut can make a piece that
    still crosses. Everything is undone before it returns: the plan's steps
    do it again."""
    out = Plan()
    margin = setback_m * 12
    found = _crossings(working_set, river, margin)
    if found is None:
        return out
    proj, R, _, crossings, dist = found
    if len(crossings) < 2:
        return out
    _, rejected, upstream = profile.grade_along([(c.r, c.ele) for c in crossings], list(dist))
    runs, lost = _runs(crossings, rejected, upstream)

    def middle(sp):
        return _at(R, dist, (sp[0] + sp[1]) / 2)
    if only is not None:
        target = proj.to(only)
        ups = [(sp, run) for run in runs for sp in run.climbs] + [(sp, None) for sp in lost]
        if not ups:
            return out
        sp, run = min(ups, key=lambda u: float(np.hypot(*(middle(u[0]) - target))))
        runs, lost = ([run], []) if run else ([], [sp])
    for sp in lost:
        out.skipped.append((f'the river climbs to {max(sp[2], sp[3]):g} m and never comes back down '
                            f'to {min(sp[2], sp[3]):g} m', *proj.back(middle(sp))))
    # one allocator a square for the whole plan: a run's contours are cut one
    # after another, and each one's new nodes must not take another's ids
    allocs: dict = {}

    def alloc_once(sq):
        return allocs.setdefault(sq.name, alloc(sq))
    applied: list = []
    try:
        for run in runs:
            # the first run sees the squares as they were found; each after
            # it, as the runs before left them
            got = _burn_run(working_set, river, run, setback_m, margin, alloc_once, applied,
                            None if applied else found)
            if isinstance(got, tuple):
                out.skipped.append(got)
                continue
            out.burned += len(run.climbs)
            out.contours_cut += len(got['cut'])
            out.pushed += got['pushed']
            out.added += got['added']
            out.dropped += got['dropped']
            out.removed += got['removed']
        cmds = list(applied)
    finally:
        for sq, cmd in reversed(applied):
            cmd.undo(sq)
    # one Compound per square, the order kept
    by_sq: dict = {}
    for sq, cmd in cmds:
        by_sq.setdefault(sq.name, (sq, []))[1].append(cmd)
    out.steps = [(sq, edits.Compound(cs, name=f'burn: {len(cs)} contour' + 's' * (len(cs) != 1) + ' cut'))
                 for sq, cs in by_sq.values()]
    return out


@dataclass
class _Run:
    """The river from the crossing it climbs from to the first downstream
    back at or below that level - everything between stands above it."""
    base: float
    lo: float                                   # metres along the river, its ends
    hi: float
    climbs: list                                # the grade's spans in it


def _runs(crossings, rejected, upstream):
    """The runs the climbs are part of, and the climbs in none - the river
    never comes back down. Runs nest or keep apart; each climb goes with the
    largest holding it, so a hill the river runs over is burned whole, not
    one step of it at a time."""
    seq = crossings[::-1] if upstream else crossings
    found, lost = [], []
    for sp in rejected:
        d0, d1, e0, e1 = sp
        if not (e0 > e1 if upstream else e1 > e0):
            continue                                    # a long span, not a climb
        base = min(e0, e1)
        r_base = d0 if e0 < e1 else d1
        i = next((i for i, c in enumerate(seq) if abs(c.r - r_base) < 1e-6 and c.ele == base), None)
        if i is None:
            continue
        j = next((j for j in range(i + 1, len(seq)) if seq[j].ele <= base), None)
        if j is None:
            lost.append(sp)
        else:
            found.append((base, *sorted((seq[i].r, seq[j].r)), sp))
    runs: list = []
    for base, lo, hi, sp in sorted(found, key=lambda f: f[1] - f[2]):
        home = next((r for r in runs if r.lo - 1e-6 <= lo and hi <= r.hi + 1e-6), None)
        if home is None:
            runs.append(_Run(base, lo, hi, [sp]))
        else:
            home.climbs.append(sp)
    return runs, lost


def _burn_run(working_set, river, run, setback_m, margin, alloc, applied, found=None):
    """Burn one run on the squares, its commands added to ``applied``: what
    it cut, pushed and drew - or why not, (why, lon, lat), with its own
    commands undone.

    The notch: every contour above the run's level is kept its setback from
    the whole stretch - the river burned down to the run's level from one end
    to the other. What of a contour lies nearer is clipped out, and its ends
    joined along the notch's rim on the side the ground is higher. That is
    the cut of a contour crossing the river, each pair of crossings of one
    weaving across it, and the push of one that only comes near, alike."""
    mark = len(applied)
    proj, R, contours, crossings, dist = found or _crossings(working_set, river, margin)
    inside = [c for c in crossings if run.lo + 1e-6 < c.r < run.hi - 1e-6]
    got = {'cut': set(), 'pushed': 0, 'added': [], 'dropped': [], 'removed': []}
    if not inside:
        return got
    levels = sorted({run.base, *(c.ele for c in inside)})
    step = min(b - a for a, b in zip(levels, levels[1:], strict=False))

    def refuse(why, xy):
        for sq, cmd in reversed(applied[mark:]):
            cmd.undo(sq)
        del applied[mark:]
        return (why, *proj.back(xy))
    over: dict = {}
    for c in inside:
        over.setdefault(c.key, []).append(c)
    for cs in over.values():
        if len(cs) % 2:
            times = 'only once' if len(cs) == 1 else f'{len(cs)} times'
            return refuse(f'the {cs[0].ele:g} m contour crosses the river {times} before it is back '
                          f'down to {run.base:g} m', _at(R, dist, cs[0].r))
    stretch = _section(R, dist, run.lo, run.hi)
    lo, hi = stretch.min(0), stretch.max(0)
    before = {k: P for k, (_, _, P) in contours.items()}
    origin: dict = {}
    rims: dict = {}
    for key, (sq, way_, P) in contours.items():
        if way_.ele <= run.base:
            continue
        d = setback_m * (way_.ele - run.base) / step
        if d > margin or (P.max(0) < lo - d).any() or (P.min(0) > hi + d).any():
            continue
        rim = _Rim(stretch, d)
        cut = _clip(sq, way_, P, rim, [(c.r - run.lo, c.s) for c in over.get(key, [])], proj, alloc)
        if cut is None:
            continue
        if isinstance(cut, str):
            return refuse(cut, P[0])
        cut['cmd'].apply(sq)
        applied.append((sq, cut['cmd']))
        for wid, _ in cut['cmd'].pieces:
            origin[(sq.name, wid)] = key
        origin[key] = key
        if key in over:
            got['cut'].add(key)
        else:
            got['pushed'] += 1
        for name in ('added', 'dropped', 'removed'):
            got[name] += cut[name]
        rims[key] = (way_.ele, cut['rims'])
        # the rim must not run over the river where it bends back
        for line in cut['rims']:
            at = _meet(line, R)
            if at is not None:
                return refuse(f'cut back, the {way_.ele:g} m contour would cross the river', at)
    # and what it made must not cross a contour it did not cross before
    clash = _clash(_near(working_set, proj, R, margin), origin, before, rims)
    if clash:
        why, xy = clash
        return refuse(why, xy)
    return got


class _Rim:
    """The edge of the notch - everything within ``d`` of the stretch -
    walked round it clockwise as one loop: along the stretch's left side
    from its start, round its far end, back along its right side and round
    its start. A place on it is the distance round."""

    def __init__(self, stretch, d):
        self.S, self.d = stretch, d
        self.sd = _along(stretch)
        self.L = float(self.sd[-1])
        self.cap = math.pi * d
        self.round = 2 * self.L + 2 * self.cap

    def _ends(self):
        S = self.S
        t0 = (S[1] - S[0]) / max(float(np.hypot(*(S[1] - S[0]))), 1e-9)
        t1 = (S[-1] - S[-2]) / max(float(np.hypot(*(S[-1] - S[-2]))), 1e-9)
        return t0, t1

    def foot(self, p):
        """The nearest place on the stretch, as metres along it, and which
        side p is: positive left."""
        a, b = self.S[:-1], self.S[1:]
        ab = b - a
        t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
        near = a + ab * t[:, None]
        i = int(np.argmin(np.hypot(*(near - p).T)))
        return float(self.sd[i] + t[i] * (self.sd[i + 1] - self.sd[i])), float(_orient(a[i], b[i], p))

    def where(self, p) -> float:
        """How far round the rim a point on it is."""
        s, side = self.foot(p)
        t0, t1 = self._ends()
        if s <= 1e-6 and float(np.dot(p - self.S[0], t0)) < -1e-6:
            v = p - self.S[0]
            n = np.array([-t0[1], t0[0]])
            return 2 * self.L + self.cap + math.atan2(-float(v @ t0), -float(v @ n)) * self.d
        if s >= self.L - 1e-6 and float(np.dot(p - self.S[-1], t1)) > 1e-6:
            v = p - self.S[-1]
            n = np.array([-t1[1], t1[0]])
            return self.L + math.atan2(float(v @ t1), float(v @ n)) * self.d
        return s if side > 0 else self.L + self.cap + (self.L - s)

    def path(self, a, b):
        """The rim from ``a`` round to ``b``, its points in order."""
        if b < a:
            b += self.round
        out = []
        k = math.floor(a / self.round)
        base = k * self.round
        while base < b:
            for lo, hi, kind in ((0, self.L, 'left'), (self.L, self.L + self.cap, 'far'),
                                 (self.L + self.cap, 2 * self.L + self.cap, 'right'),
                                 (2 * self.L + self.cap, self.round, 'near')):
                x0, x1 = max(a, base + lo), min(b, base + hi)
                if x1 - x0 <= 1e-9:
                    continue
                u0, u1 = x0 - base - lo, x1 - base - lo
                if kind == 'left':
                    out += list(_offset(_section(self.S, self.sd, u0, u1), self.d))
                elif kind == 'right':
                    out += list(_offset(_section(self.S, self.sd, self.L - u0, self.L - u1), self.d))
                else:
                    t0, t1 = self._ends()
                    if kind == 'far':
                        c, t = self.S[-1], t1
                        n = np.array([-t[1], t[0]])
                        ang = np.linspace(u0 / self.d, u1 / self.d, max(2, int((u1 - u0) / self.d * 8) + 2))
                        out += [c + self.d * (math.cos(g) * n + math.sin(g) * t) for g in ang]
                    else:
                        c, t = self.S[0], t0
                        n = np.array([-t[1], t[0]])
                        ang = np.linspace(u0 / self.d, u1 / self.d, max(2, int((u1 - u0) / self.d * 8) + 2))
                        out += [c - self.d * (math.cos(g) * n + math.sin(g) * t) for g in ang]
            base += self.round
        # inside a bend tighter than d the offset folds back on itself: those
        # points are nearer the river than d, and not on the rim
        if not out:
            return np.zeros((0, 2))
        out = np.asarray(out)
        on = _distance(self.S, out) >= self.d * 0.995
        on[0] = on[-1] = True
        keep = [out[0]]
        for q in out[1:][on[1:]]:
            if float(np.hypot(*(q - keep[-1]))) > 1e-3:
                keep.append(q)
        return np.asarray(keep)


def _high_side(P, closed, over, rim):
    """+1 when the ground above a contour is on its left, walking it forward;
    -1 on its right; None when its crossings disagree. Read where it crosses
    the river - rising across the first, falling across the second - or, for
    one that only comes near, from the river being below it."""
    n = len(P) - 1

    def ahead(s):
        a, b = max(s - 1e-3, 0.0), min(s + 1e-3, float(n))
        return _point(P, b) - _point(P, a)
    if over:
        seen = set()
        for k, (f, s) in enumerate(over):
            tr = _at(rim.S, rim.sd, min(f + 1e-3, rim.L)) - _at(rim.S, rim.sd, max(f - 1e-3, 0.0))
            tc = ahead(s)
            left = tc[0] * tr[1] - tc[1] * tr[0] > 0        # the river heads off to its left
            seen.add(1 if left == (k % 2 == 0) else -1)
        return seen.pop() if len(seen) == 1 else None
    dist = _distance(rim.S, P)
    i = int(np.argmin(np.where(dist > 1e-2, dist, np.inf)))
    foot = _at(rim.S, rim.sd, rim.foot(P[i])[0])
    t = ahead(float(i)) if 0 < i < n or closed else ahead(min(max(i, 1e-3), n - 1e-3))
    u = foot - P[i]
    return -1 if t[0] * u[1] - t[1] * u[0] > 0 else 1


def _clip(sq, way, P, rim, over, proj, alloc):
    """One contour clipped to the notch and its ends joined along the rim -
    its command, the lines it makes, and what it drops and removes; None when
    it keeps clear; or why not, as a string. ``over`` is where it crosses the
    stretch, as metres along it: the river is higher than the contour between
    the first and second of them, the third and fourth - the ground the rim
    keeps."""
    d = rim.d
    closed = way.refs[0] == way.refs[-1] and len(way.refs) > 3
    n = len(P) - 1
    # each segment sampled, a few metres apart, and each sample in or out
    step = max(1.0, min(10.0, d / 4))
    seg = np.hypot(*np.diff(P, axis=0).T)
    k = np.maximum(1, np.ceil(seg / step)).astype(int)
    s = np.concatenate([i + np.arange(k[i]) / k[i] for i in range(n)] + [[float(n)]])
    pts = np.array([_point(P, x) for x in s])
    near = _distance(rim.S, pts) < d
    if not near.any():
        return None
    if near.all():
        return _gone(way, P, proj)

    def edge(s0, s1):
        """Where the contour crosses the rim between two positions, one in
        and one out - by halves."""
        out0 = _distance(rim.S, _point(P, s0)[None])[0] >= d
        for _ in range(30):
            m_ = (s0 + s1) / 2
            if (_distance(rim.S, _point(P, m_)[None])[0] >= d) == out0:
                s0 = m_
            else:
                s1 = m_
        return (s0 + s1) / 2
    # the outside runs, each from where it comes out of the notch (or the
    # contour's start) to where it goes in (or its end)
    flips = [edge(s[i], s[i + 1]) for i in range(len(s) - 1) if near[i] != near[i + 1]]
    if closed:
        # start the walk round the ring outside the notch
        first_out = next(i for i in range(len(s)) if not near[i])
        start = s[first_out]
        flips = sorted(f if f > start else f + n for f in flips)
        # out from the last flip round through the start to the first
        pieces = [(flips[-1], flips[0] + n)] + [(flips[i], flips[i + 1]) for i in range(1, len(flips) - 1, 2)]
        gaps = [(flips[i], flips[i + 1]) for i in range(0, len(flips) - 1, 2)]
        free = set()
    else:
        cuts = [0.0, *flips, float(n)]
        if near[0]:
            cuts = cuts[1:]
        if near[-1]:
            cuts = cuts[:-1]
        pieces = [(cuts[i], cuts[i + 1]) for i in range(0, len(cuts) - 1, 2)]
        gaps = [(pieces[i][1], pieces[i + 1][0]) for i in range(len(pieces) - 1)]
        free = {x for x in (0.0, float(n)) if x in cuts}
        if near[0]:
            gaps.insert(0, (0.0, cuts[0]))
        if near[-1]:
            gaps.append((cuts[-1], float(n)))
    if len(pieces) == 0:
        return _gone(way, P, proj)

    def at(x):
        return _point(P, x % n if closed else x)

    def verts(a, b):
        """The contour's own vertices strictly between two positions."""
        first, last = math.floor(a) + 1, math.ceil(b) - 1
        return [i % n if closed else i for i in range(first, last + 1)
                if a + 1e-9 < i < b - 1e-9]
    # the ends on the rim, in order round it
    ends = []                                   # (round, piece, 0 start / 1 end)
    for j, (a, b) in enumerate(pieces):
        for e, x in ((0, a), (1, b)):
            if x not in free:
                ends.append((rim.where(at(x)), j, e))
    ends.sort()
    # which side of the contour is high; the notch, low, is on the right
    # going forward round the rim - so a piece's end joins the next end
    # forward round the rim when high is on the contour's left, the one
    # before when on its right, and that must be where a piece starts
    high = _high_side(P, closed, over, rim)
    if high is None:
        return f'cut back, the {way.ele:g} m contour has its high side both ways'
    joins = {}
    for i, (_, _, e) in enumerate(ends):
        if e != 1:
            continue
        k_ = (i + high) % len(ends)
        if ends[k_][2] != 0 or k_ in joins.values():
            return f'cut back, the {way.ele:g} m contour could not be closed along the river'
        joins[i] = k_
    # trace pieces and rim joins into lines and rings
    new_nodes: dict = {}
    ids = alloc(sq)
    point_id: dict = {}

    def rim_node(x):
        if x not in point_id:
            nid = ids.take()
            new_nodes[nid] = proj.back(at(x))
            point_id[x] = nid
        return point_id[x]

    def node(xy):
        nid = ids.take()
        new_nodes[nid] = proj.back(xy)
        return nid

    def piece_refs(j):
        a, b = pieces[j]
        refs = [way.refs[0] if a in free else rim_node(a), *(way.refs[i] for i in verts(a, b)),
                way.refs[-1] if b in free else rim_node(b)]
        return refs, [at(a), *(P[i] for i in verts(a, b)), at(b)]
    built, lines, rims, added, dropped = [], [], [], [], []
    done = set()
    start_of = {(j, e): i for i, (_, j, e) in enumerate(ends)}
    # a line starts at the piece from the contour's start; the rest are rings
    order = sorted(range(len(pieces)), key=lambda j: pieces[j][0] not in free)
    for j0 in order:
        if j0 in done:
            continue
        refs, xy, j, ring = [], [], j0, False
        while True:
            done.add(j)
            r_, p_ = piece_refs(j)
            refs += r_[1:] if refs and refs[-1] == r_[0] else r_
            xy += p_
            b = pieces[j][1]
            if b in free or start_of[(j, 1)] not in joins:
                break                               # the contour's end, or it stops at the rim
            i = start_of[(j, 1)]
            k_ = joins[i]
            _, jn, _ = ends[k_]
            line = rim.path(ends[i][0], ends[k_][0]) if high > 0 else rim.path(ends[k_][0], ends[i][0])[::-1]
            inner = line[1:-1] if len(line) > 2 else line[:0]
            refs += [node(q) for q in inner]
            xy += list(inner)
            rims.append(np.vstack([[at(b)], *([inner] if len(inner) else []), [at(pieces[jn][0])]]))
            added.append([proj.back(q) for q in rims[-1]])
            if jn == j0:
                ring = True
                break
            if jn in done:
                return f'cut back, the {way.ele:g} m contour could not be closed along the river'
            j = jn
        if ring:
            refs.append(refs[0])
            if len(set(refs)) < 3:
                dropped.append([proj.back(q) for q in xy])
                continue
        built.append(refs)
        lines.append(np.asarray(xy))
    # what goes, for the proposal to strike through: the contour inside the
    # notch; a stretch of it that goes over the river and back to the same
    # side held ground the notch has taken whole - dropped, and said
    removed = []
    for a, b in gaps:
        run_ = [proj.back(at(a))] + [proj.back(P[i]) for i in verts(a, b)] + [proj.back(at(b))]
        removed.append(run_)
    if not built:
        return _gone(way, P, proj)
    for a, b in gaps:
        if a in free or b in free:
            continue
        side = math.copysign(1, rim.foot(at(a))[1])
        if side == math.copysign(1, rim.foot(at(b))[1]):
            span = [at(a), *[P[i] for i in verts(a, b)], at(b)]
            if any(rim.foot(q)[1] * side < -1e-6 for q in span):
                dropped.append([proj.back(q) for q in span])
    pieces_out = [(way.id if k_ == 0 else ids.take(), refs) for k_, refs in enumerate(built)]
    return {'cmd': edits.ReplaceWay(way.id, pieces_out, new_nodes), 'lines': lines, 'rims': rims,
            'added': added, 'dropped': dropped, 'removed': removed}


def _gone(way, P, proj):
    """A contour wholly inside the notch - a knoll the river runs over, a
    spur's tip - cut away."""
    whole = [proj.back(p) for p in P]
    return {'cmd': edits.ReplaceWay(way.id, [], {}), 'lines': [], 'rims': [], 'added': [],
            'dropped': [whole], 'removed': [whole]}


def _meet(P, Q):
    """Where one line crosses or touches another, or None."""
    lo, hi = np.maximum(P.min(0), Q.min(0)), np.minimum(P.max(0), Q.max(0))
    if (lo > hi + 1e-3).any():
        return None
    ii, _, t, _ = _hits(P[:-1], P[1:], Q[:-1], Q[1:])
    if len(ii):
        return P[ii[0]] + (P[ii[0] + 1] - P[ii[0]]) * t[0]
    touch = _on_vertices(P, _along(P), Q)
    return _at(P, _along(P), touch[0][0]) if touch else None


def _clash(contours, origin, before, rims):
    """Where a rim the run drew crosses a contour - its own contour's other
    pieces aside, and one its contour crossed before - (why, where), or None.
    What else of a contour is kept was there before."""
    met: dict = {}
    for was, (level, lines) in rims.items():
        for line in lines:
            for other, (_, ow, Q) in contours.items():
                o = origin.get(other, other)
                if o == was:
                    continue
                at = _meet(line, Q)
                if at is None:
                    continue
                pair = frozenset((was, o))
                if pair not in met:
                    met[pair] = o in before and _meet(before[was], before[o]) is not None
                if not met[pair]:
                    return (f'cut back, the {level:g} m contour would cross the '
                            f'{ow.ele:g} m contour, way {ow.id}', at)
    return None
