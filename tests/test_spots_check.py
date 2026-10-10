"""A spot height which contradicts the contours around it - R38. No Qt."""

from danu.checks import spots
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
_ids = iter(range(1000, 10**6))


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def ring(sq, cx, cy, r, ele):
    refs = []
    for dx, dy in ((-r, -r), (r, -r), (r, r), (-r, r)):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=cx + dx, lat=cy + dy)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=[*refs, refs[0]], tags={'ele': str(ele)})
    return sq.ways[i]


def spot(sq, lon, lat, ele, **tags):
    i = next(_ids)
    sq.nodes[i] = Node(id=i, lon=lon, lat=lat, tags={'ele': str(ele), **tags})
    return i


def hill(sq):
    """100, 125 and 150 m rings, nested: a 25 m ladder, and a hill."""
    for r, ele in ((0.03, 100), (0.02, 125), (0.01, 150)):
        ring(sq, 125.5, -22.5, r, ele)


def test_a_peak_below_the_ring_it_stands_inside_is_found():
    w, sq = ws()
    hill(sq)
    i = spot(sq, 125.5, -22.5, 149, name='Nate Peak')
    (c,) = spots.find(w)
    assert (c.node, c.kind, c.level, c.hollow) == (i, 'below', 150, False)
    assert c.describe() == 'Nate Peak 149 m - below the 150 m ring round it'


def test_one_past_the_next_contour_is_found_and_one_between_is_not():
    w, sq = ws()
    hill(sq)
    i = spot(sq, 125.5, -22.5, 190)
    spot(sq, 125.505, -22.5, 170)                       # between 150 and 175: right
    (c,) = spots.find(w)
    assert (c.node, c.kind, c.bound) == (i, 'above', 175)
    assert 'past the 175 m, which is not drawn round it' in c.describe()


def test_the_next_contour_is_the_ladders_not_an_off_ladder_value_the_square_holds():
    """A 155 m ring elsewhere does not make the next contour after 150 m: on
    a 25 m ladder it is 175, and 160 m is between."""
    w, sq = ws()
    hill(sq)
    ring(sq, 125.9, -22.9, 0.01, 155)
    spot(sq, 125.5, -22.5, 160)
    assert spots.find(w) == [], 'judged against an off-ladder 155 m'


def test_in_a_rings_box_but_outside_it_is_not_inside():
    """A diamond 150 m ring: its box's corner is outside it, and a 100 m spot
    height there is not below it."""
    w, sq = ws()
    ring(sq, 125.5, -22.5, 0.05, 125)
    refs = []
    for dx, dy in ((0, -0.02), (0.02, 0), (0, 0.02), (-0.02, 0)):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=125.5 + dx, lat=-22.5 + dy)
        refs.append(i)
    sq.ways[-77] = Way(id=-77, refs=[*refs, refs[0]], tags={'ele': '150'})
    spot(sq, 125.5 - 0.017, -22.5 + 0.017, 130)                    # the box's corner
    assert spots.find(w) == []


def test_in_a_hollow_it_is_turned_over():
    w, sq = ws()
    for r, ele in ((0.03, 150), (0.02, 125), (0.01, 100)):          # down to a pit
        ring(sq, 125.5, -22.5, r, ele)
    i = spot(sq, 125.5, -22.5, 104)
    spot(sq, 125.505, -22.5, 90)                         # below 100, above 75: right
    (c,) = spots.find(w)
    assert (c.node, c.kind, c.hollow) == (i, 'below', True)
    assert 'above the 100 m ring' in c.describe()


def test_the_innermost_ring_is_the_one_that_counts():
    """Inside the 150 m and so inside the 100 m too: 140 m is below the 150."""
    w, sq = ws()
    hill(sq)
    spot(sq, 125.5, -22.5, 140)
    (c,) = spots.find(w)
    assert c.level == 150


def test_a_rivers_vertex_with_a_level_is_not_a_spot_height():
    w, sq = ws()
    hill(sq)
    a = spot(sq, 125.5, -22.5, 60)
    b = spot(sq, 125.6, -22.5, 50)
    sq.ways[-99] = Way(id=-99, refs=[a, b], tags={'waterway': 'stream'})
    assert spots.find(w) == []


def test_one_far_from_any_contour_is_not_judged():
    w, sq = ws()
    hill(sq)
    spot(sq, 125.9, -22.9, 5)
    assert spots.find(w) == []


