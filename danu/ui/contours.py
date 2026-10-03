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
- from ZOOM_LABELS labels too, on ways long enough on screen to carry one.
  Two zooms above ZOOM_ALL rather than one: the contours are what a mapper is
  reading at z12 and z13, and the labels were a third of what it cost to draw
  them

Colour is by elevation through a Ramp. The default is the spectral ramp over
the working set's own range, because the tiles' hypsometric ramp - available
as the other choice - makes a low square all one green. Alpha is ignored for
lines: the hypsometric ramp is transparent at sea level so the water shows
through a raster, and a contour at 0 m still wants drawing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import chain, pairwise

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core import geometry
from ..core.square import Square, SquareName, Way, WorkingSet, parse_ele
from ..surface.ramp import Ramp, spectral
from . import mercator as m
from .mapview import visible_rect

ZOOM_INDEX = 8
ZOOM_ALL = 11
# 14, not 12. Labels are the most expensive thing this layer draws for what
# they tell you, and they cost most where they say least: a contour carries one
# label however far in you are, so zooming out puts more of them on screen and
# makes each one smaller. Measured in one run, so the columns subtract:
#
#        labels from 12        labels from 14      saved
#   z12  33.6 ms, 86 labels    23.2 ms,  0        10.4 ms
#   z13  21.7 ms, 55 labels    14.6 ms,  0         7.2 ms
#   z14  13.2 ms, 11 labels    13.2 ms, 11             -
#
# About a third of a *repaint* at z12 and z13. Not a third of an edit: an edit
# is two repaints on top of a solve, so the 7.2 ms at z13 is about 14 of some
# 145, which is worth having and is not the same claim.
ZOOM_LABELS = 14
# spot heights appear here. Not at every zoom this layer draws at, which is
# what they did first: a working set holds as many of them as it holds
# hilltops, and at z8 to z11 they are a scatter of dots over index contours
# too coarse to place them against. The value beside one waits for
# ZOOM_LABELS either way
ZOOM_SPOTS = 12
INDEX_EVERY_N = 5
MIN_LABEL_PX = 80.0
FONT_PT = 9
# the spot height marker's radius, in pixels: a point on the ground, so it
# does not grow with the zoom
SPOT_PX = 3.5
# the one colour all water is drawn in. Not from the ramp: none of it has an
# elevation to take a colour from until G6, and a river is where the valley
# floor is rather than how high it is
WATER = QColor(70, 130, 190, 200)


@dataclass
class _Piece:
    """One way's contour, and the rectangle it occupies.

    One path per *way*, where this used to keep one per elevation. A level's
    path is every way at that elevation joined together, so on a working set
    it spans nearly the whole of it, and culling by its rectangle culls
    nothing: the gobras 3x3 redrew 341,694 points on every paint, which was
    150.8 ms of a 153 ms repaint - every pan, and every edit. Per way the
    rectangle is the way's own and the cull is worth doing.

    What it costs is a drawPath and a rectangle test per way rather than per
    level. The test is nothing; the call has some overhead, and at a zoom
    where everything is visible it is paid for no saving - which is why it is
    measured at both ends in tests/ui/test_contours.py rather than assumed.

    It carries its elevation and its label so that an edit can take one way
    out without looking at the others - see ``_drop_way``. The elevation is
    what makes that cheap, being the key into ``paths``. What makes identity
    *necessary* is that two ways drawing the same line hold equal paths, equal
    rectangles and equal labels, so equality cannot tell them apart; and what
    makes it *sufficient* is that ``_label`` builds a new object per call, so
    a piece and its label each belong to one way. A cached or shared ``Label``
    would break ``_drop_way``, not merely change what is drawn."""
    path: QPainterPath
    rect: QRectF
    ele: float | None     # None for water: it has no elevation until G6
    label: 'Label | None'  # and None for water: nothing labels it


def _water_tags(tags: dict) -> bool:
    """``natural=water``, or any ``waterway``. Asked of a way and of a
    relation with the one function, so the two cannot drift apart."""
    return tags.get('natural') == 'water' or 'waterway' in tags


