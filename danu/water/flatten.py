"""Flatten a water body at its level, through the contours - G7a, R26.

The build reads no water. A lake reaches it as what the editor writes into the
squares: its level as ``ele`` on its outline, which the build already reads as
a contour - a closed contour at the lake's level with nothing inside it, which
the fill makes flat - and the contours that disagree with that taken away.

So flattening a lake is five edits, one step:

- **The level on the outline.** A closed way's own ``ele``; a relation's on
  each of its member ways, outer and inner, so an island's shore is at the
  lake's level too and the island's own contours rise from it. A member way a
  river area's relation names as well is where the river meets the lake, water
  on both sides - its mouth, or its source - and the river's surface there is
  the lake's: it takes the level too (#240). Refused: a member that is a
  waterway itself, a river area that is all the lake's outline - the lake is
  the river (R27) - and a member another relation names, where a ring two
  lakes share has two levels to choose from.
- **Contours inside the water deleted.** They describe the lake bed, which the
  surface does not show; kept, they make the water anything but flat. Inside
  an island is land, and stays.
- **Contours crossing the shore pulled back.** Clipped where they cross it,
  and where a contour's level is not the lake's its end is drawn back from the
  water by ``pull_back_m``, so the ground climbs from the shore over that
  distance rather than standing as a step at the water's edge. A contour at the
  lake's own level is clipped at the shore and left touching it.
- **The nearest level either side pushed round.** A contour at the level
  next below or above the lake's, of those near it, that strays in and out of
  the water is the shore's neighbour drawn a little off, not the lake bed: cut,
  it is left as bits along the shore. It is pushed out round the water
  instead, ``pull_back_m`` from it - the shore offset, on the side the contour
  ran - and stays one line. Where that would cross or touch another contour it
  is tried at half the distance, and half again, and failing that is cut as
  above. The offset is GDAL's; a build without it cuts.
- **Fill lines across the water, at its level.** Straight lines every
  ``FILL_SPACING_M``, clipped to the water so an island is left out, tagged
  ``danu:fill`` with the lake they belong to. They are an interim measure. The
  shore alone does not make a lake flat: isofill declines a cell that sees one
  level in every direction - a closed contour with nothing inside is how a
  hilltop looks - and its second pass fills the lake from the islands and the
  banks around it. Lake Kinser came out 125 to 150 m with 8% of it at its
  level. Lines across it give every cell something to see: at 120 m apart,
  296 nodes, 99.7% of it at 125 m at 1 arcsecond, where spot heights on a 120 m
  grid needed 2,586 nodes for 96% at 3. When isofill learns to hold a marked
  one-level enclosure flat, every way tagged ``danu:fill`` is deleted in one
  pass.

No Qt, and GDAL only to push a contour round: geometry in metres on a local
projection about the lake, which over a lake's extent is exact enough to say
what is inside it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

from ..core import edits
from ..core.ladder import format_ele
from ..core.push import Pusher, _length
from ..core.rings import _chains, is_closed
from ..core.square import Relation, Square, Way, is_coastline, parse_ele, water_tags
from .overpass import flows

PULL_BACK_M = 100.0
FILL_SPACING_M = 120.0
FILL = 'danu:fill'
# two cut positions closer than this along a contour are one - a contour that
# shares a node with the shore is cut there once, not at both of the segments
# meeting at it
_SAME = 1e-9


@dataclass
class Plan:
    """What flattening a lake would do, before it is done."""
    level: float
    steps: list = field(default_factory=list)        # (square, Compound)
    outline: list = field(default_factory=list)      # rings, as [(lon, lat)]
    removed: list = field(default_factory=list)      # what goes, as [(lon, lat)] runs
    deleted: int = 0                                 # contours wholly inside
    clipped: int = 0                                 # crossing the shore at the lake's level
    pulled: int = 0                                  # crossing it at another, drawn back
    wrapped: int = 0                                 # the nearest level, pushed round the water
    added: list = field(default_factory=list)        # what a push round draws, as [(lon, lat)] runs
    outline_ways: int = 0
    fill: list = field(default_factory=list)         # the fill lines, as [(lon, lat)] pairs


def fill_key(feature) -> str:
    """What a lake's fill lines name it by."""
    return f'{"relation" if isinstance(feature, Relation) else "way"}/{feature.id}'


