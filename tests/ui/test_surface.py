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


def test_the_builder_reports_a_set_with_nothing_to_build_and_recovers(qtbot, tmp_path):
    from danu.core.make_square import write_square
    from danu.core.square import SquareName, WorkingSet
    from danu.surface import params
    from danu.ui.surface import SurfaceBuilder
    write_square(tmp_path / 'N10E010.osm.xz', 10, 10, 'frame')     # a frame, no contours
    ws = WorkingSet.open(tmp_path, SquareName(10, 10), 1)
    b = SurfaceBuilder()
    with qtbot.waitSignal(b.failed, timeout=30000) as got:
        assert b.request(ws, params.load().with_arcsec(3)) == 1
    assert 'nothing to build' in got.args[0] or 'GDAL' in got.args[0]
    assert not b.busy
    b.cleanup()


def test_the_worker_asks_the_build_to_keep_its_first_pass(qtbot, tmp_path, monkeypatch):
    """The one line that carries F2's saving to the editor: without it the
    overlay runs isofill's first pass a second time, which on a three by three
    working set at 1 arcsecond was 95 s of the 208 an edit took.

    There is nothing conditional about it - the worker always asks, because the
    overlay is always built - so what this pins is that it always asks, and
    that the classes it gets back are the ones the surface is shaded with.

    The worker is exercised against a stub of danu.surface.build, because the
    two halves of this path have no job that can run them together: the ui job
    has Qt and no GDAL, the golden job has GDAL and no Qt. That the kept pass
    gives the same overlay as a second fill is pinned in tests/golden.

    The stub is installed on the danu.surface package rather than in the ui
    module because the worker's import is inside run() - there is no name bound
    in danu.ui.surface to replace. Deleting the keyword from the worker makes
    this test fail, which is how that target was checked rather than reasoned
    about."""
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

    classes = tmp_path / 'first-pass.tif'

    def first_pass_classes(cont, mask, p, work, **kw):
        asked['classified'] = (cont, mask)
        return classes

    stub.build_dem = build_dem
    stub.first_pass_classes = first_pass_classes
    # both, because `from ..surface import build` takes the attribute off the
    # package where one is already bound - which it is here, and is not in a
    # job with no GDAL to have imported it
    import danu.surface
    monkeypatch.setattr(danu.surface, 'build', stub, raising=False)
    monkeypatch.setitem(sys.modules, 'danu.surface.build', stub)

    shaded = object()
    shading = {}

    def shade_dem(dem, p, work, classes=None):
        shading.update(dem=dem, classes=classes)
        return shaded

    monkeypatch.setattr('danu.ui.surface.shade.shade_dem', shade_dem)

    b = SurfaceBuilder()
    trouble = []
    b.failed.connect(trouble.append)
    with qtbot.waitSignal(b.finished, timeout=30000) as got:
        assert b.request(ws, params.load().with_arcsec(3)) == 1
    assert not trouble, trouble
    assert asked['keep_pass1'] is True, asked
    # the classes were asked for from this build's own rasters, and are what
    # the surface is shaded with - a stub whose answer nothing used would pin
    # nothing
    assert asked['classified'] == (Result.constraints, Result.drawn_mask), asked
    assert shading == {'dem': Result.dem, 'classes': classes}, shading
    assert got.args[0].shaded is shaded
    assert got.args[1] is False, 'a build nothing superseded came back stale'
    assert not b.busy
    b.cleanup()


