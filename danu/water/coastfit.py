"""Fit to the coast: an island's contours that run out past its coastline
laid again in the land between the coast and the contours that keep off it.

Contours made from one source and a coastline drawn from another disagree
at the shore: on roantra's N43E029, 10, 20 and 30 m ran out to sea round
every island, 2,376 crossings of the coast, and 40 m and up kept inside it.
Pushing a contour back off the coast (``danu.core.crossfix``) cannot help
where three levels have to fit, in order, in the strip below the fourth.

So, an island at a time - its coastline a closed ring in the open set:

- What goes: its contours that cross its coast, and those lying wholly at
  sea beside it - touching no coastline - the low ground run out past the
  shore. Nothing else: every contour of the island that keeps inside it is
  kept, at whatever level, and is what the rest is laid against - a lobe's
  own 40 m hill keeps its ring, and its lower levels are laid up to it.
- The band: the island's land reached from its coast without crossing a
  contour kept.
- In it, on a grid fine enough for a band 50 m wide, a height by where a
  point lies between the coast and the contours kept: ``lu * dc / (dc + du)``,
  ``du`` the distance to the nearest kept contour and ``lu`` the kept levels
  about the point, each weighed by its nearness. An islet with nothing kept
  above what goes is laid up to its highest spot height, or the next level,
  at its point furthest from the shore: ``top * dc / dc_max``. The levels
  that went are that height's contours: 0 at the coast and short of each
  kept level at it, so they keep off both, and off each other. Where a laid
  level is a kept one too, it is not laid along the kept line itself.
- Where a kept contour comes too near the coast for the levels below it to
  pass, a level laid stops there; each place is said, as ``pinched``.

What is laid is a proposal, as a flatten is; accepted, one step across the
squares the island is in. Nothing here is Qt's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core import edits
from ..core.rings import _chains
from ..core.square import SquareName, is_coastline, parse_ele

CELL_M = 3.5                    # the grid's cell: a band 50 m wide is fourteen of them
MAX_CELLS = 16_000_000          # and a big island's coarser, to keep to this
SEA_NEAR_M = 150.0              # a low contour wholly at sea this near an island is its
MIN_RING_CELLS = 4.0            # a ring laid smaller across than this many cells is noise
MIN_LINE_CELLS = 8.0            # and an open line shorter than this, a level squeezed out
PINCH_M = 60.0                  # ends of levels laid nearer each other than this are one place
MIN_NODES = 4


class Refused(ValueError):
    """Why a coastline can't be fitted to."""


@dataclass
class Island:
    """A closed coastline ring of the open set: its nodes in order, land on
    their left, and its coordinates."""
    ways: list                      # (square, way) of the coastline ways it is made of
    pts: np.ndarray                 # (n, 2) lon, lat, closed: the last is the first

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        (w, s), (e, n) = self.pts.min(0), self.pts.max(0)
        return float(w), float(s), float(e), float(n)


@dataclass
class Plan:
    """What fitting would do, before it is done."""
    steps: list = field(default_factory=list)        # (square, Compound)
    removed: list = field(default_factory=list)      # what goes, as [(lon, lat)] runs
    added: list = field(default_factory=list)        # what is laid, as [(lon, lat)] runs
    islands: int = 0
    dropped: int = 0                                 # contours taken out
    laid: int = 0                                    # and laid in their place
    levels: set = field(default_factory=set)         # the levels laid
    tops: list = field(default_factory=list)         # each island's lowest kept level above what goes
    refused: list = field(default_factory=list)      # (why, lon, lat): islands not fitted
    left: int = 0                                    # lines laid that would have crossed, not laid
    pinched: list = field(default_factory=list)      # ([levels], lon, lat): where levels laid stop
    taken: set = field(default_factory=set)          # (square name, way id) of what goes
    upper: float | None = None                       # a lasso's: the level it is fitted under
    outline: list = field(default_factory=list)      # a lasso's: it and its area, as rings


# ------------------------------------------------------------------ islands

def _coast_ways(working_set):
    """Every coastline way of the set, once: (square, way)."""
    seen, out = set(), []
    for sq in working_set.squares.values():
        for w in sq.ways.values():
            if is_coastline(w) and w.id not in seen:
                seen.add(w.id)
                out.append((sq, w))
    return out


