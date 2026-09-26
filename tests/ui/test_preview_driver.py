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

# cells each way in the fake raster these tests run on
GRID = 600


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
    def __init__(self, collided=()):
        self.applied, self.removed = [], []
        self.collided = list(collided)

    def burn(self, gt, box, nodata):
        import numpy as np
        return np.full(box.shape, nodata, np.float32)

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
    # as the real one does: where in the display it landed. Returning None
    # means nothing reached the screen, which is a different case and has
    # its own test.
    monkeypatch.setattr(d, '_repaint', lambda good: (good.y0, good.x0, 4, 4))
    d.solved = calls
    # GRID cells each way, not a hundred: patch() grows a box by cover + reach
    # before solving it, which is 100 cells at these parameters. On a
    # hundred-cell raster every box grows to the whole of it, every union is
    # free, and the merging tests would pass whatever the rule was.
    zeros = np.zeros((GRID, GRID), np.float32)
    rasters = type('R', (), dict(
        constraints=zeros.copy(), mask=np.ones((GRID, GRID), np.uint8), water=None,
        surface=zeros.copy(), dem=zeros.copy(),
        geotransform=(0.0, 0.01, 0.0, 1.0, 0.0, -0.01),
        projection='', nodata=-9999.0, gpkg='none.gpkg'))()
    shaded = type('S', (), dict(geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
                                dem=zeros.copy(), shade=np.zeros((GRID, GRID), np.uint8)))()
    d.adopt(Built(shaded=shaded, rasters=rasters), PARAMS)
    return d


def at_cell(col, row, wid=1, length=2):
    """A one-way square positioned at a given cell of the fake raster.

    In cells, not degrees: the geotransform runs lat *downward* from 1.0, so a
    latitude written to look like a position two-thirds down the raster is
    actually off the top of it, and the way is silently not boxed at all. Three
    tests were written that way and passed by not testing anything."""
    gt = (0.0, 0.01, 0.0, 1.0, 0.0, -0.01)
    lon = gt[0] + (col + 0.5) * gt[1]
    lat = gt[3] + (row + 0.5) * gt[5]
    return Square([Way(wid, [1, 2])],
                  {1: Node(lon, lat), 2: Node(lon + length * gt[1], lat)})


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
    d.edited(at_cell(20, 20, wid=1), {1})
    d.edited(at_cell(GRID - 40, GRID - 40, wid=2), {2})
    d._run()
    assert len(d.solved) == 2, "the two corners were solved as one box"
    whole = GRID * GRID
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


def test_a_preview_says_where_the_unreached_overlay_has_gone_stale(qtbot, monkeypatch):
    """R20's overlay is the first pass's classes, and a preview reruns the
    first pass without bringing them back. Left alone, the overlay goes on
    calling ground unreached that the contour just drawn reaches.

    Where, not just that. The rectangles are in the display's own grid, which
    is the grid the overlay's pixmap is in, so it can dim the ground it has
    stopped describing and leave the rest alone."""
    d = driver_over(monkeypatch)
    stale = []
    d.classesStale.connect(stale.append)
    d.edited(a_square(), {1})
    d._run()
    assert len(stale) == 1, "nothing said the overlay had stopped describing the surface"
    assert stale[0], "the signal named no ground at all"
    for y, x, rows, cols in stale[0]:
        assert rows > 0 and cols > 0


def test_nothing_reaching_the_display_leaves_the_overlay_alone(qtbot, monkeypatch):
    """If no patch reached the screen the displayed surface has not moved, so
    the classes still describe it and the overlay must not be dimmed. The
    condition is what was painted, not that a preview ran."""
    d = driver_over(monkeypatch)
    monkeypatch.setattr(d, "_repaint", lambda good: None)     # clipped away entirely
    stale = []
    d.classesStale.connect(stale.append)
    d.edited(a_square(), {1})
    d._run()
    assert stale == [], "the overlay was dimmed although nothing on screen changed"


