"""The main map's coastlines, as an import brings them - no Qt, no network."""

from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet
from danu.water import coast, overpass

A = SquareName(125, -24)

ANSWER = b"""<osm version="0.6">
  <node id="11" version="2" lat="-23.5" lon="125.2"/>
  <node id="12" version="1" lat="-23.5" lon="125.4"/>
  <node id="13" version="1" lat="-23.4" lon="125.4"><tag k="natural" v="beach"/></node>
  <node id="21" version="1" lat="-23.6" lon="125.2"/>
  <node id="22" version="1" lat="-23.6" lon="125.3"/>
  <way id="101" version="7"><nd ref="11"/><nd ref="12"/><nd ref="13"/>
    <tag k="natural" v="coastline"/><tag k="name" v="Bay Shore"/><tag k="source" v="survey"/></way>
  <way id="102" version="3"><nd ref="21"/><nd ref="22"/><tag k="natural" v="cliff"/></way>
</osm>"""


def test_the_query_asks_for_every_coastline_with_its_nodes_and_versions():
    q = coast.query((125.0, -24.0, 126.0, -23.0))
    assert '[bbox:-24.0,125.0,-23.0,126.0]' in q
    assert 'way["natural"="coastline"];>;' in q and q.rstrip().endswith('out meta;')


def test_a_coastline_lands_at_sea_level_with_what_upstream_owns_and_its_version():
    got = coast.coastlines(ANSWER)
    assert list(got.ways) == [101], 'only the coastline'
    assert got.ways[101].tags == {'natural': 'coastline', 'name': 'Bay Shore', 'ele': '0'}
    assert got.ways[101].refs == [11, 12, 13] and got.ways[101].version == 7
    assert set(got.nodes) == {11, 12, 13} and got.nodes[11].version == 2
    assert got.nodes[13].tags == {}, 'a vertex is geometry, its own tags left upstream'


def test_a_second_import_takes_upstreams_line_and_direction_and_keeps_the_squares_ele():
    sq = Square(name=A, present=True)
    first = coast.coastlines(ANSWER)
    edits.ImportWater(upstream_owns=coast.UPSTREAM_OWNS, new_nodes=dict(first.nodes),
                      new_ways=dict(first.ways)).apply(sq)
    sq.ways[101].tags['ele'] = '0.5'                 # set here, against the build's sea level
    again = coast.coastlines(ANSWER.replace(b'<nd ref="11"/><nd ref="12"/><nd ref="13"/>',
                                            b'<nd ref="13"/><nd ref="12"/><nd ref="11"/>'))
    edits.ImportWater(upstream_owns=coast.UPSTREAM_OWNS, new_nodes=dict(again.nodes),
                      new_ways=dict(again.ways)).apply(sq)
    assert sq.ways[101].refs == [13, 12, 11], "upstream's direction"
    assert sq.ways[101].tags['ele'] == '0.5', "the square's ele"


def test_a_coastline_upstream_no_longer_has_is_reported_and_a_drawn_one_never():
    sq = Square(name=A, present=True)
    for i in (1, 2, 3, 4):
        sq.nodes[i] = Node(id=i, lat=-23.5, lon=125 + i / 10)
    sq.ways[101] = Way(id=101, refs=[1, 2], tags={'natural': 'coastline', 'ele': '0'})
    sq.ways[102] = Way(id=102, refs=[2, 3], tags={'natural': 'coastline', 'ele': '0'})
    sq.ways[-5] = Way(id=-5, refs=[3, 4], tags={'natural': 'coastline', 'ele': '0'})    # drawn here
    sq.ways[103] = Way(id=103, refs=[3, 4], tags={'waterway': 'river'})                # not a coastline
    ws = WorkingSet(centre=A, size=1, squares={A: sq})
    gone = coast.gone(ws, frozenset({101}))
    assert [(g.kind, g.id, g.what) for g in gone] == [('way', 102, 'coastline')]


def test_the_water_import_does_not_count_a_coastline_gone():
    """The water query does not ask for coastlines, so their absence from its
    answer says nothing about them."""
    assert not overpass.asked_for('way', {'natural': 'coastline', 'ele': '0'})