def _node(working_set, nid):
    for sq in working_set.squares.values():
        n = sq.nodes.get(nid)
        if n is not None:
            return n
    return None


def islands_of(working_set, chosen) -> tuple[list[Island], list]:
    """The islands the coastline ways ``chosen`` - (square, way) - are of,
    each once, and why any can't be: a coastline that doesn't close in the
    set, or that runs clockwise, round a sea."""
    ways = _coast_ways(working_set)
    by_id = {w.id: (sq, w) for sq, w in ways}
    chains = _chains([w.refs for _, w in ways])
    # which chain each way is in: by its first node, which no other chain holds
    chain_of = {}
    for k, c in enumerate(chains):
        for r in c:
            chain_of.setdefault(r, k)
    out, refused, done = [], [], set()
    for _sq, way in chosen:
        if not way.refs:
            continue
        k = chain_of.get(way.refs[0])
        if k is None or k in done:
            continue
        done.add(k)
        ring = chains[k]
        n0 = _node(working_set, way.refs[0])
        where = (n0.lon, n0.lat) if n0 is not None else (0.0, 0.0)
        if ring[0] != ring[-1] or len(ring) < 4:
            refused.append(('its coastline does not close in the open set - the mainland, or an island '
                            'running out of it: lasso a stretch of it to fit it there', *where))
            continue
        nodes = [_node(working_set, r) for r in ring]
        if any(n is None for n in nodes):
            refused.append(('a node of its coastline is missing', *where))
            continue
        pts = np.array([(n.lon, n.lat) for n in nodes], dtype=float)
        x, y = pts[:, 0], pts[:, 1]
        area = 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
        if area <= 0:
            refused.append(('its coastline runs clockwise: the sea is inside it, not land', *where))
            continue
        members = {r for r in ring}
        mine = [(s, w) for s, w in by_id.values() if w.refs and w.refs[0] in members and w.refs[-1] in members]
        out.append(Island(mine, pts))
    return out, refused


# ------------------------------------------------------------------ geometry

class _Proj:
    """Lon, lat to metres about a latitude, and back."""

    def __init__(self, lat0: float):
        self.kx, self.ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0


def _ogr():
    from osgeo import ogr
    ogr.UseExceptions()
    return ogr


def _vectors():
    """An in-memory vector data source: GDAL 3.11 calls the driver MEM, and
    the 3.10 of Debian 13 Memory."""
    ogr = _ogr()
    for name in ('MEM', 'Memory'):
        drv = ogr.GetDriverByName(name)
        if drv is not None:
            return drv.CreateDataSource('')
    raise RuntimeError('GDAL has no in-memory vector driver')


def _line(pts):
    ogr = _ogr()
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts:
        g.AddPoint_2D(float(x), float(y))
    return g


def _polygon(pts):
    ogr = _ogr()
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in pts:
        ring.AddPoint_2D(float(x), float(y))
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    return p


def _way_pts(sq, way):
    return [(sq.nodes[r].lon, sq.nodes[r].lat) for r in way.refs if r in sq.nodes]


class _Sea:
    """Whether a point is at sea: the side of the nearest coastline segment
    of the set it lies on - land on a coastline's left."""

    def __init__(self, working_set, proj: _Proj):
        segs = []
        for sq, w in _coast_ways(working_set):
            pts = _way_pts(sq, w)
            segs += list(zip(pts, pts[1:], strict=False))
        a = np.array([s[0] for s in segs], dtype=float).reshape(-1, 2)
        b = np.array([s[1] for s in segs], dtype=float).reshape(-1, 2)
        self.k = np.array([proj.kx, proj.ky])
        self.a, self.b = a * self.k, b * self.k

    def at_sea(self, lon: float, lat: float) -> bool:
        if not len(self.a):
            return False
        p = np.array([lon, lat]) * self.k
        d = self.b - self.a
        L2 = (d ** 2).sum(1)
        t = np.clip(((p - self.a) * d).sum(1) / np.where(L2 > 0, L2, 1), 0, 1)
        q = self.a + t[:, None] * d
        i = int(np.argmin(((p - q) ** 2).sum(1)))
        cross = d[i, 0] * (p[1] - self.a[i, 1]) - d[i, 1] * (p[0] - self.a[i, 0])
        return cross < 0                       # on the right: the sea


