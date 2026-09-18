"""Contours as vectors over the map - R12.

One QGraphicsItem for the whole working set. The ways are projected once, when
the set is given, into one QPainterPath per elevation, so painting is a few
dozen path strokes rather than thousands, and every way at 250 m is the one
colour it should be. Labels are placed once too: the midpoint of each way and
the bearing of the segment it falls on.

Level of detail by zoom, because a degree square at zoom 7 is 90 pixels wide
and a thousand contours in it are a smudge:

- below ZOOM_INDEX nothing is drawn; the squares' outlines (phase 1, D) say
  where the contours are
- from ZOOM_INDEX only the index contours: every fifth distinct level in the
  working set, until the ladder is inferred (phase 3) and "index" can mean
  every fifth rung of it. Not every 100 m: OGF ladders are odd - 101, 151,
  201 - and a square can have no round hundred in it at all
- from ZOOM_ALL every contour
- from ZOOM_LABELS labels too, on ways long enough on screen to carry one

Colour is by elevation through a Ramp. The default is the spectral ramp over
the working set's own range, because the tiles' hypsometric ramp - available
as the other choice - makes a low square all one green. Alpha is ignored for
lines: the hypsometric ramp is transparent at sea level so the water shows
through a raster, and a contour at 0 m still wants drawing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core.square import WorkingSet
from ..surface.ramp import Ramp, spectral
from . import mercator as m
from .mapview import visible_rect

ZOOM_INDEX = 8
ZOOM_ALL = 11
ZOOM_LABELS = 12
INDEX_EVERY_N = 5
MIN_LABEL_PX = 80.0
FONT_PT = 9


@dataclass
class Label:
    ele: float
    x: float          # scene
    y: float
    angle: float      # degrees, upright
    length: float     # of the way, scene units


class ContourLayer(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setZValue(100)
        self.working_set: WorkingSet | None = None
        self.paths: dict[float, QPainterPath] = {}
        self.labels: list[Label] = []
        self.ramp: Ramp = spectral()
        self.index_levels: set[float] = set()
        self._bounds = QRectF()
        # what the last paint did, for tests and for a status line
        self.drawn_levels = 0
        self.drawn_labels = 0

    # ------------------------------------------------------------ data
    def set_working_set(self, ws: WorkingSet | None, ramp: Ramp | None = None):
        self.prepareGeometryChange()
        self.working_set = ws
        self.paths, self.labels, self.index_levels = {}, [], set()
        if ws is None:
            self._bounds = QRectF()
            self.update()
            return
        w, s, e, n = ws.bounds
        x0, y0 = m.lonlat_to_scene(w, n)
        x1, y1 = m.lonlat_to_scene(e, s)
        self._bounds = QRectF(x0, y0, x1 - x0, y1 - y0)
        rng = ws.elevation_range()
        self.ramp = ramp if ramp is not None else spectral(*rng) if rng else spectral()
        for square, way in ws.contours():
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in square.coords(way)]
            if len(pts) < 2:
                continue
            path = self.paths.setdefault(way.ele, QPainterPath())
            path.moveTo(*pts[0])
            for p in pts[1:]:
                path.lineTo(*p)
            self.labels.append(self._label(way.ele, pts))
        levels = sorted(self.paths)
        self.index_levels = set(levels[::INDEX_EVERY_N])
        self.update()

    @staticmethod
    def _label(ele: float, pts: list[tuple[float, float]]) -> Label:
        """Midpoint by length, and the bearing there, turned upright."""
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
        total = sum(seg)
        half, run = total / 2.0, 0.0
        for (a, b), d in zip(zip(pts, pts[1:]), seg):
            if run + d >= half and d > 0:
                t = (half - run) / d
                x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                if ang > 90 or ang <= -90:
                    ang += 180 if ang <= -90 else -180
                return Label(ele, x, y, ang, total)
            run += d
        return Label(ele, pts[0][0], pts[0][1], 0.0, total)

    def colour(self, ele: float) -> QColor:
        r, g, b, _ = self.ramp.colour(ele)
        return QColor(r, g, b)

    def is_index(self, ele: float) -> bool:
        return ele in self.index_levels

    # ------------------------------------------------------------ paint
    def boundingRect(self) -> QRectF:
        return self._bounds

    def paint(self, painter: QPainter, option, widget=None):
        self.drawn_levels = self.drawn_labels = 0
        if not self.paths:
            return
        scale = painter.worldTransform().m11()
        zoom = m.zoom_for_scale(scale)
        if zoom < ZOOM_INDEX:
            return
        rect = visible_rect(painter, option, self._bounds)
        if rect.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for ele in sorted(self.paths):
            index = self.is_index(ele)
            if zoom < ZOOM_ALL and not index:
                continue
            path = self.paths[ele]
            if not path.controlPointRect().intersects(rect):
                continue
            pen = QPen(self.colour(ele), 1.8 if index else 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(path)
            self.drawn_levels += 1
        if zoom >= ZOOM_LABELS:
            self._paint_labels(painter, rect, scale, zoom)

    def _paint_labels(self, painter: QPainter, rect: QRectF, scale: float, zoom: float):
        font = QFont()
        font.setPointSize(FONT_PT)
        halo = QPen(QColor(255, 255, 255, 220), 3.0)
        halo.setCosmetic(True)
        for lab in self.labels:
            if lab.length * scale < MIN_LABEL_PX or not rect.contains(QPointF(lab.x, lab.y)):
                continue
            if zoom < ZOOM_ALL and not self.is_index(lab.ele):
                continue
            text = f'{lab.ele:g}'
            painter.save()
            painter.translate(lab.x, lab.y)
            painter.rotate(lab.angle)
            painter.scale(1.0 / scale, 1.0 / scale)      # pixels, whatever the zoom
            tp = QPainterPath()
            tp.addText(QPointF(0, 0), font, text)
            tp.translate(-tp.boundingRect().width() / 2, tp.boundingRect().height() / 2 - 1)
            painter.setPen(halo)
            painter.drawPath(tp)
            painter.fillPath(tp, self.colour(lab.ele).darker(130))
            painter.restore()
            self.drawn_labels += 1