def test_the_index_follows_a_ring_and_a_spot_height_edited():
    w, sq = ws()
    hill(sq)
    i = spot(sq, 125.5, -22.5, 160)
    index = spots.Index(w)
    assert index.contradictions() == []
    top = next(x for x in sq.ways.values() if x.ele == 150)
    cmd = edits.SetTags(top.id, dict(top.tags), {**top.tags, 'ele': '175'})
    cmd.apply(sq)
    index.update(sq, {top.id})
    assert [c.node for c in index.contradictions()] == [i], 'a ring re-levelled round it'
    cmd.undo(sq)
    index.update(sq, {top.id})
    assert index.contradictions() == []
    n = sq.nodes[i]
    move = edits.SetNodeTags(i, dict(n.tags), {**n.tags, 'ele': '145'})
    move.apply(sq)
    index.update(sq, (), {i})
    assert [c.kind for c in index.contradictions()] == ['below']


def test_after_an_off_ladder_ring_the_next_contour_is_the_next_rung():
    """A 135 m ring innermost on a 25 m ladder: the next contour is 150 m, so
    155 m is past it - and 145 m is not."""
    w, sq = ws()
    for r, ele in ((0.03, 100), (0.02, 125), (0.01, 135)):
        ring(sq, 125.5, -22.5, r, ele)
    ring(sq, 125.9, -22.9, 0.01, 150)
    ring(sq, 125.9, -22.9, 0.005, 175)                   # the ladder's rungs held
    i = spot(sq, 125.5, -22.5, 155)
    spot(sq, 125.503, -22.5, 145)
    (c,) = spots.find(w)
    assert (c.node, c.bound) == (i, 150)


def test_a_ring_moved_off_a_spot_height_takes_its_contradiction_with_it():
    w, sq = ws()
    hill(sq)
    spot(sq, 125.5, -22.5, 149)
    index = spots.Index(w)
    assert len(index.contradictions()) == 1
    top = next(x for x in sq.ways.values() if x.ele == 150)
    moves = []
    for r in dict.fromkeys(top.refs):
        n = sq.nodes[r]
        moves.append(edits.MoveNode(r, (n.lon, n.lat), (n.lon + 0.3, n.lat)))
    cmd = edits.Compound(moves)
    cmd.apply(sq)
    index.update(sq, {top.id})
    assert index.contradictions() == []


def test_a_ring_deleted_round_a_spot_height_takes_its_contradiction_with_it():
    w, sq = ws()
    hill(sq)
    spot(sq, 125.5, -22.5, 149)
    index = spots.Index(w)
    top = next(x for x in sq.ways.values() if x.ele == 150)
    gone = edits.DeleteWay(top.id)
    gone.apply(sq)
    index.update(sq, {top.id})
    assert index.contradictions() == [], 'judged against the ring that was'


def open_box(sq, cx, cy, r, eles):
    """Four separate ways round a point, one a side: contours in every
    direction and no ring."""
    corners = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
    for k, ele in enumerate(eles):
        (x0, y0), (x1, y1) = corners[k], corners[(k + 1) % 4]
        refs = []
        for x, y in ((x0, y0), (x1, y1)):
            i = next(_ids)
            sq.nodes[i] = Node(id=i, lon=x, lat=y)
            refs.append(i)
        i = next(_ids)
        sq.ways[i] = Way(id=i, refs=refs, tags={'ele': str(ele)})


def a_ladder(sq):
    """A 25 m ladder for the square, far off."""
    for k, ele in enumerate((100, 125, 150, 175)):
        ring(sq, 125.1 + 0.05 * k, -22.9, 0.01, ele)


def test_in_no_ring_one_far_above_the_contours_nearest_it_is_found():
    """Suprrina Hill: 69 m, the contours round it 5 to 7 m."""
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (5, 5, 7, 7))
    open_box(sq, 125.5, -22.5, 0.012, (300, 300, 300, 300))     # beyond them, and not the nearest
    i = spot(sq, 125.5, -22.5, 69, name='Suprrina Hill')
    spot(sq, 125.501, -22.5, 20)                          # within a step of 7: a rise between them
    (c,) = spots.find(w)
    assert (c.node, c.kind, c.open, c.lo, c.hi, c.bound) == (i, 'above', True, 5, 7, 32)
    assert c.describe() == 'Suprrina Hill 69 m - in no ring, the contours nearest it 5 to 7 m'
    assert '62 m above the highest' in c.explain()


def test_in_no_ring_one_far_below_them_is_found_and_one_with_too_few_round_it_is_not():
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (100, 100, 125, 125))
    i = spot(sq, 125.5, -22.5, 60)
    (c,) = spots.find(w)
    assert (c.node, c.kind, c.open) == (i, 'below', True)
    # two sides only: four directions of eight meet a contour
    w2, sq2 = ws()
    a_ladder(sq2)
    open_box(sq2, 125.5, -22.5, 0.005, (100, 100, 125, 125))
    for wid in [x for x, way in sq2.ways.items() if way.ele == 125 and x not in
                {r for r in sq2.ways if sq2.ways[r].refs[0] == sq2.ways[r].refs[-1]}]:
        del sq2.ways[wid]
    spot(sq2, 125.5, -22.5, 60)
    assert spots.find(w2) == []


