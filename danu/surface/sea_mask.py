#!/usr/bin/env python3
#
# A water mask from the coastline's own direction - see Admin:Elevation process
#
#   sea_mask.py <contours.gpkg> <reference.tif> <out.tif>
#
# Produces exactly what water/<zone>.osm produces by hand for zone-roantra: a
# Byte raster, 1 where there is water, for land_clamp.py to force to zero.
# The difference is where it comes from. A coastline is directed - land on the
# left, water on the right - so the squares already say which side is which, and
# no separate file is needed.
#
# The rule holds in the data: across zone-axian 199 of 199 closed coastline
# rings wind counter-clockwise, and the one which did not turned out to be drawn
# backwards.
#
# Sides rather than rings, because a square's coastline is usually open ways
# running edge to edge rather than closed rings, and open ways enclose nothing.
# Every segment still has a left and a right:
#
#   * seed a cell a little to the left of every segment as land, and one a
#     little to the right as water
#   * every other cell takes the side of whichever seed is nearest
#
# Which side of the nearest coastline you are on, in other words - a side field
# rather than a flood fill. Connectivity was tried first and does not work here:
# a square's coastline ends where the next square has not been drawn, so you can
# walk around the end of it from sea to land. On zone-alved that left the whole
# 2 degree box as seven regions with land and water seeds in the same ones.
#
# Bounded by MAX_CELLS from the coastline, because far from any coast the
# nearest-seed answer means nothing and this must never zero real terrain. The
# plumes it exists to remove all sit within the fill radius of land, so a couple
# of times that is reach enough.

import multiprocessing
import os
import sys

import numpy as np
from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

# how far to step off the line to sample a side, in cells. Far enough to clear
# an all-touched barrier, which can be two cells thick where a line runs
# diagonally, and near enough not to step over something narrow
SIDE_STEP = 2.5
# how far the mask may reach from a coastline, in cells - twice the fill radius
MAX_CELLS = 120


def ogr_memory_driver():
    """The OGR in-memory driver, by whichever name this GDAL calls it."""
    for name in ('MEM', 'Memory'):
        drv = ogr.GetDriverByName(name)
        if drv is not None:
            return drv
    raise RuntimeError('no OGR in-memory driver')


