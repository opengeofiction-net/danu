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

from dataclasses import dataclass

import numpy as np

from . import NODATA, drawn_mask, isofill_lib, sea_mask
from .local import Box
from .params import Params
from .preview import Band, Contours, clamp_patch

# how far the solve reaches beyond the view, in radii; see above
MARGIN = 2.5


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
    """What the solve for one view reads, as arrays - the seam between the
    thread that owns the contour layer and the one that solves."""

    view: Box
    good: Box               # the view grown by the margin: what is solved
    grown: Box              # and by the radius again: what the first pass reads
    constraints: np.ndarray  # over grown
    mask: np.ndarray         # over grown
    water: np.ndarray | None  # over grown
    rim: np.ndarray          # over good, the 3 arcsecond surface brought up
    sea: np.ndarray          # over good, where the 3 arcsecond DEM is zero


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
        self.seeds = sea_mask.coast_seeds(gpkg, fine.gt) if gpkg is not None else None
        self._envelopes: dict[tuple[int, int], tuple[int, int, int, int] | None] = {}

    # ------------------------------------------------------------- inputs

    def _envelope(self, square) -> tuple[int, int, int, int] | None:
        """One degree square's envelope as cells of the fine grid - x0, x1, y0,
        y1, one past the end - from its contours burned at 1 arcsecond."""
        lat, lon, x0, x1, y0, y1 = square
        if (lat, lon) not in self._envelopes:
            a = self.contours.burn(self.fine.gt, Box(x0, y0, x1 - 1, y1 - 1), NODATA, spots=False)
            env = drawn_mask.envelope(a, NODATA)
            self._envelopes[lat, lon] = (None if env is None else
                                         (x0 + env[2], x0 + env[3], y0 + env[0], y0 + env[1]))
        return self._envelopes[lat, lon]

    def mask(self, box: Box) -> np.ndarray:
        """The drawn area over ``box``."""
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

    def prepared(self, view: Box) -> Prepared:
        """Everything the solve for ``view`` reads. Touches the contour layer,
        so it belongs to the thread that edits it; ``solved`` is the rest."""
        shape = self.fine.shape
        good = view.grown(self.margin(), shape)
        grown = good.grown(self.params.fill_cells, shape)
        cons = self.contours.burn(self.fine.gt, grown, NODATA).astype(np.float32)
        return Prepared(view, good, grown, cons, self.mask(grown), self.water(grown),
                        self.up(self.surface, good), self.up(self.dem, good, nearest=True) == 0)

    # -------------------------------------------------------------- solve

    def solved(self, p: Prepared, lib=None) -> tuple[np.ndarray, np.ndarray]:
        """The view's DEM and its fill before the clamp, both over ``p.view``."""
        return solve(p, self.fine.shape, self.params, lib)

    def view(self, view: Box, lib=None) -> tuple[np.ndarray, np.ndarray]:
        return self.solved(self.prepared(view), lib)


def solve(p: Prepared, shape: tuple[int, int], params: Params,
          lib=None) -> tuple[np.ndarray, np.ndarray]:
    """``Fine.solved``, apart from the object, so a worker needs only arrays."""
    lib = lib or isofill_lib.Isofill.load()
    good, grown = p.good, p.grown
    inner = (slice(good.y0 - grown.y0, good.y1 - grown.y0 + 1),
             slice(good.x0 - grown.x0, good.x1 - grown.x0 + 1))
    # the first pass answers the solved box only; the radius beyond it is
    # outside the mask, so it is read for its contours and not searched from
    search = np.zeros_like(p.mask)
    search[inner] = p.mask[inner]
    first, _ = lib.run(p.constraints, params, mask=search, water=p.water,
                       nodata=NODATA, pass2=False)
    first = np.ascontiguousarray(first[inner])
    mask = np.ascontiguousarray(p.mask[inner])
    water = np.ascontiguousarray(p.water[inner]) if p.water is not None else None
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
    return dem[view], surface[view]
