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
    """(x0, y1, x1, y0) of a box, in the grid's own coordinates."""
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
        src = ogr.Open(str(gpkg))
        if src is None:
            raise OSError(f'no contours to preview from: {gpkg}')
        lyr = src.GetLayer(LAYER)
        self._mem = ogr.GetDriverByName('MEM').CreateDataSource('contours')
        self.layer = self._mem.CreateLayer(LAYER, srs=lyr.GetSpatialRef(),
                                           geom_type=ogr.wkbLineString)
        self.layer.CreateField(ogr.FieldDefn('ele', ogr.OFTReal))
        self.layer.CreateField(ogr.FieldDefn('osm_id', ogr.OFTString))
        defn = self.layer.GetLayerDefn()
        self._fid: dict[str, int] = {}
        top = 0
        for f in lyr:
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
                self._fid[str(osm_id)] = f.GetFID()
            top = max(top, f.GetFID())
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
    nodata: float | None
    contours: Contours


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
