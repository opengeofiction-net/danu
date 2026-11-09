"""Water held in a zone square outside the open set, reaching into it: read
alongside the set when it opens, drawn and chosen as the set's water is, its
contours not - and an edit to it made in its home and saved with the set."""

import pytest

pytest.importorskip('PySide6')

from danu.core import zone_index
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, read_square, write_square
from danu.ui.tools import Selection

FAR, AWAY = SquareName(128, -24), SquareName(130, -24)        # in the zone, outside the 3x3


def lake_square(name, lon0, lon1, rel_id=470432, ele=None):
    """A square holding a lake whose ring runs from ``lon0`` to ``lon1`` - and
    a contour of its own, which is not the set's."""
    sq = Square(name=name, present=True, attrs={'version': '0.6', 'upload': 'never'})
    pts = [(lon0, -23.4), (lon1, -23.4), (lon1, -23.6), (lon0, -23.6)]
    for i, (lon, lat) in enumerate(pts, 1):
        sq.nodes[rel_id * 10 + i] = Node(id=rel_id * 10 + i, lon=lon, lat=lat)
    ring = [rel_id * 10 + i for i in range(1, 5)]
    sq.ways[rel_id + 1] = Way(id=rel_id + 1, refs=[*ring, ring[0]], tags={})
    sq.relations[rel_id] = Relation(id=rel_id, members=[Member('way', rel_id + 1, 'outer')],
                                    tags={'natural': 'water', **({'ele': ele} if ele else {})})
    sq.nodes[-1], sq.nodes[-2] = Node(id=-1, lon=lon1 - 0.1, lat=-23.2), Node(id=-2, lon=lon1 - 0.1, lat=-23.1)
    sq.ways[-3] = Way(id=-3, refs=[-1, -2], tags={'ele': '40'})
    return sq


@pytest.fixture
def zoned(window, zone):
    write_square(lake_square(FAR, 126.6, 128.8, ele='0'), zone / 'S24E128.osm.xz')      # reaches into the set
    write_square(lake_square(AWAY, 130.2, 130.8, rel_id=470999), zone / 'S24E130.osm.xz')  # does not
    return window, zone


def test_the_index_says_which_squares_outside_reach_in(zoned):
    w, zone = zoned
    ws = w.working_set
    assert zone_index.reaching(zone, ws.bounds, set(ws.squares)) == [FAR]


def test_water_reaching_in_is_read_alongside_drawn_and_its_contours_not(zoned):
    w, _ = zoned
    ws = w.working_set
    w._read_alongside(ws)
    assert list(ws.extra) == [FAR] and 470432 in ws.extra[FAR].relations
    assert (FAR, 470433) in w.contours._geoms, 'the lake is not drawn'
    assert (FAR, -3) not in w.contours._geoms, "the far square's contour is drawn as the set's"
    assert 'water held in S24E128, outside the set' in w.statusBar().currentMessage()


def test_it_is_chosen_and_flattened_in_its_home_and_saved_with_the_set(zoned):
    w, zone = zoned
    ws = w.working_set
    w._read_alongside(ws)
    far = ws.extra[FAR]
    w.editor.selection = Selection(far, None, relation=far.relations[470432])
    w.editor.flatten()
    p = w.editor.proposal
    assert p is not None and p.kind == 'flatten', w.statusBar().currentMessage()
    w.editor.accept_proposal()
    assert far.ways[470433].tags.get('ele') == '0', 'the level is not on its ring, in its home'
    w.save_all()
    assert read_square(zone / 'S24E128.osm.xz').ways[470433].tags.get('ele') == '0', 'not saved with the set'


def test_a_surface_built_before_the_water_alongside_is_read_is_built_again(zoned, monkeypatch):
    """The read lands after the set is on screen, so a build asked for as it
    opened had none of it: in auto it is built again, otherwise said."""
    w, _ = zoned
    asked = []
    monkeypatch.setattr(w, 'rebuild_surface', lambda arcsec=None, why='': asked.append(why) or True)
    monkeypatch.setattr(type(w.builder), 'busy', property(lambda self: True))
    w.set_rebuild_mode('auto')
    w._read_alongside(w.working_set)
    assert asked == ['water alongside']
    w.working_set.extra.clear()
    w.set_rebuild_mode('manual')
    w._read_alongside(w.working_set)
    assert asked == ['water alongside'], 'manual: not built'
    assert 'rebuild to include it' in w.surface_panel.status.text()


def test_nothing_built_nothing_rebuilt_when_the_water_alongside_is_read(zoned, monkeypatch):
    w, _ = zoned
    asked = []
    monkeypatch.setattr(w, 'rebuild_surface', lambda arcsec=None, why='': asked.append(why) or True)
    w._read_alongside(w.working_set)
    assert asked == [] and w.surface.shaded is None


def test_a_build_and_the_checks_asked_for_while_the_water_alongside_is_read_wait_for_it(zoned, monkeypatch):
    """On opening, the session's build was asked for before the squares
    alongside were read: it was built without the sea, and again once the
    read landed. Now it, and the checks, wait for the read."""
    w, _ = zoned
    ws = w.working_set
    jobs = []
    monkeypatch.setattr(w, '_checks_runner', jobs.append)
    asked = []
    monkeypatch.setattr(w.builder, 'request', lambda ws, p, dirty=(), why='': asked.append((why, sorted(ws.extra))) or 1)
    w._read_alongside(ws)
    assert w.rebuild_surface(why='session') and asked == [], 'not built before the read lands'
    assert 'reading the water held alongside' in w.surface_panel.status.text()
    w.checks_dock.show()
    w.crossing_index = None
    w._checks_shown(True)
    assert len(jobs) == 1 and 'waits for the water' in w.statusBar().currentMessage()
    jobs.pop(0).run()
    assert asked == [('session', [FAR])], 'built once, with the water alongside'
    assert len(jobs) == 1, 'and the checks started, once'
    w._read_alongside(ws)                   # nothing new: nothing waits, nothing more built
    jobs.pop(0)
    jobs.pop(0).run()
    assert asked == [('session', [FAR])]
