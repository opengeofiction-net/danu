"""From contour squares to a DEM: extent, collect, rasterise, drawn area,
water, interpolate, clamp.

There is one implementation of these stages and this is it. The editor calls
the functions; ``danu-build-zone`` calls ``python -m danu.surface.build`` and
carries on from the DEM with the stages that only a publisher needs - smoothing
for the hillshade, the Mercator copies, the contour extract, the ``.hgt``
archive. Until phase 4 the shell had its own copy of everything above the DEM
and the golden test held the two to the same reference cell for cell; the copy
is gone, and the reasoning that lived in its comments is in the docstrings here.

Parameters come through ``danu.surface.params`` from the shared file
``danu/params/elevation.toml``, with no defaults. The resolution is taken as an
argument rather than from the file, because the golden reference is built at 3
arcseconds so it stays committable, and the shell passes ``--arcsec`` for the
same reason.

The golden test still runs the whole shell script against that reference, so
the surface is still pinned cell for cell. What it no longer does is hold two
implementations to each other, because there are not two.

Where the two callers legitimately differ: the shell builds a *zone*, every
square in the directory, and the editor builds a *working set*. For a square in
the middle of a drawn zone the editor's surface near the set's edge will differ
from the zone build's, because the zone had the neighbours' contours to look at
and the set does not. That is expected, and it is why the golden fixture is a
single square: there the two are the same job, run with water constraints off as
its params.lock records, so neither path reaches Overpass.
"""

from __future__ import annotations

import json
import lzma
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from osgeo import gdal, ogr

from ..core.save import STAGE_MARKER
from ..core.square import SquareName, has_constraints, list_squares, loose_squares
from . import drawn_mask, isofill_lib, land_clamp, sea_mask
from .params import Params

gdal.UseExceptions()

NODATA = -9999
# The first pass, kept beside the surface for the overlay to read, with the
# geotransform of the raster it was filled from. Named here because three
# places have to agree about it - the fill writes it, the build clears the last
# one, and first_pass_classes looks for it - and a convention they each spell
# out separately is one that can quietly stop holding.
#
# What travels with it is what the reader has to agree with to be reading its
# own fill. The geotransform, because a shape is not a grid - a working set
# moved one square over has the same pixel dimensions and different ground
# under them. And the values the first pass was run with, because
# first_pass_classes is handed params of its own and would otherwise ignore
# them entirely whenever a kept pass existed.
#
# What is not covered is a different mask over the same grid with the same
# parameters: the mask shapes the fill and is not hashed here. Nothing produces
# one - the drawn mask is derived from the constraints - and hashing 8.6 million
# bytes on every edit to catch it is not a trade worth making.
PASS1 = 'pass1.npz'


def _pass1_file(work: Path) -> Path:
    return Path(work) / PASS1


def _fill_identity(params: Params, nodata: float | None) -> np.ndarray:
    """What the first pass was run with, as numbers a kept pass can carry:
    the nodata that decides which cells are constraints, and the three values
    that reach it. ``nan`` for no nodata, compared with ``equal_nan``.

    Those three are all of them. ``isofill_lib.run`` sets radius, barrier and
    pass 2 on the C params and leaves grad_min at the library's default, and of
    those only radius and barrier shape the first pass - pass 2 is the step
    after it. grad_min is carried because the file's value is held equal to
    that default by two tests in tests/golden/test_editor_surface.py - one
    reading the binary's usage text, one the library's own defaults - and a
    change to either would change the fill.
    ``threads`` does not change an answer. So this is the whole of what a kept
    pass has to have been filled with, not a sample of it; if another Params
    field ever reaches pass 1, it belongs here."""
    return np.array([np.nan if nodata is None else float(nodata),
                     float(params.fill_cells), float(params.barrier_cells),
                     float(params.grad_min)], dtype=float)
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
    """The raster every stage shares: whole degrees, with half a cell added on
    every side so cell centres sit on the degree lines.

    SRTM is grid registered - pixel centres on whole arcseconds - so the raster
    corner sits half a pixel outside the degree line. The master and the 3
    arcsecond products each need that offset at their own spacing: using one for
    the other leaves a fractional sample count per degree, and SRTMHGT takes
    1201 or 3601 samples square and nothing in between, so it then refuses every
    slice. ``te_at`` takes the spacing for that reason."""

    west: int
    east: int
    south: int
    north: int
    arcsec: float

    @property
    def res(self) -> float:
        return self.arcsec / 3600

    def te_at(self, arcsec: float) -> tuple[float, float, float, float]:
        """gdal's -te at some other spacing: minx miny maxx maxy. Formatted to
        nine places and read back, as the shell wrote it, so that a grid origin
        is the same number whoever computed it."""
        half = arcsec / 7200
        raw = (self.west - half, self.south - half, self.east + half, self.north + half)
        return tuple(float(f'{v:.9f}') for v in raw)

    @property
    def te(self) -> tuple[float, float, float, float]:
        return self.te_at(self.arcsec)

    @property
    def size(self) -> tuple[int, int]:
        w, s, e, n = self.te
        return round((e - w) / self.res), round((n - s) / self.res)


