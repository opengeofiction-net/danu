#!/usr/bin/env python3
#
# The grid a zone should be built on - see Admin:Elevation process
#
#   demZoneExtent.py <osm-squares-dir> <arcsec>
#
# Emits shell assignments for eval: WEST EAST SOUTH NORTH, TE for the master
# grid, TE_HGT for the 3 arcsecond products, SQUARES and SQ_DEGREES.
#
# The extent covers the squares which hold constraints, not every square with a
# file. A zone's directory carries the blank templates handed out to mappers -
# one frame way, no contours - alongside the squares which have been filled in,
# and building over the blanks costs pixels for nothing: a third of them on
# zone-roantra, plus a published .hgt of pure zeroes for each.
#
# Which squares hold something is decided by reading the files rather than by
# taking the extent of the collected geometry. A square is cut out of its DEM on
# pixel boundaries, so lines clipped at its edge overhang by half a cell, and a
# square starting at 26 degrees yields geometry from 25.9996 - which floors to
# the wrong degree. Any tolerance that fixes that is a tolerance wide enough to
# discard a genuine sliver of data, whereas the filename says exactly which
# degree square a file describes.
#
# SRTM is grid registered: 1201 samples per degree, pixel centres on whole
# arcseconds, so the raster corner sits half a pixel outside the degree line.
# The master and the 3 arcsecond products each need that offset at their own
# spacing - using one for the other leaves a fractional sample count per degree
# and SRTMHGT, which insists on exactly 1201 square, then refuses every slice.

import lzma
import os
import re
import sys

HGT_ARCSEC = 3
NAME = re.compile(r'([NS])(\d{2})([EW])(\d{3})')
# any way carrying an elevation is a constraint, contour or water edge alike
HAS_DATA = re.compile(rb"""k=["']ele["']""")


def has_constraints(path, chunk=1 << 20):
    """True if the file has any ele tag. Reads in chunks and stops at the first,
    since a filled square can be 87 MB and most are answered by the first page.

    Decompressing as it goes, so a blank template costs a few kilobytes rather
    than the whole file."""
    tail = b''
    with lzma.open(path, 'rb') as f:
        while True:
            block = f.read(chunk)
            if not block:
                return False
            if HAS_DATA.search(tail + block):
                return True
            tail = block[-16:]


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit('usage: demZoneExtent.py <osm-squares-dir> <arcsec> [drawn.geojson]')
    src, arcsec = sys.argv[1], float(sys.argv[2])
    drawn_out = sys.argv[3] if len(sys.argv) > 3 else None

    squares, blank, loose = [], 0, []
    for name in sorted(os.listdir(src)):
        if name.endswith('.osm'):
            # the squares are held compressed and only .osm.xz is read. An
            # uncompressed one is somebody's drop that never got packed, and
            # silently skipping it builds the zone without their work in it
            loose.append(name)
            continue
        if not name.endswith('.osm.xz'):
            continue
        m = NAME.match(name)
        if not m:
            # straight to stderr. Emitting a shell echo here put it on stdout,
            # which is eval'd - and with an unquoted command substitution the
            # newlines collapse, so the echo swallowed every assignment after it
            # as its own arguments and the zone came out looking empty
            print(f'  ignoring {name}, not a degree square', file=sys.stderr)
            continue
        if not has_constraints(os.path.join(src, name)):
            blank += 1
            continue
        ns, lat, ew, lon = m.groups()
        squares.append((int(lon) * (1 if ew == 'E' else -1),
                        int(lat) * (1 if ns == 'N' else -1)))

    if loose:
        print(f'  WARNING: not read, being uncompressed: {" ".join(loose)}',
              file=sys.stderr)
        print('  the squares are held as .osm.xz - xz these and remove the .osm',
              file=sys.stderr)

    if drawn_out:
        # One polygon per degree square that actually holds contours, for the
        # fill mask. The zone raster is the bounding box of these, and a bounding
        # box is not the same shape as the squares in it: ellarca's is fifteen
        # degree squares around eleven drawn ones. Without the mask the second
        # pass carries values straight across the four nobody has drawn, in
        # streaks the length of the raster, because a row is anchored at zero
        # only beyond its ends and there is nothing in between to stop it.
        feats = ','.join(
            '{"type":"Feature","properties":{},"geometry":{"type":"Polygon",'
            '"coordinates":[[[%d,%d],[%d,%d],[%d,%d],[%d,%d],[%d,%d]]]}}'
            % (lon, lat, lon + 1, lat, lon + 1, lat + 1, lon, lat + 1, lon, lat)
            for lon, lat in squares)
        with open(drawn_out, 'w') as f:
            f.write('{"type":"FeatureCollection","features":[%s]}' % feats)

    if not squares:
        print(f'SQUARES=0 SQ_DEGREES=0 BLANK={blank}')
        return

    west = min(s[0] for s in squares)
    east = max(s[0] for s in squares) + 1
    south = min(s[1] for s in squares)
    north = max(s[1] for s in squares) + 1

    half = arcsec / 7200
    half_hgt = HGT_ARCSEC / 7200

    print(f'WEST={west} EAST={east} SOUTH={south} NORTH={north}')
    print(f'TE="{west - half:.9f} {south - half:.9f} '
          f'{east + half:.9f} {north + half:.9f}"')
    print(f'TE_HGT="{west - half_hgt:.9f} {south - half_hgt:.9f} '
          f'{east + half_hgt:.9f} {north + half_hgt:.9f}"')
    print(f'SQUARES={len(squares)} SQ_DEGREES={(east - west) * (north - south)} '
          f'BLANK={blank}')


if __name__ == '__main__':
    main()
