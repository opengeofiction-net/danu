"""Territory and owner under a square - R7, and the spec's *Ownership and
handoff*.

Two published files join on a relation id. The wiki's
``OpenGeofiction:Territory_administration`` (``action=raw``) is the
attributes: ``ogfId``, ``name``, ``status``, ``owner``, ``rel``. The daily
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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

Point = tuple[float, float]
Ring = list[Point]

# statuses under which the ground is somebody's to draw
CLAIMED = {'owned', 'reserved', 'marked for withdrawal'}


@dataclass(frozen=True)
class Territory:
    rel: int
    ogf_id: str = ''
    name: str = ''
    status: str = ''
    owner: str = ''

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
        out[rel] = Territory(rel, str(rec.get('ogfId', '')), str(rec.get('name', '')),
                             str(rec.get('status', '')), str(rec.get('owner', '')))
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


@dataclass
class TerritoryIndex:
    """Polygons with a bounding box each, and the attributes to join to."""
    geometry: dict[int, list[Ring]]
    attributes: dict[int, Territory] = field(default_factory=dict)
    _boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict, init=False)

    def __post_init__(self):
        for rel, rings in self.geometry.items():
            xs = [x for ring in rings for x, _ in ring]
            ys = [y for ring in rings for _, y in ring]
            if xs:
                self._boxes[rel] = (min(xs), min(ys), max(xs), max(ys))

    def territory(self, rel: int) -> Territory:
        return self.attributes.get(rel, Territory(rel))

    def contains(self, rel: int, pt: Point) -> bool:
        """Even-odd over the relation's rings, so a hole is a hole."""
        box = self._boxes.get(rel)
        if box is None:
            return False
        w, s, e, n = box
        if not (w <= pt[0] <= e and s <= pt[1] <= n):
            return False
        return sum(_inside(pt, ring) for ring in self.geometry[rel]) % 2 == 1

    def at(self, lon: float, lat: float) -> list[Territory]:
        return [self.territory(rel) for rel in self._boxes if self.contains(rel, (lon, lat))]

    def under(self, bounds: tuple[float, float, float, float]) -> list[Territory]:
        """The territories under a box - a square, or a working set: those
        holding its centre, corners or edge midpoints, and those reaching a
        vertex into it. Ordered with the one under the centre first. This is
        the one definition of 'under'; anything else that asks - a report,
        the server - calls this rather than sampling for itself. A sample
        exactly on a shared border falls to the polygon east or north of it,
        by the strict inequality in the ray test: arbitrary, but stable."""
        w, s, e, n = bounds
        cx, cy = (w + e) / 2, (s + n) / 2
        samples = [(cx, cy), (w, s), (e, s), (e, n), (w, n), (cx, s), (cx, n), (w, cy), (e, cy)]
        found: dict[int, int] = {}                  # rel -> rank
        for rel, (bw, bs, be, bn) in self._boxes.items():
            if be < w or bw > e or bn < s or bs > n:
                continue
            for i, pt in enumerate(samples):
                if self.contains(rel, pt):
                    found[rel] = min(found.get(rel, 99), i)
                    break
            else:
                if any(w <= x <= e and s <= y <= n for ring in self.geometry[rel] for x, y in ring):
                    found[rel] = 50
        return [self.territory(rel) for rel, _ in sorted(found.items(), key=lambda kv: (kv[1], kv[0]))]


def describe(found: list[Territory], user: str = '') -> tuple[str, bool]:
    """One line for the status bar, and whether it is a warning: the ground
    is claimed by somebody who is not the user. No user set, no warning -
    the line still says whose it is."""
    if not found:
        return 'no territory here', False
    line = '; '.join(t.describe() for t in found)
    # an owner field can name several, 'Alessa;Leowezy'
    others = [t for t in found if t.known and t.status in CLAIMED and t.owner
              and user.lower() not in [o.strip().lower() for o in t.owner.split(';')]]
    if user and others:
        return f'not yours to draw: {line}', True
    return line, False
