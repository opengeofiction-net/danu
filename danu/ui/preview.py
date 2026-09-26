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

import math
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

# Pieces one gesture may be solved as. Each costs a whole solve on the UI
# thread, so past a handful the preview is worse than not previewing: the
# gesture is skipped and the idle rebuild settles it.
#
# Eight is a "not absurdly many" bound and not a latency one, and the
# difference matters to anyone reading it as a budget: at the measured worst
# case of 64.7 ms a solve, eight of them is 518 ms of frozen editor against a
# 50 ms target. A latency bound would be two or three. It is set here for the
# case that does not arise today - a command names a handful of ways - and the
# latency itself is F5c's, where the margin that makes a solve cost 40 ms is
# the thing being changed.
MAX_PIECES = 8


class PreviewDriver(QObject):
    """Turns edits into patched surface, and silence into an exact rebuild."""

    patched = Signal(object, float)     # the display rects written, and how long it took
    classesStale = Signal(object)       # where R20's overlay stopped describing the surface
    skipped = Signal(int)               # a gesture too broken up to preview; idle will settle it
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

    def follow(self, shaded):
        """Point at the surface the layer is drawing.

        Called for every build, stale or not, because the layer takes every
        build. A driver still holding the one before splices into an array
        nobody draws, and the previews simply stop appearing - which an idle
        rebuild, an edit landing while it runs, and another edit inside the
        gesture window is enough to reach."""
        self._shaded = shaded

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
        except Exception as e:      # noqa: BLE001 - see _run
            # not OSError alone: by now build_surface has put GDAL in
            # exception mode, so a file it cannot open is a RuntimeError
            self.forget()
            self._say(f'no live preview: {type(e).__name__}: {e}')
            return
        if contours.collided:
            # not a preview we can trust: apply() and remove() on a colliding
            # id reach whichever feature registered last, which is in another
            # square. The build is unaffected and the rebuild on idle is
            # right; only the live patching would be wrong.
            self.forget()
            ids = ', '.join(sorted(set(contours.collided))[:4])
            self._say(f'no live preview: {len(contours.collided)} contours share a way id '
                      f'({ids}) - squares saved before ids were made unique across the set; '
                      f'edits rebuild on idle instead')
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
            elif wid in self._drawn:
                # it was a contour and is not one now - deleted, or retagged.
                # The ground it used to cover has to be resolved, so its *old*
                # geometry is what is boxed
                self._mark(wid, self._drawn.pop(wid))
                self._kept.contours.remove(wid)
            else:
                # it was never a contour. Moving a node of a coastline, or of
                # anything untagged, constrains nothing and there is nothing to
                # resolve - boxing its geometry would solve ground the edit
                # cannot have changed, at tens of milliseconds a go
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
        # the caller's, not the dict's: on the deletion path the entry has
        # already been popped and what arrives as `points` *is* the old
        # geometry. Reading self._drawn here would find nothing and work only
        # by the order the arguments happen to be evaluated in.
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
        # floor, not int: int(-0.5) is 0, so a way half a cell west of the
        # raster came out at column 0 and was boxed as if it were inside
        xs = [math.floor((lon - gt[0]) / gt[1]) for lon, _ in points]
        ys = [math.floor((lat - gt[3]) / gt[5]) for _, lat in points]
        if max(xs) < 0 or min(xs) >= cols or max(ys) < 0 or min(ys) >= rows:
            return None
        return local.Box(max(0, min(xs)), max(0, min(ys)),
                         min(cols - 1, max(xs)), min(rows - 1, max(ys)))

    def _run(self):
        """One preview, over everything edited since the last.

        Everything here is inside the guard below, because this is a slot: an
        exception leaving it does not land in a caller, it leaves
        QTimer::timeout, and PySide6 aborts the process rather than printing
        it. The likeliest one is not exotic - the solve loads `libisofill.so`,
        and a machine can have the binary without the library, which is the
        arrangement `interpolate` already handles by falling back. The build
        succeeds there, so the driver adopts, looks live, and dies on the first
        edit.
        """
        try:
            self._preview_once()
        except Exception as e:      # noqa: BLE001
            # off, said once, and quiet after that. The exact rebuild on idle
            # still runs, so the editor keeps working - slower, and honest
            # about it
            self._gesture.stop()
            self._pending.clear()
            self._kept = None
            self._say(f'no live preview: {type(e).__name__}: {e} - '
                      f'edits rebuild on idle instead')

    def _preview_once(self):
        if not self.ready or not self._pending:
            return
        pending, self._pending = self._pending, []
        boxes = self._merged(pending)
        if boxes is None:
            # too many pieces to solve between two keystrokes. Nothing is
            # drawn and nothing is claimed: the surface on screen is still the
            # exact one, so it must not be marked provisional.
            self.skipped.emit(len(pending))
            return
        started = time.perf_counter()
        written: list = []
        for box in boxes:
            patch, good = preview.patch(self._kept, box, self._params)
            # the kept surface carries the edit forward, so the next preview
            # holds its rim at what is on screen and not at a surface two
            # edits old
            self._kept.surface[good.slice] = patch
            rect = self._repaint(good)
            if rect is not None:
                written.append(rect)
        if written:
            # R20's overlay is the first pass's classes, and a preview reruns
            # the first pass without bringing them back: shade_window returns
            # dem and hillshade only. So the overlay now describes the surface
            # as it was - it will call ground unreached that the contour just
            # drawn reaches - and saying nothing would leave red over ground
            # the mapper has just described.
            self.classesStale.emit(written)
        self.patched.emit(written, time.perf_counter() - started)

    def _merged(self, boxes: list) -> list:
        """The gesture's boxes, joined where joining is cheaper than not.

        Not one box around all of them. Two edits at opposite corners of a
        three by three have a bounding box of the whole working set - 12.9 M
        cells at 3 arcseconds - solved in one go inside a timer slot, with the
        editor frozen for it. The boxes are disjoint by construction, so
        solving them apart costs no more work and bounds each piece; they are
        joined only where their union is no bigger than solving them
        separately would be, which is what a gesture's run of adjacent nodes
        looks like.
        """
        shape = self._kept.constraints.shape
        grow = preview.grown_by(self._params)

        def solved(b):
            # what a piece actually costs: patch() grows a box by the cover and
            # the reach before solving it, so two small boxes a few cells apart
            # are two nearly-identical large solves. Comparing the boxes
            # themselves would keep them apart and do the work twice.
            return b.grown(grow, shape).cells

        out: list = []
        for box in sorted(boxes, key=lambda b: (b.y0, b.x0)):
            for i, have in enumerate(out):
                union = local.Box(min(have.x0, box.x0), min(have.y0, box.y0),
                                  max(have.x1, box.x1), max(have.y1, box.y1))
                if solved(union) <= solved(have) + solved(box):
                    out[i] = union
                    break
            else:
                out.append(box)
        if len(out) > MAX_PIECES:
            # None, not []: a caller has to tell "there was nothing to do" from
            # "there was too much". Returning an empty list for both had the
            # window report a preview of zero cells and draw the provisional
            # rim around a surface that was still exact - announcing a skipped
            # preview as a preview, which is the opposite of what skipping is
            # for.
            #
            # Nothing reaches this today - a command names a handful of ways -
            # but the cap exists to be the backstop for when something does,
            # and a backstop that reports the wrong thing is not one. Each
            # piece is a whole solve on the UI thread: at the measured 64.7 ms
            # worst case, eight of them is 518 ms frozen. Eight is a "not
            # absurdly many" bound, not a latency one; F5c is where the
            # latency itself is addressed.
            return None
        return out

    def _repaint(self, good: local.Box):
        """The patch through the clamp and the shading, and into the arrays the
        layer draws."""
        kept, p = self._kept, self._params
        gt = kept.geotransform
        shape = kept.constraints.shape
        # a halo, because the box filter and the hillshade both read their
        # neighbours and the warp reads whatever bilinear touches
        halo = p.smooth_cells + 4
        win = good.grown(halo, shape)
        # the constraints as they are *after* the edit. patch() puts its burn
        # back when it returns, so the kept array holds the build's again and
        # the contour just drawn is not in it - which would leave clamp_patch's
        # third rule testing for a constraint that is not there and never
        # putting the new contour's own elevation back over the fill's guess
        fresh = kept.contours.burn(gt, win, kept.nodata)
        clamped = preview.clamp_patch(kept.surface[win.slice], fresh, kept.dem[win.slice])
        kept.dem[win.slice] = clamped
        sub_gt = (gt[0] + win.x0 * gt[1], gt[1], 0.0, gt[3] + win.y0 * gt[5], 0.0, gt[5])
        m_dem, m_shade, m_gt, _metres = shade.shade_window(
            clamped, sub_gt, self._projection, p, align_to=self._shaded.geotransform)
        return self._splice(m_dem, m_shade, m_gt, win.shape[0], halo)

    def _splice(self, m_dem, m_shade, m_gt, source_rows, halo):
        """Write the patch into the displayed arrays, at the cell it belongs
        to. ``shade_window`` was told the display's grid, so this is whole
        cells and not a resample.

        The halo is cropped off first, which is what ``shade_window`` says its
        caller must do: its outermost cells are computed against an edge that
        is not there - ``np.pad(mode='edge')`` for the box filter,
        ``computeEdges`` for the hillshade, and whatever bilinear reaches for
        the warp. Written in, they replace good display values with worse ones,
        and the next preview holds its rim against the ring they left.
        """
        whole = self._shaded
        x = int(round((m_gt[0] - whole.geotransform[0]) / whole.geotransform[1]))
        y = int(round((m_gt[3] - whole.geotransform[3]) / whole.geotransform[5]))
        rows, cols = m_shade.shape
        # the halo in Mercator cells: the warp is from lat/lon, so a cell of
        # one is not a cell of the other, and the ratio is what converts it.
        # Rounded up, since cropping a cell too many costs a cell of staleness
        # and cropping one too few writes the artefact this exists to avoid.
        if source_rows and halo:
            # the source window's own height, clipped as it actually was. Taking
            # the unclipped height instead made `scale` too small wherever the
            # window ran into the top or bottom of the raster, so `crop` came
            # out short - and since it is rounded up, short enough to trip the
            # guard below and skip the crop altogether, writing the whole ring
            # this exists to keep out.
            scale = rows / max(1, source_rows)
            crop = int(math.ceil(halo * scale))
            if 2 * crop < rows and 2 * crop < cols:
                m_dem = m_dem[crop:rows - crop, crop:cols - crop]
                m_shade = m_shade[crop:rows - crop, crop:cols - crop]
                x, y = x + crop, y + crop
                rows, cols = m_shade.shape
        # clipped, because a window at the raster's own edge warps to a
        # Mercator box that can reach past the display's
        sy0, sx0 = max(0, y), max(0, x)
        sy1 = min(whole.shade.shape[0], y + rows)
        sx1 = min(whole.shade.shape[1], x + cols)
        if sy1 <= sy0 or sx1 <= sx0:
            return None
        dy0, dx0 = sy0 - y, sx0 - x
        whole.dem[sy0:sy1, sx0:sx1] = m_dem[dy0:dy0 + sy1 - sy0, dx0:dx0 + sx1 - sx0]
        whole.shade[sy0:sy1, sx0:sx1] = m_shade[dy0:dy0 + sy1 - sy0, dx0:dx0 + sx1 - sx0]
        # where it landed, so the layer can recolour that and nothing else
        return sy0, sx0, sy1 - sy0, sx1 - sx0
