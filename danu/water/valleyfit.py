"""Valley fit: a valley's contours built again in a lasso, off a surface its
river is the floor of - Shift+E.

A recovery from a coarse DEM leaves a valley's contours stopping short of
where they should run up it, and a chain of small rings at their levels up
the river beyond: each a hollow the old interpolator dug. Absorbing the rings
into their lines one level at a time (E) leaves the levels to argue with one
another - a 30 m taken up the valley meets the 40 m tip it should have gone
under. Built again off one surface, the levels cannot cross.

In the lasso, the levels picked are laid again inside a corridor: within
FLOOR_M of the river, and RING_M round each splinter. Outside it every line
is held where it is drawn, so the valley's sides keep the shape they have;
the levels not picked, and the contours above, are held everywhere. The
surface is a smooth (harmonic) height over the lasso held to:

- each contour held, at its level;
- the river, at its profile: each level placed at the furthest upstream it
  crosses the river - its splinters lie below it, so its line reaches that
  far up the valley - those places kept in order up the levels, linear
  between, and past either end on at the gradient of the stretch next to
  it, but never past half way to the next level, which the river does not
  cross;
- each knoll - a ring whose nearest contour outside is lower - at its level,
  and nothing drawn inside it;
- along the lasso's edge, linear between where the contours and the river
  cross it.

So each level laid leaves the corridor where its old line did, and is
joined to what is held of it there. The splinters inside the corridor go;
a loop the surface makes round a cell or two, smaller than MIN_RING_M2, is
noise and is not laid. Without a river in the lasso there is no floor, and
the throat of the valley comes out raised - the 30 and 40 m carried across
it - so a lasso with none is refused.

Worked by GDAL and numpy, as danu.water.lassofit is, whose solver, cut and
chain it shares. No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core import edits
from ..core.square import is_coastline
from .coastfit import CELL_M, _line, _per_square, _places, _Proj, _vectors, _way_pts
from .lassofit import (
    _FOUR,
    MAX_CELLS,
    MAX_SWEEPS,
    MIN_LINE_CELLS,
    OMEGA,
    SETTLED_M,
    _chain,
    _grow,
    _parts,
    _points,
)
from .overpass import FLOWING

FLOOR_M = 50.0             # the corridor laid again, either side of the river
RING_M = 10.0              # and round each splinter
WINDOW_M = 3000.0          # the river's crossings looked for this far past the lasso
SMALL_M2 = 20000.0         # a ring smaller than this, or
NARROW_M = 100.0           # narrower than this however long, may be a splinter
MIN_RING_M2 = 500.0        # a loop the surface makes smaller than this is noise
JOIN_CELLS = 8.0           # a line laid ends this near its old line's cut end: joined
SNAP_HELD_M = 60.0         # a loose end this near a held stretch of its level is joined to it there
MIN_HELD_M = 80.0          # a line held for less than this between stretches laid is laid too
EDGE_BAND_CELLS = 30       # either side of the lasso's edge, the ground as it was is solved over
HELD_BAND_CELLS = 2.5      # either side of a held line, its level is not drawn again
RIVER_OFF_EDGE_CELLS = 4   # from the lasso's edge, the river is not held
_LOOK_M = (100.0, 300.0, 1000.0)


class Refused(ValueError):
    pass


@dataclass
class Plan:
    """What fitting would do, before it is done."""
    steps: list = field(default_factory=list)        # (square, Compound)
    removed: list = field(default_factory=list)      # what goes, as [(lon, lat)] runs
    added: list = field(default_factory=list)        # what is laid
    outline: list = field(default_factory=list)      # the lasso, and the corridor laid again in it
    levels: list = field(default_factory=list)       # the levels laid
    splinters: int = 0                               # rings gone
    knolls: int = 0                                  # small rings kept as hills
    laid: int = 0                                    # lines laid
    rivers: list = field(default_factory=list)       # the rivers profiled, by name
    pinched: list = field(default_factory=list)      # ([levels], lon, lat): ends joined to nothing
    refused: str | None = None


def plan(working_set, lasso, picked: dict, alloc, report=None, cell_m: float = CELL_M) -> Plan:
    """The levels ``picked`` ({square name: node ids}) holds laid again in
    the ``lasso`` [(lon, lat)], off the surface its river is the floor of.
    ``alloc(square)`` gives the ids."""
    out = Plan()
    try:
        _fit(working_set, lasso, picked, alloc, cell_m, out, report or (lambda s: None))
    except Refused as e:
        out.refused = str(e)
        out.steps.clear()
    return out


# ------------------------------------------------------------------ geometry

def _ogr():
    from osgeo import ogr
    ogr.UseExceptions()
    return ogr


def _scaled(g, kx: float, ky: float):
    """A geometry's coordinates times (kx, ky): degrees to metres, or back."""
    g = g.Clone()
    _scale(g, kx, ky)
    return g


