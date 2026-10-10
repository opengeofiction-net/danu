"""Magnify - H3d, a loupe at the cursor.

Contours are drawn at cell precision and the map is not: the build burns a
contour into the cells it crosses, and at the zoom a mapper draws at a 1"
cell is a pixel or two. The loupe draws the map around the cursor again,
magnified, without changing the zoom the mapper is working at - the surface
there sharp-edged, a cell a square of its own colour, with the cells' grid
over it once a cell is big enough to see, so which cells a contour runs
through, and where two contours come into one, can be read before the node is
placed rather than after the build.

The scene is rendered again into the loupe, not the screen's pixels scaled:
lines stay a pixel wide, and what is being drawn shows in it as it is drawn.
The tiles are the map's own, scaled up: they are the background, not the
work, and a loupe swept across the map would otherwise ask the tile server
for tiles one to four zooms deeper wherever it went. The cursor is its centre, and it does
not take the mouse - a click through it lands where the cross is.

A child of the view, for the reason ``danu.ui.legend`` records.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget

from .tiles import TileLayer

SIZE = 240                     # the loupe's diameter, in pixels
FACTORS = (2, 4, 8, 16)        # the magnifications shift and the wheel step through
FACTOR = 4
GRID_PX = 8                    # a cell this wide in the loupe, or wider, has its grid drawn


class Loupe(QWidget):
    def __init__(self, view, surface=None):
        super().__init__(view)
        self.view, self.surface = view, surface
        self.factor = FACTOR
        self.on = False
        self.drawn_grid = 0        # grid lines drawn by the last paint, for the tests
        self._at: QPointF | None = None       # the cursor, in viewport pixels
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(SIZE, SIZE)
        self.hide()
        view.pointerMoved.connect(self.follow)
        view.pointerLeft.connect(self._left)
        view.zoomChanged.connect(lambda _: self.update())
        view.scene().changed.connect(lambda _: self.isVisible() and self.update())

    # ------------------------------------------------------------- state
    def set_on(self, on: bool):
        self.on = bool(on)
        if not self.on:
            self.hide()
        elif self._at is not None:
            self.follow(self._at)

    def step(self, down: bool) -> None:
        """A magnification further along FACTORS, or back."""
        i = FACTORS.index(self.factor) + (-1 if down else 1)
        self.factor = FACTORS[max(0, min(len(FACTORS) - 1, i))]
        self.update()

    def follow(self, at: QPointF):
        """The cursor moved to ``at``, in the viewport's pixels."""
        self._at = QPointF(at)
        if not self.on:
            return
        vp = self.view.viewport().geometry()
        self.move(int(round(vp.left() + at.x() - SIZE / 2)), int(round(vp.top() + at.y() - SIZE / 2)))
        self.show()
        self.raise_()
        self.update()

    def _left(self):
        self._at = None
        self.hide()

    def source(self) -> QRectF:
        """The scene shown: SIZE pixels at the view's scale times the factor,
        about the scene point under the cursor."""
        c = self.view.mapToScene(self._at.toPoint())
        half = SIZE / 2 / (self.view.transform().m11() * self.factor)
        return QRectF(c.x() - half, c.y() - half, 2 * half, 2 * half)

    # ------------------------------------------------------------- paint
    def paintEvent(self, _event):
        self.drawn_grid = 0
        if self._at is None:
            return
        p = QPainter(self)
        ring = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addEllipse(ring)
        p.setClipPath(clip)
        p.fillRect(self.rect(), self.view.backgroundBrush())
        source, target = self.source(), QRectF(self.rect())
        tiles = [i for i in self.view.scene().items() if isinstance(i, TileLayer)]
        for t in tiles:
            t.zoom_at_most = self.view.zoom    # what the map has, not a deeper zoom fetched
        if self.surface is not None:
            self.surface.smooth = False        # a cell its own colour, edge to edge
        try:
            self.view.scene().render(p, target, source, Qt.AspectRatioMode.IgnoreAspectRatio)
        finally:
            for t in tiles:
                t.zoom_at_most = None
            if self.surface is not None:
                self.surface.smooth = True
        self._grid(p, source)
        p.setClipping(False)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._cross(p)
        base = self.palette().color(QPalette.ColorRole.Window)
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        p.setPen(QPen(ink, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
        label = f'×{self.factor}'
        font = QFont(p.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        p.setFont(font)
        box = p.fontMetrics().boundingRect(label).adjusted(-4, -1, 4, 1)
        box.moveCenter(QPointF(SIZE / 2, SIZE - 16).toPoint())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(base.red(), base.green(), base.blue(), 210))
        p.drawRoundedRect(QRectF(box), 3, 3)
        p.setPen(ink)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    def _grid(self, p: QPainter, source: QRectF):
        """The surface's cells, where one is GRID_PX or more across."""
        cells = self.surface.cells() if self.surface is not None and self.surface.isVisible() else None
        if cells is None:
            return
        rect, cols, rows = cells
        sx = SIZE / source.width()
        cw, ch = rect.width() / cols, rect.height() / rows
        if cw * sx < GRID_PX:
            return
        shown = rect.intersected(source)
        if shown.isEmpty():
            return

        def px(x, y):
            return QPointF((x - source.left()) * sx, (y - source.top()) * sx)
        pen = QPen(QColor(0, 0, 0, 60), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        c0 = math.ceil((shown.left() - rect.left()) / cw)
        c1 = math.floor((shown.right() - rect.left()) / cw)
        for c in range(c0, c1 + 1):
            x = rect.left() + c * cw
            p.drawLine(px(x, shown.top()), px(x, shown.bottom()))
            self.drawn_grid += 1
        r0 = math.ceil((shown.top() - rect.top()) / ch)
        r1 = math.floor((shown.bottom() - rect.top()) / ch)
        for r in range(r0, r1 + 1):
            y = rect.top() + r * ch
            p.drawLine(px(shown.left(), y), px(shown.right(), y))
            self.drawn_grid += 1

    def _cross(self, p: QPainter):
        """Where a click lands: a cross with a gap at its centre, dark on
        light so it reads over any ground."""
        c = SIZE / 2
        for colour, width in ((QColor(255, 255, 255, 220), 3.0), (QColor(0, 0, 0, 230), 1.2)):
            p.setPen(QPen(colour, width))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                p.drawLine(QPointF(c + 4 * dx, c + 4 * dy), QPointF(c + 12 * dx, c + 12 * dy))