def _pixels(layer):
    """The layer's pixmap as an array - what is actually drawn, rather than
    the array it was composed from."""
    import numpy as np
    from PySide6.QtGui import QImage
    img = layer._pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = img.constBits()
    return np.frombuffer(ptr, np.uint8, img.height() * img.bytesPerLine()).reshape(
        img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


def test_recolouring_one_box_is_what_recolouring_all_of_it_would_give(qtbot):
    """A preview recolours the rectangle it changed, not the surface.

    A whole recolour is 1,472 ms on the gobras 3x3 at 3 arcseconds - 24.4 M
    cells - against 62 ms for the solve it follows. I had written that
    compose() was "the UI thread's cheap end" and asserted, without measuring,
    that splitting it to a rectangle would buy "a few milliseconds"; it buys
    the difference between an edit costing 62 ms and one costing a second and
    a half.

    What this holds is that the shortcut is not a different picture - and it
    compares the pixmaps, not the composed arrays. The arrays agree even when
    the patch is painted at the wrong offset, because writing the array and
    painting the pixmap are two steps and only the second one places it.
    """
    import numpy as np
    from danu.surface import shade as shade_mod
    from danu.ui.surface import Style, SurfaceLayer

    # a fixed colour scale, so this asks only whether composing a rectangle
    # gives the same pixels as composing the whole. Whether the scale itself
    # is held is the next test, and a different question.
    def fixed():
        st = Style()
        st.scaling = shade_mod.Scaling(mode="manual", lo=0.0, hi=600.0)
        return st

    s = synthetic(rows=40, cols=60)
    whole, part = SurfaceLayer(), SurfaceLayer()
    for layer in (whole, part):
        layer.set_style(fixed())
        layer.set_shaded(synthetic(rows=40, cols=60))
    untouched = _pixels(part)

    box = (8, 15, 12, 20)              # y0, x0, rows, cols
    y0, x0, rows, cols = box
    sl = (slice(y0, y0 + rows), slice(x0, x0 + cols))
    for layer in (whole, part):
        layer.shaded.dem[sl] += np.float32(120.0)
        layer.shaded.shade[sl] = 40

    whole.recolour()                   # the answer
    assert part.recolour_box(*box)     # the shortcut

    got, want = _pixels(part), _pixels(whole)
    assert np.array_equal(got, want), (
        "%d of %d bytes of the pixmap differ" % (int((got != want).sum()), want.size))
    assert not np.array_equal(got, untouched), "the edit changed no pixel at all"


def test_a_box_recolour_keeps_the_whole_surfaces_colour_scale(qtbot):
    """In 'auto' the ramp is stretched over the land in the whole array. A
    rectangle that worked the range out from its own contents would come out a
    different colour from the ground it sits in, and the patch would show as a
    rectangle.

    Asserting that layer._stretch is unchanged would not catch it - the
    attribute stays put whether or not compose is given it. So this compares
    the pixels against both stretches and requires the global one.
    """
    import numpy as np
    from danu.surface import shade as shade_mod
    from danu.ui.surface import RAMPS, SurfaceLayer

    layer = SurfaceLayer()
    layer.set_shaded(synthetic(rows=40, cols=60))     # auto by default
    whole_range = layer._stretch
    assert whole_range is not None and whole_range[1] > 300

    # a patch of uniformly low ground: its own range is nothing like the
    # surface's, so the two stretches give visibly different colours
    box = (5, 5, 6, 6)
    y0, x0, rows, cols = box
    sl = (slice(y0, y0 + rows), slice(x0, x0 + cols))
    layer.shaded.dem[sl] = np.float32(3.0)
    layer.shaded.shade[sl] = 200
    assert layer.recolour_box(*box)

    window = shade_mod.Shaded(dem=layer.shaded.dem[sl], shade=layer.shaded.shade[sl],
                              geotransform=layer.shaded.geotransform, metres=layer.shaded.metres)
    ramp = RAMPS[layer.style.ramp]()
    with_global = shade_mod.compose(window, ramp, layer.style.scaling, layer.style.mode,
                                    layer.style.shade_strength, stretch=whole_range)
    on_its_own = shade_mod.compose(window, ramp, layer.style.scaling, layer.style.mode,
                                   layer.style.shade_strength)
    assert not np.array_equal(with_global, on_its_own), (
        "the two stretches give the same colours here, so this cannot tell them apart")

    got = _pixels(layer)[sl]
    assert np.array_equal(got, with_global), "the patch restretched to its own contents"
