"""Danu's icon, drawn rather than drawn by hand: contours of a hill over a
shore, in the relief ramp's colours. Writes the PNGs the window and the Linux
desktop entry take, and the Windows .ico, which is those PNGs in one file.

    python packaging/icon/make_icon.py

The output is committed; run this again only to change the icon.
"""

import math
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parents[2]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def blob(c: QPointF, r: float) -> QPainterPath:
    """A lobed closed outline round ``c``, mean radius ``r``."""
    path = QPainterPath()
    n = 96
    for k in range(n + 1):
        t = 2 * math.pi * k / n
        rr = r * (1 + 0.13 * math.sin(3 * t + 0.6) + 0.07 * math.cos(2 * t))
        pt = QPointF(c.x() + rr * math.cos(t), c.y() + rr * 0.9 * math.sin(t))
        path.moveTo(pt) if k == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256
    p.scale(s, s)
    tile = QRectF(8, 8, 240, 240)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#3d7ab8'))                         # the sea
    p.drawRoundedRect(tile, 44, 44)
    clip = QPainterPath()
    clip.addRoundedRect(tile, 44, 44)
    p.setClipPath(clip)
    # an island and its contours: each level the same lobed outline, smaller,
    # drawn from the shore up to the summit; fewer levels where pixels are few
    levels = [('#cfe3b0', 96), ('#d8c486', 66), ('#c49a5d', 40), ('#a8764a', 18)]
    if size <= 24:
        levels = levels[:3]
    pen = QPen(QColor('#5b3d22'), 5 if size >= 64 else 9 if size >= 32 else 13)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    for i, (colour, r) in enumerate(levels):
        p.setBrush(QColor(colour))
        p.setPen(pen if i else QPen(QColor('#2f5f8f'), pen.widthF()))
        p.drawPath(blob(QPointF(124 + i * 6, 132 - i * 6), r))
    p.end()
    return img


def png(img: QImage) -> bytes:
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(dev, 'PNG')
    return bytes(buf)


def ico(images: list[QImage]) -> bytes:
    """An .ico of PNG entries, which Windows has read since Vista."""
    blobs = [png(i) for i in images]
    head = struct.pack('<HHH', 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b''
    for img, blob in zip(images, blobs, strict=True):
        w = img.width() if img.width() < 256 else 0      # 0 means 256
        entries += struct.pack('<BBBBHHII', w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return head + entries + b''.join(blobs)


def main() -> int:
    QGuiApplication(sys.argv[:1])
    images = [draw(n) for n in SIZES]
    out = ROOT / 'danu' / 'ui' / 'icons'
    out.mkdir(exist_ok=True)
    for n, img in zip(SIZES, images, strict=True):
        img.save(str(out / f'danu-{n}.png'))
    (ROOT / 'packaging' / 'windows').mkdir(exist_ok=True)
    (ROOT / 'packaging' / 'windows' / 'danu.ico').write_bytes(ico(images))
    return 0


if __name__ == '__main__':
    sys.exit(main())
