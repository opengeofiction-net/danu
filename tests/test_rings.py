"""Stitching a relation's member ways back into rings - the fill's groundwork.

No Qt and no GDAL: this is topology, and the question it answers - did these
pieces come back to where they started - has nothing to do with painting.
"""

from danu.core import rings
from danu.core.square import Member, Node, Relation, Square, SquareName, Way


def a_square() -> Square:
    return Square(name=SquareName(125, -24), present=True, attrs={})


def with_way(sq: Square, wid: int, refs: list[int], tags=None) -> Way:
    for r in refs:
        sq.nodes.setdefault(r, Node(id=r, lon=125.0 + r * 0.001, lat=-23.5))
    sq.ways[wid] = Way(id=wid, refs=list(refs), tags=dict(tags or {}))
    return sq.ways[wid]


def test_two_halves_make_one_ring():
    assert rings.closed_rings([[1, 2, 3], [3, 4, 1]]) == [[1, 2, 3, 4, 1]]


def test_a_member_drawn_backwards_is_turned_round():
    """A relation does not require its members to run the same way, and a
    mapper drawing the second half from the other end is doing nothing wrong."""
    got = rings.closed_rings([[1, 2, 3], [1, 4, 3]])
    assert len(got) == 1
    assert got[0][0] == got[0][-1]
    assert sorted(set(got[0])) == [1, 2, 3, 4]


def test_the_order_the_members_are_listed_in_does_not_matter():
    pieces = [[5, 6], [3, 4, 5], [6, 1], [1, 2, 3]]
    got = rings.closed_rings(pieces)
    assert len(got) == 1 and len(set(got[0])) == 6


def test_an_open_chain_is_not_a_ring():
    """The straddling case: a lake cut by the square edge arrives with pieces
    missing, and what is left does not close. It must not be filled."""
    assert rings.closed_rings([[1, 2, 3], [3, 4, 5]]) == []


def test_two_rings_come_back_as_two():
    got = rings.closed_rings([[1, 2, 3], [3, 1], [7, 8, 9], [9, 7]])
    assert len(got) == 2
    assert all(r[0] == r[-1] for r in got)


def test_a_relation_uses_only_the_members_the_square_holds():
    sq = a_square()
    with_way(sq, -10, [1, 2, 3])
    with_way(sq, -11, [3, 4, 1])
    rel = Relation(id=-20, tags={'natural': 'water'},
                   members=[Member('way', -10, 'outer'), Member('way', -11, 'outer'),
                            Member('way', -12, 'outer')])    # -12 is in the next square
    assert rings.relation_rings(sq, rel) == [[1, 2, 3, 4, 1]]


def test_a_relation_whose_ring_is_cut_by_the_edge_yields_nothing():
    sq = a_square()
    with_way(sq, -10, [1, 2, 3])
    rel = Relation(id=-20, tags={'natural': 'water'},
                   members=[Member('way', -10, 'outer'), Member('way', -11, 'outer')])
    assert rings.relation_rings(sq, rel) == []


def test_an_island_in_a_lake_is_a_second_ring():
    """Both rings come back, undistinguished - which is the point. The painter
    is given them together with an odd-even fill and the hole falls out of the
    geometry rather than out of a role we would have to trust."""
    sq = a_square()
    with_way(sq, -10, [1, 2, 3, 4, 1])
    with_way(sq, -11, [5, 6, 7, 5])
    rel = Relation(id=-20, tags={'natural': 'water'},
                   members=[Member('way', -10, 'outer'), Member('way', -11, 'inner')])
    got = rings.relation_rings(sq, rel)
    assert len(got) == 2


def test_a_closed_way_is_its_own_ring_and_a_line_is_not():
    sq = a_square()
    lake = with_way(sq, -10, [1, 2, 3, 4, 1])
    river = with_way(sq, -11, [5, 6, 7])
    sliver = with_way(sq, -12, [8, 9, 8])
    assert rings.is_closed(lake)
    assert not rings.is_closed(river)
    assert not rings.is_closed(sliver), 'a way doubling back on itself is not an area'
