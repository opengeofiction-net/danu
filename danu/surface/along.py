"""What lies along a line drawn on the map - H3b, measure and profile.

The line is the mapper's: points clicked, or a drag's two ends. Along it, the
surface the layer draws, read a cell at a time as the status line reads the
one under the cursor - so the profile and the reading agree - and the
distance on the ground, in metres. The contours and the water it crosses are
the layer's to find; this puts them at their distance along.

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

CLIMB_MIN_M = 1.0                # a climb under this is the surface's rounding


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
        """The metres climbed and fallen along it, as drawn."""
        k = self._known()
        if len(k) < 2:
            return 0.0, 0.0
        d = np.diff(self.ground[k])
        return float(d[d > 0].sum()), abs(float(d[d < 0].sum()))

    @property
    def highest(self) -> float | None:
        k = self._known()
        return float(np.nanmax(self.ground)) if len(k) else None

    @property
    def lowest(self) -> float | None:
        k = self._known()
        return float(np.nanmin(self.ground)) if len(k) else None

    def climbs(self, least: float = CLIMB_MIN_M) -> list[tuple[float, float, float]]:
        """Where the ground climbs, walking the line as drawn - each from a
        trough to the peak after it, a rise or a fall of ``least`` the turn:
        (from, to metres along, the climb). So a line drawn down a valley
        shows where water drawn that way could not run.

        Not the grade's ground above the lowest the line has been, which was
        tried first: on gobras' rolling lowland it shaded nearly the whole of
        a 25 km line, everything after its first dip."""
        k = self._known()
        if len(k) < 2:
            return []
        g = self.ground[k]
        out, lo, hi = [], 0, None
        for j in range(1, len(g)):
            if hi is None:
                if g[j] <= g[lo]:
                    lo = j                         # the last of a flat trough
                elif g[j] - g[lo] >= least:
                    hi = j
            elif g[j] > g[hi]:
                hi = j                             # the first of a flat top
            elif g[hi] - g[j] >= least:
                out.append((lo, hi))
                lo, hi = j, None
        if hi is not None:
            out.append((lo, hi))
        return [(float(self.dist[k[a]]), float(self.dist[k[b]]), float(g[b] - g[a])) for a, b in out]

    def at(self, d: float) -> tuple[float, float]:
        """The scene point ``d`` metres along."""
        i = int(np.clip(np.searchsorted(self.dist, d), 1, len(self.dist) - 1))
        d0, d1 = self.dist[i - 1], self.dist[i]
        t = 0.0 if d1 == d0 else (d - d0) / (d1 - d0)
        p = self.scene[i - 1] + (self.scene[i] - self.scene[i - 1]) * min(max(t, 0.0), 1.0)
        return float(p[0]), float(p[1])

    def ground_at(self, d: float) -> float | None:
        if self.ground is None:
            return None
        i = int(np.clip(np.searchsorted(self.dist, d), 0, len(self.dist) - 1))
        v = self.ground[i]
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


def sample(dem: np.ndarray, scene_rect: tuple, scene: np.ndarray) -> np.ndarray:
    """The surface at each scene point, as the status line reads it: the
    cell it falls in. NaN off the grid."""
    left, top, right, bottom = scene_rect
    rows, cols = dem.shape
    c = np.floor((scene[:, 0] - left) / (right - left) * cols).astype(np.int64)
    r = np.floor((scene[:, 1] - top) / (bottom - top) * rows).astype(np.int64)
    ok = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
    out = np.full(len(scene), np.nan)
    out[ok] = dem[r[ok], c[ok]]
    return out


def along(points, shaded=None) -> Along:
    """The line through scene ``points`` and the surface along it - a cell
    apart where there is a surface, and the drawn points alone where not."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if shaded is not None:
        left, _, right, _ = shaded.scene_rect
        step = (right - left) / shaded.dem.shape[1]
    else:
        step = float('inf')
    scene, at = line(pts, step)
    dist = _metres(scene)
    ground = sample(shaded.dem, shaded.scene_rect, scene) if shaded is not None else None
    return Along(scene, dist, ground, [float(dist[i]) for i in at])


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
