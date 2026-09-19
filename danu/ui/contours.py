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

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core import geometry
from ..core.square import Square, SquareName, Way, WorkingSet
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


@dataclass
class WayGeom:
    """One way projected: the square it is in, the way, its elevation (None
    for a coastline, which is here to snap to and not to draw) and its points
    in scene units. The layer keeps one per way so an edit re-projects the
    ways it touched and nothing else."""
    square: Square
    way: Way
    ele: float | None
    pts: np.ndarray


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
        self.active: float | None = None          # the active elevation, drawn heavier
        self._geoms: dict[tuple[SquareName, int], WayGeom] = {}
        # every segment of every contour, and every node of every contour and
        # coastline, as parallel arrays: the nearest of a hundred thousand,
        # or the crossings of a new segment with all of them, is one
        # vectorised operation, not a walk
        self._ways: list[WayGeom] = []
        self._seg_a = np.zeros((0, 2)); self._seg_b = np.zeros((0, 2))
        self._seg_ele = np.zeros(0); self._seg_way = np.zeros(0, dtype=np.int64); self._seg_i = np.zeros(0, dtype=np.int64)
        self._node_xy = np.zeros((0, 2)); self._node_ref: list[tuple[Square, int]] = []
        self._bounds = QRectF()
        # what the last paint did, for tests and for a status line
        self.drawn_levels = 0
        self.drawn_labels = 0

    # ------------------------------------------------------------ data
    def set_working_set(self, ws: WorkingSet | None, ramp: Ramp | None = None):
        self.prepareGeometryChange()
        self.working_set = ws
        self.paths, self.labels, self.index_levels, self._geoms = {}, [], set(), {}
        if ws is None:
            self._bounds = QRectF()
            self._rebuild_arrays()
            self.update()
            return
        w, s, e, n = ws.bounds
        x0, y0 = m.lonlat_to_scene(w, n)
        x1, y1 = m.lonlat_to_scene(e, s)
        self._bounds = QRectF(x0, y0, x1 - x0, y1 - y0)
        rng = ws.elevation_range()
        self.ramp = ramp if ramp is not None else spectral(*rng) if rng else spectral()
        for square in ws.present():
            for way in square.ways.values():
                geom = self._project(square, way)
                if geom is not None:
                    self._geoms[(square.name, way.id)] = geom
        self._rebuild_levels({g.ele for g in self._geoms.values() if g.ele is not None})
        self._rebuild_arrays()
        self.update()

    @staticmethod
    def _project(square: Square, way: Way) -> WayGeom | None:
        """A contour or a coastline with at least two placed nodes; anything
        else is not a line and is not kept."""
        ele = way.ele
        if ele is None and way.tags.get('natural') != 'coastline':
            return None
        pts = [m.lonlat_to_scene(lon, lat) for lon, lat in square.coords(way)]
        if len(pts) < 2:
            return None
        return WayGeom(square, way, ele, np.asarray(pts, dtype=float))

    def refresh(self, square: Square, way_ids: set[int]):
        """Some ways of a square changed - an edit, or its undo. Re-project
        them, rebuild the levels they were and are at, and the arrays."""
        levels: set[float] = set()
        for wid in way_ids:
            old = self._geoms.pop((square.name, wid), None)
            if old is not None and old.ele is not None:
                levels.add(old.ele)
            way = square.ways.get(wid)
            geom = self._project(square, way) if way is not None else None
            if geom is not None:
                self._geoms[(square.name, wid)] = geom
                if geom.ele is not None:
                    levels.add(geom.ele)
        self._rebuild_levels(levels)
        self._rebuild_arrays()
        self.update()

    def _rebuild_levels(self, levels: set[float]):
        for ele in levels:
            self.paths.pop(ele, None)
        self.labels = [lab for lab in self.labels if lab.ele not in levels]
        for g in self._geoms.values():
            if g.ele is None or g.ele not in levels:
                continue
            path = self.paths.setdefault(g.ele, QPainterPath())
            path.moveTo(*g.pts[0])
            for x, y in g.pts[1:]:
                path.lineTo(x, y)
            self.labels.append(self._label(g.ele, [tuple(p) for p in g.pts]))
        all_levels = sorted(self.paths)
        self.index_levels = set(all_levels[::INDEX_EVERY_N])

    def _rebuild_arrays(self):
        # always replaced: a set with no contours after one with many must
        # not leave the old segments behind for pick to find
        self._ways = [g for g in self._geoms.values() if g.ele is not None]
        seg_a = [g.pts[:-1] for g in self._ways]
        empty = np.zeros((0, 2))
        self._seg_a = np.concatenate(seg_a) if seg_a else empty
        self._seg_b = np.concatenate([g.pts[1:] for g in self._ways]) if seg_a else empty
        self._seg_ele = np.concatenate([np.full(len(g.pts) - 1, g.ele) for g in self._ways]) if seg_a else np.zeros(0)
        self._seg_way = np.concatenate([np.full(len(g.pts) - 1, i) for i, g in enumerate(self._ways)]) if seg_a else np.zeros(0, dtype=np.int64)
        self._seg_i = np.concatenate([np.arange(len(g.pts) - 1) for g in self._ways]) if seg_a else np.zeros(0, dtype=np.int64)
        node_xy, self._node_ref = [], []
        for g in self._geoms.values():                    # contours and coastlines both
            for ref, pt in zip(g.way.refs, g.pts):
                if ref in g.square.nodes:
                    node_xy.append(pt)
                    self._node_ref.append((g.square, ref))
        self._node_xy = np.asarray(node_xy, dtype=float) if node_xy else empty

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

    # ---------------------------------------------------------- queries
    def pick(self, x: float, y: float, tolerance: float) -> tuple[Square, Way, float, int] | None:
        """The contour nearest a scene point, within a scene-unit tolerance,
        as (square, way, distance, segment index); None when nothing is that
        close. Space picks up its elevation, the tools continue it and
        insert into the segment."""
        if not len(self._seg_ele):
            return None
        t, dist = geometry.nearest_point_on_segments((x, y), self._seg_a, self._seg_b)
        i = int(dist.argmin())
        if dist[i] > tolerance:
            return None
        g = self._ways[int(self._seg_way[i])]
        return g.square, g.way, float(dist[i]), int(self._seg_i[i])

    def pick_node(self, x: float, y: float, tolerance: float) -> tuple[Square, int, float] | None:
        """The node - of a contour or a coastline, R15's two snap targets -
        nearest a scene point within a tolerance, as (square, id, distance)."""
        if not len(self._node_xy):
            return None
        dist = np.hypot(*(self._node_xy - (x, y)).T)
        i = int(dist.argmin())
        if dist[i] > tolerance:
            return None
        square, ref = self._node_ref[i]
        return square, ref, float(dist[i])

    def crossings(self, p: tuple[float, float], q: tuple[float, float], ele: float) -> list[tuple[Square, Way, bool]]:
        """R16 for one prospective segment: the contours it would cross, and
        those at another elevation it would so much as touch, each with
        whether it is crossed outright (True) or only met (False). The way
        being drawn is not exempt: the new segment meets its last one at a
        shared node, which is a touch at the same elevation and allowed, and
        anything more is a contour crossing itself."""
        if not len(self._seg_ele):
            return []
        proper = geometry.crossings(p, q, self._seg_a, self._seg_b)
        touch = geometry.touches(p, q, self._seg_a, self._seg_b) & (self._seg_ele != ele)
        out: dict[int, tuple[Square, Way, bool]] = {}
        for i in np.flatnonzero(proper | touch):
            g = self._ways[int(self._seg_way[i])]
            hit = out.get(id(g.way))
            if hit is None or (proper[i] and not hit[2]):
                out[id(g.way)] = (g.square, g.way, bool(proper[i]))
        return list(out.values())

    def node_xy(self, square: Square, node_id: int) -> tuple[float, float]:
        n = square.nodes[node_id]
        return m.lonlat_to_scene(n.lon, n.lat)

    def set_active(self, ele: float | None):
        if ele != self.active:
            self.active = ele
            self.update()

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
            # grown by a unit: a straight east-west contour has a rect of no
            # height, and QRectF.intersects is false for an empty rect
            if not path.controlPointRect().adjusted(-1, -1, 1, 1).intersects(rect):
                continue
            pen = QPen(self.colour(ele), 1.8 if index else 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(path)
            self.drawn_levels += 1
        if self.active is not None and self.active in self.paths and zoom >= ZOOM_INDEX:
            # the level being drawn at, over everything: the mapper needs to
            # see where it already runs
            path = self.paths[self.active]
            if path.controlPointRect().adjusted(-1, -1, 1, 1).intersects(rect):
                pen = QPen(self.colour(self.active).darker(120), 3.2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawPath(path)
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
