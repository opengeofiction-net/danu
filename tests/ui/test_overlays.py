"""R20 and R21 on the canvas: the unreached ground and the envelope."""

import json

import numpy as np
import pytest

pytest.importorskip('PySide6')

from danu.surface import shade                               # noqa: E402
from danu.ui import mercator as m                            # noqa: E402
from danu.ui.overlays import EnvelopeItem, UnreachedLayer, envelope_rings   # noqa: E402
from danu.ui.surface import SurfaceLayer, SurfacePanel       # noqa: E402


def test_envelope_rings_come_from_the_geojson_the_build_writes(tmp_path):
    f = tmp_path / 'drawn.geojson'
    f.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [
            [[86.1, 20.2], [86.9, 20.2], [86.9, 20.8], [86.1, 20.8], [86.1, 20.2]]]}},
        {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [
            [[87.0, 20.0], [88.0, 20.0], [88.0, 21.0], [87.0, 21.0], [87.0, 20.0]]]}}]}))
    rings = envelope_rings(f)
    assert len(rings) == 2 and rings[0][0] == (86.1, 20.2) and len(rings[1]) == 5
    item = EnvelopeItem()
    item.set_rings(rings)
    r = item.boundingRect()
    x0, y0 = m.lonlat_to_scene(86.1, 21.0)
    x1, y1 = m.lonlat_to_scene(88.0, 20.0)
    assert abs(r.left() - x0) < 1 and abs(r.right() - x1) < 1 and abs(r.top() - y0) < 1 and abs(r.bottom() - y1) < 1
    item.set_rings([])
    assert item.boundingRect().isEmpty()


def _shaded_with_classes():
    rows, cols = 30, 40
    dem = np.full((rows, cols), 50.0, np.float32)
    hs = np.full((rows, cols), 180, np.uint8)
    classes = np.zeros((rows, cols), np.uint8)
    classes[:, :5] = 255            # outside the drawn area
    classes[10:20, 10:20] = 1       # nothing in reach
    classes[5, 30:35] = 2           # too flat
    classes[25, 30:33] = 3          # one level
    return shade.Shaded(dem=dem, shade=hs, geotransform=(0.0, 100.0, 0, 1000.0, 0, -100.0), metres=100.0,
                        classes=classes)


def test_the_unreached_layer_draws_the_three_warnings_and_counts_them():
    s = _shaded_with_classes()
    layer = UnreachedLayer()
    layer.set_shaded(s)
    assert layer.counts == {1: 100, 2: 5, 3: 3}
    assert layer.cells_inside == 30 * 35
    text = layer.summary()
    assert '100 cells nothing in reach' in text and '5 too flat' in text and '3 seeing one level' in text
    # the area and fraction count what the contours do not describe - not the
    # one-level cells, which are mostly their own edges
    assert f'{105 * 100 * 100 / 1e6:,.1f} km²' in text and f'{100.0 * 105 / (30 * 35):.1f}%' in text
    rgba = shade.unreached_rgba(s.classes)
    assert (rgba[15, 15] == np.array(shade.UNREACHED_RGBA[1], np.uint8)).all()
    assert (rgba[0, 0, 3] == 0) and (rgba[0, 20, 3] == 0)         # outside, and answered: see-through
    assert (rgba[25, 30, 3] == 0)                                  # one level: not drawn by default
    assert (shade.unreached_rgba(s.classes, one_level=True)[25, 30] == np.array(shade.UNREACHED_RGBA[3], np.uint8)).all()
    layer.set_one_level(True)                                      # and the layer follows the toggle
    assert layer.one_level
    layer.set_shaded(None)
    assert layer.boundingRect().isEmpty() and layer.summary() == 'no first-pass reading'
    s.classes = None
    layer.set_shaded(s)
    assert layer.boundingRect().isEmpty()


def test_the_panel_toggles_both_overlays_and_shows_the_reading(qtbot):
    surface = SurfaceLayer()
    unreached, envelope = UnreachedLayer(), EnvelopeItem()
    panel = SurfacePanel(surface, unreached=unreached, envelope=envelope)
    qtbot.addWidget(panel)
    assert unreached.isVisible() and envelope.isVisible()
    panel.show_unreached.setChecked(False)
    panel.show_envelope.setChecked(False)
    assert not unreached.isVisible() and not envelope.isVisible()
    assert not panel.show_one_level.isChecked() and not unreached.one_level
    panel.show_one_level.setChecked(True)
    assert unreached.one_level
    s = _shaded_with_classes()
    surface.set_shaded(s)
    unreached.set_shaded(s)
    panel.built(s, 4.2)
    assert 'nothing in reach' in panel.reading.text()
