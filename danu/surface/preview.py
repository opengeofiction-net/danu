"""The constraints under an edit, re-burned for one box - R19's preview.

F3 showed that a box around an edit, solved against a rim held at the last
whole-raster answer, comes out right. What it assumed was its input: it takes
``constraints`` already carrying the edit. Producing those by rebuilding is the
thing the preview exists to avoid - on the gobras 3x3 at 3 arcseconds a whole
build is 5.57 s and no one stage dominates it (collect 1.63, water 1.26,
interpolate 1.41, clamp 0.86), so skipping any one of them is not enough. All
of it has to go.

So the contours are held in memory as a layer the editor mutates, and a box is
burned from that layer alone: 2.3 ms for a five-cell edit and 5.2 ms for a
two-hundred-cell one, against 10 to 18 ms for the solve that follows. Twelve to
twenty-three milliseconds together, inside phase 4's 50 ms with the clamp and
the shading still to come.

Re-burning, not patching. A cell cannot be un-burned - deleting a contour would
leave its cells behind - so the box is cleared to nodata and every contour
touching it is burned again.

**The order matters, and the obvious way to get it is wrong.** Rasterising with
``ATTRIBUTE=ele`` is last-writer-wins where two contours touch one cell, so a
box burned in a different order from the whole raster disagrees with it. Asking
the GeoPackage for the features through an OGR spatial filter hands them back
in *spatial index* order, and burning that way put 1,359 of 48,841 cells at the
wrong elevation - not at the box edge where it would have been noticed, but
scattered through it, median 31 cells in, every one holding a value in both and
a different value in each. That is the signature of the tie being broken the
other way. The MEM layer here keeps the build's own FIDs and hands them back in
FID order, which matches the whole-raster burn exactly at every box size tried.
``tests/golden/test_preview.py`` holds it there.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import local
from .local import Box
from .params import Params

LAYER = 'contour'


def box_extent(gt: tuple, box: Box) -> tuple[float, float, float, float]:
    """The box's corners in the grid's own coordinates, as
    (west, north, east, south) on a north-up geotransform - which is the order
    the numbers come out in, x then y, and not the order a bounding box is
    usually written in."""
    rows, cols = box.shape
    x0, y1 = gt[0] + box.x0 * gt[1], gt[3] + box.y0 * gt[5]
    return x0, y1, x0 + cols * gt[1], y1 + rows * gt[5]


class Contours:
    """The working set's contour ways as a layer a box can be burned from,
    kept in step with the editor.

    Loaded once from the GeoPackage the last exact build collected - 220 ms for
    the gobras 3x3's 7,240 contours - and then mutated per edit rather than
    rebuilt, which is the whole point. The build's FIDs are kept, because they
    are the order the whole-raster burn took the features in and a box has to
    agree with it.

    A contour drawn since that build has no FID of the build's to keep, so it
    takes the next one and burns last. Against the exact build that follows it
    may take the other side of a tie, and only where a new contour shares a
    cell with an old one - the preview is an approximation there, as it is at
    the rim, and the rebuild on idle is what settles it.
    """

    def __init__(self, gpkg: Path):
        from osgeo import ogr

        # by whichever name this GDAL calls the in-memory driver: renamed from
        # Memory to MEM in 3.11, and Trixie - so the servers, and CI - ships
        # 3.10, where GetDriverByName('MEM') returns None rather than raising.
        # Asking for the wrong one fails later and elsewhere, as an
        # AttributeError on None, which is how this was found: the suite passed
        # on a 3.12 desk and all three tests failed on CI
        from .land_clamp import ogr_memory_driver

        src = ogr.Open(str(gpkg))
        if src is None:
            raise OSError(f'no contours to preview from: {gpkg}')
        lyr = src.GetLayer(LAYER)
        self._mem = ogr_memory_driver().CreateDataSource('contours')
        self.layer = self._mem.CreateLayer(LAYER, srs=lyr.GetSpatialRef(),
                                           geom_type=ogr.wkbLineString)
        self.layer.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
        self.layer.CreateField(ogr.FieldDefn('osm_id', ogr.OFTString))
        defn = self.layer.GetLayerDefn()
        self._fid: dict[str, int] = {}
        # ways whose id is claimed by more than one feature. Until the
        # allocator was made set-wide, every square minted -1 for its first new
        # way, so a working set drawn in two squares and saved holds two
        # contours calling themselves the same way - and those files exist.
        # Keyed by id here, one entry wins, and a later apply() or remove()
        # then edits whichever registered last, in the wrong square. Collected
        # rather than guessed at, so the caller can say which id and stop.
        self.collided: list[str] = []
        top = 0
        for f in lyr:
            # every feature moves the high-water mark, including one this
            # skips: if the highest FID in the source is a contour without an
            # ele, a _next taken from the kept features alone collides with an
            # FID already in use, and CreateFeature at an existing FID either
            # fails or overwrites depending on the driver - on the one layer
            # the whole ordering argument rests on
            top = max(top, f.GetFID())
            ele = f.GetField('ele')
            if ele is None:
                continue
            g = ogr.Feature(defn)
            g.SetFID(f.GetFID())
            g.SetGeometry(f.GetGeometryRef().Clone())
            g.SetField('ele', float(ele))
            osm_id = f.GetField('osm_id')
            g.SetField('osm_id', osm_id)
            self.layer.CreateFeature(g)
            if osm_id is not None:
                if str(osm_id) in self._fid:
                    self.collided.append(str(osm_id))
                self._fid[str(osm_id)] = f.GetFID()
        self._next = top + 1

    def __len__(self) -> int:
        return self.layer.GetFeatureCount()

    def remove(self, way_id) -> bool:
        """Drop a way's contour. False when there was none - a way with no
        ``ele`` never reached the layer and its deletion changes nothing."""
        fid = self._fid.pop(str(way_id), None)
        if fid is None:
            return False
        self.layer.DeleteFeature(fid)
        return True

    def apply(self, way_id, points, ele: float) -> None:
        """Put a way's contour in, at its own FID if it had one.

        Keeping the FID is what keeps a moved or re-tagged contour on the same
        side of a tie as the build would put it. Only a way the build never saw
        goes to the end."""
        from osgeo import ogr
        key = str(way_id)
        fid = self._fid.get(key)
        if fid is not None:
            self.layer.DeleteFeature(fid)
        else:
            fid = self._next
            self._next += 1
        line = ogr.Geometry(ogr.wkbLineString)
        for lon, lat in points:
            line.AddPoint_2D(float(lon), float(lat))
        f = ogr.Feature(self.layer.GetLayerDefn())
        f.SetFID(fid)
        f.SetGeometry(line)
        f.SetField('ele', float(ele))
        f.SetField('osm_id', key)
        self.layer.CreateFeature(f)
        self._fid[key] = fid

    def burn(self, gt: tuple, box: Box, nodata: float) -> np.ndarray:
        """The constraints for ``box`` alone, burned as the build burns them:
        all touched, last writer wins, in FID order.

        All touched, as ``rasterise()`` does - a thin line otherwise leaves
        diagonal gaps, and the fill's sight test threads them."""
        from osgeo import gdal
        rows, cols = box.shape
        x0, y1, x1, y0 = box_extent(gt, box)
        out = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, gdal.GDT_Int16)
        out.SetGeoTransform((x0, gt[1], 0.0, y1, 0.0, gt[5]))
        band = out.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.Fill(nodata)
        self.layer.SetSpatialFilterRect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        try:
            gdal.RasterizeLayer(out, [1], self.layer,
                                options=['ATTRIBUTE=ele', 'ALL_TOUCHED=TRUE'])
        finally:
            self.layer.SetSpatialFilter(None)
        return band.ReadAsArray()


