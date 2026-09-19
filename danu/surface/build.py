"""The surface, the editor's way: the stages of ``danu-build-zone`` that make
a DEM from contour squares, as functions.

This is the second of two paths to the same surface. The first is the shell
build, which runs on the server every night and is pinned by the golden test.
This one is what the editor calls, and it is pinned by the same golden test to
the same reference, cell for cell - that assertion is the whole reason the two
may exist. Every stage here carries a ``shell:`` line naming the command it
stands for in ``danu-build-zone``, and a test checks the line is there, so when
one side changes the other is findable.

Parameters come through ``danu.surface.params`` from the shared file
``danu/params/elevation.toml``, with no defaults -
and the resolution is taken as an argument, as the shell takes it from its
environment. The stages after the DEM - smoothing for the hillshade, the
Mercator copies, the contour extract, the archive - are not here; the editor
paints from the DEM directly (S3) and publishes nothing.

Where the two paths legitimately differ: the shell builds a *zone*, every
square in the directory, and the editor builds a *working set*. For a square
in the middle of a drawn zone the editor's surface near the set's edge will
differ from the zone build's, because the zone had the neighbours' contours to
look at and the set does not. That is expected, and it is why the golden
fixture is a single square: there the two are the same job, run with water
constraints off as its params.lock records, so neither path reaches Overpass.
"""

from __future__ import annotations

import lzma
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from osgeo import gdal, ogr

from ..core.square import SquareName, list_squares, read_square
from ..core.zone_extent import has_constraints
from . import drawn_mask, isofill_lib, land_clamp, sea_mask
from .params import Params

gdal.UseExceptions()

NODATA = -9999
# the shell's own test for "ele is a number", in the GeoPackage's SQLite
NONNUM = ("NOT ((ele GLOB '[0-9]*' OR ele GLOB '-[0-9]*') "
          "AND ele NOT GLOB '*[^-0-9.]*')")
CREATE = ['TILED=YES', 'COMPRESS=DEFLATE']
Log = Callable[[str], None]


def _quiet(_: str) -> None:
    pass


# ------------------------------------------------------------------ grid

@dataclass(frozen=True)
class Grid:
    """The raster every stage shares: whole degrees, with half a cell added
    on every side so cell centres sit on the degree lines.
    shell: eval "$(${PYTHON} -m danu.core.zone_extent ${SRC} ${ARCSEC})" -> WEST EAST SOUTH NORTH, and TE which is the te property here"""

    west: int
    east: int
    south: int
    north: int
    arcsec: float

    @property
    def res(self) -> float:
        return self.arcsec / 3600

    @property
    def te(self) -> tuple[float, float, float, float]:
        """gdal's -te: minx miny maxx maxy. Formatted to nine places and read
        back, as the shell's string is, so the origin is the shell's origin
        to the last digit it kept."""
        half = self.arcsec / 7200
        raw = (self.west - half, self.south - half, self.east + half, self.north + half)
        return tuple(float(f'{v:.9f}') for v in raw)

    @property
    def size(self) -> tuple[int, int]:
        w, s, e, n = self.te
        return round((e - w) / self.res), round((n - s) / self.res)


def squares_with_constraints(zone_dir: Path, names: Iterable[SquareName] | None = None) -> dict[SquareName, Path]:
    """The squares that hold any ``ele``, by name; the rest are templates.
    shell: zone_extent.py reads each file for an ele tag (has_constraints)"""
    found = list_squares(zone_dir)
    if names is not None:
        wanted = set(names)
        found = {n: p for n, p in found.items() if n in wanted}
    return {n: p for n, p in found.items() if has_constraints(str(p))}


def grid_for(names: Iterable[SquareName], arcsec: float) -> Grid:
    """The bounding whole degrees of the squares that hold constraints.
    shell: WEST=min EAST=max+1 SOUTH=min NORTH=max+1 over the squares zone_extent.py found"""
    names = list(names)
    if not names:
        raise ValueError('no squares with constraints: nothing to build')
    return Grid(west=min(n.lon for n in names), east=max(n.lon for n in names) + 1,
                south=min(n.lat for n in names), north=max(n.lat for n in names) + 1,
                arcsec=float(arcsec))


