"""Re-solving a box around an edit, instead of the whole working set.

Phase 4's preview rests on a claim the spec makes and this module is where it
is cashed: a cell's first-pass value depends only on contours within ``radius``,
so recomputing a box grown by that margin gives every cell inside the box the
value a whole-raster run would give it - exactly. The second pass has no such
property. Laplace diffusion is global, and a box solved against a rim held at
the last whole-raster answer is an approximation.

How good an approximation is a question about the data, not about the code, and
``tests/golden/test_local_solve.py`` answers it by doing both and comparing.
What makes it a *good* one is that the second pass only moves cells the first
pass declined, and every answered cell is fixed: diffusion cannot cross a ring
of answered ground, so a change is confined to the region of unanswered cells
it lands in. On the gobras working set 99% of those regions are under 105 cells
across.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import isofill_lib
from .params import Params


@dataclass(frozen=True)
class Box:
    """A rectangle of cells, inclusive at both ends."""

    x0: int
    y0: int
    x1: int
    y1: int

    @classmethod
    def around(cls, ys, xs) -> 'Box':
        """The box containing every given cell."""
        return cls(int(np.min(xs)), int(np.min(ys)), int(np.max(xs)), int(np.max(ys)))

    def grown(self, by: int, shape: tuple[int, int]) -> 'Box':
        """Grown by ``by`` cells and clipped to a raster of ``shape``."""
        rows, cols = shape
        return Box(max(0, self.x0 - by), max(0, self.y0 - by),
                   min(cols - 1, self.x1 + by), min(rows - 1, self.y1 + by))

    @property
    def slice(self) -> tuple[slice, slice]:
        return slice(self.y0, self.y1 + 1), slice(self.x0, self.x1 + 1)

    @property
    def shape(self) -> tuple[int, int]:
        return self.y1 - self.y0 + 1, self.x1 - self.x0 + 1

    @property
    def cells(self) -> int:
        return self.shape[0] * self.shape[1]

    def touches_edge(self, shape: tuple[int, int]) -> bool:
        rows, cols = shape
        return self.x0 == 0 or self.y0 == 0 or self.x1 == cols - 1 or self.y1 == rows - 1


def reach(params: Params, slack: int) -> int:
    """The clearance between the patch and the edge of the solve: the fill's
    radius, so the first pass inside the patch sees every contour a
    whole-raster run would, plus whatever slack the second pass is being given
    on top of it.

    These are two different needs and conflating them is a mistake I made and
    had to measure my way out of. The first pass wants exactly a radius and no
    more - beyond that it cannot see. The second is diffusion, which has no
    radius: what it wants is distance between the ground being answered and the
    rim the answer is held against."""
    return params.fill_cells + slack


def resolve(constraints: np.ndarray, mask: np.ndarray, water: np.ndarray | None,
            previous: np.ndarray, box: Box, params: Params, cover: int | None = None,
            slack: int | None = None, nodata: float | None = None,
            lib=None) -> tuple[np.ndarray, Box]:
    """The re-solved patch, and the box it is good for.

    ``constraints``, ``mask`` and ``water`` are the whole raster as it is after
    the edit; ``previous`` is the surface before it. What comes back is a patch
    and where it goes - a caller wanting a whole raster writes it in itself,
    which is two lines and its own decision. Returning ``previous`` with the
    patch written into it would copy the whole surface on every call, 311 MB at
    1 arcsecond, which is most of what solving a box was meant to avoid.

    ``cover`` is how far beyond the edited box the patch reaches, and ``slack``
    is how much clearance the solve keeps beyond that, on top of the radius.
    They answer different questions and conflating them was a mistake worth
    recording, since one number moved both and so never changed the clearance
    at all.

    ``cover`` is about what goes stale. An edit moves ground beyond the box it
    was drawn in - the first pass reaches a radius, the second carries further
    inside whatever region of unanswered cells the edit lands in - and whatever
    the patch does not cover keeps showing the surface from before. Two radii
    is what that took: on the golden square a whole contour level deleted left
    115.794 m behind at no cover, 42.392 m at one radius and nothing at two,
    and over eighteen edits on the gobras 3x3 nothing moved beyond two radii at
    all.

    ``slack`` is about what the patch gets wrong, which is the held rim. Two
    radii again, for a different reason: over the same eighteen edits it takes
    the worst from 3.278 m to 0.268 m, and no amount beyond that helps.

    What is left at that point is not the rim. It is entirely cells the first
    pass declined - 224 of them on the worst case looked at, every one classed
    "one level only" - where the second pass invents a value by diffusing
    across a region of unanswered ground. That region runs past any box worth
    solving, so the patch solves a truncated version of it and lands a little
    differently. It is the irreducible part of being local: a quarter of a
    metre against a 25 m contour interval, invisible in a hillshade, and the
    exact rebuild on idle is what removes it.
    """
    lib = lib or isofill_lib.Isofill.load()
    if cover is None:
        cover = 2 * params.fill_cells
    if slack is None:
        slack = 2 * params.fill_cells
    good = box.grown(cover, constraints.shape)
    grown = good.grown(reach(params, slack), constraints.shape)
    sl = grown.slice
    cons = np.ascontiguousarray(constraints[sl], dtype=np.float32)
    sub_mask = np.ascontiguousarray(mask[sl], dtype=np.uint8)
    sub_water = np.ascontiguousarray(water[sl], dtype=np.uint8) if water is not None else None

    # pass 1 over the grown box. Exact for every cell more than radius inside
    # it, which is every cell of the edited box
    first, _ = lib.run(cons, params, mask=sub_mask, water=sub_water,
                       nodata=nodata, pass2=False)

    # The rim, from the answer the last whole-raster solve gave - but only on
    # the sides that have ground beyond them. Where the box runs into the
    # raster's own edge there is nothing outside to hold it at, and writing the
    # old surface there pins the edge at whatever it said before the edit: the
    # whole-raster solve treats that edge as an edge, anchoring at zero and
    # flooding an unreachable region from it, and a box that holds it instead
    # is answering a different question. On the golden square, whose contours
    # run to the western edge, holding all four sides put a cell 82.656 m out
    # and no amount of margin moved it, because the margin never reaches an
    # edge that is already there.
    rows, cols = constraints.shape
    prev = previous[sl]
    if grown.y0 > 0:
        first[0, :] = prev[0, :]
    if grown.y1 < rows - 1:
        first[-1, :] = prev[-1, :]
    if grown.x0 > 0:
        first[:, 0] = prev[:, 0]
    if grown.x1 < cols - 1:
        first[:, -1] = prev[:, -1]

    solved = lib.diffuse(first, mask=sub_mask, water=sub_water)
    # crop the scaffolding: only the ground a radius inside the solve is the
    # answer a whole-raster run would have given
    return solved[good.y0 - grown.y0:good.y1 - grown.y0 + 1,
                  good.x0 - grown.x0:good.x1 - grown.x0 + 1], good
