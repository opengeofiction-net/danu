#!/usr/bin/env python3
#
# The grid a zone should be built on - see Admin:Elevation process
#
#   demZoneExtent.py <contours.gpkg> <arcsec> <west> <east> <south> <north>
#
# Emits shell assignments for eval: WEST EAST SOUTH NORTH, TE for the master
# grid, TE_HGT for the 3 arcsecond products, and SQ_DEGREES.
#
# Two things are going on.
#
# The square filenames give the zone's nominal extent, but a zone's directory
# holds the blank templates handed out to mappers alongside the squares they
# have filled in, so the nominal extent covers ground with no data. Trimming to
# where the constraints actually are saved a third of the pixels on roantra.
# The trim only ever shrinks: a contour drawn slightly outside its own square
# must not enlarge the zone, which is why the filenames bound it.
#
# And SRTM is grid registered - 1201 samples per degree with pixel centres on
# whole arcseconds, so the raster corner sits half a pixel outside the degree
# line. The master and the 3 arcsecond products each need that offset at their
# own spacing. Using one for the other leaves a fractional number of samples
# per degree, and SRTMHGT, which insists on exactly 1201 square, then refuses
# every slice of the archive without explaining why.

import math
import sys

from osgeo import ogr

ogr.UseExceptions()

HGT_ARCSEC = 3


def main():
    if len(sys.argv) != 7:
        sys.exit('usage: demZoneExtent.py <gpkg> <arcsec> <w> <e> <s> <n>')
    path = sys.argv[1]
    arcsec = float(sys.argv[2])
    west, east, south, north = (int(v) for v in sys.argv[3:7])

    # the datasource has to be held in a name of its own: taking a layer from a
    # temporary ogr.Open() lets the datasource be collected, and the layer with it
    ds = ogr.Open(path)
    layer = ds.GetLayer(0)
    x0, x1, y0, y1 = layer.GetExtent()

    west = max(west, math.floor(x0))
    east = min(east, math.ceil(x1))
    south = max(south, math.floor(y0))
    north = min(north, math.ceil(y1))

    half = arcsec / 7200
    half_hgt = HGT_ARCSEC / 7200

    print(f'WEST={west} EAST={east} SOUTH={south} NORTH={north}')
    print(f'TE="{west - half:.9f} {south - half:.9f} '
          f'{east + half:.9f} {north + half:.9f}"')
    print(f'TE_HGT="{west - half_hgt:.9f} {south - half_hgt:.9f} '
          f'{east + half_hgt:.9f} {north + half_hgt:.9f}"')
    print(f'SQ_DEGREES={(east - west) * (north - south)}')


if __name__ == '__main__':
    main()
