"""The canvas, offscreen. Skipped where there is no Qt, which is the plain
tests job; the ui job installs PySide6 and runs these on both runners."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QPoint, QPointF, Qt      # noqa: E402
from PySide6.QtGui import QWheelEvent                # noqa: E402

from danu.ui import config, mercator as m            # noqa: E402
from danu.ui.app import MainWindow                   # noqa: E402
from danu.ui.mapview import Graticule, MapView       # noqa: E402


@pytest.fixture
def view(qtbot):
    v = MapView()
    v.resize(800, 600)
    qtbot.addWidget(v)
    v.show()
    qtbot.waitExposed(v)
    return v


def test_the_view_starts_at_a_sensible_zoom_and_clamps(view):
    assert 0 <= view.zoom <= m.MAX_ZOOM
    view.set_zoom(99)
    assert view.zoom == m.MAX_ZOOM
    view.set_zoom(-4)
    assert view.zoom == 0


def test_zoom_changes_the_view_scale_and_says_so(view, qtbot):
    view.set_zoom(4)
    with qtbot.waitSignal(view.zoomChanged) as got:
        view.set_zoom(7)
    assert got.args == [7]
    assert abs(view.transform().m11() - m.scale_for_zoom(7)) < 1e-12


def test_fit_bounds_shows_the_square_whole_and_centred(view):
    view.fit_bounds(87, 20, 88, 21)
    lon, lat = view.center_lonlat()
    assert abs(lon - 87.5) < 0.01 and abs(lat - 20.5) < 0.01
    r = view.visible_scene_rect()
    x0, y0 = m.lonlat_to_scene(87, 21)
    x1, y1 = m.lonlat_to_scene(88, 20)
    assert r.left() <= x0 and r.right() >= x1 and r.top() <= y0 and r.bottom() >= y1


def test_the_wheel_steps_one_zoom_about_the_cursor(view, qtbot):
    view.fit_bounds(87, 20, 88, 21)
    z = view.zoom
    pos = QPointF(view.viewport().width() * 0.25, view.viewport().height() * 0.25)
    before = view.mapToScene(pos.toPoint())
    ev = QWheelEvent(pos, view.mapToGlobal(pos), QPoint(), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    view.wheelEvent(ev)
    assert view.zoom == z + 1
    after = view.mapToScene(pos.toPoint())
    # the point under the cursor stays under the cursor, to well under a
    # pixel: centerOn alone leaves a pixel and it compounds across steps
    px = m.tile_size(view.zoom) / 256
    assert abs(after.x() - before.x()) < px * 0.01
    assert abs(after.y() - before.y()) < px * 0.01
    for _ in range(3):
        view.wheelEvent(ev)
    after = view.mapToScene(pos.toPoint())
    px = m.tile_size(view.zoom) / 256
    assert abs(after.x() - before.x()) < px * 0.01 and abs(after.y() - before.y()) < px * 0.01


def test_moving_the_mouse_reports_lon_lat(view, qtbot):
    view.fit_bounds(87, 20, 88, 21)
    centre = view.viewport().rect().center()
    with qtbot.waitSignal(view.cursorMoved) as got:
        qtbot.mouseMove(view.viewport(), centre)
    lon, lat = got.args
    assert abs(lon - 87.5) < 0.02 and abs(lat - 20.5) < 0.02


def test_graticule_spacing_follows_the_scale():
    assert Graticule.step_for(m.scale_for_zoom(2)) == 30.0
    assert Graticule.step_for(m.scale_for_zoom(5)) == 5.0
    assert Graticule.step_for(m.scale_for_zoom(9)) == 1.0
    assert Graticule.step_for(m.scale_for_zoom(19)) == 1.0


def test_the_window_constructs_shows_and_reports_the_cursor(qtbot):
    w = MainWindow(config.load_layers())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert w.windowTitle() == 'Danu'
    assert 'z' in w._status.text()
    assert [l.name for l in w.layers] == ['ogf-carto', 'ttopo', 'cyclogf']
