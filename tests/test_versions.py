"""The main map's version, kept on what an import brought.

An import keeps the main map's id (R40, R41), and JOSM refuses a 0.6 file
holding a positive id with no version: "Missing attribute 'version' on OSM
primitive with ID 8374513", from gobras' N20E086 after its peaks came in. So
the version comes with the answer, rides on the node, way or relation, and
goes back out with it - through the file, a second import, an edit that
rebuilds a way under its own id, and the autosave's change file.
"""

import re

from danu.core import edits
from danu.core.change import ApplyChange, change_of, change_text, read_change
from danu.core.reconcile import reconcile
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, read_square, write_square
from danu.water import overpass, peaks

NAME = SquareName(125, -24)


def imported() -> Square:
    """A contour of the mapper's and a lake, a river and a peak from upstream."""
    sq = Square(name=NAME, present=True)
    for i, lon in ((-1, 125.1), (-2, 125.2)):
        sq.nodes[i] = Node(id=i, lat=-23.9, lon=lon)
    sq.ways[-3] = Way(id=-3, refs=[-1, -2], tags={'ele': '100'})
    for i, lon in ((101, 125.3), (102, 125.4), (103, 125.4)):
        sq.nodes[i] = Node(id=i, lat=-23.5 if i < 103 else -23.4, lon=lon, version=i - 99)
    sq.nodes[8374513] = Node(id=8374513, lat=-23.4, lon=125.5,
                             tags={'natural': 'peak', 'ele': '365'}, version=7)
    sq.ways[301] = Way(id=301, refs=[101, 102, 103, 101], tags={'natural': 'water'}, version=4)
    sq.relations[401] = Relation(id=401, members=[Member('way', 301, 'outer')],
                                 tags={'type': 'multipolygon', 'natural': 'water'}, version=9)
    return sq


def heads(text: str) -> dict:
    """Each element's kind and id to its version attribute, None where it has none."""
    out = {}
    for kind, i, rest in re.findall(r"<(node|way|relation) id='(-?\d+)'([^>]*)>", text):
        v = re.findall(r"version='(\d+)'", rest)
        out[(kind, int(i))] = int(v[0]) if v else None
    return out


def versions(sq: Square) -> dict:
    return {**{('node', i): n.version for i, n in sq.nodes.items()},
            **{('way', i): w.version for i, w in sq.ways.items()},
            **{('relation', i): r.version for i, r in sq.relations.items()}}


def test_the_file_writes_each_version_and_reads_it_back(tmp_path):
    sq = imported()
    path = write_square(sq, tmp_path / 'S24E125.osm')
    written = heads(path.read_text())
    assert written == versions(sq)
    assert written[('node', 8374513)] == 7 and written[('way', -3)] is None, 'a new id is written with none'
    back = read_square(path)
    assert versions(back) == versions(sq)


def test_a_version_a_file_was_saved_with_elsewhere_is_kept(tmp_path):
    """JOSM writes the version it holds; reading and saving here keeps it,
    so a square that has been through JOSM goes on opening there."""
    path = tmp_path / 'S24E125.osm'
    path.write_text("<?xml version='1.0' encoding='UTF-8'?>\n<osm version='0.6' upload='never'>\n"
                    "  <node id='5' version='12' lat='-23.5' lon='125.5' />\n"
                    "  <node id='-6' action='modify' lat='-23.6' lon='125.5' />\n"
                    "  <way id='7' version='3'><nd ref='5' /><nd ref='-6' /></way>\n</osm>\n")
    sq = read_square(path)
    assert sq.nodes[5].version == 12 and sq.nodes[-6].version is None and sq.ways[7].version == 3
    assert heads(write_square(sq, tmp_path / 'again.osm').read_text()) == {
        ('node', 5): 12, ('node', -6): None, ('way', 7): 3}


def test_the_imports_ask_for_the_version_and_keep_it():
    assert overpass.query((125, -24, 126, -23)).rstrip().endswith('out meta;')
    assert peaks.query((125, -24, 126, -23)).rstrip().endswith('out meta;')
    water = overpass.parse(b"""<osm version="0.6">
      <node id="101" version="2" lat="-23.5" lon="125.3"/>
      <node id="102" lat="-23.5" lon="125.4"/>
      <way id="301" version="4"><nd ref="101"/><nd ref="102"/><tag k="waterway" v="river"/></way>
      <relation id="401" version="9"><member type="way" ref="301" role="outer"/>
        <tag k="natural" v="water"/></relation>
    </osm>""")
    assert (water.nodes[101].version, water.nodes[102].version) == (2, None)
    assert water.ways[301].version == 4 and water.relations[401].version == 9
    got = peaks.parse(b"""<osm version="0.6"><node id="8374513" version="7" lat="-23.4" lon="125.5">
      <tag k="natural" v="peak"/><tag k="ele" v="365"/></node></osm>""")
    assert got.nodes[8374513].version == 7