def fills(square: Square, feature) -> list[Way]:
    """A lake's fill lines, as the square holds them."""
    key = fill_key(feature)
    return [w for w in square.ways.values() if w.tags.get(FILL) == key]


def relevel(square: Square, feature, text: str | None) -> list:
    """What keeps a flattened lake one level when its level changes: its
    outline ways and its fill lines take the new one, and when the level is
    cleared the outline loses its ``ele`` and the fill lines go. Empty for a
    lake never flattened. The contours were clipped against the old level and
    stay as they are - a flatten again redoes them."""
    lines = fills(square, feature)
    if isinstance(feature, Relation):
        ring = [square.ways[m.ref] for m in feature.members
                if m.type == 'way' and m.ref in square.ways and 'ele' in square.ways[m.ref].tags]
    else:
        ring = []                          # a closed way's level is its own, set by the caller
    if not lines and not ring:
        return []
    out = []
    for w in ring:
        after = {k: v for k, v in w.tags.items() if k != 'ele'}
        if text is not None:
            after['ele'] = text
        if after != w.tags:
            out.append(edits.SetTags(w.id, dict(w.tags), after))
    for w in lines:
        if text is None:
            out.append(edits.DeleteWay(w.id))
        elif w.tags.get('ele') != text:
            out.append(edits.SetTags(w.id, dict(w.tags), {**w.tags, 'ele': text}))
    return out


class Refused(ValueError):
    """Why a lake cannot be flattened as it stands - said, not raised past."""


def rings(square: Square, feature) -> tuple[list[list[int]], list[Way]]:
    """A lake's outline as closed node-id rings, and the ways they are made
    of - stitched by ``core.rings``, as the editor fills it and the server
    reads it. A ring that does not close, or a member this square lacks, is
    refused: flattening half a lake would clip contours against an edge
    nobody mapped."""
    if not isinstance(feature, Relation):
        if not is_closed(feature):
            raise Refused('its outline is not closed')
        return [list(feature.refs)], [feature]
    ways = []
    for mem in feature.members:
        if mem.type != 'way':
            continue
        if mem.ref not in square.ways:
            raise Refused('part of its outline is not in this square')
        ways.append(square.ways[mem.ref])
    chains = _chains([w.refs for w in ways])
    if not chains:
        raise Refused('it has no outline')
    if any(c[0] != c[-1] for c in chains):
        raise Refused('its outline does not close into rings')
    return chains, ways


class _Projection:
    def __init__(self, lat0: float):
        self.kx, self.ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0

    def xy(self, n) -> tuple[float, float]:
        return n.lon * self.kx, n.lat * self.ky

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        return x / self.kx, y / self.ky

    def xy_of(self, lon: float, lat: float) -> tuple[float, float]:
        return lon * self.kx, lat * self.ky


