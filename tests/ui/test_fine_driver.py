"""The 1 arcsecond view's driver - I3b's wiring, without GDAL.

What it owes: solve nothing below z15; solve the view once it settles at z15 or
closer; one solve at a time, the next for wherever the view is by then; drop an
answer that lands after the build it was held on has gone. The solve itself is
held to a whole 1 arcsecond build in tests/golden/test_fine_view.py.
"""

import numpy as np
import pytest

pytest.importorskip('PySide6')

from danu.surface import params as surface_params
from danu.surface.local import Box
from danu.ui import fine as fine_ui
from danu.ui.fine import FineDriver
from danu.ui.surface import Built

PARAMS = surface_params.load().with_arcsec(3.0)


class Plan:
    def __init__(self, view):
        self.view = view


class FakeFine:
    """Fine's planning and keeping, over a grid of 1000 cells each way from
    (0, 0), a cell a thousandth of a degree."""

    def __init__(self):
        self.planned, self.taken = [], []
        self.solved = set()
        self.params = PARAMS.with_arcsec(1)

        class G:
            shape = (1000, 1000)
            gt = (0.0, 0.001, 0.0, 0.0, 0.0, -0.001)
        self.fine = G()

    def cells(self, west, south, east, north):
        return Box(int(west * 1000), int(-north * 1000), int(east * 1000), int(-south * 1000))

    def plan(self, view):
        self.planned.append(view)
        return None if view in self.solved else Plan(view)

    def take(self, p, solved, shaded=None):
        self.taken.append(p.view)
        self.solved.add(p.view)
        return [('tile', p.view)]


@pytest.fixture
def driver(monkeypatch):
    monkeypatch.setattr(fine_ui.fine, 'solve', lambda p, shape, params: ('solved', p.view))
    d = FineDriver()
    d.fine = FakeFine()
    held = []
    d.set_runner(held.append)
    d.held = held
    return d


def run(d):
    """Run the job the runner was handed, as the pool would."""
    d.held.pop(0).run()


def test_nothing_is_solved_below_z15(driver):
    driver.view((0.1, -0.2, 0.3, -0.1), 14)
    assert driver.fine.planned == [] and driver.held == []


def test_the_settled_view_is_solved_at_z15_and_closer(driver):
    got = []
    driver.arrived.connect(lambda tiles, s: got.append((tiles, s)))
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    assert driver.fine.planned == [Box(100, 100, 300, 200)]
    run(driver)
    assert driver.fine.taken == [Box(100, 100, 300, 200)]
    assert got and got[0][0] == [('tile', Box(100, 100, 300, 200))] and got[0][1] >= 0
    # and at it again, nothing more to solve
    driver.view((0.1, -0.2, 0.3, -0.1), 17)
    assert driver.held == []


def test_one_solve_at_a_time_and_the_next_for_where_the_view_is_now(driver):
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    driver.view((0.2, -0.3, 0.4, -0.2), 15)       # moved on while it solves
    driver.view((0.5, -0.6, 0.7, -0.5), 15)       # and again
    assert len(driver.held) == 1, 'a second solve started beside the first'
    run(driver)
    # not the place it passed through, the place it came to rest
    assert len(driver.held) == 1
    run(driver)
    assert driver.fine.taken == [Box(100, 100, 300, 200), Box(500, 500, 700, 600)]


def test_zooming_out_mid_solve_keeps_the_answer_and_asks_for_nothing_more(driver):
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    driver.view((0.0, -0.9, 0.9, 0.0), 13)
    run(driver)
    assert driver.fine.taken == [Box(100, 100, 300, 200)]
    assert driver.held == []


def test_an_answer_landing_after_the_build_has_gone_is_dropped(driver):
    old = driver.fine
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    driver.forget()
    run(driver)
    assert old.taken == []


def test_a_build_at_1_arcsecond_has_no_1_arcsecond_view():
    d = FineDriver()
    d.adopt(Built(shaded=None, rasters=object()), contours=object(), params=PARAMS.with_arcsec(1))
    assert d.fine is None


def test_a_build_without_its_grids_says_why_once():
    d = FineDriver()
    said = []
    d.unavailable.connect(said.append)
    for _ in range(2):
        d.adopt(Built(shaded=None, rasters=None), contours=None, params=PARAMS)
    assert d.fine is None and len(said) == 1 and '1"' in said[0]


def test_a_solve_that_fails_says_so(driver, monkeypatch):
    def broken(p, shape, params):
        raise RuntimeError('no isofill')
    monkeypatch.setattr(fine_ui.fine, 'solve', broken)
    said = []
    driver.unavailable.connect(said.append)
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    run(driver)
    assert said and 'no isofill' in said[0]
    assert driver.fine.taken == []


