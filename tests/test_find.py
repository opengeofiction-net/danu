"""Edit › Find element's ids, and where in the open squares they are."""

import pytest

from danu.core import find
from danu.core.square import Member, Node, Relation, Square, SquareName, Way


@pytest.mark.parametrize('text, want', [
    ('w-50092477', ('way', -50092477)), ('W19573', ('way', 19573)), (' n123 ', ('node', 123)),
    ('r248', ('relation', 248)), ('way/19573', ('way', 19573)), ('relation 248', ('relation', 248)),
    ('node:-5', ('node', -5)), ('n -5', ('node', -5)),
])
def test_the_forms_an_id_is_given_in(text, want):
    assert find.parse(text) == want


@pytest.mark.parametrize('text', ['', '123', 'x12', 'w', 'w12a', 'way//12', 'w1 2'])
def test_what_is_not_an_id_says_so(text):
    with pytest.raises(ValueError, match='not an element'):
        find.parse(text)


def square(lon, ways=(), relations=()):
    sq = Square(name=SquareName(lon, -24), present=True, attrs={})
    for i in range(1, 5):
        sq.nodes[i] = Node(id=i, lon=lon + i / 10, lat=-23.5)
    for w in ways:
        sq.ways[w.id] = w
    for r in relations:
        sq.relations[r.id] = r
    return sq


def test_found_in_every_square_holding_it_in_order():
    lake = Way(id=7, refs=[1, 2, 3, 1], tags={'natural': 'water'})
    a, b, c = square(125, [lake]), square(126), square(127, [lake])
    assert [sq.name for sq, _ in find.find([a, b, c], 'way', 7)] == [a.name, c.name]
    assert find.find([a, b, c], 'way', 8) == []
    rel = Relation(id=3, members=[Member('way', 7, 'outer')], tags={'natural': 'water'})
    assert find.find([square(125, relations=[rel])], 'relation', 3)[0][1] is rel
    assert find.find([b], 'node', 2)[0][1].id == 2


def test_a_node_is_found_on_a_contour_before_a_lake_outline():
    lake = Way(id=7, refs=[1, 2, 3, 1], tags={'natural': 'water'})
    contour = Way(id=-9, refs=[2, 4], tags={'ele': '10'})
    sq = square(125, [lake, contour])
    assert find.way_of(sq, 2) is contour
    assert find.way_of(sq, 1) is lake
    assert find.way_of(sq, 99) is None