def clamp_patch(surface: np.ndarray, constraints: np.ndarray,
                kept_dem: np.ndarray) -> np.ndarray:
    """``land_clamp.clamp``'s arithmetic for one box: sea to exactly zero, land
    never zero, the burned constraints back untouched.

    The clamp has two halves and only one of them is local. Deciding *which*
    cells are sea is global - it polygonizes the candidates and keeps the
    regions that reach open water - and a box cannot do it, because whether a
    zero-cell is sea depends on what it joins up with a thousand cells away.
    The arithmetic that follows is four lines of numpy.

    So the decision is not recomputed; it is read off the last exact build,
    where a cell reading exactly zero is one the clamp called sea. That is an
    approximation and it was measured before it was relied on: deleting a
    contour level from the golden square moves 507 cells of the fill and
    changes the sea/land decision for 11 of 1,442,401 - 0.0008%. Those eleven
    are wrong in the preview until the rebuild on idle, which is the same
    bargain as the held rim.

    Burned cells are handled last and so need no care here: a coastline drawn
    at zero reads zero in ``kept_dem``, is called sea, and is then overwritten
    with its own burned value, which is zero.
    """
    from .build import NODATA
    d = np.maximum(surface.astype(np.float32), np.float32(1))
    d[kept_dem == 0] = 0
    burned = constraints != NODATA
    d[burned] = constraints[burned]
    return d


