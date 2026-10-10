"""Measure and profile (H3b): a line on the map, its length, the ground along
it from the exact surface, and what it crosses.

Over the fixture's Tenmetre square, whose five contours run east-west at 10
to 50 m from -23.9 to -23.5, a surface rising north to match them.
"""

import math
from itertools import pairwise

import numpy as np
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent

from danu.core import edits
from danu.core.profile import seg_lengths
from danu.core.square import SquareName
from danu.surface import shade
from danu.ui import mercator as m

TEN = SquareName(126, -24)
R = 6378137.0


def rising_north():
    """10 m at -23.9 to 50 m at -23.5, as the contours say; 500 m cells."""
    x0 = R * math.radians(126.0)
    y1 = R * math.log(math.tan(math.pi / 4 + math.radians(-23.0) / 2))
    rows, cols, metres = 260, 230, 500.0
    ys = y1 - (np.arange(rows) + 0.5) * metres
    lat = np.degrees(np.arctan(np.sinh(ys / R)))
    dem = np.repeat((10 + (lat + 23.9) * 100)[:, None], cols, axis=1).astype(np.float32)
    return shade.Shaded(dem=dem, shade=np.zeros(dem.shape, np.uint8),
                        geotransform=(x0, metres, 0.0, y1, 0.0, -metres), metres=metres)


def mouse(w, kind, pos, button=Qt.MouseButton.LeftButton, buttons=None):
    buttons = button if buttons is None else buttons
    return QMouseEvent(kind, QPointF(pos), w.map.viewport().mapToGlobal(pos), button, buttons,
                       Qt.KeyboardModifier.NoModifier)


def px(w, lon, lat) -> QPoint:
    return w.map.mapFromScene(QPointF(*m.lonlat_to_scene(lon, lat)))


def click(w, lon, lat):
    pos = px(w, lon, lat)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos, buttons=Qt.MouseButton.NoButton))


def double_click(w, lon, lat):
    click(w, lon, lat)
    w.map.mouseDoubleClickEvent(mouse(w, QEvent.Type.MouseButtonDblClick, px(w, lon, lat)))


def key(w, k):
    w.map.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def w(window):
    window.map.set_zoom(9)
    window.map.center_on_lonlat(126.3, -23.7)
    window.surface.set_shaded(rising_north())
    window.surface.set_preview(False)
    window.edit_actions['tool.measure'].trigger()
    return window


def test_m_is_the_tool_and_its_button_and_menu_follow(w):
    assert w.editor.tool == 'measure'
    assert w.controls.measure.isChecked() and w.edit_actions['tool.measure'].isChecked()
    assert w.edit_actions['tool.measure'].shortcut().toString() == 'M'


def test_a_line_clicked_north_is_measured_on_the_ground_with_its_profile(w):
    click(w, 126.3, -23.95)
    click(w, 126.3, -23.70)
    double_click(w, 126.3, -23.45)
    t = w.measure
    assert t.done and len(t.points) == 3, t.points
    a = t.result
    want = seg_lengths([(126.3, -23.95), (126.3, -23.70), (126.3, -23.45)]).sum()
    assert a.length == pytest.approx(want, rel=2e-3)
    g0, g1 = a.ends
    assert g0 == pytest.approx(5, abs=2) and g1 == pytest.approx(55, abs=2)
    # the five contours, at their values and in order going north
    assert [e for _, e in a.contours] == [10, 20, 30, 40, 50]
    assert all(d0 < d1 for (d0, _), (d1, _) in pairwise(a.contours))
    # 100 m a degree of latitude: 0.41 m a 458 m cell, 0.05 degrees
    assert a.steepest == pytest.approx(0.0515, abs=0.002)
    s = w.profile_dock.summary.text()
    assert s.startswith(f'{a.length / 1000:,.2f} km') and 'crosses 5 contours' in s and '%' in s
    assert 'steepest 0.1°' in s
    assert w.profile_dock.isVisible() and w.profile_dock.plot.isVisible()
    assert w.statusBar().currentMessage() == s


def test_drawn_downhill_it_only_falls(w):
    click(w, 126.3, -23.45)
    double_click(w, 126.3, -23.95)
    assert w.measure.result.up_down[0] == pytest.approx(0, abs=1)
    assert 'along it 0 m up' in w.profile_dock.summary.text()


def test_a_drag_is_a_straight_line(w):
    a, b = px(w, 126.2, -23.85), px(w, 126.4, -23.65)
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, a))
    for f in range(1, 11):
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, a + (b - a) * f / 10,
                                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    assert w.statusBar().currentMessage().startswith('measuring:')
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, b, buttons=Qt.MouseButton.NoButton))
    assert w.measure.done and len(w.measure.points) == 2
    assert [e for _, e in w.measure.result.contours] == [20, 30]


def test_while_drawn_the_status_line_reads_the_distance_and_the_ground(w):
    click(w, 126.3, -23.9)
    pos = px(w, 126.3, -23.6)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    text = w.statusBar().currentMessage()
    assert text.startswith('measuring: ') and 'from the start' in text and '+30 m' in text, text


