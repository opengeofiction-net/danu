"""A water fill too big to draw whole every paint - roantra's sea is 113,963
points, and its rectangle every view's - is drawn cut to the view: the same
inside it, pixel for pixel, as drawn whole."""

import math

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from danu.ui import contours as C


def star(cx, cy, r0, r1, n):
    """A ring of ``n`` points in and out about (cx, cy): concave everywhere."""
    return [(cx + (r1 if k % 2 else r0) * math.cos(2 * math.pi * k / n),
             cy + (r1 if k % 2 else r0) * math.sin(2 * math.pi * k / n)) for k in range(n)]


def drawn(path: QPainterPath, size=300) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor('white'))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(C.WATER_FILL)
    p.drawPath(path)
    p.end()
    return img


def whole(rings) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for ring in rings:
        path.moveTo(*ring[0])
        for pt in ring[1:]:
            path.lineTo(*pt)
        path.closeSubpath()
    return path


def same(a: QImage, b: QImage) -> bool:
    """Pixel for pixel, but for a unit of a channel: Qt's rasteriser sums an
    edge's antialiased coverage over the edges it was given, and a path cut
    to the view gives it others - 23 pixels of 90,000 one unit apart, here."""
    if a.size() != b.size():
        return False
    for y in range(a.height()):
        for x in range(a.width()):
            p, q = a.pixel(x, y), b.pixel(x, y)
            if p != q and max(abs(((p >> s) & 255) - ((q >> s) & 255)) for s in (0, 8, 16, 24)) > 1:
                return False
    return True


def piece_of(rings):
    layer = C.ContourLayer()
    layer._put_fill(('sq', 'rel', 1), [[*r, r[0]] for r in rings])
    return layer.water_fills[('sq', 'rel', 1)]


# a sea far bigger than the view, with an island in it whose shore runs
# across the view's edge, and a second island wholly outside it
RINGS = [star(150, 150, 2000, 2400, 6000), star(150, 280, 60, 90, 400), star(900, 900, 50, 70, 300)]
VIEW = QRectF(-8, -8, 316, 316)                       # the image and a margin


def test_a_big_fill_is_cut_to_the_view_and_fills_it_as_drawn_whole():
    piece = piece_of(RINGS)
    assert piece.rings is not None, 'not big enough to be cut'
    cut = piece.fill(VIEW)
    assert cut.elementCount() < piece.path.elementCount() / 10, 'cut to nothing much'
    assert same(drawn(cut), drawn(whole(RINGS)))


def test_a_ring_round_the_whole_view_fills_all_of_it():
    big = [[(-1e5, -1e5), (1e5, -1e5), (1e5, 1e5), (-1e5, 1e5)] * 1200]      # its corners, many times
    piece = piece_of(big)
    assert same(drawn(piece.fill(VIEW)), drawn(whole(big)))


def test_the_cut_is_kept_until_the_view_moves():
    piece = piece_of(RINGS)
    first = piece.fill(VIEW)
    assert piece.fill(QRectF(VIEW)) is first
    assert piece.fill(VIEW.translated(10, 0)) is not first


def test_a_small_fill_is_drawn_whole():
    piece = piece_of([star(150, 150, 50, 80, 40)])
    assert piece.rings is None and piece.fill(VIEW) is piece.path
