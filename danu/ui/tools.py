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

from dataclasses import dataclass

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

import numpy as np

from ..core import edits, geometry
from ..core.ladder import format_ele
from ..core.square import Square, Way, WorkingSet
from . import mercator as m
from .contours import ContourLayer
from .mapview import MapView, visible_rect

SNAP_PX = 10.0                  # a node this close is the one meant
PICK_PX = 8.0                   # a way this close is the one meant
DRAG_PX = 3.0                   # a press that moves less is a click
FAST_PX = 4.0                   # a held button that travels this far is drawing, not clicking
SIMPLIFY_PX = 2.0               # a fast-drawn stroke is simplified to within this of itself on release


@dataclass
class Selection:
    square: Square
    way: Way
    node: int | None = None


class EditController(QObject):
    """The tools, the history and the selection, over one working set."""

    edited = Signal()                # after any command, undo or redo
    message = Signal(str)            # for the status line
    toolChanged = Signal(str)

    def __init__(self, view: MapView, layer: ContourLayer, elevation, parent=None):
        super().__init__(parent)
        self.view, self.layer, self.elevation = view, layer, elevation
        self.history = edits.SetUndoStack()
        self.working_set: WorkingSet | None = None
        self.overlay = EditOverlay(self)
        view.scene().addItem(self.overlay)
        self.tool = 'select'
        self.selection: Selection | None = None
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
        view.tool = self

    # ------------------------------------------------------------ setup
    def set_working_set(self, ws: WorkingSet | None):
        self.working_set = ws
        self.history = edits.SetUndoStack()
        self.selection = None
        self._stop_drawing()
        self.edited.emit()

    def set_tool(self, name: str):
        if name not in ('select', 'draw'):
            raise ValueError(name)
        if name != self.tool:
            self._stop_drawing()
            self.tool = name
            self.view.setDragMode(MapView.DragMode.ScrollHandDrag if name == 'select' else MapView.DragMode.NoDrag)
            self.view.viewport().setCursor(Qt.CursorShape.CrossCursor if name == 'draw' else Qt.CursorShape.ArrowCursor)
            self.toolChanged.emit(name)
            self.overlay.update()

    def _px(self, px: float) -> float:
        return px / m.scale_for_zoom(self.view.zoom)

    # ---------------------------------------------------------- history
    def do(self, square: Square, cmd: edits.Command):
        self.history.do(square, cmd)
        self.layer.refresh(square, cmd.ways(square))
        self.edited.emit()

    def undo(self):
        step = self.history.undo()
        if step:
            square, cmd = step
            self.layer.refresh(square, cmd.ways(square))
            self._after_history_move(square)
            self.message.emit(f'undid {cmd.describe()}')

    def redo(self):
        step = self.history.redo()
        if step:
            square, cmd = step
            self.layer.refresh(square, cmd.ways(square))
            self._after_history_move(square)
            self.message.emit(f'redid {cmd.describe()}')

    def _after_history_move(self, square: Square):
        if self.drawing and (self.drawing[0] is square) and self.drawing[1] not in square.ways:
            self.drawing = None                      # the way being drawn was undone away
        if self.selection and self.selection.way.id not in self.selection.square.ways:
            self.selection = None
        elif self.selection and self.selection.node is not None and self.selection.node not in self.selection.square.nodes:
            self.selection.node = None
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
                self._stop_drawing()
                return True
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
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
        hit = self.layer.pick(pos.x(), pos.y(), self._px(PICK_PX))
        if hit is not None:
            self.selection = Selection(hit[0], hit[1])
            self.elevation.pick_up(hit[1].ele)
            self.overlay.update()
            return True
        if self.selection is not None:
            self.selection = None
            self.overlay.update()
        return False                                 # the view pans

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
        self.message.emit(f'moved a node of the {format_ele(self.selection.way.ele)} m contour' if self.selection and self.selection.way.ele is not None else 'moved a node')
        return True

    def mouse_double_click(self, event, pos: QPointF) -> bool:
        if self.working_set is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        if self.tool == 'draw':
            self._stop_drawing()
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
        if key == Qt.Key.Key_Escape:
            if self.tool == 'draw' and (self.drawing or self.pending):
                self._stop_drawing()
            else:
                self.selection = None
                self.set_tool('select')
                self.overlay.update()
            return True
        if self.tool == 'draw' and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._stop_drawing()
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
            self.message.emit(f'drawing at {format_ele(ele)} m in {square.name}')
            self.overlay.update()
            return False
        if self.pending is not None:
            square, first, first_coord = self.pending
            alloc = self.history.alloc(square)
            wid = alloc.take()
            second = self.snap[1] if self.snap and self.snap[0] is square else None
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
                self.message.emit('not redrawn: the new line would leave ' + self._describe_crossing(bad))
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
        from ..core.geometry import simplify
        pts = simplify(stroke, self._px(SIMPLIFY_PX))[1:]     # the first is the press, already down
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
        ele, tag = self.elevation.value, self.elevation.model.tag
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
        if ele is None or node in temp.refs:
            return None
        began = temp.refs[0] if at_end else temp.refs[-1]
        target = next((w for w in square.ways.values()
                       if w.id != wid and w.ele == ele and began in w.refs and node in w.refs), None)
        if target is None:
            return None
        run = list(temp.refs) if at_end else list(reversed(temp.refs))
        run.append(node)                                  # from where it began to where it came back
        i, j = target.refs.index(began), target.refs.index(node)
        if i > j:
            i, j = j, i
            run.reverse()
        cmds: list[edits.Command] = []
        if target.closed:
            # two ways round a ring; the one it was drawn over is the one meant
            body = len(target.refs) - 1
            inner, outer = target.refs[i + 1:j], target.refs[j + 1:-1] + target.refs[:i]
            if self._mean_distance(square, outer, run) < self._mean_distance(square, inner, run):
                cmds.append(edits.RotateRing(target.id, j))
                i, j = 0, (i - j) % body
                run.reverse()
        cmds.append(edits.ReplaceSection(target.id, i, j, run))
        cmds.append(edits.DeleteWay(wid))                 # after the splice, so its nodes are not orphans
        drawn = len(run) - 2
        return edits.Compound(cmds, f'redraw {drawn} nodes of a {format_ele(ele)} m contour'), target, drawn

    def _way_at(self, square: Square, node: int, ele: float) -> Way | None:
        """The contour at this elevation holding a node, if there is one."""
        return next((w for w in square.ways.values() if w.ele == ele and node in w.refs), None)

    def _crossings_along(self, square: Square, way: Way, refs: list[int]) -> list:
        """What a run of a way's own refs crosses, now that it is in place."""
        found: list = []
        for a, b in zip(refs, refs[1:]):
            if a not in square.nodes or b not in square.nodes:
                continue
            for c in self.layer.crossings(self.layer.node_xy(square, a), self.layer.node_xy(square, b), way.ele):
                if c not in found:
                    found.append(c)
        return found

    def _mean_distance(self, square: Square, node_ids: list[int], run: list[int]) -> float:
        """How far a stretch of contour lies, on average, from what was drawn."""
        if not node_ids:
            return 0.0
        pts = np.array([self.layer.node_xy(square, r) for r in run], dtype=float)
        a, b = pts[:-1], pts[1:]
        total = 0.0
        for nid in node_ids:
            _, d = geometry.nearest_point_on_segments(self.layer.node_xy(square, nid), a, b)
            total += float(d.min())
        return total / len(node_ids)

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
        if sel.node is not None:
            self.do(sel.square, edits.DeleteNode(sel.node))
            self.selection = Selection(sel.square, sel.way) if sel.way.id in sel.square.ways else None
            self.message.emit('deleted a node')
        else:
            self.do(sel.square, edits.DeleteWay(sel.way.id))
            self.selection = None
            self.message.emit(f'deleted the {format_ele(sel.way.ele)} m contour' if sel.way.ele is not None else 'deleted a way')
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

    def paint(self, painter: QPainter, option, widget=None):
        ctl = self.ctl
        scale = painter.worldTransform().m11()
        px = 1.0 / scale
        rect = visible_rect(painter, option, self.boundingRect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sel = ctl.selection
        if sel is not None and sel.way.id in sel.square.ways:
            pts = [m.lonlat_to_scene(lon, lat) for lon, lat in sel.square.coords(sel.way)]
            if len(pts) >= 2:
                path = QPainterPath(QPointF(*pts[0]))
                for p in pts[1:]:
                    path.lineTo(*p)
                halo = QPen(QColor(255, 140, 0, 110), 7.0); halo.setCosmetic(True)
                painter.setPen(halo); painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 140, 0))
                if len(pts) <= 4000:
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
