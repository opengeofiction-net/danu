"""The preview driver - R19's wiring, without GDAL.

What the driver owes: coalesce a gesture's edits into one preview, keep the
contour layer in step with the editor, ask for an exact rebuild once the
drawing stops, and say so when there is no preview to be had. The arithmetic
it drives is held to the exact build in tests/golden/test_preview.py; this is
about the wiring.
"""

import pytest

pytest.importorskip('PySide6')

from danu.surface import params as surface_params      # noqa: E402
from danu.ui.preview import PreviewDriver              # noqa: E402
from danu.ui.surface import Built                      # noqa: E402

PARAMS = surface_params.load().with_arcsec(3.0)


class Way:
    def __init__(self, wid, refs, ele=100.0):
        self.id, self.refs, self.ele = wid, refs, ele


class Node:
    def __init__(self, lon, lat):
        self.lon, self.lat = lon, lat


class Square:
    def __init__(self, ways, nodes):
        self.ways = {w.id: w for w in ways}
        self.nodes = nodes


class FakeContours:
    def __init__(self):
        self.applied, self.removed = [], []

    def apply(self, way_id, points, ele):
        self.applied.append((way_id, len(points), ele))

    def remove(self, way_id):
        self.removed.append(way_id)
        return True


def driver_over(monkeypatch, gesture_ms=1, idle_ms=10_000):
    """A driver holding a 100x100 grid, with the solve and the repaint stubbed:
    what is under test here is when they are called and with what."""
    import numpy as np
    from danu.surface import preview as surface_preview

    monkeypatch.setattr(surface_preview, 'Contours', lambda gpkg: FakeContours())
    # the solve and the repaint are held to the exact build elsewhere; here
    # they only have to record that they were asked, and with what
    calls = []
    monkeypatch.setattr(surface_preview, 'patch',
                        lambda kept, box, p, **kw: (calls.append(box),
                                                    (kept.surface[box.slice], box))[1])
    d = PreviewDriver(gesture_ms=gesture_ms, idle_ms=idle_ms)
    monkeypatch.setattr(d, '_repaint', lambda good: None)
    d.solved = calls
    zeros = np.zeros((100, 100), np.float32)
    rasters = type('R', (), dict(
        constraints=zeros.copy(), mask=np.ones((100, 100), np.uint8), water=None,
        surface=zeros.copy(), dem=zeros.copy(),
        geotransform=(0.0, 0.01, 0.0, 1.0, 0.0, -0.01),
        projection='', nodata=-9999.0, gpkg='none.gpkg'))()
    shaded = type('S', (), dict(geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
                                dem=zeros.copy(), shade=np.zeros((100, 100), np.uint8)))()
    d.adopt(Built(shaded=shaded, rasters=rasters), PARAMS)
    return d


def a_square(lon=0.5, lat=0.5, wid=1):
    return Square([Way(wid, [1, 2])], {1: Node(lon, lat), 2: Node(lon + 0.01, lat)})


def test_a_gesture_of_edits_becomes_one_preview(qtbot, monkeypatch):
    """Drawing a contour is one edit per node. Previewing each would spend the
    budget many times over on frames nobody sees."""
    d = driver_over(monkeypatch, gesture_ms=50)
    for i in range(10):
        d.edited(a_square(0.3 + 0.01 * i, 0.5), [Way(1, [1, 2])])
    assert not d.solved, 'a preview ran before the gesture finished'
    qtbot.waitUntil(lambda: bool(d.solved), timeout=2000)
    assert len(d.solved) == 1, f'ten edits in one gesture became {len(d.solved)} previews'