# --------------------------------------------------------------- collect

def lines_osmconf(work: Path) -> Path:
    """GDAL's OSM config with closed ways read as lines, so a coastline drawn
    closed is a constraint and not an area filed under multipolygons.
    shell: sed 's/^closed_ways_are_polygons=.*/closed_ways_are_polygons=/' ${OSMCONF} > ${WORK}/osmconf-lines.ini"""
    text = resources.files('danu.surface').joinpath('osmconf.ini').read_text(encoding='utf-8')
    text = re.sub(r'^closed_ways_are_polygons=.*$', 'closed_ways_are_polygons=', text, flags=re.M)
    out = work / 'osmconf-lines.ini'
    out.write_text(text, encoding='utf-8')
    return out


def check_long_ways(square_path: Path, log: Log) -> None:
    """A way over 10,000 nodes is dropped silently by GDAL and its ground
    comes out as a void; over 2,000 the OSM API would refuse it on upload.
    shell: the awk over ${SQUARE} counting <nd /> per way (sq_over, sq_drop, sq_max)"""
    sq = read_square(square_path)
    longest = max((len(w.refs) for w in sq.ways.values()), default=0)
    drop = sum(1 for w in sq.ways.values() if len(w.refs) > 10000)
    over = sum(1 for w in sq.ways.values() if len(w.refs) > 2000)
    if drop:
        raise ValueError(f'{square_path.name} has {drop} way(s) over 10,000 nodes (longest {longest}); '
                         f'GDAL drops these silently. Run danu.core.split_long_ways')
    if over:
        log(f'  WARNING: {square_path.name} has {over} way(s) over 2,000 nodes (longest {longest}), '
            f'which the OSM API would reject on upload')