def _water_members(square: Square) -> frozenset:
    """The ways a square's water relations are made of. A multipolygon's rings
    carry no tagging of their own, so this is what says they are water.

    The same test as ``_is_water``, deliberately: the import only asks
    Overpass for ``relation["natural"="water"]``, so a ``type=waterway``
    relation does not arrive from there - but one can be drawn, or already be
    in a square, and its member ways carry no tagging of their own either. A
    relation the predicates disagreed about would draw its rings on one path
    and not the other.
    """
    return frozenset(mem.ref for rel in square.relations.values()
                     if _water_tags(rel.tags)
                     for mem in rel.members if mem.type == 'way')


def _is_water(way: Way) -> bool:
    """A way an import brought, or a mapper drew, as water.

    ``natural=water`` or any ``waterway``. A multipolygon's member rings carry
    neither - the relation holds the tagging - so ``set_working_set`` marks
    them from the relation; this answers for the way alone."""
    return _water_tags(way.tags)


@dataclass
class Spot:
    """A node carrying an elevation, projected - R36's spot height.

    It is not a `WayGeom` of one point. A way is a line and everything about
    drawing, picking and culling one is about the line; a spot height is a
    place and a number, and the only thing it shares with a contour is the
    colour its elevation gives it."""
    square: Square
    node_id: int
    ele: float
    x: float          # scene
    y: float


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
    ways it touched and nothing else.

    ``refs`` are the node ids those points belong to, in the same order and the
    same number: a way can name a node the square does not have - JOSM will
    save a way whose node was deleted under it - and that ref has no point.
    Kept together because the alternative, pairing ``way.refs`` with ``pts``
    afterwards, silently pairs every ref after a gap with the next node's
    position, so a click snapped to one node and dragged another."""
    square: Square
    way: Way
    ele: float | None
    pts: np.ndarray
    refs: list[int] = field(default_factory=list)

    def __post_init__(self):
        # _rebuild_arrays builds the node index by putting refs against points
        # one for one, so a WayGeom whose two disagreed would file a node at
        # another node's position - which is the bug this pairing replaced.
        # Whether each ref is one the square has is _project's business; that
        # they line up is every caller's, so it is checked here
        if self.refs and len(self.refs) != len(self.pts):
            raise ValueError(f'{len(self.refs)} refs against {len(self.pts)} points')

    # A cache, not a field: annotated with a default inside a dataclass body it
    # became a constructor parameter and part of __repr__ and __eq__, which is
    # not what a lazily built index of the object's own data should be.
    _node_ref: list[tuple[Square, int]] | None = field(
        init=False, repr=False, compare=False, default=None)

    @property
    def node_ref(self) -> list[tuple[Square, int]]:
        """(square, ref) per point, which is what the layer's node index is
        made of. Built once here rather than per rebuild.

        It caches ``refs`` and ``square``, which a WayGeom does not change
        after ``_project`` builds it - an edited way is re-projected into a new
        one rather than mutated. That invariant is what makes the cache safe.
        """
        if self._node_ref is None:
            self._node_ref = [(self.square, r) for r in self.refs]
        return self._node_ref


class ContourLayer(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)
        self.setZValue(100)
        self.working_set: WorkingSet | None = None
        # per way, not per level: see _Piece and paint()
        self.paths: dict[float, list[_Piece]] = {}
        self.labels: list[Label] = []
        self.ramp: Ramp = spectral()
        self.index_levels: set[float] = set()
        self.active: float | None = None          # the active elevation, drawn heavier
        self._geoms: dict[tuple[SquareName, int], WayGeom] = {}
        # the piece each way contributes, so an edit can replace one of them
        self._pieces: dict[tuple[SquareName, int], _Piece] = {}
        # and the spot heights, by square and node. Drawn over the contours and
        # picked before them: a spot height is a few pixels across and sits on
        # ground a contour runs through, so a click that could mean either
        # means the small thing
        self.spots: dict[tuple[SquareName, int], Spot] = {}
        # the water, drawn under everything. Here and not only in
        # set_working_set because _paint_water reads it, and a layer can be
        # painted before it is given a set
        self.water: dict[tuple[SquareName, int], _Piece] = {}
        # whether a level has appeared or emptied since index_levels was last
        # worked out, which is the only thing that can move an index contour
        self._levels_moved = False
        # every segment of every contour, and every node of every contour and
        # coastline, as parallel arrays: the nearest of a hundred thousand,
        # or the crossings of a new segment with all of them, is one
        # vectorised operation, not a walk
        self._ways: list[WayGeom] = []
        self._seg_a = np.zeros((0, 2)); self._seg_b = np.zeros((0, 2))
        self._seg_ele = np.zeros(0); self._seg_way = np.zeros(0, dtype=np.int64); self._seg_i = np.zeros(0, dtype=np.int64)
        self._node_xy = np.zeros((0, 2)); self._node_ref: list[tuple[Square, int]] = []
        self._arrays_stale = False
        self._text: dict[tuple[str, str], QPainterPath] = {}
        self._bounds = QRectF()
        # what the last paint did, for tests and for a status line
        self.drawn_levels = 0
        # how many ways the cull let through, for tests. The level pass only:
        # the active level is drawn again over the top and counting that would
        # count the same ways twice
        self.drawn_ways = 0
        self.drawn_labels = 0
        self.drawn_spots = 0
        self.drawn_water = 0

    # ------------------------------------------------------------ data
    def set_working_set(self, ws: WorkingSet | None, ramp: Ramp | None = None):
        self.prepareGeometryChange()
        self.working_set = ws
        # _text is not cleared with them: it is keyed on the label's string and
        # the font, and the strings are elevations, which are the same from one
        # working set to the next. It grows with the distinct pairs ever shown,
        # which is bounded and small - and the font being in the key is what
        # makes not clearing safe, since there is otherwise no eviction.
        self.paths, self.labels, self.index_levels = {}, [], set()
        self._geoms, self._pieces, self.spots, self.water = {}, {}, {}, {}
        if ws is None:
            self._bounds = QRectF()
            self._arrays_stale = True
            self.update()
            return
        w, s, e, n = ws.bounds
        x0, y0 = m.lonlat_to_scene(w, n)
        x1, y1 = m.lonlat_to_scene(e, s)
        self._bounds = QRectF(x0, y0, x1 - x0, y1 - y0)
        rng = ws.elevation_range()
        self.ramp = ramp if ramp is not None else spectral(*rng) if rng else spectral()
        for square in ws.present():
            # a multipolygon's rings carry no tagging of their own - the
            # relation holds it - so a layer that asked the way alone would
            # draw a lake as nothing. Gathered once per square rather than
            # asked per way, which on 112 relations and four thousand ways is
            # the difference between a lookup and a search
            members = _water_members(square)
            for way in square.ways.values():
                geom = self._project(square, way, members)
                if geom is not None:
                    self._geoms[(square.name, way.id)] = geom
            for nid in square.nodes:
                self._project_spot(square, nid)
        for key, geom in self._geoms.items():
            if geom.ele is not None:
                self._add_way(key, geom)
            else:
                # whatever is not a contour and was kept is water or a
                # coastline; the coastline is here to snap to and not to draw,
                # and `_project` is what decided either of them was worth
                # keeping at all
                if geom.way.tags.get('natural') != 'coastline':
                    self._add_water(key, geom)
        self._reindex()
        self._levels_moved = False
        self._arrays_stale = True
        self.update()

    @staticmethod
    def _project(square: Square, way: Way, water_members=frozenset()) -> WayGeom | None:
        """A contour, a coastline or water, with at least two placed nodes;
        anything else is not a line and is not kept.

        Water joined when an import could put it in a square - G4c. It is kept
        for the same reason a coastline is, which is that a mapper drawing
        contours along a valley needs to see where the river is, and it is
        drawn in a colour of its own because it has no elevation to take one
        from.

        The refs are carried alongside the points, so both drop a node the
        square does not have and the two stay aligned."""
        ele = way.ele
        if (ele is None and not _is_water(way) and way.id not in water_members
                and way.tags.get('natural') != 'coastline'):
            return None
        nodes = square.nodes
        placed = [(r, nodes[r]) for r in way.refs if r in nodes]
        if len(placed) < 2:
            return None
        pts = m.lonlat_to_scene_array([n.lon for _, n in placed], [n.lat for _, n in placed])
        return WayGeom(square, way, ele, pts, [r for r, _ in placed])

    def _project_spot(self, square: Square, node_id: int) -> None:
        """Put a node in the spot dict if it carries a usable elevation, and
        take it out if it does not. Called for every node a command names, so
        it is also how one stops being a spot height."""
        key = (square.name, node_id)
        node = square.nodes.get(node_id)
        # the same rule a way's elevation is read by, and the same function:
        # ele=TBD on a lake outlet and ele=tbd on a peak are not elevations,
        # and neither is inf. A mapper should not see one of those drawn as
        # ground at 0 m, or at all
        ele = parse_ele(node.tags.get('ele')) if node is not None else None
        if ele is None:
            self.spots.pop(key, None)
            return
        x, y = m.lonlat_to_scene(node.lon, node.lat)
        self.spots[key] = Spot(square, node_id, ele, x, y)

    def refresh_spots(self, square: Square, node_ids) -> None:
        """Some nodes of a square changed - re-project the ones that are spot
        heights and drop the ones that are not.

        Only the ids given, where ``set_working_set`` walks every node. What
        makes that safe is ``Command.spots()``: a command names every node
        whose standing as a constraint it may change, and the only command
        that writes a node's tags - ``SetNodeTags`` - names its own. A command
        added later that mutates tags without declaring them would leave the
        canvas showing something the build does not, which is the divergence
        the whole arrangement exists to prevent.
        """
        if not node_ids:
            return
        for nid in node_ids:
            self._project_spot(square, nid)
        self.update()

    def refresh(self, square: Square, way_ids: set[int]):
        """Some ways of a square changed - an edit, or its undo. Re-project
        them, replace what they draw, and mark the arrays stale.

        Only those ways. This used to rebuild every way at the elevations they
        were and are at, because the pieces were reachable only through the
        level that held them: moving one node of a 175 m contour on the gobras
        3x3 re-projected 723 ways and 28,618 points, and cost 27 ms of a 50 ms
        budget on every edit at every zoom - the largest thing left on the UI
        thread once F5c had finished with the painting. A piece now knows its
        own level and label, so taking one out is a list removal by identity
        and putting one back is one path.
        """
        # once for the call, not once per way: the same reason set_working_set
        # gathers it once per square
        members = _water_members(square)
        for wid in way_ids:
            key = (square.name, wid)
            self._drop_way(key)
            self._geoms.pop(key, None)
            self.water.pop(key, None)
            way = square.ways.get(wid)
            geom = (self._project(square, way, members)
                    if way is not None else None)
            if geom is not None:
                self._geoms[key] = geom
                if geom.ele is not None:
                    self._add_way(key, geom)
                elif geom.way.tags.get('natural') != 'coastline':
                    self._add_water(key, geom)
        if self._levels_moved:
            self._reindex()
            self._levels_moved = False
        self._arrays_stale = True
        self.update()

    def _add_water(self, key: tuple[SquareName, int], g: WayGeom) -> None:
        """A water way's path and rectangle, in the pass that draws under the
        contours."""
        pts = g.pts.tolist()
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        xs, ys = g.pts[:, 0], g.pts[:, 1]
        rect = QRectF(float(xs.min()) - 1, float(ys.min()) - 1,
                      float(xs.max() - xs.min()) + 2, float(ys.max() - ys.min()) + 2)
        self.water[key] = _Piece(path, rect, None, None)

    def _add_way(self, key: tuple[SquareName, int], g: WayGeom) -> None:
        """One way's path, rectangle and label, into the level it draws at."""
        # tolist() first: stepping a numpy (n, 2) array row by row in
        # Python builds an array scalar per coordinate, and there are
        # 342,000 of them in the gobras 3x3. The same path building over
        # plain floats is 66 ms against 400 ms, measured on that set
        pts = g.pts.tolist()
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        xs, ys = g.pts[:, 0], g.pts[:, 1]
        # grown by a unit, so a straight east-west contour - whose rect has
        # no height - still intersects anything
        rect = QRectF(float(xs.min()) - 1, float(ys.min()) - 1,
                      float(xs.max() - xs.min()) + 2, float(ys.max() - ys.min()) + 2)
        piece = _Piece(path, rect, g.ele, self._label(g.ele, pts))
        self._pieces[key] = piece
        if g.ele not in self.paths:
            self._levels_moved = True
        self.paths.setdefault(g.ele, []).append(piece)
        self.labels.append(piece.label)

    def _drop_way(self, key: tuple[SquareName, int]) -> None:
        """Whatever that way was drawing, out - and nothing else.

        By identity rather than by equality: two ways at one elevation can
        hold equal paths, equal rectangles and equal labels, and a fixture
        where 39 of 94 contours are an exact copy of another is not
        hypothetical here. What makes identity enough for the label, which is
        not keyed on anything, is that ``_label`` builds a new one per call -
        so a ``Label`` belongs to exactly one piece and appears in ``labels``
        exactly once.
        """
        piece = self._pieces.pop(key, None)
        if piece is None:
            return
        # not pieces.remove(piece): list.remove takes the first element that
        # compares equal, and only checks identity per element on the way past
        # - so an earlier way drawing the same line would go instead of this
        # one, which is the whole hazard the loop below exists to avoid
        pieces = self.paths[piece.ele]
        for i, p in enumerate(pieces):
            if p is piece:
                del pieces[i]
                break
        else:
            # _add_way writes both and this pops _pieces first, so the two
            # cannot disagree - and if they ever do, the quiet failure is a
            # level that has emptied without _levels_moved being set, which
            # leaves every index contour from there up misnumbered and says
            # nothing. Loud instead
            raise AssertionError(f'{key} is in _pieces but not in paths[{piece.ele}]')
        if not pieces:
            del self.paths[piece.ele]
            self._levels_moved = True
        for i, lab in enumerate(self.labels):
            if lab is piece.label:
                del self.labels[i]
                break
        else:
            # the same disagreement as above and just as quiet: a label left
            # behind is drawn at a level with no piece under it
            raise AssertionError(f'{key} has a label that is not in labels')

    def _reindex(self) -> None:
        """Every fifth level is an index contour, counted over the levels that
        are drawn - so a level appearing or emptying moves the rest, and
        nothing else does. Called on an edit only when one of those happened:
        sorting every drawn level is small against re-projecting 723 ways, but
        it is still a cost that grows with the working set, which is the shape
        this whole change is for."""
        self.index_levels = set(sorted(self.paths)[::INDEX_EVERY_N])

    def _ensure_arrays(self):
        """The flat arrays, if an edit has been made since they were last
        built.

        Nothing in ``paint`` reads them - they are for picking a contour, a
        node, or the crossings a prospective segment would make - so building
        them when an edit arrives spends 14.5 ms of every edit on an answer
        that is usually asked for later, or never. Drawing a contour node by
        node paid it once per node and used it on none of them."""
        if self._arrays_stale:
            self._rebuild_arrays()
            self._arrays_stale = False

    def _rebuild_arrays(self):
        """The flat segment and node arrays, from the per-way geometry.

        Always replaced: a set with no contours after one with many must not
        leave the old segments behind for pick to find.

        Built with one vectorised operation per array rather than one small
        array per way. The per-way form cost 136 ms on the gobras 3x3 - paid on
        every edit, since an edit to one way rebuilds all of them - of which
        almost none was the concatenation: it was six thousand calls to
        ``np.full`` and ``np.arange``, and a Python loop over all 342,000 points
        to build the node index."""
        empty = np.zeros((0, 2))
        self._ways = [g for g in self._geoms.values() if g.ele is not None]
        # a projected way always has two points or more, so every count is >= 1
        counts = np.array([len(g.pts) - 1 for g in self._ways], dtype=np.int64)
        if not len(counts):
            self._seg_a = self._seg_b = empty
            self._seg_ele = np.zeros(0)
            self._seg_way = np.zeros(0, dtype=np.int64)
            self._seg_i = np.zeros(0, dtype=np.int64)
        else:
            self._seg_a = np.concatenate([g.pts[:-1] for g in self._ways])
            self._seg_b = np.concatenate([g.pts[1:] for g in self._ways])
            self._seg_ele = np.repeat(np.array([g.ele for g in self._ways], dtype=float), counts)
            self._seg_way = np.repeat(np.arange(len(self._ways), dtype=np.int64), counts)
            # the per-way 0..n-1 ramp, without a per-way arange: a running
            # index minus where each way starts
            starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
            self._seg_i = np.arange(counts.sum(), dtype=np.int64) - np.repeat(starts, counts)
        geoms = list(self._geoms.values())                # contours and coastlines both
        pts = [g.pts for g in geoms if len(g.pts)]
        self._node_xy = np.concatenate(pts) if pts else empty
        self._node_ref = list(chain.from_iterable(g.node_ref for g in geoms if len(g.pts)))

    @staticmethod
    def _label(ele: float, pts: list[tuple[float, float]]) -> Label:
        """Midpoint by length, and the bearing there, turned upright."""
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(pts)]
        total = sum(seg)
        half, run = total / 2.0, 0.0
        for (a, b), d in zip(pairwise(pts), seg, strict=True):
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
        self._ensure_arrays()
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
        self._ensure_arrays()
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
        self._ensure_arrays()
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
        # all three together, before the early returns: drawn_ways was reset
        # further down and kept last paint's count whenever this returned
        # early, so below ZOOM_INDEX it reported ways drawn while
        # drawn_levels correctly reported none
        self.drawn_levels = self.drawn_labels = self.drawn_ways = 0
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
        self._paint_water(painter, rect)
        for ele in sorted(self.paths):
            index = self.is_index(ele)
            if zoom < ZOOM_ALL and not index:
                continue
            # the rectangle is each way's own. A level's ways joined into one
            # path have a rectangle that spans the working set, and culling by
            # it culls nothing - see _Piece
            visible = [piece for piece in self.paths[ele] if piece.rect.intersects(rect)]
            if not visible:
                continue
            pen = QPen(self.colour(ele), 1.8 if index else 1.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            for piece in visible:
                painter.drawPath(piece.path)
            self.drawn_ways += len(visible)
            self.drawn_levels += 1
        if self.active is not None and self.active in self.paths and zoom >= ZOOM_INDEX:
            # the level being drawn at, over everything: the mapper needs to
            # see where it already runs
            active = [piece for piece in self.paths[self.active] if piece.rect.intersects(rect)]
            if active:
                pen = QPen(self.colour(self.active).darker(120), 3.2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                for piece in active:
                    painter.drawPath(piece.path)
        self._paint_spots(painter, rect, scale, zoom)
        if zoom >= ZOOM_LABELS:
            self._paint_labels(painter, rect, scale, zoom)

    def _paint_water(self, painter: QPainter, rect: QRectF):
        """The water, under the contours.

        One colour for all of it rather than the ramp's, because none of it
        has an elevation to take one from - that is G6's, and until then a
        river is where the valley floor is and not how high. Under, because it
        is the context a contour is drawn against and not the work: a mapper
        following a stream wants to see the line they are drawing on top.
        """
        self.drawn_water = 0
        if not self.water:
            return
        pen = QPen(WATER, 1.4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for piece in self.water.values():
            if piece.rect.intersects(rect):
                painter.drawPath(piece.path)
                self.drawn_water += 1

    def _paint_spots(self, painter: QPainter, rect: QRectF, scale: float, zoom: float):
        """The spot heights: a ring in the elevation's own colour, and the
        value beside it once there is room for it.

        From ``ZOOM_SPOTS`` up, and not with the index contours. They were
        drawn at every zoom this layer draws at first, on the argument that a
        spot height is not a level - there is one of it - so hiding it with the
        intermediate contours would hide the only thing that says how high a
        hill goes. That is still true about *levels* and was the wrong
        conclusion about *zooms*: a working set holds a spot height per
        hilltop, and at z8 to z11 they are a scatter of dots over index
        contours too coarse to place them against.

        In pixels, not scene units: a marker that scales with the zoom is a dot
        at z12 and a blot at z19, and what it marks is a point either way.
        """
        self.drawn_spots = 0
        if not self.spots or zoom < ZOOM_SPOTS:
            return
        font = QFont()
        font.setPointSize(FONT_PT)
        for spot in self.spots.values():
            if not rect.contains(QPointF(spot.x, spot.y)):
                continue
            colour = self.colour(spot.ele)
            painter.save()
            painter.translate(spot.x, spot.y)
            # undoing the view's scale is what makes the radius below a count
            # of device pixels. It is not redundant beside the cosmetic pens:
            # those fix the stroke width, this fixes the size of the thing
            # being stroked
            painter.scale(1.0 / scale, 1.0 / scale)
            pen = QPen(QColor(255, 255, 255, 220), 3.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(0, 0), SPOT_PX, SPOT_PX)
            pen = QPen(colour.darker(130), 1.8)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(colour)
            painter.drawEllipse(QPointF(0, 0), SPOT_PX, SPOT_PX)
            if zoom >= ZOOM_LABELS:
                tp = self._text_path(f'{spot.ele:g}', font)
                painter.translate(SPOT_PX + 3.0, 4.0)
                painter.setPen(QPen(QColor(255, 255, 255, 220), 3.0))
                painter.drawPath(tp)
                painter.fillPath(tp, colour.darker(150))
            painter.restore()
            self.drawn_spots += 1

    def pick_spot(self, x: float, y: float, tolerance: float, zoom: float):
        """The nearest spot height within ``tolerance``, as (square, node id,
        distance), or None.

        Nothing below ``ZOOM_SPOTS``, where they are not drawn. The rule lives
        here rather than at the call site so that picking cannot drift from
        painting: a click that selects something invisible is worse than one
        that selects nothing, because the next keystroke goes somewhere the
        mapper cannot see.
        """
        if zoom < ZOOM_SPOTS:
            return None
        best = None
        for spot in self.spots.values():
            d = math.hypot(spot.x - x, spot.y - y)
            if d <= tolerance and (best is None or d < best[2]):
                best = (spot.square, spot.node_id, d)
        return best

    def _text_path(self, text: str, font: QFont) -> QPainterPath:
        """The outline of a label's text, centred on the origin, kept.

        ``addText`` turns a string into glyph outlines, and there are only as
        many distinct strings as there are elevations - 72 on the gobras 3x3
        against 86 labels in one window of it, the same ones again on every
        repaint. The font and the centring depend on nothing else, so the path
        is built once per string.

        Keyed on the string *and the font*. ``FONT_PT`` is a module constant,
        but ``QFont()`` is not: it resolves to the application's default
        family, which a theme or a display can change under a running editor,
        and an outline cached before that would be served after it with no way
        to evict it - the cache is deliberately not cleared between working
        sets. ``QFont.key()`` is what makes that impossible rather than
        unlikely.

        The zoom is not in the key and does not need to be: the path is built
        at one size and ``_paint_labels`` scales the *painter* by the
        reciprocal of the view's scale, so one outline is right at every
        zoom.

        Worth less than it looks: labels went from 9.2 ms of a zoom-13 repaint
        to 7.3, not to nothing. Building the outline is the smaller half of
        drawing a label; the larger is stroking a three-wide halo around it and
        then filling it, and that is per label wherever the path came from.
        """
        key = (text, font.key())
        path = self._text.get(key)
        if path is None:
            path = QPainterPath()
            path.addText(QPointF(0, 0), font, text)
            box = path.boundingRect()
            path.translate(-box.width() / 2, box.height() / 2 - 1)
            self._text[key] = path
        return path

    def _paint_labels(self, painter: QPainter, rect: QRectF, scale: float, zoom: float):
        # one font per paint, not one per label: it is the cache's key as well
        # as what builds the outline
        font = QFont()
        font.setPointSize(FONT_PT)
        halo = QPen(QColor(255, 255, 255, 220), 3.0)
        halo.setCosmetic(True)
        for lab in self.labels:
            if lab.length * scale < MIN_LABEL_PX or not rect.contains(QPointF(lab.x, lab.y)):
                continue
            if zoom < ZOOM_ALL and not self.is_index(lab.ele):
                continue
            tp = self._text_path(f'{lab.ele:g}', font)
            painter.save()
            painter.translate(lab.x, lab.y)
            painter.rotate(lab.angle)
            painter.scale(1.0 / scale, 1.0 / scale)      # pixels, whatever the zoom
            painter.setPen(halo)
            painter.drawPath(tp)
            painter.fillPath(tp, self.colour(lab.ele).darker(130))
            painter.restore()
            self.drawn_labels += 1