class _Shore:
    """Every edge of a lake's rings, as arrays - asked of each contour near it
    at once rather than edge by edge, which on Lake Kinser's 3,000 shore
    edges and 128 contours near it was most of five seconds. And indexed by
    cell, so a contour is asked only of the edges near it: roantra's estuary,
    relation 470435, has 32,918, and all of them asked of each of the 3,451
    contours near it was three minutes of a four-minute flatten."""

    CELL_M = 500.0

    def __init__(self, polys):
        self.a = np.array([p for ring in polys for p in ring[:-1]], dtype=float)
        self.b = np.array([p for ring in polys for p in ring[1:]], dtype=float)
        lo = np.floor(np.minimum(self.a, self.b) / self.CELL_M).astype(np.int64)
        hi = np.floor(np.maximum(self.a, self.b) / self.CELL_M).astype(np.int64)
        cells, rows = defaultdict(list), defaultdict(list)
        for k, ((x0, y0), (x1, y1)) in enumerate(zip(lo, hi, strict=True)):
            for cy in range(y0, y1 + 1):
                rows[cy].append(k)
                for cx in range(x0, x1 + 1):
                    cells[(cx, cy)].append(k)
        self.cells = {c: np.array(v) for c, v in cells.items()}
        self.rows = {r: np.array(v) for r, v in rows.items()}

    def inside(self, pt) -> bool:
        """Even-odd over every ring: inside an outer ring and not inside one
        of its inner rings - an island is outside the water. The ray runs
        east, so only the edges in the point's row of cells can cross it."""
        x, y = pt
        k = self.rows.get(int(math.floor(y / self.CELL_M)))
        if k is None:
            return False
        (x0, y0), (x1, y1) = self.a[k].T, self.b[k].T
        spans = (y0 > y) != (y1 > y)
        with np.errstate(divide='ignore', invalid='ignore'):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        return bool(np.count_nonzero(spans & (x < xc)) % 2)

    def _near(self, pts) -> np.ndarray:
        """The edges in the cells a run of points passes through."""
        out = set()
        for (ax, ay), (bx, by) in pairwise(pts):
            for cx in range(math.floor(min(ax, bx) / self.CELL_M), math.floor(max(ax, bx) / self.CELL_M) + 1):
                for cy in range(math.floor(min(ay, by) / self.CELL_M), math.floor(max(ay, by) / self.CELL_M) + 1):
                    k = self.cells.get((cx, cy))
                    if k is not None:
                        out.update(k.tolist())
        return np.array(sorted(out), dtype=np.int64)

    def cuts(self, pts) -> list[float]:
        """Where a run of points meets the shore, as positions along it."""
        near = self._near(pts)
        if not len(near):
            return []
        a, b = self.a[near], self.b[near]
        p = np.asarray(pts[:-1], dtype=float)[:, None, :]
        d = (np.asarray(pts[1:], dtype=float) - np.asarray(pts[:-1], dtype=float))[:, None, :]
        e = (b - a)[None, :, :]
        w = a[None, :, :] - p
        den = d[..., 0] * e[..., 1] - d[..., 1] * e[..., 0]
        with np.errstate(divide='ignore', invalid='ignore'):
            t = (w[..., 0] * e[..., 1] - w[..., 1] * e[..., 0]) / den
            u = (w[..., 0] * d[..., 1] - w[..., 1] * d[..., 0]) / den
        hit = (den != 0) & (t >= -_SAME) & (t <= 1 + _SAME) & (u >= -_SAME) & (u <= 1 + _SAME)
        i, _ = np.nonzero(hit)
        return sorted({round(float(k + min(1.0, max(0.0, v))), 12) for k, v in zip(i, t[hit], strict=True)})


def _pieces(pts, closed: bool, shore):
    """A contour cut at the shore into runs of position along it - position
    ``i + t`` is fraction ``t`` of the way from vertex ``i`` to ``i + 1`` -
    each with whether it lies in the water, and whether each end is a cut."""
    n = len(pts) - 1
    stops = [0.0, *[c for c in shore.cuts(pts) if _SAME < c < n - _SAME], float(n)]
    runs = []
    for a, b in pairwise(stops):
        runs.append([a, b, shore.inside(_at(pts, (a + b) / 2)), a > 0, b < n])
    if closed and len(runs) > 1 and runs[0][2] == runs[-1][2]:
        # a ring cut open: its first and last runs meet at the closing vertex,
        # which is no cut, and are one run
        last = runs.pop()
        runs[0] = [last[0] - n, runs[0][1], last[2], last[3], runs[0][4]]
    elif closed and len(runs) == 1:
        runs[0][3] = runs[0][4] = False
    return runs


def _at(pts, pos: float):
    """The point at a position along the run. Outside 0..n only on a closed
    contour cut open across its closing vertex, where it wraps."""
    n = len(pts) - 1
    if pos < 0 or pos > n:
        pos %= n
    i = min(int(math.floor(pos)), n - 1)
    t = pos - i
    (x0, y0), (x1, y1) = pts[i], pts[i + 1]
    return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t