@dataclass
class Kept:
    """What the last exact build left, which a preview reads and updates.

    The arrays are the whole working set's, on the build's own lat/lon grid.
    ``surface`` is ``rounded.tif``, the fill's answer before the clamp, because
    that is what a solve continues from and what a solve returns - and it is
    the caller's to keep current: splice each patch into it, or the next
    preview holds the rim at a surface two edits old.
    """
    constraints: np.ndarray
    mask: np.ndarray
    water: np.ndarray | None
    surface: np.ndarray
    geotransform: tuple
    nodata: float          # the build's own; None would reach SetNoDataValue
    contours: Contours
    dem: np.ndarray                 # the clamped surface, which clamp_patch
                                    # reads the sea decision off. Not optional:
                                    # the default was documented as being for
                                    # a caller that solves without clamping,
                                    # and there is no such caller - what it
                                    # bought was a TypeError in a slot, from a
                                    # Kept built without one


def patch(kept: Kept, box: Box, params: Params, cover: int | None = None,
          slack: int | None = None, lib=None) -> tuple[np.ndarray, Box]:
    """The surface around an edit, and the box it is good for.

    The constraints are re-burned over everything the solve reads - the edited
    box grown by the cover and the reach - and put into the kept array for the
    call, so ``local.resolve`` sees the whole raster as it is after the edit,
    which is what it documents itself as taking.

    Put in, and taken out again. Copying the array instead would be 92 MB per
    keystroke at 3 arcseconds and 311 at 1, which is most of what solving a box
    was meant to avoid; and leaving the burn behind would have the kept
    constraints drift from the build that produced them, one box at a time. The
    edits are not lost by restoring, because they live in ``contours`` and
    every preview re-burns its own box from there.

    ``mask`` and ``water`` need no such care and get none: ``isofill`` takes
    both as ``const``, and a test asserts they come back untouched. The
    asymmetry with ``constraints`` is the point - that one is written on
    purpose, and put back.
    """
    cover = 2 * params.fill_cells if cover is None else cover
    slack = 2 * params.fill_cells if slack is None else slack
    shape = kept.constraints.shape
    good = box.grown(cover, shape)
    grown = good.grown(local.reach(params, slack), shape)
    fresh = kept.contours.burn(kept.geotransform, grown, kept.nodata)
    sl = grown.slice
    was = kept.constraints[sl].copy()
    kept.constraints[sl] = fresh
    try:
        return local.resolve(kept.constraints, kept.mask, kept.water, kept.surface,
                             box, params, cover=cover, slack=slack,
                             nodata=kept.nodata, lib=lib)
    finally:
        kept.constraints[sl] = was
