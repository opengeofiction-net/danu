"""Water from Overpass into the squares - G4's import, without the network.

R23 makes this an import and not a cache: a square is opened, edited and built
from its own file. So what has to be right here is what is asked for, what is
kept, and which square each feature lands in - and none of it reaches
Overpass, as none of the tile or territory tests reach their servers.
"""

import pytest

from danu.core.square import SquareName, WorkingSet
from danu.water import overpass

BOUNDS = (125.0, -24.0, 126.0, -23.0)

ANSWER = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="Overpass API">
  <node id="101" lat="-23.5" lon="125.2"/>
  <node id="102" lat="-23.5" lon="125.4"/>
  <node id="103" lat="-23.3" lon="125.4"/>
  <node id="104" lat="-23.3" lon="125.2"/>
  <node id="105" lat="-23.4" lon="125.3">
    <tag k="natural" v="spring"/>
    <tag k="name" v="Cold Spring"/>
    <tag k="ele" v="310"/>
  </node>
  <node id="201" lat="-23.8" lon="126.6"/>
  <node id="202" lat="-23.8" lon="126.8"/>
  <way id="301">
    <nd ref="101"/><nd ref="102"/><nd ref="103"/><nd ref="104"/><nd ref="101"/>
    <tag k="natural" v="water"/>
    <tag k="water" v="lake"/>
    <tag k="name" v="Lake Kinser"/>
    <tag k="source" v="survey 2019"/>
    <tag k="wikidata" v="Q1"/>
  </way>
  <way id="302">
    <nd ref="201"/><nd ref="202"/>
    <tag k="waterway" v="river"/>
    <tag k="name" v="Bosco River"/>
  </way>
  <relation id="401">
    <member type="way" ref="301" role="outer"/>
    <tag k="type" v="multipolygon"/>
    <tag k="natural" v="water"/>
    <tag k="ele" v="120"/>
  </relation>
