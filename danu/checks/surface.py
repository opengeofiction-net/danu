"""What only a built surface can say - H2, three rows of the validation table:

- **rivers which climb** (R29), on the DEM: a waterway sampled along the
  surface, and the climb it cannot lose whichever way the water runs - the
  smaller of its ascent and its descent, `checks.rivers`' irreducible ascent.
  The grade's climbs are the contours'; this is the ground's. 10 m or more:
  1,601 waterways on the gobras 3x3 after phase 5's burn, 477 climbing a metre
  or more where the surface's own rounding reaches, 162 ten. One that climbs
  most of the way and falls little is said apart: drawn backwards, likely.
- **sea level off the drawn coastline** (R32), `checks.zero_line`'s question:
  the DEM's zero line, a stretch of it over a kilometre long and more than
  500 m from any `ele=0` vertex drawn, in a square where sea level is drawn.
  Only well inside the drawn area: outside it the surface is 0, so the drawn
  envelope's own edge is a zero line, and on gobras it was two stretches of 184
  and 114 km, up to 60 km from any shore, saying nothing.
- **unreached ground** (R20), as area and fraction, a row a square: the first
  pass's nothing-in-reach, which the overlay draws.

Asked of the build's own grids, on the build's worker, from a snapshot of the
squares taken on the UI thread as the build started - so of the state that
was built. No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.profile import densify, invalid_intervals, seg_lengths
from ..core.square import parse_ele
from .files import Finding

CLIMB_MIN = 10.0                 # metres of a river's climb it cannot lose either way round
FAR_M = 500.0                    # a zero line this far from a drawn shore
RUN_MIN_M = 1000.0               # for this long
INSET = 2                        # cells of drawn area either side of it

FLOWING_LINES = ('river', 'stream', 'canal', 'ditch', 'drain')


@dataclass
class Snapshot:
    """What the checks read of the squares, as they were built."""
    waterways: list = field(default_factory=list)    # (square, id, name, kind, (n, 2) lon/lat)
    zero: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))   # drawn ele=0 vertices
    shore: set = field(default_factory=set)          # degree squares with sea level drawn
    squares: list = field(default_factory=list)      # the set's names


def snapshot(working_set) -> Snapshot:
    s = Snapshot(squares=list(working_set.squares))
    zero = []
    for sq in working_set.squares.values():
        for w in sq.ways.values():
            kind = w.tags.get('waterway')
            if kind in FLOWING_LINES:
                pts = [(sq.nodes[r].lon, sq.nodes[r].lat) for r in w.refs if r in sq.nodes]
                if len(pts) >= 2:
                    s.waterways.append((sq.name, w.id, w.tags.get('name'), kind, np.array(pts)))
            elif parse_ele(w.tags.get('ele')) == 0:
                for r in w.refs:
                    n = sq.nodes.get(r)
                    if n is not None:
                        zero.append((n.lon, n.lat))
                        s.shore.add((math.floor(n.lon), math.floor(n.lat)))
    s.zero = np.array(zero, float).reshape(-1, 2)
    return s


def _cells(gt, lon, lat):
    return ((np.asarray(lon) - gt[0]) / gt[1]).astype(int), ((np.asarray(lat) - gt[3]) / gt[5]).astype(int)


# --------------------------------------------------------------- R29

def climbs(snap: Snapshot, dem: np.ndarray, gt: tuple, least: float = CLIMB_MIN) -> list[Finding]:
    out = []
    for square, wid, name, kind, pts in snap.waterways:
        dense = np.asarray(densify([tuple(p) for p in pts], abs(gt[1])))
        c, r = _cells(gt, dense[:, 0], dense[:, 1])
        ok = (c >= 0) & (c < dem.shape[1]) & (r >= 0) & (r < dem.shape[0])
        if ok.sum() < 2:
            continue
        e = np.full(len(dense), np.nan)
        e[ok] = dem[r[ok], c[ok]]
        d = np.diff(e)
        up, down = float(np.nansum(d[d > 0])), abs(float(np.nansum(d[d < 0])))    # abs: not '-0 m'
        what = f'{kind} "{name}"' if name else kind
        if up > down and up >= least and min(up, down) < 0.25 * up:
            # it climbs most of its way and falls little: drawn the wrong way round
            mid = dense[len(dense) // 2]
            out.append((up, Finding(square, 'backwards', f'{what}, way {wid} - climbs {up:,.0f} m, falls {down:,.0f} m',
                               'a waterway is drawn downstream; this one climbs where it should fall - drawn '
                               'the wrong way round, most likely: reverse it, rather than move the contours',
                               float(mid[0]), float(mid[1]), _box(pts), way=wid)))
            continue
        lost = min(up, down)
        if lost < least:
            continue
        # where: the run that climbs highest above the lowest the river had been
        runs = invalid_intervals(e)
        if runs:
            seg = seg_lengths(dense)
            worst = max(runs, key=lambda iv: np.nanmax(e[iv[0]:iv[1] + 1]) - e[max(iv[0] - 1, 0)])
            i0, i1 = worst
            rise = float(np.nanmax(e[i0:i1 + 1]) - e[max(i0 - 1, 0)])
            km = float(seg[i0:i1 + 1].sum()) / 1000
            at = dense[(i0 + i1) // 2]
            box = _box(dense[i0:i1 + 2])
            where = f', the most {rise:,.0f} m over {km:,.1f} km'
        else:
            at, box, where = dense[len(dense) // 2], _box(pts), ''
        out.append((lost, Finding(square, 'climb', f'{what}, way {wid} - climbs {lost:,.0f} m it cannot lose{where}',
                           'the surface climbs where the water runs: the contours say the ground rises across '
                           'its course - burn the climb (B) or mend the contours',
                           float(at[0]), float(at[1]), box, way=wid)))
    # worst first: the climb the ground holds, the climb drawn the wrong way
    return [f for _, f in sorted(out, key=lambda kf: -kf[0])]


def _box(pts) -> tuple:
    p = np.asarray(pts)
    return float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())


# --------------------------------------------------------------- R32

def sea_off_shore(snap: Snapshot, dem_path: Path, mask: np.ndarray, gt: tuple) -> list[Finding]:
    if not len(snap.zero):
        return []                          # inland: nothing drawn at sea level to compare with
    from osgeo import gdal, ogr

    from .zero_line import nearest_metres
    gdal.UseExceptions()
    ds = gdal.Open(str(dem_path))
    src = ogr.GetDriverByName('MEM').CreateDataSource('zero')
    layer = src.CreateLayer('zero')
    layer.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
    # between the sea's 0 and the land's 1 m, where the clamp puts the lowest land
    gdal.ContourGenerate(ds.GetRasterBand(1), 0, 0, [0.5], 0, 0, layer, -1, 0)
    rows, cols = mask.shape
    out = []
    for feat in layer:
        P = np.array(feat.GetGeometryRef().GetPoints(), float)[:, :2]
        if len(P) < 2:
            continue
        c, r = _cells(gt, P[:, 0], P[:, 1])
        judged = np.array([(math.floor(x), math.floor(y)) in snap.shore for x, y in P])
        # well inside the drawn area: every cell INSET either side in it
        for dy in (-INSET, INSET):
            for dx in (-INSET, INSET):
                rr, cc = np.clip(r + dy, 0, rows - 1), np.clip(c + dx, 0, cols - 1)
                judged &= mask[rr, cc] > 0
        if not judged.any():
            continue
        d = np.zeros(len(P))
        d[judged] = nearest_metres(P[judged], snap.zero, float(P[:, 1].mean()))
        far = judged & (d > FAR_M)
        i = 0
        while i < len(P):
            if not far[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(P) and far[j + 1]:
                j += 1
            seg = P[i:j + 1]
            length = float(seg_lengths(seg).sum()) if len(seg) > 1 else 0.0
            if length >= RUN_MIN_M:
                at = seg[len(seg) // 2]
                worst = float(d[i:j + 1].max())
                out.append((worst, Finding(
                    _square_of(snap, at), 'sea',
                    f'sea level {worst / 1000:,.1f} km from a drawn shore, for {length / 1000:,.1f} km',
                    'the surface reaches sea level here, well inside the drawn area and away from any coastline '
                    'drawn: the fill running out rather than meeting a shore - an island or a coast with no '
                    'coastline, or contours that stop short',
                    float(at[0]), float(at[1]), _box(seg))))
            i = j + 1
    return [f for _, f in sorted(out, key=lambda kf: -kf[0])]


def _square_of(snap, at):
    lon, lat = math.floor(at[0]), math.floor(at[1])
    return next((n for n in snap.squares if (n.lon, n.lat) == (lon, lat)), snap.squares[0] if snap.squares else None)


# --------------------------------------------------------------- R20

def unreached(snap: Snapshot, classes: np.ndarray, gt: tuple) -> list[Finding]:
    """A row a square with ground the first pass had nothing in reach of:
    its area, and its share of the square's drawn area."""
    from ..surface.build import OUTSIDE, UNREACHED
    rows, cols = classes.shape
    lat_rows = gt[3] + (np.arange(rows) + 0.5) * gt[5]
    cell_km2 = (abs(gt[1]) * 111.32) * (abs(gt[5]) * 111.32) * np.cos(np.radians(lat_rows))
    out = []
    for name in snap.squares:
        c0, r0 = _cells(gt, name.lon, name.lat + 1)
        c1, r1 = _cells(gt, name.lon + 1, name.lat)
        c0, r0 = max(int(c0), 0), max(int(r0), 0)
        c1, r1 = min(int(c1), cols), min(int(r1), rows)
        if c1 <= c0 or r1 <= r0:
            continue
        block = classes[r0:r1, c0:c1]
        k = cell_km2[r0:r1]
        inside = ((block != OUTSIDE).sum(axis=1) * k).sum()
        none = ((block == UNREACHED).sum(axis=1) * k).sum()
        if none <= 0 or inside <= 0:
            continue
        share = 100 * none / inside
        ys, xs = np.nonzero(block == UNREACHED)
        at = (gt[0] + (c0 + xs.mean() + 0.5) * gt[1], gt[3] + (r0 + ys.mean() + 0.5) * gt[5])
        out.append((none, Finding(name, 'unreached', f'{none:,.1f} km² unreached, {share:.1f}% of the drawn area',
                           'ground in the drawn area the first pass had no contour in reach of: the surface '
                           'there is the second pass carrying values across it - the overlay shows where',
                           float(at[0]), float(at[1]), (name.lon, name.lat, name.lon + 1, name.lat + 1))))
    return [f for _, f in sorted(out, key=lambda kf: -kf[0])]


def find(snap: Snapshot, work: Path) -> list[Finding]:
    """Every surface check, from the grids a build left in ``work``."""
    from osgeo import gdal
    gdal.UseExceptions()
    work = Path(work)
    dem_ds = gdal.Open(str(work / 'dem.tif'))
    gt = dem_ds.GetGeoTransform()
    dem = dem_ds.GetRasterBand(1).ReadAsArray().astype('f8')
    nodata = dem_ds.GetRasterBand(1).GetNoDataValue()
    if nodata is not None:
        dem[dem == nodata] = np.nan
    mask_ds = gdal.Open(str(work / 'drawn-mask.tif'))       # held: a band outlives no dataset
    mask = mask_ds.GetRasterBand(1).ReadAsArray()
    out = climbs(snap, dem, gt)
    out += sea_off_shore(snap, work / 'dem.tif', mask, gt)
    classes_path = work / 'first-pass.tif'
    if classes_path.exists():
        cds = gdal.Open(str(classes_path))
        out += unreached(snap, cds.GetRasterBand(1).ReadAsArray(), cds.GetGeoTransform())
    return out