def plan(working_set, square: Square, feature, alloc, pull_back_m: float = PULL_BACK_M,
         fill_spacing_m: float = FILL_SPACING_M) -> Plan:
    """What flattening ``feature`` - a lake in ``square``, a closed way or a
    relation - at its level would do. ``alloc(square)`` gives the id
    allocator for a square. Raises ``Refused`` with why it cannot."""
    if not fill_spacing_m > 0:
        raise ValueError(f'fill lines {fill_spacing_m} m apart would never stop')
    tags = feature.tags
    if flows(tags):
        raise Refused('flowing water is never flattened - it descends along its course')
    level = parse_ele(tags.get('ele'))
    if level is None:
        raise Refused('it has no level yet - G grades it from the contours, '
                      'L or the panel sets one')
    node_rings, outline_ways = rings(square, feature)
    outline_ids = {w.id for w in outline_ways}
    for w in outline_ways:
        if w is feature:
            continue
        others = [r for r in square.relations.values()
                  if r is not feature and any(m.type == 'way' and m.ref == w.id for m in r.members)]
        if flows(w.tags):
            raise Refused(f'way {w.id} of its outline is a {w.tags.get("waterway") or "river"} itself: '
                          'flowing water has no one level')
        rivers = [r for r in others if flows(r.tags)]
        for r in rivers:
            if all(m.type != 'way' or m.ref in outline_ids for m in r.members):
                raise Refused(f'{r.tags.get("name") or f"relation {r.id}"} is a river with all of its '
                              'outline the lake\'s: flowing water has no one level')
        others = [r for r in others if not flows(r.tags)]
        if others:
            raise Refused(f'way {w.id} of its outline is shared with '
                          f'{others[0].tags.get("name") or f"relation {others[0].id}"}')
    nodes = square.nodes
    if any(r not in nodes for ring in node_rings for r in ring):
        raise Refused('a node of its outline is missing')
    lat0 = sum(nodes[ring[0]].lat for ring in node_rings) / len(node_rings)
    proj = _Projection(lat0)
    polys = [[proj.xy(nodes[r]) for r in ring] for ring in node_rings]
    shore = _Shore(polys)
    xs = [x for ring in polys for x, _ in ring]
    ys = [y for ring in polys for _, y in ring]
    box = (min(xs) - pull_back_m, min(ys) - pull_back_m, max(xs) + pull_back_m, max(ys) + pull_back_m)
    out = Plan(level, outline=[[(nodes[r].lon, nodes[r].lat) for r in ring] for ring in node_rings])
    text = format_ele(level)
    per_square: dict = {}
    # the level on the outline: the lake's own ways, in its own square
    for w in outline_ways:
        if w.tags.get('ele') != text:
            per_square.setdefault(square.name, []).append(
                edits.SetTags(w.id, dict(w.tags), {**w.tags, 'ele': text}))
            out.outline_ways += w is not feature
    # and a lake held in a square read alongside the set, outside it: its
    # outline and fill lines are written there
    by_name = {sq.name: sq for sq in [*working_set.squares.values(), *getattr(working_set, 'extra', {}).values()]}
    near = []
    for sq in working_set.squares.values():
        watery = {m.ref for r in sq.relations.values() if water_tags(r.tags)
                  for m in r.members if m.type == 'way'}
        for way in list(sq.ways.values()):
            e = parse_ele(way.tags.get('ele'))
            if (e is None or len(way.refs) < 2 or water_tags(way.tags) or way.id in watery
                    or FILL in way.tags or is_coastline(way)          # never reshaped: its direction is the sea
                    or (sq is square and way.id in outline_ids)
                    or any(r not in sq.nodes for r in way.refs)):
                continue
            pts = [proj.xy(sq.nodes[r]) for r in way.refs]
            if (max(x for x, _ in pts) < box[0] or min(x for x, _ in pts) > box[2]
                    or max(y for _, y in pts) < box[1] or min(y for _, y in pts) > box[3]):
                continue
            near.append((sq, way, pts, e))
    below = max((e for *_, e in near if e < level), default=None)
    above = min((e for *_, e in near if e > level), default=None)
    # what it can of each contour, pushed round: a stretch the next
    # contour up crowds against the shore is cut as a deeper one is, the
    # rest of it one line still (r239 in roantra's N46E029: its 30 m touches
    # the water here and there, and the 20 m was cut into seventeen)
    pushed = Pusher.make(polys, pull_back_m, partial=True)

    def push_round(sq, way, pts):
        got = pushed.round(sq, way, pts, proj, alloc)
        return None if got is None else (*got, pushed.last)
    wrap = []
    for sq, way, pts, e in near:
        if pushed is not None and e in (below, above):
            wrap.append((sq, way, pts, e))
            continue
        cmd = _reshape(sq, way, pts, e, level, shore, proj, alloc, pull_back_m, out)
        if cmd is not None:
            per_square.setdefault(sq.name, []).append(cmd)
        if pushed is not None:
            pushed.stays(way.id, _after(sq, way, pts, cmd, proj))
    tried = [[sq, way, pts, e, push_round(sq, way, pts)] for sq, way, pts, e in wrap]
    cut: dict = {}
    while True:
        for k, (sq, way, pts, e, got) in enumerate(tried):
            if got is None and k not in cut:
                cut[k] = _reshape(sq, way, pts, e, level, shore, proj, alloc, pull_back_m, out)
                pushed.stays(way.id, _after(sq, way, pts, cut[k], proj))
        # one cut after all can run across one pushed round before it was:
        # that one is tried again, nearer the water, against what is known now
        crossed = [t for t in tried if t[4] is not None and not pushed.clear(t[1].id, t[4][1], t[4][2])]
        if not crossed:
            break
        for t in crossed:
            pushed.drop(t[1].id)
            t[4] = push_round(t[0], t[1], t[2])
    for k, (sq, way, _, e, got) in enumerate(tried):
        cmd = cut.get(k)
        if got is not None:
            cmd, arcs, gone, _ = got
            out.wrapped += 1
            out.added += [[proj.lonlat(*q) for q in arc] for arc in arcs]
            out.removed += [[proj.lonlat(*q) for q in run] for run in gone]
            # what was not pushed and still reaches the water, cut there: the
            # cut worked out on the contour as pushed, then the push taken back
            cmd.apply(sq)
            now = sq.ways[way.id]
            aside = Plan(level)
            rest = _reshape(sq, now, [proj.xy(sq.nodes[r]) for r in now.refs], e, level, shore, proj, alloc,
                            pull_back_m, aside)
            cmd.undo(sq)
            if rest is not None:
                cmd = edits.Compound([cmd, rest], name=cmd.describe())
                out.removed += aside.removed
        if cmd is not None:
            per_square.setdefault(sq.name, []).append(cmd)
    # the lake's fill lines: the old ones out, new ones across the water
    lines = [edits.DeleteWay(w.id) for w in fills(square, feature)]
    ids = alloc(square)
    xs0, xs1 = min(xs) - 10.0, max(xs) + 10.0
    y = min(ys) + fill_spacing_m / 2
    while y < max(ys):
        pts = [(xs0, y), (xs1, y)]
        stops = [0.0, *shore.cuts(pts), 1.0]
        for a, b in pairwise(stops):
            if (b - a) * (xs1 - xs0) < 1.0:
                continue
            if not shore.inside((xs0 + (xs1 - xs0) * (a + b) / 2, y)):
                continue
            ends = [proj.lonlat(xs0 + (xs1 - xs0) * t, y) for t in (a, b)]
            nids = [ids.take(), ids.take()]
            lines.append(edits.AddWay(ids.take(), nids, ends, {'ele': text, FILL: fill_key(feature)}))
            out.fill.append(ends)
        y += fill_spacing_m
    old = [c for c in lines if isinstance(c, edits.DeleteWay)]
    if lines and not (len(old) == len(lines) - len(old)
                      and _same_lines(square, old, lines[len(old):])):
        per_square.setdefault(square.name, []).extend(lines)
    name = tags.get('name') or 'the lake'
    out.steps = [(by_name[k], edits.Compound(cmds, name=f'flatten {name} at {text} m'))
                 for k, cmds in per_square.items()]
    return out