# ------------------------------------------------------------- the layer

class Piece:
    """shade.Shaded's shape, without importing what it needs."""

    def __init__(self, c0, r0, rows, cols, value, metres=31):
        from danu.surface import shade
        self.dem = np.full((rows, cols), value, np.float32)
        self.shade = np.full((rows, cols), 200, np.uint8)
        self.metres = metres
        self.geotransform = (c0 * metres - shade.HALF, metres, 0.0, shade.HALF - r0 * metres, 0.0, -metres)

    @property
    def scene_rect(self):
        from danu.surface import shade
        return shade.Shaded(self.dem, self.shade, self.geotransform, self.metres).scene_rect


class TiledFine:
    """Two tiles side by side, and nothing else."""

    def __init__(self, pieces):
        self.pieces = pieces
        self.revision = 0

    def cells(self, *bounds):
        return Box(0, 0, 10, 10)

    def tiles(self, box):
        return list(self.pieces)

    def piece(self, k):
        return self.pieces.get(k)


@pytest.fixture
def layer(qapp):
    from danu.ui.fine import FineLayer
    from danu.ui.surface import SurfaceLayer

    surface = SurfaceLayer()
    surface._stretch = (0.0, 100.0)
    d = FineDriver()
    origin = (1 << 20, 1 << 20)
    d.fine = TiledFine({(0, 0): Piece(origin[0], origin[1], 5, 4, 10.0),
                        (0, 1): Piece(origin[0] + 4, origin[1], 5, 3, 90.0)})
    lay = FineLayer(surface, d)
    lay.origin = origin
    return lay


def test_the_tiles_in_view_are_one_picture_with_each_on_its_own_cells(layer):
    from PySide6.QtCore import QRectF

    pix, at = layer.picture(QRectF(0, 0, 1, 1))
    assert (pix.width(), pix.height()) == (7, 5)
    img = pix.toImage()
    left, right = img.pixelColor(1, 2), img.pixelColor(5, 2)
    assert left != right, 'the two tiles came out one colour'
    assert img.pixelColor(3, 0) == left and img.pixelColor(4, 0) == right


def test_a_picture_is_kept_until_the_tiles_or_the_style_change(layer):
    from dataclasses import replace

    from PySide6.QtCore import QRectF

    first = layer.picture(QRectF(0, 0, 1, 1))[0]
    assert layer.picture(QRectF(0, 0, 1, 1))[0] is first
    layer.surface.style = replace(layer.surface.style, mode='hillshade')
    assert layer.picture(QRectF(0, 0, 1, 1))[0] is not first
    again = layer.picture(QRectF(0, 0, 1, 1))[0]
    layer.arrived([(0, 1)])
    assert layer.picture(QRectF(0, 0, 1, 1))[0] is not again


def test_a_cell_no_tile_covers_is_clear(layer):
    from PySide6.QtCore import QRectF

    layer.driver.fine.pieces[(1, 0)] = Piece(layer.origin[0], layer.origin[1] + 5, 2, 2, 50.0)
    img = layer.picture(QRectF(0, 0, 1, 1))[0].toImage()
    assert img.pixelColor(6, 6).alpha() == 0
    assert img.pixelColor(1, 6).alpha() == 255


def test_the_layer_shows_at_z15_and_closer(layer):
    layer.set_zoom(14)
    assert not layer.isVisible()
    layer.set_zoom(15)
    assert layer.isVisible()


def test_an_edit_drops_the_tiles_and_the_answer_in_flight(driver):
    cleared = []
    driver.fine.clear = lambda: cleared.append(True)
    driver.view((0.1, -0.2, 0.3, -0.1), 15)
    assert len(driver.held) == 1
    told = []
    driver.cleared.connect(lambda: told.append(True))
    driver.edited()
    assert cleared and told, 'the layer was not told to stop drawing what was kept'
    assert len(driver.held) == 2, 'the view is solved again'
    run(driver)                       # the old answer lands, and is dropped
    assert driver.fine.taken == []
    run(driver)
    assert driver.fine.taken == [Box(100, 100, 300, 200)]


def test_a_new_set_of_tiles_is_a_new_picture_though_the_keys_are_the_same(layer):
    """Tiles solved again after an edit come back under the same keys; the
    picture is of what is kept now, not of what was kept under those keys."""
    from PySide6.QtCore import QRectF

    first = layer.picture(QRectF(0, 0, 1, 1))[0]
    layer.driver.fine.pieces[(0, 0)] = Piece(layer.origin[0], layer.origin[1], 5, 4, 60.0)
    layer.driver.fine.revision += 1
    assert layer.picture(QRectF(0, 0, 1, 1))[0] is not first
