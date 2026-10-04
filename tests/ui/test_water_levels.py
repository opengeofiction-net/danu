"""Selecting water and setting its level by hand - R24, G6a.

Water is placed in the fixture's blank square to the north, so no contour is
there to compete for a click. A lake takes one level; a river takes a level at
a point, because it descends; a river area takes none, because R27 says
flowing water is never held flat. Upstream owns where water is and the mapper
owns how high it is, so a river's vertex is never dragged, and Delete on one
takes its level rather than the point.
"""

import pytest

pytest.importorskip('PySide6')

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter

from danu.core.square import Member, Node, Relation, SquareName, Way
from danu.ui.water import Answer
from danu.water import overpass

NORTH = SquareName(125, -23)


def mouse(w, kind, pos, button=Qt.MouseButton.LeftButton, buttons=None,
          mods=Qt.KeyboardModifier.NoModifier):
    buttons = button if buttons is None else buttons
    return QMouseEvent(kind, QPointF(pos), w.map.viewport().mapToGlobal(pos),
                       button, buttons, mods)


def click(w, lon, lat, mods=Qt.KeyboardModifier.NoModifier):
    w.map.center_on_lonlat(lon, lat)
    pos = w.map.viewport().rect().center()
    w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                               Qt.MouseButton.NoButton, mods))
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos, mods=mods))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos,
                                  buttons=Qt.MouseButton.NoButton, mods=mods))


def some_water():
    """A river of five vertices, a lake as a relation with an untagged ring,
    a one-way pond, and a river area - in the blank square to the north."""
    w = overpass.Water()
    for i, lon in enumerate((125.30, 125.32, 125.34, 125.36, 125.38), 1):
        w.nodes[i] = Node(id=i, lon=lon, lat=-22.70)
    w.ways[100] = Way(id=100, refs=[1, 2, 3, 4, 5], tags={'waterway': 'river', 'name': 'Bosco'})
    box = lambda base, lon, lat, d: {  # noqa: E731 - four corners, ids from base
        base + k: Node(id=base + k, lon=lon + dx * d, lat=lat + dy * d)
        for k, (dx, dy) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1)))}
    for base, lon, lat, d in ((10, 125.50, -22.50, 0.04), (20, 125.60, -22.50, 0.02),
                              (30, 125.70, -22.50, 0.03)):
        w.nodes.update(box(base, lon, lat, d))
    w.ways[200] = Way(id=200, refs=[10, 11, 12, 13, 10])
    w.relations[300] = Relation(id=300, tags={'natural': 'water', 'water': 'lake',
                                              'name': 'Kinser'},
                                members=[Member('way', 200, 'outer')])
    w.ways[400] = Way(id=400, refs=[20, 21, 22, 23, 20], tags={'natural': 'water'})
    w.ways[500] = Way(id=500, refs=[30, 31, 32, 33, 30], tags={'waterway': 'riverbank'})
    return w


@pytest.fixture
def wet(window):
    w = window
    water = some_water()
    w._water_imported(Answer({NORTH: water}, frozenset(water.ways),
                             frozenset(water.relations)), w.working_set)
    w.map.set_zoom(14)
    w.elevation.set(42.0)
    return w, w.working_set.squares[NORTH]


def level(w, value):
    w.elevation.set(value)
    w.editor.set_level()


# --------------------------------------------------------------- selecting

def test_a_click_on_a_rivers_vertex_selects_that_point(wet):
    w, sq = wet
    assert w.contours.pick(*w.map.mapToScene(w.map.viewport().rect().center()).toTuple(), 5) is None
    click(w, 125.34, -22.70)
    sel = w.editor.selection
    assert sel is not None and sel.way is sq.ways[100] and sel.node == 3


def test_shift_selects_the_whole_river(wet):
    w, sq = wet
    click(w, 125.34, -22.70, Qt.KeyboardModifier.ShiftModifier)
    sel = w.editor.selection
    assert sel is not None and sel.way is sq.ways[100] and sel.node is None


def test_a_click_on_a_lakes_ring_selects_the_lake(wet):
    """A lake is the relation, not the ring: its level is the relation's."""
    w, sq = wet
    click(w, 125.52, -22.50)
    sel = w.editor.selection
    assert sel is not None and sel.relation is sq.relations[300]


def test_water_stays_out_of_the_crossing_arrays(wet):
    """Picking water has its own path. In the contour arrays it would make
    every contour drawn across a river a refused crossing."""
    w, sq = wet
    w.contours._ensure_arrays()
    named = {id(g.way) for g in w.contours._ways}
    assert not {id(sq.ways[i]) for i in (100, 200, 400, 500)} & named


# ----------------------------------------------------------- setting levels

def test_a_rivers_level_is_set_at_a_point(wet):
    w, sq = wet
    click(w, 125.34, -22.70)
    level(w, 42.0)
    assert sq.nodes[3].tags.get('ele') == '42'
    assert sq.ways[100].tags.get('ele') is None, 'the river took one level for its length'
    spot = w.contours.spots[(NORTH, 3)]
    assert spot.on_water, 'a level on a river was taken for a spot height'


