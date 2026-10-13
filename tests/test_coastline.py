"""Coastlines in the editor: marked, turned round, and never turned by
anything else.

A ``natural=coastline`` is the one way whose direction is data - land on its
left, sea on its right, which is where the build reads the sea from - and in
these squares one carries ``ele=0`` as well, so it passes every test a 0 m
contour does. What is held here is that nothing but Reverse changes which way
one runs.
"""

from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, is_coastline

NAME = SquareName(125, -24)


def square() -> Square:
    """Two sea-level lines end to end, west to east, a 100 m contour, and a
    river: 1-2-3, 3-4-5, 6-7 at 100 m, 8-9 a river at 0."""
    sq = Square(name=NAME, present=True)
    for i in range(1, 10):
        sq.nodes[i] = Node(id=i, lat=-23.5 + (0.1 if i >= 6 else 0), lon=125 + i / 20)
    sq.ways[-1] = Way(id=-1, refs=[1, 2, 3], tags={'ele': '0'})
    sq.ways[-2] = Way(id=-2, refs=[3, 4, 5], tags={'ele': '0'})
    sq.ways[-3] = Way(id=-3, refs=[6, 7], tags={'ele': '100'})
    sq.ways[-4] = Way(id=-4, refs=[8, 9], tags={'ele': '0', 'waterway': 'river'})
    return sq


def coast(sq: Square, *ids: int) -> Square:
    for i in ids:
        sq.ways[i].tags['natural'] = 'coastline'
    return sq


def test_a_sea_level_line_is_marked_and_unmarked_as_one_step_each():
    sq = square()
    cmd = edits.mark_coastline(sq, -1, True)
    cmd.apply(sq)
    assert is_coastline(sq.ways[-1]) and sq.ways[-1].tags['ele'] == '0', 'the elevation stays'
    assert sq.ways[-1].refs == [1, 2, 3], 'and so does the direction it was drawn in'
    cmd.undo(sq)
    assert not is_coastline(sq.ways[-1])
    cmd.apply(sq)
    off = edits.mark_coastline(sq, -1, False)
    off.apply(sq)
    assert sq.ways[-1].tags == {'ele': '0'}


def test_only_a_sea_level_line_that_is_nothing_else_is_marked():
    sq = square()
    assert 'ele=0' in edits.mark_coastline(sq, -3, True)
    assert edits.mark_coastline(sq, -4, True) == 'it is water'
    sq.ways[-2].tags['natural'] = 'cliff'
    assert edits.mark_coastline(sq, -2, True) == 'it is natural=cliff already'
    assert edits.mark_coastline(coast(sq, -1), -1, True) == 'it is a coastline already'
    assert edits.mark_coastline(sq, -99, True) == 'that way is no longer there'
    assert edits.mark_coastline(square(), -1, False) == 'it is not a coastline'


def test_reverse_turns_a_coastline_round_and_back():
    sq = coast(square(), -1)
    cmd = edits.reverse_coastline(sq, -1)
    cmd.apply(sq)
    assert sq.ways[-1].refs == [3, 2, 1]
    cmd.undo(sq)
    assert sq.ways[-1].refs == [1, 2, 3]
    assert edits.reverse_coastline(sq, -2) == 'only a coastline has a direction that matters'


def test_a_coastline_joins_only_a_coastline():
    sq = coast(square(), -1)
    assert edits.join_ways(sq, -1, 3, -2, 3) == 'a coastline joins only another coastline'
    assert edits.join_ways(sq, -2, 3, -1, 3) == 'a coastline joins only another coastline'


def test_two_coastlines_join_head_to_tail_as_they_run_and_never_turned():
    """Tail onto head keeps the first's run; head onto tail puts the other
    first. Either way the result runs as both did, and keeps the dragged
    way's id as every join does."""
    sq = coast(square(), -1, -2)
    edits.join_ways(sq, -1, 3, -2, 3).apply(sq)
    assert sq.ways[-1].refs == [1, 2, 3, 4, 5] and -2 not in sq.ways

    sq = coast(square(), -1, -2)
    edits.join_ways(sq, -2, 3, -1, 3).apply(sq)
    assert sq.ways[-2].refs == [1, 2, 3, 4, 5] and -1 not in sq.ways


def test_two_coastlines_that_run_against_each_other_are_refused():
    sq = coast(square(), -1, -2)
    sq.ways[-2].refs.reverse()                      # 5-4-3: both end at 3
    assert 'reverse one first' in edits.join_ways(sq, -1, 3, -2, 3)
    # a contour still joins either way round, as it always has
    sq = square()
    sq.ways[-2].refs.reverse()
    edits.join_ways(sq, -1, 3, -2, 3).apply(sq)
    assert sq.ways[-1].refs == [1, 2, 3, 4, 5]


def test_a_coastline_closed_on_itself_keeps_its_direction():
    for end, want in ((5, [1, 2, 3, 4, 1]), (1, [5, 2, 3, 4, 5])):
        sq = coast(square(), -2)
        sq.ways[-2].refs = [1, 2, 3, 4, 5]
        edits.join_ways(sq, -2, end, -2, 1 if end == 5 else 5).apply(sq)
        assert sq.ways[-2].refs == want, f'dragging {end}'