def strips(rows, cols, itemsize=4, budget=256 << 20):
    """Row bands small enough to hold, as land_clamp.py does."""
    per_row = max(1, cols * itemsize)
    height = max(1, min(rows, budget // per_row))
    for y in range(0, rows, height):
        yield y, min(height, rows - y)


def _segments(layer, gt) -> np.ndarray:
    """Every coastline segment of the layer in raster space, as (n, 4) rows of
    col0, row0, col1, row1 - none of no length."""
    out = []
    layer.ResetReading()
    for feat in layer:
        geom = feat.GetGeometryRef()
        if geom is None:
            continue
        parts = ([geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
                 if geom.GetGeometryCount() else [geom])
        for part in parts:
            pts = np.array([part.GetPoint_2D(i) for i in range(part.GetPointCount())], dtype=float)
            if len(pts) < 2:
                continue
            c = (pts[:, 0] - gt[0]) / gt[1]
            r = (pts[:, 1] - gt[3]) / gt[5]
            out.append(np.stack([c[:-1], r[:-1], c[1:], r[1:]], axis=1))
    s = np.concatenate(out) if out else np.zeros((0, 4))
    return s[(s[:, 2] != s[:, 0]) | (s[:, 3] != s[:, 1])]


# the side of the grid of buckets the crossing test files segments in, in
# cells: a step is SIDE_STEP long, so it lies in at most four of them
BUCKET = 8


def _cells(boxes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each (c0, r0, c1, r1) box, the buckets it touches: (owner, key)
    pairs, one per bucket."""
    lo = np.floor(np.minimum(boxes[:, :2], boxes[:, 2:]) / BUCKET).astype(np.int64)
    hi = np.floor(np.maximum(boxes[:, :2], boxes[:, 2:]) / BUCKET).astype(np.int64)
    nx, ny = hi[:, 0] - lo[:, 0] + 1, hi[:, 1] - lo[:, 1] + 1
    n = nx * ny
    owner = np.repeat(np.arange(len(boxes)), n)
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    bx = lo[owner, 0] + k % nx[owner]
    by = lo[owner, 1] + k // nx[owner]
    return owner, (by << 32) + bx


def _odd_crossings(segs: np.ndarray, own: np.ndarray, probes: np.ndarray, chunk: int = 1 << 20) -> np.ndarray:
    """Whether each probe - (c0, r0, c1, r1), from a point on segment
    ``own`` to its seed - crosses the coastline an odd number of times, its
    own segment aside: which is the seed's being on the other side of the
    coastline from the segment it was stepped off.

    Half-open, both ways: a point exactly on a line counts as on its
    negative side, so a probe through a vertex crosses one of the two
    segments meeting there and not both or neither, and a seed exactly on a
    coastline is on one side of it."""
    seg_owner, seg_key = _cells(segs)
    order = np.argsort(seg_key, kind='stable')
    seg_owner, seg_key = seg_owner[order], seg_key[order]
    out = np.zeros(len(probes), dtype=bool)

    def orient(ax, ay, bx, by, cx, cy):
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    for start in range(0, len(probes), chunk):
        pr = probes[start:start + chunk]
        p_owner, p_key = _cells(pr)
        a = np.searchsorted(seg_key, p_key, side='left')
        b = np.searchsorted(seg_key, p_key, side='right')
        n = b - a
        pi = np.repeat(p_owner, n)
        si = seg_owner[np.repeat(a, n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))]
        keep = si != own[start + pi]
        pi, si = pi[keep], si[keep]
        # a segment met in two buckets of one probe is one segment
        pair = np.unique((pi.astype(np.int64) << 32) + si)
        pi, si = pair >> 32, pair & 0xFFFFFFFF
        p, s = pr[pi], segs[si]
        o1 = orient(p[:, 0], p[:, 1], p[:, 2], p[:, 3], s[:, 0], s[:, 1]) > 0
        o2 = orient(p[:, 0], p[:, 1], p[:, 2], p[:, 3], s[:, 2], s[:, 3]) > 0
        o3 = orient(s[:, 0], s[:, 1], s[:, 2], s[:, 3], p[:, 0], p[:, 1]) > 0
        o4 = orient(s[:, 0], s[:, 1], s[:, 2], s[:, 3], p[:, 2], p[:, 3]) > 0
        hit = (o1 != o2) & (o3 != o4)
        out[start:start + len(pr)] = np.bincount(pi[hit], minlength=len(pr)) % 2 == 1
    return out


def seed_points(layer, gt, dropped: list | None = None):
    """Points just off each side of every coastline segment.

    Returns (water, land) as lists of (col, row).

    Work in raster space throughout. Left of travel in map coordinates, where y
    is north, is (-dy, dx). Rows increase southward, so mapping that to (col,
    row) flips the y term and the left normal becomes (drow, -dcol) - not
    (-drow, -dcol), which is the sign error that put both seeds on one side.

    A seed the step to it carries across a coastline is dropped, water and
    land alike. SIDE_STEP is 230 m at 3 arcseconds, and the main map's coast
    has detail far finer: an islet a hundred metres off the shore put its
    sea seeds on the mainland, nearer the ground behind it than the shore's
    own land seeds, and they took a cone of it inland for the sea - gobras'
    N20E086, where the bloom ran five kilometres. Detail finer than the step
    gives no seeds where it is; the shore round it gives plenty. ``dropped``,
    a list, is given how many went, (water, land).
    """
    segs = _segments(layer, gt)
    if not len(segs):
        if dropped is not None:
            dropped[:] = [0, 0]
        return [], []
    d = segs[:, 2:] - segs[:, :2]
    u = d / np.hypot(d[:, 0], d[:, 1])[:, None]
    mid = (segs[:, :2] + segs[:, 2:]) / 2
    left = np.stack([u[:, 1], -u[:, 0]], axis=1)          # land
    own = np.arange(len(segs))
    out = []
    for normal in (-left, left):                          # water, then land
        at = mid + normal * SIDE_STEP
        across = _odd_crossings(segs, own, np.concatenate([mid, at], axis=1))
        cells = np.trunc(at[~across]).astype(np.int64)    # int(), as it always was
        out.append((list(map(tuple, cells.tolist())), int(across.sum())))
    (water, w_gone), (land, l_gone) = out
    if dropped is not None:
        dropped[:] = [w_gone, l_gone]
    return water, land


def proximity_worker(seed_path, out_path, cols, rows, gt, proj):
    """One proximity pass, in its own process. Opens the seed raster by path
    rather than taking a band across the fork."""
    src = gdal.Open(seed_path)
    ds = gdal.GetDriverByName('GTiff').Create(
        out_path, cols, rows, 1, gdal.GDT_Float32,
        options=['TILED=YES', 'COMPRESS=ZSTD', 'PREDICTOR=3', 'ZSTD_LEVEL=1',
                 'BIGTIFF=IF_SAFER'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    # Bounded at MAX_CELLS, because nothing past it is ever read: the mask is
    # (waterdist < landdist) & (waterdist <= MAX_CELLS), so a cell beyond the
    # bound fails the second test whatever the first says, and two cells both
    # beyond it compare equal and fail anyway. Unbounded, these two temporaries
    # are a distinct float per cell over the whole zone and compress barely two
    # to one: on zone-axian, 64801 by 32401, they had reached 4.3 GB each and
    # were heading for 8.4, which filled the disk and took the build with it.
    # Bounded, everything past the coast is one repeated value.
    gdal.ComputeProximity(src.GetRasterBand(1), ds.GetRasterBand(1),
                          ['VALUES=1', 'DISTUNITS=PIXEL',
                           f'MAXDIST={MAX_CELLS + 1}', 'NODATA=30000'])
    ds.FlushCache()
    ds = src = None


def coast_seeds(src_path, gt):
    """Every coastline seed on a grid, as (water, land) arrays of (col, row).
    None when there is no coastline. Those off the raster are kept, and
    ``sea_window`` drops them with everything else outside its reach."""
    src = ogr.Open(str(src_path))
    layer = src.GetLayer(0)
    layer.SetAttributeFilter("natural = 'coastline'")
    if layer.GetFeatureCount() == 0:
        return None
    water, land = seed_points(layer, gt)
    layer = src = None
    return (np.array(water, dtype=np.int64).reshape(-1, 2),
            np.array(land, dtype=np.int64).reshape(-1, 2))


def sea_window(water, land, x0, y0, cols, rows, whole):
    """``sea_mask`` for one window of the raster - cols by rows from (x0, y0)
    on a raster ``whole`` (rows, cols) in size - from ``coast_seeds``.

    The same answer as the whole raster's, because the mask is local: a cell
    is water only with a water seed within MAX_CELLS, and then only if no land
    seed is nearer still - so every seed that can make it water, or stop it
    being, lies within MAX_CELLS of it. A seed beyond the window's reach can
    only be one that would not have been the nearer. The distances are taken
    over the window grown by that much and two more, and read back for the
    window alone."""
    pad = MAX_CELLS + 2
    H, W = whole
    ex0, ey0 = max(0, x0 - pad), max(0, y0 - pad)
    ex1, ey1 = min(W, x0 + cols + pad), min(H, y0 + rows + pad)
    ew, eh = ex1 - ex0, ey1 - ey0
    mem = gdal.GetDriverByName('MEM')

    def distance(points):
        seeds = mem.Create('', ew, eh, 1, gdal.GDT_Byte)
        a = np.zeros((eh, ew), np.uint8)
        p = points[(points[:, 0] >= ex0) & (points[:, 0] < ex1)
                   & (points[:, 1] >= ey0) & (points[:, 1] < ey1)]
        a[p[:, 1] - ey0, p[:, 0] - ex0] = 1
        seeds.GetRasterBand(1).WriteArray(a)
        dist = mem.Create('', ew, eh, 1, gdal.GDT_Float32)
        gdal.ComputeProximity(seeds.GetRasterBand(1), dist.GetRasterBand(1),
                              ['VALUES=1', 'DISTUNITS=PIXEL',
                               f'MAXDIST={MAX_CELLS + 1}', 'NODATA=30000'])
        return dist.GetRasterBand(1).ReadAsArray(x0 - ex0, y0 - ey0, cols, rows)

    dw, dl = distance(water), distance(land)
    return ((dw < dl) & (dw <= MAX_CELLS)).astype(np.uint8)


def sea_mask(src_path, ref_path, out_path, log=None):
    """A water mask from the coastline's direction, on the reference raster's
    grid. Returns False, writing nothing, when the contours carry no
    coastline - the command line's exit 2."""
    say = log if log is not None else (lambda *a: None)
    ref = gdal.Open(ref_path)
    gt, proj = ref.GetGeoTransform(), ref.GetProjection()
    cols, rows = ref.RasterXSize, ref.RasterYSize

    src = ogr.Open(src_path)
    layer = src.GetLayer(0)
    layer.SetAttributeFilter("natural = 'coastline'")
    if layer.GetFeatureCount() == 0:
        say('  no coastline in this zone, no water mask')
        return False
    say(f'  {layer.GetFeatureCount()} coastline ways')

    gone = []
    water_pts, land_pts = seed_points(layer, gt, gone)
    say(f'  {len(water_pts)} water seeds and {len(land_pts)} land; {gone[0]} and {gone[1]} dropped, '
        'stepped across a coastline')

    tmp = {}

    def seed_raster(name, points):
        path = f'{out_path}.{name}.tif'
        tmp[name] = path
        ds = gdal.GetDriverByName('GTiff').Create(
            path, cols, rows, 1, gdal.GDT_Byte,
            options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        band = ds.GetRasterBand(1)
        for y, h in strips(rows, cols, itemsize=1):
            band.WriteArray(np.zeros((h, cols), np.uint8), 0, y)
        for cx, cy in points:
            if 0 <= cx < cols and 0 <= cy < rows:
                band.WriteArray(np.ones((1, 1), np.uint8), cx, cy)
        band.FlushCache()
        return ds, band

    w_ds, w_band = seed_raster('water', water_pts)
    l_ds, l_band = seed_raster('land', land_pts)
    # closed before forking: a GDAL dataset handle does not survive one, and
    # the children open the seeds by path
    w_ds = l_ds = w_band = l_band = None

    # The two proximity passes are the bulk of this script - 439 s of a 1,805 s
    # zone build on makaska, the largest single cost outside isofill. They are
    # independent, one from the water seeds and one from the land, so they run
    # side by side rather than one after the other.
    #
    # Processes rather than threads: gdal.ComputeProximity is one call into C
    # and whether the binding releases the GIL for it is not something to bet
    # the stage on.
    #
    # spawn, not fork, and that is not a preference. GDAL_NUM_THREADS makes
    # GDAL start a worker pool - 23 threads in this process on a 24 core box -
    # and fork carries over only the thread that called it. Any GDAL mutex a
    # different thread happened to hold at that moment is locked for ever in
    # the child, which then blocks in futex_wait and never returns. That is
    # exactly what happened: both children stuck, the parent in do_wait, the
    # stage running 39 minutes against the 7 it had taken. A spawned child is a
    # fresh interpreter with no inherited lock state, for about half a second.
    for name in ('water', 'land'):
        tmp[name + 'dist'] = f'{out_path}.{name}dist.tif'
    ctx = multiprocessing.get_context('spawn')
    jobs = [ctx.Process(
                target=proximity_worker,
                args=(tmp[n], tmp[n + 'dist'], cols, rows, gt, proj))
            for n in ('water', 'land')]
    for j in jobs:
        j.start()
    for j in jobs:
        j.join()
    bad = [j.exitcode for j in jobs if j.exitcode != 0]
    if bad:
        raise RuntimeError(f'sea_mask: a proximity pass failed, exit {bad}')

    wd_ds = gdal.Open(tmp['waterdist'])
    ld_ds = gdal.Open(tmp['landdist'])
    wd_band, ld_band = wd_ds.GetRasterBand(1), ld_ds.GetRasterBand(1)

    out_ds = gdal.GetDriverByName('GTiff').Create(
        out_path, cols, rows, 1, gdal.GDT_Byte,
        options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'])
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_band = out_ds.GetRasterBand(1)

    n_water = 0
    for y, h in strips(rows, cols):
        dw = wd_band.ReadAsArray(0, y, cols, h)
        dl = ld_band.ReadAsArray(0, y, cols, h)
        m = ((dw < dl) & (dw <= MAX_CELLS)).astype(np.uint8)
        out_band.WriteArray(m, 0, y)
        n_water += int(m.sum())
    out_band.FlushCache()
    out_ds = wd_ds = ld_ds = w_ds = l_ds = None
    for p in tmp.values():
        os.unlink(p)

    say(f'  water mask covers {100 * n_water / (rows * cols):.2f}% of the zone')
    return True


def main():
    if len(sys.argv) != 4:
        sys.exit('usage: sea_mask.py <contours.gpkg> <reference.tif> <out.tif>')
    try:
        ok = sea_mask(*sys.argv[1:4], log=lambda *a: print(*a, file=sys.stderr))
    except RuntimeError as e:
        sys.exit(str(e))
    if not ok:
        sys.exit(2)


if __name__ == '__main__':
    main()
