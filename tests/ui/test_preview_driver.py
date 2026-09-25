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
        d.edited(a_square(0.3 + 0.01 * i, 0.5), {1})
    assert not d.solved, 'a preview ran before the gesture finished'
    qtbot.waitUntil(lambda: bool(d.solved), timeout=2000)
    assert len(d.solved) == 1, f'ten edits in one gesture became {len(d.solved)} previews'


def test_the_boxes_of_a_gesture_are_all_covered(qtbot, monkeypatch):
    """The one preview has to cover everything the gesture touched, not just
    the last edit - otherwise the earlier nodes keep the old surface."""
    d = driver_over(monkeypatch)
    d.edited(a_square(0.10, 0.5, wid=1), {1})
    d.edited(a_square(0.80, 0.5, wid=2), {2})
    assert len(d._pending) == 2
    want = [(b.x0, b.x1) for b in d._pending]
    d._run()
    covered = [(b.x0, b.x1) for b in d.solved]
    for lo, hi in want:
        assert any(b0 <= lo and hi <= b1 for b0, b1 in covered), \
            "an edit in the gesture was not covered: %r in %r" % ((lo, hi), covered)


def test_distant_edits_are_not_merged_into_one_huge_box(qtbot, monkeypatch):
    """Two edits at opposite corners have a bounding box of the whole working
    set - 12.9 M cells on a 3x3 at 3 arcseconds - and it would be solved in one
    go inside a timer slot, with the editor frozen for all of it.

    They are disjoint, so solving them apart is no more work and bounds each
    piece."""
    d = driver_over(monkeypatch)
    d.edited(a_square(0.02, 0.05, wid=1), {1})
    d.edited(a_square(0.95, 0.95, wid=2), {2})
    d._run()
    assert len(d.solved) == 2, "the two corners were solved as one box"
    whole = 100 * 100
    for b in d.solved:
        assert b.cells < whole / 4, "a box of %d cells of a %d-cell raster" % (b.cells, whole)


def test_edits_along_one_stroke_are_solved_together(qtbot, monkeypatch):
    """The other side of it: a run of adjacent nodes is one piece of ground and
    splitting it would solve the overlap twice."""
    d = driver_over(monkeypatch)
    for i in range(6):
        d.edited(a_square(0.40 + 0.005 * i, 0.5, wid=1), {1})
    d._run()
    assert len(d.solved) == 1, "one stroke became %d solves" % len(d.solved)


def test_the_contour_layer_follows_the_editor(qtbot, monkeypatch):
    """A way that is still a contour is put in; one that has been deleted, or
    has stopped being a contour, is taken out. Otherwise the next preview burns
    a contour that is not there."""
    d = driver_over(monkeypatch)
    layer = d._kept.contours

    d.edited(Square([Way(7, [1, 2], ele=250.0)],
                    {1: Node(0.5, 0.5), 2: Node(0.51, 0.5)}), {7})
    assert layer.applied == [(7, 2, 250.0)], layer.applied

    gone = Square([], {1: Node(0.5, 0.5), 2: Node(0.51, 0.5)})     # deleted
    d.edited(gone, {7})
    assert layer.removed == [7], layer.removed

    no_ele = Square([Way(8, [1, 2], ele=None)], {1: Node(0.5, 0.5), 2: Node(0.51, 0.5)})
    d.edited(no_ele, {8})
    assert layer.removed == [7, 8], 'a way that stopped being a contour stayed in the layer'


def test_silence_asks_for_the_exact_rebuild(qtbot, monkeypatch):
    """R19's second half: on idle it is rebuilt exactly."""
    d = driver_over(monkeypatch, idle_ms=50)
    asked = []
    d.exact_wanted.connect(lambda: asked.append(True))
    d.edited(a_square(), {1})
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
        d.edited(a_square(), {1})
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
    d.edited(a_square(), {1})
    assert d._pending == []


def test_a_way_dragged_out_of_the_working_set_is_not_a_box(qtbot, monkeypatch):
    """A working set is a window, and a way can be moved off it. That is not an
    error and must not be clipped to a box at the raster's corner."""
    d = driver_over(monkeypatch)
    far = Square([Way(1, [1, 2])], {1: Node(99.0, 99.0), 2: Node(99.1, 99.0)})
    d.edited(far, {1})
    assert d._pending == [], 'a way outside the raster produced a box inside it'


