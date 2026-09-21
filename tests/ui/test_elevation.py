"""Elevation control: keys, wheel, slider, pick-up, and the ladder of the square under the cursor."""

import shutil
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QPoint, QPointF, Qt                       # noqa: E402
from PySide6.QtGui import QKeySequence, QWheelEvent                  # noqa: E402
from PySide6.QtTest import QTest                                     # noqa: E402

from danu.core import edits, ladder as L                             # noqa: E402
from danu.core.square import Square, SquareName, WorkingSet, read_square, write_square   # noqa: E402
from danu.ui import mercator as m                                    # noqa: E402
from danu.ui.app import MainWindow                                   # noqa: E402
from danu.ui.config import load_layers                               # noqa: E402
from danu.ui.contours import ContourLayer                            # noqa: E402
from danu.ui.elevation import ElevationControl, ElevationPanel       # noqa: E402
from danu.ui.settings import DEFAULT_KEYS, Settings                  # noqa: E402

from .conftest import cursor_to                                      # noqa: E402


# --------------------------------------------------------------- ladder

def test_the_panel_reads_the_square_under_the_cursor_and_keeps_the_value(window, qtbot):
    w = window
    panel, control = w.elevation_panel, w.elevation
    assert control.ladder.interval == 50 and control.ladder.square == 'S24E125'
    assert 'inferred from S24E125' in panel.reading.text()
    assert panel.slider.maximum() == len(control.ladder.notches) - 1
    control.set(301)
    assert panel.slider.value() == control.ladder.index(301) and panel.value.value() == 301
    cursor_to(w, 126.5, -23.5)                                   # into the 10 m square
    assert control.ladder.interval == 10 and control.ladder.square == 'S24E126'
    assert control.value == 301                                  # the value did not jump
    assert '10 m ladder, inferred from S24E126' in panel.reading.text()
    assert panel.slider.value() == control.ladder.index(301)     # the slider grew to show it
    cursor_to(w, 125.5, -22.5)                                   # a blank square: the default
    assert control.ladder.source == 'default' and control.ladder.square == 'S23E125'


def test_opening_a_square_reads_its_own_ladder_with_the_cursor_over_a_neighbour(window, qtbot):
    """The panel named a neighbour after an open. set_working_set read the
    centre square, that ladder change refreshed the status line through the
    last cursor position, and the refresh went the whole way round to
    cursor_at - so wherever the cursor had been last read the ladder again."""
    w = window
    cursor_to(w, 126.5, -23.5)                                   # the 10 m square, in the same set
    assert w.elevation.ladder.square == 'S24E126'
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        assert w.open_working_set(w.zone_dir, SquareName(125, -24))
    qtbot.waitUntil(lambda: w.working_set is not None, timeout=5000)
    assert w.elevation.ladder.square == 'S24E125' and w.elevation.ladder.interval == 50
    lat, lon = (float(x) for x in w._status.text().split()[2:4])   # and the line says where it is now
    assert (125, -24) <= (lon, lat) <= (126, -23)                  # inside the square that was opened
    w.elevation.set(301)                                         # a ladder change is not a cursor move
    assert w.elevation.ladder.square == 'S24E125'


def test_a_zone_default_and_a_square_override_from_the_ladders_file(window, tmp_path):
    w = window
    w.settings.ladders_file.write_text('[zone."pizarrales"]\ninterval = 25\n\n[square."pizarrales/S24E126"]\nvalues = [5, 15]\n')
    w.elevation.reload_overrides()
    cursor_to(w, 125.5, -22.5)                                   # blank: the zone default now
    assert w.elevation.ladder.source == 'zone' and w.elevation.ladder.interval == 25
    cursor_to(w, 126.5, -23.5)                                   # overridden
    assert w.elevation.ladder.source == 'square' and {5, 15} <= set(w.elevation.ladder.notches)
    cursor_to(w, 125.5, -23.5)                                   # still inferred
    assert w.elevation.ladder.source == 'inferred'


# ----------------------------------------------------------------- keys

def test_the_spec_keys_drive_the_elevation(window, qtbot):
    w = window
    c = w.elevation
    c.set(100)
    w.map.setFocus()
    for key, expect in (('2', 150), ('w', 160), ('s', 150), ('x', 100), (']', 101), ('[', 100), ('0', 0)):
        QTest.keyClick(w, key)
        assert c.value == expect, (key, c.value)
    assert w.statusBar().findChild(type(w._status)) is not None and '0 m' in w._status.text()
    assert w.contours.active == 0


def test_the_steps_are_configurable_and_remembered(window, tmp_path):
    w = window
    w.elevation_panel.small.setValue(5)
    w.elevation_panel.big.setValue(25)
    w.elevation.set(100)
    w.elevation_actions['elevation.small_up'].trigger()
    w.elevation_actions['elevation.big_up'].trigger()
    assert w.elevation.value == 130
    again = Settings(tmp_path / 'danu.ini')
    assert (again.small_step, again.big_step) == (5, 25)


def test_keys_are_rebound_through_the_settings(zone, tmp_path, qtbot):
    settings = Settings(tmp_path / 'danu.ini')
    settings.set_key('elevation.big_up', 'PgUp')
    settings.set_key('elevation.sea_level', '')                  # unbound
    w = MainWindow(load_layers(), cache_dir=None, settings=settings)
    qtbot.addWidget(w)
    assert w.elevation_actions['elevation.big_up'].shortcut() == QKeySequence('PgUp')
    assert w.elevation_actions['elevation.sea_level'].shortcut().isEmpty()
    assert w.elevation_actions['elevation.small_up'].shortcut() == QKeySequence('W')
    assert 'PgUp' in w.elevation_panel.keys.text()
    assert set(DEFAULT_KEYS) == set(w.elevation_actions) | set(w.edit_actions) | set(w.file_actions) | set(w.surface_actions)