def test_a_working_set_whose_ways_share_an_id_gets_no_preview(qtbot, monkeypatch):
    """Until the allocator was made set-wide, every square minted -1 for its
    first new way, so a set drawn in two squares and saved holds two contours
    calling themselves the same way. Those files exist.

    Keyed by id, one wins: a later apply() or remove() edits whichever
    registered last, in the wrong square. The build is unaffected and the idle
    rebuild is right; only the live patching would be wrong, so it is the live
    patching that stops."""
    import numpy as np
    from danu.surface import preview as surface_preview

    monkeypatch.setattr(surface_preview, "Contours",
                        lambda gpkg: FakeContours(collided=["-1", "-1", "-2"]))
    d = PreviewDriver(gesture_ms=1, idle_ms=10_000)
    said = []
    d.unavailable.connect(said.append)
    zeros = np.zeros((8, 8), np.float32)
    rasters = type("R", (), dict(
        constraints=zeros, mask=np.ones((8, 8), np.uint8), water=None, surface=zeros,
        dem=zeros, geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0), projection="",
        nodata=-9999.0, gpkg="x.gpkg"))()
    d.adopt(Built(shaded=object(), rasters=rasters), PARAMS)

    assert not d.ready, "the preview armed itself against colliding ids"
    assert said and "share a way id" in said[0], said
    assert "-1" in said[0], "the message does not say which id to look for"



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


