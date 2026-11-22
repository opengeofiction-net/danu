"""The main map's landforms, imported - #191. No Qt and no GDAL."""

from danu.water import landforms


def test_the_query_asks_for_every_landform_and_the_areas_as_relations_too():
    q = landforms.query((125.0, -23.0, 126.0, -22.0))
    for k in ('ridge', 'arete', 'valley', 'gully', 'gorge', 'cliff', 'earth_bank', 'dry_lake', 'plateau'):
        assert f'way["natural"="{k}"];' in q
    assert 'relation["natural"="dry_lake"];' in q and 'relation["natural"="plateau"];' in q
    assert 'relation["natural"="ridge"]' not in q
    assert '[bbox:-23.0,125.0,-22.0,126.0]' in q and '(._;>>;);' in q


def test_the_answer_keeps_landforms_and_their_geometry_and_nothing_else():
    payload = b"""<osm version="0.6">
      <node id="1" lat="-22.5" lon="125.2"><tag k="natural" v="peak"/><tag k="ele" v="900"/></node>
      <node id="2" lat="-22.5" lon="125.3"/>
      <node id="3" lat="-22.6" lon="125.3"/>
      <way id="10"><nd ref="1"/><nd ref="2"/><tag k="natural" v="cliff"/><tag k="height" v="40"/>
        <tag k="surface" v="rock"/></way>
      <way id="11"><nd ref="2"/><nd ref="3"/><tag k="highway" v="track"/></way>
    </osm>"""
    got = landforms.landforms(payload)
    assert set(got.ways) == {10}
    assert got.ways[10].tags == {'natural': 'cliff', 'height': '40'}
    assert set(got.nodes) == {1, 2} and got.nodes[1].tags == {}
