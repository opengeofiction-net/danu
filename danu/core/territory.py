"""Territory and owner under a square - R7, and the spec's *Ownership and
handoff*.

Two published files join on a relation id. The wiki's
``OpenGeofiction:Territory_administration`` (``action=raw``) is the
attributes: ``ogfId``, ``name``, ``status``, ``owner``, ``rel`` and
``constraints``. The daily
``data.opengeofiction.net/utility/territory.json`` is the geometry: relation
id to rings of ``[lat, lon]`` - the spec said ``[lon, lat]`` until the file
was measured on 2026-09-19 (longitudes run to 179, latitudes to 80) and now
says what the file does - one ring as a list of points, or several as a list
of rings, and the two spellings are both in the file. The join is not
total (1,103 geometries to 1,089 records on 2026-09-19), so a polygon with no
record is reported as unknown rather than guessed at.

The question is *whose ground is under this square?*, answered by which
polygons hold the square's centre, corners and edge midpoints or reach a
vertex into it. A square straddling a border reports both; a collaborative
territory reports as such. Ownership warns and never blocks - the editor
reports, the project adjudicates. Nothing here fetches anything: the files
arrive as text from whoever holds the cache.

The data drop (#190) asks the sharper question, *may this user upload this
square?* - ``permission``: yes where all the territory in the square is
theirs, partial where some is, no where none is. Theirs is a territory that
names them as an owner, or as a delegate in a ``dem:`` constraint. Its
status is not asked: the territory administration takes owners off a
territory as it is withdrawn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

Point = tuple[float, float]
Ring = list[Point]

# where the two files are published - the editor's and the data drop's
GEOMETRY_URL = 'https://data.opengeofiction.net/utility/territory.json'
ATTRIBUTES_URL = 'https://wiki.opengeofiction.net/index.php?title=OpenGeofiction:Territory_administration&action=raw'

# statuses under which the ground is somebody's to draw
CLAIMED = {'owned', 'reserved', 'marked for withdrawal'}

# a delegate for the elevation: a constraint "dem:Alice;Bob" (#190)
DEM = 'dem:'

# A territory is in a square when more than this share of the square is
# under it: slivers where two neighbours' polygons disagree by a few metres
# are not a claim. 1e-5 of a degree square is about 0.1 km2 at the equator
MIN_SHARE = 1e-5

YES, PARTIAL, NO = 'yes', 'partial', 'no'

# how far into a neighbour's ground a partial square's mapper may reach: the
# social contract, which the editor shades (danu.core.ground) and says
REACH_M = 2000.0


@dataclass(frozen=True)
class Territory:
    rel: int
    ogf_id: str = ''
    name: str = ''
    status: str = ''
    owner: str = ''
    constraints: tuple[str, ...] = ()

    @property
    def editors(self) -> frozenset[str]:
        """Who may draw it: each of the ``;`` separated owners, and each
        delegate a ``dem:`` constraint names, trimmed. Exact, as OGF's names
        are: wangi, not Wangi (H6f)."""
        names = self.owner.split(';')
        for c in self.constraints:
            if c[:len(DEM)].lower() == DEM:
                names += c[len(DEM):].split(';')
        return frozenset(n.strip() for n in names if n.strip())

    @property
    def known(self) -> bool:
        return bool(self.name)

    def describe(self) -> str:
        if not self.known:
            return f'unknown territory (relation {self.rel})'
        if self.status in CLAIMED and self.owner:
            return f'{self.name} ({self.ogf_id}), {self.status} by {self.owner}'
        return f'{self.name} ({self.ogf_id}), {self.status}'


def parse_attributes(text: str) -> dict[int, Territory]:
    """The wiki's JSON list, by relation id. A record without a usable
    ``rel`` is skipped: it has no geometry to join to."""
    out: dict[int, Territory] = {}
    for rec in json.loads(text):
        try:
            rel = int(rec['rel'])
        except (KeyError, TypeError, ValueError):
            continue
        cons = rec.get('constraints')
        cons = [cons] if isinstance(cons, str) else cons
        out[rel] = Territory(rel, str(rec.get('ogfId', '')), str(rec.get('name', '')),
                             str(rec.get('status', '')), str(rec.get('owner', '')),
                             tuple(c for c in cons if isinstance(c, str)) if isinstance(cons, list) else ())
    return out


def parse_geometry(text: str) -> dict[int, list[Ring]]:
    """The published polygons, by relation id, always as a list of rings."""
    out: dict[int, list[Ring]] = {}
    for key, value in json.loads(text).items():
        if not isinstance(value, list) or not value:
            continue
        first = value[0]
        if isinstance(first, list) and first and isinstance(first[0], (int, float)):
            rings = [value]                       # a bare ring: a list of points
        else:
            rings = value                         # a list of rings
        kept: list[Ring] = []
        for ring in rings:
            try:
                # the file is [lat, lon]; everything here is (lon, lat)
                pts = [(float(lon), float(lat)) for lat, lon in ring]
            except (TypeError, ValueError):
                continue                          # a malformed ring is dropped, not fatal
            if len(pts) >= 3:
                kept.append(pts)
        if kept:
            out[int(key)] = kept
    return out


def _inside(pt: Point, ring: Ring) -> bool:
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _clip(ring: Ring, bounds: tuple[float, float, float, float]) -> Ring:
    """Sutherland-Hodgman: the ring cut to the box. Edges along the box's
    sides may come out doubled back, which leave the area as it is."""
    w, s, e, n = bounds
    out = ring
    for inside, cut in (
            (lambda p: p[0] >= w, lambda a, b: (w, a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0]))),
            (lambda p: p[0] <= e, lambda a, b: (e, a[1] + (b[1] - a[1]) * (e - a[0]) / (b[0] - a[0]))),
            (lambda p: p[1] >= s, lambda a, b: (a[0] + (b[0] - a[0]) * (s - a[1]) / (b[1] - a[1]), s)),
            (lambda p: p[1] <= n, lambda a, b: (a[0] + (b[0] - a[0]) * (n - a[1]) / (b[1] - a[1]), n))):
        if not out:
            break
        pts, out = out, []
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
            prev = cur
    return out


def _area(ring: Ring) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True))) / 2


@dataclass(frozen=True)
class Permission:
    """May a user upload a square: ``level`` yes, partial or no, and the
    territories in the square that are theirs and that are another's."""
    level: str
    mine: tuple[Territory, ...] = ()
    others: tuple[Territory, ...] = ()


