"""The colour scale on the map: the legend, and the control for pinch - R11.

A bar down the right of the view shows the ramp as the surface is coloured
now: over the land's range, through the scaling in force, so a pinched ramp
reads as a band of colour between saturated ends, exactly as the map does.
Ticks name the ends and the pinch centre, on the map side of the bar.

It is the control too. Drag on it to set the pinch centre to the elevation
under the pointer, wheel over it to widen or narrow the window, right click -
or the key - to centre it on the active elevation. Any of those switches the
scaling to pinch; the panel's spin boxes follow, since the panel is the one
place a Style is made.

A widget over the map, and a child of the **view** rather than of its
viewport. It was painted into the view's foreground first, in viewport
coordinates, and tore across the map as the map was panned. A scroll blits
the pixels the viewport already has and repaints only what the move exposed,
which drags anything drawn in those coordinates along with it; giving up the
blit for the whole viewport would cure that and costs a repaint of 28 ms at
zoom 15 and 104 ms at zoom 11 on a three by three Gobras set, paid on every
step of a pan.

So the bar is a widget, and the parent matters: a child of the *viewport* is
moved by the scroll with everything else in it - QWidget::scroll takes a
widget's children along, measured at -33866, -30325 after one pan - while a
child of the *view*, raised over the viewport, neither moves with the scroll
nor is repainted by the scene, and the scene is not repainted for it.

None of the tearing reproduces under the offscreen platform, which does not
blit: a panned view and a clean repaint of it come out identical, before this
change and after. The choice rests on the measurements above rather than on a
test that can show the artefact.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.ladder import format_ele
from ..surface import shade
from .surface import RAMPS, SurfaceLayer, SurfacePanel

WIDTH = 22                 # the bar
GUTTER = 64                # room for the labels, on the map side of the bar
MARGIN = 2                 # from the viewport's right edge
WHEEL_FACTOR = 1.25        # a notch of the wheel: the window a quarter wider or narrower
MIN_WIDTH = 1.0


class Legend(QWidget):
    """Reads the layer and the panel; writes the panel."""

    pinched = Signal(float, float)        # centre, width - after any change from here

    def __init__(self, view, layer: SurfaceLayer, panel: SurfacePanel, elevation=None):
        super().__init__(view)
        self.view, self.layer, self.panel, self.elevation = view, layer, panel, elevation
        self.land: tuple[float, float] | None = None        # what the bar spans
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip('the ramp as the surface shows it - drag to pinch about a height, '
                        'wheel for the width, right click to pinch on the active elevation')
        # the viewport's resize, not the view's: the view is told first and
        # lays its viewport out afterwards, so a filter on the view reads the
        # size the viewport is about to stop having - measured, 398 while the
        # view was already 900 - and the scale was left marooned against an
        # edge the map no longer had. Held by name, because the filter must
        # not ask the view for anything: Qt resizes children as it takes a
        # window down, and by then the view's C++ object can be gone
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self.panel.styleChanged.connect(self.refresh)
        self.refresh()
        self.raise_()

    # ------------------------------------------------------------ layout
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._viewport and event.type() == QEvent.Type.Resize:   # identity, no C++ asked
            self.place()
        return False

    def place(self):
        """Over the viewport's right edge, centred."""
        vp = self._viewport.geometry()
        h = max(120, int(vp.height() * 0.55))
        w = WIDTH + GUTTER
        self.setGeometry(vp.right() - w - MARGIN + 1, vp.top() + (vp.height() - h) // 2, w, h)

    def bar_rect(self) -> QRect:
        """The coloured bar, in this widget's own coordinates."""
        return QRect(self.width() - WIDTH, 8, WIDTH, self.height() - 16)

    # -------------------------------------------------------------- data
    @property
    def has_land(self) -> bool:
        return self.land is not None and self.layer.style.mode != 'hillshade'

    def refresh(self, *_):
        """What the bar spans: the land in the surface, else nothing to show."""
        shaded = self.layer.shaded
        if shaded is not None:
            land = shaded.dem[shaded.dem > 0]
            self.land = (float(land.min()), float(land.max())) if land.size and land.max() > land.min() else None
        else:
            self.land = None
        self.place()
        self.setVisible(self.has_land)
        self.update()

    def value_at(self, y: int) -> float:
        """The elevation at a row of the bar - top is high."""
        lo, hi = self.land
        r = self.bar_rect()
        t = 1.0 - (y - r.top()) / max(1, r.height() - 1)
        return lo + max(0.0, min(1.0, t)) * (hi - lo)

    def y_for(self, value: float) -> int:
        lo, hi = self.land
        r = self.bar_rect()
        t = (value - lo) / (hi - lo) if hi > lo else 0.0
        return int(round(r.top() + (1.0 - max(0.0, min(1.0, t))) * (r.height() - 1)))

    # ---------------------------------------------------------- control
    def pinch(self, centre: float | None = None, width: float | None = None):
        """Set the pinch and switch the scaling to it, through the panel."""
        s = self.layer.style.scaling
        centre = s.centre if centre is None else centre
        width = max(MIN_WIDTH, s.width if width is None else width)
        p = self.panel
        p.centre.blockSignals(True); p.width.blockSignals(True)
        p.centre.setValue(centre); p.width.setValue(width)
        p.centre.blockSignals(False); p.width.blockSignals(False)
        if p.scaling.currentText() != 'pinch':
            p.scaling.setCurrentText('pinch')          # fires _changed
        else:
            p._changed()
        # what the panel holds, which is what the layer got - a spin box clamps
        self.pinched.emit(p.centre.value(), p.width.value())

    def pinch_on_active(self):
        if self.elevation is not None:
            self.pinch(centre=self.elevation.value)

    # -- the moves, in this widget's coordinates; the event handlers call them
    def press(self, pos: QPoint, button) -> bool:
        if not self.has_land:
            return False
        if button == Qt.MouseButton.RightButton:
            self.pinch_on_active()
        elif button == Qt.MouseButton.LeftButton:
            self.pinch(centre=round(self.value_at(pos.y()), 1))
        else:
            return False
        return True

    def move(self, pos: QPoint, buttons) -> bool:
        if not self.has_land or not (buttons & Qt.MouseButton.LeftButton):
            return False
        self.pinch(centre=round(self.value_at(pos.y()), 1))
        return True

    def wheel(self, delta: int) -> bool:
        if not self.has_land or not delta:
            return False
        w = self.layer.style.scaling.width
        self.pinch(width=round(w / WHEEL_FACTOR if delta > 0 else w * WHEEL_FACTOR, 1))
        return True

    def mousePressEvent(self, event):
        self.press(event.position().toPoint(), event.button())
        event.accept()

    def mouseMoveEvent(self, event):
        self.move(event.position().toPoint(), event.buttons())
        event.accept()

    def wheelEvent(self, event):
        d = event.angleDelta()
        self.wheel(d.y() or d.x())
        event.accept()

    # ------------------------------------------------------------ paint
    def paintEvent(self, event):
        if not self.has_land:
            return
        style = self.layer.style
        ramp = RAMPS[style.ramp]()
        lo, hi = self.land
        r = self.bar_rect()
        # the bar: each row is one elevation, coloured as compose() colours a cell
        rows = np.linspace(hi, lo, r.height())
        rgba = shade.ramp_rgba(ramp, rows, style.scaling, self.layer.shaded.dem)
        img = QImage(1, r.height(), QImage.Format.Format_RGBA8888)
        for i, c in enumerate(rgba):
            img.setPixelColor(0, i, QColor(int(c[0]), int(c[1]), int(c[2])))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawImage(r, img)
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))
        font = QFont(); font.setPointSize(8); p.setFont(font)
        labels = QRect(0, r.top(), r.left() - 5, r.height())         # left of the bar, right-aligned
        right = int(Qt.AlignmentFlag.AlignRight)
        p.drawText(QRect(labels.left(), r.top() - 2, labels.width(), 14), right, f'{format_ele(hi)} m')
        p.drawText(QRect(labels.left(), r.bottom() - 11, labels.width(), 14), right, f'{format_ele(lo)} m')
        if style.scaling.mode == 'pinch':
            s = style.scaling
            y0, y1 = self.y_for(s.centre + s.width / 2), self.y_for(s.centre - s.width / 2)
            yc = self.y_for(s.centre)
            red = QColor(200, 30, 30)
            p.setPen(QPen(red, 2))
            p.drawRect(QRect(r.left() - 2, y0 - 1, r.width() + 3, max(3, y1 - y0 + 2)))
            p.setBrush(red); p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon([QPoint(r.left() - 3, yc), QPoint(r.left() - 10, yc - 5), QPoint(r.left() - 10, yc + 5)])
            p.setPen(QPen(red, 1))
            p.drawText(QRect(labels.left(), yc - 7, labels.width() - 8, 14), right, f'{format_ele(s.centre)} ±{format_ele(s.width / 2)}')
        p.end()
