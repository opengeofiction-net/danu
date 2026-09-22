"""The colour scale: the legend that is also the pinch control."""

import numpy as np
import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt                 # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent      # noqa: E402

from danu.surface import ramp, shade                                   # noqa: E402
from danu.ui.legend import WHEEL_FACTOR, Legend                        # noqa: E402
from danu.ui.mapview import MapView                                    # noqa: E402
from danu.ui.surface import SurfaceLayer, SurfacePanel                 # noqa: E402

from .test_surface import synthetic                                    # noqa: E402


def test_ramp_rgba_colours_a_value_as_compose_colours_the_cell():
    shaded = synthetic()
    for scaling in (shade.Scaling('auto'), shade.Scaling('manual', lo=100, hi=300), shade.Scaling('pinch', centre=200, width=20)):
        composed = shade.compose(shaded, ramp.spectral(), scaling, mode='relief')
        r, c = 10, 20
        legend = shade.ramp_rgba(ramp.spectral(), np.array([shaded.dem[r, c]]), scaling, shaded.dem)[0]
        assert tuple(legend[:3]) == tuple(composed[r, c, :3]), scaling


@pytest.fixture
def parts(qtbot):
    view = MapView(); view.resize(600, 500); qtbot.addWidget(view); view.show(); qtbot.waitExposed(view)
    layer = SurfaceLayer(); layer.set_shaded(synthetic()); view.scene().addItem(layer)
    panel = SurfacePanel(layer); qtbot.addWidget(panel)
    legend = Legend(view, layer, panel)
    return view, layer, panel, legend


def render(widget) -> QImage:
    return widget.grab().toImage()          # grab includes the child widgets, which is the point here


def test_the_legend_spans_the_land_sits_at_the_right_edge_and_is_painted(parts):
    view, layer, panel, legend = parts
    lo, hi = legend.land
    land = layer.shaded.dem[layer.shaded.dem > 0]
    assert (lo, hi) == (float(land.min()), float(land.max()))
    r = legend.bar_rect()
    vp = view.viewport().geometry()
    assert legend.isVisible() and legend.parentWidget() is view          # the view, not its viewport
    assert vp.right() - 4 <= legend.geometry().right() <= vp.right()     # against the map's edge
    assert r.left() > 0                                                  # labels on the map side of the bar
    assert legend.value_at(r.top()) == pytest.approx(hi) and legend.value_at(r.bottom()) == pytest.approx(lo)
    assert legend.y_for(legend.value_at(r.top() + 30)) == r.top() + 30
    img = render(legend)
    colours = {QColor(img.pixel(r.center().x(), r.top() + i * (r.height() - 1) // 4)).name() for i in range(5)}
    assert len(colours) >= 4                                   # blue through red down the bar
    panel.mode.setCurrentText('hillshade')
    assert not legend.has_land and not legend.isVisible()       # nothing to colour, nothing shown


def test_a_pan_does_not_move_the_legend(parts):
    """What can be held to here: a scroll takes the children of the viewport
    with it - the bar ended up at -33866, -30325 as one - and leaves a child
    of the view where it is. The tearing itself needs a platform that blits,
    which the offscreen one does not, so it is not what this asserts."""
    view, layer, panel, legend = parts
    view.set_zoom(10); view.center_on_lonlat(10, 10)
    before = legend.geometry()
    for i in range(1, 6):
        view.center_on_lonlat(10 + 0.3 * i, 10.1 * (1 + 0.001 * i))
    assert legend.parentWidget() is view and legend.geometry() == before
    assert view.viewport().geometry().contains(legend.geometry())     # and still over the map


def test_dragging_sets_the_centre_and_switches_to_pinch(parts):
    view, layer, panel, legend = parts
    assert panel.scaling.currentText() == 'auto'
    fired = []
    legend.pinched.connect(lambda c, w: fired.append((c, w)))
    r = legend.bar_rect()
    y = r.top() + r.height() // 3
    assert legend.press(QPoint(r.center().x(), y), Qt.MouseButton.LeftButton)
    want = round(legend.value_at(y), 1)
    assert panel.scaling.currentText() == 'pinch' and panel.centre.value() == want
    assert layer.style.scaling.mode == 'pinch' and layer.style.scaling.centre == want and fired[-1][0] == want
    y2 = r.top() + r.height() // 2
    assert legend.move(QPoint(r.center().x(), y2), Qt.MouseButton.LeftButton)
    assert layer.style.scaling.centre == round(legend.value_at(y2), 1)
    assert not legend.move(QPoint(r.center().x(), y2), Qt.MouseButton.NoButton)     # no button: not a drag
    # through a real event, as the window delivers it
    pos = QPointF(r.center().x(), r.top() + 5)
    legend.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, legend.mapToGlobal(pos.toPoint()),
                                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert layer.style.scaling.centre == round(legend.value_at(r.top() + 5), 1)
    # the marker is painted where the centre is
    img = render(legend)
    yc = legend.y_for(layer.style.scaling.centre)
    assert any(QColor(img.pixel(r.left() - 6, yc + dy)).red() > 150 for dy in range(-2, 3))


def test_the_wheel_over_the_bar_sets_the_width_and_never_below_a_metre(parts):
    view, layer, panel, legend = parts
    w0 = panel.width.value()
    assert legend.wheel(-120)
    assert layer.style.scaling.mode == 'pinch' and layer.style.scaling.width == pytest.approx(round(w0 * WHEEL_FACTOR, 1))
    for _ in range(40):
        legend.wheel(120)
    assert layer.style.scaling.width == 1.0
    # a wheel over the legend is the legend's: it never reaches the map
    z = view.zoom
    pos = QPointF(legend.bar_rect().center())
    legend.wheelEvent(QWheelEvent(pos, legend.mapToGlobal(pos.toPoint()), QPoint(), QPoint(0, -120),
                                  Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                                  Qt.ScrollPhase.NoScrollPhase, False))
    assert view.zoom == z and layer.style.scaling.width == pytest.approx(1.2, abs=0.06)


def test_right_click_and_the_key_pinch_on_the_active_elevation(window):
    w = window
    w.surface.set_shaded(synthetic()); w.legend.refresh()
    w.elevation.set(222)
    assert w.legend.press(w.legend.bar_rect().center(), Qt.MouseButton.RightButton)
    assert w.surface.style.scaling.mode == 'pinch' and w.surface.style.scaling.centre == 222
    w.elevation.set(333)
    w.map.setFocus()
    from PySide6.QtTest import QTest
    QTest.keyClick(w, 'p')
    assert w.surface.style.scaling.centre == 333 and w.surface_panel.centre.value() == 333