def test_the_index_follows_a_contour_moved_near_a_spot_height_in_no_ring_and_agrees_with_a_fresh_scan():
    import random
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (5, 5, 7, 7))
    spot(sq, 125.5, -22.5, 20)
    index = spots.Index(w)
    assert index.contradictions() == []
    rnd = random.Random(5)
    for step in range(60):
        nid = rnd.choice([i for i, n in sq.nodes.items() if 'ele' not in n.tags])
        n = sq.nodes[nid]
        cmd = edits.MoveNode(nid, (n.lon, n.lat), (n.lon + rnd.uniform(-0.004, 0.004), n.lat + rnd.uniform(-0.004, 0.004)))
        cmd.apply(sq)
        index.update(sq, cmd.ways(sq))
        assert sorted(c.describe() for c in index.contradictions()) == sorted(c.describe() for c in spots.find(w)), step
    t = next(x for x in sq.ways.values() if x.ele == 7)
    cmd = edits.SetTags(t.id, dict(t.tags), {'ele': '-30'})                 # the 7 m becomes -30: 20 m is far above
    cmd.apply(sq)
    index.update(sq, {t.id})
    assert sorted(c.describe() for c in index.contradictions()) == sorted(c.describe() for c in spots.find(w))


def test_a_contour_moved_in_beside_a_spot_height_in_no_ring_clears_it_though_the_edit_names_only_the_contour():
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (5, 5, 7, 7))
    i = spot(sq, 125.5, -22.5, 69)
    far = []
    for x, y in ((125.8, -22.2), (125.81, -22.2)):
        k = next(_ids)
        sq.nodes[k] = Node(id=k, lon=x, lat=y)
        far.append(k)
    k = next(_ids)
    sq.ways[k] = Way(id=k, refs=far, tags={'ele': '70'})
    index = spots.Index(w)
    assert [c.node for c in index.contradictions()] == [i]
    moves = edits.Compound([edits.MoveNode(far[0], (125.8, -22.2), (125.502, -22.503)),
                            edits.MoveNode(far[1], (125.81, -22.2), (125.502, -22.497))])
    moves.apply(sq)
    index.update(sq, moves.ways(sq))
    assert index.contradictions() == [], 'the spot height beside it not asked again'
    gone = edits.DeleteWay(k)
    gone.apply(sq)
    index.update(sq, {k})
    assert [c.node for c in index.contradictions()] == [i], 'a deleted contour still judged by'


def test_a_node_two_edited_contours_share_moved_in_beside_one_asks_it_again():
    """Both contours are the edit's; each lost the node's old place and has
    its new one - gathered together those must not cancel."""
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (5, 5, 7, 7))
    i = spot(sq, 125.5, -22.5, 69)
    ids = []
    for x, y in ((125.8, -22.2), (125.9, -22.2), (125.9, -22.3)):
        k = next(_ids)
        sq.nodes[k] = Node(id=k, lon=x, lat=y)
        ids.append(k)
    shared, a, b = ids[0], ids[1], ids[2]
    for refs, ele in (([a, shared], '70'), ([b, shared], '75')):
        k = next(_ids)
        sq.ways[k] = Way(id=k, refs=refs, tags={'ele': ele})
    index = spots.Index(w)
    assert [c.node for c in index.contradictions()] == [i]
    move = edits.MoveNode(shared, (125.8, -22.2), (125.501, -22.5))
    move.apply(sq)
    index.update(sq, move.ways(sq))
    assert sorted(c.node for c in index.contradictions()) == sorted(c.node for c in spots.find(w))


def test_a_long_segment_passing_close_with_both_ends_far_off_is_met():
    """A 70 m contour as one segment 20 km long, passing 400 m from the
    spot height: both its ends are far beyond reach, and it is the nearest
    contour on that side."""
    w, sq = ws()
    a_ladder(sq)
    open_box(sq, 125.5, -22.5, 0.005, (5, 5, 7, 7))
    i = spot(sq, 125.5, -22.5, 69)
    assert [c.node for c in spots.find(w)] == [i]
    ends = []
    for x, y in ((125.4, -22.502), (125.6, -22.502)):          # 0.2 degrees long, just south of it
        k = next(_ids)
        sq.nodes[k] = Node(id=k, lon=x, lat=y)
        ends.append(k)
    k = next(_ids)
    sq.ways[k] = Way(id=k, refs=ends, tags={'ele': '70'})
    assert spots.find(w) == [], 'the long contour beside it not met'