def _same_lines(square, old, new) -> bool:
    """Whether the fill lines a flatten would draw are the ones already
    there - so a lake flattened twice at one level is no step the second
    time."""
    have = sorted(tuple((round(square.nodes[r].lon, 9), round(square.nodes[r].lat, 9))
                        for r in square.ways[c.way_id].refs) + (square.ways[c.way_id].tags.get('ele'),)
                  for c in old)
    want = sorted(tuple((round(lon, 9), round(lat, 9)) for lon, lat in c.coords) + (c.tags.get('ele'),)
                  for c in new)
    return have == want


def _reshape(sq, way, pts, e, level, shore, proj, alloc, pull_back_m, out):
    closed = way.refs[0] == way.refs[-1] and len(way.refs) > 3
    runs = _pieces(pts, closed, shore)
    if not any(r[2] for r in runs) and not any(r[3] or r[4] for r in runs):
        return None                                      # nowhere near the water
    if all(r[2] for r in runs):
        out.deleted += 1
        out.removed.append([proj.lonlat(*p) for p in pts])
        return edits.ReplaceWay(way.id, [], {})
    at_level = abs(e - level) < 1e-6
    keep = []
    for a, b, wet, cut_a, cut_b in runs:
        if wet:
            out.removed.append([proj.lonlat(*_at(pts, a + (b - a) * k / 8)) for k in range(9)])
            continue
        if not at_level:
            a, b = _drawn_back(pts, a, b, cut_a, cut_b, pull_back_m, proj, out)
            if a is None:
                continue
        keep.append((a, b, cut_a, cut_b))
    if at_level:
        out.clipped += 1
    else:
        out.pulled += 1
    ids = alloc(sq)
    n = len(way.refs) - 1
    new_nodes, pieces = {}, []

    def node_at(pos):
        whole = round(pos)
        if abs(pos - whole) < _SAME:
            return way.refs[whole % n if closed else whole]
        nid = ids.take()
        new_nodes[nid] = proj.lonlat(*_at(pts, pos))
        return nid

    for k, (a, b, _, _) in enumerate(keep):
        refs = [node_at(a)]
        i = math.floor(a + _SAME) + 1
        while i < b - _SAME:
            r = way.refs[i % n if closed else i]
            if r != refs[-1]:
                refs.append(r)
            i += 1
        end = node_at(b)
        if end != refs[-1]:
            refs.append(end)
        if len(refs) >= 2:
            pieces.append((way.id if k == 0 else ids.take(), refs))
    if not pieces:
        out.deleted += 1
        out.pulled -= not at_level
        out.clipped -= at_level
        return edits.ReplaceWay(way.id, [], {})
    return edits.ReplaceWay(way.id, pieces, new_nodes)


