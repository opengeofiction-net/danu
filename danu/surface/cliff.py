"""A cliff with its top and its height - #191.

OSM draws a cliff (``natural=cliff``, and the smaller ``earth_bank``) as a way
along its top edge, the ground below on the way's right, and gives the drop
as ``height``; nothing gives the top a height. Where a mapper has given a cliff
``ele`` - the top - as well as ``height``, the surface takes it at its word: the
top edge burned as a constraint at ``ele``, and the foot, a line beside it on
the right, at ``ele - height``.

Every cliff, heights or none, is a wall as well (isofill 0.16.0's ``--wall``):
the fill does not see past it or diffuse across it, so the ground either side
is filled from its own side and the drop is where the contours put it - the
cliff's line kept in the ``cliff`` layer whatever it carries, burned into a
raster of its own by ``build.rasterise_wall`` and ``Contours.burn_wall``.

How far the foot is from the top is the build's grid's to say, not the
cliff's: a cell and a half, so the two lines never share a cell and nothing
lies between them but the drop. A cliff is a face a few metres across; the
grid is 31 m at 1 arcsecond and 93 at 3, and the face is as steep as the grid
can draw it.

No Qt. GDAL only for the features, as ``held`` and ``saddle``.
"""

from __future__ import annotations

import math

from ..core.square import parse_ele

KINDS = ('cliff', 'earth_bank')
WORDS = tuple(q + k.encode() + q for k in KINDS for q in (b"'", b'"'))
GAP_CELLS = 1.5                 # the foot from the top, in cells of the grid burned on


def is_cliff(way) -> bool:
    return way.tags.get('natural') in KINDS


def levels(way) -> tuple[float, float] | None:
    """(top, foot) for a cliff with ``ele`` and a positive ``height``, or
    None - a cliff with no top given has nothing to burn."""
    if not is_cliff(way):
        return None
    top = parse_ele(way.tags.get('ele'))
    drop = parse_ele(way.tags.get('height'))
    if top is None or drop is None or drop <= 0:
        return None
    return top, top - drop


def foot(points, gap_deg: float) -> list[tuple[float, float]]:
    """The line beside ``points`` (lon, lat) on their right, ``gap_deg``
    degrees of latitude away - at each vertex along the mean of the right
    normals of the segments either side, in metres, so a bend keeps its
    distance."""
    n = len(points)
    if n < 2:
        return []
    lat0 = sum(p[1] for p in points) / n
    k = math.cos(math.radians(lat0))
    xy = [(lon * k, lat) for lon, lat in points]
    normals = []
    for (x0, y0), (x1, y1) in zip(xy, xy[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        normals.append((dy / length, -dx / length))           # the right of travel
    out = []
    for i, (x, y) in enumerate(xy):
        ns = [normals[j] for j in (i - 1, i) if 0 <= j < len(normals)]
        nx, ny = sum(a for a, _ in ns), sum(b for _, b in ns)
        length = math.hypot(nx, ny) or 1.0
        out.append(((x + gap_deg * nx / length) / k, y + gap_deg * ny / length))
    return out


def lines(points, top: float, bottom: float, res_deg: float) -> list:
    """The two lines a cliff burns, as (points, level): its top edge at
    ``top``, and its foot beside it on the right at ``bottom``, a cell and a
    half of a grid of ``res_deg`` away."""
    return [(list(points), top), (foot(points, GAP_CELLS * res_deg), bottom)]


def feature(defn, points, way_id, bottom: float | None, square=None):
    """A cliff as a feature of the ``cliff`` layer: its top edge as drawn,
    and the level of its foot. The top is burned as the contour the cliff's
    ``ele`` makes it; the foot is made from this for the grid it is burned
    on (``burn_feet``)."""
    from osgeo import ogr
    g = ogr.Geometry(ogr.wkbLineString)
    for lon, lat in points:
        g.AddPoint_2D(float(lon), float(lat))
    f = ogr.Feature(defn)
    f.SetGeometry(g)
    f.SetField('osm_id', str(way_id))
    if bottom is not None:
        f.SetField('bottom', float(bottom))
    if square is not None and defn.GetFieldIndex('square') >= 0:
        f.SetField('square', square)
    return f


def burn_feet(ds, layer, res_deg: float) -> None:
    """Each cliff's foot burned into the open raster ``ds``, at its level: the
    feet of ``layer``'s cliffs (its spatial filter honoured), a cell and a half
    of ``res_deg`` to the right of each top. The build and the preview both
    burn them so (R35)."""
    from osgeo import gdal, ogr

    from .land_clamp import ogr_memory_driver
    mem = ogr_memory_driver().CreateDataSource('feet')
    out = mem.CreateLayer('feet', layer.GetSpatialRef(), ogr.wkbLineString)
    out.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
    bottom_i = layer.GetLayerDefn().GetFieldIndex('bottom')
    n = 0
    for f in layer:
        if not f.IsFieldSetAndNotNull(bottom_i):
            continue                # a cliff with no heights: a wall, and no foot
        g = f.GetGeometryRef()
        pts = [g.GetPoint_2D(i) for i in range(g.GetPointCount())]
        ft = foot(pts, GAP_CELLS * res_deg)
        if len(ft) < 2:
            continue
        line = ogr.Geometry(ogr.wkbLineString)
        for x, y in ft:
            line.AddPoint_2D(x, y)
        o = ogr.Feature(out.GetLayerDefn())
        o.SetGeometry(line)
        o.SetField('ele', f.GetField(bottom_i))
        out.CreateFeature(o)
        n += 1
    layer.ResetReading()
    if n:
        gdal.RasterizeLayer(ds, [1], out, options=['ATTRIBUTE=ele', 'ALL_TOUCHED=FALSE'])