# ------------------------------------------------------------------ the plan

def plan(working_set, chosen, alloc, cell_m: float = CELL_M) -> Plan:
    """What fitting the islands of the coastline ways ``chosen`` - (square,
    way) - to their coast would do. ``alloc(square)`` gives the id allocator
    for a square. An island that can't be fitted is in ``refused``."""
    out = Plan()
    islands, refused = islands_of(working_set, chosen)
    out.refused += refused
    if not islands:
        return out
    lat0 = sum(i.bounds[1] + i.bounds[3] for i in islands) / (2 * len(islands))
    proj = _Proj(lat0)
    sea = _Sea(working_set, proj)
    coasts = [(g, g.GetEnvelope()) for g in (_line(_way_pts(sq, w)) for sq, w in _coast_ways(working_set))]
    contours = [(sq, w, parse_ele(w.tags.get('ele'))) for sq in working_set.squares.values()
                for w in sq.ways.values() if not is_coastline(w) and parse_ele(w.tags.get('ele')) is not None]
    taken = out.taken                               # (square name, way id) dropped already
    by_square: dict = {}
    for isl in islands:
        try:
            got = _fit(isl, contours, sea, coasts, proj, cell_m, taken, working_set)
        except Refused as why:
            w, s, e, n = isl.bounds
            out.refused.append((str(why), (w + e) / 2, (s + n) / 2))
            continue
        if got is None:
            continue
        dropped, lines, top, left, pinched = got
        out.islands += 1
        out.tops.append(top)
        out.left += left
        out.pinched += pinched
        for sq, w in dropped:
            taken.add((sq.name, w.id))
            by_square.setdefault(sq.name, (sq, [], []))[1].append(w)
            out.removed.append(_way_pts(sq, w))
        out.dropped += len(dropped)
        for ele, pts in lines:
            out.levels.add(ele)
            out.added.append(pts)
            out.laid += 1
            for name, part, closed in _per_square(working_set, pts):
                by_square.setdefault(name, (working_set.squares[name], [], []))[2].append((ele, part, closed))
    for name in sorted(by_square, key=str):
        sq, gone, new = by_square[name]
        ids = alloc(sq)
        cmds: list = [edits.DeleteWay(w.id) for w in gone]
        for ele, pts, closed in new:
            wid = ids.take()
            coords = pts[:-1] if closed else pts
            nodes = [ids.take() for _ in coords]
            cmds.append(edits.AddWay(wid, nodes, coords, {'contour': 'elevation', 'ele': f'{ele:g}'}))
            if closed:
                cmds.append(edits.ExtendWayWithExisting(wid, True, nodes[0]))
        if cmds:
            out.steps.append((sq, edits.Compound(cmds, name=f'fit the contours to the coast in {name}')))
    return out


def _per_square(working_set, pts):
    """A line laid, as the squares of the set hold it: cut at each square's
    edge, (square, points, closed) a piece - a ring in one square stays one."""
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    names = {SquareName(math.floor(x), math.floor(y)) for x, y in zip(lons, lats, strict=True)}
    closed = len(pts) > 3 and pts[0] == pts[-1]
    if len(names) == 1:
        name = next(iter(names))
        return [(name, pts, closed)] if name in working_set.squares else []
    line = _line(pts)
    out = []
    for name in sorted(names, key=str):
        if name not in working_set.squares:
            continue
        w, s, e, n = name.bounds
        part = line.Intersection(_polygon([(w, s), (e, s), (e, n), (w, n), (w, s)]))
        kids = ([part.GetGeometryRef(i) for i in range(part.GetGeometryCount())]
                if part.GetGeometryCount() else [part])
        for g in kids:
            if g.GetGeometryName() == 'LINESTRING' and g.GetPointCount() >= 2:
                out.append((name, [(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())], False))
    return out


def _touches_a_coast(g, coasts) -> bool:
    x0, x1, y0, y1 = g.GetEnvelope()
    return any(not (e[1] < x0 or e[0] > x1 or e[3] < y0 or e[2] > y1) and g.Intersects(c) for c, e in coasts)


