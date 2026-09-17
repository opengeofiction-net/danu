#!/usr/bin/env python3
#
# Blank contour squares, for ground nobody has drawn yet - see
# Admin:Elevation process
#
#   demMakeSquare.py <outdir> <square> [<square> ...]
#   demMakeSquare.py <outdir> --box <west> <south> <east> <north>
#
# A square is named for its south west corner in the SRTM convention, always
# N/SxxE/Wxxx: N42E017, S03W121. The file holds one closed way around the
# degree, tagged with the square name, and nothing else - the mapper draws the
# contours inside it.
#
# The frame is what makes a square a square. Everything downstream takes the
# extent from the filename, but the frame is what a mapper sees in JOSM, and
# without it there is nothing to draw against.
#
# upload='never' is not decoration. The file carries negative ids, so JOSM
# treats every object in it as new, and an accidental upload would put contour
# data onto the live map.

import argparse
import lzma
import os
import sys


def square_name(lon, lat):
    ns = 'N' if lat >= 0 else 'S'
    ew = 'E' if lon >= 0 else 'W'
    return f'{ns}{abs(lat):02d}{ew}{abs(lon):03d}'


def parse_square(name):
    """N42E017 -> (17, 42). Raises on anything else."""
    import re
    m = re.fullmatch(r'([NS])(\d{2})([EW])(\d{3})', name.upper())
    if not m:
        raise ValueError(f'{name}: not a degree square name, want N42E017')
    ns, lat, ew, lon = m.groups()
    return (int(lon) * (1 if ew == 'E' else -1),
            int(lat) * (1 if ns == 'N' else -1))


def write_square(path, lon, lat, note):
    name = square_name(lon, lat)
    corners = [(lon, lat), (lon + 1, lat), (lon + 1, lat + 1), (lon, lat + 1)]
    # compressed, which is how the squares are held and handed out
    with lzma.open(path, 'wt') as f:
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        f.write("<osm version='0.6' upload='never' "
                "generator='demMakeSquare.py'>\n")
        for i, (x, y) in enumerate(corners, start=1):
            f.write(f"  <node id='-{i}' action='modify' "
                    f"lat='{y:.7f}' lon='{x:.7f}' />\n")
        f.write("  <way id='-5' action='modify'>\n")
        for i in (1, 2, 3, 4, 1):
            f.write(f"    <nd ref='-{i}' />\n")
        f.write(f"    <tag k='ref' v='{name}' />\n")
        f.write(f"    <tag k='note' v='{note}' />\n")
        f.write("  </way>\n")
        f.write('</osm>\n')
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outdir')
    ap.add_argument('squares', nargs='*',
                    help='square names, e.g. N42E017 S03W121')
    ap.add_argument('--box', nargs=4, type=int,
                    metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'),
                    help='every square in a range of whole degrees, east and '
                         'north exclusive')
    ap.add_argument('--note',
                    default='degree square frame, not contour data',
                    help='the note tag on the frame way')
    args = ap.parse_args()

    wanted = []
    for name in args.squares:
        try:
            wanted.append(parse_square(name))
        except ValueError as e:
            sys.exit(str(e))
    if args.box:
        w, s, e, n = args.box
        wanted += [(lon, lat) for lat in range(s, n) for lon in range(w, e)]
    if not wanted:
        sys.exit('name at least one square, or give --box')

    os.makedirs(args.outdir, exist_ok=True)
    made = skipped = 0
    for lon, lat in sorted(set(wanted)):
        name = square_name(lon, lat)
        path = os.path.join(args.outdir, f'{name}.osm.xz')
        if os.path.exists(path):
            # never over an existing square: it may be someone's drawing
            print(f'  {name}: already there, left alone', file=sys.stderr)
            skipped += 1
            continue
        write_square(path, lon, lat, args.note)
        print(f'  {name}', file=sys.stderr)
        made += 1

    print(f'{made} written to {args.outdir}'
          f'{f", {skipped} already there" if skipped else ""}', file=sys.stderr)


if __name__ == '__main__':
    main()
