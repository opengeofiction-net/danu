#!/usr/bin/env python3
#
# How far the published sea level sits from the shore somebody drew - see
# Admin:Elevation process
#
#   demCheckZeroLine.py <osm-squares-dir> <contours-<zone>.osm.pbf> [--far 500]
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
import osmium

# the squares are held compressed - see buildDemZone.sh
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


class ZeroWays(osmium.SimpleHandler):
    """The ele=0 ways of a published contour file, kept whole."""

    def __init__(self):
        super().__init__()
        self.ways = []

    def way(self, w):
        if w.tags.get('ele') != '0':
            return
        pts = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        if pts:
            self.ways.append((w.id, np.array(pts, dtype=float)))


def nearest_metres(points, reference, lat):
    """Distance from each point to the nearest reference point, in metres.

    Chunked rather than indexed: a zone runs to a few hundred thousand drawn
    vertices against a few thousand published ones, which is seconds, and a
    spatial index is a dependency for no gain at that size."""
    m_lon = M_PER_DEG_LAT * np.cos(np.radians(lat))
    out = np.full(len(points), np.inf)
    for i in range(0, len(reference), 4096):
        chunk = reference[i:i + 4096]
        dx = (points[:, None, 0] - chunk[None, :, 0]) * m_lon
        dy = (points[:, None, 1] - chunk[None, :, 1]) * M_PER_DEG_LAT
        out = np.minimum(out, np.hypot(dx, dy).min(axis=1))
    return out


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
    handler = ZeroWays()
    handler.apply_file(args.contours, locations=True)

    published = sum(len(p) for _, p in handler.ways)
    print(f'  drawn ele=0 vertices    {len(drawn):8d}')
    print(f'  published ele=0 vertices{published:8d} in {len(handler.ways)} rings')

    if not len(drawn):
        print('  nothing drawn at sea level in this zone, so nothing to check '
              'against - inland, or a coastline nobody has drawn')
        return
    if not handler.ways:
        print('  no ele=0 in the published contours')
        return

    lat = float(np.mean(np.concatenate([p[:, 1] for _, p in handler.ways])))

    rows, elsewhere = [], 0
    for wid, pts in handler.ways:
        # judged only where sea level was drawn - see the head of this file
        squares = {(math.floor(x), math.floor(y)) for x, y in pts}
        if not (squares & with_shore):
            elsewhere += 1
            continue
        d = nearest_metres(pts, drawn, lat)
        rows.append((float(np.median(d)), float(d.max()), wid, len(pts),
                     float(pts[:, 0].mean()), float(pts[:, 1].mean())))

    print(f'  {len(with_shore)} of the zone\'s squares have sea level drawn in '
          f'them; {elsewhere} rings lie outside those and are not judged')
    if not rows:
        print('  no published ele=0 inside a square with a drawn shore')
        return

    judged = [(wid, p) for wid, p in handler.ways
              if {(math.floor(x), math.floor(y)) for x, y in p} & with_shore]
    everything = np.concatenate([nearest_metres(p, drawn, lat)
                                 for _, p in judged])
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
