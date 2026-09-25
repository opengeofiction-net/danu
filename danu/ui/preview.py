"""An edit to a repainted patch - R19's first half.

*While drawing, the surface updates locally and immediately. On idle it is
rebuilt exactly. The two states are distinguishable at a glance.*

This is the wiring. The parts it joins were each measured on their own before
being put together, and the budget is the phase's own fifty milliseconds:

    burn the constraints for the box      2.3 - 5.2 ms
    solve it against the held rim        10   - 18   ms
    clamp it                             numpy, on the box
    smooth, warp and hillshade it        14.4 - 19.8 ms
                                         ---------------
                                         27   - 43   ms

Two timers. A short one coalesces the edits of a single gesture - drawing a
contour is one edit per node, and previewing each would spend the budget many
times over for frames nobody sees. A long one asks for the exact rebuild once
the drawing stops, through the queue F4 built, which is where the preview's
approximations are settled: the rim, the eleven cells of the sea decision, and
a newly drawn contour's side of a tie.

What the preview is *not* is a different surface. It is the same isofill, the
same clamp arithmetic, the same box filter and hillshade, over a box instead of
a raster. Where it differs from the rebuild it differs by the approximations
above and by nothing else, and each of those is measured in
``tests/golden/test_preview.py``.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from ..surface import local, preview, shade
from ..surface.params import Params

# One gesture's worth of edits, coalesced. A contour is drawn a node at a time
# and each is an edit; at 30 ms a fast hand's run of them becomes one preview
# and the frame is still inside a fifth of a second.
GESTURE_MS = 30

# How long the drawing has to stop before the exact rebuild is asked for.
IDLE_MS = 1500


class PreviewDriver(QObject):
    """Turns edits into patched surface, and silence into an exact rebuild."""

    patched = Signal(object, float)     # the Box repainted, and how long it took
    exact_wanted = Signal()
    unavailable = Signal(str)           # why there is no preview, once per reason

    def __init__(self, parent=None, gesture_ms: int = GESTURE_MS, idle_ms: int = IDLE_MS):
        super().__init__(parent)
        self._kept: preview.Kept | None = None
        self._shaded: shade.Shaded | None = None
        self._params: Params | None = None
        self._projection = ''
        self._pending: list = []        # boxes of ways edited since the last preview
        self._drawn: dict = {}          # each way's geometry as last burned
        self._said = ''
        self._gesture = QTimer(self)
        self._gesture.setSingleShot(True)
        self._gesture.setInterval(gesture_ms)
        self._gesture.timeout.connect(self._run)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(idle_ms)
        self._idle.timeout.connect(self.exact_wanted)

    @property
    def ready(self) -> bool:
        return self._kept is not None

    def forget(self):
        """Drop the rasters - a new working set, or a build that gave none."""
        self._kept, self._shaded, self._params = None, None, None
        self._pending.clear()
        self._drawn.clear()
        self._gesture.stop()
        self._idle.stop()

    def adopt(self, built, params: Params):
        """Take the exact build's grids as the ground the next preview works
        from. Called on every build, so the approximations do not compound:
        each preview starts from an answer, not from another preview."""
        if built.rasters is None:
            self.forget()
            self._say(f'no live preview at {params.arcsec:g}" - the grids it works '
                      f'from are gigabytes here; edits rebuild instead')
            return
        r = built.rasters
        try:
            contours = preview.Contours(r.gpkg)
        except OSError as e:
            self.forget()
            self._say(str(e))
            return
        self._kept = preview.Kept(constraints=r.constraints, mask=r.mask, water=r.water,
                                  surface=r.surface, geotransform=r.geotransform,
                                  nodata=r.nodata, contours=contours, dem=r.dem)
        self._shaded = built.shaded
        self._params = params
        # the layer is the build's again, so what it holds for each way is the
        # build's geometry and not the last preview's
        self._drawn.clear()
        self._projection = r.projection
        self._said = ''

    def _say(self, why: str):
        if why != self._said:
            self._said = why
            self.unavailable.emit(why)

    # ------------------------------------------------------------- edits

    def edited(self, square, way_ids):
        """One editor command's worth of change: the ids of the ways it
        touched, in the square it touched them in.

        Ids, not ways: ``Command.ways()`` returns ``set[int]``, and it is asked
        before apply and after undo alike, so a way it names may not be in the
        square at all. That is how a deletion arrives.
        """
        self._idle.start()
        if not self.ready:
            return
        for wid in way_ids:
            way = square.ways.get(wid)
            points = ([(square.nodes[r].lon, square.nodes[r].lat)
                       for r in way.refs if r in square.nodes] if way is not None else [])
            ele = getattr(way, 'ele', None) if way is not None else None
            if ele is not None and len(points) > 1:
                self._mark(wid, points)
                self._kept.contours.apply(wid, points, ele)
                self._drawn[wid] = points
            else:
                # gone from the square, or no longer a contour: either way it
                # stops constraining the surface, and the ground it used to
                # cover has to be resolved
                self._mark(wid, self._drawn.pop(wid, points))
                self._kept.contours.remove(wid)
        if self._pending:
            self._gesture.start()

    def _mark(self, wid, points):
        """Box the part of a way whose burn actually changed.

        Not the whole way. Moving one node of a five-hundred-node contour
        changes the surface around that node, and a box around the whole way is
        the whole contour - which is the difference between a patch that solves
        in thirty milliseconds and one that solves in a second. So the previous
        geometry is kept and compared: only the points that moved, with their
        neighbours, since it is the segments either side of a moved node whose
        cells are burned differently.

        A way with no previous geometry - newly drawn, or the first edit after
        a rebuild - is marked whole, because all of it is new.
        """
        gt = self._kept.geotransform
        shape = self._kept.constraints.shape
        before = self._drawn.get(wid)
        changed = points
        if before is not None and points:
            n = max(len(before), len(points))
            at = [i for i in range(n)
                  if i >= len(before) or i >= len(points) or before[i] != points[i]]
            if not at:
                return                       # nothing about this way moved
            near = {i for j in at for i in (j - 1, j, j + 1)}
            changed = [points[i] for i in sorted(near) if 0 <= i < len(points)]
            # the cells the way used to cover there have to be resolved too
            changed += [before[i] for i in sorted(near) if 0 <= i < len(before)]
        box = self._box(changed, gt, shape)
        if box is not None:
            self._pending.append(box)

    @staticmethod
    def _box(points, gt, shape) -> local.Box | None:
        """The cells a way's nodes fall in, clipped to the raster. None when
        the way lies outside it entirely - which is not an error: a working set
        is a window, and a way can be dragged out of it."""
        if not points:
            return None
        rows, cols = shape
        xs = [int((lon - gt[0]) / gt[1]) for lon, _ in points]
        ys = [int((lat - gt[3]) / gt[5]) for _, lat in points]
        if max(xs) < 0 or min(xs) >= cols or max(ys) < 0 or min(ys) >= rows:
            return None
        return local.Box(max(0, min(xs)), max(0, min(ys)),
                         min(cols - 1, max(xs)), min(rows - 1, max(ys)))

    def _run(self):
        """One preview, over everything edited since the last."""
        if not self.ready or not self._pending:
            return
        boxes, self._pending = self._pending, []
        box = local.Box(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                        max(b.x1 for b in boxes), max(b.y1 for b in boxes))
        started = time.perf_counter()
        patch, good = preview.patch(self._kept, box, self._params)
        # the kept surface carries the edit forward, so the next preview holds
        # its rim at what is on screen rather than at a surface two edits old
        self._kept.surface[good.slice] = patch
        self._repaint(good)
        self.patched.emit(good, time.perf_counter() - started)

    def _repaint(self, good: local.Box):
        """The patch through the clamp and the shading, and into the arrays the
        layer draws."""
        kept, p = self._kept, self._params
        gt = kept.geotransform
        shape = kept.constraints.shape
        # a halo, because the box filter and the hillshade both read their
        # neighbours and the warp reads whatever bilinear touches
        win = good.grown(p.smooth_cells + 4, shape)
        clamped = preview.clamp_patch(kept.surface[win.slice], kept.constraints[win.slice],
                                      kept.dem[win.slice])
        kept.dem[win.slice] = clamped
        sub_gt = (gt[0] + win.x0 * gt[1], gt[1], 0.0, gt[3] + win.y0 * gt[5], 0.0, gt[5])
        m_dem, m_shade, m_gt, _metres = shade.shade_window(
            clamped, sub_gt, self._projection, p, align_to=self._shaded.geotransform)
        self._splice(m_dem, m_shade, m_gt)

    def _splice(self, m_dem, m_shade, m_gt):
        """Write the patch into the displayed arrays, at the cell it belongs
        to. ``shade_window`` was told the display's grid, so this is whole
        cells and not a resample."""
        whole = self._shaded
        x = int(round((m_gt[0] - whole.geotransform[0]) / whole.geotransform[1]))
        y = int(round((m_gt[3] - whole.geotransform[3]) / whole.geotransform[5]))
        rows, cols = m_shade.shape
        # clipped, because a window at the raster's own edge warps to a
        # Mercator box that can reach past the display's
        sy0, sx0 = max(0, y), max(0, x)
        sy1 = min(whole.shade.shape[0], y + rows)
        sx1 = min(whole.shade.shape[1], x + cols)
        if sy1 <= sy0 or sx1 <= sx0:
            return
        dy0, dx0 = sy0 - y, sx0 - x
        whole.dem[sy0:sy1, sx0:sx1] = m_dem[dy0:dy0 + sy1 - sy0, dx0:dx0 + sx1 - sx0]
        whole.shade[sy0:sy1, sx0:sx1] = m_shade[dy0:dy0 + sy1 - sy0, dx0:dx0 + sx1 - sx0]
