#!/usr/bin/env python3
#
# Contour lines to .osm.pbf, for the render databases - see Admin:Elevation process
#
#   demContoursToOsm.py <contours.gpkg> <out.osm.pbf> --zone <zone> \
#                       [--id-blocks <file>] [--max-nodes 2000]
#
# Replaces phyghtmap in the elevation pipeline. Not because phyghtmap is wrong -
# it is unmaintained, its maintained fork pyhgtmap is PyPI only, and it works
# from a raster where by this point we already have the contours as vectors.
# pyosmium is a Debian package and lets the id allocation be deliberate.
#
# Ids: every zone's contours are merged into one database, so the zones must not
# collide. The old process kept a hand-maintained table of NODEWAYSTART values
# in the guide, which had to be edited for each new zone. Here the block is
# recorded in a small state file the first time a zone is seen and reused
# thereafter, so a new zone needs no edit and an existing one never moves.
#
# Objects come out sorted by type then id, which is what osm2pgsql wants, so
# there is no separate sort step to forget.

import argparse
import os
import sys

from osgeo import ogr

try:
    import osmium
    import osmium.osm.mutable as mutable
except ImportError:
    sys.exit('python3-pyosmium is needed')

ogr.UseExceptions()

BLOCK = 100_000_000


def id_block(zone, path):
    """The id block for a zone, assigning and recording one if it is new."""
    blocks = {}
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if line:
                    name, start = line.split()
                    blocks[name] = int(start)
    if zone in blocks:
        return blocks[zone]

    start = max(blocks.values(), default=0) + BLOCK
    if path:
        new = not os.path.exists(path)
        with open(path, 'a') as f:
            if new:
                f.write('# zone id blocks for the contour pbfs, one per zone.\n'
                        '# Assigned on first build and never moved: the zones are\n'
                        '# merged into one database, so a block that shifts would\n'
                        '# collide with whatever holds the old ids.\n')
            f.write(f'{zone} {start}\n')
    print(f'{zone}: assigned id block {start}', file=sys.stderr)
    return start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('gpkg')
    ap.add_argument('out')
    ap.add_argument('--zone', required=True)
    ap.add_argument('--id-blocks')
    ap.add_argument('--max-nodes', type=int, default=2000,
                    help='split ways longer than this, as the old process did - '
                         'mapnik and osm2pgsql both prefer bounded ways')
    ap.add_argument('--layer', default=None)
    args = ap.parse_args()

    base = id_block(args.zone, args.id_blocks)

    ds = ogr.Open(args.gpkg)
    layer = ds.GetLayerByName(args.layer) if args.layer else ds.GetLayer(0)

    # Nodes first, then ways, both ascending: readers index nodes before they
    # resolve ways, and pyosmium will not write a way whose nodes come later
    ways = []
    node_id = base
    lines = 0

    if os.path.exists(args.out):
        os.unlink(args.out)
    writer = osmium.SimpleWriter(args.out)

    for feat in layer:
        ele = feat.GetField('ele')
        if ele is None:
            continue
        ele = int(round(ele))
        geom = feat.GetGeometryRef()
        parts = ([geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
                 if geom.GetGeometryName() == 'MULTILINESTRING' else [geom])
        for part in parts:
            pts = [(part.GetX(i), part.GetY(i)) for i in range(part.GetPointCount())]
            if len(pts) < 2:
                continue
            lines += 1
            # split, keeping one node shared at each break so the line stays
            # continuous through the render
            for start in range(0, len(pts) - 1, args.max_nodes - 1):
                chunk = pts[start:start + args.max_nodes]
                if len(chunk) < 2:
                    continue
                ids = []
                for lon, lat in chunk:
                    writer.add_node(mutable.Node(id=node_id, location=(lon, lat)))
                    ids.append(node_id)
                    node_id += 1
                ways.append((ids, ele))

    way_id = base
    for ids, ele in ways:
        writer.add_way(mutable.Way(id=way_id, nodes=ids,
                                   tags={'contour': 'elevation', 'ele': str(ele)}))
        way_id += 1
    writer.close()

    print(f'{args.zone}: {lines} contour lines -> {len(ways)} ways, '
          f'{node_id - base} nodes, ids {base}..{max(node_id, way_id) - 1}',
          file=sys.stderr)
    if max(node_id, way_id) - base > BLOCK:
        print(f'{args.zone}: WARNING block of {BLOCK} exceeded, ids will collide '
              f'with the next zone', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
