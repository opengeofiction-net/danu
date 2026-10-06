"""The drawing tools - R13, R15, R16 and R17 on screen.

Two tools over the map. **Draw** puts down a contour at the active elevation
one click at a time, continues an existing one when the first click lands on
its end, and snaps to the nodes of contours and coastlines within reach.
**Select** picks a node or a way, drags a node, inserts one with a double
click on a segment, and deletes with the key. Every change is a command from
``danu.core.edits`` on one history over the working set, so undo and redo
walk back through drawing and selecting alike.

Crossing (R16) is warned live - the rubber band turns red and the status line
says which contour - and refused on the click. A node snapped from another
square is a position, not a shared node: each square is its own file and a
way cannot reference a node in another.

The tools hold state and issue commands; the ``EditOverlay`` draws the rubber
band, the snap mark and the selection; the window owns the menu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import pairwise

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..core import edits, geometry, profile
from ..core.chains import LINE_KINDS, Network, component, free_end_side, node_key
from ..core.ladder import format_ele
from ..core.square import Relation, Square, Way, WorkingSet, parse_ele
from ..water import flatten
from ..water.overpass import flows
from . import mercator as m
from .contours import ContourLayer, water_feature, water_tags
from .mapview import MapView, visible_rect

SNAP_PX = 10.0                  # a node this close is the one meant
FINISH_PX = 24.0                # and this close, when a redraw is being finished on its contour
PICK_PX = 8.0                   # a way this close is the one meant
DRAG_PX = 3.0                   # a press that moves less is a click
FAST_PX = 4.0                   # a held button that travels this far is drawing, not clicking
SIMPLIFY_PX = 2.0               # a fast-drawn stroke is simplified to within this of itself on release


@dataclass
class Selection:
    """What is selected: a way, a node of one, a spot height, or a relation.

    A spot height is the one with no way, since it belongs to none - so every
    reader of ``way`` has to ask, and ``spot`` is the question. That is the
    whole of what R36 costs the selection: a node that is its own constraint
    rather than a vertex of something."""
    square: Square
    way: Way | None
    node: int | None = None
    # a relation, chosen from the gone-from-upstream dock - G5c. A lake is a
    # relation and not one of its rings, and deleting it has to mean the lake.
    # Nothing on the map selects one: a click lands on a line, and which of
    # the relations naming that line was meant is not something a click says
    relation: Relation | None = None

    @property
    def spot(self) -> bool:
        """A node selected with no way around it.

        Which is a spot height by convention rather than by construction: it
        answers *is there no way, but a node* and is read as *is this a spot
        height*. A relation selection is the other way-less case - G5c's, from
        the gone dock - and it says what it is, as this asked a third case to:
        ``relation`` is set and ``node`` is not, so this stays False for it.
        Readers that act on a selection ask ``relation`` first.
        """
        return self.way is None and self.node is not None


@dataclass(frozen=True)
class Issue:
    """One thing a grade found and says - G6d-3: a span it left ungraded,
    or a gap it walked across. Each has its place, so the panel's list and
    the profile can take the map to it rather than leave a mapper to search
    for a coordinate."""
    kind: str                 # 'side', 'gap', 'climb' or 'far'
    text: str
    path: tuple               # scene points: the span, or the one point of a gap
    span: tuple | None = None  # (d0, d1) along the profile, when on the stem it shows


ISSUE_ORDER = {'side': 0, 'gap': 1, 'climb': 2, 'far': 3}
# said when a flattened lake's new level is carried to its outline and fill
# lines; its contours were clipped against the old one
_FOLLOW = ' - its outline and fill lines follow; F flattens it again to redo its contours'
# on the map, and lighter in the profile: a climb is a fault, red; ground no
# contour reaches is only unknown, grey
ISSUE_PEN = {'climb': QColor(200, 30, 30, 200), 'far': QColor(110, 110, 110, 200)}


def _path(points) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(*pt)
    return path


def _point_at(scene, dist, d):
    """The scene point ``d`` metres along a run of points."""
    for (a, da), (b, db) in pairwise(zip(scene, dist, strict=True)):
        if da <= d <= db:
            t = 0.0 if db == da else (d - da) / (db - da)
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return scene[0] if d <= dist[0] else scene[-1]


def span_issues(label, scene, dist, rejected, upstream, shown) -> list:
    """The spans a grade left ungraded, told apart: a climb is the contours
    and the river disagreeing, which is a fault in one or the other; a long
    span is ground nobody contoured - the lowland run of a river, mostly."""
    out = []
    for d0, d1, e0, e1 in rejected:
        run = [_point_at(scene, dist, d0)]
        run += [pt for pt, x in zip(scene, dist, strict=True) if d0 < x < d1]
        run.append(_point_at(scene, dist, d1))
        lo, hi = min(e0, e1), max(e0, e1)
        if e0 > e1 if upstream else e1 > e0:
            kind = 'climb'
            text = (f'{label}: the contours climb from {lo:g} to {hi:g} m going downstream '
                    '- left ungraded')
        else:
            kind = 'far'
            text = (f'{label}: {(d1 - d0) / 1000:.1f} km between the {hi:g} and {lo:g} m '
                    f'contours, over {profile.MAX_SEGMENT_M / 1000:g} km - left ungraded')
        out.append(Issue(kind, text, tuple(run), (d0, d1) if shown else None))
    return out


def gap_issue(kind, label, gap_m, lon, lat) -> Issue:
    """A gap walked across - ``side`` for a tributary short of its river's
    side, ``gap`` for one between two ways end to end."""
    if kind == 'side':
        what = ('ends on its river without a node they share' if gap_m < 0.05
                else f'stops {gap_m:g} m short of the river it joins')
    else:
        what = ('two nodes on one spot between its ways, not merged' if gap_m < 0.05
                else f'a {gap_m:g} m gap between its ways')
    return Issue(kind, f'{label}: {what}, at {lat:.5f}, {lon:.5f} - a mapping error, '
                 'to join upstream', (m.lonlat_to_scene(lon, lat),))


@dataclass
class Proposal:
    """A grade worked out and not yet applied - G6b. R24 asks for an
    elevation "from the contours it touches", and the spec for it shown
    before it lands: this is what is shown, and Accept is one step.

    Dropped by any edit and by any change of selection: it was worked out
    against the square as it was, for the feature that was selected.
    """
    square: Square
    feature: object                       # the Way or Relation it is for
    # what Accept does, as one step: a lake's, which is in one square. A
    # river's is ``steps`` below, since a chain may span squares - a proposal
    # carries one or the other, never both
    command: object
    summary: str
    # a river's profile, for the panel to draw - metres along it, and per
    # vertex the level proposed and the level it has now
    dist: list | None = None
    levels: list | None = None
    current: list | None = None
    known: list | None = None             # (metres, contour) where one crosses
    rejected: list | None = None          # (d0, d1, e0, e1) spans left ungraded
    # for the map: each proposed level at its place, and each rejected span
    preview: list | None = None
    # what the grade found and says, each with its place: spans left ungraded,
    # gaps walked across - for the panel's list and the map (G6d-3)
    issues: list | None = None
    # a chain's (G6d): what Accept does when the grade spans squares - one
    # step on the history across them - and the ways of the chain and the gaps
    # it was walked across, for the map
    steps: list | None = None
    chain_paths: list | None = None
    # a flatten's (G7a): the contours it takes out of the water and back from
    # its shore, as scene runs, the fill lines it lays across it, and how far
    # it draws the contours back
    removed: list | None = None
    fill: list | None = None
    pull_back_m: float | None = None
    joins: list | None = None             # (scene x, y, gap metres)

    @property
    def acceptable(self) -> bool:
        return self.command is not None or bool(self.steps)


class EditController(QObject):
    """The tools, the history and the selection, over one working set."""

    edited = Signal()                # after any command, undo or redo
    editedWays = Signal(object, object, object)   # and which ways and spot heights, in which
                                                  # square, for the preview
    message = Signal(str)            # for the status line
    toolChanged = Signal(str)
    # whenever the selection is set, to anything - the selection panel's cue.
    # Emitted on every assignment rather than on a change, because telling a
    # change means comparing Selections, and a Selection's dataclass equality
    # compares its Square, which is every node and way in it
    selectionChanged = Signal()
    proposalChanged = Signal()       # a grade proposed, accepted or dropped
    placeAsked = Signal(float, float, float, float)   # west, south, east, north: show it
    flattened = Signal(object, object)                # square, lake: a flatten accepted

    def __init__(self, view: MapView, layer: ContourLayer, elevation, parent=None):
        super().__init__(parent)
        self.view, self.layer, self.elevation = view, layer, elevation
        self.history = edits.SetUndoStack()
        self.working_set: WorkingSet | None = None
        self.overlay = EditOverlay(self)
        view.scene().addItem(self.overlay)
        self.tool = 'select'
        self._selection: Selection | None = None
        self.proposal: Proposal | None = None
        self.focused_issue: Issue | None = None   # the one the map was last taken to
        self.pull_back_m = flatten.PULL_BACK_M        # how far a flatten draws contours back
        # where contours cross, for the map to mark while the checks panel is
        # open (G8a): scene points, and those of the row chosen
        self.marks: list = []
        self.marks_focus: list = []
        # a proposal is of the square as it was and the feature then selected
        self.selectionChanged.connect(self._drop_proposal)
        self.edited.connect(self._drop_proposal)
        # drawing
        self.drawing: tuple[Square, int, bool] | None = None      # square, way id, at the end
        self.pending: tuple[Square, int | None, tuple[float, float]] | None = None   # first click
        self.cursor: tuple[float, float] | None = None           # scene
        self.snap: tuple[Square, int, float, float] | None = None  # square, node, x, y
        self.crossing: list = []
        # a fast draw: the button held and dragged
        self._stroke: list[tuple[float, float]] | None = None
        self._press_added = False            # the press put a node down that a dropped stroke should take back
        # the contour a redraw began on, whose crossings do not block: the
        # stretch being redrawn goes when the new one lands, so a line that
        # cuts across a wiggle is refused on what results, not on every click
        self.redraw_origin: tuple[Square, int] | None = None
        # dragging a node
        self._press: QPointF | None = None
        self._drag: tuple[Square, int, tuple[float, float]] | None = None    # square, node, before (lon, lat)
        self._dragged = False
        # carrying a whole contour - shift and drag (G8b): square, way, where
        # the press was, and the contour as it would be, in scene points
        self._carry: tuple[Square, Way, QPointF] | None = None
        self.ghost: list | None = None
        view.tool = self

    @property
    def selection(self) -> Selection | None:
        return self._selection

    @selection.setter
    def selection(self, value: Selection | None) -> None:
        # a property so that the twenty-odd places that set it say so without
        # each having to remember to
        self._selection = value
        self.selectionChanged.emit()

    # ------------------------------------------------------------ setup
    def set_working_set(self, ws: WorkingSet | None):
        self.working_set = ws
        self.history = edits.SetUndoStack()
        self.selection = None
        self._stop_drawing()
        self.edited.emit()

    def set_tool(self, name: str):
        if name not in ('select', 'draw', 'spot'):
            raise ValueError(name)
        if name != self.tool:
            self._stop_drawing()
            self.tool = name
            self.view.setDragMode(MapView.DragMode.ScrollHandDrag if name == 'select' else MapView.DragMode.NoDrag)
            self.view.viewport().setCursor(Qt.CursorShape.ArrowCursor if name == 'select'
                                           else Qt.CursorShape.CrossCursor)
            self.toolChanged.emit(name)
            self.overlay.update()

    def _px(self, px: float) -> float:
        return px / m.scale_for_zoom(self.view.zoom)

    # ---------------------------------------------------------- history
    def do(self, square: Square, cmd: edits.Command):
        self.history.do(square, cmd)
        ways, spots = cmd.ways(square), cmd.spots(square)
        self.layer.refresh(square, ways)
        self.layer.refresh_spots(square, spots)
        self.editedWays.emit(square, ways, spots)
        self.edited.emit()

    def undo(self):
        self._history_move(self.history.undo_across(), 'undid')

    def redo(self):
        self._history_move(self.history.redo_across(), 'redid')

    def do_across(self, steps) -> None:
        """A step that spans squares, done forward - the import's path onto
        the history, and the same path back off it that undo takes.

        It used to be written out again in the window, which was the same
        three lines minus ``_after_history_move``. That was harmless while an
        import only added: nothing under the selection could vanish, so there
        was nothing to clear. G5's reconciliation replaces superseded features,
        which means deleting ways, and then the forward path would leave a
        selection pointing at a way no longer in the square while the undo
        path cleared it. One entry point, so the two cannot differ.
        """
        steps = list(steps)
        if not steps:
            return
        self.history.do_across(steps)
        self._refresh_step(steps)

    def _refresh_step(self, step) -> None:
        for square, cmd in step:
            ways, spots = cmd.ways(square), cmd.spots(square)
            self.layer.refresh(square, ways)
            self.layer.refresh_spots(square, spots)
            self._after_history_move(square, ways, spots)

    def _history_move(self, step, verb: str):
        """One step off the history, or back on, however many squares it
        touched. An import lands in up to nine files at once and comes back
        the same way - R40 asks for one undoable step and this is where that
        stops being one square's business."""
        if not step:
            return
        self._refresh_step(step)
        self.message.emit(f'{verb} {step[0][1].describe()}')

    def _after_history_move(self, square: Square, ways=(), spots=()):
        if ways or spots:
            self.editedWays.emit(square, ways, spots)
        if self.drawing and (self.drawing[0] is square) and self.drawing[1] not in square.ways:
            self.drawing = None                      # the way being drawn was undone away
        if (self.selection and self.selection.relation is not None
                and self.selection.relation.id not in self.selection.square.relations):
            self.selection = None
        elif self.selection and self.selection.way is not None and self.selection.way.id not in self.selection.square.ways:
            self.selection = None
        elif self.selection and self.selection.node is not None and self.selection.node not in self.selection.square.nodes:
            # a spot height undone away is nothing at all; a node of a way is
            # the way with no node picked
            self.selection = None if self.selection.spot else replace(self.selection, node=None)
        self.overlay.update()
        self.edited.emit()

    def dirty(self) -> bool:
        return bool(self.history.dirty_squares())

    # ------------------------------------------------------------ events
    # each returns True when it consumed the event
    def mouse_press(self, event, pos: QPointF) -> bool:
        if self.working_set is None:
            return False
        if self.tool == 'draw':
            if event.button() == Qt.MouseButton.LeftButton:
                added = self._draw_click(pos)
                # if the button stays down and travels, the rest is a stroke
                self._stroke = [(pos.x(), pos.y())] if (self.drawing or self.pending) else None
                self._press_added = added
                return True
            if event.button() == Qt.MouseButton.RightButton:
                self.finish_line()
                return True
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self.tool == 'spot':
            self._place_spot(pos)
            return True
        # a spot height first: it is a few pixels across and sits on ground a
        # contour runs through, so a click that could mean either means the
        # small thing. Shift is the line, as below, and skips this too
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            hit = self.layer.pick_spot(pos.x(), pos.y(), self._px(SNAP_PX), self.view.zoom)
            if hit is not None:
                square, nid, _ = hit
                self.selection = Selection(square, None, nid)
                self.elevation.pick_up(self.layer.spots[(square.name, nid)].ele)
                n = square.nodes[nid]
                self._drag = (square, nid, (n.lon, n.lat))
                self._press = pos
                self._dragged = False
                self.overlay.update()
                return True
        # shift means the line, not a node of it. A contour's nodes are some
        # 87 m apart in Gobras, which is under the snap radius at every zoom
        # that shows a whole contour, so without this the way itself could
        # only be selected by zooming in past seeing it
        whole = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        node = None if whole else self.layer.pick_node(pos.x(), pos.y(), self._px(SNAP_PX))
        if node is not None:
            square, nid, _ = node
            way = self._way_holding(square, nid)
            if way is not None:
                self.selection = Selection(square, way, nid)
                self.elevation.pick_up(way.ele)          # selecting is picking up, as space does
                n = square.nodes[nid]
                self._drag = (square, nid, (n.lon, n.lat))
                self._press = pos
                self._dragged = False
                self.overlay.update()
                return True
        if whole and self._on_selected_contour(pos):
            # the contour already selected - from the checks panel, as a rule
            # - is the one carried, though another runs nearer the press: in
            # a massif's thirty contours a press is near several (G8b)
            sel = self.selection
            self._carry = (sel.square, sel.way, pos)
            self.ghost = None
            return True
        hit = self.layer.pick(pos.x(), pos.y(), self._px(PICK_PX))
        wet = self.layer.pick_water(pos.x(), pos.y(), self._px(PICK_PX))
        # the nearer of the two. A river runs down the valley a contour bends
        # round, and contour-first would leave it unselectable at every zoom
        # that shows both
        if wet is not None and (hit is None or wet[2] < hit[2]):
            self._select_water(wet, whole)
            return True
        if hit is not None:
            self.selection = Selection(hit[0], hit[1])
            self.elevation.pick_up(hit[1].ele)
            if whole:
                # shift is the line; shift and a drag carries it - a contour
                # whose shape is right and whose place is not (G8b)
                self._carry = (hit[0], hit[1], pos)
                self.ghost = None
            self.overlay.update()
            return True
        if self.selection is not None:
            self.selection = None
            self.overlay.update()
        return False                                 # the view pans

    def _select_water(self, wet, whole: bool) -> None:
        """A click on water - G6a. A lake, when the line is its ring; a
        point on a river, when the click is on one of its vertices, since
        that is where a river's level lives (decision 1); otherwise the way.
        Shift is the whole line, as it is for a contour.

        No drag. Upstream owns where water is - G5a - and a vertex moved here
        goes back on the next import, so offering to move one would offer an
        edit that does not last."""
        square, way, _, vid, vdist = wet
        feature = water_feature(square, way)
        if isinstance(feature, Relation):
            self.selection = Selection(square, None, relation=feature)
            ele = feature.ele
        elif not whole and not way.closed and vdist <= self._px(SNAP_PX):
            self.selection = Selection(square, way, vid)
            ele = parse_ele(square.nodes[vid].tags.get('ele')) if vid in square.nodes else None
        else:
            self.selection = Selection(square, way)
            ele = way.ele
        if ele is not None:
            self.elevation.pick_up(ele)              # selecting is picking up, as for a contour
        self.overlay.update()

    def mouse_move(self, event, pos: QPointF) -> bool:
        self.cursor = (pos.x(), pos.y())
        if self.working_set is None:
            return False
        if self.tool == 'draw':
            if self._stroke is not None and event.buttons() & Qt.MouseButton.LeftButton:
                last = self._stroke[-1]
                if abs(pos.x() - last[0]) + abs(pos.y() - last[1]) >= self._px(FAST_PX):
                    self._stroke.append((pos.x(), pos.y()))
            self._update_snap(pos)
            self._update_crossing()
            self.overlay.update()
            return True
        if self._carry is not None and event.buttons() & Qt.MouseButton.LeftButton:
            square, way, start = self._carry
            if self.ghost is None and (pos - start).manhattanLength() < self._px(DRAG_PX):
                return True
            dx, dy = pos.x() - start.x(), pos.y() - start.y()
            self.ghost = [(x + dx, y + dy) for x, y in
                          (self.layer.node_xy(square, r) for r in way.refs if r in square.nodes)]
            self.overlay.update()
            return True
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if not self._dragged and (pos - self._press).manhattanLength() < self._px(DRAG_PX):
                return True
            self._dragged = True
            square, nid, _ = self._drag
            lon, lat = m.scene_to_lonlat(pos.x(), pos.y())
            n = square.nodes[nid]
            n.lon, n.lat = lon, lat
            self.layer.refresh(square, self._ways_holding(square, nid))
            self.overlay.update()
            return True
        return False

    def mouse_release(self, event, pos: QPointF) -> bool:
        if self._carry is not None:
            carry, self._carry = self._carry, None
            ghost, self.ghost = self.ghost, None
            if ghost is not None:
                self._put_down(*carry, pos)
            self.overlay.update()
            return True
        if self._stroke is not None:
            stroke, self._stroke = self._stroke, None
            if len(stroke) > 1:
                self._fast_draw(stroke)
                return True
        if self._drag is None:
            return False
        square, nid, before = self._drag
        self._drag = None
        if not self._dragged:
            return True
        n = square.nodes[nid]
        after = (n.lon, n.lat)
        bad = self._node_crossings(square, nid)
        if bad:
            n.lon, n.lat = before                  # R16: refused on commit, put back
            self.layer.refresh(square, self._ways_holding(square, nid))
            self.message.emit('not moved: ' + self._describe_crossing(bad))
            self.overlay.update()
            return True
        n.lon, n.lat = before                      # the command does the move, so undo has it exact
        self.do(square, edits.MoveNode(nid, before, after))
        self.message.emit(self._moved_what())
        return True

    def _on_selected_contour(self, pos: QPointF) -> bool:
        """Whether a press lands on the contour selected whole."""
        sel = self.selection
        if (sel is None or sel.way is None or sel.node is not None or sel.relation is not None
                or sel.way.id not in sel.square.ways or sel.way.ele is None
                or (sel.square.name, sel.way.id) in self.layer.water):
            return False
        pts = np.array([self.layer.node_xy(sel.square, r) for r in sel.way.refs if r in sel.square.nodes])
        if len(pts) < 2:
            return False
        _, dist = geometry.nearest_point_on_segments((pos.x(), pos.y()), pts[:-1], pts[1:])
        return float(dist.min()) <= self._px(PICK_PX)

    def _put_down(self, square: Square, way: Way, start: QPointF, pos: QPointF) -> None:
        """The contour carried, put where the drag ended - G8b.

        R16 asked of the move, not of the contour: refused if it would cross
        a contour it does not cross already, and otherwise done, saying what
        it still crosses. A contour drawn in the wrong place crosses its
        neighbours there, and the first drag towards the right place need not
        land it - refusing every move that left a crossing would ask for one
        perfect drag. One that makes a crossing that was not there is a move
        the wrong way."""
        dx, dy = pos.x() - start.x(), pos.y() - start.y()

        def move(lon, lat):
            x, y = m.lonlat_to_scene(lon, lat)
            return m.scene_to_lonlat(x + dx, y + dy)
        key = (square.name, way.id)
        here = [self.layer.node_xy(square, r) for r in way.refs if r in square.nodes]
        there = [(x + dx, y + dy) for x, y in here]
        before = self.layer.crossed_by(here, skip=key)
        after = self.layer.crossed_by(there, skip=key)
        new = after - before
        name = f'the {format_ele(way.ele)} m contour'
        if new:
            sq_name, wid = sorted(new, key=str)[0]
            other = self.working_set.squares[sq_name].ways.get(wid)
            what = f'the {format_ele(other.ele)} m contour' if other is not None else f'way {wid}'
            self.message.emit(f'not moved: {name} would cross {what}, which it does not cross now'
                              + (f', and {len(new) - 1} more' if len(new) > 1 else ''))
            return
        cmd = edits.translate_way(square, way.id, move, self.history.alloc(square))
        self.do(square, cmd)
        (lon0, lat0), (lon1, lat1) = (m.scene_to_lonlat(start.x(), start.y()),
                                      m.scene_to_lonlat(pos.x(), pos.y()))
        metres = math.hypot((lon1 - lon0) * 111320 * math.cos(math.radians(lat0)),
                            (lat1 - lat0) * 110540)
        said = f'moved {name} {metres:,.0f} m'
        if cmd.copies:
            said += f'; it came away from {len(cmd.copies)} node{"s" * (len(cmd.copies) != 1)} it shared'
        said += (f'; it still crosses {len(after)} contour{"s" * (len(after) != 1)}' if after
                 else '; it crosses nothing now')
        self.message.emit(said)

    def _moved_what(self) -> str:
        sel = self.selection
        if sel is not None and sel.spot:
            spot = self.layer.spots.get((sel.square.name, sel.node))
            return f'moved the {format_ele(spot.ele)} m spot height' if spot else 'moved a spot height'
        if sel is not None and sel.way is not None and sel.way.ele is not None:
            return f'moved a node of the {format_ele(sel.way.ele)} m contour'
        return 'moved a node'

    def _place_spot(self, pos: QPointF) -> None:
        """A spot height at the active elevation, where the click landed.

        R37: the only thing that can say how high a hill goes, since its
        contours can only bracket it. So the elevation this takes is the one
        the panel is holding - the mapper sets the height and then says where
        - and an off-ladder value is expected rather than suspect here, which
        is what a summit is.
        """
        lon, lat = m.scene_to_lonlat(pos.x(), pos.y())
        square = self.working_set.at(lon, lat) if self.working_set else None
        if square is None:
            self.message.emit('outside the working set')
            return
        ele = self.elevation.value
        nid = self.history.alloc(square).take()
        self.do(square, edits.AddNode(nid, (lon, lat), {'ele': format_ele(ele)}))
        self.selection = Selection(square, None, nid)
        self.message.emit(f'spot height at {format_ele(ele)} m')
        self.overlay.update()

    def mouse_double_click(self, event, pos: QPointF) -> bool:
        if self.working_set is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        if self.tool == 'draw':
            self.finish_line()
            return True
        if self.layer.pick_node(pos.x(), pos.y(), self._px(SNAP_PX)) is not None:
            return True                              # a node: the press selected it
        hit = self.layer.pick(pos.x(), pos.y(), self._px(PICK_PX))
        if hit is None:
            return False
        square, way, _, seg = hit
        a = self.layer.node_xy(square, way.refs[seg]); b = self.layer.node_xy(square, way.refs[seg + 1])
        ax, ay = a; bx, by = b
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((pos.x() - ax) * dx + (pos.y() - ay) * dy) / (dx * dx + dy * dy or 1.0)))
        lon, lat = m.scene_to_lonlat(ax + t * dx, ay + t * dy)
        nid = self.history.alloc(square).take()
        self.do(square, edits.InsertNode(way.id, seg + 1, nid, (lon, lat)))
        self.selection = Selection(square, way, nid)
        self.message.emit(f'inserted a node into the {format_ele(way.ele)} m contour')
        self.overlay.update()
        return True

    def key_press(self, event) -> bool:
        key = event.key()
        if self.proposal is not None and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_proposal()
            return True
        if self.proposal is not None and key == Qt.Key.Key_Escape:
            self.cancel_proposal()
            return True
        if key == Qt.Key.Key_Escape:
            if self.tool == 'draw' and (self.drawing or self.pending):
                self._stop_drawing()
            else:
                self.selection = None
                self.set_tool('select')
                self.overlay.update()
            return True
        if self.tool == 'draw' and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_line()
            return True
        if self.tool == 'draw' and key == Qt.Key.Key_Backspace and self.drawing:
            self.undo()
            return True
        return False

    # ------------------------------------------------------------- draw
    def _draw_click(self, pos: QPointF) -> bool:
        """One click of the draw tool. True when it put a command on the
        history - a node added or a way begun - so a stroke that is dropped
        can take the press's node back with it."""
        self._update_snap(pos)
        self._update_crossing()
        if self.blocking():
            self.message.emit('not drawn: ' + self._describe_crossing(self.blocking()))
            return False
        x, y = self._point(pos)
        lon, lat = m.scene_to_lonlat(x, y)
        ele = self.elevation.value
        tag = self.elevation.model.tag
        if self.drawing is None and self.pending is None:
            # the first click: onto the end of a contour at this elevation continues it
            cont = self._continuable(ele)
            if cont is not None:
                square, way, at_end = cont
                self.drawing = (square, way.id, at_end)
                self.message.emit(f'continuing the {format_ele(ele)} m contour; right click or Enter ends it')
                self.overlay.update()
                return False
            square = self.working_set.at(lon, lat)
            if square is None:
                self.message.emit('outside the working set')
                return False
            node = self.snap[1] if self.snap and self.snap[0] is square else None
            # begun on a contour at this elevation: what follows may be a redraw
            origin = self._way_at(square, node, ele) if node is not None else None
            self.redraw_origin = (square, origin.id) if origin is not None else None
            self.pending = (square, node, (lon, lat))
            self.message.emit(f'redrawing the {format_ele(ele)} m contour - end on it with Enter or a right click'
                              if origin is not None else f'drawing at {format_ele(ele)} m in {square.name}')
            self.overlay.update()
            return False
        if self.pending is not None:
            square, first, first_coord = self.pending
            alloc = self.history.alloc(square)
            wid = alloc.take()
            second = self.snap[1] if self.snap and self.snap[0] is square else None
            if second is not None and self._on_origin(square, second):
                second = None                    # not onto the contour being redrawn - see below
            cmds = []
            fresh_ids, fresh_coords = [], []
            if first is None:
                fresh_ids.append(alloc.take()); fresh_coords.append(first_coord)
            if second is None:
                fresh_ids.append(alloc.take()); fresh_coords.append((lon, lat))
            cmds.append(edits.AddWay(wid, fresh_ids, fresh_coords, {'ele': tag}))
            if first is not None:
                cmds.append(edits.ExtendWayWithExisting(wid, False, first))
            if second is not None:
                cmds.append(edits.ExtendWayWithExisting(wid, True, second))
            cmd = cmds[0] if len(cmds) == 1 else edits.Compound(cmds, f'draw {tag} m')
            self.pending = None
            self.drawing = (square, wid, True)
            self.do(square, cmd)
            self.overlay.update()
            return True
        square, wid, at_end = self.drawing
        node = self.snap[1] if self.snap and self.snap[0] is square else None
        # not onto the contour being redrawn. Drawing a new section means
        # drawing alongside the old one, and its nodes are eighty metres apart
        # in Gobras - so click after click landed on one, each ending the
        # redraw at once over a sliver of contour and starting a fresh line.
        # A redraw ends when the line does: Enter, a right click, a double
        # click, or letting go of a stroke
        if node is not None and self._on_origin(square, node):
            node = None
        way = square.ways[wid]
        if node is not None and node in way.refs and node != way.refs[0 if at_end else -1]:
            # onto its own node other than the far end: a loop, refused
            self.message.emit('a contour may not cross itself')
            return False
        if node is not None:
            self._close_onto(square, wid, at_end, node, ele)
        else:
            self.do(square, edits.ExtendWay(wid, at_end, self.history.alloc(square).take(), (lon, lat)))
            self.overlay.update()
        return True

    def _close_onto(self, square: Square, wid: int, at_end: bool, node: int, ele: float):
        """The line has come back to a node that was already there. If it
        began on the same contour, that is a redraw of the stretch between
        the two; otherwise it joins, as a shared node."""
        swap = self._section_replacement(square, wid, at_end, node)
        if swap is not None:
            cmd, target, drawn = swap
            self.do(square, cmd)
            # R16 is answered here rather than at every click: a line redrawing
            # a stretch crosses the stretch as often as not, and that crossing
            # goes with it. What has to hold is the contour that results
            bad = self._crossings_along(square, target, cmd.commands[-2].refs)
            if bad:
                self.undo()
                self.message.emit('not redrawn: the result ' + self._describe_crossing(bad))
                self._stop_drawing()
                return
            self.message.emit(f'redrew {len(cmd.commands[-2].old) - 2} nodes of the '
                              f'{format_ele(ele)} m contour as {drawn}')
            self.drawing = self.pending = None
            self.crossing = []
            self.selection = Selection(square, target)
            self.overlay.update()
            return
        self.do(square, edits.ExtendWayWithExisting(wid, at_end, node))
        if square.ways[wid].closed:
            self.message.emit(f'closed the {format_ele(ele)} m contour')
            self._stop_drawing()
            return
        self.overlay.update()

    def _fast_draw(self, stroke: list[tuple[float, float]]):
        """The button was held and dragged: the stroke, simplified to what
        a mapper would have clicked, goes on as one step. The press already
        put its first point down, so the stroke continues from there. A
        stroke that crosses anything is dropped whole and said so."""
        ele, tag = self.elevation.value, self.elevation.model.tag
        pts = geometry.simplify(stroke, self._px(SIMPLIFY_PX))[1:]   # the first is the press, already down
        # a stroke let go on an existing node ends on it, so that drawing a
        # replacement in one gesture means what the same line clicked means
        square_now = self.drawing[0] if self.drawing else (self.pending[0] if self.pending else None)
        hit = self.layer.pick_node(stroke[-1][0], stroke[-1][1], self._px(SNAP_PX))
        end_node = hit[1] if hit is not None and square_now is not None and hit[0] is square_now else None
        if end_node is not None:
            pts = pts[:-1]
        if not pts:
            if end_node is not None and self.drawing:
                self._close_onto(self.drawing[0], self.drawing[1], self.drawing[2], end_node, ele)
            return
        anchor = self._anchor()
        if anchor is None:
            return
        for p in pts:
            found = self.layer.crossings(anchor, p, ele)
            if self.redraw_origin is not None:
                sq, wid = self.redraw_origin
                found = [c for c in found if not (c[0] is sq and c[1].id == wid)]
            if found:
                if self._press_added:
                    # the press's node was the start of this stroke; it goes with it
                    self.undo()
                self.message.emit('stroke not drawn: ' + self._describe_crossing(found))
                return
            anchor = p
        coords = [m.scene_to_lonlat(x, y) for x, y in pts]
        cmds: list[edits.Command] = []
        if self.pending is not None:
            square, first, first_coord = self.pending
            alloc = self.history.alloc(square)
            wid = alloc.take()
            if first is None:                     # the press was a fresh point: it leads the way
                all_coords = [first_coord, *coords]
                cmds.append(edits.AddWay(wid, [alloc.take() for _ in all_coords], all_coords, {'ele': tag}))
            else:                                 # the press snapped onto a node: shared, at the start
                cmds.append(edits.AddWay(wid, [alloc.take() for _ in coords], coords, {'ele': tag}))
                cmds.append(edits.ExtendWayWithExisting(wid, False, first))
            self.pending = None
            self.drawing = (square, wid, True)
        else:
            square, wid, at_end = self.drawing
            alloc = self.history.alloc(square)
            for c in coords:
                cmds.append(edits.ExtendWay(wid, at_end, alloc.take(), c))
        self.do(square, edits.Compound(cmds, f'draw {len(pts)} nodes at {tag} m') if len(cmds) > 1 else cmds[0])
        self.message.emit(f'{len(pts)} nodes from a stroke of {len(stroke)}, at {tag} m')
        if end_node is not None:
            self._close_onto(square, self.drawing[1], self.drawing[2], end_node, ele)
        self.overlay.update()

    def _section_replacement(self, square: Square, wid: int, at_end: bool, node: int):
        """A line begun on a contour and brought back to it is a redraw of the
        stretch between the two points, not a second way beside it - the
        review asked for it and R13 is the place for it. Both ends must be
        nodes of one contour at the elevation being drawn at: a line that
        ends on a different contour, or on one at another level, still joins
        as it did.

        Returns the commands, the contour, and how many nodes were drawn.
        """
        temp = square.ways[wid]
        ele = temp.ele
        if ele is None or node in temp.refs or self.redraw_origin is None:
            return None
        # the contour the line began on, as recorded when it began, rather than
        # whichever way happens to hold both ends: two contours at one
        # elevation can share a node, and the wrong one would be spliced.
        # The elevation is also what keeps a coastline out of this. A way's
        # direction means nothing anywhere else, but a coastline carries the
        # land on its left and the sea on its right, so re-splicing or
        # turning one would move the sea; a coastline has no ele and can
        # never be a target
        origin_square, origin_id = self.redraw_origin
        target = origin_square.ways.get(origin_id)
        began = temp.refs[0] if at_end else temp.refs[-1]
        if (target is None or origin_square is not square or target.id == wid or target.ele != ele
                or began not in target.refs or node not in target.refs):
            return None
        run = list(temp.refs) if at_end else list(reversed(temp.refs))
        # a last point put down on top of where it joins is that node twice
        # over, and a segment of no length between them
        if len(run) > 1:
            x, y = self.layer.node_xy(square, node)
            lx, ly = self.layer.node_xy(square, run[-1])
            if math.hypot(lx - x, ly - y) < self._px(4.0):
                run.pop()
        run.append(node)                                  # from where it began to where it came back
        i, j = target.refs.index(began), target.refs.index(node)
        if i > j:
            i, j = j, i
            run.reverse()
        cmds: list[edits.Command] = []
        if target.closed:
            # two ways round a ring; the one it was drawn along is the one meant
            body = len(target.refs) - 1
            inner, outer = target.refs[i:j + 1], target.refs[j:-1] + target.refs[:i + 1]
            if self._how_far(square, run[1:-1], outer) < self._how_far(square, run[1:-1], inner):
                cmds.append(edits.RotateRing(target.id, j))
                i, j = 0, (i - j) % body
                run.reverse()
        cmds.append(edits.ReplaceSection(target.id, i, j, run))
        cmds.append(edits.DeleteWay(wid))                 # after the splice, so its nodes are not orphans
        drawn = len(run) - 2
        return edits.Compound(cmds, f'redraw {drawn} nodes of a {format_ele(ele)} m contour'), target, drawn

    def _on_origin(self, square: Square, node: int) -> bool:
        """Is this node one of the contour a redraw began on?"""
        if self.redraw_origin is None:
            return False
        sq, wid = self.redraw_origin
        way = sq.ways.get(wid)
        return sq is square and way is not None and node in way.refs

    def finish_line(self):
        """End the line. A redraw joins back to the contour it began on if
        its last node came near one - which is what the mapper was aiming at,
        rather than at a particular node of it."""
        if self.drawing is not None and self.redraw_origin is not None:
            square, wid, at_end = self.drawing
            way = square.ways.get(wid)
            sq, owid = self.redraw_origin
            origin = sq.ways.get(owid)
            if way is not None and origin is not None and way.ele is not None:
                last = way.refs[-1 if at_end else 0]
                node = self._nearest_of(sq, origin, self.layer.node_xy(square, last), self._px(FINISH_PX))
                if node is not None and node != last:
                    self._close_onto(square, wid, at_end, node, way.ele)
                    return
        self._stop_drawing()

    def _nearest_of(self, square: Square, way: Way, point: tuple[float, float], within: float) -> int | None:
        best, best_d = None, within
        for ref in way.refs:
            if ref not in square.nodes:
                continue
            x, y = self.layer.node_xy(square, ref)
            d = math.hypot(x - point[0], y - point[1])
            if d <= best_d:
                best, best_d = ref, d
        return best

    def _way_at(self, square: Square, node: int, ele: float) -> Way | None:
        """The contour at this elevation holding a node, if there is one."""
        return next((w for w in square.ways.values() if w.ele == ele and node in w.refs), None)

    def _crossings_along(self, square: Square, way: Way, refs: list[int]) -> list:
        """What a run of a way's own refs crosses, now that it is in place."""
        found: list = []
        for a, b in pairwise(refs):
            if a not in square.nodes or b not in square.nodes:
                continue
            for c in self.layer.crossings(self.layer.node_xy(square, a), self.layer.node_xy(square, b), way.ele):
                if c not in found:
                    found.append(c)
        return found

    def _how_far(self, square: Square, drawn: list[int], arc: list[int]) -> float:
        """How far what was drawn lies, on average, from a stretch of the
        contour - ends included, so the stretch is the whole polyline.

        Asked this way round, from the drawing to the stretch. The other way
        round reads zero for a stretch with no nodes between its ends, which
        is any two neighbours in the file: clicking those and drawing the long
        way round then replaced nothing at all and left the original where it
        was, which is what the review saw.
        """
        pts = np.array([self.layer.node_xy(square, r) for r in arc], dtype=float)
        if len(pts) < 2:
            return float('inf')
        a, b = pts[:-1], pts[1:]
        if not drawn:
            # nothing was drawn between the two ends, so there is nothing for a
            # stretch to be near: take the one that is shorter on the ground,
            # which is a length like the other answer rather than a node count
            return float(np.hypot(*(b - a).T).sum())
        total = 0.0
        for nid in drawn:
            _, d = geometry.nearest_point_on_segments(self.layer.node_xy(square, nid), a, b)
            total += float(d.min())
        return total / len(drawn)

    def _continuable(self, ele: float) -> tuple[Square, Way, bool] | None:
        """The contour whose end the snap is on, if it is at this elevation
        and not closed: (square, way, at the end rather than the start)."""
        if self.snap is None:
            return None
        square, nid, _, _ = self.snap
        for way in square.ways.values():
            if way.ele == ele and not way.closed and len(way.refs) >= 2:
                if way.refs[-1] == nid:
                    return square, way, True
                if way.refs[0] == nid:
                    return square, way, False
        return None

    def blocking(self) -> list:
        """The crossings that refuse a click - every one but those with the
        contour a redraw began on."""
        if self.redraw_origin is None:
            return self.crossing
        sq, wid = self.redraw_origin
        return [c for c in self.crossing if not (c[0] is sq and c[1].id == wid)]

    def _stop_drawing(self):
        self.drawing = None
        self.pending = None
        self.crossing = []
        self.redraw_origin = None
        self.overlay.update()

    def _update_snap(self, pos: QPointF):
        hit = self.layer.pick_node(pos.x(), pos.y(), self._px(SNAP_PX))
        if hit is None:
            self.snap = None
            return
        square, nid, _ = hit
        x, y = self.layer.node_xy(square, nid)
        self.snap = (square, nid, x, y)

    def _point(self, pos: QPointF) -> tuple[float, float]:
        return (self.snap[2], self.snap[3]) if self.snap else (pos.x(), pos.y())

    def _anchor(self) -> tuple[float, float] | None:
        """Where the rubber band starts: the last node drawn, or the first click."""
        if self.drawing:
            square, wid, at_end = self.drawing
            way = square.ways.get(wid)
            if way is None:
                return None
            return self.layer.node_xy(square, way.refs[-1 if at_end else 0])
        if self.pending:
            return m.lonlat_to_scene(*self.pending[2])
        return None

    def _update_crossing(self):
        a = self._anchor()
        if a is None or self.cursor is None:
            self.crossing = []
            return
        q = (self.snap[2], self.snap[3]) if self.snap else self.cursor
        self.crossing = self.layer.crossings(a, q, self.elevation.value)
        if self.blocking():
            self.message.emit(self._describe_crossing(self.blocking()))

    @staticmethod
    def _describe_crossing(found) -> str:
        square, way, proper = found[0]
        what = f'the {format_ele(way.ele)} m contour' if way.ele is not None else 'a way'
        verb = 'crosses' if proper else 'meets'
        more = f' and {len(found) - 1} more' if len(found) > 1 else ''
        return f'{verb} {what}{more} - contours may not cross'

    # ----------------------------------------------------------- select
    def delete_way(self):
        """The selected contour, whole, whether a node of it or the line is
        what was clicked - the way to be rid of a contour that should not be
        there at all."""
        sel = self.selection
        if sel is None:
            self.message.emit('nothing selected')
            return
        if sel.relation is not None:
            self._delete_relation(sel)
            return
        if sel.way is None:
            # a spot height is selected: Delete takes it, and this is the
            # action for being rid of a whole contour
            self.message.emit('that is a spot height, not a contour')
            return
        if sel.way.id not in sel.square.ways:
            self.selection = None
            self.message.emit('that contour is already gone')
            return
        nodes, what = len(sel.way.refs), format_ele(sel.way.ele) if sel.way.ele is not None else None
        self.do(sel.square, edits.DeleteWay(sel.way.id))
        self.selection = None
        self.message.emit(f'deleted the {what} m contour, {nodes} nodes' if what
                          else f'deleted a way of {nodes} nodes')
        self.overlay.update()

    def delete_selected(self):
        sel = self.selection
        if sel is None:
            self.message.emit('nothing selected')
            return
        if sel.relation is not None:
            self._delete_relation(sel)
            return
        if sel.spot:
            if sel.node not in sel.square.nodes:
                # as the contour action checks its way: DeleteNode pops the
                # node and a menu item is reachable without a history move in
                # between, so this is the difference between a message and a
                # KeyError out of a menu
                self.selection = None
                self.message.emit('that spot height is already gone')
                return
            spot = self.layer.spots.get((sel.square.name, sel.node))
            what = format_ele(spot.ele) if spot else None
            self.do(sel.square, edits.DeleteNode(sel.node))
            self.selection = None
            self.message.emit(f'deleted the {what} m spot height' if what else 'deleted a spot height')
        elif (sel.node is not None and sel.way is not None
              and (sel.square.name, sel.way.id) in self.layer.water):
            # a point on a river: Delete takes its level, not the point. The
            # vertex is upstream's and comes back on the next import - G5a -
            # where the level is the mapper's and would not
            node = sel.square.nodes.get(sel.node)
            if node is None or 'ele' not in node.tags:
                self.message.emit("no level at that point; a river's vertices are upstream's")
                return
            was = node.tags['ele']        # before the step: it replaces the tags
            after = {k: v for k, v in node.tags.items() if k != 'ele'}
            self.do(sel.square, edits.SetNodeTags(sel.node, dict(node.tags), after))
            self.message.emit(f'removed the {was} m level')
        elif sel.node is not None:
            self.do(sel.square, edits.DeleteNode(sel.node))
            self.selection = Selection(sel.square, sel.way) if sel.way.id in sel.square.ways else None
            self.message.emit('deleted a node')
        else:
            self.do(sel.square, edits.DeleteWay(sel.way.id))
            self.selection = None
            self.message.emit(f'deleted the {format_ele(sel.way.ele)} m contour' if sel.way.ele is not None else 'deleted a way')
        self.overlay.update()

    def set_level(self):
        """L: the active elevation, as the level of the selected water - R24
        by hand, G6a. Water only, as the menu says; the selection panel is
        what re-levels a contour or a spot height, through ``set_ele`` as this
        does."""
        sel = self.selection
        if sel is not None and sel.relation is None and not (
                sel.way is not None and (sel.square.name, sel.way.id) in self.layer.water):
            self.message.emit('setting a level is for water - a contour takes its level '
                              'when it is drawn')
            return
        self.set_ele(self.elevation.value)

    def set_ele(self, value: float | None) -> bool:
        """The selection's elevation set to ``value``, or cleared with None -
        the one property the selection panel edits, and what L does with the
        active elevation. Answers whether anything changed.

        - A **contour** is its elevation: setting re-levels it, the edit there
          was no way to make before; clearing is refused, since a way with no
          elevation is not a contour. A node of one is the contour.
        - A **spot height** likewise: setting moves its value, clearing is
          refused - Delete removes it.
        - A **lake** takes one level, on its relation or on its one closed way;
          clearing takes it off.
        - A **river** takes a level at a point - the vertex selected - because
          it descends; selected whole, it is asked for a point. A river area
          is refused outright: R27, flowing water is never held flat.
        """
        sel = self.selection
        if sel is None:
            self.message.emit('nothing selected')
            return False
        text = format_ele(value) if value is not None else None
        sq = sel.square

        def retagged(tags: dict) -> dict:
            if text is None:
                return {k: v for k, v in tags.items() if k != 'ele'}
            return {**tags, 'ele': text}

        def unchanged(tags: dict) -> bool:
            # the level it already has is no step on the history - so L at a
            # lake already at the active elevation, and Enter on the panel's
            # unchanged field, leave Ctrl+Z where it was
            if retagged(tags) == tags:
                self.message.emit(f'already {what}')
                return True
            return False

        what = f'{text} m' if text is not None else 'no level'
        if sel.relation is not None:
            rel = sel.relation
            if rel.id not in sq.relations:
                self.selection = None
                self.message.emit('that relation is already gone')
                return False
            name = rel.tags.get('name') or 'the lake'
            if flows(rel.tags):
                self.message.emit(f'{name} flows, so it has no one level (R27): grade it instead')
                return False
            if unchanged(rel.tags):
                return False
            after = retagged(rel.tags)
            follow = flatten.relevel(sq, rel, after.get('ele'))
            self.do(sq, edits.Compound([edits.SetRelationTags(rel.id, dict(rel.tags), after), *follow],
                                       name=f'{name}: {what}'))
            self.message.emit(f'{name}: {what}' + _FOLLOW * bool(follow))
        elif sel.spot:
            if sel.node not in sq.nodes:
                self.selection = None
                self.message.emit('that spot height is already gone')
                return False
            if value is None:
                self.message.emit('a spot height is its elevation - Delete removes it')
                return False
            node = sq.nodes[sel.node]
            if unchanged(node.tags):
                return False
            self.do(sq, edits.SetNodeTags(sel.node, dict(node.tags), retagged(node.tags)))
            self.message.emit(f'spot height: {what}')
        elif sel.way is not None and (sq.name, sel.way.id) in self.layer.water:
            way = sel.way
            name = way.tags.get('name')
            if sel.node is not None and sel.node in sq.nodes:
                node = sq.nodes[sel.node]
                if unchanged(node.tags):
                    return False
                self.do(sq, edits.SetNodeTags(sel.node, dict(node.tags), retagged(node.tags)))
                self.message.emit(f'{what} at a point on {name or "the river"}')
            elif way.closed and flows(way.tags):
                self.message.emit(f'{name or "a river area"} flows, so it has no one level '
                                  '(R27): grade it instead')
                return False
            elif flows(way.tags) or not way.closed:
                self.message.emit('a river descends, so its level is set at a point on it: '
                                  'click one of its vertices, or grade it')
                return False
            elif not water_tags(way.tags):
                self.message.emit('more than one water relation names this ring; '
                                  'the level belongs to the lake, not to its ring')
                return False
            else:
                if unchanged(way.tags):
                    return False
                after = retagged(way.tags)
                follow = flatten.relevel(sq, way, after.get('ele'))
                self.do(sq, edits.Compound([edits.SetTags(way.id, dict(way.tags), after), *follow],
                                           name=f'{name or "the lake"}: {what}'))
                self.message.emit(f'{name or "the lake"}: {what}' + _FOLLOW * bool(follow))
        elif sel.way is not None:
            if value is None:
                self.message.emit('a contour is its elevation - without one it is not a contour')
                return False
            way = sel.way
            if unchanged(way.tags):
                return False
            self.do(sq, edits.SetTags(way.id, dict(way.tags), retagged(way.tags)))
            self.message.emit(f'contour re-levelled to {what}')
        else:
            return False
        self.overlay.update()
        return True

    def grade(self):
        """G: a level from the contours, for the selected water - R24's other
        half, G6b - proposed, not applied. Enter accepts it as one step,
        Escape drops it.

        A river is graded between the contours it crosses, by distance along
        it, descending only: ``profile.grade_along``, the batch grader's rule.
        A span where the contours climb is left ungraded and said so - not
        forced down, which would invent ground nobody drew. A lake takes its
        outlet, failing that the lowest contour on its rim:
        ``ContourLayer.outlet``, the batch grader's rule again. A river area is
        refused - R27, and it is graded through the river that runs down it.
        """
        sel = self.selection
        if sel is None:
            self.message.emit('nothing selected')
            return
        sq = sel.square
        if sel.relation is not None and water_tags(sel.relation.tags):
            # R27 for a relation as for a closed way: a river area mapped as a
            # multipolygon went down the lake path and was proposed one flat
            # level, which is how the Bosco River's area got its mouth's height
            if flows(sel.relation.tags):
                self.message.emit(f'{sel.relation.tags.get("name") or "a river area"} flows, '
                                  'so it has no one level (R27): grade the river that runs '
                                  'down it')
            else:
                self._propose_lake(sq, sel.relation)
        elif sel.way is not None and (sq.name, sel.way.id) in self.layer.water:
            way = sel.way
            if way.closed and flows(way.tags):
                self.message.emit('a river area flows, so it has no one level (R27): '
                                  'grade the river that runs down it')
            elif way.closed and water_tags(way.tags):
                self._propose_lake(sq, way)
            elif way.closed:
                self.message.emit('more than one water relation names this ring; '
                                  'grade the lake, not its ring')
            else:
                self._propose_river(sq, way)
        else:
            self.message.emit('grading is for water - select a river or a lake')

    def _along_chain(self, chain):
        """A chain's vertices in one order, as (square, node id), each one's
        distance along it, and where contours cross it - the pieces end to
        end, each turned to continue the last, the distances and crossings
        carried across each link and across any gap walked."""
        seq, dist, known, offset = [], [], [], 0.0
        crossed = {(j.after, j.before): j for j in chain.joins}
        for i, link in enumerate(chain.links):
            refs, d = self.layer.along(link.square, link.way)
            if len(refs) < 2:
                continue
            cr = self.layer.crossings_of(link.square, link.way)
            length = d[-1]
            if link.backwards:
                refs, d = refs[::-1], [length - x for x in reversed(d)]
                cr = [(length - x, e) for x, e in cr]
            if i:
                j = crossed.get((chain.links[i - 1].way.id, link.way.id))
                if j is not None:
                    offset += j.gap_m              # a gap: its length is distance too
                elif seq and seq[-1][1] == refs[0]:
                    refs, d = refs[1:], d[1:]       # the node the two share, once
            seq += [(link.square, r) for r in refs]
            dist += [offset + x for x in d]
            known += [(offset + x, e) for x, e in cr]
            offset += length
        return seq, dist, sorted(set(known))

    def _propose_river(self, sq: Square, way: Way) -> None:
        """A river graded as the chain it belongs to - G6d. The ways it was
        split into, end to end, crossing gaps of up to ``chains.TOLERANCE_M``
        between free ends: the vertices in one order, the distances and the
        crossings carried across each link, one grade along the lot."""
        chain = Network(self.working_set).chain_of(sq, way)
        seq, dist, known = self._along_chain(chain)
        name = way.tags.get('name') or f'way {way.id}'
        pieces = len(chain.links)
        if len(known) < 2:
            self.message.emit(f'{name} crosses {len(known)} contour'
                              f'{"" if len(known) == 1 else "s"}'
                              + (f' along its {pieces} ways' if pieces > 1 else '')
                              + ' - not enough to grade from')
            return
        levels, rejected, upstream = profile.grade_along(known, dist)
        # to the decimetre: the build rasterises to the metre, and a level
        # interpolated to the millimetre is precision nobody measured - but a
        # metre would make a slow river a staircase
        levels = [round(v, 1) if v is not None else None for v in levels]
        current = [parse_ele(s2.nodes[r].tags.get('ele')) for s2, r in seq]
        # an imported node is one OSM node in every file that holds it - a
        # junction in two squares of the chain, or a node a contour in a third
        # square was snapped to - and its level goes into every one of them
        everywhere = list(self.working_set.squares.values())
        changes: dict = {}
        replaced = 0
        for (s2, r), lv, cur in zip(seq, levels, current, strict=True):
            if lv is None:
                continue
            text = format_ele(lv)
            for holder in ([s2] if r < 0 else [x for x in everywhere if r in x.nodes]):
                tags = holder.nodes[r].tags
                if tags.get('ele') == text or r in changes.get(holder.name, {}):
                    continue
                if holder is s2:
                    replaced += cur is not None
                changes.setdefault(holder.name, {})[r] = (dict(tags), {**tags, 'ele': text})
        steps = []
        by_name = {x.name: x for x in everywhere}
        for sq_name, ch in changes.items():
            ids = tuple(link.way.id for link in chain.links if link.square.name == sq_name)
            steps.append((by_name[sq_name], edits.SetNodeLevels(ch, ids, f'grade {name}')))
        graded = [v for v in levels if v is not None]
        # points counted as nodes, not as places along the chain: a way that
        # passes through one of its own nodes twice - Wandrasoon Creek's
        # 30384414 does - gives that node two distances and two levels, and the
        # first visit in walking order is the one written above. That is not
        # always the upstream one - the chain is walked in the direction the
        # clicked way was drawn - but the two levels lie between the same two
        # crossings, a few metres apart
        points = len({(s2.name, r) for s2, r in seq})
        levelled = len({(s2.name, r) for (s2, r), lv in zip(seq, levels, strict=True)
                        if lv is not None})
        # proposed even when nothing grades: the profile is what shows why
        parts = [f'{name}' + (f': a chain of {pieces} ways' if pieces > 1 else '')
                 + f', {len(known)} crossings, {levelled} of {points} points levelled'
                 + (f', {max(graded):g} to {min(graded):g} m' if graded else '')]
        # two reasons a span is left ungraded, and they are told apart: a
        # climb is the contours and the river disagreeing; a long span is
        # ground nobody contoured - the lowland run of a river, mostly
        climbs = sum(1 for _, _, e0, e1 in rejected if (e0 > e1 if upstream else e1 > e0))
        far = len(rejected) - climbs
        why = []
        if climbs:
            why.append(f'{climbs} where the contours climb')
        if far:
            why.append(f'{far} running over {profile.MAX_SEGMENT_M / 1000:g} km '
                       'without a contour')
        if why:
            parts.append(f'{len(rejected)} span{"s" * (len(rejected) != 1)} left ungraded - '
                         + ', '.join(why))
        if upstream:
            parts.append('drawn upstream - graded from its higher end')
        if chain.joins:
            # crossed for the grade, and said - each in the list, with where
            # it is - so the mapping error is fixed where it was made rather
            # than hidden here
            parts.append(f'walked across {len(chain.joins)} gap'
                         f'{"s" * (len(chain.joins) != 1)} between its ways - '
                         'a mapping error, to join upstream')
        if replaced:
            parts.append(f'replaces {replaced} level{"s" * (replaced != 1)} set before')
        if not steps:
            parts.append('already graded so - nothing to change')
        pts = [m.lonlat_to_scene(s2.nodes[r].lon, s2.nodes[r].lat) for s2, r in seq]
        # six of the seven gaps on the gobras set are two nodes on one spot,
        # never merged - "a 0 m gap" would say nothing a mapper can act on
        issues = sorted(span_issues(name, pts, dist, rejected, upstream, True)
                        + [gap_issue('gap', name, j.gap_m, j.lon, j.lat) for j in chain.joins],
                        key=lambda i: ISSUE_ORDER[i.kind])
        chain_paths = []
        for link in chain.links:
            ns = link.square.nodes
            run = [m.lonlat_to_scene(ns[r].lon, ns[r].lat) for r in link.way.refs if r in ns]
            if len(run) >= 2:
                chain_paths.append(run)
        joins = [(*m.lonlat_to_scene(j.lon, j.lat), j.gap_m) for j in chain.joins]
        self._set_proposal(Proposal(
            sq, way, None, '; '.join(parts), dist, levels, current, known, rejected,
            [(*pt, lv) for pt, lv in zip(pts, levels, strict=True) if lv is not None], issues,
            steps=steps, chain_paths=chain_paths, joins=joins))

    def grade_network(self):
        """Shift+G: the river network the selected way belongs to, graded as
        one - G6d-2, proposed like any grade.

        The network is everything connected: by a node shared, by a gap end
        to end, or by an end that stops short of another line's side within
        ``chains.TOLERANCE_M``. It is split into stems - by name first, where
        the name carries a stem on through a confluence (445 of the gobras
        set's 632), and where it does not, chains that stop there. A stem is
        graded after the stems its ends sit on, so a tributary's lower end
        takes the level its river has at the confluence; among stems ready
        together, named before unnamed and then the longer first, which is
        the length fallback for the confluences names do not settle; stems
        that wait on each other in a ring are taken in that order too. A
        level set by an earlier stem is not changed by a later one.
        """
        sel = self.selection
        if (sel is None or sel.way is None or sel.relation is not None
                or sel.way.tags.get('waterway') not in LINE_KINDS):
            self.message.emit('select a river or a stream to grade its network')
            return
        sq0, way0 = sel.square, sel.way
        net = Network(self.working_set)
        members = component(net, sq0, way0)
        if not members:
            members = [(sq0, way0)]
        metres = {(s.name, w.id): (self.layer.along(s, w)[1] or [0.0])[-1] for s, w in members}
        by_name: dict = {}
        for s, w in members:
            if w.tags.get('name'):
                by_name[w.tags['name']] = by_name.get(w.tags['name'], 0.0) + metres[(s.name, w.id)]
        order = sorted(members, key=lambda sw: (
            not sw[1].tags.get('name'),
            -by_name.get(sw[1].tags.get('name'), 0.0),
            -metres[(sw[0].name, sw[1].id)]))
        stems, claimed = [], set()
        for s, w in order:
            if (s.name, w.id) in claimed:
                continue
            stem = net.stem_of(s, w, claimed)
            stems.append(stem)
            claimed |= {(link.square.name, link.way.id) for link in stem.links}
        owner = {(link.square.name, link.way.id): i
                 for i, st in enumerate(stems) for link in st.links}
        profiles = [self._along_chain(st) for st in stems]
        keys = [{node_key(s2, r) for s2, r in prof[0]} for prof in profiles]
        # where each stem's ends meet another stem: at a node, or at a side
        ends, needs = [], []
        for i, (st, (seq, _dist, _)) in enumerate(zip(stems, profiles, strict=True)):
            here, deps = [], set()
            if not seq:
                ends.append(here); needs.append(deps)
                continue
            first, last = st.links[0], st.links[-1]
            for pos, link, at_start in ((0, first, not first.backwards),
                                        (-1, last, last.backwards)):
                k = node_key(*seq[pos])
                for j, kj in enumerate(keys):
                    if j != i and k in kj:
                        deps.add(j)
                side = free_end_side(net, link.square, link.way, at_start)
                if side is not None:
                    j = owner.get((side.square.name, side.way.id))
                    if j is not None and j != i:
                        deps.add(j)
                        here.append((pos, side))
            ends.append(here)
            needs.append(deps)
        rank = {i: (not stems[i].links[0].way.tags.get('name'),
                    -(profiles[i][1][-1] if profiles[i][1] else 0.0)) for i in range(len(stems))}
        done, sequence = set(), []
        while len(done) < len(stems):
            ready = [i for i in rank if i not in done and needs[i] <= done]
            # a ring of stems each waiting on another is broken by the same
            # priority: named, then longer
            pick = min(ready or [i for i in rank if i not in done], key=rank.get)
            done.add(pick)
            sequence.append(pick)
        levels_at: dict = {}
        mine = None                                   # the selected way's stem, for the profile
        issues, all_rejected, joins = [], [], []
        crossings = climbs = far = 0
        for i in sequence:
            seq, dist, known = profiles[i]
            if len(seq) < 2:
                continue
            label = next((link.way.tags['name'] for link in stems[i].links
                          if link.way.tags.get('name')),
                         f'an unnamed {stems[i].links[0].way.tags.get("waterway", "stream")} '
                         f'(way {stems[i].links[0].way.id})')
            extra = [(dist[n], levels_at[node_key(s2, r)]) for n, (s2, r) in enumerate(seq)
                     if node_key(s2, r) in levels_at]
            for pos, side in ends[i]:
                ns, refs = side.square.nodes, side.way.refs
                a = levels_at.get(node_key(side.square, refs[side.seg]))
                b = levels_at.get(node_key(side.square, refs[side.seg + 1]))
                if a is not None and b is not None:
                    extra.append((dist[pos], round(a + (b - a) * side.t, 1)))
                pt = seq[pos]
                n = pt[0].nodes[pt[1]]
                joins.append((*m.lonlat_to_scene(n.lon, n.lat), side.gap_m))
                issues.append(gap_issue('side', label, side.gap_m, n.lon, n.lat))
            for j in stems[i].joins:
                joins.append((*m.lonlat_to_scene(j.lon, j.lat), j.gap_m))
                issues.append(gap_issue('gap', label, j.gap_m, j.lon, j.lat))
            pts = sorted(set(known) | set(extra))
            crossings += len(known)
            if len(pts) < 2:
                continue
            lv, rejected, upstream = profile.grade_along(pts, dist)
            lv = [round(v, 1) if v is not None else None for v in lv]
            for (s2, r), v in zip(seq, lv, strict=True):
                if v is not None:
                    levels_at.setdefault(node_key(s2, r), v)
            c = sum(1 for _, _, e0, e1 in rejected if (e0 > e1 if upstream else e1 > e0))
            climbs, far = climbs + c, far + len(rejected) - c
            scene = [m.lonlat_to_scene(s2.nodes[r].lon, s2.nodes[r].lat) for s2, r in seq]
            shown = any((link.square.name, link.way.id) == (sq0.name, way0.id)
                        for link in stems[i].links)
            issues += span_issues(label, scene, dist, rejected, upstream, shown)
            if shown:
                cur = [parse_ele(s2.nodes[r].tags.get('ele')) for s2, r in seq]
                mine = (dist, [levels_at.get(node_key(s2, r)) for s2, r in seq], cur, pts, rejected)
                all_rejected = rejected
        # named after its main river - the first named stem graded - and not
        # the tributary that happened to be clicked
        name = next((stems[i].links[0].way.tags['name'] for i in sequence
                     if stems[i].links[0].way.tags.get('name')), 'unnamed')
        if not levels_at:
            self.message.emit(f'the {name} network crosses {crossings} contour'
                              f'{"s" * (crossings != 1)} along its {len(stems)} stem'
                              f'{"s" * (len(stems) != 1)} - not enough to grade from')
            return
        everywhere = list(self.working_set.squares.values())
        by_sq = {x.name: x for x in everywhere}
        changes: dict = {}
        replaced = 0
        for k, v in levels_at.items():
            text = format_ele(v)
            holders = ([(by_sq[k[0]], k[1])] if isinstance(k, tuple)
                       else [(x, k) for x in everywhere if k in x.nodes])
            for holder, nid in holders:
                tags = holder.nodes[nid].tags
                if tags.get('ele') == text:
                    continue
                replaced += 'ele' in tags
                changes.setdefault(holder.name, {})[nid] = (dict(tags), {**tags, 'ele': text})
        steps = []
        for sq_name, ch in changes.items():
            ids = tuple(link.way.id for st in stems for link in st.links
                        if link.square.name == sq_name)
            steps.append((by_sq[sq_name], edits.SetNodeLevels(ch, ids, f'grade the {name} network')))
        points = {node_key(s2, r) for prof in profiles for s2, r in prof[0]}
        named = sum(1 for st in stems if st.links and st.links[0].way.tags.get('name'))
        values = list(levels_at.values())
        parts = [f'{name} network: {len(stems)} stem{"s" * (len(stems) != 1)} ({named} named), '
                 f'{crossings} crossing{"s" * (crossings != 1)}, '
                 f'{len(levels_at)} of {len(points)} points levelled'
                 + (f', {max(values):g} to {min(values):g} m' if values else '')]
        why = []
        if climbs:
            why.append(f'{climbs} where the contours climb')
        if far:
            why.append(f'{far} running over {profile.MAX_SEGMENT_M / 1000:g} km without a contour')
        if why:
            parts.append(f'{climbs + far} span{"s" * (climbs + far != 1)} left ungraded - '
                         + ', '.join(why))
        gaps = [x for x in issues if x.kind in ('side', 'gap')]
        if gaps:
            # each in the list, with where it is, so it is fixed where it was made
            sides = sum(x.kind == 'side' for x in gaps)
            parts.append(f'walked across {len(gaps)} gap{"s" * (len(gaps) != 1)}'
                         + (f', {sides} where a tributary stops short of its river'
                            if sides else '')
                         + ' - mapping errors, to join upstream')
        if replaced:
            parts.append(f'replaces {replaced} level{"s" * (replaced != 1)} set before')
        if not steps:
            parts.append('already graded so - nothing to change')
        preview = []
        for k, v in levels_at.items():
            s2, nid = ((by_sq[k[0]], k[1]) if isinstance(k, tuple)
                       else next((x, k) for x in everywhere if k in x.nodes))
            n = s2.nodes[nid]
            preview.append((*m.lonlat_to_scene(n.lon, n.lat), v))
        chain_paths = []
        for st in stems:
            for link in st.links:
                ns = link.square.nodes
                run = [m.lonlat_to_scene(ns[r].lon, ns[r].lat) for r in link.way.refs if r in ns]
                if len(run) >= 2:
                    chain_paths.append(run)
        dist, levels, current, known, _ = mine if mine else (None, None, None, None, None)
        self._set_proposal(Proposal(
            sq0, way0, None, '; '.join(parts), dist, levels, current, known, all_rejected,
            preview, sorted(issues, key=lambda x: ISSUE_ORDER[x.kind]),
            steps=steps, chain_paths=chain_paths, joins=joins))

    def flatten(self, pull_back_m: float | None = None):
        """F: flatten the selected lake at its level - G7a, R26 - proposed, not
        applied. The level goes on its outline, which the build reads as a
        contour; the contours in the water are deleted and those crossing its
        shore drawn back from it by ``pull_back_m``. Enter accepts it as one
        step across every square it touches.

        At the level the lake has: G grades one from its outlet or rim, L or
        the panel sets one by hand - which is R26's "a chosen level" without a
        second way of choosing it."""
        if pull_back_m is not None:
            self.pull_back_m = float(pull_back_m)
        sel = self.selection
        feature = None
        if sel is not None and sel.relation is not None and water_tags(sel.relation.tags):
            feature = sel.relation
        elif (sel is not None and sel.way is not None and sel.way.closed
              and sel.way.tags.get('natural') == 'water'):
            feature = sel.way
        if feature is None:
            self.message.emit('select a lake to flatten')
            return
        sq = sel.square
        name = feature.tags.get('name') or 'the lake'
        try:
            p = flatten.plan(self.working_set, sq, feature, self.history.alloc,
                             pull_back_m=self.pull_back_m)
        except flatten.Refused as why:
            self.message.emit(f'{name} cannot be flattened: {why}')
            return
        text = format_ele(p.level)
        parts = [f'{name} flattened at {text} m']
        if p.outline_ways:
            parts.append(f'the level on its outline, {p.outline_ways} way{"s" * (p.outline_ways != 1)}')
        if p.deleted:
            parts.append(f'{p.deleted} contour{"s" * (p.deleted != 1)} in the water removed')
        if p.pulled:
            parts.append(f'{p.pulled} crossing its shore drawn back {self.pull_back_m:g} m')
        if p.clipped:
            parts.append(f'{p.clipped} at its level cut at the shore')
        if p.fill:
            parts.append(f'{len(p.fill)} fill line{"s" * (len(p.fill) != 1)} across the water, '
                         f'{flatten.FILL_SPACING_M:g} m apart, to hold it flat')
        if not p.steps:
            parts = [f'{name} is already flat at {text} m - nothing to change']
        pts = [m.lonlat_to_scene(lon, lat) for ring in p.outline for lon, lat in ring]
        centre = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        self._set_proposal(Proposal(
            sq, feature, None, '; '.join(parts), preview=[(*centre, p.level)], issues=[],
            steps=p.steps or None,
            chain_paths=[[m.lonlat_to_scene(lon, lat) for lon, lat in ring] for ring in p.outline],
            removed=[[m.lonlat_to_scene(lon, lat) for lon, lat in run] for run in p.removed],
            fill=[[m.lonlat_to_scene(lon, lat) for lon, lat in run] for run in p.fill],
            pull_back_m=self.pull_back_m))

    def _propose_lake(self, sq: Square, feature) -> None:
        name = feature.tags.get('name') or 'the lake'
        found = self.layer.outlet(sq, feature)
        if found is None:
            self.message.emit(f'{name}: no graded river reaches it and no contour '
                              'crosses its shore - nothing to grade from')
            return
        level, how, higher = found
        text = format_ele(round(level, 1))
        before = dict(feature.tags)
        after = {**before, 'ele': text}
        if isinstance(feature, Relation):
            cmd = edits.SetRelationTags(feature.id, before, after)
            ring = [sq.ways[mem.ref] for mem in feature.members
                    if mem.type == 'way' and mem.ref in sq.ways]
        else:
            cmd = edits.SetTags(feature.id, before, after)
            ring = [feature]
        was = before.get('ele')
        if how == 'outlet':
            why = ' - the lowest graded river level in it'
        elif higher is not None:
            # a graded river reaches it, higher than its shore: flowing in
            why = (f' - the lowest contour its shore crosses; a graded river reaches it '
                   f'at {higher:g} m, above that, so flows in rather than out - grade '
                   'the one that drains it')
        else:
            why = (' - the lowest contour its shore crosses; grade the river that drains '
                   'it for a truer level')
        summary = (f'{name}: {text} m, from its {how}' + why
                   + (f'; replaces {was} m' if was is not None and was != text else ''))
        follow = flatten.relevel(sq, feature, text)
        if follow:
            cmd = edits.Compound([cmd, *follow], name=f'{name}: {text} m')
            summary += _FOLLOW
        if was == text:
            cmd, summary = None, f'{name} is already at {text} m, from its {how}'
        xs = [m.lonlat_to_scene(sq.nodes[r].lon, sq.nodes[r].lat)
              for w in ring for r in w.refs if r in sq.nodes]
        centre = (sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)) if xs else (0, 0)
        self._set_proposal(Proposal(sq, feature, cmd, summary,
                                    preview=[(*centre, round(level, 1))], issues=[]))

    def show_issue(self, issue: Issue) -> None:
        """Take the map to something a grade found, and outline it - G6d-3,
        from the panel's list or a click on the profile."""
        self.focused_issue = issue
        lonlat = [m.scene_to_lonlat(x, y) for x, y in issue.path]
        lons, lats = [a for a, _ in lonlat], [b for _, b in lonlat]
        self.placeAsked.emit(min(lons), min(lats), max(lons), max(lats))
        self.message.emit(issue.text)
        self.overlay.update()

    def _set_proposal(self, proposal: Proposal | None) -> None:
        self.proposal = proposal
        self.focused_issue = None
        if proposal is not None:
            self.message.emit(proposal.summary + (' - Enter accepts, Escape drops it'
                                                  if proposal.acceptable else ''))
        self.proposalChanged.emit()
        self.overlay.update()

    def accept_proposal(self) -> bool:
        p = self.proposal
        if p is None or not p.acceptable:
            self._set_proposal(None)
            return False
        self.proposal = None                       # before the step, which drops it
        if p.steps:
            self.do_across(p.steps)                # a chain may run into the next square
        else:
            self.do(p.square, p.command)
        self.message.emit(f'accepted: {p.summary}')
        if p.pull_back_m is not None:
            self.flattened.emit(p.square, p.feature)
        self.proposalChanged.emit()
        self.overlay.update()
        return True

    def cancel_proposal(self) -> None:
        if self.proposal is not None:
            self.message.emit('grade dropped')
            self._set_proposal(None)

    def _drop_proposal(self) -> None:
        if self.proposal is not None:
            self.proposal = None
            self.proposalChanged.emit()
            self.overlay.update()

    def _delete_relation(self, sel: Selection):
        """The lake, with the untagged rings that are nothing without it -
        ``edits.delete_relation`` says which. One step, so Ctrl+Z is the lake
        back whole."""
        if sel.relation.id not in sel.square.relations:
            self.selection = None
            self.message.emit('that relation is already gone')
            return
        cmd = edits.delete_relation(sel.square, sel.relation.id)
        rings = len(cmd.commands) - 1
        self.do(sel.square, cmd)
        self.selection = None
        name = sel.relation.tags.get('name')
        what = f'"{name}"' if name else 'a relation'
        self.message.emit(f'deleted {what}' + (f' and its {rings} ring{"s" * (rings != 1)}'
                                              if rings else ''))
        self.overlay.update()

    @staticmethod
    def _ways_holding(square: Square, nid: int) -> set[int]:
        return edits.ways_holding(square, nid)

    def _way_holding(self, square: Square, nid: int) -> Way | None:
        for w in square.ways.values():
            if nid in w.refs and w.ele is not None:
                return w
        return None

    def _node_crossings(self, square: Square, nid: int) -> list:
        """R16 for the segments either side of a node, after a move - the only
        two that moved, so the only two that can newly cross anything."""
        p = self.layer.node_xy(square, nid)
        found = []
        for wid in self._ways_holding(square, nid):
            way = square.ways[wid]
            if way.ele is None:
                continue
            for i, ref in enumerate(way.refs):
                if ref != nid:
                    continue
                for j in (i - 1, i + 1):
                    if 0 <= j < len(way.refs):
                        q = self.layer.node_xy(square, way.refs[j])
                        found += [c for c in self.layer.crossings(p, q, way.ele) if c not in found]
        return found