def squares_with_constraints(zone_dir: Path, names: Iterable[SquareName] | None = None,
                             log: Log = _quiet,
                             listing: dict[SquareName, Path] | None = None) -> dict[SquareName, Path]:
    """The squares that hold any ``ele``, by name; the rest are templates.

    A zone's directory carries the blank templates handed out to mappers - one
    frame way, no contours - alongside the squares which have been filled in,
    and building over the blanks costs pixels for nothing: a third of them on
    zone-roantra, plus a published ``.hgt`` of pure zeroes for each. Which
    squares hold something is decided by reading the files rather than by taking
    the extent of the collected geometry: a square is cut out of its DEM on
    pixel boundaries, so lines clipped at its edge overhang by half a cell, and
    a square starting at 26 degrees yields geometry from 25.9996 - which floors
    to the wrong degree. Any tolerance that fixes that is wide enough to discard
    a genuine sliver of data, whereas the filename says exactly which degree
    square a file describes.

    ``listing`` is that directory listing, where the caller has already made
    one and would otherwise be walking the directory twice."""
    staged = is_staging(zone_dir)
    found = (list_squares(zone_dir, compressed_only=not staged) if listing is None
             else dict(listing))
    if names is not None:
        wanted = set(names)
        found = {n: p for n, p in found.items() if n in wanted}
    elif not staged:
        # a bare .osm here is a drop nobody packed, and the zone would be built
        # without that mapper's work in it. In a staging directory it is meant
        loose = loose_squares(zone_dir)
        if loose:
            log(f'  WARNING: not read, being uncompressed: {" ".join(f.name for f in loose)}')
            log('  the squares are held as .osm.xz - xz these and remove the .osm')
    return {n: p for n, p in found.items() if has_constraints(str(p))}


def is_staging(zone_dir: Path) -> bool:
    """Whether this directory is one ``danu.core.save.stage_zone`` made.

    It decides one thing: whether a bare ``.osm`` beside the squares is meant.
    In a zone directory it is a drop somebody never packed, and reading it
    would build a zone from a file nobody else can see; in a staging directory
    it is how the editor hands over the square it has in memory, uncompressed
    because the build is about to expand it anyway."""
    return (Path(zone_dir) / STAGE_MARKER).exists()


def grid_for(names: Iterable[SquareName], arcsec: float) -> Grid:
    """The bounding whole degrees of the squares that hold constraints."""
    names = list(names)
    if not names:
        raise ValueError('no squares with constraints: nothing to build')
    return Grid(west=min(n.lon for n in names), east=max(n.lon for n in names) + 1,
                south=min(n.lat for n in names), north=max(n.lat for n in names) + 1,
                arcsec=float(arcsec))


# --------------------------------------------------------------- collect

def lines_osmconf(work: Path) -> Path:
    """GDAL's OSM config with closed ways read as lines.

    This is the difference between a coastline being a constraint and not being
    one. A coastline is drawn closed and tagged ``natural=coastline``, ``natural``
    is on GDAL's list of area keys, so the driver calls the way an area and files
    it under ``multipolygons`` - a layer the collect reads nothing from, and which
    does not carry ``ele`` anyway. The contours survive only because they are
    tagged with nothing but ``ele``.

    Silently, and the sea then has nothing holding it down: the fill runs its
    whole radius out from the lowest contour it can see and the zero line lands
    there instead of on the shore. On zone-axian that put 99% of the published
    ele=0 vertices more than 500 m out to sea, a median of 1,693 m.

    Derived from the one packaged ``osmconf.ini`` rather than kept as a second
    copy, because ``water_areas`` wants the opposite - ``natural=water`` has to
    be an area there."""
    text = resources.files('danu.surface').joinpath('osmconf.ini').read_text(encoding='utf-8')
    text = re.sub(r'^closed_ways_are_polygons=.*$', 'closed_ways_are_polygons=', text, flags=re.M)
    out = work / 'osmconf-lines.ini'
    out.write_text(text, encoding='utf-8')
    return out


# The tokens the long-way guard counts, and an overlap longer than the longest
# of them so one split across a read boundary is still seen whole
_SCAN = re.compile(rb"""<way\b|</way>|<nd\b|k=["']ele["']""")
_SCAN_OVERLAP = 16


def _way_counts(path: Path, chunk: int = 1 << 20) -> tuple[int, int, int, int]:
    """(ways over 2,000 nodes, ways over 10,000, the longest, ways tagged ele),
    by scanning the XML rather than parsing it.

    Scanned, because this runs on every square of every zone every night and on
    every working set the editor opens. Parsing a square into objects to count
    its ``nd`` elements costs the whole file's geometry for four integers - on
    the largest squares, tens of seconds and a few hundred MB - which is what the
    shell's one streaming ``awk`` pass was avoiding.

    Unlike that ``awk``, an ``ele`` is only credited to a way when it is inside
    one: the old pass counted a tag anywhere, so an ``ele`` on a node before a
    way made that way look tagged."""
    over = drop = longest = ele_ways = 0
    nodes = 0
    in_way = has_ele = False
    carry = b''
    with open(path, 'rb') as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            buf = carry + block
            # a token starting in the last few bytes may not be complete yet, so
            # it waits for the next block rather than being half-read here
            limit = len(buf) - _SCAN_OVERLAP if len(block) == chunk else len(buf)
            for m in _SCAN.finditer(buf):
                if m.start() >= limit:
                    break
                token = m.group()
                if token == b'<way':
                    in_way, nodes, has_ele = True, 0, False
                elif token == b'<nd':
                    nodes += in_way
                elif token == b'</way>':
                    over += nodes > 2000
                    drop += nodes > 10000
                    longest = max(longest, nodes)
                    ele_ways += has_ele
                    in_way = False
                elif in_way:
                    has_ele = True
            carry = buf[max(limit, 0):]
    return over, drop, longest, ele_ways


def check_long_ways(square_path: Path, log: Log, name: str | None = None) -> int:
    """How many ways in the square carry an ``ele``, having refused it if any
    way is too long for GDAL to read. Takes the expanded square, which
    ``collect`` has written out for GDAL anyway, and ``name`` for the messages -
    the expanded file is called square.osm and saying so would tell an operator
    nothing about which square to go and fix.

    GDAL's OSM driver drops any way over 10,000 nodes. It says so once per node
    beyond the limit, so one 45,000 node contour buries the message under 35,000
    identical lines and GDAL's own 1,000 error cap hides the rest - which is how
    ten contours between 101 m and 171 m went missing from S37E147_Madison_City,
    45% of that square's contour length, and came back as voids nobody could
    account for. A blank square is better than a quietly wrong one, so this
    stops. The warning threshold is the OSM API's own limit, which these files
    would have to satisfy to be uploaded; ``danu.core.split_long_ways`` fixes
    both."""
    name = name or square_path.name
    over, drop, longest, ele_ways = _way_counts(square_path)
    if drop:
        raise ValueError(f'{name} has {drop} way(s) over 10,000 nodes (longest {longest}); '
                         f'GDAL drops these silently. Run danu.core.split_long_ways')
    if over:
        log(f'  WARNING: {name} has {over} way(s) over 2,000 nodes (longest {longest}), '
            f'which the OSM API would reject on upload')
    return ele_ways


