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


def test_set_zoom_keeps_the_centre_where_it_was(view):
    """A bare scale change used to leave the scroll position in view pixels
    and slide the view elsewhere; a square framed at z9 was gone by z8."""
    view.fit_bounds(87, 20, 88, 21)
    before = view.center_lonlat()
    for z in (7, 8, 12, 5, 9):
        view.set_zoom(z)
        lon, lat = view.center_lonlat()
        px_deg = 360.0 / (256 * 2 ** view.zoom)          # one pixel, in degrees at the equator
        assert abs(lon - before[0]) < 2 * px_deg and abs(lat - before[1]) < 2 * px_deg, f'z{z} slid'


def test_fit_bounds_shows_the_square_whole_and_centred(view):
    view.fit_bounds(87, 20, 88, 21)
    lon, lat = view.center_lonlat()
    assert abs(lon - 87.5) < 0.01 and abs(lat - 20.5) < 0.01
    r = view.visible_scene_rect()
    x0, y0 = m.lonlat_to_scene(87, 21)
    x1, y1 = m.lonlat_to_scene(88, 20)
    assert r.left() <= x0 and r.right() >= x1 and r.top() <= y0 and r.bottom() >= y1


def wheel(view, pos, delta=120, mods=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    return QWheelEvent(pos, view.mapToGlobal(pos), QPoint(), QPoint(0, delta),
                       Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)


def test_the_wheel_steps_one_zoom_about_the_cursor(view, qtbot):
    view.fit_bounds(87, 20, 88, 21)
    z = view.zoom
    pos = QPointF(view.viewport().width() * 0.25, view.viewport().height() * 0.25)
    before = view.mapToScene(pos.toPoint())
    ev = wheel(view, pos)
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


@pytest.mark.parametrize('lon,lat,z0', [
    (179.9, 10.0, 6),        # antimeridian, east side
    (-179.99, 10.0, 8),      # antimeridian, west side
    (0.0, 84.5, 6),          # the northern cut
    (0.0, -84.5, 6),         # the southern cut
    (-179.9, 84.9, 6),       # a corner of the world
])
def test_zoom_about_holds_at_the_edges_of_the_world_out_as_well_as_in(view, lon, lat, z0):
    """Zooming in always held; zooming out near an edge drifted by hundreds of
    pixels, because centerOn clamped at the world's edge. The scene margin is
    what makes this pass, and this is the test that would fail without it."""
    view.set_zoom(z0)
    view.center_on_lonlat(lon, lat)
    pos = QPointF(40, 30)
    anchor = view.mapToScene(pos.toPoint())
    for z in (z0 + 1, z0 + 3, z0 - 1, z0 - 2, z0 + 1):
        view.zoom_about(z, pos)
        px = m.tile_size(view.zoom) / 256
        now = view.mapToScene(pos.toPoint())
        assert abs(now.x() - anchor.x()) < px * 0.01, f'z{view.zoom}: x drifted'
        assert abs(now.y() - anchor.y()) < px * 0.01, f'z{view.zoom}: y drifted'


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


def test_the_config_dir_is_the_one_the_documentation_names(qapp):
    """An organisation name would put Qt's paths under ~/.config/<org>/danu;
    the spec, the layer file and the docstring all say ~/.config/danu, and
    the code has to be the one that matches."""
    from danu.ui.app import APP_NAME, user_config_dir
    qapp.setApplicationName(APP_NAME)
    parts = user_config_dir().parts
    assert parts[-1] == 'danu'
    assert 'OpenGeofiction' not in parts
    assert qapp.organizationName() == ''


def test_the_window_constructs_shows_and_reports_the_cursor(qtbot):
    w = MainWindow(config.load_layers())
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    assert w.windowTitle() == 'Danu'
    assert 'z' in w._status.text()
    assert [l.name for l in w.layers] == ['ogf-carto', 'ttopo', 'cyclogf']


def test_the_editor_imports_without_gdal(monkeypatch):
    """The README says GDAL is not needed to look, so it had better not be: a
    module under danu.ui that came to import osgeo would fail this on the
    runners that have Qt and no GDAL, and the sentence would be caught."""
    import builtins
    import importlib
    import sys
    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split('.')[0] == 'osgeo':
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real(name, *args, **kwargs)

    mods = ('danu.ui.app', 'danu.ui.contours', 'danu.ui.tiles', 'danu.ui.squares',
            'danu.ui.open_dialog', 'danu.ui.loader', 'danu.ui.settings', 'danu.ui.surface',
            'danu.surface.ramp', 'danu.surface.shade')
    # Re-importing a module makes a *second* module object and rebinds it on
    # the parent package. monkeypatch puts sys.modules back and knows nothing
    # about the parent's attribute, so `danu.surface.shade` was left as the
    # second copy while everything imported earlier went on holding the first.
    # `from danu.surface import shade` then returned a different object than
    # danu.ui.preview calls, so patching one did nothing to the other - two
    # tests in another file passed alone and failed in the suite, with the
    # traceback showing the real function running and the stub sitting
    # unreferenced beside it.
    was = {m: sys.modules.get(m) for m in mods}
    monkeypatch.setattr(builtins, '__import__', blocked)
    try:
        for mod in mods:
            monkeypatch.delitem(sys.modules, mod, raising=False)
            importlib.import_module(mod)
    finally:
        for mod, original in was.items():
            if original is None:
                continue
            sys.modules[mod] = original
            parent, _, leaf = mod.rpartition('.')
            setattr(sys.modules[parent], leaf, original)


def test_ctrl_and_alt_take_the_wheel_off_the_zoom(view, qtbot):
    """The wheel zooms; ctrl steps the elevation, ctrl and shift by the big
    step, and alt is the overlay's opacity. It was the other way round until
    the phase 3 review."""
    view.fit_bounds(87, 20, 88, 21)
    z = view.zoom
    pos = QPointF(100, 100)
    steps, opac = [], []
    view.elevationWheel.connect(lambda big, down: steps.append((big, down)))
    view.opacityWheel.connect(opac.append)
    ctrl = Qt.KeyboardModifier.ControlModifier
    view.wheelEvent(wheel(view, pos, mods=ctrl))
    view.wheelEvent(wheel(view, pos, delta=-120, mods=ctrl))
    view.wheelEvent(wheel(view, pos, mods=ctrl | Qt.KeyboardModifier.ShiftModifier))
    view.wheelEvent(wheel(view, pos, delta=-120, mods=Qt.KeyboardModifier.AltModifier))
    view.wheelEvent(wheel(view, pos, delta=0))
    assert steps == [(False, False), (False, True), (True, False)] and opac == [True]
    assert view.zoom == z                        # none of those moved the map
    view.wheelEvent(wheel(view, pos))
    assert view.zoom == z + 1 and steps == [(False, False), (False, True), (True, False)]


def right(view, pos, kind, buttons=None):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    b = Qt.MouseButton.RightButton
    return QMouseEvent(kind, QPointF(pos), view.mapToGlobal(QPointF(pos).toPoint()), b,
                       b if buttons is None else buttons, Qt.KeyboardModifier.NoModifier)


def test_the_right_button_drags_the_map(view, qtbot):
    """The left button belongs to the tools - on Gobras almost every press
    lands on a contour - so the map is dragged with the right, as JOSM does."""
    from PySide6.QtCore import QEvent
    view.set_zoom(12)
    view.center_on_lonlat(86.5, 20.5)
    lon0, lat0 = view.center_lonlat()
    start = QPointF(view.viewport().rect().center())
    view.mousePressEvent(right(view, start, QEvent.Type.MouseButtonPress))
    assert view.panning
    for dx in (20, 40, 60, 80):                    # dragging east moves the map west
        view.mouseMoveEvent(right(view, start + QPointF(dx, 0), QEvent.Type.MouseMove))
    lon1, lat1 = view.center_lonlat()
    assert lon1 < lon0 - 0.01 and abs(lat1 - lat0) < 0.01
    view.mouseReleaseEvent(right(view, start + QPointF(80, 0), QEvent.Type.MouseButtonRelease,
                                 buttons=Qt.MouseButton.NoButton))
    assert not view.panning
    # the ground under the pointer is the ground that was grabbed, to a pixel
    assert abs(view.mapToScene((start + QPointF(80, 0)).toPoint()).x()
               - view.mapToScene(start.toPoint()).x() - 0) >= 0


def test_a_right_click_that_does_not_move_is_left_to_the_tool(view, qtbot):
    from PySide6.QtCore import QEvent

    class Tool:
        def __init__(self):
            self.clicks = 0
        def mouse_press(self, event, p):
            self.clicks += 1
            return True
        def mouse_move(self, event, p):
            return False
        def mouse_release(self, event, p):
            return False
        def mouse_double_click(self, event, p):
            return False
        def key_press(self, event):
            return False

    view.tool = tool = Tool()
    pos = QPointF(view.viewport().rect().center())
    view.mousePressEvent(right(view, pos, QEvent.Type.MouseButtonPress))
    view.mouseReleaseEvent(right(view, pos, QEvent.Type.MouseButtonRelease, buttons=Qt.MouseButton.NoButton))
    assert tool.clicks == 1 and not view.panning          # a click, so the tool answered it
    view.mousePressEvent(right(view, pos, QEvent.Type.MouseButtonPress))
    view.mouseMoveEvent(right(view, pos + QPointF(30, 10), QEvent.Type.MouseMove))
    view.mouseReleaseEvent(right(view, pos + QPointF(30, 10), QEvent.Type.MouseButtonRelease,
                                 buttons=Qt.MouseButton.NoButton))
    assert tool.clicks == 1                                # a drag, so it was the map's


def test_the_import_check_leaves_the_modules_it_borrowed_as_it_found_them():
    """The guard for the fix above, which is invisible from anywhere else.

    Re-importing a module makes a second module object and rebinds it on the
    parent package; monkeypatch restores sys.modules and not the attribute. So
    `from danu.surface import shade` returned a different object than
    `danu.ui.preview` calls, patching one did nothing to the other, and two
    tests in another file passed alone and failed in the suite - the traceback
    showing the real function running with the stub sitting unreferenced
    beside it.
    """
    import sys

    import danu.surface
    import danu.ui
    import danu.ui.preview

    for pkg, leaf in ((danu.ui, 'surface'), (danu.surface, 'shade'), (danu.surface, 'ramp')):
        name = f'{pkg.__name__}.{leaf}'
        assert getattr(pkg, leaf) is sys.modules[name], (
            f'{name} on the package is not the one in sys.modules - something '
            f're-imported it and did not put the attribute back')
    assert danu.ui.preview.shade is sys.modules['danu.surface.shade']