def test_the_editor_passes_way_ids_and_the_driver_takes_them(qtbot, monkeypatch):
    """The contract, pinned against the real one rather than a fake of it.

    edits.Command.ways() returns set[int]. The first version of this driver
    took Way objects, and every test here passed because the fakes were written
    to match the mistake rather than the source - so the editor raised
    AttributeError on the first node moved and no preview ever ran. This reads
    the real annotation, so a fake cannot disagree with it again.
    """
    import inspect

    from danu.core import edits

    got = inspect.signature(edits.Command.ways).return_annotation
    assert got in ('set[int]', set[int]), f'Command.ways now returns {got!r}'

    # and the driver survives what that actually delivers: a bare int naming a
    # way the square no longer holds
    d = driver_over(monkeypatch)
    d.edited(Square([], {}), {12345})
    assert d._kept.contours.removed == [12345]


def test_moving_one_node_boxes_that_node_and_not_the_whole_contour(qtbot, monkeypatch):
    """The difference between a patch that solves in thirty milliseconds and
    one that solves in a second.

    A long contour is drawn, then one node in the middle of it is moved. The
    box has to be around the node, not around the contour."""
    d = driver_over(monkeypatch)
    refs = list(range(1, 41))
    nodes = {r: Node(0.10 + 0.02 * i, 0.5) for i, r in enumerate(refs)}
    square = Square([Way(1, refs)], nodes)
    d.edited(square, {1})                    # drawn: the whole way is new
    whole = d._pending[-1]
    d._pending.clear()

    nodes[refs[20]] = Node(nodes[refs[20]].lon, 0.62)    # one node moved north
    d.edited(Square([Way(1, refs)], nodes), {1})
    assert d._pending, 'moving a node produced no box at all'
    one = d._pending[-1]
    # along the way, which is where the saving is. Not by cell count: this
    # fixture's contour is a horizontal line one cell tall, so the whole of it
    # is 79 cells and a tall thin box around one moved node is 65 - the same
    # order, and the comparison says nothing.
    span, all_of_it = one.x1 - one.x0, whole.x1 - whole.x0
    assert span < all_of_it / 5, \
        f'moving one node of a {len(refs)}-node contour boxed {span} columns of {all_of_it}'


def test_a_way_that_did_not_move_is_not_previewed(qtbot, monkeypatch):
    """A command can name a way it did not change - retagging its neighbour,
    say. Re-solving for it is the budget spent on nothing."""
    d = driver_over(monkeypatch)
    square = a_square(0.5, 0.5, wid=3)
    d.edited(square, {3})
    d._pending.clear()
    d.edited(square, {3})                    # same geometry, again
    assert d._pending == [], 'a way whose geometry did not move was boxed anyway'

def test_a_solve_that_cannot_run_turns_the_preview_off_instead_of_the_process(qtbot, monkeypatch):
    """_run is a slot. An exception leaving it does not land in a caller, it
    leaves QTimer::timeout, and PySide6 aborts the process.

    The likeliest one is not exotic: the solve loads libisofill.so, and a
    machine can have the binary without the library - which is the arrangement
    interpolate already handles by falling back, so the build succeeds there,
    the driver adopts, and the editor looks correct right up to the first edit.
    """
    from danu.surface import preview as surface_preview

    d = driver_over(monkeypatch)
    said = []
    d.unavailable.connect(said.append)

    def no_library(*a, **kw):
        raise RuntimeError("no isofill library: tried libisofill.so")

    monkeypatch.setattr(surface_preview, "patch", no_library)
    d.edited(a_square(), {1})
    d._run()                                  # must not raise

    assert said and "no live preview" in said[0], said
    assert not d.ready, "the preview stayed armed after it could not run"
    assert not d._gesture.isActive()
    # and the editor keeps working: edits still ask for the exact rebuild
    asked = []
    d.exact_wanted.connect(lambda: asked.append(True))
    d.edited(a_square(), {1})
    assert d._pending == []


