"""A river as the chain of ways it was split into - G6d. No Qt, no GDAL.

Built on a small grid of squares with ways laid out by hand, so every place a
chain runs on, stops or crosses a gap is one the test can name.
"""

from danu.core.chains import TOLERANCE_M, Network, component, free_end_side
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A, B = SquareName(125, -24), SquareName(126, -24)
M = 1 / 110540                              # a metre of latitude


def ws():
    squares = {n: Square(name=n, present=True, attrs={}) for n in (A, B)}
    return WorkingSet(centre=A, size=1, squares=squares)


def node(sq, nid, lon, lat):
    sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat)
    return nid


def way(sq, wid, refs, kind='stream', name=None):
    tags = {'waterway': kind}
    if name:
        tags['name'] = name
    sq.ways[wid] = Way(id=wid, refs=list(refs), tags=tags)
    return sq.ways[wid]


def line(sq, wid, ids, lat=-23.5, lon0=125.1, name=None, step=0.01):
    """A way of len(ids) nodes running east."""
    for k, i in enumerate(ids):
        node(sq, i, lon0 + step * k, lat)
    return way(sq, wid, ids, name=name)


def walked(chain):
    out = []
    for link in chain.links:
        r = link.refs()
        out += r if not out else (r[1:] if r[0] == out[-1] else r)
    return out


def test_ways_sharing_an_end_are_one_chain():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    line(sq, 2, [12, 13, 14], lon0=125.12)
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert [link.way.id for link in chain.links] == [1, 2]
    assert walked(chain) == [10, 11, 12, 13, 14]


def test_a_piece_drawn_the_other_way_is_walked_against_its_drawing_and_not_reversed():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    for k, i in enumerate((14, 13, 12)):
        node(sq, i, 125.14 - 0.01 * k, -23.5)
    way(sq, 2, [14, 13, 12])
    line(sq, 3, [14, 15], lon0=125.14)
    chain = Network(w).chain_of(sq, sq.ways[2])
    # walked in the direction the way clicked on was drawn - 15 to 10 - which
    # is as good an order as the other: the grade finds downstream itself
    assert walked(chain) == [15, 14, 13, 12, 11, 10]
    assert [link.way.id for link in chain.links] == [3, 2, 1]
    assert [link.backwards for link in chain.links] == [True, False, True]
    assert sq.ways[2].refs == [14, 13, 12], 'the way itself was reversed'


def test_a_chain_stops_at_a_confluence():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    line(sq, 2, [12, 13], lon0=125.12)
    node(sq, 20, 125.12, -23.6)
    way(sq, 3, [20, 12])                      # a tributary joining at 12
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert [link.way.id for link in chain.links] == [1]
    assert 'a confluence' in chain.stops


def test_a_chain_stops_where_a_line_passes_through():
    """A tributary drawn on to the river's side, not to one of its ends."""
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    node(sq, 20, 125.11, -23.6)
    way(sq, 2, [20, 11])                      # ends at the middle of way 1
    chain = Network(w).chain_of(sq, sq.ways[2])
    assert [link.way.id for link in chain.links] == [2]
    assert 'a line passes through' in chain.stops


def test_a_gap_within_the_tolerance_is_walked_across_and_reported():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    line(sq, 2, [13, 14], lon0=125.12, lat=-23.5 + 2.5 * M)      # 2.5 m short
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert [link.way.id for link in chain.links] == [1, 2]
    (j,) = chain.joins
    assert (j.after, j.before) == (1, 2) and abs(j.gap_m - 2.5) < 0.2


def test_a_gap_wider_than_the_tolerance_is_not():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    line(sq, 2, [13, 14], lon0=125.12, lat=-23.5 + (TOLERANCE_M + 1) * M)
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert [link.way.id for link in chain.links] == [1] and chain.joins == []


def test_a_gap_is_not_crossed_into_another_named_stream():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12], name='Bosco')
    line(sq, 2, [13, 14], lon0=125.12, lat=-23.5 + 2 * M, name='Kinser Water')
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert len(chain.links) == 1
    assert any('another stream' in s for s in chain.stops)