def test_the_boxes_of_a_gesture_are_covered_together(qtbot, monkeypatch):
    """The one preview has to cover everything the gesture touched, not just
    the last edit - otherwise the earlier nodes keep the old surface."""
    d = driver_over(monkeypatch)
    d.edited(a_square(0.10, 0.5), [Way(1, [1, 2])])
    d.edited(a_square(0.80, 0.5), [Way(2, [1, 2])])
    assert len(d._pending) == 2
    xs = [b.x0 for b in d._pending] + [b.x1 for b in d._pending]
    d._run()
    assert len(d.solved) == 1
    assert d.solved[0].x0 == min(xs) and d.solved[0].x1 == max(xs), \
        f'the preview covered {d.solved[0]}, not both edits'


def test_the_contour_layer_follows_the_editor(qtbot, monkeypatch):
    """A way that is still a contour is put in; one that has been deleted, or
    has stopped being a contour, is taken out. Otherwise the next preview burns
    a contour that is not there."""
    d = driver_over(monkeypatch)
    layer = d._kept.contours

    d.edited(a_square(0.5, 0.5, wid=7), [Way(7, [1, 2], ele=250.0)])
    assert layer.applied == [(7, 2, 250.0)], layer.applied

    gone = Square([], {1: Node(0.5, 0.5), 2: Node(0.51, 0.5)})     # deleted
    d.edited(gone, [Way(7, [1, 2], ele=250.0)])
    assert layer.removed == [7], layer.removed

    no_ele = Square([Way(8, [1, 2], ele=None)], {1: Node(0.5, 0.5), 2: Node(0.51, 0.5)})
    d.edited(no_ele, [Way(8, [1, 2], ele=None)])
    assert layer.removed == [7, 8], 'a way that stopped being a contour stayed in the layer'


def test_silence_asks_for_the_exact_rebuild(qtbot, monkeypatch):
    """R19's second half: on idle it is rebuilt exactly."""
    d = driver_over(monkeypatch, idle_ms=50)
    asked = []
    d.exact_wanted.connect(lambda: asked.append(True))
    d.edited(a_square(), [Way(1, [1, 2])])
    assert not asked, 'the rebuild was asked for before the drawing stopped'
    qtbot.waitUntil(lambda: bool(asked), timeout=3000)
    assert len(asked) == 1


def test_an_edit_restarts_the_idle_wait(qtbot, monkeypatch):
    """A rebuild during a pause between strokes would be thrown away by the
    next one, and at 3 arcseconds it costs five seconds of CPU."""
    d = driver_over(monkeypatch, idle_ms=300)
    asked = []
    d.exact_wanted.connect(lambda: asked.append(True))
    for _ in range(4):
        d.edited(a_square(), [Way(1, [1, 2])])
        qtbot.wait(120)
    assert not asked, 'the rebuild fired while edits were still arriving'
    qtbot.waitUntil(lambda: bool(asked), timeout=3000)


def test_the_driver_says_when_there_is_no_preview(qtbot, monkeypatch):
    """At the publishing resolution the grids are gigabytes and are not kept,
    so the editor rebuilds instead - and has to say so rather than look broken."""
    d = PreviewDriver(gesture_ms=1, idle_ms=10_000)
    said = []
    d.unavailable.connect(said.append)
    d.adopt(Built(shaded=object(), rasters=None), surface_params.load().with_arcsec(1.0))
    assert not d.ready
    assert said and '1"' in said[0], said
    # edits are still harmless, and still ask for the rebuild
    asked = []
    d.exact_wanted.connect(lambda: asked.append(True))
    d.edited(a_square(), [Way(1, [1, 2])])
    assert d._pending == []


def test_a_way_dragged_out_of_the_working_set_is_not_a_box(qtbot, monkeypatch):
    """A working set is a window, and a way can be moved off it. That is not an
    error and must not be clipped to a box at the raster's corner."""
    d = driver_over(monkeypatch)
    far = Square([Way(1, [1, 2])], {1: Node(99.0, 99.0), 2: Node(99.1, 99.0)})
    d.edited(far, [Way(1, [1, 2])])
    assert d._pending == [], 'a way outside the raster produced a box inside it'