def _after(sq, way, pts, cmd, proj) -> list[list[tuple[float, float]]]:
    """A contour as a flatten leaves it, in metres: its pieces, or itself
    when it is left alone."""
    if cmd is None:
        return [pts]
    return [[proj.xy(sq.nodes[r]) if r not in cmd.new_nodes else proj.xy_of(*cmd.new_nodes[r]) for r in refs]
            for _, refs in cmd.pieces]


def _drawn_back(pts, a, b, cut_a, cut_b, d, proj, out):
    """A run's ends that are cuts at the shore, drawn back along it by ``d``
    metres; None when the run is shorter than that."""
    seq = [_at(pts, a)] + [_at(pts, float(i)) for i in range(math.floor(a + _SAME) + 1, math.ceil(b - _SAME))] + [_at(pts, b)]
    pos = [a] + [float(i) for i in range(math.floor(a + _SAME) + 1, math.ceil(b - _SAME))] + [b]
    dist = _length(seq)
    total = dist[-1]
    lo, hi = (d if cut_a else 0.0), total - (d if cut_b else 0.0)
    if hi - lo <= 0:
        out.removed.append([proj.lonlat(*p) for p in seq])
        return None, None

    def pos_at(m):
        for (p0, d0), (p1, d1) in pairwise(zip(pos, dist, strict=True)):
            if d0 <= m <= d1:
                return p0 + (p1 - p0) * ((m - d0) / (d1 - d0) if d1 > d0 else 0.0)
        return pos[-1]
    na, nb = pos_at(lo), pos_at(hi)
    for keep_lo, m0, m1 in ((cut_a, 0.0, lo), (cut_b, hi, total)):
        if keep_lo and m1 > m0:
            out.removed.append([proj.lonlat(*_at(pts, pos_at(m0 + (m1 - m0) * k / 4)))
                                for k in range(5)])
    return na, nb


