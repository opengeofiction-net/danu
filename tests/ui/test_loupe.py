"""Magnify (H3d): a loupe at the cursor, the map in it again a few times over.

Over the fixture's Tenmetre square, whose five contours run east-west at 10
to 50 m from -23.9 to -23.5, with a surface rising north to match them.
"""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QWheelEvent

from danu.ui import loupe as L
from tests.ui.test_measure import click, mouse, px, rising_north


def moved(w, pos):
    w.map.pointerMoved.emit(QPointF(pos))


def wheel(w, down, mods=Qt.KeyboardModifier.ShiftModifier):
    pos = QPointF(w.map.viewport().rect().center())
    ev = QWheelEvent(pos, w.map.viewport().mapToGlobal(pos), QPoint(), QPoint(0, -120 if down else 120),
                     Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
    w.map.wheelEvent(ev)


@pytest.fixture
def w(window):
    window.map.set_zoom(12)
    window.map.center_on_lonlat(126.5, -23.7)
    return window


def image(w):
    return w.loupe.grab().toImage()


def drawn_rows(img, x, background):
    """The rows of a column of the loupe drawn other than the background,
    inside its ring."""
    c, r = L.SIZE / 2, L.SIZE / 2 - 6
    return [y for y in range(img.height())
            if (x - c) ** 2 + (y - c) ** 2 < r * r and QColor(img.pixel(x, y)) != background]


def test_v_turns_it_on_and_the_button_and_menu_follow(w):
    a = w.edit_actions['view.magnify']
    assert a.shortcut().toString() == 'V' and a.isCheckable()
    a.trigger()
    assert w.loupe.on and w.controls.magnify.isChecked()
    w.controls.magnify.click()
    assert not w.loupe.on and not a.isChecked()


def test_centred_on_the_cursor_and_gone_when_it_leaves_the_map(w):
    at = QPoint(300, 200)
    moved(w, at)
    assert not w.loupe.isVisible(), 'shown while off'
    w.edit_actions['view.magnify'].trigger()
    assert w.loupe.isVisible(), 'on under a cursor already over the map'
    vp = w.map.viewport().geometry()
    centre = QPoint(L.SIZE // 2, L.SIZE // 2)
    assert w.loupe.geometry().topLeft() + centre == vp.topLeft() + at
    moved(w, QPoint(320, 210))
    assert w.loupe.geometry().topLeft() + centre == vp.topLeft() + QPoint(320, 210)
    w.map.viewportEvent(QEvent(QEvent.Type.Leave))
    assert not w.loupe.isVisible()
    moved(w, at)
    assert w.loupe.isVisible()
    w.edit_actions['view.magnify'].trigger()
    assert not w.loupe.isVisible()


def test_it_takes_no_click_from_the_map(w):
    w.edit_actions['view.magnify'].trigger()
    at = w.map.viewport().rect().center()
    moved(w, at)
    assert w.loupe.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert w.map.childAt(w.map.viewport().geometry().topLeft() + at) is w.map.viewport()


def test_the_contour_twelve_pixels_off_is_forty_eight_off_in_it(w):
    """The 30 m contour at -23.7, the cursor 12 px north of it: in the loupe
    it is four times as far below the centre, and then eight."""
    w.edit_actions['view.magnify'].trigger()
    on = px(w, 126.5, -23.7)
    moved(w, on - QPoint(0, 12))
    background = QColor(w.map.backgroundBrush().color())
    x = L.SIZE // 2 + 30                           # clear of the cross
    rows = drawn_rows(image(w), x, background)
    assert rows and all(abs(y - (L.SIZE // 2 + 48)) <= 2 for y in rows), rows
    wheel(w, down=False)
    assert w.loupe.factor == 8 and w.map.zoom == 12, 'shift and the wheel: the loupe, not the map'
    moved(w, on - QPoint(0, 6))
    rows = drawn_rows(image(w), x, background)
    assert rows and all(abs(y - (L.SIZE // 2 + 48)) <= 3 for y in rows), rows


def test_the_magnification_steps_and_stops_at_its_ends(w):
    w.edit_actions['view.magnify'].trigger()
    for _ in range(5):
        wheel(w, down=False)
    assert w.loupe.factor == L.FACTORS[-1]
    for _ in range(5):
        wheel(w, down=True)
    assert w.loupe.factor == L.FACTORS[0]
    w.edit_actions['view.magnify'].trigger()
    wheel(w, down=True)
    assert w.map.zoom == 11, 'off, shift and the wheel zoom the map as before'


def striped():
    """rising_north's grid, its columns 100 m and 900 m by turns: a cell
    its own colour, beside one far from it."""
    s = rising_north()
    s.dem[:, ::2], s.dem[:, 1::2] = 100.0, 900.0
    return s


def test_the_cells_are_sharp_and_their_grid_drawn_once_they_are_big_enough(w):
    w.contours.setVisible(False)
    w.surface.set_runner(None)                      # composed where asked
    w.surface_panel.mode.setCurrentText('relief')
    w.surface.set_shaded(striped())                 # 500 m cells: 13 px at zoom 12, 52 in the loupe
    w.surface.set_preview(False)
    w.edit_actions['view.magnify'].trigger()
    moved(w, w.map.viewport().rect().center())
    img = image(w)
    assert w.loupe.drawn_grid > 4
    assert w.surface.smooth, 'the map smoothed again after the loupe'
    # across the row, three cells and more: each one colour, edge to edge
    y = L.SIZE // 2 + 30                            # clear of the cross
    colours = {img.pixel(x, y) for x in range(30, L.SIZE - 30)}
    assert len(colours) <= 4, f'{len(colours)} colours, not two and the grid over each: smoothed'
    w.map.set_zoom(8)                               # a cell under a pixel, and four in the loupe
    image(w)
    assert w.loupe.drawn_grid == 0


def test_what_is_being_drawn_is_in_it(w):
    """The measure tool's line, as it is drawn, at the cursor."""
    w.contours.setVisible(False)
    w.edit_actions['tool.measure'].trigger()
    w.edit_actions['view.magnify'].trigger()
    background = QColor(w.map.backgroundBrush().color())
    click(w, 126.45, -23.75)
    at = px(w, 126.5, -23.75)
    moved(w, at)
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, at, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
    img = image(w)
    assert drawn_rows(img, L.SIZE // 2 - 40, background), 'the line west of the cursor, magnified'



def test_the_tiles_are_the_maps_own_not_fetched_deeper(w):
    asked = []
    w.fetcher.request = lambda layer, z, x, y: asked.append(z)
    w.edit_actions['view.magnify'].trigger()
    moved(w, w.map.viewport().rect().center())
    image(w)
    assert asked and max(asked) == w.map.zoom, asked
    assert all(t.zoom_at_most is None for t in w.map.scene().items() if hasattr(t, 'zoom_at_most'))


def test_drawn_again_when_the_map_under_it_changes(w, qtbot):
    w.edit_actions['view.magnify'].trigger()
    moved(w, w.map.viewport().rect().center())
    asked = []
    w.loupe.update = lambda *a: asked.append(a)
    w.contours.update()                             # an edit, a tile come in
    qtbot.waitUntil(lambda: bool(asked), timeout=2000)


def test_no_grid_while_the_cells_are_too_short_to_see(w):
    """500 m wide and 50 m high: 52 px across in the loupe, and 5 high."""
    import numpy as np

    from danu.surface import shade
    s = rising_north()
    x0, _, _, y1, _, _ = s.geotransform
    dem = np.repeat(s.dem, 10, axis=0)
    w.surface.set_runner(None)
    w.surface.set_shaded(shade.Shaded(dem=dem, shade=np.zeros(dem.shape, np.uint8),
                                      geotransform=(x0, 500.0, 0.0, y1, 0.0, -50.0), metres=50.0))
    w.surface.set_preview(False)
    w.edit_actions['view.magnify'].trigger()
    moved(w, w.map.viewport().rect().center())
    image(w)
    assert w.loupe.drawn_grid == 0
