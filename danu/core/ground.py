"""Whose ground a square is, drawn (#190): the parts of a square a user may
map freely, the parts they may reach into, and the parts that are another's.

A square shared with a neighbour is ``partial`` (``TerritoryIndex.permission``):
the mapper may upload it all, on the understanding that they keep to their
own territory and reach at most ``REACH_M`` into the neighbour's. This is
that understanding as polygons, for the editor to shade - ``near``, the
neighbour's ground within reach, and ``far``, the neighbour's ground beyond
it. Their own ground, and the sea under no territory, are left alone.

Worked in metres about the square's centre, which over one degree is close
enough for a 10 km band, with OGR for the buffer and the overlaps. Rings in
the territory file are even-odd, so a territory is the symmetric difference
of its rings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from osgeo import ogr

from .territory import REACH_M, Ring, Territory, TerritoryIndex

ogr.UseExceptions()


@dataclass
class Ground:
    """Each a list of polygons, each polygon a list of rings, (lon, lat)."""
    mine: list[list[Ring]] = field(default_factory=list)
    near: list[list[Ring]] = field(default_factory=list)
    far: list[list[Ring]] = field(default_factory=list)


class _Local:
    """Degrees to metres and back, about a point."""

    def __init__(self, lon: float, lat: float):
        self.lon0, self.lat0 = lon, lat
        self.kx = 111320.0 * math.cos(math.radians(lat))
        self.ky = 110574.0

    def ring(self, ring: Ring) -> ogr.Geometry:
        g = ogr.Geometry(ogr.wkbLinearRing)
        for lon, lat in ring:
            g.AddPoint_2D((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)
        g.CloseRings()
        return g

    def polygon(self, ring: Ring) -> ogr.Geometry:
        p = ogr.Geometry(ogr.wkbPolygon)
        p.AddGeometry(self.ring(ring))
        return p

    def back(self, geom: ogr.Geometry | None) -> list[list[Ring]]:
        """Every polygon in it, however deep: an overlay can come back a
        collection holding a multipolygon. Lines and points, the slivers an
        overlay leaves along a shared edge, have no ground to shade."""
        if geom is None or geom.IsEmpty():
            return []
        if ogr.GT_Flatten(geom.GetGeometryType()) != ogr.wkbPolygon:
            return [p for i in range(geom.GetGeometryCount()) for p in self.back(geom.GetGeometryRef(i))]
        rings = []
        for i in range(geom.GetGeometryCount()):
            r = geom.GetGeometryRef(i)
            rings.append([(self.lon0 + r.GetX(j) / self.kx, self.lat0 + r.GetY(j) / self.ky)
                          for j in range(r.GetPointCount())])
        return [rings]


def _union(geoms: list[ogr.Geometry]) -> ogr.Geometry | None:
    out = None
    for g in geoms:
        out = g if out is None else out.Union(g)
    return out


def _area(index: TerritoryIndex, t: Territory, local: _Local, box: ogr.Geometry) -> ogr.Geometry | None:
    """One territory's ground in the box: its rings, even-odd."""
    out = None
    for ring in index.geometry.get(t.rel, []):
        p = local.polygon(ring).MakeValid()
        out = p if out is None else out.SymDifference(p)
    return out.Intersection(box) if out is not None else None


def ground(index: TerritoryIndex, bounds: tuple[float, float, float, float], user: str,
           reach_m: float = REACH_M) -> Ground:
    w, s, e, n = bounds
    local = _Local((w + e) / 2, (s + n) / 2)
    box = local.polygon([(w, s), (e, s), (e, n), (w, n)])
    p = index.permission(bounds, user)
    mine = _union([a for t in p.mine if (a := _area(index, t, local, box)) is not None])
    others = _union([a for t in p.others if (a := _area(index, t, local, box)) is not None])
    if others is not None and mine is not None:
        others = others.Difference(mine)
    if mine is None or others is None:
        return Ground(local.back(mine), [], local.back(others))
    reach = mine.Buffer(reach_m, 8)
    return Ground(local.back(mine), local.back(others.Intersection(reach)), local.back(others.Difference(reach)))
