"""Colour ramps: elevation in, colour out.

Two, as R10 asks. The traditional hypsometric ramp - green through brown to
white - is not defined here. It is ``relief.ramp`` beside this file, the
gdaldem colour-relief table the build applies to every published relief
raster, so the editor colours ground exactly as the topo tiles do. The
server's ``server/etc/relief.ramp`` is a symlink to it; there is one file.
The spectral ramp is for reading relief where the traditional one would be all
one green: blue through green and yellow to red, over whatever range the caller
gives it.

A ramp is stops, linear between them, clamped beyond. ``colour`` answers one
value; ``rgba`` answers an array, for the rasters phase 2 will paint.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np

RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Ramp:
    name: str
    values: tuple[float, ...]        # ascending
    colours: tuple[RGBA, ...]        # one per value

    def __post_init__(self):
        if len(self.values) != len(self.colours) or len(self.values) < 2:
            raise ValueError(f'ramp {self.name!r}: need at least two stops, one colour each')
        if any(b <= a for a, b in zip(self.values, self.values[1:])):
            raise ValueError(f'ramp {self.name!r}: stops must ascend')

    @property
    def lo(self) -> float:
        return self.values[0]

    @property
    def hi(self) -> float:
        return self.values[-1]

    def colour(self, value: float) -> RGBA:
        """Linear between the stops either side; the end colours beyond."""
        v = np.asarray(self.values)
        c = np.asarray(self.colours, dtype=float)
        return tuple(int(round(np.interp(value, v, c[:, i]))) for i in range(4))

    def rgba(self, values: np.ndarray) -> np.ndarray:
        """(..., 4) uint8 for an array of values, the same arithmetic as colour."""
        v = np.asarray(self.values)
        c = np.asarray(self.colours, dtype=float)
        out = np.stack([np.interp(values, v, c[:, i]) for i in range(4)], axis=-1)
        return np.rint(out).astype(np.uint8)

    def rescaled(self, lo: float, hi: float) -> 'Ramp':
        """The same colours over a new range: for the spectral ramp, which
        means nothing in absolute metres and is stretched over the ground in
        view. A hypsometric ramp should not be rescaled, and is not, by the
        callers that know which they hold."""
        if hi <= lo:
            hi = lo + 1.0
        t = (np.asarray(self.values) - self.lo) / (self.hi - self.lo)
        return Ramp(self.name, tuple(float(lo + x * (hi - lo)) for x in t), self.colours)

    @classmethod
    def from_gdaldem(cls, text: str, name: str) -> 'Ramp':
        """gdaldem colour-relief format: ``value R G B [A]`` per line, ``#``
        comments. Alpha defaults to opaque, as it does for gdaldem."""
        values, colours = [], []
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) not in (4, 5):
                raise ValueError(f'{name} line {n}: want "value R G B [A]", got {raw!r}')
            values.append(float(parts[0]))
            rgb = [int(p) for p in parts[1:4]]
            a = int(parts[4]) if len(parts) == 5 else 255
            if any(not 0 <= x <= 255 for x in rgb + [a]):
                raise ValueError(f'{name} line {n}: a channel is outside 0..255')
            colours.append((rgb[0], rgb[1], rgb[2], a))
        return cls(name, tuple(values), tuple(colours))


def traditional() -> Ramp:
    """The tiles' own hypsometric ramp, in absolute metres."""
    text = resources.files('danu.surface').joinpath('relief.ramp').read_text(encoding='utf-8')
    return Ramp.from_gdaldem(text, 'relief.ramp')


def spectral(lo: float = 0.0, hi: float = 1.0) -> Ramp:
    """Blue - green - yellow - orange - red, over lo..hi. ColorBrewer's
    Spectral, reversed so that up is warm."""
    stops = ((43, 131, 186, 255), (171, 221, 164, 255), (255, 255, 191, 255),
             (253, 174, 97, 255), (215, 25, 28, 255))
    return Ramp('spectral', (0.0, 0.25, 0.5, 0.75, 1.0), stops).rescaled(lo, hi)


def relief_ramp_path() -> Path:
    return Path(str(resources.files('danu.surface').joinpath('relief.ramp')))