def _scale(g, kx, ky):
    n = g.GetGeometryCount()
    if n:
        for i in range(n):
            _scale(g.GetGeometryRef(i), kx, ky)
        return
    for i in range(g.GetPointCount()):
        x, y = g.GetPoint_2D(i)
        g.SetPoint_2D(i, x * kx, y * ky)


def _ring_poly(pts):
    ogr = _ogr()
    r = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in pts:
        r.AddPoint_2D(float(x), float(y))
    if pts[0] != pts[-1]:
        r.AddPoint_2D(float(pts[0][0]), float(pts[0][1]))
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(r)
    p = p.Buffer(0)
    return p if p is not None and not p.IsEmpty() and p.GetArea() > 0 else None


def small_ring(poly_m) -> bool:
    """Under SMALL_M2, or narrower than NARROW_M however long - twice the
    area over the perimeter, a strip's own width: a valley's piece 600 m up
    it and 76 m across, w-49978846 in N43E029, is 47,000 m2."""
    a = poly_m.GetArea()
    return a < SMALL_M2 or 2 * a / (poly_m.GetBoundary().Length() or 1.0) < NARROW_M


def _rivers(working_set, L):
    """The rivers through the lasso, each a chain of its ways joined end to
    end, by name: [(name, [(lon, lat)])]."""
    pieces = []
    for sq in working_set.squares.values():
        for w in sq.ways.values():
            if w.tags.get('waterway') not in FLOWING or w.tags.get('waterway') == 'riverbank' or len(w.refs) < 2:
                continue
            pts = _way_pts(sq, w)
            if len(pts) >= 2:
                pieces.append((w.tags.get('name') or f'w{w.id}', pts, None))
    chains = _chain(pieces)
    return [(name, pts) for name, pts, _ in chains if _line(pts).Intersects(L)]


def profile(pts, contours, proj: _Proj, window, step: float) -> list:
    """The river's height at each of its points - see the module's account:
    each level at the furthest upstream it crosses, in order, linear between
    and on past the ends, never half way to the next level. None where it
    crosses fewer than two levels."""
    k = np.array([proj.kx, proj.ky])
    xy = np.array(pts) * k
    seg = xy[1:] - xy[:-1]
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    d = np.concatenate([[0.0], np.cumsum(seglen)])
    L2 = np.maximum((seg ** 2).sum(1), 1e-9)
    line = _line(pts)
    cross = []
    for ele, g in contours:
        if not g.Intersects(window):
            continue
        for p in _points(line.Intersection(g)):
            pk = np.array(p) * k
            t = np.clip(((pk - xy[:-1]) * seg).sum(1) / L2, 0, 1)
            q = xy[:-1] + t[:, None] * seg
            i = int(np.argmin(((pk - q) ** 2).sum(1)))
            cross.append((float(d[i] + t[i] * seglen[i]), ele))
    if len({e for _, e in cross}) < 2:
        return [None] * len(pts)
    ds, es = np.array([c[0] for c in cross]), np.array([c[1] for c in cross])
    # upstream is where the crossings are higher: the way's direction says nothing
    up = np.polyfit(ds, es, 1)[0] >= 0
    du = ds if up else d[-1] - ds
    furthest: dict = {}
    for x, e in zip(du, es, strict=True):
        furthest[e] = max(furthest.get(e, -math.inf), float(x))
    placed = []
    for e in sorted(furthest):
        x = furthest[e]
        if placed and x <= placed[-1][0]:
            x = placed[-1][0] + 1.0               # in order up the levels
        placed.append((x, e))
    xs, ys = np.array([p[0] for p in placed]), np.array([p[1] for p in placed])
    lo_g = (ys[1] - ys[0]) / (xs[1] - xs[0])
    hi_g = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    vd = d if up else d[-1] - d
    out = []
    for v in vd:
        if v < xs[0]:
            out.append(max(float(ys[0] - step / 2), float(ys[0] - lo_g * (xs[0] - v))))
        elif v > xs[-1]:
            out.append(min(float(ys[-1] + step / 2), float(ys[-1] + hi_g * (v - xs[-1]))))
        else:
            out.append(float(np.interp(v, xs, ys)))
    return out