def test_a_gap_is_crossed_into_the_same_stream_or_an_unnamed_one():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12], name='Bosco')
    line(sq, 2, [13, 14], lon0=125.12, lat=-23.5 + 2 * M)
    assert len(Network(w).chain_of(sq, sq.ways[1]).links) == 2


def test_two_pieces_in_reach_is_a_branch_the_data_does_not_say_and_not_crossed():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    line(sq, 2, [13, 14], lon0=125.12, lat=-23.5 + 2 * M)
    line(sq, 3, [15, 16], lon0=125.12, lat=-23.5 - 2 * M)
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert len(chain.links) == 1
    assert any('two pieces' in s for s in chain.stops)


def test_a_ring_of_ways_ends():
    w = ws(); sq = w.squares[A]
    for i, (lon, lat) in enumerate(((125.1, -23.5), (125.2, -23.5), (125.2, -23.4)), 10):
        node(sq, i, lon, lat)
    way(sq, 1, [10, 11]); way(sq, 2, [11, 12]); way(sq, 3, [12, 10])
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert sorted(link.way.id for link in chain.links) == [1, 2, 3]
    assert 'it comes back on itself' in chain.stops


def test_a_chain_runs_into_the_next_square_by_an_imported_nodes_id():
    """An import places each way whole into one square, nodes and all, so a
    junction node is in both squares' files under one OSM id."""
    w = ws(); a, b = w.squares[A], w.squares[B]
    line(a, 1, [10, 11, 12], lon0=125.97)
    for k, i in enumerate((12, 13, 14)):
        node(b, i, 125.99 + 0.01 * k, -23.5)
    way(b, 2, [12, 13, 14])
    chain = Network(w).chain_of(a, a.ways[1])
    assert [(link.square.name, link.way.id) for link in chain.links] == [(A, 1), (B, 2)]


def test_a_local_node_id_means_nothing_in_another_square():
    w = ws(); a, b = w.squares[A], w.squares[B]
    line(a, -1, [-10, -11, -12], lon0=125.97)
    for k, i in enumerate((-12, -13)):
        node(b, i, 126.5 + 0.01 * k, -23.5)       # the same id, somewhere else entirely
    way(b, -2, [-12, -13])
    assert len(Network(w).chain_of(a, a.ways[-1]).links) == 1


def test_only_river_and_stream_lines_chain():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    for k, i in enumerate((12, 13)):
        node(sq, i, 125.12 + 0.01 * k, -23.5)
    way(sq, 2, [12, 13], kind='riverbank')
    sq.ways[3] = Way(id=3, refs=[12, 13], tags={'ele': '40'})
    assert len(Network(w).chain_of(sq, sq.ways[1]).links) == 1


def test_a_ring_closed_by_a_gap_ends_and_does_not_loop():
    w = ws(); sq = w.squares[A]
    for i, (lon, lat) in enumerate(((125.1, -23.5), (125.2, -23.5), (125.2, -23.4)), 10):
        node(sq, i, lon, lat)
    node(sq, 13, 125.1, -23.5 + 2 * M)        # 2 m from where the ring began
    way(sq, 1, [10, 11]); way(sq, 2, [11, 12]); way(sq, 3, [12, 13])
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert sorted(link.way.id for link in chain.links) == [1, 2, 3], 'a way was walked twice'


def test_a_way_whose_own_ends_are_within_reach_is_not_crossed_into_itself():
    """A stream that nearly closes on itself: its two free ends 2 m apart. It
    must not be walked across into its own other end."""
    w = ws(); sq = w.squares[A]
    for i, (lon, lat) in enumerate(((125.1, -23.5), (125.2, -23.5), (125.2, -23.4)), 10):
        node(sq, i, lon, lat)
    node(sq, 13, 125.1, -23.5 + 2 * M)
    way(sq, 1, [10, 11, 12, 13])
    chain = Network(w).chain_of(sq, sq.ways[1])
    assert [link.way.id for link in chain.links] == [1] and chain.joins == []


# ------------------------------------------------------------ networks - G6d-2

