"""The surface layer, its panel and its builder, offscreen and without a
build: a synthetic Shaded stands in for what the worker would return."""

import numpy as np
import pytest

pytest.importorskip('PySide6')
from PySide6.QtGui import QColor, QImage, QPainter        # noqa: E402

from danu.surface import shade                            # noqa: E402
from danu.surface.shade import HALF                       # noqa: E402
from danu.ui import mercator as m                         # noqa: E402
from danu.ui.mapview import MapView                       # noqa: E402
from danu.ui.surface import SurfaceLayer, SurfacePanel, Style   # noqa: E402


def synthetic(rows=40, cols=60, x0_m=0.0, y1_m=2_000_000.0, metres=1000.0) -> shade.Shaded:
    """A ramp of land from 0 to 400 m west to east, sea in the south."""
    dem = np.tile(np.linspace(1, 400, cols, dtype=np.float32), (rows, 1))
    dem[rows - 8:, :] = 0.0
    hs = np.full((rows, cols), 181, np.uint8)
    hs[:, ::2] = 120
    return shade.Shaded(dem=dem, shade=hs, geotransform=(x0_m, metres, 0.0, y1_m, 0.0, -metres), metres=metres)


def test_scene_rect_is_the_mercator_extent_in_scene_units():
    s = synthetic()
    l, t, r, b = s.scene_rect
    # x = 0 m is the world's middle; the raster runs 2,000,000 m north to
    # 1,960,000 m north, all of it above the equator - so above WORLD/2 on
    # a y axis that grows downward
    assert abs(l - m.WORLD / 2) < 1e-6
    assert t < b < m.WORLD / 2
    assert abs((r - l) - 60 * 1000 / (2 * HALF) * m.WORLD) < 1e-6


def test_the_layer_draws_land_and_leaves_sea_transparent(qtbot):
    v = MapView(); v.resize(600, 400); qtbot.addWidget(v); v.show(); qtbot.waitExposed(v)
    layer = SurfaceLayer(); v.scene().addItem(layer)
    s = synthetic()
    layer.set_shaded(s)
    l, t, r, b = s.scene_rect
    v.fit_bounds(*m.scene_to_lonlat(l, b), *m.scene_to_lonlat(r, t))
    img = QImage(v.viewport().size(), QImage.Format.Format_ARGB32); img.fill(QColor('white'))
    p = QPainter(img); v.render(p); p.end()
    land = v.mapFromScene((l + r) / 2, t + (b - t) * 0.3)
    sea = v.mapFromScene((l + r) / 2, t + (b - t) * 0.95)
    c_land, c_sea = img.pixelColor(land), img.pixelColor(sea)
    bg = v.backgroundBrush().color()
    assert (c_land.red(), c_land.green(), c_land.blue()) != (bg.red(), bg.green(), bg.blue())
    assert (c_sea.red(), c_sea.green(), c_sea.blue()) == (bg.red(), bg.green(), bg.blue())   # see-through
    layer.set_shaded(None)
    assert layer.boundingRect().isEmpty()


def test_the_traditional_ramp_is_the_one_compose_applies_in_metres():
    """compose() recognises the hypsometric ramp by name, and the panel
    disables scaling for it; both rest on traditional() being that ramp."""
    from danu.surface.ramp import spectral, traditional
    assert traditional().name == 'relief.ramp' and spectral().name != 'relief.ramp'


def test_full_shadow_is_drawn_and_only_nodata_is_transparent():
    """gdaldem's hillshade is 1 in complete shadow and 0 only for nodata;
    compose() must draw the 1 and drop the 0."""
    s = synthetic()
    s.shade[:, 0] = 1                                  # a column in full shadow
    s.shade[:, 1] = shade.HILLSHADE_NODATA             # a column of nodata
    grey = shade.compose(s, None, shade.Scaling(), mode='hillshade')
    assert (grey[:, 0, 3] == 255).all() and (grey[:, 0, 0] == 1).all()
    assert (grey[:, 1, 3] == 0).all()


def test_compose_refuses_a_relief_with_no_ramp_and_an_unknown_mode():
    s = synthetic()
    with pytest.raises(ValueError, match='needs a ramp'):
        shade.compose(s, None, shade.Scaling(), mode='relief')
    with pytest.raises(ValueError, match='mode'):
        shade.compose(s, None, shade.Scaling(), mode='sepia')


def test_recolour_follows_the_style_without_a_rebuild():
    layer = SurfaceLayer()
    s = synthetic()
    layer.set_shaded(s)
    layer.set_style(Style(mode='hillshade'))
    grey = layer._array.copy()
    assert (grey[..., 0] == grey[..., 1]).all()
    layer.set_style(Style(mode='relief', ramp='spectral', scaling=shade.Scaling('auto')))
    colour = layer._array.copy()
    assert not (colour[..., 0] == colour[..., 1]).all()          # coloured now
    west, east = colour[10, 2, :3], colour[10, -3, :3]
    assert tuple(west) != tuple(east)                             # low is not high
    layer.set_style(Style(mode='relief', ramp='spectral', scaling=shade.Scaling('pinch', centre=200, width=20)))
    pinched = layer._array.copy()
    assert tuple(pinched[10, -3, :3]) == tuple(pinched[10, -10, :3])   # everything above 210 m saturates alike
    layer.set_style(Style(mode='relief', ramp='traditional'))
    trad = layer._array.copy()
    assert (trad[-2, :, 3] == 0).all()                             # sea transparent in metres