def test_a_second_import_takes_upstreams_version_and_an_undo_gives_the_old_back():
    """Whether the merge keeps the square's object or builds a new one - the
    mapper's elevation on it - the version is the one upstream's geometry
    came with."""
    sq = imported()
    sq.ways[301].tags['ele'] = '120'                    # set here, so the merge builds a new way
    up_nodes = {i: Node(id=i, lat=n.lat, lon=n.lon, tags=dict(n.tags), version=(n.version or 0) + 10)
                for i, n in sq.nodes.items() if i > 0}
    up_nodes[8374513].tags['ele'] = '370'                # differs, so a merged node too
    up_ways = {301: Way(id=301, refs=[101, 102, 103, 101], tags={'natural': 'water'}, version=14)}
    up_rels = {401: Relation(id=401, members=[Member('way', 301, 'outer')],
                             tags={'type': 'multipolygon', 'natural': 'water', 'name': 'Kinser'}, version=19)}
    w = reconcile(sq, up_nodes, up_ways, up_rels, overpass.UPSTREAM_OWNS)
    assert w.ways[301] is not up_ways[301] and w.ways[301].tags['ele'] == '120', 'the fixture must merge'
    assert w.ways[301].version == 14 and w.relations[401].version == 19
    assert w.nodes[8374513].version == 17 and w.nodes[101].version == 12

    before = versions(sq)
    cmd = edits.ImportWater(upstream_owns=overpass.UPSTREAM_OWNS, new_nodes=up_nodes,
                            new_ways=up_ways, new_relations=up_rels)
    cmd.apply(sq)
    assert sq.ways[301].version == 14 and sq.nodes[8374513].version == 17
    cmd.undo(sq)
    assert versions(sq) == before


def test_a_way_rebuilt_under_its_own_id_keeps_its_version():
    """A river cut back at a lake, or bent from a contour, is ReplaceWay; a
    way over the API's limit split on save keeps its id on the first piece.
    That piece is the way still; the others are new."""
    sq = imported()
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    other = alloc.take()
    cmd = edits.ReplaceWay(301, [(301, [101, 102]), (other, [102, 103])], {})
    cmd.apply(sq)
    assert sq.ways[301].version == 4 and sq.ways[other].version is None
    cmd.undo(sq)
    assert sq.ways[301].version == 4

    long = Square(name=NAME, present=True)
    for i in range(1, 6):
        long.nodes[i] = Node(id=i, lat=-23.5, lon=125 + i / 10, version=1)
    long.ways[50] = Way(id=50, refs=[1, 2, 3, 4, 5], tags={'waterway': 'river'}, version=6)
    split = edits.split_long_ways(long, edits.SetUndoStack().alloc(long), limit=3)
    split.apply(long)
    assert long.ways[50].version == 6 and len(long.ways) == 2
    assert [w.version for i, w in long.ways.items() if i != 50] == [None]


def test_the_autosaves_change_file_carries_the_version(tmp_path):
    """An import not yet saved is in the change and nowhere else, so its
    versions have to come back with a recovery - and the .osc opens in JOSM
    as the square does."""
    path = write_square(Square(name=NAME, present=True), tmp_path / 'S24E125.osm.xz')
    sq = read_square(path)
    hist = edits.SetUndoStack()
    up = imported()
    hist.do(sq, edits.ImportWater(upstream_owns=overpass.UPSTREAM_OWNS, new_nodes=dict(up.nodes),
                                  new_ways=dict(up.ways), new_relations=dict(up.relations)))
    c = change_of(sq, hist.journal(sq))
    text = change_text(c)
    assert heads(text) == versions(up)
    again = read_square(path)
    ApplyChange(read_change(text, c.tail)).apply(again)
    assert versions(again) == versions(up)


def test_a_deleted_imported_feature_goes_into_the_change_at_its_version(tmp_path):
    """JOSM asks a delete of a positive id for its version too. A feature
    deleted is gone from the square, so the version is the one the history
    saw the first time an edit touched it - or, for what a command took out
    only as it ran, the one the command says it took (Command.taken): the
    vertices a deleted way leaves, the way a deleted node leaves too short,
    and the stretch a redrawn section lets go."""
    from xml.etree import ElementTree

    def deleted(sq, hist):
        c = change_of(sq, hist.journal(sq), hist.versions(sq))
        root = ElementTree.fromstring(change_text(c))
        block = root.find('delete')
        got = {(e.tag, int(e.get('id'))): e.get('version') for e in (block if block is not None else [])}
        back = read_change(change_text(c), c.tail)
        assert back.deleted_versions == c.deleted_versions
        return got

    path = write_square(imported(), tmp_path / 'S24E125.osm')
    sq, hist = read_square(path), edits.SetUndoStack()
    hist.mark_clean(sq)
    hist.do(sq, edits.DeleteRelation(401))
    hist.do(sq, edits.DeleteWay(301))                  # and its vertices with it, named as it runs
    assert deleted(sq, hist) == {('relation', 401): '9', ('way', 301): '4', ('node', 101): '2',
                                 ('node', 102): '3', ('node', 103): '4'}

    sq, hist = read_square(path), edits.SetUndoStack()
    sq.ways[302] = Way(id=302, refs=[101, 8374513], version=5)     # as the file might hold it
    hist.mark_clean(sq)
    hist.do(sq, edits.DeleteNode(8374513))             # leaves 302 a single node, so it goes too
    assert deleted(sq, hist) == {('node', 8374513): '7', ('way', 302): '5'}

    sq, hist = read_square(path), edits.SetUndoStack()
    hist.mark_clean(sq)
    hist.do(sq, edits.ReplaceSection(301, 0, 2, [101, 103]))   # 102 let go
    assert deleted(sq, hist) == {('node', 102): '3'}

    sq, hist = read_square(path), edits.SetUndoStack()
    hist.do(sq, edits.ReplaceWay(301, [(301, [101, 102])], {}))   # 103 let go
    assert deleted(sq, hist) == {('node', 103): '4'}

    sq, hist = read_square(path), edits.SetUndoStack()
    rerouted = Way(id=301, refs=[101, 102, 8374513, 101], tags={'natural': 'water'}, version=5)
    hist.do(sq, edits.ImportWater(upstream_owns=overpass.UPSTREAM_OWNS, new_ways={301: rerouted}))
    assert deleted(sq, hist) == {('node', 103): '4'}, 'the vertex a re-route left behind'