# ------------------------------------------------- re-import, G7a-bis

@dataclass(frozen=True)
class Reshaped:
    """A flattened lake whose outline an import has since changed - its
    fill lines and clipped contours were laid against the old one. Shaped
    like ``gone.Gone`` so the dock and the map choose it the same way."""
    square: object
    kind: str                # 'way' or 'relation'
    id: int
    name: str | None
    why: str

    def describe(self) -> str:
        return f'"{self.name}" - {self.why}' if self.name else f'{self.kind} {self.id} - {self.why}'


def _outline(square: Square, feature):
    """A lake's outline as it stands, comparable before and after: its
    rings' coordinates, each ring from its lowest point and the rings in
    order, so the same shape read twice is equal. None when it no longer
    closes."""
    try:
        node_rings, _ = rings(square, feature)
    except Refused:
        return None
    out = []
    for ring in node_rings:
        pts = [(round(square.nodes[r].lon, 7), round(square.nodes[r].lat, 7))
               for r in ring[:-1] if r in square.nodes]
        if not pts:
            return None
        k = pts.index(min(pts))
        pts = pts[k:] + pts[:k]
        out.append(tuple(min(pts, pts[:1] + pts[:0:-1])))      # either direction
    return tuple(sorted(out))


def flattened(working_set) -> dict:
    """Every lake the set holds that has been flattened, with its outline as
    it stands: one with fill lines, or a relation whose rings carry a level
    - a lake too narrow for a fill line still has that. Keyed by square,
    kind and id."""
    out = {}
    for sq in working_set.squares.values():
        keys = {w.tags[FILL] for w in sq.ways.values() if FILL in w.tags}
        for rel in sq.relations.values():
            if not water_tags(rel.tags):
                continue
            # rings with a level, of a relation with one: the sea's coastline
            # ways carry 0 m as coastlines, and the sea is no flattened lake
            ringed = 'ele' in rel.tags and any(m.type == 'way' and m.ref in sq.ways and 'ele' in sq.ways[m.ref].tags
                                               for m in rel.members)
            if ringed or fill_key(rel) in keys:
                out[(sq.name, 'relation', rel.id)] = (rel.tags.get('name'), _outline(sq, rel))
        for way in sq.ways.values():
            if fill_key(way) in keys:
                out[(sq.name, 'way', way.id)] = (way.tags.get('name'), _outline(sq, way))
    return out


def _unlevelled(square: Square, feature) -> bool:
    """A flattened relation lake with a ring way that does not carry its
    level - one upstream put in place of the way that did."""
    if not isinstance(feature, Relation):
        return False
    level = feature.tags.get('ele')
    return any(m.type == 'way' and m.ref in square.ways and square.ways[m.ref].tags.get('ele') != level
               for m in feature.members)


def reshaped(before: dict, working_set) -> list[Reshaped]:
    """The flattened lakes ``before`` named whose outline is not what it was.
    A lake no longer held at all is the gone report's, not this one's."""
    out = []
    for (name, kind, fid), (label, was) in sorted(before.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
        sq = working_set.squares.get(name)
        holder = (sq.relations if kind == 'relation' else sq.ways) if sq is not None else {}
        feature = holder.get(fid)
        if feature is None:
            continue
        now = _outline(sq, feature)
        if now == was and not _unlevelled(sq, feature):
            continue
        if now is None:
            why = 'its outline no longer closes in this square'
        elif now == was:
            # the same shore under new ways: upstream redrew the ring, and the
            # new ways do not carry the level the build reads as its contour
            why = 'its shore was redrawn upstream without its level - F flattens it again'
        else:
            why = 'reshaped upstream since it was flattened - F flattens it again'
        out.append(Reshaped(name, kind, fid, label, why))
    return out
