"""Fit to the coast inside a lasso: the mainland's low contours laid again in
the land between the coast and the highest level the lasso picked.

``coastfit`` lays an island's low contours again inside its coastline ring.
The mainland's coast doesn't close in the open set, and its contours are long
ways right for nearly all their length - fitting a whole square of it took the
ways out whole and laid levels kilometres up valleys from a coast far away.
So the mapper says where, with a lasso, and how far up the stack: the highest
level of what the lasso picked, the upper level, ``U``.

- Islands wholly inside the lasso are fitted as ``coastfit`` fits them.
- What goes: every other contour below ``U``, where it is inside the lasso -
  but a closed ring wholly inside it, on land and touching no coast, is a
  hill, kept, and laid round.
- The area: the land inside the lasso reached from the coast without crossing
  ``U`` or a hill; bounded by the coast, ``U``, the hills and the lasso.
- In it, on a grid fine enough for a band 50 m wide, a harmonic height: 0 on
  the coast, ``U`` along ``U``, a hill at its level, and along the lasso's
  edge linear between where the coast, ``U`` and the contours that go cross
  it. Solved by red-black over-relaxation from a guess by distance.
- The levels that went are that height's lines. Each leaves the lasso where
  its old line did and is joined to what is kept of it there; an end with no
  room to reach it - where ``U`` comes down to the coast - is said, as
  ``pinched``.

What is laid is a proposal, as ``coastfit``'s is. Nothing here is Qt's.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np

from ..core import edits
from ..core.square import is_coastline, parse_ele
from . import coastfit
from .coastfit import (
    CELL_M,
    Plan,
    _line,
    _ogr,
    _per_square,
    _places,
    _polygon,
    _Proj,
    _Sea,
    _vectors,
    _way_pts,
)

MAX_CELLS = 4_000_000           # a lasso's grid: coarser than CELL_M beyond this
MAX_SWEEPS = 4000               # over-relaxation's sweeps at most
SETTLED_M = 1e-4                # and done when no cell moves more than this in one
OMEGA = 1.9
JOIN_CELLS = 4.0                # a line laid ends this near its old line's cut end: joined
MIN_LINE_CELLS = 4.0            # a line laid shorter than this is noise


class Refused(ValueError):
    """Why the lasso can't be fitted to."""


def upper_of(working_set, picked: dict) -> float | None:
    """The highest level of a contour with a node picked - by the lasso, the
    editor's pick being what it drew round, less what an edit took away."""
    top = None
    for name, ids in picked.items():
        sq = working_set.squares.get(name)
        if sq is None:
            continue
        for w in sq.ways.values():
            if is_coastline(w):
                continue
            ele = parse_ele(w.tags.get('ele'))
            if ele is not None and (top is None or ele > top) and ids.intersection(w.refs):
                top = ele
    return top