# ------------------------------------------------------------------ the fit

def _fit(ws, lasso, picked, alloc, cell_m, out: Plan, say) -> None:
    ogr = _ogr()
    from osgeo import gdal, osr
    gdal.UseExceptions()
    ring = [(float(a), float(b)) for a, b in lasso]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    L = _ring_poly(ring)
    if L is None:
        raise Refused('the lasso has no inside')
    out.outline.append(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    proj = _Proj(lat0)
    k = np.array([proj.kx, proj.ky])

    def to_m(g):
        return _scaled(g, proj.kx, proj.ky)

    def to_deg(g):
        return _scaled(g, 1 / proj.kx, 1 / proj.ky)

    # the levels picked
    levels = set()
    for name, ids in picked.items():
        sq = ws.squares.get(name)
        if sq is None:
            continue
        for w in sq.ways.values():
            if w.ele is not None and not is_coastline(w) and ids.intersection(w.refs):
                levels.add(w.ele)
    if not levels:
        raise Refused('no contour picked: lasso the valley, with the levels to lay again')
    levels = sorted(levels)
    every = sorted({w.ele for sq in ws.squares.values() for w in sq.ways.values() if w.ele is not None})
    steps_ = [b - a for a, b in zip(every, every[1:], strict=False)]
    step = min((s for s in steps_ if s > 0), default=10.0)

    # every contour by the lasso, in degrees and metres
    window_m = to_m(L).Buffer(WINDOW_M, 8)
    near = []                                  # (sq, way, ele, g_deg)
    for sq in ws.squares.values():
        for w in sq.ways.values():
            if w.ele is None or is_coastline(w) or len(w.refs) < 2:
                continue
            pts = _way_pts(sq, w)
            if len(pts) < 2:
                continue
            g = _line(pts)
            if to_m(g).Intersects(window_m):
                near.append((sq, w, w.ele, g))
    window = to_deg(window_m)

    rivers = _rivers(ws, L)
    if not rivers:
        raise Refused('no river in the lasso: its profile is the valley\'s floor - import the water, '
                      'or lasso the valley with its river in it')
    say('fitting the valley: the river\'s profile…')
    contours = [(ele, g) for _, _, ele, g in near]
    profiled = []
    for name, pts in rivers:
        hs = profile(pts, contours, proj, window, step)
        if any(h is not None for h in hs):
            profiled.append((name, pts, hs))
            out.rivers.append(name)
    if not profiled:
        raise Refused('the river in the lasso crosses fewer than two levels: no profile to take its floor from')

    # the splinters and knolls: rings of a level picked, inside the lasso
    in_lasso = [(sq, w, ele, g) for sq, w, ele, g in near if g.Intersects(L)]
    rings_m = []
    knoll_ids = set()
    for sq, w, ele, g in in_lasso:
        if ele not in levels or not w.closed or not L.Contains(g):
            continue
        pm = _ring_poly([tuple(np.array(p) * k) for p in _way_pts(sq, w)])
        if pm is None or not small_ring(pm):
            continue
        # a ring the river runs through is the valley's: the river is below it
        through = any(_line(rp).Intersects(g) or _ring_poly(_way_pts(sq, w)).Contains(_line(rp))
                      for _, rp, _ in profiled)
        if through or _hollow(pm, ele, to_m(g), [(e, to_m(h)) for _, _, e, h in in_lasso if e != ele]):
            rings_m.append(pm)
        else:
            knoll_ids.add((sq.name, w.id))
    river_m = ogr.Geometry(ogr.wkbMultiLineString)
    for _, pts, _ in profiled:
        river_m.AddGeometry(_line([tuple(np.array(p) * k) for p in pts]))
    reach = river_m.Buffer(FLOOR_M, 8)
    for pm in rings_m:
        reach = reach.Union(pm.Buffer(RING_M, 8))
    corridor_m = reach.Intersection(to_m(L))
    if corridor_m is None or corridor_m.IsEmpty():
        raise Refused('the river does not run through the lasso')
    # a line of a level picked that runs along the corridor's edge weaves in
    # and out of it: each stretch it is held for shorter than MIN_HELD_M is
    # taken into the corridor, so its edge cuts only lines that leave it
    picked_m = [to_m(g) for _, w, ele, g in near if ele in levels and g.Intersects(L)]
    for _ in range(3):
        grow = []
        for gm in picked_m:
            if not gm.Intersects(corridor_m):
                continue
            for part in _parts(gm.Difference(corridor_m)):
                pl = _line(part)
                if pl.Length() < MIN_HELD_M and to_m(L).Contains(pl):
                    grow.append(pl.Buffer(2 * cell_m, 4))
        if not grow:
            break
        for g in grow:
            corridor_m = corridor_m.Union(g)
        corridor_m = corridor_m.Intersection(to_m(L))
    corridor = to_deg(corridor_m)

    # what goes: each way of a level picked, inside the corridor - a ring
    # wholly in it whole, a line its stretch in it - and every other way held
    gone, held = [], []
    for sq, w, ele, g in in_lasso:
        if ele in levels and (sq.name, w.id) not in knoll_ids and g.Intersects(corridor):
            gone.append((sq, w, ele, g))
            if w.closed and corridor.Contains(g):
                out.splinters += 1
        else:
            held.append((ele, g))
    out.knolls = len(knoll_ids)
    if not gone:
        raise Refused('no contour of the levels picked along the river in the lasso')

    # the grid
    w_, e_, s_, n_ = L.GetEnvelope()
    wm, hm = (e_ - w_) * proj.kx, (n_ - s_) * proj.ky
    cell = max(cell_m, math.sqrt(max(wm * hm, 1.0) / MAX_CELLS))
    dx, dy = cell / proj.kx, cell / proj.ky
    pad = 3
    x0, y1 = w_ - pad * dx, n_ + pad * dy
    cols = int(math.ceil((e_ - w_) / dx)) + 2 * pad
    rows = int(math.ceil((n_ - s_) / dy)) + 2 * pad
    gt = (x0, dx, 0, y1, 0, -dy)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    def raster(kind):
        r = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, kind)
        r.SetGeoTransform(gt)
        r.SetProjection(srs.ExportToWkt())
        return r

    def burn(geoms, polygons=False):
        r = raster(gdal.GDT_Byte)
        if geoms:
            mem = _vectors()
            lyr = mem.CreateLayer('g', srs, ogr.wkbUnknown)
            for g in geoms:
                f = ogr.Feature(lyr.GetLayerDefn())
                f.SetGeometry(g)
                lyr.CreateFeature(f)
            gdal.RasterizeLayer(r, [1], lyr, burn_values=[1], options=[] if polygons else ['ALL_TOUCHED=TRUE'])
        band = r.GetRasterBand(1)
        a = band.ReadAsArray().astype(bool)
        del band
        return a

    def centre(r, c):
        return x0 + (c + 0.5) * dx, y1 - (r + 0.5) * dy

    inl = burn([L], polygons=True)
    corr = burn([corridor], polygons=True) & inl
    fixed = np.zeros_like(inl)
    val = np.zeros((rows, cols))
    # the held contours, at their levels; and what goes, outside the corridor
    held_at: dict = {}                    # level: the cells its lines are held on
    for ele, g in held:
        c = burn([g]) & inl
        fixed |= c
        val[c] = ele
        held_at[ele] = held_at.get(ele, np.zeros_like(inl)) | c
    for _sq, _w, ele, g in gone:
        # what is held of it, as itself: its cells outside the corridor's
        # raster would take in cells it runs along the edge through
        part = g.Difference(corridor)
        if part is None or part.IsEmpty():
            continue
        c = burn([part]) & inl & ~corr
        fixed |= c
        val[c] = ele
        held_at[ele] = held_at.get(ele, np.zeros_like(inl)) | c
    knoll_in = np.zeros_like(inl)
    for sq, w, _ele, _g in in_lasso:
        if (sq.name, w.id) in knoll_ids:
            knoll_in |= burn([_ring_poly(_way_pts(sq, w))], polygons=True) & inl
    # the river, at its profile
    river_held = np.zeros_like(inl)
    for _name, pts, hs in profiled:
        dense = []
        for (a, ha), (b, hb) in zip(zip(pts, hs, strict=True), zip(pts[1:], hs[1:], strict=True), strict=False):
            if ha is None or hb is None:
                continue
            n = max(1, int(math.hypot((b[0] - a[0]) * proj.kx, (b[1] - a[1]) * proj.ky) / (cell / 2)))
            for j in range(n + 1):
                f = j / n
                dense.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), ha + f * (hb - ha)))
        for lon, lat, hv in dense:
            c, r = int((lon - x0) / dx), int((y1 - lat) / dy)
            if 0 <= r < rows and 0 <= c < cols:
                if inl[r, c] and not fixed[r, c]:
                    fixed[r, c] = True
                    val[r, c] = hv
                    river_held[r, c] = True

    # the lasso's edge: from the ground as it was drawn - a surface held to
    # every contour, splinters and all - so it matches each
    # line where it crosses and bends between as they do. Linear between the
    # crossings, two of one level made the edge flat at it between, and a
    # line was drawn along it that ended nowhere
    say('fitting the valley: the lasso\'s edge…')
    was_fixed = np.zeros_like(inl)
    was_val = np.zeros((rows, cols))
    for _sq, _w, ele, g in near:
        c = burn([g])
        was_fixed |= c
        was_val[c] = ele
    # not the river: its profile is the new floor, and from it the levels
    # crossed the edge where no line of theirs did, with nothing to join
    # only a band along the edge, and from a guess filled in from the held
    # cells: over the whole box, from their mean, it took a minute
    edge_c = inl & _grow(~inl)
    src = raster(gdal.GDT_Byte)
    src.GetRasterBand(1).WriteArray(edge_c.astype(np.uint8))
    dst = raster(gdal.GDT_Float32)
    gdal.ComputeProximity(src.GetRasterBand(1), dst.GetRasterBand(1),
                          ['VALUES=1', 'DISTUNITS=PIXEL', f'NODATA={cols + rows}'])
    from_edge = dst.GetRasterBand(1).ReadAsArray()
    band = from_edge <= EDGE_BAND_CELLS
    # the river let go of next to the edge: held a cell from it at its new
    # floor, the edge at the old ground, a level was squeezed between the two
    # and ran out along the edge
    let_go = river_held & (from_edge <= RIVER_OFF_EDGE_CELLS)
    fixed[let_go] = False
    at_edge = inl & _grow(~inl) & ~fixed
    guess = raster(gdal.GDT_Float32)
    gb = guess.GetRasterBand(1)
    gb.SetNoDataValue(-9999.0)
    gb.WriteArray(np.where(was_fixed, was_val, -9999.0).astype(np.float32))
    gdal.FillNodata(gb, None, maxSearchDist=cols + rows, smoothingIterations=0)
    start = gb.ReadAsArray().astype(np.float64)
    start = np.where(start < -1000, float(was_val[was_fixed].mean()) if was_fixed.any() else 0.0, start)
    was = _solve(was_val, was_fixed & band, band, start=start)
    fixed |= at_edge
    val[at_edge] = was[at_edge]

    # the surface: red-black over-relaxation, from the ground as it was
    say(f'fitting the valley: the height over {int(inl.sum()):,} cells…')
    h = _solve(np.where(fixed, val, start), fixed, inl, start=np.where(band, was, start))

    # each level's line, over the lasso but along its own held lines - the
    # surface is that level there, and its line would be drawn again on the
    # cells it is held on - which is where a line laid stops, at the cut
    def proximity(cells):
        src = raster(gdal.GDT_Byte)
        src.GetRasterBand(1).WriteArray(cells.astype(np.uint8))
        dst = raster(gdal.GDT_Float32)
        gdal.ComputeProximity(src.GetRasterBand(1), dst.GetRasterBand(1),
                              ['VALUES=1', 'DISTUNITS=PIXEL', f'NODATA={cols + rows}'])
        return dst.GetRasterBand(1).ReadAsArray()
    mem = _vectors()
    cl = mem.CreateLayer('c', srs, ogr.wkbLineString)
    cl.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
    cl.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
    # nor along the lasso's edge, held at the ground as it was: a level near
    # it there was drawn along the edge and out of the lasso
    off_edge = from_edge > 1.5
    for ele in levels:
        mask = inl & ~knoll_in & off_edge
        if ele in held_at:
            mask &= proximity(held_at[ele]) > HELD_BAND_CELLS
        hgrid = np.where(mask, h, -9999.0)
        rst = raster(gdal.GDT_Float32)
        rst.GetRasterBand(1).WriteArray(hgrid.astype(np.float32))
        gdal.ContourGenerateEx(rst.GetRasterBand(1), cl,
                               options=[f'FIXED_LEVELS={ele:g}', 'ID_FIELD=0', 'ELEV_FIELD=1', 'NODATA=-9999'])

    def metres(pts):
        return sum(math.hypot((b[0] - a[0]) * proj.kx, (b[1] - a[1]) * proj.ky)
                   for a, b in zip(pts, pts[1:], strict=False))
    lines = []
    for f in cl:
        g = f.GetGeometryRef().SimplifyPreserveTopology(dy / 3)
        for pts in _parts(g):
            if len(pts) < 2 or metres(pts) < MIN_LINE_CELLS * cell:
                continue
            if pts[0] == pts[-1] and len(pts) > 3:
                pg = _ring_poly([tuple(np.array(p) * k) for p in pts])
                if pg is None or pg.GetArea() < MIN_RING_M2:
                    continue                      # a loop round a cell or two: noise
            lines.append((float(f.GetField('ele')), pts))

    # what is held of each way that goes: outside the corridor, cut on its edge
    bound = corridor.Boundary()
    cuts: dict = {}
    by_square: dict = {}
    for sq, w, ele, g in gone:
        for pts in _parts(g.Difference(corridor)):
            for p in (pts[0], pts[-1]):
                pt = ogr.Geometry(ogr.wkbPoint)
                pt.AddPoint_2D(*p)
                if bound.Distance(pt) < 1e-9:
                    cuts[(sq.name, p)] = ele
            by_square.setdefault(sq.name, (sq, [], []))[1].append([ele, pts, w.tags])
        by_square.setdefault(sq.name, (sq, [], []))[2].append(w)
        out.removed += _parts(g.Intersection(corridor))

    taken = set()
    joined = []                           # [level, points, start loose, end loose]
    for ele, pts in lines:
        pts = list(pts)
        free_ends = [False, False]
        if pts[0] != pts[-1]:
            for k_, end in enumerate((0, -1)):
                p = pts[end]
                best, bd = None, None
                for (name, cp), ce in cuts.items():
                    if ce != ele or (name, cp) in taken:
                        continue
                    dd = math.hypot((p[0] - cp[0]) * proj.kx, (p[1] - cp[1]) * proj.ky)
                    if bd is None or dd < bd:
                        best, bd = (name, cp), dd
                if best is not None and bd <= JOIN_CELLS * cell:
                    taken.add(best)
                    if bd < cell:
                        pts[end] = best[1]
                    elif end == 0:
                        pts.insert(0, best[1])
                    else:
                        pts.append(best[1])
                else:
                    free_ends[k_] = True
        joined.append([ele, pts, *free_ends])
    # loose ends of one level near one another, the pieces of a line a scrap
    # held between them cut apart: joined, or the line closed on itself
    reach = 2 * JOIN_CELLS * cell
    while True:
        ends = [(i, e) for i, j in enumerate(joined) if j is not None for e in (0, 1) if j[2 + e]]
        best = None
        for a in range(len(ends)):
            for b in range(a + 1, len(ends)):
                (i, ei), (j, ej) = ends[a], ends[b]
                if joined[i][0] != joined[j][0]:
                    continue
                p = joined[i][1][0 if ei == 0 else -1]
                q = joined[j][1][0 if ej == 0 else -1]
                dd = math.hypot((p[0] - q[0]) * proj.kx, (p[1] - q[1]) * proj.ky)
                if dd <= reach and (best is None or dd < best[0]):
                    best = (dd, i, ei, j, ej)
        if best is None:
            break
        _, i, ei, j, ej = best
        if i == j:                            # its own two ends: a ring
            joined[i][1].append(joined[i][1][0])
            joined[i][2] = joined[i][3] = False
            continue
        a_pts = joined[i][1] if ei == 1 else joined[i][1][::-1]          # ending at the joined end
        b_pts = joined[j][1] if ej == 0 else joined[j][1][::-1]          # starting at it
        a_free = joined[i][2] if ei == 1 else joined[i][3]               # a's other end
        b_free = joined[j][3] if ej == 0 else joined[j][2]
        joined[i] = [joined[i][0], a_pts + b_pts, a_free, b_free]
        joined[j] = None
    # a loose end near a stretch of its level held outside the corridor: the
    # line laid left the corridor elsewhere than its old line was cut, and
    # ran beside it to the band it is not drawn in. Joined to it there, the
    # held stretch cut back to that place, the stub to its cut end dropped -
    # where the join crosses nothing
    held_pieces = [(name, piece) for name, (_sq, pcs, _ws) in by_square.items() for piece in pcs]
    others = [to_m(g) for _, _, _, g in near]
    for j in joined:
        if j is None:
            continue
        for e in (0, 1):
            if not j[2 + e]:
                continue
            p = j[1][0 if e == 0 else -1]
            pm = np.array(p) * k
            best = None
            for name, piece in held_pieces:
                if piece[0] != j[0]:
                    continue
                cut_ends = [i for i in (0, -1) if (name, piece[1][i]) in cuts and (name, piece[1][i]) not in taken]
                if not cut_ends:
                    continue
                xy = np.array(piece[1]) * k
                for i in range(len(xy) - 1):
                    a, b = xy[i], xy[i + 1]
                    ab = b - a
                    t = float(np.clip(((pm - a) * ab).sum() / max((ab * ab).sum(), 1e-9), 0, 1))
                    q = a + t * ab
                    dd = float(np.hypot(*(q - pm)))
                    if dd <= SNAP_HELD_M and (best is None or dd < best[0]):
                        best = (dd, name, piece, i, (q[0] / proj.kx, q[1] / proj.ky), cut_ends)
            if best is None:
                continue
            _, name, piece, i, q, cut_ends = best
            bridge = _line([tuple(pm), (q[0] * proj.kx, q[1] * proj.ky)])
            if any(bridge.Crosses(o) for o in others):
                continue
            pts = piece[1]
            # the side dropped: towards a cut end, the shorter if both are
            keep_start = [*pts[:i + 1], q]          # dropping towards pts[-1]
            keep_end = [q, *pts[i + 1:]]            # dropping towards pts[0]
            options = []
            if -1 in cut_ends:
                options.append((len(pts) - i, keep_start, keep_end, pts[-1]))
            if 0 in cut_ends:
                options.append((i + 1, keep_end, keep_start, pts[0]))
            _, kept_, dropped, cut = min(options, key=lambda o: o[0])
            piece[1] = kept_
            out.removed.append(dropped)
            taken.add((name, cut))
            if e == 0:
                j[1].insert(0, q)
            else:
                j[1].append(q)
            j[2 + e] = False

    loose = []
    for j in joined:
        if j is None:
            continue
        ele, pts, f0, f1 = j
        loose += [(ele, *pts[0])] * f0 + [(ele, *pts[-1])] * f1
        out.added.append(pts)
        out.laid += 1
        for name, part, _closed in _per_square(ws, pts):
            sq = ws.squares[name]
            entry = by_square.setdefault(name, (sq, [], []))
            like = next((t for e, _, t in entry[1] if e == ele), None)
            entry[1].append((ele, part, like))
    out.levels = levels
    out.pinched = _places(loose, proj)
    out.outline += _rings(corridor)

    for name in sorted(by_square, key=str):
        sq, pieces, ways = by_square[name]
        ids = alloc(sq)
        cmds: list = [edits.DeleteWay(w.id) for w in ways]
        for ele, pts, tags in _chain(pieces):
            closed = len(pts) > 3 and pts[0] == pts[-1]
            coords = pts[:-1] if closed else pts
            if len(coords) < 2:
                continue
            wid = ids.take()
            nodes = [ids.take() for _ in coords]
            cmds.append(edits.AddWay(wid, nodes, coords, dict(tags) if tags else
                                     {'contour': 'elevation', 'ele': f'{ele:g}'}))
            if closed:
                cmds.append(edits.ExtendWayWithExisting(wid, True, nodes[0]))
        if cmds:
            out.steps.append((sq, edits.Compound(cmds, name=f'fit the valley in {name}')))