# ---------------------------------------------------------------- wheel

def wheel(w, delta, mods=Qt.KeyboardModifier.NoModifier):
    pos = QPointF(w.map.viewport().rect().center())
    return QWheelEvent(pos, w.map.viewport().mapToGlobal(pos.toPoint()), QPoint(), QPoint(0, delta),
                       Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)


def test_the_wheel_steps_the_elevation_and_alt_the_surface_opacity(window):
    w = window
    w.elevation.set(100)
    z = w.map.zoom
    w.map.wheelEvent(wheel(w, 120))
    w.map.wheelEvent(wheel(w, 120, Qt.KeyboardModifier.ShiftModifier))
    w.map.wheelEvent(wheel(w, -120))
    assert w.elevation.value == 150 and w.map.zoom == z
    before = w.surface_panel.opacity.value()
    w.map.wheelEvent(wheel(w, -120, Qt.KeyboardModifier.AltModifier))
    assert w.surface_panel.opacity.value() == before - 5
    # with alt held, X11 and Wayland deliver the wheel as a horizontal delta
    pos = QPointF(w.map.viewport().rect().center())
    sideways = QWheelEvent(pos, w.map.viewport().mapToGlobal(pos.toPoint()), QPoint(), QPoint(-120, 0),
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.AltModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.map.wheelEvent(sideways)
    assert w.surface_panel.opacity.value() == before - 10
    w.map.wheelEvent(wheel(w, 120, Qt.KeyboardModifier.ControlModifier))
    assert w.map.zoom == z + 1


# -------------------------------------------------------------- pick up

def test_space_picks_up_the_contour_under_the_cursor_and_nothing_elsewhere(window):
    w = window
    ws = w.working_set
    square = ws.squares[SquareName(126, -24)]
    way = next(square.contours())                                # the 10 m line at lat -23.9
    lon, lat = square.coords(way)[0]
    w.elevation.set(777)
    cursor_to(w, lon + 0.2, lat)                                 # on the line
    w.pick_up()
    assert w.elevation.value == 10
    cursor_to(w, 126.5, -23.85)                                  # between lines, 5 km from either
    w.pick_up()
    assert w.elevation.value == 10                               # nothing there: nothing changes
    w.elevation.set(777)
    w.elevation_actions['elevation.pick_up'].trigger()
    assert w.elevation.value == 777


def test_pick_up_reaches_eight_pixels_from_a_line_and_no_further(window):
    w = window
    square = w.working_set.squares[SquareName(126, -24)]
    lon, lat = square.coords(next(square.contours()))[0]            # the 10 m line
    x, y = m.lonlat_to_scene(lon + 0.2, lat)
    per_px = 1.0 / m.scale_for_zoom(w.map.zoom)                    # scene units in a pixel at this zoom
    for px, expect in ((4, 10), (20, 777)):
        w.elevation.set(777)
        cursor_to(w, *m.scene_to_lonlat(x, y + px * per_px))
        w.pick_up()
        assert w.elevation.value == expect, px


def test_a_set_without_contours_after_one_with_them_leaves_nothing_to_pick(zone):
    layer = ContourLayer()
    layer.set_working_set(WorkingSet.open(zone, SquareName(126, -24), 1))
    x, y = m.lonlat_to_scene(126.5, -23.7)
    assert layer.pick(x, y, 1e6) is not None
    layer.set_working_set(WorkingSet.open(zone, SquareName(120, -24), 1))   # nothing there
    assert layer.pick(x, y, 1e12) is None


def test_the_layer_picks_the_nearest_segment_within_tolerance(zone):
    ws = WorkingSet.open(zone, SquareName(126, -24), 1)
    layer = ContourLayer()
    layer.set_working_set(ws)
    x, y = m.lonlat_to_scene(126.5, -23.7)                       # on the 30 m line
    hit = layer.pick(x, y, 1e-9 + abs(m.lonlat_to_scene(126.5, -23.7001)[1] - y))
    assert hit is not None and hit[1].ele == 30 and hit[2] < 1e-6
    x, y = m.lonlat_to_scene(126.5, -23.74)                      # 4 km south of it
    assert layer.pick(x, y, abs(m.lonlat_to_scene(126.5, -23.73)[1] - y)) is None
    near = layer.pick(x, y, abs(m.lonlat_to_scene(126.5, -23.69)[1] - y))
    assert near is not None and near[1].ele == 30
    assert ContourLayer().pick(0, 0, 1e9) is None


def test_the_active_level_is_drawn_heavier(zone, qtbot):
    from PySide6.QtGui import QColor, QImage, QPainter
    from danu.ui.mapview import MapView
    ws = WorkingSet.open(zone, SquareName(126, -24), 1)
    view = MapView(); view.resize(600, 600); qtbot.addWidget(view); view.show(); qtbot.waitExposed(view)
    layer = ContourLayer(); layer.set_working_set(ws); view.scene().addItem(layer)
    view.set_zoom(12); view.center_on_lonlat(126.5, -23.7)

    def coloured_pixels():
        # over the whole view: the graticule's label is the same in both
        # renders, so the difference is the line's weight
        img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
        img.fill(QColor('white'))
        p = QPainter(img); view.render(p); p.end()
        w, h = img.width(), img.height()
        return sum(1 for x in range(0, w, 4) for y in range(h) if QColor(img.pixel(x, y)).hsvSaturation() > 40)

    plain = coloured_pixels()
    layer.set_active(30.0)
    heavier = coloured_pixels()
    assert layer.drawn_levels == 1 and 0 < plain < heavier * 0.6