def plan(working_set, lasso, picked: dict, alloc, cell_m: float = CELL_M, report=None) -> Plan:
    """What fitting the contours to the coast inside ``lasso`` - a ring of
    (lon, lat) - would do, ``picked`` being what it picked by square.
    ``alloc(square)`` gives the set's id allocator."""
    say = report or (lambda s: None)
    chosen = []
    for name, ids in picked.items():
        sq = working_set.squares.get(name)
        if sq is not None:
            chosen += [(sq, w) for w in sq.ways.values() if is_coastline(w) and ids.intersection(w.refs)]
    if not chosen:
        out = Plan()
        out.refused.append(('no coastline in the lasso', *lasso[0]))
        return out
    islands, refused = coastfit.islands_of(working_set, chosen)

    def whole(isl):
        return all(set(w.refs) <= picked.get(sq.name, set()) for sq, w in isl.ways)
    inside = [i for i in islands if whole(i)]
    out = coastfit.plan(working_set, [isl.ways[0] for isl in inside], alloc, cell_m) if inside else Plan()
    out.refused += [r for r in refused if 'does not close' not in r[0]]
    upper = upper_of(working_set, picked)
    if upper is None:
        out.refused.append(('no contour picked: lasso up to the level to keep the fit under', *lasso[0]))
        return out
    out.upper = upper
    out.outline.append([(float(a), float(b)) for a, b in lasso] + [(float(lasso[0][0]), float(lasso[0][1]))])
    say(f'fitting the coast in the lasso, under {upper:g} m…')
    try:
        _fit(working_set, lasso, upper, inside, out, alloc, cell_m, say)
    except Refused as why:
        xs = [p[0] for p in lasso]
        ys = [p[1] for p in lasso]
        out.refused.append((str(why), (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    return out


def _parts(g) -> list:
    """A line, or the lines of a collection, as [(lon, lat)] runs."""
    if g is None or g.IsEmpty():
        return []
    if g.GetGeometryName() == 'LINESTRING':
        return [[(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())]] if g.GetPointCount() >= 2 else []
    out = []
    for i in range(g.GetGeometryCount()):
        out += _parts(g.GetGeometryRef(i))
    return out


def _points(g) -> list:
    """The points of an intersection: lone points, and a shared stretch's first."""
    name = g.GetGeometryName()
    if name == 'POINT':
        return [(g.GetX(), g.GetY())]
    if name == 'LINESTRING':
        return [(g.GetX(0), g.GetY(0))] if g.GetPointCount() else []
    out = []
    for i in range(g.GetGeometryCount()):
        out += _points(g.GetGeometryRef(i))
    return out


_FOUR = [((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
         ((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
         ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
         ((slice(None), slice(None, -1)), (slice(None), slice(1, None)))]
_DIAG = [((slice(1, None), slice(1, None)), (slice(None, -1), slice(None, -1))),
         ((slice(None, -1), slice(None, -1)), (slice(1, None), slice(1, None))),
         ((slice(1, None), slice(None, -1)), (slice(None, -1), slice(1, None))),
         ((slice(None, -1), slice(1, None)), (slice(1, None), slice(None, -1)))]


def _grow(mask, diag=False):
    g = mask.copy()
    for a, b in _FOUR + (_DIAG if diag else []):
        g[a] |= mask[b]
    return g


def _fit(ws, lasso, U: float, islands, out: Plan, alloc, cell_m: float, say) -> None:
    ogr = _ogr()
    ring = list(lasso) + ([lasso[0]] if tuple(lasso[0]) != tuple(lasso[-1]) else [])
    ring = [(float(a), float(b)) for a, b in ring]
    L = _polygon(ring)
    if not L.IsValid():
        L = L.Buffer(0)
    edge = L.Boundary()
    lat0 = sum(p[1] for p in ring) / len(ring)
    proj = _Proj(lat0)
    k = np.array([proj.kx, proj.ky])
    sea = _Sea(ws, proj)
    isl_ids = {(sq.name, w.id) for isl in islands for sq, w in isl.ways}
    isl_polys = [_polygon(isl.pts) for isl in islands]

    coast, barriers = [], []
    for sq in ws.squares.values():
        for w in sq.ways.values():
            if not is_coastline(w) or len(w.refs) < 2:
                continue
            g = _line(_way_pts(sq, w))
            if not g.Intersects(L):
                continue
            (barriers if (sq.name, w.id) in isl_ids else coast).append(g)
    if not coast:
        if islands:
            return
        raise Refused('no coastline in the lasso')

    uppers, gone, hills = [], [], []
    for sq in ws.squares.values():
        for w in sq.ways.values():
            if is_coastline(w) or (sq.name, w.id) in out.taken:
                continue
            ele = parse_ele(w.tags.get('ele'))
            if ele is None or ele > U:
                continue
            pts = _way_pts(sq, w)
            if len(pts) < 2:
                continue
            g = _line(pts)
            if not g.Intersects(L):
                continue
            if any(p.Intersects(g) for p in isl_polys):
                continue                          # an island's, fitted or kept with it
            if ele == U:
                uppers.append(g)
            elif (pts[0] == pts[-1] and L.Contains(g) and not any(g.Intersects(c) for c in coast)
                  and not sea.at_sea(*pts[0])):
                hills.append((ele, g))
            else:
                gone.append((sq, w, ele, g))
    if not gone:
        if islands:
            return
        raise Refused(f'no contour below {U:g} m in the lasso')
    for u in uppers:
        cut = u.Intersection(L)
        if any(cut.Intersects(c) for c in coast):
            raise Refused(f'{U:g} m, the highest level picked, crosses the coast inside the lasso: '
                          'lasso a level higher')
    levels = sorted({ele for *_, ele, _ in gone})

    # the grid: the lasso's box, square cells in metres
    from osgeo import gdal, osr
    gdal.UseExceptions()
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

    def proximity(cells):
        src = raster(gdal.GDT_Byte)
        src.GetRasterBand(1).WriteArray(cells.astype(np.uint8))
        dst = raster(gdal.GDT_Float32)
        far = float(cols + rows)
        gdal.ComputeProximity(src.GetRasterBand(1), dst.GetRasterBand(1),
                              ['VALUES=1', 'DISTUNITS=PIXEL', f'NODATA={far:.0f}'])
        band = dst.GetRasterBand(1)
        a = band.ReadAsArray().astype(np.float64)
        del band
        return a

    def centre(r, c):
        return x0 + (c + 0.5) * dx, y1 - (r + 0.5) * dy

    inl = burn([L], polygons=True)
    coast_c = burn(coast)
    wall_c = burn(barriers)
    up_c = burn(uppers)
    hill_c: dict = {}
    for ele, g in hills:
        hill_c[ele] = hill_c.get(ele, np.zeros_like(inl)) | burn([g])
    hill_any = np.zeros_like(inl)
    for c in hill_c.values():
        hill_any |= c
    passable = inl & ~coast_c & ~wall_c & ~up_c & ~hill_any

    # the area: 4-connected land in the lasso that the coast touches
    say('fitting the coast in the lasso: the area…')
    lab = np.zeros((rows, cols), dtype=np.int32)
    area = np.zeros_like(inl)
    coast_near = _grow(coast_c)
    n = 0
    for r0, c0 in zip(*np.nonzero(passable), strict=True):
        if lab[r0, c0]:
            continue
        n += 1
        lab[r0, c0] = n
        q = deque([(r0, c0)])
        cells = []
        while q:
            r, c = q.popleft()
            cells.append((r, c))
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < rows and 0 <= cc < cols and passable[rr, cc] and not lab[rr, cc]:
                    lab[rr, cc] = n
                    q.append((rr, cc))
        if not any(coast_near[r, c] for r, c in cells):
            continue
        # land or sea, by a cell clear of the coast
        test = next((rc for rc in cells[::max(1, len(cells) // 64)]
                     if not coast_c[max(rc[0] - 2, 0):rc[0] + 3, max(rc[1] - 2, 0):rc[1] + 3].any()), cells[0])
        if not sea.at_sea(*centre(*test)):
            rs, cs = zip(*cells, strict=True)
            area[list(rs), list(cs)] = True
    if not area.any():
        raise Refused(f'no land between the coast and {U:g} m in the lasso')

    # where the lasso's edge is crossed - by the coast, U and what goes - and
    # the heights along it, linear between
    ex = np.array(ring) * k
    seg = ex[1:] - ex[:-1]
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = float(cum[-1])
    L2 = np.maximum((seg ** 2).sum(1), 1e-9)

    def along(lon, lat):
        p = np.array([lon, lat]) * k
        t = np.clip(((p - ex[:-1]) * seg).sum(1) / L2, 0, 1)
        q = ex[:-1] + t[:, None] * seg
        i = int(np.argmin(((p - q) ** 2).sum(1)))
        return float(cum[i] + t[i] * seglen[i])

    known = []
    for val, geoms in ((0.0, coast), (U, uppers)):
        for g in geoms:
            known += [(along(*p), val) for p in _points(g.Intersection(edge))]
    for *_, ele, g in gone:
        known += [(along(*p), ele) for p in _points(g.Intersection(edge)) if not sea.at_sea(*p)]
    known.sort()
    kt = np.array([t for t, _ in known])
    kv = np.array([v for _, v in known])

    def edge_value(t):
        nk = len(kt)
        i = int(np.searchsorted(kt, t))
        a, b = (i - 1) % nk, i % nk
        ta = kt[a] if i > 0 else kt[a] - total
        tb = kt[b] if i < nk else kt[b] + total
        f = 0.0 if tb == ta else (t - ta) / (tb - ta)
        return float(kv[a] + f * (kv[b] - kv[a]))

    grown = _grow(area, diag=True)
    fixed = np.zeros_like(inl)
    val = np.zeros((rows, cols))
    for cells, v in ((grown & (coast_c | wall_c), 0.0), (grown & up_c & ~coast_c, U)):
        fixed |= cells
        val[cells] = v
    for ele, c in hill_c.items():
        fixed |= grown & c
        val[grown & c] = ele
    at_edge = area & _grow(~inl) & ~fixed
    if len(kt):
        for r, c in zip(*np.nonzero(at_edge), strict=True):
            fixed[r, c] = True
            val[r, c] = edge_value(along(*centre(r, c)))
    free = area & ~fixed
    usable = free | fixed

    say(f'fitting the coast in the lasso: the height over {int(area.sum()):,} cells…')
    dc, du = proximity(fixed & (val <= 1e-9)), proximity(fixed & (val >= U - 1e-9))
    h = np.where(fixed, val, U * dc / np.maximum(dc + du, 1e-9))
    h = np.where(usable, h, 0.0)
    nb = np.zeros((rows, cols))
    for a, b in _FOUR:
        nb[a] += usable[b]
    rr, cc = np.indices((rows, cols))
    red = free & ((rr + cc) % 2 == 0) & (nb > 0)
    black = free & ((rr + cc) % 2 == 1) & (nb > 0)
    del rr, cc
    nb_red, nb_black = nb[red], nb[black]
    s = np.zeros((rows, cols))
    for _ in range(MAX_SWEEPS):
        moved = 0.0
        for mask, nbm in ((red, nb_red), (black, nb_black)):
            s[:] = 0.0
            for a, b in _FOUR:
                s[a] += h[b]
            d = s[mask] / nbm - h[mask]
            h[mask] += OMEGA * d
            if d.size:
                moved = max(moved, float(np.abs(d).max()))
        if moved < SETTLED_M:
            break

    # the levels' lines; a level not laid along a hill of its own
    hgrid = np.where(usable, h, -9999.0)
    for ele, c in hill_c.items():
        if ele in levels:
            hgrid[(proximity(c) <= 1.5) & area] = -9999.0
    rst = raster(gdal.GDT_Float32)
    rst.GetRasterBand(1).WriteArray(hgrid.astype(np.float32))
    mem = _vectors()
    cl = mem.CreateLayer('c', srs, ogr.wkbLineString)
    cl.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
    cl.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
    gdal.ContourGenerateEx(rst.GetRasterBand(1), cl,
                           options=[f'FIXED_LEVELS={",".join(f"{v:g}" for v in levels)}',
                                    'ID_FIELD=0', 'ELEV_FIELD=1', 'NODATA=-9999'])

    def metres(pts):
        return sum(math.hypot((b[0] - a[0]) * k[0], (b[1] - a[1]) * k[1]) for a, b in zip(pts, pts[1:], strict=False))
    lines = []
    for f in cl:
        g = f.GetGeometryRef().SimplifyPreserveTopology(dy / 3)
        for pts in _parts(g):
            if len(pts) >= 2 and metres(pts) >= MIN_LINE_CELLS * cell:
                lines.append((float(f.GetField('ele')), pts))

    # what is kept of each way that goes: outside the lasso, cut on its edge
    cuts: dict = {}                       # (square name, point) -> level
    kept = []                             # (square, level, points, tags)
    for sq, w, ele, g in gone:
        for pts in _parts(g.Difference(L)):
            for p in (pts[0], pts[-1]):
                pt = ogr.Geometry(ogr.wkbPoint)
                pt.AddPoint_2D(*p)
                if edge.Distance(pt) < 1e-9:
                    cuts[(sq.name, p)] = ele
            kept.append((sq, ele, pts, w.tags))

    # each line laid: its ends taken to the cut ends of its level near them
    taken, loose = set(), []
    laid = []
    for ele, pts in lines:
        pts = list(pts)
        if pts[0] != pts[-1]:
            for end in (0, -1):
                p = pts[end]
                best, bd = None, None
                for (name, cp), ce in cuts.items():
                    if ce != ele or (name, cp) in taken:
                        continue
                    d = math.hypot((p[0] - cp[0]) * k[0], (p[1] - cp[1]) * k[1])
                    if bd is None or d < bd:
                        best, bd = (name, cp), d
                if best is not None and bd <= JOIN_CELLS * cell:
                    taken.add(best)
                    if bd < cell:
                        pts[end] = best[1]
                    elif end == 0:
                        pts.insert(0, best[1])
                    else:
                        pts.append(best[1])
                else:
                    loose.append((ele, *p))
        laid.append((ele, pts))

    # by square: the kept pieces and the parts of the lines laid, chained at
    # the cut ends into ways - tags from the way that went
    by_square: dict = {}
    for sq, ele, pts, tags in kept:
        by_square.setdefault(sq.name, (sq, [], []))[1].append((ele, pts, tags))
    for sq, w, _ele, _g in gone:
        by_square.setdefault(sq.name, (sq, [], []))[2].append(w)
    for ele, pts in laid:
        out.added.append(pts)
        out.levels.add(ele)
        out.laid += 1
        for name, part, _closed in _per_square(ws, pts):
            sq = ws.squares[name]
            like = next((t for e, _, t in by_square.get(name, (None, [], []))[1] if e == ele), None)
            by_square.setdefault(name, (sq, [], []))[1].append((ele, part, like))
    for sq, w, _ele, _g in gone:
        out.removed.append(_way_pts(sq, w))
        out.taken.add((sq.name, w.id))
    out.dropped += len(gone)
    out.pinched += _places(loose, proj)
    out.outline += _outline(area, raster, srs)

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
            out.steps.append((sq, edits.Compound(cmds, name=f'fit the contours to the coast in {name}')))


def _chain(pieces) -> list:
    """Runs that share an end point, at one level, joined into ways: (level,
    points, tags), a ring where they close."""
    at: dict = {}
    for i, (ele, pts, _t) in enumerate(pieces):
        for p in (pts[0], pts[-1]):
            at.setdefault((ele, p), []).append(i)
    used: set = set()
    out = []
    for i, (ele, pts, tags) in enumerate(pieces):
        if i in used:
            continue
        used.add(i)
        run = list(pts)
        if run[0] != run[-1]:
            for forward in (True, False):
                while True:
                    p = run[-1] if forward else run[0]
                    nxt = [j for j in at.get((ele, p), []) if j not in used]
                    if not nxt:
                        break
                    j = nxt[0]
                    used.add(j)
                    q = list(pieces[j][1])
                    tags = tags or pieces[j][2]
                    if forward:
                        run += (q if q[0] == p else q[::-1])[1:]
                    else:
                        run = (q if q[-1] == p else q[::-1])[:-1] + run
                    if run[0] == run[-1]:
                        break
                if run[0] == run[-1]:
                    break
        out.append((ele, run, tags))
    return out


def _outline(area, raster, srs) -> list:
    """The area's outline rings, for the map."""
    from osgeo import gdal, ogr
    r = raster(gdal.GDT_Byte)
    r.GetRasterBand(1).WriteArray(area.astype(np.uint8))
    mem = _vectors()
    pl = mem.CreateLayer('a', srs, ogr.wkbPolygon)
    pl.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
    gdal.Polygonize(r.GetRasterBand(1), r.GetRasterBand(1), pl, 0)
    out = []
    for f in pl:
        g = f.GetGeometryRef()
        for i in range(g.GetGeometryCount()):
            ring = g.GetGeometryRef(i)
            out.append([(ring.GetX(j), ring.GetY(j)) for j in range(ring.GetPointCount())])
    return out

