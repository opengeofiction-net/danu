"""Web Mercator, as the map canvas sees it.

The scene is the whole world in Web Mercator, measured in pixels at
``SCENE_ZOOM``: 2**19 * 256 units to a side. Every zoom level is then a
uniform scale of that one scene, so panning and zooming are view transforms
and nothing in the scene moves. A tile at zoom z is a square of
``TILE * 2**(SCENE_ZOOM - z)`` scene units.

Pure arithmetic, no Qt, so it is tested on the runners that have no Qt and
so the numbers can be checked by hand.

This is for display. Contours stay in degrees and the surface is solved in
degrees; this only decides where a thing is drawn on the canvas. The server
also uses Mercator - it warps the DEM to it for the hillshades the styles
expect, through PROJ - and tests/test_mercator_proj.py asserts this
arithmetic agrees with PROJ's to a millionth of a pixel, so the two ways of
projecting cannot quietly differ.
"""

from __future__ import annotations

import math
from typing import Iterator

TILE = 256
SCENE_ZOOM = 19
MAX_ZOOM = SCENE_ZOOM
WORLD = TILE * (1 << SCENE_ZOOM)
# the Mercator cut, where y would go to infinity
MAX_LAT = math.degrees(math.atan(math.sinh(math.pi)))   # 85.0511...


def lonlat_to_scene(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = (lon + 180.0) / 360.0 * WORLD
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * WORLD
    return x, y


def scene_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = x / WORLD * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / WORLD))))
    return lon, lat


def scale_for_zoom(zoom: float) -> float:
    """The view scale that shows the scene at this zoom: 1.0 at SCENE_ZOOM."""
    return 2.0 ** (zoom - SCENE_ZOOM)


def zoom_for_scale(scale: float) -> float:
    return SCENE_ZOOM + math.log2(scale)


def tile_size(zoom: int) -> float:
    """A zoom-z tile's side, in scene units."""
    return TILE * 2.0 ** (SCENE_ZOOM - zoom)


def tile_rect(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of a tile in scene units. x is not wrapped:
    a tile drawn past the antimeridian while panning has x >= 2**z here and
    ``wrap_x`` gives the one to fetch."""
    s = tile_size(zoom)
    return x * s, y * s, (x + 1) * s, (y + 1) * s


def wrap_x(x: int, zoom: int) -> int:
    return x % (1 << zoom)


def tiles_in_rect(left: float, top: float, right: float, bottom: float,
                  zoom: int) -> Iterator[tuple[int, int, int]]:
    """Every (zoom, x, y) tile touching a scene rectangle. y is clamped to the
    world, because there is nothing above or below it; x is not, because the
    world continues to the east and west and a view that straddles the
    antimeridian needs both sides drawn."""
    if right <= left or bottom <= top:
        return
    s = tile_size(zoom)
    n = 1 << zoom
    x0 = math.floor(left / s)
    x1 = math.ceil(right / s) - 1
    y0 = max(0, math.floor(top / s))
    y1 = min(n - 1, math.ceil(bottom / s) - 1)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            yield zoom, x, y


def zoom_to_fit(width_px: float, height_px: float,
                left: float, top: float, right: float, bottom: float,
                max_zoom: int = MAX_ZOOM) -> int:
    """The largest integer zoom at which a scene rectangle fits a viewport."""
    w = max(right - left, 1e-9)
    h = max(bottom - top, 1e-9)
    scale = min(width_px / w, height_px / h)
    return max(0, min(max_zoom, math.floor(zoom_for_scale(scale))))