def test_the_clamp_sees_the_contour_that_was_just_drawn(qtbot, monkeypatch):
    """M2, pinned where the wiring is.

    preview.patch puts its burn back before it returns, so by the time the
    repaint runs, kept.constraints holds the *build's* constraints and the
    contour just drawn is not in them. Clamping against those leaves
    clamp_patch's third rule - burned constraints back, untouched - testing for
    something that is not there, so a new contour never overrides the value the
    fill guessed at the cells the fill declined. That is the largest error
    class F3 names.

    So _repaint burns the window itself. No GDAL here: a fake layer returns a
    burn holding the new contour, and what is asserted is that the contour's
    own elevation reaches kept.dem.
    """
    import numpy as np
    # NODATA from the package, not from build: this job has Qt and no GDAL,
    # and build imports osgeo at module scope
    from danu.surface import NODATA, local
    from danu.surface import preview as surface_preview, shade as surface_shade

    d = driver_over(monkeypatch)
    kept = d._kept
    NEW_ELE = 321.0

    class BurnsTheNewContour:
        applied, removed, collided = [], [], []

        def apply(self, *a):
            pass

        def remove(self, *a):
            return True

        def burn(self, gt, box, nodata):
            a = np.full(box.shape, NODATA, np.float32)
            a[box.shape[0] // 2, :] = NEW_ELE        # a contour across the window
            return a

    kept.contours = BurnsTheNewContour()
    # the fill guessed something else entirely for that ground
    kept.surface[:] = 40.0
    kept.dem[:] = 40.0
    kept.constraints[:] = NODATA                     # the build never saw it

    monkeypatch.setattr(surface_preview, 'patch',
                        lambda k, box, p, **kw: (k.surface[box.grown(0, k.constraints.shape).slice],
                                                 box))
    monkeypatch.setattr(surface_shade, 'shade_window',
                        lambda *a, **kw: (np.zeros((2, 2), np.float32),
                                          np.zeros((2, 2), np.uint8),
                                          d._shaded.geotransform, 1.0))
    # the real one: driver_over stubs _repaint, and that stub is what the
    # wiring tests want. This is the one test about what _repaint does.
    from danu.ui.preview import PreviewDriver as Driver
    Driver._repaint(d, local.Box(20, 20, 24, 24))

    assert NEW_ELE in set(np.unique(kept.dem).tolist()), (
        'the clamp never saw the contour just drawn, so its elevation did not '
        'reach the surface')



def _splice_marker(d, source_rows, mercator_rows, halo=1):
    """Run _splice with a marked patch and say where the marker landed.

    The patch is all 7s with a border of 9s ``halo`` thick, scaled into
    Mercator - the ring the crop is supposed to remove. If the crop works, no 9
    reaches the display.
    """
    import numpy as np
    from danu.ui.preview import PreviewDriver as Driver

    ring = max(1, round(halo * mercator_rows / max(1, source_rows)))
    m_shade = np.full((mercator_rows, mercator_rows), 7, np.uint8)
    m_shade[:ring, :] = m_shade[-ring:, :] = 9
    m_shade[:, :ring] = m_shade[:, -ring:] = 9
    m_dem = m_shade.astype(np.float32)
    gt = d._shaded.geotransform
    # a window sitting at the display's origin
    return Driver._splice(d, m_dem, m_shade, gt, source_rows, halo)


def test_the_halo_is_cropped_before_the_patch_is_written(qtbot, monkeypatch):
    """shade_window's contract: the caller passes a window grown by a halo and
    crops what comes back. Its outermost cells are computed against an edge
    that is not there - np.pad(mode='edge'), computeEdges, and whatever
    bilinear reaches - so written in, they replace good display values with
    worse ones, and the next preview holds its rim against the ring they left.

    This was the fix for that and had no test.
    """
    import numpy as np
    from danu.surface import local

    d = driver_over(monkeypatch)
    d._shaded.shade[:] = 0
    rect = _splice_marker(d, source_rows=22, mercator_rows=22)
    assert rect is not None
    written = d._shaded.shade[d._shaded.shade != 0]
    assert written.size, "nothing was written at all"
    assert 9 not in set(written.tolist()), "the halo ring reached the display"
    assert 7 in set(written.tolist()), "the patch itself did not reach the display"


def test_the_crop_holds_when_the_window_was_clipped_by_the_raster(qtbot, monkeypatch):
    """The case that defeated the first version, and the one nobody would think
    to write.

    The crop converts a halo in source cells into Mercator cells by the ratio
    between the two heights. Taking the *unclipped* source height made that
    ratio too small wherever the window ran into the top or bottom of the
    raster - and since the crop is rounded up, short enough to trip the guard
    that skips it, writing the whole ring.

    Here the source window is clipped to half its asked-for height while the
    Mercator output keeps its own, which is the shape of that disagreement.
    """
    import numpy as np
    from danu.surface import local

    d = driver_over(monkeypatch)
    d._shaded.shade[:] = 0
    # A halo of 2, and a Mercator window twice the source's height, so the ring
    # is 4 Mercator cells. Measured against the source's real 11 rows the crop
    # is ceil(2 * 22/11) = 4 and the ring goes; measured against the 21 rows an
    # unclipped window would have had, it is ceil(2 * 22/21) = 3 and a cell of
    # the ring survives on every side.
    #
    # The first version of this used a halo of 1, where ceil lifts both
    # spellings to the same 2 - so the case it was named for was not the case
    # it exercised. It also sat at the *top* edge, which the commit's own
    # reasoning says cannot show the fault at all, because Box.grown clamps
    # with max(0, y0 - by) whatever shape it is given.
    rect = _splice_marker(d, source_rows=11, mercator_rows=22, halo=2)
    assert rect is not None
    written = set(d._shaded.shade[d._shaded.shade != 0].tolist())
    assert written, "nothing was written at all"
    assert 9 not in written, (
        "the halo ring reached the display: the crop was computed from a "
        "window height the source did not have")
    assert 7 in written, "the patch itself did not reach the display"

def test_repaint_measures_the_halo_against_the_window_it_actually_solved(qtbot, monkeypatch):
    """The denominator, pinned at the place that chooses it.

    The crop converts a halo in source cells into Mercator cells by the ratio
    between the two heights. The window is clipped to the raster before it is
    solved, so the source height is the clipped one - and measuring against the
    height it *asked* for makes the ratio too small wherever the window runs
    into the top or bottom of the raster. Rounded up, short enough to trip the
    guard that skips the crop, writing the whole halo ring.

    Handing _splice the number directly cannot catch this: the fault is in what
    _repaint passes, not in what _splice does with it. So this spies on the
    call.
    """
    import numpy as np
    from danu.surface import local, shade as surface_shade
    from danu.ui.preview import PreviewDriver as Driver

    d = driver_over(monkeypatch)
    kept = d._kept
    rows, cols = kept.constraints.shape
    monkeypatch.setattr(surface_shade, "shade_window",
                        lambda *a, **kw: (np.zeros((6, 6), np.float32),
                                          np.zeros((6, 6), np.uint8),
                                          d._shaded.geotransform, 1.0))
    seen = []
    monkeypatch.setattr(d, "_splice",
                        lambda m_dem, m_shade, m_gt, source_rows, halo:
                        seen.append((source_rows, halo)))

    # against the *bottom*, not the top. Box.grown clamps with max(0, y0 - by)
    # whatever shape it is given, so at the top edge the clipped and unclipped
    # heights are the same number and the fault is invisible. Only the far
    # edge, where the clamp is min(rows - 1, ...), can tell them apart.
    good = local.Box(5, rows - 11, 25, rows - 1)
    Driver._repaint(d, good)
    assert seen, "_repaint did not reach _splice"
    source_rows, halo = seen[0]
    clipped = good.grown(halo, (rows, cols)).shape[0]
    asked_for = good.shape[0] + 2 * halo
    assert clipped < asked_for, "this box is not clipped, so the test proves nothing"
    assert source_rows == clipped, (
        "the halo was measured against %d rows, but only %d were solved"
        % (source_rows, clipped))


def test_merging_counts_what_a_piece_costs_to_solve_not_its_own_size(qtbot, monkeypatch):
    """patch() grows a box by the cover and the reach before solving it, so two
    small boxes a few cells apart are two nearly identical large solves.
    Comparing the boxes themselves keeps them apart and does the work twice."""
    d = driver_over(monkeypatch)
    d.edited(at_cell(240, 250, wid=1), {1})
    d.edited(at_cell(248, 250, wid=2), {2})
    assert len(d._pending) == 2
    assert len(d._merged(d._pending)) == 1, \
        'two edits a few cells apart were solved as two nearly identical boxes'


def test_a_gesture_split_into_too_many_pieces_is_skipped(qtbot, monkeypatch):
    """Each piece is a whole solve on the UI thread. Past a handful the preview
    costs more than not previewing, and the idle rebuild settles it anyway -
    R19's guarantee is about the idle state, not the gesture."""
    import danu.ui.preview as mod

    # The cap is lowered rather than the raster stretched. A dozen edits spread
    # over a real working set merge down to two or three pieces - the merging
    # above is aggressive on purpose - so reaching the cap honestly would need
    # a raster far larger than anything else here, and the test would be about
    # the fixture. One piece is the cap, two pieces trip it.
    def two_corners():
        d = driver_over(monkeypatch)
        d.edited(at_cell(30, 30, wid=1), {1})
        d.edited(at_cell(GRID - 40, GRID - 40, wid=2), {2})
        d._run()
        return d.solved

    # the same gesture either side of the cap, because the capped answer is an
    # empty list and asserting on it alone would pass if the boxes had simply
    # merged
    monkeypatch.setattr(mod, 'MAX_PIECES', 8)
    assert len(two_corners()) == 2, 'these two merged, so there is no cap to test'

    monkeypatch.setattr(mod, 'MAX_PIECES', 1)
    assert two_corners() == [], 'the gesture was solved piece by piece past the cap'


def test_a_skipped_gesture_is_not_announced_as_a_preview(qtbot, monkeypatch):
    """Skipping is right; announcing a skipped preview as a preview is not.

    _merged used to return [] for "too many pieces" and for "nothing pending"
    alike, so the window reported *preview: 0 cells in 0 ms* and drew the
    dashed provisional rim around a surface that was still exact - the R19
    at-a-glance distinction saying the opposite of the truth, for as long as
    the idle timer runs.
    """
    import danu.ui.preview as mod

    monkeypatch.setattr(mod, 'MAX_PIECES', 1)
    d = driver_over(monkeypatch)
    previewed, skipped = [], []
    d.patched.connect(lambda rects, secs: previewed.append(rects))
    d.skipped.connect(skipped.append)

    d.edited(at_cell(30, 30, wid=1), {1})
    d.edited(at_cell(GRID - 40, GRID - 40, wid=2), {2})
    d._run()

    assert previewed == [], 'a preview was announced for a gesture that was skipped'
    assert skipped == [2], f'the skip was not reported: {skipped}'
    assert d.solved == [], 'the gesture was solved anyway'


def test_the_unreached_overlay_dims_where_the_surface_moved_and_nowhere_else(qtbot):
    """R20's overlay draws the first pass's classes. A preview reruns the first
    pass for a box and brings back the DEM and the hillshade, not the classes -
    so after an edit the overlay describes the surface as it was, in red, over
    a surface that shows otherwise.

    Three properties, and the fixture has to be able to tell them apart:

    - the previewed ground is dimmed,
    - ground the preview never touched is not,
    - and ground with no overlay on it is left alone entirely.

    The third is why the classes are not uniform here. Filling the raster with
    class 1 makes every cell dim the same way, and "dim inside, not outside"
    and "do not touch what has no overlay" then produce identical pixels. With
    a transparent quarter *inside* the previewed box, a wash drawn over the top
    instead of the overlay being drawn faded shows up as a pale rectangle over
    the surface - which is what the first version did.
    """
    import numpy as np
    from PySide6.QtGui import QColor, QImage, QPainter

    from danu.surface import shade
    from danu.ui.mapview import MapView
    from danu.ui import mercator as m
    from danu.ui.overlays import UnreachedLayer

    rows = cols = 64
    classes = np.full((rows, cols), 1, np.uint8)          # "nothing in reach"
    classes[:16, :16] = 0                                 # answered: no overlay here
    s = shade.Shaded(dem=np.full((rows, cols), 100.0, np.float32),
                     shade=np.full((rows, cols), 180, np.uint8),
                     geotransform=(0.0, 1000.0, 0.0, 2_000_000.0, 0.0, -1000.0),
                     metres=1000.0, classes=classes)

    layer = UnreachedLayer()
    layer.set_shaded(s)
    v = MapView(); v.resize(400, 400); qtbot.addWidget(v); v.show(); qtbot.waitExposed(v)
    v.scene().addItem(layer)
    l, t, r, b = s.scene_rect
    v.fit_bounds(*m.scene_to_lonlat(l, b), *m.scene_to_lonlat(r, t))

    def at(fx, fy):
        img = QImage(v.viewport().size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img); v.render(p); p.end()
        return img.pixelColor(v.mapFromScene(l + (r - l) * fx, t + (b - t) * fy))

    # a tenth in is inside the transparent quarter; a third in is overlaid and
    # still inside the previewed half; five sixths is outside it entirely
    clear_before, dim_before, keep_before = at(0.1, 0.1), at(0.33, 0.33), at(0.85, 0.85)
    assert dim_before != clear_before, "the fixture has no overlay to dim"

    layer.set_stale([(0, 0, rows // 2, cols // 2)])       # the top-left quarter previewed
    clear_after, dim_after, keep_after = at(0.1, 0.1), at(0.33, 0.33), at(0.85, 0.85)

    assert dim_after != dim_before, "the previewed ground was not dimmed"
    assert keep_after == keep_before, "ground the preview never touched was dimmed too"
    assert clear_after == clear_before, (
        "ground with no overlay on it changed: the fade is being painted over the "
        "surface rather than applied to the overlay")

    # a build puts it all back
    layer.set_shaded(s)
    assert not layer.stale
    assert at(0.33, 0.33) == dim_before, "a rebuild did not restore the overlay"


def test_the_stale_region_covers_everything_previewed_since_the_last_build(qtbot):
    """A contour drawn node by node is one preview per gesture, each carrying
    that node's box. Replacing left the dimmed region chasing the cursor while
    the nodes behind it - whose classes are equally out of date - sat at full
    strength, and going back to an earlier stroke made it bright again."""
    import numpy as np

    from danu.surface import shade
    from danu.ui.overlays import UnreachedLayer

    layer = UnreachedLayer()
    layer.set_shaded(shade.Shaded(dem=np.zeros((32, 32), np.float32),
                                  shade=np.zeros((32, 32), np.uint8),
                                  geotransform=(0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
                                  metres=1.0, classes=np.ones((32, 32), np.uint8)))
    layer.set_stale([(0, 0, 8, 8)])
    layer.set_stale([(20, 20, 8, 8)])
    assert (0, 0, 8, 8) in layer.stale, "the first stroke stopped being stale"
    assert (20, 20, 8, 8) in layer.stale
    layer.set_stale([(20, 20, 8, 8)])
    assert len(layer.stale) == 2, "the same rectangle was counted twice"
    layer.set_shaded(None)
    assert not layer.stale, "a build did not clear it"
