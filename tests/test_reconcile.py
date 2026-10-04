"""A second import, reconciled - R40, G5a.

Upstream owns where the water is; the mapper owns how high it is. No Qt and no
GDAL: this is a rule about dictionaries, and the `tests` job runs it.
"""

import copy

from danu.core import edits
from danu.core.reconcile import merge_tags, reconcile
from danu.core.square import Member, Node, Relation, Square, SquareName, Way

OWNS = ('natural', 'water', 'waterway', 'name')


def upstream():
    """A river of four vertices and a lake of four, as an answer gives them."""
    nodes = {i: Node(id=i, lat=-23.5, lon=125.0 + i * 0.01) for i in range(1, 5)}
    nodes.update({i: Node(id=i, lat=-23.6 + (i % 2) * 0.01, lon=125.1 + (i // 12) * 0.01)
                  for i in range(11, 15)})
    ways = {
        100: Way(id=100, refs=[1, 2, 3, 4], tags={'waterway': 'river', 'name': 'Bosco'}),
        200: Way(id=200, refs=[11, 12, 13, 14, 11], tags={'natural': 'water'}),
    }
    rels = {300: Relation(id=300, tags={'natural': 'water', 'name': 'Kinser'},
                          members=[Member('way', 200, 'outer')])}
    return nodes, ways, rels


def held(nodes, ways, rels) -> Square:
    """The square after a first import of that answer."""
    sq = Square(name=SquareName(125, -24), present=True, attrs={})
    sq.nodes.update(copy.deepcopy(nodes))
    sq.ways.update(copy.deepcopy(ways))
    sq.relations.update(copy.deepcopy(rels))
    return sq


# ------------------------------------------------------------------- tags

def test_upstream_owns_what_the_water_is_and_what_it_is_called():
    got = merge_tags({'waterway': 'stream', 'name': 'renamed here'},
                     {'waterway': 'river', 'name': 'Bosco'}, OWNS)
    assert got == {'waterway': 'river', 'name': 'Bosco'}


def test_a_name_upstream_dropped_does_not_outlive_it_here():
    """A key upstream owns follows upstream when upstream removes it too."""
    assert merge_tags({'waterway': 'river', 'name': 'Bosco'},
                      {'waterway': 'river'}, OWNS) == {'waterway': 'river'}


def test_the_mappers_elevation_wins_and_upstreams_fills_in():
    assert merge_tags({'ele': '120'}, {'natural': 'water', 'ele': '95'}, OWNS)['ele'] == '120'
    assert merge_tags({}, {'natural': 'water', 'ele': '95'}, OWNS)['ele'] == '95'


def test_a_tag_upstream_does_not_own_is_the_mappers():
    got = merge_tags({'natural': 'water', 'note': 'checked on the ground'},
                     {'natural': 'water'}, OWNS)
    assert got['note'] == 'checked on the ground'


def test_the_tags_come_out_in_the_order_a_first_import_writes_them():
    """Upstream's, then `ele`, then the mapper's - so a feature with nothing of
    the mapper's on it writes the same line twice, and a re-import leaves no
    diff in the file."""
    got = merge_tags({'note': 'x', 'ele': '120'},
                     {'natural': 'water', 'water': 'lake', 'name': 'Kinser'}, OWNS)
    assert list(got) == ['natural', 'water', 'name', 'ele', 'note']


# ------------------------------------------------------------- the merge

def test_a_first_import_writes_upstreams_objects_as_they_are():
    nodes, ways, rels = upstream()
    sq = Square(name=SquareName(125, -24), present=True, attrs={})
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert all(got.ways[i] is ways[i] for i in ways)
    assert all(got.nodes[i] is nodes[i] for i in nodes)
    assert got.removed == set() and got.moved == set()


def test_reimporting_what_the_square_holds_changes_nothing():
    """The common case, and the cheap one: nearly every vertex of a second
    import has no tags either side, and is written as upstream's object
    rather than a new one saying the same thing."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    before = edits.snapshot(sq)
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert all(got.nodes[i] is nodes[i] for i in nodes), 'a settled vertex was rebuilt'
    assert got.removed == set() and got.moved == set()
    sq.nodes.update(got.nodes)
    sq.ways.update(got.ways)
    sq.relations.update(got.relations)
    assert edits.snapshot(sq) == before


def test_a_second_import_keeps_the_elevation_set_here():
    """The fault G5 exists for. G4b's import overwrote a held feature whole,
    and every elevation set since the first import went with it."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.ways[100].tags['ele'] = '42'
    sq.relations[300].tags['ele'] = '120'
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert got.ways[100].tags['ele'] == '42', 'the river lost the elevation set on it'
    assert got.relations[300].tags['ele'] == '120', 'the lake lost its level'
    assert got.ways[100].refs == ways[100].refs


def test_a_vertex_moved_here_goes_back_where_upstream_has_it():
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.nodes[2].lat += 0.05
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert (got.nodes[2].lat, got.nodes[2].lon) == (nodes[2].lat, nodes[2].lon)


def test_the_merge_builds_new_objects_and_leaves_the_squares_alone():
    """The caller's undo holds the square's objects. One altered in place
    would come back altered."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.ways[100].tags['ele'] = '42'
    sq.ways[100].tags['name'] = 'renamed here'
    mine = sq.ways[100]
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert got.ways[100] is not mine
    assert mine.tags == {'waterway': 'river', 'name': 'renamed here', 'ele': '42'}, (
        "the square's own way was changed by working out the merge"
    )
    assert got.ways[100].tags['name'] == 'Bosco'


def test_a_reroute_removes_the_vertices_it_left_behind():
    """Upstream redrew the river without vertex 3. Untagged and named by
    nothing else, it goes where the way went."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    del nodes[3]
    ways[100] = Way(id=100, refs=[1, 2, 4], tags=dict(ways[100].tags))
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert got.removed == {3}


def test_a_spot_height_left_behind_by_a_reroute_stays():
    """A vertex with an `ele` on it is a spot height somebody placed."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.nodes[3].tags['ele'] = '88'
    del nodes[3]
    ways[100] = Way(id=100, refs=[1, 2, 4], tags=dict(ways[100].tags))
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert 3 not in got.removed, 'a spot height was deleted by an import'


def test_a_vertex_a_contour_also_uses_stays_when_the_river_leaves_it():
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.ways[-1] = Way(id=-1, refs=[3, -10], tags={'ele': '40'})
    sq.nodes[-10] = Node(id=-10, lat=-23.4, lon=125.03)
    del nodes[3]
    ways[100] = Way(id=100, refs=[1, 2, 4], tags=dict(ways[100].tags))
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert 3 not in got.removed, 'a node a contour still uses was removed'


def test_a_contour_snapped_to_a_river_is_redrawn_when_the_river_moves():
    """Upstream owns where the river is; the contour was put on it. The node
    moves for both, and the contour has to be named so it is redrawn."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.ways[-1] = Way(id=-1, refs=[2, -10], tags={'ele': '40'})
    sq.nodes[-10] = Node(id=-10, lat=-23.4, lon=125.02)
    nodes[2] = Node(id=2, lat=-23.45, lon=nodes[2].lon)
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert got.moved == {-1}
    assert got.nodes[2].lat == -23.45


def test_a_relations_members_come_from_upstream_and_its_level_stays():
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.relations[300].tags['ele'] = '120'
    rels[300] = Relation(id=300, tags=dict(rels[300].tags),
                         members=[Member('way', 200, 'outer'), Member('way', 201, 'inner')])
    got = reconcile(sq, nodes, ways, rels, OWNS)
    assert [m.ref for m in got.relations[300].members] == [200, 201]
    assert got.relations[300].tags['ele'] == '120'


# ----------------------------------------------------------- the command

def test_reimport_keep_elevation_and_round_trip_on_the_history():
    """Import, set an elevation, import again: the elevation survives, and
    Ctrl+Z takes the second import back to exactly the square that had it."""
    nodes, ways, rels = upstream()
    sq = Square(name=SquareName(125, -24), present=True, attrs={})
    history = edits.SetUndoStack()

    def an_import():
        n, w, r = upstream()
        return edits.ImportWater(upstream_owns=OWNS, new_nodes=n, new_ways=w,
                                 new_relations=r)

    history.do(sq, an_import())
    history.do(sq, edits.SetTags(100, dict(sq.ways[100].tags),
                                 {**sq.ways[100].tags, 'ele': '42'}))
    sq.nodes[2].lat += 0.05                     # and a vertex moved by hand
    set_here = edits.snapshot(sq)

    history.do(sq, an_import())
    assert sq.ways[100].tags['ele'] == '42', 'the second import threw the elevation away'
    assert sq.nodes[2].lat == -23.5, 'upstream did not take its vertex back'
    for _ in range(3):
        history.undo()
        assert edits.snapshot(sq) == set_here, 'the undo did not restore the square'
        history.redo()
        assert sq.ways[100].tags['ele'] == '42'


def test_the_command_names_what_it_redraws_after_an_undo_too():
    """The driver asks ways() and spots() after the undo to know what moved
    back. A contour a moved node carried has to be in the answer both times."""
    nodes, ways, rels = upstream()
    sq = held(nodes, ways, rels)
    sq.ways[-1] = Way(id=-1, refs=[2, -10], tags={'ele': '40'})
    sq.nodes[-10] = Node(id=-10, lat=-23.4, lon=125.02)
    sq.nodes[2].tags['ele'] = '35'              # and it is a spot height too
    nodes[2] = Node(id=2, lat=-23.45, lon=nodes[2].lon)
    cmd = edits.ImportWater(upstream_owns=OWNS, new_nodes=nodes, new_ways=ways,
                            new_relations=rels)
    cmd.apply(sq)
    assert -1 in cmd.ways(sq) and 2 in cmd.spots(sq)
    cmd.undo(sq)
    assert -1 in cmd.ways(sq), 'after the undo the contour is not redrawn'
    assert 2 in cmd.spots(sq), 'after the undo the spot height is not redrawn'