class EditOverlay(QGraphicsItem):
    """The rubber band, the snap mark, the selection and its node handles."""

    def __init__(self, ctl: EditController):
        super().__init__()
        self.ctl = ctl
        self.setZValue(200)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption)

    def boundingRect(self) -> QRectF:
        return QRectF(-m.WORLD, -m.WORLD, 3 * m.WORLD, 3 * m.WORLD)

    def _paint_proposal(self, painter: QPainter, proposal) -> None:
        """A grade not yet accepted - G6b. The spans left ungraded in red, and
        each proposed level as an amber diamond, hollow: a level that is not
        there yet, apart from the water's own diamonds, which are. A lake's is
        its value, written at its middle."""
        scale = painter.worldTransform().m11() or 1.0
        # the whole chain being graded, not only the way that was clicked:
        # the grade is the chain's, and so is what it will change (G6d)
        chain = QPen(QColor(255, 140, 0, 90), 9.0)
        chain.setCosmetic(True)
        painter.setPen(chain)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for run in proposal.chain_paths or ():
            path = QPainterPath(QPointF(*run[0]))
            for pt in run[1:]:
                path.lineTo(*pt)
            painter.drawPath(path)
        # what a flatten takes away: struck through in red, dashed, so the
        # contour under it still shows what is being lost
        cut = QPen(QColor(200, 30, 30, 220), 2.5)
        cut.setCosmetic(True)
        cut.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(cut)
        for run in proposal.removed or ():
            if len(run) >= 2:
                painter.drawPath(_path(run))
        # and what it lays across the water: its fill lines, in the lake's own
        # dark blue so they read as the lake's and not as contours
        lay = QPen(QColor(20, 70, 140, 200), 1.2, Qt.PenStyle.DashLine)
        lay.setCosmetic(True)
        painter.setPen(lay)
        for run in proposal.fill or ():
            painter.drawPath(_path(run))
        # each gap walked across: a ring, so the mapping error can be found
        ring = QPen(QColor(120, 60, 0), 2.0)
        ring.setCosmetic(True)
        for x, y, _gap in proposal.joins or ():
            painter.setPen(ring)
            painter.drawEllipse(QPointF(x, y), 9.0 / scale, 9.0 / scale)
        # the spans left ungraded, as the profile shades them: a climb red,
        # ground nobody contoured grey; and the one the list or the profile
        # last took the map to, outlined under it
        focus = self.ctl.focused_issue
        for issue in proposal.issues or ():
            if issue is focus:
                mark = QPen(QColor(255, 220, 0, 230), 12.0)
                mark.setCosmetic(True)
                painter.setPen(mark)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                if len(issue.path) == 1:
                    painter.drawEllipse(QPointF(*issue.path[0]), 14.0 / scale, 14.0 / scale)
                else:
                    painter.drawPath(_path(issue.path))
            if issue.kind not in ISSUE_PEN:
                continue
            pen = QPen(ISSUE_PEN[issue.kind], 4.0)
            pen.setCosmetic(True)
            if issue.kind == 'far':
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_path(issue.path))
        amber = QColor(220, 140, 0)
        h = 4.5 / scale
        # dark on a white halo: the river under it is haloed orange as the
        # selection, and amber on orange is not there at all
        halo = QPen(QColor(255, 255, 255, 230), 3.6)
        halo.setCosmetic(True)
        pen = QPen(QColor(120, 60, 0), 1.6)
        pen.setCosmetic(True)
        lake = not isinstance(proposal.feature, Way) or proposal.feature.closed
        for x, y, level in proposal.preview or ():
            if lake:
                painter.save()
                painter.translate(x, y)
                painter.scale(1.0 / scale, 1.0 / scale)
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                text = f'{level:g} m ?'
                painter.setPen(QPen(QColor(255, 255, 255, 230), 4.0))
                painter.drawText(QPointF(-20, 5), text)
                painter.setPen(amber.darker(140))
                painter.drawText(QPointF(-20, 5), text)
                painter.restore()
                continue
            diamond = [QPointF(x, y - h), QPointF(x + h, y), QPointF(x, y + h), QPointF(x - h, y)]
            painter.setPen(halo)
            painter.drawPolygon(diamond)
            painter.setPen(pen)
            painter.drawPolygon(diamond)

    def _paint_marks(self, painter: QPainter, ctl, rect: QRectF, px: float) -> None:
        """Every crossing in view as a small red cross, and those of the row
        chosen in the checks panel larger, ringed - G8a. In pixels, as a
        spot height is: a crossing is a point at any zoom."""
        pen = QPen(QColor(210, 20, 20), 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        h = 3.5 * px
        for x, y in ctl.marks:
            if rect.contains(QPointF(x, y)):
                painter.drawLine(QPointF(x - h, y - h), QPointF(x + h, y + h))
                painter.drawLine(QPointF(x - h, y + h), QPointF(x + h, y - h))
        if ctl.marks_focus:
            ring = QPen(QColor(210, 20, 20), 2.2)
            ring.setCosmetic(True)
            painter.setPen(ring)
            for x, y in ctl.marks_focus:
                if rect.contains(QPointF(x, y)):
                    painter.drawEllipse(QPointF(x, y), 7 * px, 7 * px)

    def paint(self, painter: QPainter, option, widget=None):
        ctl = self.ctl
        scale = painter.worldTransform().m11()
        px = 1.0 / scale
        rect = visible_rect(painter, option, self.boundingRect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sel = ctl.selection
        if sel is not None and sel.spot and sel.node in sel.square.nodes:
            node = sel.square.nodes[sel.node]
            x, y = m.lonlat_to_scene(node.lon, node.lat)
            pen = QPen(QColor(255, 140, 0), 2.5); pen.setCosmetic(True)
            painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
            h = 7 * px
            painter.drawRect(QRectF(x - h, y - h, 2 * h, 2 * h))
        if (sel is not None and sel.relation is not None
                and sel.relation.id in sel.square.relations):
            # the relation's member ways, haloed, without the per-node marks:
            # nothing here edits a relation's vertices, and a lake's rings run
            # to thousands of them
            halo = QPen(QColor(255, 140, 0, 140), 7.0); halo.setCosmetic(True)
            painter.setPen(halo); painter.setBrush(Qt.BrushStyle.NoBrush)
            for mem in sel.relation.members:
                way = sel.square.ways.get(mem.ref) if mem.type == 'way' else None
                if way is None:
                    continue
                pts = [m.lonlat_to_scene(lon, lat) for lon, lat in sel.square.coords(way)]
                if len(pts) >= 2:
                    path = QPainterPath(QPointF(*pts[0]))
                    for p in pts[1:]:
                        path.lineTo(*p)
                    painter.drawPath(path)
        if sel is not None and sel.way is not None and sel.way.id in sel.square.ways:
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in sel.square.coords(sel.way)]
            if len(pts) >= 2:
                path = QPainterPath(QPointF(*pts[0]))
                for p in pts[1:]:
                    path.lineTo(*p)
                halo = QPen(QColor(255, 140, 0, 110), 7.0); halo.setCosmetic(True)
                painter.setPen(halo); painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 140, 0))
                # not while a grade is proposed: at a zoom that shows a river
                # whole, these vertex marks and its proposed levels were the
                # same size, close in colour and on the same line - a mark on
                # the river has to mean one thing
                if len(pts) <= 4000 and ctl.proposal is None:
                    h = 2.5 * px
                    for x, y in pts:
                        if rect.contains(QPointF(x, y)):
                            painter.drawRect(QRectF(x - h, y - h, 2 * h, 2 * h))
            if sel.node is not None and sel.node in sel.square.nodes:
                x, y = ctl.layer.node_xy(sel.square, sel.node)
                pen = QPen(QColor(200, 0, 0), 2.0); pen.setCosmetic(True)
                painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
                h = 5 * px
                painter.drawRect(QRectF(x - h, y - h, 2 * h, 2 * h))
        # a grade not yet accepted, over the selection's halo: drawn under it,
        # the red of a rejected span was hidden by the orange of the river
        # being graded, which is the river it is on
        if ctl.proposal is not None:
            self._paint_proposal(painter, ctl.proposal)
        if ctl.marks:
            self._paint_marks(painter, ctl, rect, px)
        if ctl.ghost:
            # the contour being carried, where it would go (G8b)
            pen = QPen(QColor(255, 140, 0), 2.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(_path(ctl.ghost))
        if ctl.tool != 'draw':
            return
        anchor = ctl._anchor()
        target = (ctl.snap[2], ctl.snap[3]) if ctl.snap else ctl.cursor
        if ctl._stroke is not None and len(ctl._stroke) > 1:
            # a fast draw in progress: the mouse's own path, as it will be laid
            pen = QPen(QColor(30, 30, 30), 1.5); pen.setCosmetic(True)
            painter.setPen(pen)
            path = QPainterPath(QPointF(*ctl._stroke[0]))
            for p in ctl._stroke[1:]:
                path.lineTo(*p)
            painter.drawPath(path)
        elif anchor is not None and target is not None:
            colour = QColor(200, 0, 0) if ctl.blocking() else QColor(30, 30, 30)
            pen = QPen(colour, 1.5, Qt.PenStyle.DashLine); pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(QPointF(*anchor), QPointF(*target))
        if ctl.snap is not None:
            pen = QPen(QColor(0, 120, 255), 2.0); pen.setCosmetic(True)
            painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
            r = 6 * px
            painter.drawEllipse(QPointF(ctl.snap[2], ctl.snap[3]), r, r)
