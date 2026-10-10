"""Zooms 19 and 20 (H6): the tiles stop at 19 and are drawn stretched past
it; the editor's own layers go on, and at 20 a river inside a narrow river
area comes apart from the area's outline under the pick radius - which at 19
it does not.

The case is the Water of Meeonoa on gobras: a ``waterway=stream`` a median
1.4 m from the outline of the ``natural=water`` + ``water=river`` it runs in.
Here it is drawn in the fixture's Tenmetre square, at -23.7.
"""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QPointF

from danu.core import edits
from danu.core.square import SquareName
from danu.ui import mercator as m
from danu.ui.tools import PICK_PX

TEN = SquareName(126, -24)
APART_M = 1.4
LAT = -23.7


@pytest.fixture
def river(window):
    """The stream along -23.7, and its river area's outline 1.4 m north."""
    sq = window.working_set.squares[TEN]
    alloc = window.editor.history.alloc(sq)
    north = LAT + APART_M / 110540.0
    stream, area = alloc.take(), alloc.take()
    window.editor.do(sq, edits.AddWay(stream, [alloc.take() for _ in range(3)],
                                      [(126.30, LAT), (126.31, LAT), (126.32, LAT)], {'waterway': 'stream'}))
    ring = [alloc.take() for _ in range(4)]
    window.editor.do(sq, edits.AddWay(area, ring, [(126.30, north), (126.32, north), (126.32, north + 0.001),
                                                   (126.30, north + 0.001)], {'natural': 'water', 'water': 'river'}))
    window.editor.do(sq, edits.ExtendWayWithExisting(area, True, ring[0]))
    window.map.center_on_lonlat(126.31, LAT)
    return window, stream, area


def test_the_map_goes_to_20_and_stops(window):
    window.map.set_zoom(99)
    assert window.map.zoom == m.MAX_ZOOM == 20
    assert not window.controls.zoom_in.isEnabled()


def test_past_19_the_tiles_are_19s_stretched_not_fetched_deeper(window):
    asked = []
    window.fetcher.request = lambda layer, z, x, y: asked.append(z)
    window.map.set_zoom(20)
    window.map.center_on_lonlat(126.31, LAT)
    window.map.viewport().grab()
    assert asked and max(asked) == 19


def test_a_zoom_about_a_point_at_20_keeps_it_where_it_was(window):
    window.map.set_zoom(20)
    at = QPointF(300, 200)
    a = window.map.mapToScene(at.toPoint())
    window.map.zoom_about(19, at)
    window.map.zoom_about(20, at)
    b = window.map.mapToScene(at.toPoint())
    assert (a - b).manhattanLength() < 1e-6


@pytest.mark.parametrize('zoom, picked', [(19, 'area'), (20, 'stream')])
def test_a_click_just_off_the_stream_is_the_stream_only_at_20(river, zoom, picked):
    """Three pixels off the stream toward the outline: at 19 the outline is
    5 px away and nearer, at 20 it is 10 px away and the stream is."""
    w, stream, area = river
    w.map.set_zoom(zoom)
    x, y = m.lonlat_to_scene(126.31, LAT)
    scale = m.scale_for_zoom(zoom)
    _, ya = m.lonlat_to_scene(126.31, LAT + APART_M / 110540.0)
    assert (y - ya) * scale > PICK_PX if zoom == 20 else (y - ya) * scale < PICK_PX
    hit = w.contours.pick_water(x, y - 3 / scale, PICK_PX / scale)
    assert hit is not None and hit[1].id == {'area': area, 'stream': stream}[picked]
