#!/usr/bin/env python3
#
# How far the published sea level sits from the shore somebody drew - see
# Admin:Elevation process
#
#   zero_line.py <osm-squares-dir> <contours-<zone>.osm.pbf> [--far 500]
#
# Every ele=0 line in the output should lie on an ele=0 line in the input: the
# contour cutter traces where the DEM crosses zero, and a drawn coastline pins
# it there. A ring which sits a long way from anything drawn was not traced from
# a shore at all - it is where the bounded fill ran out, a kilometre or two off
# an island whose coastline nobody has drawn, and it renders as a sea level
# contour ringing open water.
#
# That is what this measures, in metres, per ring. On zone-axian in August 2026
# it read a median of 1,693 m while coastlines were being dropped by the OSM
# driver, 105 m once they were read, and named the one islet still without a
# shore - a ring whose median was 3,723 m from anything drawn.
#
# It says nothing about a zone with no coastline at all. An inland zone has
# nothing to compare against and is reported as such rather than judged: the
# question here is whether the sea level that was published matches the sea
# level that was drawn, and where none was drawn there is no answer to give.
#
# That applies square by square, not just zone by zone, and it has to. A zone is
# the bounding box of its squares and most of one can be empty - zone-axian is
# 22 drawn squares in 153 degrees - so terrain drawn inland runs out into
# undrawn space and the fill boundary there is a zero line hundreds of
# kilometres from any coast. Real, expected, and nothing to do with a missing
# shore. So only rings inside a square where somebody has drawn sea level are
# judged: there, land without a shore of its own is an inconsistency in the
# mapper's own work rather than an opinion about what the zone ought to be.

import argparse
import glob
import lzma
import math
import os
import re
import sys

import numpy as np

# the squares are held compressed - see danu-build-zone
SQUARE = '*.osm.xz'
NODE = re.compile(rb"<node id=['\"](-?\d+)['\"][^>]*?lat=['\"]([-\d.]+)['\"] "
                  rb"lon=['\"]([-\d.]+)['\"]")
WAY = re.compile(rb'<way\b.*?</way>', re.S)
ND = re.compile(rb"<nd ref=['\"](-?\d+)['\"]")
TAG = re.compile(rb"<tag k=['\"]([^'\"]+)['\"] v=['\"]([^'\"]*)['\"]")

M_PER_DEG_LAT = 111320.0


def drawn_zero_vertices(squares_dir):
    """Every vertex of every ele=0 way across a zone's squares, and the set of
    whole degree squares in which some sea level was drawn."""
    pts = []
    with_shore = set()
    loose = sorted(os.path.basename(p)
                   for p in glob.glob(os.path.join(squares_dir, '*.osm')))
    if loose:
        print(f'  ignoring {len(loose)} uncompressed square(s), '
              f'e.g. {loose[0]} - the squares are held as .osm.xz',
              file=sys.stderr)
    for path in sorted(glob.glob(os.path.join(squares_dir, SQUARE))):
        with lzma.open(path, 'rb') as f:
            data = f.read()
        nodes = {m.group(1): (float(m.group(3)), float(m.group(2)))
                 for m in NODE.finditer(data)}
        for m in WAY.finditer(data):
            chunk = m.group(0)
            if dict(TAG.findall(chunk)).get(b'ele') != b'0':
                continue
            here = [nodes[r] for r in ND.findall(chunk) if r in nodes]
            pts += here
            for lon, lat in here:
                with_shore.add((math.floor(lon), math.floor(lat)))
    return np.array(pts, dtype=float), with_shore