def _fit(isl: Island, contours, sea: _Sea, coasts, proj: _Proj, cell_m: float, taken: set, working_set):
    """One island: (the contours dropped, the lines laid as (level, points),
    the band's top, the lines not laid for crossing) - or None, nothing on
    it crossing its coast."""
    land = _polygon(isl.pts)
    shore = _line(isl.pts)
    w, s, e, n = isl.bounds
    pad = SEA_NEAR_M / proj.ky
    near = [(sq, way, ele) for sq, way, ele in contours if (sq.name, way.id) not in taken]
    crossing, inside, at_sea = [], [], []
    for sq, way, ele in near:
        pts = _way_pts(sq, way)
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if max(xs) < w - pad * 1.5 or min(xs) > e + pad * 1.5 or max(ys) < s - pad or min(ys) > n + pad:
            continue
        g = _line(pts)
        if g.Intersects(shore):
            crossing.append((sq, way, ele, pts))
        elif land.Contains(g):
            inside.append((sq, way, ele, pts))
        elif (g.Distance(land) * proj.ky <= SEA_NEAR_M and sea.at_sea(*pts[0])
              and not _touches_a_coast(g, coasts)):
            # wholly at sea: one crossing another island's coast is that
            # island's to fit, not this one's to take away
            at_sea.append((sq, way, ele, pts))
    wrong = crossing + at_sea
    if not wrong:
        return None
    worst = max(ele for _, _, ele, _ in wrong)
    above = sorted({ele for _, _, ele, _ in inside if ele > worst})
    if above:
        top, islet = above[0], False
    else:
        top, islet = _islet_top(working_set, land, isl.bounds, worst, contours), True
    # every contour inside the island that keeps off its coast is kept
    kept = [(ele, pts) for _, _, ele, pts in inside]
    levels = sorted({ele for _, _, ele, _ in wrong})
    grid = _Grid(isl, proj, cell_m)
    band = grid.band([pts for _, pts in kept])
    h = grid.height(band, kept, top, islet, levels)
    lines = grid.contours(h, levels)
    # what would cross the coast or a contour kept is not laid
    keep_lines = [shore] + [_line(p) for _, p in kept]
    same = {}
    for ele, pts in kept:
        same.setdefault(ele, []).append(_line(pts))
    laid, left, pinched = [], 0, []
    reach = 3 * grid.cell / proj.ky
    for ele, pts in lines:
        g = _line(pts)
        if any(g.Intersects(k) for k in keep_lines):
            left += 1
            continue
        laid.append((ele, pts))
        if pts[0] != pts[-1]:
            # an end where it meets its own level kept is a join; any other
            # is where there was no room for it
            for end in (pts[0], pts[-1]):
                p = _ogr().CreateGeometryFromWkt(f'POINT ({end[0]} {end[1]})')
                if not any(k.Distance(p) <= reach for k in same.get(ele, ())):
                    pinched.append((ele, *end))
    return [(sq, way) for sq, way, _, _ in wrong], laid, top, left, _places(pinched, proj)


def _places(ends, proj: _Proj) -> list:
    """The ends of levels laid where there was no room, as places: those
    within PINCH_M of one another one place - the levels that stop at a neck
    stop there together, each twice, one end from either side - as
    ([levels], lon, lat)."""
    places: list = []
    for ele, lon, lat in ends:
        for p in places:
            if math.hypot((p[1] - lon) * proj.kx, (p[2] - lat) * proj.ky) <= PINCH_M:
                if ele not in p[0]:
                    p[0].append(ele)
                break
        else:
            places.append([[ele], lon, lat])
    return [(sorted(levels), lon, lat) for levels, lon, lat in places]


def _islet_top(working_set, land, bounds, worst: float, contours) -> float:
    """An islet's top, with no contour of its own above what crosses its
    coast: its highest spot height above that, or the ladder's next level up
    - the set's levels above it, or the step between the ones that cross."""
    ogr = _ogr()
    w, s, e, n = bounds
    spots = []
    for sq in working_set.squares.values():
        for nd in sq.nodes.values():
            if 'ele' not in nd.tags or not (w <= nd.lon <= e and s <= nd.lat <= n):
                continue
            h = parse_ele(nd.tags.get('ele'))
            pt = ogr.Geometry(ogr.wkbPoint)
            pt.AddPoint_2D(nd.lon, nd.lat)
            if h is not None and h > worst and land.Contains(pt):
                spots.append(h)
    if spots:
        return max(spots)
    ladder = sorted({ele for *_, ele in contours})
    higher = [v for v in ladder if v > worst]
    if higher:
        return higher[0]
    lower = [v for v in ladder if v < worst]
    return worst + (worst - lower[-1] if lower else 10.0)