def test_a_river_selected_whole_is_asked_for_a_point(wet):
    w, sq = wet
    click(w, 125.34, -22.70, Qt.KeyboardModifier.ShiftModifier)
    before = dict(sq.ways[100].tags)
    level(w, 42.0)
    assert sq.ways[100].tags == before
    assert 'at a point' in w.statusBar().currentMessage()


def test_a_lakes_level_goes_on_the_lake(wet):
    w, sq = wet
    click(w, 125.52, -22.50)
    level(w, 120.0)
    assert sq.relations[300].tags.get('ele') == '120'
    assert sq.ways[200].tags.get('ele') is None, 'the level went on the ring, not the lake'
    assert w.contours.water_fills[(NORTH, 'rel', 300)].ele == 120.0, 'the lake was not redrawn'


def test_a_pond_drawn_as_one_way_takes_its_level_on_the_way(wet):
    w, sq = wet
    click(w, 125.61, -22.50)
    level(w, 88.0)
    assert sq.ways[400].tags.get('ele') == '88'


def test_a_river_area_is_never_given_one_level(wet):
    """R27. Flattening the Bosco River's area at one level put the whole of
    it at its mouth's height and cost 1,262 m of river ascent."""
    w, sq = wet
    click(w, 125.70, -22.50)
    before = dict(sq.ways[500].tags)
    level(w, 50.0)
    assert sq.ways[500].tags == before, 'a river area was held flat'
    assert 'descends' in w.statusBar().currentMessage()


def test_a_level_set_goes_back_on_ctrl_z(wet):
    w, sq = wet
    click(w, 125.52, -22.50)
    level(w, 120.0)
    w.editor.undo()
    assert 'ele' not in sq.relations[300].tags
    assert w.contours.water_fills[(NORTH, 'rel', 300)].ele is None


# ------------------------------------------------- upstream owns the shape

def test_a_rivers_vertex_is_not_dragged(wet):
    w, sq = wet
    lon, lat = sq.nodes[3].lon, sq.nodes[3].lat
    w.map.center_on_lonlat(lon, lat)
    pos = w.map.viewport().rect().center()
    w.map.mousePressEvent(mouse(w, QEvent.Type.MouseButtonPress, pos))
    for p in (pos + QPoint(20, 10), pos + QPoint(40, 20)):
        w.map.mouseMoveEvent(mouse(w, QEvent.Type.MouseMove, p, Qt.MouseButton.NoButton,
                                   Qt.MouseButton.LeftButton))
    w.map.mouseReleaseEvent(mouse(w, QEvent.Type.MouseButtonRelease, pos + QPoint(40, 20),
                                  buttons=Qt.MouseButton.NoButton))
    assert (sq.nodes[3].lon, sq.nodes[3].lat) == (lon, lat), 'a river vertex was dragged'


def test_delete_on_a_rivers_point_takes_its_level_not_the_point(wet):
    w, sq = wet
    click(w, 125.34, -22.70)
    level(w, 42.0)
    w.editor.delete_selected()
    assert 3 in sq.nodes and 3 in sq.ways[100].refs, 'the river lost a vertex'
    assert 'ele' not in sq.nodes[3].tags, 'the level stayed'
    assert (NORTH, 3) not in w.contours.spots


def test_delete_on_a_rivers_point_with_no_level_says_so(wet):
    w, sq = wet
    click(w, 125.34, -22.70)
    w.editor.delete_selected()
    assert 3 in sq.nodes
    assert 'no level' in w.statusBar().currentMessage()


# ------------------------------------------------- G5a, in the editor at last

def test_a_second_import_keeps_the_levels_set_in_the_editor(wet):
    """G5a's rule was tested by setting levels programmatically, because the
    editor could not set one. Now it can."""
    w, sq = wet
    click(w, 125.34, -22.70)
    level(w, 42.0)
    click(w, 125.52, -22.50)
    level(w, 120.0)
    water = some_water()
    w._water_imported(Answer({NORTH: water}, frozenset(water.ways),
                             frozenset(water.relations)), w.working_set)
    assert sq.nodes[3].tags.get('ele') == '42', 'the import threw away the river level'
    assert sq.relations[300].tags.get('ele') == '120', 'the import threw away the lake level'


# ------------------------------------------------------------- drawn

