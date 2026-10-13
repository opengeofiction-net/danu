"""The ground in view at 1 arcsecond, held on the 3 arcsecond surface - R43.

The working set's surface is at 3 arcseconds, and at z15 and closer the ground
in view is at 1. Solving the view alone is what makes that affordable, and it
rests on the same two facts the preview does. The first pass is local: a cell's
value depends only on contours within the radius, so a box grown by the radius
gives every cell in it the whole raster's answer, to the bit. The second pass is
not, and a box solved against a rim is an approximation - held here at the 3
arcsecond surface, brought up to 1 arcsecond, rather than at a 1 arcsecond
surface nobody has.

How far beyond the view the solve has to reach was measured, against an exact
whole 1 arcsecond solve, on 28 views of gobras City and 50 of ellarca's 2x2, at
the size of a screen at z15 (250 by 150 cells) and at z14 (500 by 300). With no
margin a z14 view was 2.1 m out on gobras and 2.7 m on ellarca; a radius was
enough at z15 and not at z14, 2.1 m again on one gobras view; a radius and a
half put every view within 4 cm on both.

The golden square needed more, and taught why. Ten of fifty z15 views centred
on its drawn ground were out by up to 138 m at a radius and a half, every one
near the edge of the drawn area, and the cells wrong were ground the first pass
left to the second. The 3 arcsecond surface there is itself 111 m from the 1
arcsecond one: a contour burned at 3 arcseconds is three times as wide, closes
gaps the 1 arcsecond burn leaves open, and seals a patch the finer grid drains
to zero through one. A rim held at the coarse answer brings the coarse
topology with it. Two radii left four views out; two and a half left none, the
worst 2 mm. So the view is grown by two and a half, and the first pass searches
only there: the radius beyond it is read, for the contours it holds, and is not
itself answered, which takes a third off the first pass.

What that costs is the first pass over the grown view. On the densest z15 view
of gobras City, 22.5% of it contour, it is 3.5 s on a machine running the whole
square's first pass in 37 s - which took 21 s the day I1 measured it, so about
1.9 s at that speed. The median view is half that.

The void, which isofill decides by flooding from the edge of the drawn area,
was the fault the scratch work found first: a box that floods from its own edge
calls a pocket void and holds it at zero, 94 to 472 m out on ellarca. Holding
the box's rim fixes that by itself, since a held cell is not out of reach and
seeds nothing - taking the void from the 3 arcsecond solve instead changed no
view by as much as a centimetre, so it is not done.

Everything the solve reads is local, so it is computed for the window rather
than read off a whole 1 arcsecond raster nobody has built:

* the constraints, burned at 1 arcsecond from the preview's contour layer;
* the drawn area, by ``drawn_mask``'s rule, from each degree square's contours
  burned at 1 arcsecond - once a square, kept;
* the sea, by ``sea_mask``'s rule over the window grown by its reach;
* the sea *decision* the clamp makes, read off the 3 arcsecond DEM as the
  preview reads it off the last build. That one is global and cannot be
  computed for a window.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from . import NODATA, isofill_lib
from .local import Box
from .params import Params
from .preview import Band, Contours, clamp_patch

# how far the solve reaches beyond the view, in radii; see above
MARGIN = 2.5

# the side of a tile, in cells: what is kept, and what a view is answered in.
# A z15 screen is about 250 by 140 cells at the latitudes drawn so far, and a
# view is answered in whole tiles, so the tile is overhead: on the densest
# z15 view of gobras City, 1.88 s from the view settling at 128 and 1.46 s at
# 64, with the machine's yardstick the same, and 1.30 s at 32
TILE = 64

# the smallest view solved, in cells each way: a smaller one is solved as this
# much ground around it. Zoomed in, a screen is a few dozen cells - 60 by 35 at
# z17, 8 by 4 at z20 - and solved as itself it would be the shape the margin
# fails on. Views 64 cells wide near the golden square's western edge were up
# to 90 m out in 4 of 44 places at 160, and in none at 192 - too near failing
# to trust - nor at 256, 384 or 512
SMALLEST = 256

# how many cells of tiles are kept, first passes and DEMs together - a DEM tile
# counts twice, holding its fill as well. 24 M cells is about 290 MB, and a
# whole 3x3 working set at 1 arcsecond is 78 M
BUDGET = 24_000_000


@dataclass(frozen=True)
class Grid:
    """A grid registered as the build registers it - cell centres on whole
    multiples of the spacing from a whole degree - by its geotransform and
    size. The 1 and 3 arcsecond grids of one working set share the west and
    north degree lines, so a fine cell's centre is a coarse cell's index times
    the ratio, exactly."""

    gt: tuple
    rows: int
    cols: int

    @classmethod
    def of(cls, grid) -> 'Grid':
        """From ``build.Grid``."""
        w, _, _, n = grid.te
        cols, rows = grid.size
        return cls((w, grid.res, 0.0, n, 0.0, -grid.res), rows, cols)

    @property
    def shape(self) -> tuple[int, int]:
        return self.rows, self.cols


@dataclass
class Prepared:
    """What one solve reads, as arrays - the seam between the thread that owns
    the contour layer and the one that solves."""

    view: Box                 # the cells answered
    good: Box                 # the view grown by the margin: what the second pass solves
    outer: Box                # and by the radius again: what the first pass may read
    constraints: np.ndarray   # over outer
    mask: np.ndarray          # over outer
    first: np.ndarray         # over good: the first pass, where it is already known
    todo: np.ndarray          # over good: where it is not, and is to be searched
    water: np.ndarray | None  # over good
    rim: np.ndarray           # over good, the 3 arcsecond surface brought up
    sea: np.ndarray           # over good, where the 3 arcsecond DEM is zero


@dataclass
class Solved:
    dem: np.ndarray           # over the view
    surface: np.ndarray       # over the view: the fill before the clamp
    first: np.ndarray         # over good: the first pass, complete
    around: np.ndarray | None = None   # over good: the DEM, for shading the view with a halo


class Fine:
    """The 1 arcsecond view of a working set built at 3."""

    def __init__(self, fine: Grid, coarse: Grid, contours: Contours,
                 surface: Band, dem: Band, params: Params, gpkg=None):
        """``fine`` and ``coarse`` are the working set's grids at the two
        spacings; ``surface`` and ``dem`` are the 3 arcsecond build's fill and
        clamped DEM; ``params`` are at 1 arcsecond. ``gpkg`` is the build's
        collected contours, read once for the coastline."""
        ratio = coarse.gt[1] / fine.gt[1]
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError(f'a {coarse.gt[1]} grid over a {fine.gt[1]} one is not a whole ratio')
        # and their first centres the same point, which is what ``up`` reads
        # the coarse cells by: off by one, it would read every one wrong
        for i, d in ((0, 1), (3, 5)):
            off = (coarse.gt[i] + coarse.gt[d] / 2) - (fine.gt[i] + fine.gt[d] / 2)
            if abs(off) > abs(fine.gt[d]) * 1e-6:
                raise ValueError(f'the grids\' first centres are {off / fine.gt[d]:g} fine cells apart')
        self.fine, self.coarse = fine, coarse
        self.ratio = round(ratio)
        self.contours = contours
        self.surface, self.dem = surface, dem
        self.params = params
        # here and not at the top: drawn_mask and sea_mask are GDAL's, and the
        # editor's driver imports this module on a machine that may have none
        self.seeds = None
        if gpkg is not None:
            from . import sea_mask
            self.seeds = sea_mask.coast_seeds(gpkg, fine.gt)
        self._envelopes: dict[tuple[int, int], tuple[int, int, int, int] | None] = {}
        # the tiles kept, ('first' or 'dem', key) -> (value, cells), least
        # recently used first
        self._kept: OrderedDict = OrderedDict()
        self._held = 0
        self.budget = BUDGET
        # counted up whenever what is kept changes, for a caller to tell one
        # set of tiles from the next without asking which
        self.revision = 0

    # ------------------------------------------------------------- inputs

    def _envelope(self, square) -> tuple[int, int, int, int] | None:
        """One degree square's envelope as cells of the fine grid - x0, x1, y0,
        y1, one past the end - from its contours burned at 1 arcsecond."""
        from . import drawn_mask
        lat, lon, x0, x1, y0, y1 = square
        if (lat, lon) not in self._envelopes:
            a = self.contours.burn(self.fine.gt, Box(x0, y0, x1 - 1, y1 - 1), NODATA, spots=False)
            env = drawn_mask.envelope(a, NODATA)
            self._envelopes[lat, lon] = (None if env is None else
                                         (x0 + env[2], x0 + env[3], y0 + env[0], y0 + env[1]))
        return self._envelopes[lat, lon]

    def mask(self, box: Box) -> np.ndarray:
        """The drawn area over ``box``."""
        from . import drawn_mask
        out = np.zeros(box.shape, np.uint8)
        for square in drawn_mask.squares(self.fine.gt, self.fine.cols, self.fine.rows):
            _, _, x0, x1, y0, y1 = square
            if x1 <= box.x0 or x0 > box.x1 or y1 <= box.y0 or y0 > box.y1:
                continue
            env = self._envelope(square)
            if env is None:
                continue
            ex0, ex1 = max(env[0], box.x0), min(env[1], box.x1 + 1)
            ey0, ey1 = max(env[2], box.y0), min(env[3], box.y1 + 1)
            if ex1 > ex0 and ey1 > ey0:
                out[ey0 - box.y0:ey1 - box.y0, ex0 - box.x0:ex1 - box.x0] = 1
        return out

    def water(self, box: Box) -> np.ndarray | None:
        """The sea over ``box``, or None where the working set has no coastline."""
        if self.seeds is None:
            return None
        from . import sea_mask
        rows, cols = box.shape
        return sea_mask.sea_window(*self.seeds, box.x0, box.y0, cols, rows, self.fine.shape)

    def up(self, band: Band, box: Box, nearest: bool = False) -> np.ndarray:
        """A coarse band over the fine ``box``: bilinear, or the nearest cell."""
        k, (crows, ccols) = self.ratio, self.coarse.shape
        ys = np.arange(box.y0, box.y1 + 1) / k
        xs = np.arange(box.x0, box.x1 + 1) / k
        if nearest:
            iy = np.minimum(np.rint(ys).astype(int), crows - 1)
            ix = np.minimum(np.rint(xs).astype(int), ccols - 1)
            r0, c0 = iy.min(), ix.min()
            a = band.read(Box(c0, r0, ix.max(), iy.max()))
            return a[np.ix_(iy - r0, ix - c0)]
        y0 = np.minimum(np.floor(ys).astype(int), crows - 1)
        x0 = np.minimum(np.floor(xs).astype(int), ccols - 1)
        y1, x1 = np.minimum(y0 + 1, crows - 1), np.minimum(x0 + 1, ccols - 1)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        r0, c0 = y0.min(), x0.min()
        a = band.read(Box(c0, r0, x1.max(), y1.max())).astype(np.float64)
        y0, y1, x0, x1 = y0 - r0, y1 - r0, x0 - c0, x1 - c0
        top = a[np.ix_(y0, x0)] * (1 - fx) + a[np.ix_(y0, x1)] * fx
        bottom = a[np.ix_(y1, x0)] * (1 - fx) + a[np.ix_(y1, x1)] * fx
        return (top * (1 - fy) + bottom * fy).astype(np.float32)

    def margin(self) -> int:
        return round(MARGIN * self.params.fill_cells)

    # -------------------------------------------------------------- tiles

    def tile(self, key: tuple[int, int]) -> Box:
        """Tile ``key``, (row, column) of tiles, as cells - clipped at the
        grid's south and east edges."""
        ty, tx = key
        return Box(tx * TILE, ty * TILE, min((tx + 1) * TILE, self.fine.cols) - 1,
                   min((ty + 1) * TILE, self.fine.rows) - 1)

    def tiles(self, box: Box) -> list[tuple[int, int]]:
        """Every tile ``box`` touches."""
        return [(ty, tx) for ty in range(box.y0 // TILE, box.y1 // TILE + 1)
                for tx in range(box.x0 // TILE, box.x1 // TILE + 1)]

    def cells(self, west: float, south: float, east: float, north: float) -> Box | None:
        """A lon/lat box as the cells it covers, clipped to the grid; None
        when it misses it."""
        gt = self.fine.gt
        x0, x1 = int((west - gt[0]) // gt[1]), int((east - gt[0]) // gt[1])
        y0, y1 = int((north - gt[3]) // gt[5]), int((south - gt[3]) // gt[5])
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, self.fine.cols - 1), min(y1, self.fine.rows - 1)
        if x1 < x0 or y1 < y0:
            return None
        return Box(x0, y0, x1, y1)

    def _get(self, kind: str, key):
        """A kept tile, now the most recently used; None if not kept."""
        got = self._kept.get((kind, key))
        if got is None:
            return None
        self._kept.move_to_end((kind, key))
        return got[0]

    def _put(self, kind: str, key, value, cells: int) -> None:
        """Keep a tile, letting the least recently used go past the budget."""
        old = self._kept.pop((kind, key), None)
        if old is not None:
            self._held -= old[1]
        self._kept[kind, key] = (value, cells)
        self._held += cells
        self.revision += 1
        while self._held > self.budget and len(self._kept) > 1:
            _, (_, c) = self._kept.popitem(last=False)
            self._held -= c

    def piece(self, key):
        """Tile ``key``'s shading on the Mercator grid, or None when it is not
        solved or was solved without one."""
        got = self._kept.get(('dem', key))
        return got[0][2] if got is not None else None

    def pieces_kept(self) -> list:
        """Every tile's shading kept, as (key, piece)."""
        return [(k, v[0][2]) for (kind, k), v in self._kept.items()
                if kind == 'dem' and v[0][2] is not None]

    def fine_box(self, box: Box) -> Box:
        """A box of the 3 arcsecond grid as the 1 arcsecond cells it covers:
        a coarse cell's centre is a fine cell's, and it reaches a fine cell
        either side."""
        k = self.ratio
        h = k // 2
        return Box(max(box.x0 * k - h, 0), max(box.y0 * k - h, 0),
                   min(box.x1 * k + h, self.fine.cols - 1), min(box.y1 * k + h, self.fine.rows - 1))

    def drop(self, coarse: Box) -> list[tuple[int, int]]:
        """An edit re-solved ``coarse`` on the 3 arcsecond surface - the
        preview's box, the edit grown by its cover - so what the 1 arcsecond
        tiles made of it is out of date: the first pass of every tile in it,
        which reaches a radius and the box is that far round the edit at
        least, and the DEM of every tile within a radius more, which the
        second pass carries further. Everything else is kept (I4). Returns
        the DEM tiles dropped."""
        box = self.fine_box(coarse)
        dem_box = box.grown(self.params.fill_cells, self.fine.shape)
        dropped = []
        for kind, area in (('first', box), ('dem', dem_box)):
            for k in self.tiles(area):
                got = self._kept.pop((kind, k), None)
                if got is not None:
                    self._held -= got[1]
                    if kind == 'dem':
                        dropped.append(k)
        self.revision += 1
        return dropped

    def clear(self) -> None:
        """Every tile gone - what an edit the preview could not show does,
        and the drawn area with them: such an edit can have moved it."""
        self._kept.clear()
        self._held = 0
        self._envelopes.clear()
        self.revision += 1

    def rehold(self, contours: Contours, surface: Band, dem: Band, gpkg=None) -> bool:
        """Hold the tiles on a new build of the same grid and drawn area -
        an idle rebuild's - rather than solve them again (I5). That it is the
        same grid and drawn area is the caller's to have checked, as
        ``FineDriver.adopt`` does; this does not look. They are still
        its answer: the first pass depends on the contours alone, and the
        tiles an edit reached went when it was previewed; the DEM was held on
        a preview's surface within a millimetre of the exact one. The drawn
        area is taken from the contours again, and the sea; if the sea moved,
        every tile goes. Returns whether the tiles were kept."""
        self.contours, self.surface, self.dem = contours, surface, dem
        self._envelopes.clear()
        seeds = None
        if gpkg is not None:
            from . import sea_mask
            seeds = sea_mask.coast_seeds(gpkg, self.fine.gt)
        same = (seeds is None) == (self.seeds is None) and (
            seeds is None or all(np.array_equal(a, b) for a, b in zip(seeds, self.seeds, strict=True)))
        self.seeds = seeds
        if not same:
            self.clear()
        return same

    def known(self, view: Box) -> bool:
        """Whether every tile of ``view`` is solved."""
        return all(('dem', k) in self._kept for k in self.tiles(view))

    def read(self, view: Box) -> tuple[np.ndarray, np.ndarray] | None:
        """The DEM and fill over ``view`` from the tiles, or None if a tile of
        it is not solved."""
        if not self.known(view):
            return None
        dem = np.empty(view.shape, np.float32)
        surface = np.empty(view.shape, np.float32)
        for k in self.tiles(view):
            d, f, _ = self._get('dem', k)
            t = self.tile(k)
            a = Box(max(t.x0, view.x0), max(t.y0, view.y0), min(t.x1, view.x1), min(t.y1, view.y1))
            src = (slice(a.y0 - t.y0, a.y1 - t.y0 + 1), slice(a.x0 - t.x0, a.x1 - t.x0 + 1))
            dst = (slice(a.y0 - view.y0, a.y1 - view.y0 + 1), slice(a.x0 - view.x0, a.x1 - view.x0 + 1))
            dem[dst], surface[dst] = d[src], f[src]
        return dem, surface

    def plan(self, view: Box) -> Prepared | None:
        """The solve that would answer the tiles of ``view``, or None when
        they are all solved already. Touches the contour layer, so it belongs
        to the thread that edits it; ``solve`` is the rest.

        The whole view, in whole tiles, whenever any of it is missing - not
        the missing tiles alone - and never less than SMALLEST each way. A pan
        leaves a strip of new tiles, and a strip solved on a rim of its own is
        the shape the margin was never measured for: every cell of it is near
        the rim on three sides, and walked across the golden square at 64-cell
        tiles that came out 140 m from the whole build where solving the view
        did not move by a centimetre. Solving the view costs a second pass
        over it, a few hundredths of a second; the first pass, which is the
        cost, comes from the tiles already searched wherever it can - it
        depends on the contours alone, so a tile searched for one view is the
        answer for every view after it - and only the new ground is searched."""
        if all(('dem', k) in self._kept for k in self.tiles(view)):
            return None
        boxes = [self.tile(k) for k in self.tiles(at_least(view, SMALLEST, self.fine.shape))]
        answer = Box(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                     max(b.x1 for b in boxes), max(b.y1 for b in boxes))
        return self.prepared(answer)

    def prepared(self, view: Box) -> Prepared:
        """Everything the solve for ``view`` reads."""
        shape = self.fine.shape
        good = view.grown(self.margin(), shape)
        outer = good.grown(self.params.fill_cells, shape)
        cons = self.contours.burn(self.fine.gt, outer, NODATA).astype(np.float32)
        first = np.zeros(good.shape, np.float32)
        todo = np.ones(good.shape, bool)
        for k in self.tiles(good):
            a = self._get('first', k)
            if a is None:
                continue
            t = self.tile(k)
            c = Box(max(t.x0, good.x0), max(t.y0, good.y0), min(t.x1, good.x1), min(t.y1, good.y1))
            dst = (slice(c.y0 - good.y0, c.y1 - good.y0 + 1), slice(c.x0 - good.x0, c.x1 - good.x0 + 1))
            first[dst] = a[c.y0 - t.y0:c.y1 - t.y0 + 1, c.x0 - t.x0:c.x1 - t.x0 + 1]
            todo[dst] = False
        return Prepared(view, good, outer, cons, self.mask(outer), first, todo,
                        self.water(good), self.up(self.surface, good),
                        self.up(self.dem, good, nearest=True) == 0)

    def take(self, p: Prepared, solved: Solved, shaded: dict | None = None) -> list[tuple[int, int]]:
        """Keep what a solve found: the DEM of every tile of its view, with
        its piece of the shading if there is one, and the first pass of every
        tile it searched whole. Returns the DEM's tiles."""
        good = p.good
        for k in self.tiles(good):
            t = self.tile(k)
            if ('first', k) in self._kept or not (t.x0 >= good.x0 and t.y0 >= good.y0
                                         and t.x1 <= good.x1 and t.y1 <= good.y1):
                continue
            a = solved.first[t.y0 - good.y0:t.y1 - good.y0 + 1, t.x0 - good.x0:t.x1 - good.x0 + 1]
            self._put('first', k, a.copy(), t.cells)
        keys = self.tiles(p.view)
        v = p.view
        for k in keys:
            t = self.tile(k)
            src = (slice(t.y0 - v.y0, t.y1 - v.y0 + 1), slice(t.x0 - v.x0, t.x1 - v.x0 + 1))
            piece = shaded.get(k) if shaded else None
            self._put('dem', k, (solved.dem[src].copy(), solved.surface[src].copy(), piece),
                      2 * t.cells + (piece.dem.size + piece.shade.size // 4 if piece is not None else 0))
        return keys

    def view(self, view: Box, lib=None) -> tuple[np.ndarray, np.ndarray]:
        """The DEM and fill over ``view``, solving what is not yet solved -
        in one go, on this thread."""
        p = self.plan(view)
        if p is not None:
            self.take(p, solve(p, self.fine.shape, self.params, lib))
        return self.read(view)


def at_least(box: Box, side: int, shape: tuple[int, int]) -> Box:
    """``box`` grown about its middle to ``side`` cells each way where it is
    smaller, and kept inside the raster."""
    rows, cols = shape

    def span(a, b, n):
        if b - a + 1 >= min(side, n):
            return a, b
        a = max(0, (a + b) // 2 - side // 2)
        b = min(n - 1, a + side - 1)
        return max(0, b - side + 1), b
    x0, x1 = span(box.x0, box.x1, cols)
    y0, y1 = span(box.y0, box.y1, rows)
    return Box(x0, y0, x1, y1)


def solve(p: Prepared, shape: tuple[int, int], params: Params, lib=None) -> Solved:
    """The solve, apart from the object, so a worker needs only arrays."""
    lib = lib or isofill_lib.Isofill.load()
    good, outer = p.good, p.outer
    inner = (slice(good.y0 - outer.y0, good.y1 - outer.y0 + 1),
             slice(good.x0 - outer.x0, good.x1 - outer.x0 + 1))
    first = p.first.copy()
    if p.todo.any():
        # searched only where it is not already known. The box read is that
        # ground grown by the radius, so every cell searched sees every
        # contour the whole raster's search would; the rest of it is outside
        # the mask, read for its contours and not searched from
        ys, xs = np.nonzero(p.todo)
        searched = Box(good.x0 + int(xs.min()), good.y0 + int(ys.min()),
                       good.x0 + int(xs.max()), good.y0 + int(ys.max()))
        read = searched.grown(params.fill_cells, shape)
        at = (slice(read.y0 - outer.y0, read.y1 - outer.y0 + 1),
              slice(read.x0 - outer.x0, read.x1 - outer.x0 + 1))
        todo = np.zeros(outer.shape, bool)
        todo[inner] = p.todo
        search = np.where(todo[at], p.mask[at], 0).astype(np.uint8)
        found, _ = lib.run(np.ascontiguousarray(p.constraints[at]), params, mask=search,
                           nodata=NODATA, pass2=False)
        # read covers good wherever there is todo, but not necessarily all of
        # it: put the found values back where todo is, through the overlap
        oy0, oy1 = max(good.y0, read.y0), min(good.y1, read.y1)
        ox0, ox1 = max(good.x0, read.x0), min(good.x1, read.x1)
        dst = (slice(oy0 - good.y0, oy1 - good.y0 + 1), slice(ox0 - good.x0, ox1 - good.x0 + 1))
        src = (slice(oy0 - read.y0, oy1 - read.y0 + 1), slice(ox0 - read.x0, ox1 - read.x0 + 1))
        first[dst] = np.where(p.todo[dst], found[src], first[dst])
    complete = first.copy()
    mask = np.ascontiguousarray(p.mask[inner])
    water = p.water
    # the rim at the coarse surface, on the sides with ground beyond them -
    # local.resolve_window's rule, for its reason
    rows, cols = shape
    if good.y0 > 0:
        first[0, :] = p.rim[0, :]
    if good.y1 < rows - 1:
        first[-1, :] = p.rim[-1, :]
    if good.x0 > 0:
        first[:, 0] = p.rim[:, 0]
    if good.x1 < cols - 1:
        first[:, -1] = p.rim[:, -1]
    surface = lib.diffuse(first, mask=mask, water=water)
    cons = p.constraints[inner]
    # the clamp's sea is a global decision, read off the coarse DEM - but only
    # for a cell the clamp would have offered it: one the fill left under half
    # a metre and nothing burned. Read off the coarse DEM alone, a cell at the
    # edge of the drawn area whose nearest coarse cell was sea went to zero
    # from 726 m. Offered first, a wrong decision costs the metre between sea
    # and the lowest land, and no more. The water mask is sea whatever reaches
    # it, as in the whole clamp
    sea = p.sea & (np.abs(surface) < 0.5) & (cons == NODATA)
    if water is not None:
        sea |= water != 0
    dem = clamp_patch(surface, cons, np.where(sea, 0, 1))
    view = (slice(p.view.y0 - good.y0, p.view.y1 - good.y0 + 1),
            slice(p.view.x0 - good.x0, p.view.x1 - good.x0 + 1))
    return Solved(dem[view], surface[view], complete, dem)


def pieces(p: Prepared, solved: Solved, gt: tuple, projection: str,
           params: Params) -> dict:
    """The view shaded, as Mercator pieces a tile each: ``shade.Shaded``
    by tile key.

    Shaded once for the whole view and cut up after, so there is no seam
    between two tiles of one solve: the box filter, the hillshade and the warp
    all read their neighbours, and a tile shaded alone would have its edges
    computed against nothing. The view is grown by a halo first, from the DEM
    the solve found beyond it, and the halo's own cells are never kept - as
    the preview's patch is cropped. On one Mercator grid wherever the view is,
    so pieces of two solves meet on whole cells.

    A Mercator cell goes to the tile its centre lies in, so neighbouring
    pieces neither overlap nor leave a gap."""
    from . import shade
    good, view = p.good, p.view
    halo = params.smooth_cells + 4
    win = Box(max(view.x0 - halo, good.x0), max(view.y0 - halo, good.y0),
              min(view.x1 + halo, good.x1), min(view.y1 + halo, good.y1))
    dem = solved.around[win.y0 - good.y0:win.y1 - good.y0 + 1, win.x0 - good.x0:win.x1 - good.x0 + 1]
    sub = (gt[0] + win.x0 * gt[1], gt[1], 0.0, gt[3] + win.y0 * gt[5], 0.0, gt[5])
    metres = shade.fine_metres(params)
    grid = (-shade.HALF, metres, 0.0, shade.HALF, 0.0, -metres)
    m_dem, m_shade, m_gt, _ = shade.shade_window(dem, sub, projection, params, align_to=grid)
    rows, cols = m_dem.shape
    # each Mercator cell's centre, as lon and lat
    lon = np.degrees((m_gt[0] + (np.arange(cols) + 0.5) * m_gt[1]) / shade.R)
    my = m_gt[3] + (np.arange(rows) + 0.5) * m_gt[5]
    lat = np.degrees(2 * np.arctan(np.exp(my / shade.R)) - np.pi / 2)
    out = {}
    for ty in range(view.y0 // TILE, view.y1 // TILE + 1):
        for tx in range(view.x0 // TILE, view.x1 // TILE + 1):
            tile = Box(tx * TILE, ty * TILE, min(view.x1, (tx + 1) * TILE - 1),
                       min(view.y1, (ty + 1) * TILE - 1))
            # the tile's own edges, which are cell edges of the 1" grid
            west, east = gt[0] + tile.x0 * gt[1], gt[0] + (tile.x1 + 1) * gt[1]
            north, south = gt[3] + tile.y0 * gt[5], gt[3] + (tile.y1 + 1) * gt[5]
            cs = np.flatnonzero((lon >= west) & (lon < east))
            rs = np.flatnonzero((lat <= north) & (lat > south))
            if not len(cs) or not len(rs):
                continue
            r0, r1, c0, c1 = rs[0], rs[-1] + 1, cs[0], cs[-1] + 1
            out[ty, tx] = shade.Shaded(
                dem=np.ascontiguousarray(m_dem[r0:r1, c0:c1]),
                shade=np.ascontiguousarray(m_shade[r0:r1, c0:c1]),
                geotransform=(m_gt[0] + c0 * m_gt[1], m_gt[1], 0.0, m_gt[3] + r0 * m_gt[5], 0.0, m_gt[5]),
                metres=metres)
    return out



def mosaic(pieces) -> 'tuple | None':
    """Tiles' shading pasted onto the one grid they are all on: a
    ``shade.Shaded`` over the box they span, and which of its cells a piece
    covers. None for no pieces. What the layer draws and what the readings
    read are the one array."""
    from . import shade
    pieces = list(pieces)
    if not pieces:
        return None
    metres = pieces[0].metres
    # whole cells of the one grid, counted from the Mercator origin
    at = [(round((p.geotransform[0] + shade.HALF) / metres),
           round((shade.HALF - p.geotransform[3]) / metres), p) for p in pieces]
    c0 = min(c for c, _, _ in at)
    r0 = min(r for _, r, _ in at)
    c1 = max(c + p.dem.shape[1] for c, _, p in at)
    r1 = max(r + p.dem.shape[0] for _, r, p in at)
    dem = np.zeros((r1 - r0, c1 - c0), np.float32)
    hill = np.zeros((r1 - r0, c1 - c0), np.uint8)
    covered = np.zeros((r1 - r0, c1 - c0), bool)
    for c, r, p in at:
        rows, cols = p.dem.shape
        dem[r - r0:r - r0 + rows, c - c0:c - c0 + cols] = p.dem
        hill[r - r0:r - r0 + rows, c - c0:c - c0 + cols] = p.shade
        covered[r - r0:r - r0 + rows, c - c0:c - c0 + cols] = True
    return shade.Shaded(dem=dem, shade=hill, metres=metres,
                        geotransform=(c0 * metres - shade.HALF, metres, 0.0,
                                      shade.HALF - r0 * metres, 0.0, -metres)), covered
