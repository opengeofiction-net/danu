"""Measure and profile - H3b. A line on the map and what lies along it.

M is the tool. Points clicked, a line through them, ended by a double click,
Enter or a right click; or a drag, which is a straight line of its two ends.
While it is drawn the status line says how long it is and the ground at the
cursor against the start. Ended, it is measured: its length on the ground,
the ground at its ends, the rise and the gradient between them, what it climbs
and falls along the way and the steepest it gets - and the profile panel draws
the ground along it, with the contours it crosses at their values and the
water at its levels, or the ground's slope along it, as the map's slope mode
gives it. A click on the profile takes the map to the place.

No climbs shaded, as the grade's plot shades them: on a line drawn anywhere a
climb is only the ground going up, and there is nothing to do about it. A
river's climbs are the grade's to show and the burn's to mend.

The ground is the exact surface's, or nothing: while a preview stands the
profile says so, and is drawn again when the exact build lands - the spec's
"a profile ... is taken from an exact surface or refuses to answer".
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..core.square import parse_ele
from ..surface import along as A
from . import mercator as m
from .contours import water_feature
from .tools import FAST_PX

GROUND = QColor(120, 75, 30)
SLOPE = QColor(200, 90, 20)
SLOPE_FLOOR = 5.0                # degrees: the slope plot's least top, so the flat reads flat
WATER = QColor(30, 100, 200)
LINE = QColor(20, 20, 20)
AGAIN_MS = 500                   # edits this long apart, and an ended line is measured again


def metres(d: float) -> str:
    return f'{d:,.0f} m' if d < 1000 else f'{d / 1000:,.2f} km'


class MeasureTool(QObject):
    """The line, its points in scene units, and what was found along it."""

    changed = Signal()               # the line, the cursor or the reading moved: repaint
    measured = Signal()              # a line ended and measured, or measured again
    ended = Signal()                 # a line ended: the profile is shown
    message = Signal(str)

    def __init__(self, view, layer, surface, parent=None):
        super().__init__(parent)
        self.view, self.layer, self.surface = view, layer, surface
        self.points: list[tuple[float, float]] = []
        self.cursor: tuple[float, float] | None = None
        self.done = False
        self.result: A.Along | None = None
        self.why_not: str | None = None          # why there is no ground along it
        self.hover_d: float | None = None        # metres along the profile is pointing at
        self._press: QPointF | None = None
        self._dragging = False
        self.overlay = MeasureOverlay(self)
        view.scene().addItem(self.overlay)
        # an edit makes the layer's crossing index stale, and asking it again
        # is 0.3 s on the gobras 3x3 - once the edits pause, not at each
        self._again = QTimer(self)
        self._again.setSingleShot(True)
        self._again.setInterval(AGAIN_MS)
        self._again.timeout.connect(self.surface_changed)

    def _px(self, px: float) -> float:
        return px / m.scale_for_zoom(self.view.zoom)

    # ------------------------------------------------------------ input
    def mouse_press(self, event, pos: QPointF) -> bool:
        if event.button() == Qt.MouseButton.RightButton:
            self.finish()
            return True
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self.done:
            self.clear()                          # a click after a line ended begins another
        self._press = QPointF(pos)
        self._dragging = False
        return True

    def mouse_move(self, event, pos: QPointF) -> bool:
        self.cursor = (pos.x(), pos.y())
        if self._press is not None and not self.points and event.buttons() & Qt.MouseButton.LeftButton:
            d = pos - self._press
            if abs(d.x()) + abs(d.y()) >= self._px(FAST_PX):
                self._dragging = True
        if not self.done and (self.points or self._dragging):
            self.message.emit(self.live())
        self.changed.emit()
        return True

    def mouse_release(self, event, pos: QPointF) -> bool:
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        press, self._press = self._press, None
        if self._dragging:
            # a drag with nothing clicked yet: a straight line, its two ends
            self._dragging = False
            self.points = [(press.x(), press.y()), (pos.x(), pos.y())]
            self.finish()
            return True
        p = (press.x(), press.y())
        if not self.points or np.hypot(p[0] - self.points[-1][0], p[1] - self.points[-1][1]) > self._px(2):
            self.points.append(p)
        if len(self.points) == 1:
            self.message.emit('measuring: click the next point; a double click, Enter or a right '
                              'click ends the line')
        self.changed.emit()
        return True

    def mouse_double_click(self, event, pos: QPointF) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        self.finish()
        return True

    def key_press(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
            return True
        if key == Qt.Key.Key_Backspace and self.points and not self.done:
            self.points.pop()
            self.changed.emit()
            return True
        if key == Qt.Key.Key_Escape and (self.points or self.done):
            self.clear()
            return True
        return False

    # ---------------------------------------------------------- the line
    def clear(self) -> None:
        self.points, self.done, self.result, self.why_not, self.hover_d = [], False, None, None, None
        self._press, self._dragging = None, False
        self.changed.emit()
        self.measured.emit()

    def finish(self) -> None:
        if self.done:
            return
        if len(self.points) < 2:
            self.message.emit('a line wants two points or more - click them, or drag one')
            return
        self.done = True
        self.measure()
        self.ended.emit()
        self.message.emit(self.summary())

    def live(self) -> str:
        """While it is drawn: how long, to the cursor, and the ground there
        against the start."""
        pts = list(self.points)
        if self._dragging and self._press is not None:
            pts = [(self._press.x(), self._press.y())]
        if self.cursor is not None:
            pts.append(self.cursor)
        if len(pts) < 2:
            return ''
        a = A.along(pts)
        text = f'measuring: {metres(a.length)}'
        shaded = self._exact()
        if shaded is not None:
            g = A.sample(shaded.dem, shaded.scene_rect, np.array([pts[0], pts[-1]]))
            if not np.isnan(g).any():
                rise = g[1] - g[0]
                text += f', {g[1]:,.0f} m here, {rise:+,.0f} m from the start'
                if a.length:
                    text += f' ({100 * rise / a.length:+.1f}%)'
        return text

    def _exact(self):
        shaded = self.surface.shaded
        return None if shaded is None or self.surface.previewing else shaded

    def measure(self) -> None:
        """What lies along the line, from the exact surface - again when the
        surface or the squares change under a line already ended."""
        if not self.done:
            return
        shaded = self._exact()
        if self.surface.shaded is None:
            self.why_not = 'no surface built - Ctrl+R builds one'
        elif shaded is None:
            self.why_not = 'a preview stands: the ground along it waits for the exact surface'
        else:
            self.why_not = None
        a = A.along(self.points, shaded)
        contours, water = self.layer.line_crossings(self.points)
        a.contours = sorted((a.distance_of(k, t), e) for k, t, e in contours)
        a.water = sorted((a.distance_of(k, t), *self._water(sq, way, j, u)) for k, t, sq, way, j, u in water)
        self.result = a
        self.changed.emit()
        self.measured.emit()

    def _water(self, square, way, j: int, u: float) -> tuple[str, float | None]:
        """What water it crosses, and its level there: a lake's, or a river's
        between the levels on its vertices either side."""
        feature = water_feature(square, way)
        tags = feature.tags
        kind = tags.get('waterway') or tags.get('water') or 'water'
        label = f'{kind} "{tags["name"]}"' if tags.get('name') else kind
        if 'waterway' not in tags or way.closed:
            return label, parse_ele(tags.get('ele'))
        refs, dist = self.layer.along(square, way)
        if j + 1 >= len(dist):
            return label, None
        d = dist[j] + u * (dist[j + 1] - dist[j])
        levels = [(dist[i], parse_ele(square.nodes[r].tags.get('ele'))) for i, r in enumerate(refs)]
        return label, A.level_between([(x, e) for x, e in levels if e is not None], d)

    def surface_changed(self) -> None:
        if self.done:
            self.measure()

    def edited(self) -> None:
        if self.done:
            self._again.start()

    # ----------------------------------------------------------- reading
    def summary(self) -> str:
        a = self.result
        if a is None:
            return ''
        parts = [metres(a.length)]
        if self.why_not:
            parts.append(self.why_not)
        elif a.ends is None:
            parts.append('off the surface')
        else:
            g0, g1 = a.ends
            rise = g1 - g0
            parts.append(f'{g0:,.0f} m to {g1:,.0f} m, {rise:+,.0f} m'
                         + (f' ({100 * rise / a.length:+.1f}%)' if a.length else ''))
            up, down = a.up_down
            parts.append(f'along it {up:,.0f} m up and {down:,.0f} m down, '
                         f'{a.lowest:,.0f} to {a.highest:,.0f} m'
                         + (f', steepest {a.steepest:.1f}°' if a.steepest is not None else ''))
        crossed = []
        if a.contours:
            crossed.append(f'{len(a.contours)} contour{"s" * (len(a.contours) != 1)}')
        if a.water:
            crossed.append(f'{len(a.water)} water')
        if crossed:
            parts.append('crosses ' + ' and '.join(crossed))
        return ' · '.join(parts)


class MeasureOverlay(QGraphicsItem):
    """The line on the map: drawn, the stretch to the cursor while it is
    being drawn, and the place the profile points at."""

    def __init__(self, tool: MeasureTool):
        super().__init__()
        self.tool = tool
        self.setZValue(210)
        tool.changed.connect(self.update)

    def boundingRect(self) -> QRectF:
        return QRectF(-m.WORLD, -m.WORLD, 3 * m.WORLD, 3 * m.WORLD)

    def paint(self, painter: QPainter, option, widget=None):
        t = self.tool
        pts = list(t.points)
        if t._dragging and t._press is not None:
            pts = [(t._press.x(), t._press.y())]
        if not pts:
            return
        scale = painter.worldTransform().m11() or 1.0
        halo = QPen(QColor(255, 255, 255, 200), 5.0)
        halo.setCosmetic(True)
        pen = QPen(LINE, 2.0, Qt.PenStyle.SolidLine if t.done else Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        path = QPainterPath(QPointF(*pts[0]))
        for p in pts[1:]:
            path.lineTo(*p)
        if not t.done and t.cursor is not None:
            path.lineTo(*t.cursor)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for p_ in (halo, pen):
            painter.setPen(p_)
            painter.drawPath(path)
        painter.setPen(QPen(LINE, 0))
        painter.setBrush(QColor(255, 255, 255))
        r = 3.0 / scale
        for p in pts:
            painter.drawEllipse(QPointF(*p), r, r)
        if t.hover_d is not None and t.result is not None:
            painter.setBrush(GROUND)
            painter.drawEllipse(QPointF(*t.result.at(t.hover_d)), 5.0 / scale, 5.0 / scale)


class TerrainProfile(QWidget):
    """The ground along the line, distance across. In elevation, the ground
    brown, the contours crossed as dark dots at their values and the water as
    blue triangles at its level - hollow, at the ground, where it has none.
    In slope, the ground's slope in degrees, and the contours and the water
    as ticks along the foot. Under the line, each stretch filled in the
    colour the map gives that place - ``colourer`` says what that is. Hover
    for the ground at a place, which the map marks; a click takes the map
    there."""

    hovered = Signal(object)              # metres along, or None
    chosen = Signal(float)                # metres along: show it on the map

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line: A.Along | None = None
        self.mode = 'elevation'
        self._x = None                    # metres along to pixels, as last painted
        self._plot = None
        # (Along) -> RGBA a point, or None for no colours: the window's, from
        # the legend, so the fill is the map's colour scale as it stands
        self.colourer = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def show_line(self, line) -> None:
        self.line = line if line is not None and line.ground is not None else None
        self._x = self._plot = None
        self.setVisible(self.line is not None)
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode not in ('elevation', 'slope'):
            raise ValueError(mode)
        self.mode = mode
        self.update()

    def _d_at(self, px: float):
        if self._plot is None:
            return None
        left, width, length = self._plot
        d = (px - left) / width * length
        return d if 0 <= d <= length else None

    def mouseMoveEvent(self, event):
        d = self._d_at(event.position().x())
        self.hovered.emit(d)
        if d is not None and self.line is not None:
            g, sl = self.line.ground_at(d), self.line.slope_at(d)
            said = [f'ground {g:,.0f} m'] if g is not None else []
            said += [f'slope {sl:.1f}°'] if sl is not None else []
            QToolTip.showText(event.globalPosition().toPoint(),
                              f'{metres(d)} along' + (' - ' + ', '.join(said) if said else '')
                              + '. Click to show it on the map.', self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        d = self._d_at(event.position().x())
        if d is not None and event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(d)
            return
        super().mousePressEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(None)
        super().leaveEvent(event)

    def _values(self):
        a = self.line
        v = a.slope if self.mode == 'slope' else a.ground
        return v if v is not None else np.full(len(a.dist), np.nan)

    def _fill(self, painter, a, v, x, y, r) -> None:
        """Under the line, from each point to the next, in the colour the
        map gives the first of them; grey where the map has no colours."""
        rgba = self.colourer(a) if self.colourer is not None else None
        grey = QColor(200, 200, 200)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)   # no seams between stretches
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(len(v) - 1):
            if np.isnan(v[i]) or np.isnan(v[i + 1]):
                continue
            c = rgba[i] if rgba is not None else None
            painter.setBrush(grey if c is None else QColor(int(c[0]), int(c[1]), int(c[2])))
            x0, x1 = x(a.dist[i]), x(a.dist[i + 1])
            path = QPainterPath(QPointF(x0, r.bottom()))
            path.lineTo(x0, y(v[i]))
            path.lineTo(x1, y(v[i + 1]))
            path.lineTo(x1, r.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        painter.restore()

    def paintEvent(self, _event):
        a = self.line
        if a is None:
            return
        slope = self.mode == 'slope'
        v = self._values()
        if slope:
            known = v[~np.isnan(v)]
            if not len(known):
                return
            lo, hi = 0.0, max(SLOPE_FLOOR, float(known.max()) * 1.08)
            top_label, foot_label = f'{hi:.0f}°', '0°'
        else:
            values = [float(x) for x in v[~np.isnan(v)]] + [e for _, e in a.contours] \
                + [x for _, _, x in a.water if x is not None]
            if not values:
                return
            lo, hi = min(values), max(values)
            pad = max(1.0, (hi - lo) * 0.08)
            top_label, foot_label = f'{hi:,.0f}', f'{lo:,.0f}'
            lo, hi = lo - pad, hi + pad
        length = a.length or 1.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(40, 6, -6, -16)
        painter.fillRect(r, self.palette().base())
        x = lambda d: r.left() + r.width() * d / length            # noqa: E731
        y = lambda e: r.bottom() - r.height() * (e - lo) / (hi - lo)  # noqa: E731
        self._x = x
        self._plot = (r.left(), r.width(), length)
        self._fill(painter, a, v, x, y, r)
        painter.setPen(QPen(SLOPE if slope else GROUND, 1.6))
        path, open_ = QPainterPath(), False
        for d, e in zip(a.dist, v, strict=True):
            if np.isnan(e):
                open_ = False
                continue
            if open_:
                path.lineTo(x(d), y(e))
            else:
                path.moveTo(x(d), y(e))
                open_ = True
        painter.drawPath(path)
        # the contours in the text's colour, so they read on the plot's own
        # ground in a dark theme as in a light one - charcoal was lost on dark
        ink, ground = self.palette().text().color(), self.palette().base().color()
        if slope:
            # what it crosses, where: a tick along the foot, as no slope is theirs
            painter.setPen(QPen(ink, 1.2))
            for d, _ in a.contours:
                painter.drawLine(QPointF(x(d), r.bottom()), QPointF(x(d), r.bottom() - 6))
            painter.setPen(QPen(WATER, 2.0))
            for d, _, _ in a.water:
                painter.drawLine(QPointF(x(d), r.bottom()), QPointF(x(d), r.bottom() - 9))
        else:
            painter.setPen(QPen(ground, 1.0))            # a ring, to stand off the fill too
            painter.setBrush(ink)
            for d, e in a.contours:
                painter.drawEllipse(QPointF(x(d), y(e)), 2.6, 2.6)
            painter.setPen(Qt.PenStyle.NoPen)
            for d, _, level in a.water:
                at = level if level is not None else a.ground_at(d)
                if at is None:
                    continue
                tri = QPainterPath()
                tri.moveTo(x(d) - 4, y(at) - 5)
                tri.lineTo(x(d) + 4, y(at) - 5)
                tri.lineTo(x(d), y(at) + 1)
                tri.closeSubpath()
                if level is not None:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(WATER)
                else:
                    painter.setPen(QPen(WATER, 1.2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(tri)
        painter.setPen(self.palette().text().color())
        painter.drawText(QRectF(0, r.top() - 6, 38, 14), Qt.AlignmentFlag.AlignRight, top_label)
        painter.drawText(QRectF(0, r.bottom() - 8, 38, 14), Qt.AlignmentFlag.AlignRight, foot_label)
        painter.drawText(QRectF(r.left(), r.bottom() + 1, r.width(), 14),
                         Qt.AlignmentFlag.AlignRight, metres(length))
        painter.end()


class ProfileDock(QDockWidget):
    """What the measured line says, and its profile - of the ground or of
    its slope."""

    placeChosen = Signal(float, float)    # lon, lat: take the map there

    def __init__(self, tool: MeasureTool, parent=None):
        super().__init__('Profile', parent)
        self.setObjectName('profile')
        self.tool = tool
        body = QWidget()
        box = QVBoxLayout(body)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.summary, 1)
        self.modes = QButtonGroup(self)
        self.mode_buttons = {}
        for mode, text in (('elevation', 'Elevation'), ('slope', 'Slope')):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)      # the map keeps the keys
            b.clicked.connect(lambda _=False, mode=mode: self.set_mode(mode))
            self.modes.addButton(b)
            self.mode_buttons[mode] = b
            top.addWidget(b)
        self.mode_buttons['elevation'].setChecked(True)
        self.plot = TerrainProfile()
        self.plot.setMinimumHeight(150)
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.hint = QLabel('M measures: click points along a line - a double click, Enter or a right click '
                           'ends it - or drag a straight one. Esc clears it. A click on the profile shows '
                           'the place on the map.')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color: palette(mid);')
        box.addLayout(top)
        box.addWidget(self.plot, 1)
        box.addWidget(self.hint)
        self.setWidget(body)
        self.plot.hovered.connect(self._hovered)
        self.plot.chosen.connect(self._chosen)
        tool.measured.connect(self.refresh)
        tool.ended.connect(self._ended)
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self.plot.set_mode(mode)
        self.mode_buttons[mode].setChecked(True)

    def _hovered(self, d) -> None:
        self.tool.hover_d = d
        self.tool.changed.emit()

    def _chosen(self, d: float) -> None:
        if self.tool.result is not None:
            self.placeChosen.emit(*m.scene_to_lonlat(*self.tool.result.at(d)))

    def refresh(self) -> None:
        t = self.tool
        self.summary.setText(t.summary() if t.result is not None else 'No line measured.')
        self.plot.show_line(t.result if t.why_not is None else None)

    def _ended(self) -> None:
        # shown when a line ends, and only then: measured again after an
        # edit, a panel the mapper closed stays closed
        self.show()
        self.raise_()