def confluence(names=('Bosco', 'Bosco', None)):
    """Two pieces of a river meeting a tributary at node 12."""
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12], name=names[0])
    line(sq, 2, [12, 13, 14], lon0=125.12, name=names[1])
    node(sq, 20, 125.12, -23.6)
    way(sq, 3, [20, 12], name=names[2])
    return w, sq


def test_a_stem_carries_on_through_a_confluence_into_the_arm_with_its_name():
    w, sq = confluence()
    stem = Network(w).stem_of(sq, sq.ways[1])
    assert [link.way.id for link in stem.links] == [1, 2]
    assert walked(stem) == [10, 11, 12, 13, 14]


def test_a_chain_still_stops_there():
    w, sq = confluence()
    assert [link.way.id for link in Network(w).chain_of(sq, sq.ways[1]).links] == [1]


def test_a_stem_stops_where_no_one_arm_carries_its_name():
    for names in (('Bosco', 'Kinser', None), ('Bosco', 'Bosco', 'Bosco'), (None, None, None)):
        w, sq = confluence(names)
        stem = Network(w).stem_of(sq, sq.ways[1])
        assert [link.way.id for link in stem.links] == [1], names
        assert 'a confluence' in stem.stops


def test_a_stem_stops_short_of_a_way_another_stem_holds():
    w, sq = confluence()
    stem = Network(w).stem_of(sq, sq.ways[1], claimed={(A, 2)})
    assert [link.way.id for link in stem.links] == [1]


def test_an_end_that_stops_short_of_a_rivers_side_is_found():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    node(sq, 20, 125.105, -23.6)
    node(sq, 21, 125.105, -23.5 - 2 * M)                  # 2 m short of way 1's side
    way(sq, 2, [20, 21])
    net = Network(w)
    side = free_end_side(net, sq, sq.ways[2], at_start=False)
    assert side is not None and side.way.id == 1 and side.seg == 0
    assert abs(side.t - 0.5) < 0.01 and abs(side.gap_m - 2) < 0.2
    assert free_end_side(net, sq, sq.ways[2], at_start=True) is None, 'the far end reached it'


def test_an_end_that_meets_a_line_or_reaches_two_has_no_side():
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    node(sq, 20, 125.105, -23.6)
    way(sq, 2, [20, 11])                                   # meets way 1 at a node
    assert free_end_side(Network(w), sq, sq.ways[2], at_start=False) is None
    line(sq, 3, [30, 31], lat=-23.5 - 4 * M)               # a second line, 4 m the other side
    node(sq, 22, 125.105, -23.5 - 2 * M)
    way(sq, 4, [20, 22])
    assert free_end_side(Network(w), sq, sq.ways[4], at_start=False) is None


def test_a_network_is_the_same_whichever_line_it_is_asked_from():
    """A tributary that stops short of its river is found from the river too
    - on the gobras set it was not, and one network was proposed three ways."""
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])
    node(sq, 20, 125.105, -23.6)
    node(sq, 21, 125.105, -23.5 - 2 * M)
    way(sq, 2, [20, 21])
    line(sq, 3, [12, 13], lon0=125.12)                     # on, by a shared node
    line(sq, 4, [40, 41], lon0=125.13, lat=-23.5 + 2 * M)  # on, across a gap
    net = Network(w)
    want = {1, 2, 3, 4}
    for wid in want:
        assert {x.id for _, x in component(net, sq, sq.ways[wid])} == want, wid


def test_a_side_is_found_beside_the_end_of_a_long_segment():
    """Segments are found by cell; one a kilometre long is in every cell it
    crosses, not only the one its middle is in."""
    w = ws(); sq = w.squares[A]
    line(sq, 1, [10, 11, 12])                              # 1 km segments
    node(sq, 20, 125.119, -23.6)
    node(sq, 21, 125.119, -23.5 - 2 * M)                   # 100 m from 12, 450 from the middle
    way(sq, 2, [20, 21])
    side = free_end_side(Network(w), sq, sq.ways[2], at_start=False)
    assert side is not None and side.way.id == 1 and side.seg == 1
