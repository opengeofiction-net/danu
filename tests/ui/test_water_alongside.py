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