def collect(squares: dict[SquareName, Path], work: Path, log: Log = _quiet) -> Path | None:
    """Every square's contour ways into one GeoPackage layer, ``contour``, with
    a numeric ``ele``. None when there are no contours at all.
    shell: xz -dc ${f} > ${SQUARE}; OSM_CONFIG_FILE=osmconf-lines.ini ogr2ogr -f GPKG [-append] contours.gpkg ${SQUARE} lines -where "ele IS NOT NULL" -nln contour [-nlt LINESTRING]; then DELETE FROM contour WHERE ${NONNUM}"""
    gpkg = work / 'contours.gpkg'
    if gpkg.exists():
        gpkg.unlink()
    conf = lines_osmconf(work)
    square = work / 'square.osm'
    first = True
    with gdal.config_options({'OSM_CONFIG_FILE': str(conf), 'OSM_USE_CUSTOM_INDEXING': 'NO',
                              'CPL_TMPDIR': str(work)}):
        for name, path in sorted(squares.items()):
            check_long_ways(path, log)
            with lzma.open(path, 'rb') as src, open(square, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            opts = dict(format='GPKG', layers=['lines'], where='ele IS NOT NULL', layerName='contour')
            if first:
                opts['geometryType'] = 'LINESTRING'
            else:
                opts['accessMode'] = 'append'
            gdal.VectorTranslate(str(gpkg), str(square), options=gdal.VectorTranslateOptions(**opts))
            first = False
            square.unlink()
    if not gpkg.exists():
        return None
    ds = ogr.Open(str(gpkg), update=1)
    dropped = ds.ExecuteSQL(f'SELECT DISTINCT ele FROM contour WHERE {NONNUM}', dialect='SQLite')
    bad = [f.GetField(0) for f in dropped]
    ds.ReleaseResultSet(dropped)
    if bad:
        log(f'  ignoring ways whose ele is not a number: {" ".join(map(str, bad))}')
        ds.ExecuteSQL(f'DELETE FROM contour WHERE {NONNUM}', dialect='SQLite')
    layer = ds.GetLayer('contour')
    features = layer.GetFeatureCount()
    layer.SetAttributeFilter('ele = 0')
    zeros = layer.GetFeatureCount()
    layer.SetAttributeFilter(None)
    layer = None                # before the datasource, not by refcount luck
    ds = None
    if features == 0:
        log('  no contours in any square, nothing to build yet')
        return None
    log(f'  {features} constraint lines')
    log(f'  {zeros} of them at ele 0, holding sea level')
    if zeros == 0:
        log('  WARNING: no ele 0 constraint anywhere. If this ground has sea, its squares need '
            'coastline, or the water will interpolate upward')
    return gpkg


# ------------------------------------------------------------- rasterise

def rasterise(gpkg: Path, grid: Grid, work: Path) -> Path:
    """The constraints as an Int16 raster of metres, nodata where none.
    shell: gdal_rasterize -q -at -a ele -a_nodata -9999 -init -9999 -ot Int16 -tr ${RES} ${RES} -te ${TE} -co TILED=YES -co COMPRESS=DEFLATE contours.gpkg cont.tif"""
    out = work / 'cont.tif'
    gdal.Rasterize(str(out), str(gpkg), options=gdal.RasterizeOptions(
        format='GTiff', allTouched=True, attribute='ele', noData=NODATA, initValues=[NODATA],
        outputType=gdal.GDT_Int16, xRes=grid.res, yRes=grid.res, outputBounds=list(grid.te),
        creationOptions=CREATE))
    return out


def drawn_area(cont: Path, grid: Grid, work: Path, log: Log = _quiet) -> Path:
    """Where the contours describe ground, as a byte mask on the same grid.
    shell: ${PYTHON} -m danu.surface.drawn_mask cont.tif drawn.geojson; gdal_rasterize -q -burn 1 -init 0 -ot Byte -tr ${RES} ${RES} -te ${TE} -co ... drawn.geojson drawn-mask.tif"""
    geojson = work / 'drawn.geojson'
    n = drawn_mask.envelopes(str(cont), str(geojson))
    log(f'  drawn area: {n} square envelopes')
    out = work / 'drawn-mask.tif'
    gdal.Rasterize(str(out), str(geojson), options=gdal.RasterizeOptions(
        format='GTiff', burnValues=[1], initValues=[0], outputType=gdal.GDT_Byte,
        xRes=grid.res, yRes=grid.res, outputBounds=list(grid.te), creationOptions=CREATE))
    return out


def water_constraints(cont: Path, grid: Grid, mask: Path, work: Path, log: Log = _quiet) -> None:
    """Rivers and lakes from Overpass written into the constraints, inside the
    drawn area. The same module, the same way, because it is a command - and
    a failure is a warning and the build goes on, as it is in the shell: a
    surface without them is the one published before they existed.
    shell: ${PYTHON} -m danu.water.constraints cont.tif --bbox "${BBOX}" --mask drawn-mask.tif --report water-report.json  (WATER_CONSTRAINTS=1)"""
    w, s, e, n = grid.te
    run = subprocess.run([sys.executable, '-m', 'danu.water.constraints', str(cont),
                          '--bbox', f'{w},{s},{e},{n}', '--mask', str(mask),
                          '--report', str(work / 'water-report.json')],
                         capture_output=True, text=True)
    if run.returncode != 0:
        log('  WARNING: water constraints failed, continuing without them')
        log(run.stderr[-800:])


def water_mask(gpkg: Path, cont: Path, work: Path, log: Log = _quiet) -> Path | None:
    """Sea, from the coastline's direction. None when the squares carry no
    coastline. The editor has no curated water file; the shell's other branch
    - natural=water areas from a zone's water file - is not here.
    shell: ${PYTHON} -m danu.surface.sea_mask contours.gpkg cont.tif water-mask.tif  (the no-${WATER} branch)"""
    out = work / 'water-mask.tif'
    if out.exists():
        out.unlink()
    if sea_mask.sea_mask(str(gpkg), str(cont), str(out), log=log):
        return out
    log('  no coastline - enclosed water will read as land unless a contour holds it')
    return None


def interpolate(cont: Path, mask: Path, water: Path | None, params: Params, work: Path,
                isofill: str = 'isofill', library: bool | None = None, log: Log = _quiet) -> Path:
    """The surface between the constraints, by isofill. Through the library
    by default - the binary's own in-core path is a call to the same
    function - and through the binary where the library cannot be loaded, or
    where the raster is larger than the in-core fill would hold and the
    binary would band it, which the library does not do.
    shell: isofill --radius ${FILL_CELLS} --barrier ${BARRIER_CELLS} --max-mem ${MAX_MEM} --mask drawn-mask.tif [--water water-mask.tif] ${ISOFILL_EXTRA} cont.tif rounded.tif
    The same flags and no others. The shell passes no --grad-min and relies
    on isofill's default, so neither does the binary call here nor the
    library call, which starts from the library's own defaults and sets only
    what the flags set. The file's grad_min is held equal to that default by
    a test. pass2 has one implemented value and this refuses any other
    rather than ignoring it."""
    if params.pass2 != 'diffuse':
        raise ValueError(f'pass2 = {params.pass2!r}: isofill implements only "diffuse" ("linear" was removed)')
    out = work / 'rounded.tif'
    if out.exists():
        out.unlink()
    if library is not False:
        try:
            lib = isofill_lib.Isofill.load()
        except isofill_lib.IsofillError as e:
            if library is True:
                raise
            log(f'  isofill library not used: {str(e).splitlines()[0]}')
            lib = None
        if lib is not None:
            ds = gdal.Open(str(cont))
            cols, rows = ds.RasterXSize, ds.RasterYSize
            mb = lib.whole_mb(cols, rows)
            if mb > params.max_mem_mb:
                if library is True:
                    raise isofill_lib.IsofillError(f'{cols}x{rows} needs {mb:.0f} MB in core, above {params.max_mem_mb}; the binary bands it')
                log(f'  {mb:.0f} MB in core is above {params.max_mem_mb}: the binary bands it')
            else:
                return _interpolate_library(lib, ds, cont, mask, water, params, out, log)
    return _interpolate_binary(cont, mask, water, params, out, isofill)


def _same_grid(a, b, a_path: Path, b_path: Path) -> None:
    """The binary checks the mask and water are the constraints' size; the
    library path checks they are the constraints' grid, since here the
    arrays meet with no file to carry the georeferencing."""
    if (a.RasterXSize, a.RasterYSize) != (b.RasterXSize, b.RasterYSize):
        raise ValueError(f'{b_path.name} is {b.RasterXSize}x{b.RasterYSize}, '
                         f'{a_path.name} is {a.RasterXSize}x{a.RasterYSize}')
    if any(abs(x - y) > 1e-9 for x, y in zip(a.GetGeoTransform(), b.GetGeoTransform())):
        raise ValueError(f'{b_path.name} is not on {a_path.name}\'s grid')


def _interpolate_library(lib, ds, cont: Path, mask: Path, water: Path | None, params: Params,
                         out: Path, log: Log) -> Path:
    """The library call, with the rasters read to arrays and the surface written
    as the binary writes it: Float32, ZSTD, the float predictor.
    shell: the in-core branch of isofill.c's main(), which is isofill_run()"""
    band = ds.GetRasterBand(1)
    cons = band.ReadAsArray().astype(np.float32)
    nodata = band.GetNoDataValue()
    m_ds = gdal.Open(str(mask))
    _same_grid(ds, m_ds, cont, mask)
    m = m_ds.GetRasterBand(1).ReadAsArray()
    w = None
    if water is not None:
        w_ds = gdal.Open(str(water))
        _same_grid(ds, w_ds, cont, water)
        w = w_ds.GetRasterBand(1).ReadAsArray()
    surface, filled = lib.run(cons, params, mask=m, water=w, nodata=nodata)
    log(f'  isofill {lib.version} as a library: pass 1 set {filled:,} of {cons.size:,} cells')
    drv = gdal.GetDriverByName('GTiff')
    o = drv.Create(str(out), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Float32,
                   options=['TILED=YES', 'COMPRESS=ZSTD', 'ZSTD_LEVEL=9', 'PREDICTOR=3', 'BIGTIFF=IF_SAFER'])
    o.SetGeoTransform(ds.GetGeoTransform())
    o.SetProjection(ds.GetProjection())
    o.GetRasterBand(1).WriteArray(surface)
    o.FlushCache()
    o = None
    return out


def _interpolate_binary(cont: Path, mask: Path, water: Path | None, params: Params, out: Path,
                        isofill: str) -> Path:
    """The same binary the shell runs, with the same flags and no others.
    shell: isofill --radius ${FILL_CELLS} --barrier ${BARRIER_CELLS} --max-mem ${MAX_MEM} --mask drawn-mask.tif [--water water-mask.tif] cont.tif rounded.tif"""
    cmd = [isofill, '--radius', str(params.fill_cells), '--barrier', str(params.barrier_cells),
           '--max-mem', str(params.max_mem_mb), '--mask', str(mask)]
    if water is not None:
        cmd += ['--water', str(water)]
    cmd += [str(cont), str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f'isofill failed ({run.returncode}):\n{run.stderr[-2000:]}')
    return out

def clamp(rounded: Path, cont: Path, water: Path | None, work: Path, log: Log = _quiet) -> Path:
    """Sea to zero, land never zero, the constraints back untouched, written
    as the published DEM is written.
    shell: ${PYTHON} -m danu.surface.land_clamp rounded.tif cont.tif dem.tif ${WATER_MASK}"""
    out = work / 'dem.tif'
    if out.exists():
        out.unlink()
    land_clamp.clamp(str(rounded), str(cont), str(out), str(water) if water else None, log=log)
    return out


# ----------------------------------------------------------------- build

@dataclass
class Result:
    dem: Path | None
    grid: Grid | None
    squares: dict[SquareName, Path]
    contours_gpkg: Path | None
    constraints: Path | None
    drawn_mask: Path | None
    water_mask: Path | None


def build_dem(zone_dir: Path, work: Path, params: Params, names: Iterable[SquareName] | None = None,
              water: bool = False, log: Log = _quiet, isofill: str = 'isofill',
              library: bool | None = None) -> Result:
    """From squares to a DEM, in the shell's order: extent, collect, rasterise,
    drawn area, water constraints (off unless asked), water mask, interpolate,
    clamp. ``names`` limits the build to a working set; None builds the zone
    as the shell does. The DEM is None when there was nothing to build."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    squares = squares_with_constraints(Path(zone_dir), names)
    if not squares:
        log('  no squares with contours - nothing to build yet')
        return Result(None, None, {}, None, None, None, None)
    grid = grid_for(squares, params.arcsec)
    log(f'  {len(squares)} squares with contours, {grid.west}..{grid.east} by {grid.south}..{grid.north}, '
        f'{grid.size[0]}x{grid.size[1]} at {params.arcsec:g}"')
    log(f'  fill bounded to {params.fill_metres:g} m = {params.fill_cells} cells')
    gpkg = collect(squares, work, log)
    if gpkg is None:
        return Result(None, grid, squares, None, None, None, None)
    cont = rasterise(gpkg, grid, work)
    mask = drawn_area(cont, grid, work, log)
    if water:
        water_constraints(cont, grid, mask, work, log)
    wmask = water_mask(gpkg, cont, work, log)
    rounded = interpolate(cont, mask, wmask, params, work, isofill, library, log)
    dem = clamp(rounded, cont, wmask, work, log)
    return Result(dem, grid, squares, gpkg, cont, mask, wmask)
