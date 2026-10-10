"""What lies along a line drawn on the map - H3b, measure and profile.

The line is the mapper's: points clicked, or a drag's two ends. Along it, the
surface the layer draws, read a cell at a time as the status line reads the
one under the cursor - so the profile and the reading agree - and its slope as
the map's slope mode shows it, with the distance on the ground in metres. The
contours and the water it crosses are the layer's to find; this puts them at
their distance along.

From the exact surface only (the spec's "a profile ... is taken from an exact
surface or refuses to answer"): the caller asks whether a preview stands.

No Qt and no GDAL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..core.profile import seg_lengths
from ..ui import mercator as m
from . import shade


@dataclass
class Along:
    """A line and what lies along it. ``scene`` and ``dist`` are the
    densified points, a cell apart, and the metres along to each; ``ground``
    the surface at each, NaN off it; ``vertex_d`` the metres along to each
    drawn point."""
    scene: np.ndarray
    dist: np.ndarray
    ground: np.ndarray | None
    vertex_d: list
    slope: np.ndarray | None = None                   # the ground's slope at each, degrees
    contours: list = field(default_factory=list)      # (metres along, ele)
    water: list = field(default_factory=list)         # (metres along, label, level or None)

    @property
    def length(self) -> float:
        return float(self.dist[-1]) if len(self.dist) else 0.0

    def _known(self):
        g = self.ground
        return np.flatnonzero(~np.isnan(g)) if g is not None else np.zeros(0, dtype=int)

    @property
    def ends(self) -> tuple[float, float] | None:
        """The ground at the first and last points the surface reaches."""
        k = self._known()
        return (float(self.ground[k[0]]), float(self.ground[k[-1]])) if len(k) else None

    @property
    def up_down(self) -> tuple[float, float]:
        """The metres climbed and fallen along it, as drawn - between
        neighbouring cells, so a line off the surface and back on does not
        climb across the gap."""
        if self.ground is None or len(self.ground) < 2:
            return 0.0, 0.0
        d = np.diff(self.ground)
        d = d[~np.isnan(d)]
        return float(d[d > 0].sum()), abs(float(d[d < 0].sum()))

    @property
    def highest(self) -> float | None:
        k = self._known()
        return float(np.nanmax(self.ground)) if len(k) else None

    @property
    def lowest(self) -> float | None:
        k = self._known()
        return float(np.nanmin(self.ground)) if len(k) else None

    @property
    def steepest(self) -> float | None:
        """The steepest the ground is anywhere along it, in degrees."""
        if self.slope is None or np.isnan(self.slope).all():
            return None
        return float(np.nanmax(self.slope))

    def at(self, d: float) -> tuple[float, float]:
        """The scene point ``d`` metres along."""
        i = int(np.clip(np.searchsorted(self.dist, d), 1, len(self.dist) - 1))
        d0, d1 = self.dist[i - 1], self.dist[i]
        t = 0.0 if d1 == d0 else (d - d0) / (d1 - d0)
        p = self.scene[i - 1] + (self.scene[i] - self.scene[i - 1]) * min(max(t, 0.0), 1.0)
        return float(p[0]), float(p[1])

    def ground_at(self, d: float) -> float | None:
        return self._value_at(self.ground, d)

    def slope_at(self, d: float) -> float | None:
        return self._value_at(self.slope, d)

    def _value_at(self, values, d: float) -> float | None:
        if values is None:
            return None
        i = int(np.clip(np.searchsorted(self.dist, d), 0, len(self.dist) - 1))
        v = values[i]
        return None if np.isnan(v) else float(v)

    def distance_of(self, k: int, t: float) -> float:
        """Metres along to a place on drawn segment ``k``, ``t`` of the way
        from its start to its end."""
        return self.vertex_d[k] + t * (self.vertex_d[k + 1] - self.vertex_d[k])


def _metres(scene: np.ndarray) -> np.ndarray:
    lonlat = [m.scene_to_lonlat(float(x), float(y)) for x, y in scene]
    return np.concatenate([[0.0], np.cumsum(seg_lengths(lonlat))]) if len(lonlat) > 1 else np.zeros(1)


def line(points, step: float) -> tuple[np.ndarray, list]:
    """The drawn points, in scene units, with points put between them no
    more than ``step`` apart; and the index of each drawn point in it."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    out, at = [pts[0]], [0]
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        k = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
        out.extend(a + (b - a) * (i / k) for i in range(1, k + 1))
        at.append(len(out) - 1)
    return np.array(out), at


def cells(shape: tuple, scene_rect: tuple, scene: np.ndarray):
    """The row and column of the cell each scene point falls in, and which
    are on the grid."""
    left, top, right, bottom = scene_rect
    rows, cols = shape
    c = np.floor((scene[:, 0] - left) / (right - left) * cols).astype(np.int64)
    r = np.floor((scene[:, 1] - top) / (bottom - top) * rows).astype(np.int64)
    return r, c, (r >= 0) & (r < rows) & (c >= 0) & (c < cols)


def sample(dem: np.ndarray, scene_rect: tuple, scene: np.ndarray) -> np.ndarray:
    """The surface at each scene point: the cell it falls in, NaN off the
    grid. The status line's reading is this, so the two agree."""
    r, c, ok = cells(dem.shape, scene_rect, scene)
    out = np.full(len(scene), np.nan)
    out[ok] = dem[r[ok], c[ok]]
    return out


def slope(shaded, scene: np.ndarray) -> np.ndarray:
    """The ground's slope at each scene point, in degrees, as the map's slope
    mode and the status line give it - `shade.slope_degrees` over the cells
    the line's box holds and one round it, read at the cell each point is
    in. NaN off the grid."""
    r, c, ok = cells(shaded.dem.shape, shaded.scene_rect, scene)
    out = np.full(len(scene), np.nan)
    if not ok.any():
        return out
    rows, cols = shaded.dem.shape
    r0, r1 = max(int(r[ok].min()) - 1, 0), min(int(r[ok].max()) + 2, rows)
    c0, c1 = max(int(c[ok].min()) - 1, 0), min(int(c[ok].max()) + 2, cols)
    deg = shade.slope_degrees(shaded.dem[r0:r1, c0:c1], shaded.geotransform, r0)
    out[ok] = deg[r[ok] - r0, c[ok] - c0]
    return out


def along(points, shaded=None) -> Along:
    """The line through scene ``points`` and the surface along it - a cell
    apart where there is a surface, and the drawn points alone where not."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if shaded is not None:
        # a cell's width: the Mercator grids are square-celled (shade.py)
        left, _, right, _ = shaded.scene_rect
        step = (right - left) / shaded.dem.shape[1]
    else:
        step = float('inf')
    scene, at = line(pts, step)
    dist = _metres(scene)
    if shaded is None:
        return Along(scene, dist, None, [float(dist[i]) for i in at])
    ground = sample(shaded.dem, shaded.scene_rect, scene)
    return Along(scene, dist, ground, [float(dist[i]) for i in at], slope=slope(shaded, scene))


def level_between(levels: list[tuple[float, float]], d: float) -> float | None:
    """A level at ``d`` metres along a water way from the levels its
    vertices carry, (metres, level) in order: between the two either side,
    and nothing beyond the first or the last - a river's level is not
    carried past where anyone gave it one."""
    for (d0, e0), (d1, e1) in zip(levels[:-1], levels[1:], strict=True):
        if d0 <= d <= d1:
            return e0 if d1 == d0 else e0 + (e1 - e0) * (d - d0) / (d1 - d0)
    if len(levels) == 1 and abs(levels[0][0] - d) < 1e-6:
        return levels[0][1]
    return None