def _render_at(w, lon, lat, zoom):
    w.map.set_zoom(zoom)
    w.map.center_on_lonlat(lon, lat)
    img = QImage(w.map.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(QColor('white'))
    p = QPainter(img)
    w.map.render(p)
    p.end()
    return img


def _ink(c) -> bool:
    """A pixel of the water's own dark blue - the line, the mark, the text -
    and not the pale fill, the hatching or the background. Thresholds from
    the measured rendering, after two guesses at the pen colour found nothing:
    a 1.6 px antialiased diamond never reaches its pen's colour, and comes out
    the river line's own blue."""
    return c.red() < 110 and c.blue() - c.red() > 40


def _count(img, xs, ys):
    return sum(_ink(img.pixelColor(x, y)) for x in xs for y in ys)


def test_a_rivers_level_is_drawn_as_a_mark_and_a_value(wet):
    """Read from pixels. The colour cannot tell the mark from the river - it
    is the same blue - so the shape does: the river runs level through the
    point, and the mark reaches two and three rows off it, where the line
    does not; the value is above and to the right."""
    w, sq = wet
    click(w, 125.34, -22.70)
    level(w, 42.0)
    w.editor.selection = None
    n = sq.nodes[3]
    img = _render_at(w, n.lon, n.lat, 16)
    cx, cy = img.width() // 2, img.height() // 2
    line = max(range(cy - 3, cy + 4), key=lambda y: _count(img, range(img.width()), [y]))
    off_line = [line - 3, line - 2, line + 2, line + 3]
    assert _count(img, range(cx - 4, cx + 5), off_line) >= 4, "the level's mark was not drawn"
    assert _count(img, range(cx + 4, cx + 24), range(line - 12, line - 3)) >= 3, (
        'the value was not drawn above the mark'
    )
    assert w.contours.spots[(NORTH, 3)].on_water and w.contours.drawn_spots == 0, (
        'a level on water was drawn as a spot height'
    )


def test_a_rivers_level_mark_is_absent_where_there_is_no_level(wet):
    """The same reading at a vertex with no level finds the line alone - so
    the test above is reading the mark, not the river."""
    w, sq = wet
    n = sq.nodes[3]
    img = _render_at(w, n.lon, n.lat, 16)
    cx, cy = img.width() // 2, img.height() // 2
    line = max(range(cy - 3, cy + 4), key=lambda y: _count(img, range(img.width()), [y]))
    assert _count(img, range(cx - 4, cx + 5), [line - 3, line - 2, line + 2, line + 3]) == 0


def test_a_lakes_level_is_written_on_it(wet):
    """The value at the lake's middle, where without it there is only the
    pale fill and the hatching."""
    w, sq = wet
    lon, lat = 125.52, -22.48
    img = _render_at(w, lon, lat, 14)
    cx, cy = img.width() // 2, img.height() // 2
    region = (range(cx - 25, cx + 26), range(cy - 10, cy + 11))
    before = _count(img, *region)
    click(w, 125.52, -22.50)
    level(w, 120.0)
    w.editor.selection = None
    img = _render_at(w, lon, lat, 14)
    after = _count(img, *region)
    assert before == 0 and after >= 10, f'no level written on the lake ({before} -> {after})'


def test_the_nearer_of_a_contour_and_a_river_is_what_a_click_selects(wet):
    """A river runs down the valley a contour bends round. Contour-first left
    it unselectable at every zoom showing both; nearer-first gives each the
    clicks that land on it."""
    w, sq = wet
    w.map.set_zoom(14)
    # a contour some three pixels south of the river, near enough for either
    # to be picked from a click on the other
    px = 1 / (2 ** 14 * 256 / 360) * 3
    for i, lon in enumerate((125.335, 125.345), 9001):
        sq.nodes[i] = Node(id=i, lon=lon, lat=-22.70 - px)
    sq.ways[9100] = Way(id=9100, refs=[9001, 9002], tags={'ele': '40'})
    w.contours.set_working_set(w.working_set)
    w.editor.set_tool('select')

    click(w, 125.341, -22.70, Qt.KeyboardModifier.ShiftModifier)
    assert w.editor.selection.way is sq.ways[100], 'a click on the river took the contour'
    click(w, 125.341, -22.70 - px, Qt.KeyboardModifier.ShiftModifier)
    assert w.editor.selection.way is sq.ways[9100], 'a click on the contour took the river'


def test_a_rebuild_keeps_what_an_import_put_in_a_square_with_no_file(wet):
    """The blank square to the north has no file: an import brought it into
    being, and it is not `present` until saved. A rebuild that walked only
    present squares dropped everything there from the canvas while the square
    still held it."""
    w, sq = wet
    assert not sq.present
    w.contours.set_working_set(w.working_set)
    assert (NORTH, 100) in w.contours.water, 'the river vanished from the canvas'
    assert (NORTH, 'rel', 300) in w.contours.water_fills, 'the lake vanished from the canvas'


def test_a_ring_two_lakes_share_has_no_one_level(wet):
    """A ring two water relations name - a lake sharing a shore with a river
    area - leaves a click no lake to mean, so the ring itself is selected.
    It is untagged, its level belongs to whichever lake, and L says so rather
    than writing a level onto a ring. Reachable: the layer keeps untagged
    rings a water relation names, which review read as impossible."""
    w, sq = wet
    sq.relations[301] = Relation(id=301, tags={'natural': 'water', 'water': 'river'},
                                 members=[Member('way', 200, 'outer')])
    w.contours.set_working_set(w.working_set)
    click(w, 125.52, -22.50)
    sel = w.editor.selection
    assert sel is not None and sel.relation is None and sel.way is sq.ways[200]
    level(w, 90.0)
    assert 'ele' not in sq.ways[200].tags, 'a level was written onto a shared ring'
    assert 'more than one water relation' in w.statusBar().currentMessage()