@dataclass
class TerritoryIndex:
    """Polygons with a bounding box each, and the attributes to join to."""
    geometry: dict[int, list[Ring]]
    attributes: dict[int, Territory] = field(default_factory=dict)
    _boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict, init=False)
    _signs: dict[int, list[int]] = field(default_factory=dict, init=False)

    def __post_init__(self):
        for rel, rings in self.geometry.items():
            xs = [x for ring in rings for x, _ in ring]
            ys = [y for ring in rings for _, y in ring]
            if xs:
                self._boxes[rel] = (min(xs), min(ys), max(xs), max(ys))

    def territory(self, rel: int) -> Territory:
        return self.attributes.get(rel, Territory(rel))

    def is_territory(self, rel: int) -> bool:
        """Whether a relation is a territory to name under a square. The
        geometry file holds more than territories: a timezone is a relation
        with rings and no ogf:id, and so no record - 304988, GOBRAS PEN,
        lies over all of Gobrassanya. And a territory split into admin
        level 3 and 4 sub-territories is an ``outline`` over them, the parts
        holding the status and the owner that matter. With the records not
        read yet, every polygon counts, and says it is unknown."""
        if not self.attributes:
            return True
        t = self.attributes.get(rel)
        return t is not None and t.status != 'outline'

    def contains(self, rel: int, pt: Point) -> bool:
        """Even-odd over the relation's rings, so a hole is a hole."""
        box = self._boxes.get(rel)
        if box is None:
            return False
        w, s, e, n = box
        if not (w <= pt[0] <= e and s <= pt[1] <= n):
            return False
        return sum(_inside(pt, ring) for ring in self.geometry[rel]) % 2 == 1

    def _ring_signs(self, rel: int) -> list[int]:
        """+1 for an outer ring, -1 for a hole - one inside an odd number of
        the others - so that areas sum as even-odd fills. Judged by the
        middle of a ring's first edge, not a vertex: a hole often shares a
        vertex with the ring round it, and a point on a ring falls either
        way."""
        if rel not in self._signs:
            rings = self.geometry[rel]
            mid = [((r[0][0] + r[1][0]) / 2, (r[0][1] + r[1][1]) / 2) for r in rings]
            self._signs[rel] = [
                -1 if sum(_inside(mid[i], o) for j, o in enumerate(rings) if j != i) % 2 else 1
                for i in range(len(rings))]
        return self._signs[rel]

    def shares(self, bounds: tuple[float, float, float, float]) -> dict[int, float]:
        """Each territory in a box, by relation, with the share of the box it
        covers: exact, from its rings cut to the box, holes taken out. Only
        those over MIN_SHARE."""
        w, s, e, n = bounds
        whole = (e - w) * (n - s)
        out: dict[int, float] = {}
        for rel, (bw, bs, be, bn) in self._boxes.items():
            if be < w or bw > e or bn < s or bs > n or not self.is_territory(rel):
                continue
            area = sum(sign * _area(_clip(ring, bounds))
                       for sign, ring in zip(self._ring_signs(rel), self.geometry[rel], strict=True))
            if area / whole > MIN_SHARE:
                out[rel] = area / whole
        return out

    def at(self, lon: float, lat: float) -> list[Territory]:
        return [self.territory(rel) for rel in self._boxes if self.contains(rel, (lon, lat))]

    def under(self, bounds: tuple[float, float, float, float]) -> list[Territory]:
        """The territories under a box - a square, or a working set: those
        with a share of it (``shares``). Ordered with the one under the
        centre first, then by the share each has. This is the one definition
        of 'under'; anything else that asks - a report, the server's
        permission - calls this. A centre exactly on a shared border falls to
        the polygon east or north of it, by the strict inequality in the ray
        test: arbitrary, but stable."""
        w, s, e, n = bounds
        centre = ((w + e) / 2, (s + n) / 2)
        found = self.shares(bounds)
        return [self.territory(rel) for rel in
                sorted(found, key=lambda rel: (not self.contains(rel, centre), -found[rel], rel))]

    def permission(self, bounds: tuple[float, float, float, float], user: str) -> Permission:
        """May ``user`` upload the square at ``bounds`` (#190): yes where all
        the territory in it is theirs - ground under no territory, the sea,
        counts against nobody - partial where some is, no where none is. A
        square of open sea, with no territory in it, is no: an
        administrator's. An administrator may upload anything; that is the
        caller's to know."""
        found = self.under(bounds)
        mine = tuple(t for t in found if user and user in t.editors)
        others = tuple(t for t in found if t not in mine)
        level = NO if not mine else PARTIAL if others else YES
        return Permission(level, mine, others)


def describe(found: list[Territory], user: str = '', admin: bool = False) -> tuple[str, bool]:
    """One line for the status bar, and whether it is a warning: the ground
    is claimed by somebody who is not the user. No user set, no warning -
    the line still says whose it is. An administrator is warned as anyone
    is - so as to know - and told they are one."""
    if not found:
        return 'no territory here', False
    line = '; '.join(t.describe() for t in found)
    if admin and user:
        line += ' (administrator)'
    # not somebody else's to the owners, 'Alessa;Leowezy', nor to a dem:
    # delegate (#190) - Territory.editors. The CLAIMED gate stays, unlike in
    # permission: this is a warning while drawing, not who may upload
    others = [t for t in found if t.known and t.status in CLAIMED and t.owner
              and user not in t.editors]
    if user and others:
        return f'not yours to draw: {line}', True
    return line, False