</osm>
"""


@pytest.fixture
def ws(tmp_path):
    """A 3x3 set around S24E125, with no square files: ``WorkingSet.open``
    makes every member present or not, and placement only asks which square a
    point is in."""
    return WorkingSet.open(tmp_path, SquareName(125, -24))


# ------------------------------------------------------------------ query

def test_the_query_asks_for_the_working_sets_bounds():
    q = overpass.query(BOUNDS)
    # the box in the settings, where every statement inherits it, rather than
    # written out four times
    assert '[bbox:-24.0,125.0,-23.0,126.0]' in q, 'the bbox is south,west,north,east'
    assert q.count('125.0') == 1, 'the box is repeated on the statements'
    # exact values, not a regex: a tag value is an index lookup where a
    # pattern is a test run over what the index returned
    assert 'way["waterway"="river"];' in q and 'way["waterway"="stream"];' in q
    assert '~"' not in q, 'a regex came back'
    # river areas, which the data still tags the deprecated way: 115 of them
    # over the gobras 3x3, 114 closed, none also carrying natural=water
    assert 'way["waterway"="riverbank"];' in q
    # and nothing wider: a bare way["waterway"] brings drains, ditches, docks,
    # dams and weirs, which nothing grades and a re-import must reconcile
    assert 'way["waterway"];' not in q
    assert 'way["natural"="water"];' in q and 'relation["natural"="water"];' in q
    # the geometry has to come with it, or a square has a feature it cannot draw
    assert '(._;>>;);' in q and 'out body;' in q


def test_the_query_follows_relations_inside_relations():
    """``>`` would not. ``recurse.cc`` has ``DOWN`` collecting a relation's
    member nodes, its member ways and those ways' nodes; ``DOWN_REL`` does the
    same after a ``relations_loop`` over member relations. A multipolygon
    whose outer is itself a relation arrives under ``>`` as a member id with
    nothing behind it, and ``place`` has code to follow exactly that."""
    assert '(._;>>;);' in overpass.query(BOUNDS)
    assert '(._;>;);' not in overpass.query(BOUNDS)


def test_the_timeouts_are_an_editors_and_the_read_outlasts_the_server():
    """The batch grading asks for 900 seconds because a quarter hour at 3am is
    nothing. This is somebody sitting there. And the read waits a little
    longer than the server's own limit, so a timeout comes back as Overpass
    saying so rather than as us cutting the connection and guessing."""
    assert f'[timeout:{overpass.QUERY_TIMEOUT}]' in overpass.query(BOUNDS)
    assert overpass.QUERY_TIMEOUT <= 60
    assert overpass.READ_TIMEOUT > overpass.QUERY_TIMEOUT


def test_the_fetch_retries_and_then_gives_up():
    tries = []

    def never(req, timeout=None):
        tries.append(req.full_url)
        raise OSError('down')

    with pytest.raises(OSError, match='did not answer after 3'):
        overpass.fetch(BOUNDS, opener=never)
    assert len(tries) == 3


def test_the_fetch_returns_what_the_server_said():
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'<osm/>'

    sent = []

    def once(req, timeout=None):
        sent.append(req.data.decode())
        return Reply()

    assert overpass.fetch(BOUNDS, opener=once) == b'<osm/>'
    assert '125.0' in sent[0], 'the query went in the body'


# -------------------------------------------------------------------- tags

def test_only_the_tags_asked_for_come_across():
    water = overpass.parse(ANSWER.encode())
    lake = water.ways[301]
    assert lake.tags == {'natural': 'water', 'water': 'lake', 'name': 'Lake Kinser'}
    assert 'source' not in lake.tags and 'wikidata' not in lake.tags
    assert water.ways[302].tags == {'waterway': 'river', 'name': 'Bosco River'}
    assert water.relations[401].tags == {'natural': 'water', 'ele': '120'}
    assert water.relations[401].ele == 120.0


def test_a_tag_order_that_two_imports_agree_on():
    """The same feature imported twice writes the same line, which is what
    makes a diff of two versions of a square worth reading."""
    tags = {'name': 'A', 'ele': '5', 'water': 'lake', 'natural': 'water', 'zzz': '1'}
    assert list(overpass.kept(tags)) == ['natural', 'water', 'name', 'ele']


def test_a_nodes_tags_are_filtered_too_and_most_nodes_keep_none():
    water = overpass.parse(ANSWER.encode())
    assert water.nodes[101].tags == {}, 'a vertex of a river is geometry'
    assert water.nodes[105].tags == {'natural': 'spring', 'name': 'Cold Spring', 'ele': '310'}


def test_the_features_are_the_ways_and_relations_not_the_nodes():
    water = overpass.parse(ANSWER.encode())
    assert len(water.nodes) == 7
    assert len(water) == 3, 'a river of a thousand vertices is one thing imported'


# ------------------------------------------------------------------- place

def test_a_feature_goes_whole_into_the_square_holding_its_anchor(ws):
    water = overpass.parse(ANSWER.encode())
    placed = overpass.place(water, ws)

    here, east = SquareName(125, -24), SquareName(126, -24)
    assert set(placed) == {here, east}
    # the lake's ring went with its relation, and its nodes with it
    assert set(placed[here].relations) == {401}
    assert set(placed[here].ways) == {301}
    assert set(placed[here].nodes) == {101, 102, 103, 104}
    # the river is its own feature, in the square its first node is in
    assert set(placed[east].ways) == {302} and set(placed[east].relations) == set()
    assert set(placed[east].nodes) == {201, 202}


def test_a_member_way_goes_where_its_relation_goes(ws):
    """Not where its own first node falls. Otherwise a lake's outer ring is
    placed twice - once on its own account and once as a member - and a square
    two degrees away holds half its shape.

    The two anchors have to differ for this to be testing anything, and for a
    relation of one way member they cannot: the relation's anchor *is* that
    way's first node. So the relation gets a node member of its own, in
    another square and listed first, which is what a label node on a lake
    looks like.
    """
    from danu.core.square import Member

    water = overpass.parse(ANSWER.encode())
    rel = water.relations[401]
    rel.members.insert(0, Member('node', 105, 'label'))     # 105 is at 125.3, in the centre
    for ref in (101, 102, 103, 104):                        # the ring, moved east
        water.nodes[ref].lon += 1.0

    here, east = SquareName(125, -24), SquareName(126, -24)
    assert ws.at(water.nodes[105].lon, water.nodes[105].lat).name == here
    assert ws.at(water.nodes[101].lon, water.nodes[101].lat).name == east

    placed = overpass.place(water, ws)
    holding = [name for name, w in placed.items() if 301 in w.ways]
    assert holding == [here], f'the ring landed in {holding}, not with its relation'
    assert 401 in placed[here].relations


def test_a_feature_outside_the_set_is_dropped(ws):
    """Overpass answers a bounding box and a working set is not one, so some
    of what comes back is a river passing by."""
    water = overpass.parse(ANSWER.encode())
    for node in water.nodes.values():
        node.lat = -40.0                       # nowhere near the set
    assert overpass.place(water, ws) == {}


def test_a_way_with_no_geometry_is_dropped(ws):
    water = overpass.parse(ANSWER.encode())
    water.nodes.clear()
    assert overpass.place(water, ws) == {}


def test_a_relation_inside_a_relation_goes_in_its_parents_square(ws):
    """A multipolygon's outer may itself be a relation, which OSM really
    holds. Placed on its own account it would land where *its* anchor falls -
    which can be another square - and the parent would name a shape two
    degrees away while also holding a copy of it.

    The anchors have to differ for this to test anything, so the parent gets a
    node member in the centre square and the child's ring is moved east. The
    first version of this test had them agree and passed with the whole rule
    taken out.
    """
    from danu.core.square import Member, Relation

    water = overpass.parse(ANSWER.encode())
    wrapper = Relation(id=402, members=[Member('node', 105, 'label'),
                                        Member('relation', 401, 'outer')],
                       tags={'natural': 'water'})
    water.relations[402] = wrapper
    for ref in (101, 102, 103, 104):
        water.nodes[ref].lon += 1.0                  # the child's own anchor, east

    here, east = SquareName(125, -24), SquareName(126, -24)
    assert ws.at(water.nodes[101].lon, water.nodes[101].lat).name == east

    placed = overpass.place(water, ws)
    assert set(placed[here].relations) == {401, 402}, 'the child was not placed with its parent'
    assert east not in placed or 401 not in placed[east].relations, 'the child was placed twice'
    assert 301 in placed[here].ways, 'the ring inside the nested relation was dropped'
    assert {101, 102, 103, 104} <= set(placed[here].nodes)


def test_a_relation_that_names_itself_does_not_walk_for_ever(ws):
    """Bad data rather than a shape - and bad data is what a public API
    returns."""
    from danu.core.square import Member, Relation

    water = overpass.parse(ANSWER.encode())
    water.relations[403] = Relation(id=403, members=[Member('relation', 404, '')],
                                    tags={'natural': 'water'})
    water.relations[404] = Relation(id=404, members=[Member('relation', 403, ''),
                                                     Member('way', 301, 'outer')],
                                    tags={'natural': 'water'})
    placed = overpass.place(water, ws)                 # must return
    here = SquareName(125, -24)
    assert {403, 404} <= set(placed[here].relations)


def test_a_way_whose_relation_was_dropped_is_still_placed_on_its_own(ws):
    """Only a relation that was placed claims anything. One anchored outside
    the set is dropped, and a member way of it that *is* inside has to be left
    for the standalone pass - otherwise it is claimed by nothing and vanishes.
    """
    from danu.core.square import Member, Relation

    water = overpass.parse(ANSWER.encode())
    # a relation anchored far away, naming the lake ring that is inside the set
    water.nodes[999] = type(water.nodes[101])(id=999, lat=-40.0, lon=140.0)
    water.relations[405] = Relation(id=405, members=[Member('node', 999, 'label'),
                                                     Member('way', 301, 'outer')],
                                    tags={'natural': 'water'})
    del water.relations[401]                           # so 301 has only the far relation

    placed = overpass.place(water, ws)
    here = SquareName(125, -24)
    assert 405 not in placed.get(here, overpass.Water()).relations
    assert 301 in placed[here].ways, 'the ring went with a relation that was never placed'


def test_an_anchor_walks_past_a_branch_that_leads_nowhere(ws):
    """A relation whose first member is a chain of empty relations and whose
    second resolves. The walk has to carry on rather than stop at the first
    member that gave nothing.

    This does *not* distinguish the path-scoped cycle guard from an
    accumulating one; nothing does, and the docstring on ``_relation_anchor``
    says why. It pins the thing that is actually testable.
    """
    from danu.core.square import Member, Relation

    water = overpass.parse(ANSWER.encode())
    water.relations[501] = Relation(id=501, members=[], tags={})
    water.relations[502] = Relation(id=502, members=[Member('relation', 501, '')], tags={})
    water.relations[504] = Relation(id=504, members=[Member('relation', 502, ''),
                                                     Member('node', 105, 'label')],
                                    tags={'natural': 'water'})

    here = SquareName(125, -24)
    placed = overpass.place(water, ws)
    assert 504 in placed.get(here, overpass.Water()).relations, (
        'the walk stopped at a branch that led nowhere')


def test_an_imported_id_cannot_collide_with_one_a_mapper_draws():
    """The whole identity story rests on this: a feature arrives with the
    positive OSM id it had, and R40 matches a later import on it. The
    allocator takes 0 as its ceiling, so a positive id never moves it."""
    from danu.core import edits
    from danu.core.square import Node, Square, Way

    sq = Square(name=SquareName(125, -24), present=True)
    sq.nodes[12345678] = Node(id=12345678, lat=-23.5, lon=125.5)
    sq.ways[87654321] = Way(id=87654321, refs=[12345678])
    alloc = edits.IdAllocator(sq)
    assert alloc.take() == -1, 'a square of positive ids should still mint from -1'
    assert alloc.take() == -2
