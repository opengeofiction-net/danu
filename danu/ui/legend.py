"""The colour scale on the map: the legend, and the control for pinch - R11.

A bar down the right of the view shows the ramp as the surface is coloured
now: over the land's range, through the scaling in force, so a pinched ramp
reads as a band of colour between saturated ends, exactly as the map does.
Ticks name the ends and the pinch centre.

It is the control too. Drag on the bar to set the pinch centre to the
elevation under the pointer, wheel over it to widen or narrow the window,
right click - or the key - to centre it on the active elevation. Any of
those switches the scaling to pinch; the panel's spin boxes follow, since
the panel is the one place a Style is made.

Painted as the view's foreground, in device pixels, not as a widget over
the viewport: a child widget there was repainted over by the scene on every
update, and a scene item would scale with the map. The view asks it about
mouse events before the tools see them.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from ..core.ladder import format_ele
from ..surface import shade
from .surface import RAMPS, SurfaceLayer, SurfacePanel

WIDTH = 22                 # the bar
GUTTER = 64                # room for the labels, on the map side of the bar
MARGIN = 2                 # from the view's right edge
WHEEL_FACTOR = 1.25        # a notch of the wheel: the window a quarter wider or narrower
MIN_WIDTH = 1.0


class Legend(QObject):
    """Reads the layer and the panel; writes the panel; paints in the view."""

    pinched = Signal(float, float)        # centre, width - after any change from here

    def __init__(self, view, layer: SurfaceLayer, panel: SurfacePanel, elevation=None):
        super().__init__(view)
        self.view, self.layer, self.panel, self.elevation = view, layer, panel, elevation
        self.land: tuple[float, float] | None = None        # what the bar spans
        self.panel.styleChanged.connect(self.refresh)
        view.hud.append(self)
        self.refresh()

    # ------------------------------------------------------------ layout
    @property
    def visible(self) -> bool:
        return self.land is not None and self.layer.style.mode != 'hillshade'

    def rect(self) -> QRect:
        """Where it sits, in viewport pixels: against the right edge, centred,
        the labels on the map side of the bar."""
        vp = self.view.viewport().rect()
        h = max(120, int(vp.height() * 0.55))
        return QRect(vp.right() - GUTTER - WIDTH - MARGIN + 1, vp.top() + (vp.height() - h) // 2, WIDTH + GUTTER, h)

    def bar_rect(self) -> QRect:
        r = self.rect()
        return QRect(r.right() - WIDTH + 1, r.top() + 8, WIDTH, r.height() - 16)

    def contains(self, pos: QPoint) -> bool:
        return self.visible and self.rect().contains(pos)

    # -------------------------------------------------------------- data
    def refresh(self, *_):
        """What the bar spans: the land in the surface, else nothing to show."""
        shaded = self.layer.shaded
        if shaded is not None:
            land = shaded.dem[shaded.dem > 0]
            self.land = (float(land.min()), float(land.max())) if land.size and land.max() > land.min() else None
        else:
            self.land = None
        self.view.viewport().update()

    def value_at(self, y: int) -> float:
        """The elevation at a viewport row of the bar - top is high."""
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

    # the view asks these first, with viewport positions; True when taken
    def press(self, pos: QPoint, button) -> bool:
        if not self.contains(pos):
            return False
        if button == Qt.MouseButton.RightButton:
            self.pinch_on_active()
        elif button == Qt.MouseButton.LeftButton:
            self.pinch(centre=round(self.value_at(pos.y()), 1))
        return True

    def move(self, pos: QPoint, buttons) -> bool:
        if not self.visible or not (buttons & Qt.MouseButton.LeftButton) or not self._dragging(pos):
            return False
        self.pinch(centre=round(self.value_at(pos.y()), 1))
        return True

    def _dragging(self, pos: QPoint) -> bool:
        # a drag that began on the bar may wander off it sideways; only the row matters
        r = self.rect()
        return r.left() - 40 <= pos.x() <= r.right()

    def wheel(self, pos: QPoint, delta: int) -> bool:
        if not self.contains(pos) or not delta:
            return False
        w = self.layer.style.scaling.width
        self.pinch(width=round(w / WHEEL_FACTOR if delta > 0 else w * WHEEL_FACTOR, 1))
        return True

    # ------------------------------------------------------------ paint
    def paint(self, p: QPainter):
        """In viewport pixels; the view has reset the transform."""
        if not self.visible:
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
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawImage(r, img)
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))
        font = QFont(); font.setPointSize(8); p.setFont(font)
        labels = QRect(self.rect().left(), r.top(), GUTTER - 5, r.height())      # left of the bar, right-aligned
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
        p.restore()