def _solve(h0, fixed, usable, start=None):
    """Red-black over-relaxation of a harmonic height over ``usable``, held
    at ``h0`` where ``fixed``; from ``start``, or the mean held."""
    rows, cols = h0.shape
    free = usable & ~fixed
    h = np.where(fixed, h0, start if start is not None else float(h0[fixed].mean()) if fixed.any() else 0.0)
    h = np.where(usable, h, 0.0).astype(np.float64)
    nb = np.zeros((rows, cols))
    for a, b in _FOUR:
        nb[a] += usable[b]
    rr, cc = np.indices((rows, cols))
    red = free & ((rr + cc) % 2 == 0) & (nb > 0)
    black = free & ((rr + cc) % 2 == 1) & (nb > 0)
    del rr, cc
    s = np.zeros((rows, cols))
    for _ in range(MAX_SWEEPS):
        moved = 0.0
        for mask in (red, black):
            s[:] = 0.0
            for a, b in _FOUR:
                s[a] += h[b]
            dlt = s[mask] / nb[mask] - h[mask]
            h[mask] += OMEGA * dlt
            if dlt.size:
                moved = max(moved, float(np.abs(dlt).max()))
        if moved < SETTLED_M:
            break
    return h


def _rings(g) -> list:
    """The rings of the polygons in a geometry - a union's or intersection's
    answer is a polygon, a multipolygon or a collection - as [(lon, lat)]."""
    out = []
    name = g.GetGeometryName()
    if name == 'POLYGON':
        polys = [g]
    elif name in ('MULTIPOLYGON', 'GEOMETRYCOLLECTION'):
        polys = [g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
        polys = [p for p in polys if p.GetGeometryName() == 'POLYGON']
    else:
        polys = []
    for p in polys:
        for i in range(p.GetGeometryCount()):
            r = p.GetGeometryRef(i)
            out.append([r.GetPoint_2D(j) for j in range(r.GetPointCount())])
    return out


def _hollow(poly_m, ele, line_m, others) -> bool:
    """The nearest contour of another level outside the ring higher than it
    - or none near at all: a small ring alone in a lasso along a river is
    taken for the valley's, not a hill's. What a reach finds stands only within it: a long
    line's envelope comes near where the line does not."""
    for reach in _LOOK_M:
        best, lev = math.inf, None
        e = poly_m.GetEnvelope()
        for oe, g in others:
            f = g.GetEnvelope()
            if f[0] > e[1] + reach or f[1] < e[0] - reach or f[2] > e[3] + reach or f[3] < e[2] - reach:
                continue
            if poly_m.Contains(g):
                continue
            d = line_m.Distance(g)
            if d < best:
                best, lev = d, oe
        if lev is not None and best <= reach:
            return lev > ele
    return True