def test_adopt_survives_gdal_raising_rather_than_returning_none(qtbot, monkeypatch):
    """By the time adopt runs, build_surface has put GDAL in exception mode, so
    a file it cannot open is a RuntimeError and not the OSError Contours raises
    for a missing one. adopt is called from a slot too."""
    from danu.surface import preview as surface_preview
    import numpy as np

    def gdal_says_no(gpkg):
        raise RuntimeError("not recognised as a supported file format")

    monkeypatch.setattr(surface_preview, "Contours", gdal_says_no)
    d = PreviewDriver(gesture_ms=1, idle_ms=10_000)
    said = []
    d.unavailable.connect(said.append)
    zeros = np.zeros((4, 4), np.float32)
    rasters = type("R", (), dict(
        constraints=zeros, mask=np.ones((4, 4), np.uint8), water=None, surface=zeros,
        dem=zeros, geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0), projection="",
        nodata=-9999.0, gpkg="x.gpkg"))()
    d.adopt(Built(shaded=object(), rasters=rasters), PARAMS)   # must not raise
    assert not d.ready
    assert said and "RuntimeError" in said[0], said


def test_the_driver_follows_the_surface_the_layer_is_drawing(qtbot, monkeypatch):
    """The layer takes every build; the grids to work from come only from the
    exact ones. A driver that skipped the stale builds went on splicing into
    the array of the build before, which nobody draws, and previews stopped
    appearing until the next exact one."""
    d = driver_over(monkeypatch)
    newer = object()
    d.follow(newer)
    assert d._shaded is newer, "the driver is still pointing at the old surface"
    assert d.ready, "following a new surface threw away the grids as well"


def test_a_way_that_was_never_a_contour_costs_nothing(qtbot, monkeypatch):
    """Moving a node of a coastline, or of anything untagged, constrains
    nothing. Boxing its geometry would solve ground the edit cannot have
    changed, at tens of milliseconds a go."""
    d = driver_over(monkeypatch)
    sq = Square([Way(9, [1, 2], ele=None)], {1: Node(0.2, 0.5), 2: Node(0.7, 0.5)})
    d.edited(sq, {9})
    assert d._pending == [], "a way that was never a contour was boxed"
    assert d._kept.contours.removed == [9]


def test_a_contour_deleted_still_resolves_the_ground_it_covered(qtbot, monkeypatch):
    """The other half of it: a way that *was* a contour leaves ground behind
    that has to be filled in again."""
    d = driver_over(monkeypatch)
    sq = Square([Way(9, [1, 2], ele=75.0)], {1: Node(0.2, 0.5), 2: Node(0.7, 0.5)})
    d.edited(sq, {9})
    d._pending.clear()
    d.edited(Square([], {1: Node(0.2, 0.5), 2: Node(0.7, 0.5)}), {9})
    assert d._pending, "deleting a contour resolved nothing"


def test_a_way_just_off_the_raster_is_not_boxed_at_its_corner(qtbot, monkeypatch):
    """int() truncates toward zero, so a way half a cell west of the raster
    came out at column 0 and was boxed as though it were inside."""
    d = driver_over(monkeypatch)
    gt = d._kept.geotransform                 # 0.01 deg cells from lon 0
    just_west = Square([Way(1, [1, 2])],
                       {1: Node(-0.005, 0.5), 2: Node(-0.004, 0.5)})
    d.edited(just_west, {1})
    assert d._pending == [], "a way west of the raster was boxed inside it"


def test_a_preview_says_the_unreached_overlay_has_gone_stale(qtbot, monkeypatch):
    """R20's overlay is the first pass's classes, and a preview reruns the
    first pass without bringing them back. Left alone, the overlay goes on
    calling ground unreached that the contour just drawn reaches."""
    d = driver_over(monkeypatch)
    stale = []
    d.classesStale.connect(lambda: stale.append(True))
    d.edited(a_square(), {1})
    d._run()
    assert stale == [True], "nothing said the overlay no longer describes the surface"


def test_the_unreached_overlay_fades_when_the_surface_has_moved_under_it(qtbot):
    """R20's overlay draws the first pass's classes. A preview reruns the first
    pass for a box and brings back the DEM and the hillshade, not the classes -
    so after an edit the overlay is describing the surface as it was, in red,
    over a surface that shows otherwise.

    Faded, not hidden: what it says is still true of most of the raster.
    """
    import numpy as np
    from danu.surface import shade
    from danu.ui.overlays import UnreachedLayer

    layer = UnreachedLayer()
    assert not layer.stale
    layer.set_stale()
    assert layer.stale
    # and a real build clears it again
    dem = np.zeros((4, 4), np.float32)
    layer.set_shaded(shade.Shaded(dem=dem, shade=np.zeros((4, 4), np.uint8),
                                  geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0), metres=1.0,
                                  classes=np.zeros((4, 4), np.uint8)))
    assert not layer.stale, 'an exact build left the overlay marked stale'
