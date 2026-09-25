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


def reach(params: Params, margin: int) -> int:
    """How far out of the edited box the solve has to go: the fill's radius, so
    the first pass inside the box sees every contour a whole-raster run would,
    plus whatever margin is being given to the second."""
    return params.fill_cells + margin


def resolve(constraints: np.ndarray, mask: np.ndarray, water: np.ndarray | None,
            previous: np.ndarray, box: Box, params: Params, margin: int = 0,
            nodata: float | None = None, lib=None) -> tuple[np.ndarray, Box]:
    """The surface with ``box`` re-solved, and the box that was actually solved.

    ``constraints``, ``mask`` and ``water`` are the whole raster as it is after
    the edit; ``previous`` is the surface before it. The returned array is
    ``previous`` with the solved box written into it.

    The rim of the solved box is written from ``previous`` before the second
    pass runs, which is the whole of the boundary condition: isofill does not
    move a cell carrying anything but a sentinel.
    """
    lib = lib or isofill_lib.Isofill.load()
    grown = box.grown(reach(params, margin), constraints.shape)
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
    out = previous.copy()
    out[sl] = solved
    return out, grown