def test_a_preview_refuses_the_ground_and_the_exact_build_brings_it_back(w):
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    w.surface.set_preview(True)
    w.measure.surface_changed()
    assert w.measure.why_not.startswith('a preview stands')
    assert 'a preview stands' in w.profile_dock.summary.text() and not w.profile_dock.plot.isVisible()
    w.surface.set_preview(False)
    w.measure.surface_changed()
    assert w.measure.why_not is None and w.profile_dock.plot.isVisible()


def test_with_no_surface_it_measures_the_distance_and_says_why_no_more(w):
    w.surface.set_shaded(None)
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    assert 'no surface built' in w.profile_dock.summary.text()
    assert 'crosses 5 contours' in w.profile_dock.summary.text()


def test_water_crossed_is_shown_at_its_level_between_the_levels_given(w):
    sq = w.working_set.squares[TEN]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in range(3)]
    w.editor.do(sq, edits.AddWay(wid, ids, [(126.1, -23.75), (126.3, -23.75), (126.5, -23.75)],
                                 {'waterway': 'stream', 'name': 'Test Burn'}))
    sq.nodes[ids[0]].tags['ele'] = '40'
    sq.nodes[ids[2]].tags['ele'] = '20'
    click(w, 126.4, -23.85)
    double_click(w, 126.4, -23.65)
    (d, label, level), = w.measure.result.water
    assert label == 'stream "Test Burn"' and level == pytest.approx(25, abs=0.5)
    assert 'and 1 water' in w.profile_dock.summary.text()


def test_backspace_takes_a_point_back_and_escape_clears_then_leaves(w):
    click(w, 126.3, -23.9)
    click(w, 126.3, -23.8)
    key(w, Qt.Key.Key_Backspace)
    assert len(w.measure.points) == 1
    click(w, 126.3, -23.7)
    key(w, Qt.Key.Key_Return)
    assert w.measure.done
    key(w, Qt.Key.Key_Escape)
    assert not w.measure.points and w.measure.result is None and w.editor.tool == 'measure'
    assert w.profile_dock.summary.text() == 'No line measured.'
    key(w, Qt.Key.Key_Escape)
    assert w.editor.tool == 'select'


def test_a_click_after_a_line_ended_begins_another(w):
    click(w, 126.3, -23.9)
    double_click(w, 126.3, -23.7)
    click(w, 126.2, -23.6)
    assert not w.measure.done and len(w.measure.points) == 1


def test_one_point_is_not_a_line(w):
    click(w, 126.3, -23.9)
    key(w, Qt.Key.Key_Return)
    assert not w.measure.done and 'two points or more' in w.statusBar().currentMessage()


def test_an_ended_line_stays_with_the_other_tools_and_follows_the_edits(w, qtbot):
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    w.editor.set_tool('select')
    assert w.measure.done and len(w.measure.result.contours) == 5
    (thirty,) = [way for way in w.working_set.squares[TEN].contours() if way.ele == 30]
    w.editor.selection = None
    w.editor.do(w.working_set.squares[TEN], edits.DeleteWay(thirty.id))
    assert len(w.measure.result.contours) == 5, 'measured again at the edit, not once they pause'
    qtbot.waitUntil(lambda: [e for _, e in w.measure.result.contours] == [10, 20, 40, 50], timeout=2000)


def test_a_profile_closed_stays_closed_when_the_line_is_measured_again(w):
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    w.profile_dock.close()
    w.measure.surface_changed()
    assert not w.profile_dock.isVisible()
    click(w, 126.2, -23.95)
    double_click(w, 126.2, -23.45)
    assert w.profile_dock.isVisible(), 'a new line ended and its profile not shown'


def test_a_line_half_drawn_goes_with_its_tool(w):
    click(w, 126.3, -23.9)
    w.editor.set_tool('draw')
    assert not w.measure.points


def test_hovering_the_profile_marks_the_place_on_the_map(w):
    click(w, 126.3, -23.45)
    double_click(w, 126.3, -23.95)                      # downhill: nothing shaded to hover over
    plot = w.profile_dock.plot
    plot.repaint()
    mid = QPointF(plot._x(w.measure.result.length / 2), plot.height() / 2)
    plot.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, mid, plot.mapToGlobal(mid.toPoint()),
                                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier))
    assert w.measure.hover_d == pytest.approx(w.measure.result.length / 2, rel=0.02)
    plot.leaveEvent(QEvent(QEvent.Type.Leave))
    assert w.measure.hover_d is None


def press_plot(w, d):
    plot = w.profile_dock.plot
    plot.repaint()
    at = QPointF(plot._x(d), plot.height() / 2)
    plot.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, at, plot.mapToGlobal(at.toPoint()),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))


def test_a_click_on_the_profile_takes_the_map_to_the_place(w):
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    w.map.set_zoom(6)
    w.map.center_on_lonlat(120.0, -20.0)
    press_plot(w, w.measure.result.length / 4)
    lon, lat = w.map.center_lonlat()
    assert lon == pytest.approx(126.3, abs=0.01) and lat == pytest.approx(-23.825, abs=0.01)
    assert w.map.zoom > 6


