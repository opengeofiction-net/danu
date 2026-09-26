"""What the surface cannot say, drawn over it - R20 and R21.

The envelope: the outline of the ground the contours describe, one rectangle
per square as ``drawn_mask`` computes it, from the GeoJSON the build wrote.
Beyond it the fill does not reach, and the surface stops.

The unreached ground: where the first pass found no answer, in three shades of
warning - nothing within reach, a pair too flat to trust, a single level in
sight - on the surface's own Mercator grid. R20 calls this the most useful
thing the editor can tell a mapper: here is ground your contours do not
describe.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from ..surface import shade
from . import mercator as m


def envelope_rings(geojson: Path) -> list[list[tuple[float, float]]]:
    """The polygons' outer rings as (lon, lat) lists, from drawn.geojson."""
    data = json.loads(Path(geojson).read_text(encoding='utf-8'))
    rings = []
    for feat in data.get('features', []):
        geom = feat.get('geometry') or {}
        if geom.get('type') == 'Polygon' and geom.get('coordinates'):
            rings.append([(float(x), float(y)) for x, y in geom['coordinates'][0]])
        elif geom.get('type') == 'MultiPolygon':
            for poly in geom.get('coordinates', []):
                if poly:
                    rings.append([(float(x), float(y)) for x, y in poly[0]])
    return rings


class EnvelopeItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setZValue(96)          # over the surface and the unreached ground, under the squares
        self._path = QPainterPath()
        self._rect = QRectF()
        self.rings: list[list[tuple[float, float]]] = []

    def set_rings(self, rings: list[list[tuple[float, float]]]):
        self.prepareGeometryChange()
        self.rings = rings
        path = QPainterPath()
        for ring in rings:
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in ring]
            if len(pts) < 2:
                continue
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
        self._path = path
        self._rect = path.controlPointRect()
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._path.isEmpty():
            return
        pen = QPen(QColor(120, 30, 160, 220), 1.6, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)