def zero_ways(path):
    """The ele=0 ways of a published contour file, kept whole, as
    [(id, (n, 2) lon/lat)]. osmium only here: the editor's surface checks
    take ``nearest_metres`` from this module and have no osmium."""
    import osmium

    class ZeroWays(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways = []

        def way(self, w):
            if w.tags.get('ele') != '0':
                return
            pts = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
            if pts:
                self.ways.append((w.id, np.array(pts, dtype=float)))

    handler = ZeroWays()
    handler.apply_file(str(path), locations=True)
    return handler.ways


CELL_M = 2000.0


def _grid(reference_m):
    """Reference points bucketed into square cells, for the search below."""
    cells = {}
    keys = np.floor(reference_m / CELL_M).astype(np.int64)
    order = np.lexsort((keys[:, 1], keys[:, 0]))
    keys, pts = keys[order], reference_m[order]
    starts = np.flatnonzero(np.r_[True, (np.diff(keys, axis=0) != 0).any(1)])
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(pts)
        cells[tuple(keys[start])] = pts[start:end]
    return cells


class Nearest:
    """Distance to the nearest of a set of reference points, in metres, the
    index built once and asked as often as wanted - the surface check asks it
    once a stretch of the zero line, and a zone's zero line can be thousands.

    Indexed on a 2 km grid, because the honest version of this is O(n*m) and a
    zone runs to a hundred thousand drawn vertices against fifty thousand
    published ones - 95 seconds for zone-axian, which is too much to hang on
    every build.

    Exact, not approximate. A neighbour found within k cells either side is
    only known to be the nearest if it is closer than k cell widths, since
    anything further out is at least that far away; until it is, the search
    widens a ring of cells at a time. It used to fall back to every reference
    point instead, which a stretch of ground far from any drawn shore made the
    whole of the cost: 193 of 237 s against the 171,561 vertices of an inland
    sea drawn at 0 m.

    Each ask at a latitude of its own, as when the index was built for each:
    the cells are laid out at ``lat`` and a degree of longitude measured at the
    ask's, a cell then narrower or wider than 2 km by as much."""

    def __init__(self, reference, lat):
        self.lat = lat
        self.scale = _scale(lat)
        ref = np.asarray(reference, float).reshape(-1, 2)
        self.cells = _grid(ref * self.scale) if len(ref) else {}
        keys = np.array(list(self.cells), np.int64).reshape(-1, 2)
        self.lo, self.hi = (keys.min(0), keys.max(0)) if len(keys) else (None, None)

    def _ring(self, key, k):
        """The reference points in the cells k from ``key``, every way."""
        x, y = key
        at = ([(x + dx, y + dy) for dx in range(-k, k + 1) for dy in (-k, k)]
              + [(x + dx, y + dy) for dx in (-k, k) for dy in range(-k + 1, k)]) if k else [key]
        return [self.cells[c] for c in at if c in self.cells]

    def __call__(self, points, lat=None):
        """Metres from each point to the nearest reference point, a degree of
        longitude as long as at ``lat`` - the index's own unless given."""
        scale = _scale(self.lat if lat is None else lat)
        ratio = scale / self.scale                 # the index's units to this ask's metres
        width = CELL_M * min(ratio[0], 1.0)        # the narrowest a cell is, in them
        q = np.asarray(points, float).reshape(-1, 2) * scale
        out = np.full(len(q), np.inf)
        if self.lo is None or not len(q):
            return out
        qkeys = np.floor(q / ratio / CELL_M).astype(np.int64)
        # queries grouped by cell, so each neighbourhood is gathered once
        for key in {tuple(k) for k in qkeys}:
            mine = np.flatnonzero((qkeys[:, 0] == key[0]) & (qkeys[:, 1] == key[1]))
            # how many rings out every cell holding a reference point is
            last = int(max(abs(key[0] - self.lo[0]), abs(key[0] - self.hi[0]),
                           abs(key[1] - self.lo[1]), abs(key[1] - self.hi[1])))
            d = out[mine]
            for k in range(last + 1):
                near = self._ring(key, k)
                if near:
                    cand = np.concatenate(near) * ratio
                    d = np.minimum(d, np.hypot(q[mine, None, 0] - cand[None, :, 0],
                                               q[mine, None, 1] - cand[None, :, 1]).min(axis=1))
                if k and (d <= k * width).all():
                    break
            out[mine] = d
        return out


def _scale(lat):
    return np.array([M_PER_DEG_LAT * np.cos(np.radians(lat)), M_PER_DEG_LAT])


def nearest_metres(points, reference, lat):
    """Distance from each point to the nearest reference point, in metres -
    ``Nearest``, for a caller asking once."""
    return Nearest(reference, lat)(points)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('squares_dir')
    ap.add_argument('contours')
    ap.add_argument('--far', type=float, default=500.0,
                    help='metres beyond which a ring is called out (500)')
    ap.add_argument('--rings', type=int, default=10,
                    help='how many rings to list, worst first (10)')
    args = ap.parse_args()

    drawn, with_shore = drawn_zero_vertices(args.squares_dir)
    ways = zero_ways(args.contours)

    published = sum(len(p) for _, p in ways)
    print(f'  drawn ele=0 vertices    {len(drawn):8d}')
    print(f'  published ele=0 vertices{published:8d} in {len(ways)} rings')

    if not len(drawn):
        print('  nothing drawn at sea level in this zone, so nothing to check '
              'against - inland, or a coastline nobody has drawn')
        return
    if not ways:
        print('  no ele=0 in the published contours')
        return

    lat = float(np.mean(np.concatenate([p[:, 1] for _, p in ways])))

    rows, elsewhere, parts = [], 0, []
    for wid, pts in ways:
        # judged vertex by vertex, not ring by ring. A ring can run through many
        # squares - one of them is 2,000 points across two degrees - so asking
        # whether any part of it sits where sea level was drawn pulls the whole
        # thing in, and the far end scores its distance to a shore in another
        # square entirely. That read 238 km once
        keep = np.array([(math.floor(x), math.floor(y)) in with_shore
                         for x, y in pts])
        if not keep.any():
            elsewhere += 1
            continue
        here = pts[keep]
        d = nearest_metres(here, drawn, lat)
        parts.append(d)
        rows.append((float(np.median(d)), float(d.max()), wid, len(here),
                     float(here[:, 0].mean()), float(here[:, 1].mean())))

    print(f'  {len(with_shore)} of the zone\'s squares have sea level drawn in '
          f'them; {elsewhere} rings lie wholly outside those and are not judged')
    if not rows:
        print('  no published ele=0 inside a square with a drawn shore')
        return

    everything = np.concatenate(parts)
    print('  distance from the published zero line to the nearest drawn shore:')
    for p in (50, 75, 90, 95, 99, 100):
        print(f'    p{p:<4} {np.percentile(everything, p):9.1f} m')
    far = int((everything > args.far).sum())
    print(f'  beyond {args.far:.0f} m: {far} of {len(everything)} vertices '
          f'({100 * far / len(everything):.1f}%)')

    rows.sort(reverse=True)
    flagged = [r for r in rows if r[0] > args.far]
    if flagged:
        print(f'  rings whose median is beyond {args.far:.0f} m - land with no '
              f'shore drawn, most likely:')
        for med, mx, wid, n, lon, la in flagged[:args.rings]:
            print(f'    way {wid} {n:6d} pts  median {med:8.1f} m  '
                  f'max {mx:8.1f} m  at {lon:.4f},{la:.4f}')
    else:
        print(f'  every ring sits within {args.far:.0f} m of a drawn shore')


if __name__ == '__main__':
    main()