def test_the_profile_switches_to_slope_and_back(w):
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    d = w.profile_dock
    assert d.plot.mode == 'elevation' and d.mode_buttons['elevation'].isChecked()
    d.mode_buttons['slope'].click()
    assert d.plot.mode == 'slope' and d.mode_buttons['slope'].isChecked()
    assert np.array_equal(d.plot._values(), w.measure.result.slope, equal_nan=True)
    d.plot.repaint()                                   # draws the slope without falling over
    press_plot(w, w.measure.result.length / 2)          # and a click still shows the place
    assert w.map.center_lonlat()[1] == pytest.approx(-23.70, abs=0.01)
    d.mode_buttons['elevation'].click()
    assert d.plot.mode == 'elevation'


def test_the_window_tells_it_when_a_preview_lands_and_when_the_exact_build_does(w):
    from danu.ui.surface import Built
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    w._surface_previewed([], 0.05)
    assert w.measure.why_not.startswith('a preview stands')
    w._surface_built_shown(Built(rising_north()))
    assert w.measure.why_not is None and w.measure.result.ends is not None


def test_a_lake_crossed_is_at_its_level(w):
    sq = w.working_set.squares[TEN]
    alloc = w.editor.history.alloc(sq)
    wid, ids = alloc.take(), [alloc.take() for _ in range(4)]
    ring = [(126.60, -23.78), (126.70, -23.78), (126.70, -23.72), (126.60, -23.72)]
    w.editor.do(sq, edits.AddWay(wid, ids, ring, {'natural': 'water', 'name': 'Loch Test', 'ele': '33'}))
    w.editor.do(sq, edits.ExtendWayWithExisting(wid, True, ids[0]))
    click(w, 126.65, -23.85)
    double_click(w, 126.65, -23.65)
    assert [(label, level) for _, label, level in w.measure.result.water] == [('water "Loch Test"', 33.0)] * 2


def test_the_profile_is_filled_in_the_colours_the_map_gives_each_place(w):
    """The legend's colours at the ground along the line; at its slope while
    the map shows slope; none in hillshade - and the plot told to repaint
    when the map's colours change."""
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    a = w.measure.result
    plot = w.profile_dock.plot
    got = plot.colourer(a)
    assert np.array_equal(got, w.legend.colours(a.ground))
    assert not np.array_equal(got[0], got[-1]), 'the ground rises 50 m and the colour does not follow'
    w.surface_panel.mode.setCurrentText('slope')
    assert np.array_equal(plot.colourer(a), w.legend.colours(a.slope))
    assert np.array_equal(w.legend.colours(a.slope), shade.SLOPE_RAMP.rgba(a.slope))
    w.surface_panel.mode.setCurrentText('hillshade')
    assert plot.colourer(a) is None
    plot.repaint()                                      # grey, without falling over
    told = []
    w.legend.changed.connect(lambda: told.append(1))
    w.surface_panel.mode.setCurrentText('relief')
    assert told


def test_the_fill_is_the_colour_under_the_line(w, qtbot):
    """Rendered: a pixel just under the line, mid-profile, is the legend's
    colour for the ground there."""
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    plot = w.profile_dock.plot
    plot.resize(600, 200)
    img = plot.grab().toImage()
    a = w.measure.result
    d = a.length / 2
    i = int(np.searchsorted(a.dist, d))
    want = w.legend.colours(a.ground)[i]
    px = img.pixelColor(int(plot._x(d)), int(plot.height() - 20))
    assert (px.red(), px.green(), px.blue()) == pytest.approx(tuple(int(c) for c in want[:3]), abs=3)


@pytest.mark.parametrize('dark', [True, False])
def test_the_contours_are_in_the_texts_colour_light_or_dark(w, dark):
    """Charcoal dots were lost on a dark theme's plot: white there, black
    in a light one."""
    from PySide6.QtGui import QPalette
    click(w, 126.3, -23.95)
    double_click(w, 126.3, -23.45)
    plot = w.profile_dock.plot
    pal = QPalette(plot.palette())
    ink, ground = (QColor(255, 255, 255), QColor(30, 30, 30)) if dark else (QColor(0, 0, 0), QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.Text, ink)
    pal.setColor(QPalette.ColorRole.Base, ground)
    plot.setPalette(pal)
    plot.resize(600, 200)
    img = plot.grab().toImage()
    d, e = w.measure.result.contours[2]
    ys = [float(v) for v in w.measure.result.ground[~np.isnan(w.measure.result.ground)]] + [10, 50]
    lo, hi = min(ys), max(ys)
    pad = max(1.0, (hi - lo) * 0.08)
    lo, hi = lo - pad, hi + pad
    top, bottom = 6, plot.height() - 16
    y = bottom - (bottom - top) * (e - lo) / (hi - lo)
    px = img.pixelColor(round(plot._x(d)), round(y))
    assert abs(px.red() - ink.red()) < 60 and abs(px.blue() - ink.blue()) < 60, (px.name(), ink.name())