def collect(squares: dict[SquareName, Path], work: Path, log: Log = _quiet) -> Path | None:
    """Every square's contour ways into one GeoPackage layer, ``contour``, with
    a numeric ``ele``. None when there are no contours at all.

    Every way carrying a numeric ``ele`` is a constraint: contours, and the
    water edges at ele 0. Ways without one - the frame, stray tagging - are
    ignored.

    A zone's squares are held compressed; a staging directory's edited ones are
    not. Either is read, and an expanded one is read where it lies."""
    gpkg = work / 'contours.gpkg'
    if gpkg.exists():
        gpkg.unlink()
    conf = lines_osmconf(work)
    square = work / 'square.osm'
    first = True
    before = 0
    with gdal.config_options({'OSM_CONFIG_FILE': str(conf), 'OSM_USE_CUSTOM_INDEXING': 'NO',
                              # A square whose in-memory database exceeds
                              # OSM_MAX_TMPFILE_SIZE (100 MB) spills to disk.
                              # Without this GDAL writes the spill relative to
                              # the current directory, which under systemd is /
                              # and unwritable: the copy fails and the driver
                              # returns the square as zero features, silently,
                              # with a non-zero exit code nowhere
                              'CPL_TMPDIR': str(work)}):
        for name, path in sorted(squares.items()):
            # GDAL has no VSI handler for xz - there is one for zip, gzip and
            # 7z, but not this - so a compressed square is expanded into the
            # working directory, read, and dropped again. One at a time, so the
            # cost is the largest square rather than the whole zone. A square
            # that is already expanded, which is how the editor stages the one
            # it is holding, is read where it lies.
            #
            # Whether an expanded square should be here at all was decided by
            # squares_with_constraints, which reads the staging marker: outside
            # a staging directory a bare .osm is reported and never reaches
            # this dict. This step takes the files it is given.
            expanded = path.suffix != '.xz'
            source = path
            if not expanded:
                with lzma.open(path, 'rb') as src, open(square, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                source = square
            # the guard reads the expanded file, not the archive: GDAL needs it
            # expanded regardless, so the square is decompressed once a build
            ele_ways = check_long_ways(source, log, name=path.name)
            opts = dict(format='GPKG', layers=['lines'], where='ele IS NOT NULL', layerName='contour')
            if first:
                opts['geometryType'] = 'LINESTRING'
            else:
                opts['accessMode'] = 'append'
            gdal.VectorTranslate(str(gpkg), str(source), options=gdal.VectorTranslateOptions(**opts))
            first = False
            if not expanded:
                square.unlink()
            # A square can convert to nothing and still succeed: the OSM driver
            # spills to disk over OSM_MAX_TMPFILE_SIZE, and if that write fails
            # it hands back an empty layer rather than an error. That cost
            # liberian 16,555 of its 20,472 constraint lines - 81% of the zone -
            # across every build until CPL_TMPDIR was set above, and nothing in
            # the run said so. The count at the end cannot see it, because the
            # other squares carry the total past zero
            now = _feature_count(gpkg)
            if ele_ways and now == before:
                raise ValueError(
                    f'{path.name} has {ele_ways} way(s) tagged ele but converted to none. '
                    f'Check the run for "Cannot create" - the OSM driver loses a square '
                    f'silently when its temporary file cannot be written')
            before = now
    if not gpkg.exists():
        return None
    ds = ogr.Open(str(gpkg), update=1)
    # ele is a string, and not every string is a height. Squares carry ele=TBD
    # on lake outlines nobody has surveyed yet, ele=tbd on peaks, the odd
    # ele=169s typo - and rasterising -a ele coerces each of them to 0, planting
    # a sea level constraint across whatever the way runs over. Worse than no
    # constraint, since the fill then drags the ground around it down to meet
    # the line. Cleaned here rather than filtered on the way in: the where above
    # goes to the OSM driver, whose OGR SQL has no pattern test this needs, and
    # the GeoPackage is SQLite and does
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
        # Not a failure. A zone's directory holds the blank templates handed out
        # to mappers - one frame way, no contours - and a zone which is all
        # templates has nothing to build yet rather than something wrong with it
        log('  no contours in any square, nothing to build yet')
        return None
    log(f'  {features} constraint lines')
    # Water with nothing holding it at sea level is the largest error this
    # pipeline can produce - 46 m RMS over the water in the one roantra square
    # the water file did not reach - and it is silent, because the result looks
    # like plausible terrain. A zone with no zero constraint anywhere either has
    # no sea, which is fine, or has sea nobody has drawn a coastline for
    log(f'  {zeros} of them at ele 0, holding sea level')
    if zeros == 0:
        log('  WARNING: no ele 0 constraint anywhere. If this ground has sea, its squares need '
            'coastline, or the water will interpolate upward')
    return gpkg


def _feature_count(gpkg: Path, layer_name: str = 'contour') -> int:
    """A layer's feature count, or 0 where the file or the layer is not there
    yet - which is the state a square that converted to nothing leaves."""
    if not gpkg.exists():
        return 0
    ds = ogr.Open(str(gpkg))
    if ds is None:
        return 0
    layer = ds.GetLayerByName(layer_name)
    n = layer.GetFeatureCount() if layer is not None else 0
    layer = None
    ds = None
    return int(n)


# ------------------------------------------------------------- rasterise

def rasterise(gpkg: Path, grid: Grid, work: Path) -> Path:
    """The constraints as an Int16 raster of metres, nodata where none.

    Int16, not Int32: elevations fit with room to spare and so does the nodata,
    and at 1 arcsecond the wider type costs 1.7 GB of the clamp's working set.

    All touched, not only the cells a line passes through the middle of: a thin
    line leaves diagonal gaps, and the fill's sight test threads them - a ray
    reaches the ground behind a coastline without crossing it."""
    out = work / 'cont.tif'
    gdal.Rasterize(str(out), str(gpkg), options=gdal.RasterizeOptions(
        format='GTiff', allTouched=True, attribute='ele', noData=NODATA, initValues=[NODATA],
        outputType=gdal.GDT_Int16, xRes=grid.res, yRes=grid.res, outputBounds=list(grid.te),
        creationOptions=CREATE))
    return out


def drawn_area(cont: Path, grid: Grid, work: Path, log: Log = _quiet) -> Path:
    """Where the contours describe ground, as a byte mask on the same grid.

    The zone raster is the bounding box of the squares holding contours, and a
    bounding box is not the shape they describe: zone-gobras is five drawn
    squares in a four by four box, and even within those five only 37% of the
    area has contours near it.

    Unmasked, the second pass carries values across the undescribed ground in
    streaks the length of whatever it is allowed to cross - every row is
    anchored at zero only beyond its ends, so across an empty region there is
    nothing in between to stop it. Measured on ellarca, the blocks smeared right
    across were 100% cells the first pass never reached, against a 0.1% median
    elsewhere.

    ``drawn_mask`` takes the convex hull of the contours in each degree square,
    clipped to that square. It masks where there is no data, not where the fill
    is merely far from a contour: inside the described area the fill still
    reaches everywhere, which is the point of the reach behaviour. Bounding the
    carry instead, with isofill's ``--pass2-tile``, would suppress the streaks by
    reopening the voids.

    On gobras that is 5.5% of the raster against 31.2% for the squares that
    contain the contours, and it takes nothing from makaska's S37E147, whose
    sparse contours span their square: the hull covers 95.1% of it and masks out
    none of its terrain. Contours inside the mask still inform cells outside it,
    so its edge is not a wall to the ground beyond."""
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
    drawn area.

    Contours describe the ground every 25 m of height and say nothing between,
    which is exactly where a river is. The interpolator has no reason to put the
    valley floor under the drawn water rather than anywhere else in the band, so
    it does not. Reading the water as a constraint of its own puts it there.

    After the mask, and not before it, for two reasons which are really the same
    one. ``drawn_mask`` derives the envelope from the constraints, so water
    written earlier grows the mask along every river and the fill then works
    ground the contours never described. And the water is held inside that
    envelope, because a graded river reaching past the last contour has nothing
    to blend into: it came out as a 4.7 km strip of 449 m ground standing in a
    void held at zero, which is a wall in the hillshade at the edge of the
    mapped contours.

    A failure is a warning and the build goes on, which is also what happens
    with no network: a zone without this is the DEM we published yesterday.
    Run as a command, because it is one."""
    w, s, e, n = grid.te
    run = subprocess.run([sys.executable, '-m', 'danu.water.constraints', str(cont),
                          '--bbox', f'{w},{s},{e},{n}', '--mask', str(mask),
                          '--report', str(work / 'water-report.json')],
                         capture_output=True, text=True)
    if run.returncode != 0:
        log('  WARNING: water constraints failed, continuing without them')
        log(run.stderr[-800:])


def water_areas(water_file: Path, grid: Grid, work: Path, log: Log = _quiet) -> Path:
    """Sea and lakes from a curated water file, as a byte mask.

    ``natural=water`` states that its interior is water; a closed coastline ring
    does not, being equally able to describe an island - which is why this reads
    the areas and ``water_mask`` reads directions. Used only to tell land at sea
    level from the sea itself; the squares remain the elevation source of truth.

    The file is per zone and optional. No zone has had one since the coastline
    direction below started producing the same artefact from the squares
    themselves, and the directory it is read from is empty on the server."""
    log(f'  water areas from {water_file.name}')
    areas = work / 'water-areas.gpkg'
    for f in (areas, work / 'water-mask.tif'):
        if f.exists():
            f.unlink()
    conf = resources.files('danu.surface').joinpath('osmconf.ini')
    with gdal.config_options({'OSM_CONFIG_FILE': str(conf), 'OSM_USE_CUSTOM_INDEXING': 'NO',
                              'CPL_TMPDIR': str(work)}):
        gdal.VectorTranslate(str(areas), str(water_file), options=gdal.VectorTranslateOptions(
            format='GPKG', layers=['multipolygons'], where="natural='water'", layerName='water'))
    found = _feature_count(areas, 'water')
    log(f'  {found} water areas')
    if found == 0:
        log(f'  WARNING: {water_file.name} has no natural=water areas, so the mask is empty and '
            f'enclosed water will read as land. The coastline direction is the other way to this, '
            f'and it is what a zone with no water file uses')
    out = work / 'water-mask.tif'
    gdal.Rasterize(str(out), str(areas), options=gdal.RasterizeOptions(
        format='GTiff', burnValues=[1], initValues=[0], outputType=gdal.GDT_Byte,
        xRes=grid.res, yRes=grid.res, outputBounds=list(grid.te), creationOptions=CREATE))
    return out


def water_mask(gpkg: Path, cont: Path, work: Path, log: Log = _quiet) -> Path | None:
    """Sea, from the coastline's own direction - land on the left, water on the
    right - which the squares already carry. None when they carry no coastline.

    It exists to stop the fill leaving elevation offshore: on zone-alved it
    covers 96.8% of the cells which had it, and 99.6% of what it marks is
    genuinely sea. Same artefact as ``water_areas``, same slot, no file to
    maintain.

    Built before the fill, not after it. It has always been derived from the
    collected contours and the constraint raster, both of which exist by now, so
    the order was free either way - until ``--pass2 diffuse``, which needs the
    sea as a boundary rather than as something to clean up afterwards. Laplace
    has no notion of running out of information: bounded by a coastline at zero
    on one side and whatever the far shore carries on the other, it ramps
    between them and fills the sea. On zone-ellarca that took the sea from
    67.32% of the zone to 59.76%, because ``land_clamp`` looks for candidate sea
    where the DEM reads zero and water carrying a value is no longer recognised
    as water. The linear pass never needed telling, since it anchored every row
    and column at zero one step past its ends - a pull towards zero wherever the
    data is sparse, which was doing this job as a side effect."""
    out = work / 'water-mask.tif'
    if out.exists():
        out.unlink()
    if sea_mask.sea_mask(str(gpkg), str(cont), str(out), log=log):
        return out
    log('  no coastline - enclosed water will read as land unless a contour holds it')
    return None


def interpolate(cont: Path, mask: Path, water: Path | None, params: Params, work: Path,
                isofill: str = 'isofill', library: bool | None = None, log: Log = _quiet,
                extra: list[str] | None = None, keep_pass1: bool = False) -> Path:
    """The surface between the constraints, by isofill.

    isofill, not ``gdal_fillnodata``: the latter will interpolate from a single
    sample, which terraces the surface into plateaus with straight edges where
    the chosen sample switches. A hillshade is a derivative and shows that
    plainly where a slope histogram averages it away. isofill takes the steepest
    pair of contours in line of sight and declines to fill at all from one,
    which is also what keeps water enclosed by a coastline empty.

    Its output is Float32, and has been since September 2026 - both passes work
    in float and write float. There is no rounding step after it either way:
    ``clamp`` writes the published DEM, and the whole-metre grid is what the
    float output exists to escape. (isofill's own README still says Int16 in its
    opening summary and Float32 forty lines later; the code writes Float32.)

    The barrier - how wide a contour is for the sight test only, not for its
    value - was tuned by measuring open water, so 1 was tried on the grounds
    that a thicker wall occludes the second contour a cell needs in order to
    interpolate at all, pushing cells out of the first pass and into the second,
    which has to invent them. Measured on zone-ellarca inside the described
    area, first pass only, at barrier 0, 1, 2 and 3, the ground the first pass
    resolves is 54.88, 54.71, 49.29 and 46.46%: all of the cost sits between 1
    and 2, 5.4 points, a ninth of what the pass answers.

    It was reverted because none of that reaches the map. Five zones were built
    at 1 and inspected against the same zones at 2, and the hillshade is the
    same picture - the cells that move are ones the second pass was already
    filling with the value the first pass would have derived. What does not come
    back is the cost: 195 s against 175 s on ellarca, and elevation left over
    water 0.776% against 0.738%, or on zone-tapira, which is 92% sea, 42 cells
    against 12. So 2 stands, on runtime and on the sea, and the measurement is
    kept because it says where to look if the first pass ever needs widening:
    the whole of the barrier's effect on coverage is in that one step.

    Needs isofill 0.4.0 or later, which fills the cells the first pass found
    nothing for rather than leaving them at zero - the behaviour 0.3.1 had
    behind ``--no-reach``. Against 0.3.1's default, 114,309 cells in zone-tapira
    read 1 m between ground at 130 m.

    Through the library by default - the binary's own in-core path is a call to
    the same function - and through the binary where the library cannot be
    loaded, or where the raster is larger than the in-core fill would hold and
    the binary would band it, which the library does not do. ``library`` forces
    the choice: True demands the library and raises rather than fall back, False
    never tries it; None is the default described above. ``extra`` is further
    flags for trying a change on one zone before it becomes the default, and it
    takes the binary, since the library has no flags to give them to.

    ``keep_pass1`` writes the first pass beside the surface, under the one name
    ``PASS1``, which is what ``first_pass_classes`` looks for: what the first
    pass left, from this same fill rather than from a second one. Only the
    library can give it - the binary writes one raster - and where the binary
    is what runs, for any of the reasons above, that is logged rather than left
    for the overlay to find out by filling again.

    No ``--grad-min``: the file's value is held equal to isofill's own default
    by a test, and neither path passes it. ``pass2`` has one implemented value
    and this refuses any other rather than ignoring it."""
    if params.pass2 != 'diffuse':
        raise ValueError(f'pass2 = {params.pass2!r}: isofill implements only "diffuse" ("linear" was removed)')
    out = work / 'rounded.tif'
    if out.exists():
        out.unlink()
    if extra:
        log(f'  extra isofill flags, so the binary: {" ".join(extra)}')
        if library is True:
            raise ValueError(f'extra isofill flags ({" ".join(extra)}) need the binary, not the library')
        library = False
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
                return _interpolate_library(lib, ds, cont, mask, water, params, out, log,
                                            _pass1_file(work) if keep_pass1 else None)
    if keep_pass1:
        # the caller asked for the first pass and is not going to get one: the
        # binary writes a single raster. Said here rather than left for the
        # overlay to discover, because from there it looks like a build that
        # never asked, and the second fill it then runs is the cost this flag
        # exists to avoid
        log('  the binary cannot keep the first pass, so the overlay will fill again')
    return _interpolate_binary(cont, mask, water, params, out, isofill, extra, log)


def _same_grid(a, b, a_path: Path, b_path: Path) -> None:
    """The binary checks the mask and water are the constraints' size; the
    library path checks they are the constraints' grid, since here the
    arrays meet with no file to carry the georeferencing."""
    if (a.RasterXSize, a.RasterYSize) != (b.RasterXSize, b.RasterYSize):
        raise ValueError(f'{b_path.name} is {b.RasterXSize}x{b.RasterYSize}, '
                         f'{a_path.name} is {a.RasterXSize}x{a.RasterYSize}')
    ga, gb = a.GetGeoTransform(), b.GetGeoTransform()
    res = abs(ga[1])
    # in cells, not degrees: an origin around 100 and a cell of 1/3600 are
    # eight orders apart, and one absolute tolerance cannot serve both
    off_by = max(abs(ga[0] - gb[0]), abs(ga[3] - gb[3])) / res
    scale_by = max(abs(ga[1] - gb[1]), abs(ga[5] - gb[5])) / res
    if off_by > 1e-6 or scale_by > 1e-9:
        raise ValueError(f'{b_path.name} is not on {a_path.name}\'s grid: origin off by {off_by:g} cells')


def _interpolate_library(lib, ds, cont: Path, mask: Path, water: Path | None, params: Params,
                         out: Path, log: Log, pass1: Path | None = None) -> Path:
    """The library call, with the rasters read to arrays and the surface written
    as the binary writes it: Float32, ZSTD, the float predictor. This is the
    in-core branch of isofill.c's own main(), which is isofill_run()."""
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
    result = lib.run(cons, params, mask=m, water=w, nodata=nodata, keep_pass1=pass1 is not None)
    surface, filled = result[0], result[1]
    log(f'  isofill {lib.version} as a library: pass 1 set {filled:,} of {cons.size:,} cells')
    if pass1 is not None:
        # the first pass is nearly all of the fill, so the alternative is
        # running the whole thing again to read it
        np.savez(pass1, surface=result[2],
                 gt=np.asarray(ds.GetGeoTransform(), dtype=float),
                 fill=_fill_identity(params, nodata))
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
                        isofill: str, extra: list[str] | None = None, log: Log = _quiet) -> Path:
    """The binary, with the flags the build sets and no others.

    What isofill may hold is a budget, not a peak. The two passes decide
    separately whether to band, and they are not equal: the first reads each
    band with a radius margin, so every interior cell still sees its whole
    search circle and a banded run is exact. The second banded is an
    approximation. So the budget wants to be large enough for the second pass on
    the largest zone even where the first must band - 13.6 GB for zone-yuethon
    at 46801 square, against 26.5 GB to hold that zone's first pass whole.

    isofill sizes its own arrays against the budget, and GDAL's block cache, the
    rasterisation and the contour reads all sit outside it. Once isofill's own
    figures were made honest - the banded first pass also holds the whole output
    array, and the second pass holds both mask rasters - the measured peak on
    zone-axian is 1.06 times the budget, so it is close to the real ceiling
    rather than a number to multiply. 18500 clears every zone's second pass, the
    largest being zone-yuethon at 18104 MB, and puts the peak near 19.6 GB:
    inside util's guaranteed 24 without leaning on the balloon, which the host
    can reclaim mid-run. Below it the big zones fall to the second pass's
    out-of-core path, which is an approximation - at 15000, zone-axian took it
    and came out with a different sea."""
    cmd = [isofill, '--radius', str(params.fill_cells), '--barrier', str(params.barrier_cells),
           '--max-mem', str(params.max_mem_mb), '--mask', str(mask)]
    if water is not None:
        cmd += ['--water', str(water)]
    cmd += list(extra or [])
    cmd += [str(cont), str(out)]
    # which of the two ran, in the zone's own log. The library and the binary
    # are held equal cell for cell by the golden test, so this is not a warning
    # - but a build that silently changed code path between one night and the
    # next would be a bad thing to have to work out afterwards
    log(f'  isofill as the binary: {isofill}')
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f'isofill failed ({run.returncode}):\n{run.stderr[-2000:]}')
    return out