class UnreachedLayer(QGraphicsItem):
    """The first-pass classes as a pixmap on the surface's rectangle."""

    def __init__(self):
        super().__init__()
        self.setZValue(55)          # just over the surface
        self._pixmap: QPixmap | None = None
        self._rect = QRectF()
        self.reading: dict | None = None
        self.one_level = False
        self.stale = False
        self._shaded: shade.Shaded | None = None

    def set_stale(self, rects=True):
        """Where the surface has moved under this overlay without the classes
        being recomputed - which is what a preview does: it reruns the first
        pass for a box and brings back the DEM and the hillshade, not the
        classes. Left alone the overlay goes on calling ground unreached that
        the contour just drawn reaches, in red, over a surface that shows it
        does.

        ``rects`` is a list of (y, x, rows, cols) in this pixmap's own grid,
        which is the grid the preview splices into. They are **added to** what
        is already stale, not substituted for it: the classes are out of date
        over everything previewed since the last build, and only a build makes
        them true again. ``set_shaded`` is what clears it.

        So ``False`` and ``[]`` mean *nothing new to add*, not *nothing is
        stale* - the one direction of this that is surprising, and the reason
        it is written here rather than only in a comment inside the function.

        Faded there rather than hidden: the classes are a *first pass* result,
        and most of what they say about the patched ground is still true - the
        contour just drawn changes the answer near itself, not everywhere in
        the box. Faded *only there* rather than everywhere, because the first
        version of this dimmed the whole raster to say something about a
        215-cell box of 24.4 M - about 0.2% of it - and a uniformly dim overlay
        reads as "faint", not as "out of date here". Dimming with an edge says
        which ground has stopped being described, which is what the dashed
        amber rim says for the surface.

        True dims all of it, which is the honest answer when the caller does
        not know where.

        A failed build leaves this alone, which looks like an oversight and is
        not: a build that failed did not make the classes true, so the ground
        it would have covered really is still out of date and the fade is
        reporting accurately. The provisional rim behaves the same way for the
        same reason.
        """
        before = self.stale
        if rects is True or self.stale is True:
            self.stale = True
        elif not rects:
            pass                     # nothing new to add
        elif isinstance(self.stale, list):
            # added to, not replaced. The classes are out of date over
            # everything previewed since the last build, not over the last
            # preview: a contour drawn node by node is one preview per gesture,
            # so replacing left the dim region chasing the cursor while the
            # nodes behind it - equally out of date - sat at full strength.
            # A build clears it, which is the right bound, because a build is
            # what makes the classes true again.
            have = set(map(tuple, self.stale))
            self.stale = self.stale + [r for r in map(tuple, rects) if r not in have]
        else:
            self.stale = [tuple(r) for r in rects]
        if before != self.stale:
            self.update()

    def set_shaded(self, shaded: shade.Shaded | None):
        self.stale = False
        self.prepareGeometryChange()
        self._shaded = shaded
        if shaded is None or shaded.classes is None:
            self._pixmap, self._rect, self.reading = None, QRectF(), None
            self.update()
            return
        l, t, r, b = shaded.scene_rect
        self._rect = QRectF(l, t, r - l, b - t)
        self._repaint_classes()
        self.reading = shaded.reading
        self.update()

    def set_one_level(self, on: bool):
        self.one_level = bool(on)
        if self._shaded is not None and self._shaded.classes is not None:
            self._repaint_classes()
            self.update()

    def _repaint_classes(self):
        shaded = self._shaded
        rgba = np.ascontiguousarray(shade.unreached_rgba(shaded.classes, self.one_level))
        rows, cols = rgba.shape[:2]
        img = QImage(rgba.data, cols, rows, cols * 4, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(img.copy())

    def summary(self) -> str:
        """Area and fraction, as the validation table asks - the build's own
        reading, measured on the lat/lon grid, not recounted on the Mercator
        pixels this is drawn on."""
        r = self.reading
        if not r or not r.get('inside_cells'):
            return 'no first-pass reading'
        km2 = r['km2']['1'] + r['km2']['2']
        pct = r['percent']['1'] + r['percent']['2']
        return (f'{km2:,.1f} km² the contours do not describe, {pct:.1f}% of the drawn area: '
                f'{r["cells"]["1"]:,} cells nothing in reach, {r["cells"]["2"]:,} too flat to trust; '
                f'and {r["cells"]["3"]:,} seeing one level, mostly the contours\' own edges')

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None):
        if self._pixmap is None:
            return
        whole = QRectF(self._pixmap.rect())
        if not self.stale:
            painter.drawPixmap(self._rect, self._pixmap, whole)
            return
        # Drawn twice, clipped: full strength where these classes still
        # describe the surface, faded where a preview has moved the ground
        # under them - see set_stale.
        #
        # The overlay's own pixmap both times, never a wash over the top. A
        # translucent rectangle drawn over this layer does not dim the overlay,
        # it paints over whatever is beneath it: unreached_rgba is transparent
        # wherever the first pass had an answer, which is most of any box, so a
        # white wash at alpha 165 turned a mostly-answered patch into a pale
        # grey rectangle over the hillshade, 73% brighter than the ground
        # around it and with no red in it at all - and where the surface itself
        # is transparent, over the map tiles.
        rows, cols = self._pixmap.height(), self._pixmap.width()
        if rows <= 0 or cols <= 0:
            return
        sx, sy = self._rect.width() / cols, self._rect.height() / rows
        faded = QPainterPath()
        # Winding, and QPainterPath's default is *odd-even*. These rectangles
        # overlap as a matter of course - a contour drawn node by node is one
        # preview per gesture and each rect is grown by a hundred cells, so
        # consecutive ones cover almost the same ground - and under odd-even
        # an overlap cancels: it falls out of `faded`, back into `crisp`, and
        # is drawn at full strength. Measured before this line existed, the
        # middle of a stroke came out the plain overlay colour while its ends
        # were faded, which reads as a rendering quirk rather than as the
        # overlap of two stale regions.
        faded.setFillRule(Qt.FillRule.WindingFill)
        if isinstance(self.stale, list):
            for y, x, h, w in self.stale:
                faded.addRect(QRectF(self._rect.left() + x * sx, self._rect.top() + y * sy,
                                     w * sx, h * sy))
        else:
            faded.addRect(self._rect)
        crisp = QPainterPath()
        crisp.addRect(self._rect)
        crisp = crisp.subtracted(faded)

        was_clip, had_clip = painter.clipPath(), painter.hasClipping()
        painter.setClipPath(crisp)
        painter.drawPixmap(self._rect, self._pixmap, whole)
        painter.setClipPath(faded)
        was_opacity = painter.opacity()
        painter.setOpacity(was_opacity * 0.35)
        painter.drawPixmap(self._rect, self._pixmap, whole)
        painter.setOpacity(was_opacity)
        if had_clip:
            painter.setClipPath(was_clip)
        else:
            painter.setClipping(False)