def test_the_panel_enables_what_the_choice_needs_and_drives_the_layer(qtbot):
    layer = SurfaceLayer()
    layer.set_shaded(synthetic())
    panel = SurfacePanel(layer)
    qtbot.addWidget(panel)
    assert layer.style.mode == 'shaded relief' and abs(layer.opacity() - 0.85) < 1e-9
    assert not panel.lo.isEnabled() and not panel.centre.isEnabled()
    panel.scaling.setCurrentText('manual')
    assert panel.lo.isEnabled() and not panel.centre.isEnabled() and layer.style.scaling.mode == 'manual'
    panel.scaling.setCurrentText('pinch')
    assert panel.centre.isEnabled() and layer.style.scaling.mode == 'pinch'
    panel.ramp.setCurrentText('traditional')
    assert not panel.scaling.isEnabled()                           # metres mean metres
    panel.mode.setCurrentText('hillshade')
    assert not panel.ramp.isEnabled() and layer.style.mode == 'hillshade'
    panel.opacity.setValue(40)
    assert abs(layer.opacity() - 0.4) < 1e-9
    fired = []
    panel.rebuild.connect(fired.append)
    panel.button.click()
    assert fired == [3.0]                                          # the default resolution


def test_the_builder_refuses_a_set_with_nothing_to_build_and_recovers(qtbot, tmp_path):
    from danu.core.make_square import write_square
    from danu.core.square import SquareName, WorkingSet
    from danu.surface import params
    from danu.ui.surface import SurfaceBuilder
    write_square(tmp_path / 'N10E010.osm.xz', 10, 10, 'frame')     # a frame, no contours
    ws = WorkingSet.open(tmp_path, SquareName(10, 10), 1)
    b = SurfaceBuilder()
    with qtbot.waitSignal(b.failed, timeout=30000) as got:
        assert b.build(ws, params.load().with_arcsec(3))
        assert b.busy and not b.build(ws, params.load())
    assert 'nothing to build' in got.args[0] or 'GDAL' in got.args[0]
    assert not b.busy
    b.cleanup()


def test_the_worker_asks_the_build_to_keep_its_first_pass(qtbot, tmp_path, monkeypatch):
    """The one line that carries F2's saving to the editor: without it the
    overlay runs isofill's first pass a second time, which on a three by three
    working set at 1 arcsecond was 95 s of the 208 an edit took.

    The worker is exercised against a stub of danu.surface.build, because the
    two halves of this path have no job that can run them together - the ui
    job has Qt and no GDAL, the golden job has GDAL and no Qt. What is pinned
    here is the asking; that the kept pass gives the same overlay as a second
    fill is pinned in tests/golden."""
    import sys
    import types

    import numpy as np
    from danu.core.make_square import write_square
    from danu.core.square import SquareName, WorkingSet
    from danu.surface import params
    from danu.ui.surface import SurfaceBuilder

    write_square(tmp_path / 'N10E010.osm.xz', 10, 10, 'frame')
    ws = WorkingSet.open(tmp_path, SquareName(10, 10), 1)

    asked = {}
    stub = types.ModuleType('danu.surface.build')

    class Result:
        dem = tmp_path / 'dem.tif'
        constraints = tmp_path / 'cont.tif'
        drawn_mask = tmp_path / 'mask.tif'
        envelopes = None

    def build_dem(zone_dir, work, p, names=None, keep_pass1=False, **kw):
        asked['keep_pass1'] = keep_pass1
        return Result()

    def first_pass_classes(cont, mask, p, work, **kw):
        asked['classified'] = True
        return tmp_path / 'first-pass.tif'

    stub.build_dem = build_dem
    stub.first_pass_classes = first_pass_classes
    # both, because `from ..surface import build` takes the attribute off the
    # package where one is already bound - which it is here, and is not in a
    # job with no GDAL to have imported it
    import danu.surface
    monkeypatch.setattr(danu.surface, 'build', stub, raising=False)
    monkeypatch.setitem(sys.modules, 'danu.surface.build', stub)

    shaded = object()
    monkeypatch.setattr('danu.ui.surface.shade.shade_dem',
                        lambda dem, p, work, classes=None: shaded)

    b = SurfaceBuilder()
    trouble = []
    b.failed.connect(trouble.append)
    with qtbot.waitSignal(b.finished, timeout=30000) as got:
        assert b.build(ws, params.load().with_arcsec(3))
    assert not trouble, trouble
    assert asked == {'keep_pass1': True, 'classified': True}, asked
    assert got.args[0].shaded is shaded
    assert not b.busy
    b.cleanup()