def clamp(rounded: Path, cont: Path, water: Path | None, work: Path, log: Log = _quiet,
          params: Params | None = None) -> Path:
    """Sea to zero, land never zero, the constraints back untouched, written as
    the published DEM is written.

    Land at sea level is not the sea. Flat coastal ground whose nearest
    constraint is the coastline interpolates to zero, and zero is transparent in
    the relief ramp, so it would vanish from the map - 64% of the low land in
    zone-roantra did."""
    out = work / 'dem.tif'
    if out.exists():
        out.unlink()
    land_clamp.clamp(str(rounded), str(cont), str(out), str(water) if water else None,
                     log=log, params=params)
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
    envelopes: Path | None = None       # drawn.geojson, the outline R21 draws
    blank: int = 0                      # squares with a file but no contours


def build_dem(zone_dir: Path, work: Path, params: Params, names: Iterable[SquareName] | None = None,
              water: bool = False, log: Log = _quiet, isofill: str = 'isofill',
              library: bool | None = None, water_file: Path | None = None,
              extra: list[str] | None = None, stage: Log = _quiet,
              keep_pass1: bool = False) -> Result:
    """From squares to a DEM: extent, collect, rasterise, drawn area, water
    constraints (off unless asked), water mask, interpolate, clamp. ``names``
    limits the build to a working set; None builds the whole zone. ``stage`` is
    called with each stage's name as it starts, which is where the timings come
    from. The DEM is None when there was nothing to build."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stage('extent')
    listing = list_squares(Path(zone_dir), compressed_only=not is_staging(zone_dir))
    squares = squares_with_constraints(Path(zone_dir), names, log, listing=listing)
    # how many of the zone's squares are templates, which is a zone-wide count
    # and means nothing about a working set - the editor asks for named squares
    # and the ones it did not ask for are not blank, they are elsewhere
    blank = len(listing) - len(squares) if names is None else 0
    if not squares:
        # two different nothings: a zone whose squares are all still templates,
        # and a working set the editor opened over ground nobody has drawn.
        # blank counts the first and is 0 for the second, so the message has to
        # say which rather than reporting "0 squares, none with contours"
        log(f'  {blank} squares, none with contours - nothing to build yet' if names is None
            else '  no contours in this working set - nothing to build')
        return Result(None, None, {}, None, None, None, None, blank=blank)
    grid = grid_for(squares, params.arcsec)
    log(f'  {len(squares)} squares with contours ({blank} blank), '
        f'{grid.west}..{grid.east} by {grid.south}..{grid.north}, '
        f'{grid.size[0]}x{grid.size[1]} at {params.arcsec:g}"')
    log(f'  fill bounded to {params.fill_metres:g} m = {params.fill_cells} cells')
    stage('collect')
    gpkg = collect(squares, work, log)
    if gpkg is None:
        return Result(None, grid, squares, None, None, None, None, blank=blank)
    stage(f'rasterise at {params.arcsec:g}"')
    cont = rasterise(gpkg, grid, work)
    stage('drawn area')
    mask = drawn_area(cont, grid, work, log)
    if water:
        stage('water constraints from the drawn rivers and lakes')
        water_constraints(cont, grid, mask, work, log)
    if water_file is not None:
        stage('water areas')
        wmask = water_areas(Path(water_file), grid, work, log)
    else:
        stage('water from the coastline direction')
        wmask = water_mask(gpkg, cont, work, log)
    stage(f'interpolate, radius {params.fill_cells} cells, barrier {params.barrier_cells}')
    pass1 = _pass1_file(work)
    if pass1.exists():
        pass1.unlink()                       # never a previous build's
    rounded = interpolate(cont, mask, wmask, params, work, isofill, library, log, extra, keep_pass1)
    stage('clamp')
    dem = clamp(rounded, cont, wmask, work, log, params)
    return Result(dem, grid, squares, gpkg, cont, mask, wmask,
                  envelopes=work / 'drawn.geojson', blank=blank)


# ------------------------------------------------------------------- cli

def _shell_assignments(result: Result, params: Params) -> str:
    """What ``danu-build-zone`` needs in order to carry on from the DEM: the
    degree extent for the .hgt slicing, the 3 arcsecond grid for the derivative,
    and the DEM itself. Written to a file and sourced rather than eval'd from
    stdout - ``eval "$(cmd)"`` takes eval's exit status, so a build that died
    here would have been carried on from silently."""
    lines = [f'SQUARES={len(result.squares)}', f'BLANK={result.blank}']
    if result.grid is not None:
        g = result.grid
        lines += [f'WEST={g.west}', f'EAST={g.east}', f'SOUTH={g.south}', f'NORTH={g.north}',
                  'TE_HGT="{} {} {} {}"'.format(*(f'{v:.9f}' for v in g.te_at(params.hgt_arcsec)))]
    lines.append(f'DEM={result.dem or ""}')
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    """``python -m danu.surface.build <zone-dir> <work-dir>`` - the stages up to
    the DEM, for a caller that goes on to publish. The log goes to stdout; the
    shell assignments go to the file ``--shell`` names, so nothing on stdout is
    ever evaluated."""
    import argparse
    import time
    from . import params as params_module

    ap = argparse.ArgumentParser(prog='python -m danu.surface.build', description=main.__doc__)
    ap.add_argument('zone_dir', type=Path, help='the directory of .osm.xz squares')
    ap.add_argument('work', type=Path, help='where the working rasters go')
    ap.add_argument('--arcsec', type=float, help='resolution; the file\'s value by default')
    ap.add_argument('--hgt-arcsec', type=float,
                    help='the spacing TE_HGT is reported at; the file\'s value by default. An '
                         'argument for the same reason --arcsec is: the caller may be overriding '
                         'it, and TE_HGT has to be the grid the caller then slices on')
    ap.add_argument('--params', type=Path, help='an elevation.toml other than the packaged one')
    ap.add_argument('--water-constraints', action='store_true',
                    help='read rivers and lakes from Overpass as constraints')
    ap.add_argument('--water-areas', type=Path, metavar='FILE',
                    help='a curated natural=water file, in place of the coastline direction')
    ap.add_argument('--isofill-extra', default='', metavar='FLAGS',
                    help='further isofill flags, for trying a change on one zone')
    ap.add_argument('--shell', type=Path, metavar='FILE', help='write shell assignments here')
    ap.add_argument('--timings', type=Path, metavar='FILE', help='append stage timings here')
    ap.add_argument('--since', type=float, default=0.0, metavar='SECONDS',
                    help='what the caller\'s clock read when it handed over, so the '
                         'timings are one series and not two')
    ap.add_argument('--zone', default='', help='the zone name, for the stage headings')
    args = ap.parse_args(argv)

    p = params_module.load(args.params)
    if args.arcsec is not None:
        p = p.with_arcsec(args.arcsec)
    if args.hgt_arcsec is not None:
        p = replace(p, hgt_arcsec=float(args.hgt_arcsec))

    began = time.monotonic()
    prefix = f'{args.zone}: ' if args.zone else ''

    def log(line: str) -> None:
        print(line, flush=True)

    def stage(name: str) -> None:
        if args.timings:
            with open(args.timings, 'a', encoding='utf-8') as fh:
                fh.write(f'{round(args.since + time.monotonic() - began)}\t{name}\n')
        print(f'=== {prefix}{name} ===', flush=True)

    try:
        result = build_dem(args.zone_dir, args.work, p, water=args.water_constraints,
                           log=log, water_file=args.water_areas,
                           extra=args.isofill_extra.split() or None, stage=stage)
    except (ValueError, FileExistsError, RuntimeError, isofill_lib.IsofillError) as e:
        print(f'{prefix}{e}', file=sys.stderr)
        return 1
    if args.shell:
        Path(args.shell).write_text(_shell_assignments(result, p), encoding='utf-8')
    return 0


# ------------------------------------------------------------ first pass

# isofill's sentinels for a cell the first pass did not answer, from
# isofill.c: nothing within reach; a pair too flat to trust; a single level
OUT_OF_REACH, NO_ELEV, ONE_LEVEL = -32767, -32768, -32766
# the classes first_pass_classes() writes
ANSWERED, UNREACHED, DECLINED, ONE_ONLY, OUTSIDE = 0, 1, 2, 3, 255


def first_pass_reading(classes: np.ndarray, gt: tuple) -> dict:
    """Cells, square kilometres and share of the drawn area, per class, on
    the constraints' own lat/lon grid. A cell's ground area is its degree
    size squared times cos(latitude) of its row: a cell at 20 N is 6% smaller
    on the ground than at the equator and at 60 N half the size. Counted here
    and nowhere else, so the build log and the panel say one number; the
    Mercator grid the overlay is drawn on inflates area by 1/cos² and is not
    a place to measure it."""
    rows, cols = classes.shape
    lat_rows = gt[3] + (np.arange(rows) + 0.5) * gt[5]
    km_per_deg = 111.32
    cell_km2 = (abs(gt[1]) * km_per_deg) * (abs(gt[5]) * km_per_deg) * np.cos(np.radians(lat_rows))
    inside = classes != OUTSIDE
    out = {'cells': {}, 'km2': {}, 'percent': {},
           'inside_cells': int(inside.sum()), 'inside_km2': float((inside.sum(axis=1) * cell_km2).sum())}
    for code in (UNREACHED, DECLINED, ONE_ONLY):
        rowsum = (classes == code).sum(axis=1)
        out['cells'][str(code)] = int(rowsum.sum())
        out['km2'][str(code)] = float((rowsum * cell_km2).sum())
        out['percent'][str(code)] = (100.0 * out['km2'][str(code)] / out['inside_km2']) if out['inside_km2'] else 0.0
    return out


def first_pass_classes(cont: Path, mask: Path, params: Params, work: Path,
                       log: Log = _quiet) -> Path:
    """Where the first pass found no answer, as a byte raster on the
    constraints' grid: 1 nothing in reach, 2 a pair too flat to trust, 3 a
    single level in sight, 0 answered or a constraint, 255 outside the drawn
    area. R20 calls this the single most useful thing the editor can tell a
    mapper - here is ground your contours do not describe - and the
    validation table wants it as area and fraction.

    The published build never runs this - it is the diagnostic isofill's README
    describes, ``--no-pass2`` - and the editor runs it on every surface, for the
    overlay.

    It reads the first pass ``build_dem(keep_pass1=True)`` left rather than
    filling again where there is one - having checked that the pass is of this
    grid and was filled with the four values that reach the first pass, since
    otherwise ``params`` would mean something on one path and nothing on the
    other -
    which is the difference between an edit
    costing one fill and two: the first pass is 0.56 s of a 0.67 s run, so the
    second fill was 95 s of the 208 s an edit took at 1 arcsecond on a three by
    three working set. Without one - the binary writes a single raster, and a
    build that took the binary leaves none - it runs the fill itself, which is
    what it always did."""
    ds = gdal.Open(str(cont))
    band = ds.GetRasterBand(1)
    # The constraints raster is the grid: its geotransform measures the reading
    # below and its size is what the classes are written out on. Everything else
    # is checked against it rather than against whatever it came with - a kept
    # first pass and the mask beside it are from the same build, so they agree
    # with each other and would say nothing about belonging to this one.
    grid = (ds.RasterYSize, ds.RasterXSize)
    m_ds = gdal.Open(str(mask))          # held: a chained Open().GetRasterBand() frees the dataset under the band
    m = m_ds.GetRasterBand(1).ReadAsArray()
    if m.shape != grid:
        raise ValueError(f'the drawn mask is {m.shape}, the constraints are {grid}')
    kept = _pass1_file(work)
    if kept.exists():
        with np.load(kept) as held:
            surface, gt, fill = held['surface'], held['gt'], held['fill']
        want = _fill_identity(params, band.GetNoDataValue())
        if surface.shape != grid or not np.array_equal(gt, np.asarray(ds.GetGeoTransform())):
            raise ValueError(
                f'the kept first pass is {surface.shape} at {(gt[0], gt[3])}, the constraints '
                f'are {grid} at {(ds.GetGeoTransform()[0], ds.GetGeoTransform()[3])}; '
                f"it is not this build's")
        if not np.array_equal(fill, want, equal_nan=True):
            raise ValueError(
                f'the kept first pass was filled with nodata/radius/barrier/grad_min {tuple(fill)}, '
                f'and this asks for {tuple(want)}; it is not this build\'s')
    else:
        log('  no first pass was kept, so the fill runs again for the overlay')
        lib = isofill_lib.Isofill.load()
        cons = band.ReadAsArray().astype(np.float32)
        surface, _ = lib.run(cons, params, mask=m, nodata=band.GetNoDataValue(), pass2=False)
    classes = np.full(grid, ANSWERED, np.uint8)
    classes[surface == OUT_OF_REACH] = UNREACHED
    classes[surface == NO_ELEV] = DECLINED
    classes[surface == ONE_LEVEL] = ONE_ONLY
    classes[m == 0] = OUTSIDE
    reading = first_pass_reading(classes, ds.GetGeoTransform())
    for name, code in (('nothing in reach', UNREACHED), ('too flat to trust', DECLINED), ('one level only', ONE_ONLY)):
        if reading['inside_cells']:
            log(f'  first pass, {name}: {reading["cells"][str(code)]:,} cells, '
                f'{reading["km2"][str(code)]:,.1f} km², {reading["percent"][str(code)]:.1f}% of the drawn area')
    (work / 'first-pass.json').write_text(json.dumps(reading), encoding='utf-8')
    out = work / 'first-pass.tif'
    o = gdal.GetDriverByName('GTiff').Create(str(out), ds.RasterXSize, ds.RasterYSize, 1, gdal.GDT_Byte,
                                             options=CREATE)
    o.SetGeoTransform(ds.GetGeoTransform())
    o.SetProjection(ds.GetProjection())
    o.GetRasterBand(1).WriteArray(classes)
    o.FlushCache()
    o = None
    return out



if __name__ == '__main__':
    sys.exit(main())