class _Grid:
    """An island's grid: square cells in metres over its rectangle, a few
    cells round it."""

    def __init__(self, isl: Island, proj: _Proj, cell_m: float):
        from osgeo import gdal, osr
        gdal.UseExceptions()
        w, s, e, n = isl.bounds
        wm, hm = (e - w) * proj.kx, (n - s) * proj.ky
        cell = max(cell_m, math.sqrt(max(wm * hm, 1.0) / MAX_CELLS))
        self.cell = cell
        self.dx, self.dy = cell / proj.kx, cell / proj.ky
        m = 4
        self.cols = int(math.ceil((e - w) / self.dx)) + 2 * m
        self.rows = int(math.ceil((n - s) / self.dy)) + 2 * m
        self.x0, self.y1 = w - m * self.dx, n + m * self.dy
        self.gt = (self.x0, self.dx, 0, self.y1, 0, -self.dy)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        self.srs = srs
        self.isl = isl
        self._land = self._burn([_polygon(isl.pts)], polygons=True)
        self._coast = self._burn([_line(isl.pts)])

    def _raster(self, kind):
        from osgeo import gdal
        r = gdal.GetDriverByName('MEM').Create('', self.cols, self.rows, 1, kind)
        r.SetGeoTransform(self.gt)
        r.SetProjection(self.srs.ExportToWkt())
        return r

    def _burn(self, geoms, polygons=False) -> np.ndarray:
        from osgeo import gdal, ogr
        r = self._raster(gdal.GDT_Byte)
        mem = _vectors()
        lyr = mem.CreateLayer('g', self.srs, ogr.wkbUnknown)
        for g in geoms:
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetGeometry(g)
            lyr.CreateFeature(f)
        gdal.RasterizeLayer(r, [1], lyr, burn_values=[1], options=[] if polygons else ['ALL_TOUCHED=TRUE'])
        band = r.GetRasterBand(1)
        out = band.ReadAsArray().astype(bool)
        del band
        return out

    def _distance(self, cells: np.ndarray) -> np.ndarray:
        """Each cell's distance, in cells, to the nearest of ``cells``."""
        from osgeo import gdal
        src = self._raster(gdal.GDT_Byte)
        src.GetRasterBand(1).WriteArray(cells.astype(np.uint8))
        dst = self._raster(gdal.GDT_Float32)
        far = float(self.cols + self.rows)
        gdal.ComputeProximity(src.GetRasterBand(1), dst.GetRasterBand(1),
                              ['VALUES=1', 'DISTUNITS=PIXEL', f'NODATA={far:.0f}'])
        band = dst.GetRasterBand(1)
        out = band.ReadAsArray()
        del band
        return out

    def band(self, kept) -> np.ndarray:
        """The island's land reached from its coast without crossing a kept
        contour: the regions of land and no kept line, 4-connected, that the
        coast - a cell wider, its cells being mostly at sea - touches."""
        from osgeo import gdal, ogr
        lines = self._burn([_line(p) for p in kept]) if kept else np.zeros_like(self._land)
        self._kept = lines
        passable = self._land & ~lines
        src = self._raster(gdal.GDT_Byte)
        src.GetRasterBand(1).WriteArray(passable.astype(np.uint8))
        mem = _vectors()
        regions = mem.CreateLayer('r', self.srs, ogr.wkbPolygon)
        regions.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
        gdal.Polygonize(src.GetRasterBand(1), src.GetRasterBand(1), regions, 0)
        regions.CreateField(ogr.FieldDefn('k', ogr.OFTInteger))
        for k, f in enumerate(regions):
            f.SetField('k', k + 1)
            regions.SetFeature(f)
        lab = self._raster(gdal.GDT_Int32)
        gdal.RasterizeLayer(lab, [1], regions, options=['ATTRIBUTE=k'])
        b = lab.GetRasterBand(1)
        labels = b.ReadAsArray()
        del b
        c = self._coast
        wide = c.copy()
        wide[1:, :] |= c[:-1, :]
        wide[:-1, :] |= c[1:, :]
        wide[:, 1:] |= c[:, :-1]
        wide[:, :-1] |= c[:, 1:]
        touched = np.unique(labels[wide & passable])
        return passable & np.isin(labels, touched[touched > 0])

    def height(self, band, kept, top: float, islet: bool, laid=()) -> np.ndarray:
        """The band's heights: by the coast and the kept contours bordering
        the band, each level weighed by its nearness - or an islet's, up to
        ``top`` at its point furthest from the shore. ``kept`` is (level,
        points); ``laid`` the levels to be laid, which are not laid along a
        kept line of their own level."""
        dc = self._distance(self._coast)
        near_own = np.zeros_like(band)
        by_level: dict = {}
        for ele, pts in kept:
            by_level.setdefault(ele, []).append(pts)
        cells = {ele: self._burn([_line(p) for p in pl]) for ele, pl in by_level.items()}
        # the levels whose lines border the band: those the band is laid against
        grown = band.copy()
        grown[1:, :] |= band[:-1, :]
        grown[:-1, :] |= band[1:, :]
        grown[:, 1:] |= band[:, :-1]
        grown[:, :-1] |= band[:, 1:]
        bordering = [ele for ele, c in cells.items() if (c & grown).any()]
        if islet or not bordering:
            with np.errstate(invalid='ignore', divide='ignore'):
                peak = float(dc[band].max()) if band.any() else 1.0
                h = top * dc / max(peak, 1.0)
        else:
            dist = {ele: self._distance(cells[ele]) for ele in bordering}
            du = np.minimum.reduce([dist[e] for e in bordering])
            weight = {e: 1.0 / (dist[e] + 0.5) ** 4 for e in bordering}
            total = np.add.reduce([weight[e] for e in bordering])
            lu = np.add.reduce([e * weight[e] for e in bordering]) / total
            with np.errstate(invalid='ignore', divide='ignore'):
                h = lu * dc / (dc + du)
            h[(dc + du) == 0] = lu[(dc + du) == 0] / 2
            for ele in laid:
                if ele in dist:
                    near_own |= dist[ele] <= 1.5
                elif ele in cells:
                    near_own |= self._distance(cells[ele]) <= 1.5
        # land beyond the band is no height at all - a value beside the sea
        # would draw every level along the coast - and the sea is below 0;
        # and a level laid is no height beside its own kept line
        h = np.where(band, h, np.where(self._land, -9999.0, -10.0))
        h[band & near_own] = -9999.0
        return h.astype(np.float32)

    def contours(self, h: np.ndarray, levels) -> list:
        """The levels' lines through ``h``, as (level, [(lon, lat)]), thinned
        to a third of a cell, the rings smaller than a few cells left out."""
        from osgeo import gdal, ogr
        r = self._raster(gdal.GDT_Float32)
        r.GetRasterBand(1).WriteArray(h)
        mem = _vectors()
        lyr = mem.CreateLayer('c', self.srs, ogr.wkbLineString)
        lyr.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
        lyr.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
        gdal.ContourGenerateEx(r.GetRasterBand(1), lyr,
                               options=[f'FIXED_LEVELS={",".join(f"{v:g}" for v in levels)}',
                                        'ID_FIELD=0', 'ELEV_FIELD=1', 'NODATA=-9999'])
        tol = self.dy / 3
        out = []
        for f in lyr:
            g = f.GetGeometryRef().SimplifyPreserveTopology(tol)
            if g.GetGeometryName() != 'LINESTRING' or g.GetPointCount() < MIN_NODES:
                continue
            pts = [(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())]
            if pts[0] == pts[-1]:
                x0, x1, y0, y1 = g.GetEnvelope()
                if max((x1 - x0) / self.dx, (y1 - y0) / self.dy) < MIN_RING_CELLS:
                    continue
            elif sum(math.hypot((b[0] - a[0]) / self.dx, (b[1] - a[1]) / self.dy)
                     for a, b in zip(pts, pts[1:], strict=False)) < MIN_LINE_CELLS:
                continue
            out.append((float(f.GetField('ele')), pts))
        return out
