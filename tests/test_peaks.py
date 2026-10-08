"""Spot heights imported from the main map - G9, R41. No Qt, no network."""

import pytest

from danu.core import edits
from danu.core.square import Node, Square, SquareName, WorkingSet
from danu.water import overpass, peaks

A = SquareName(125, -23)
B = SquareName(126, -23)


def answer(*nodes, remark=None) -> bytes:
    """An Overpass XML answer: (id, lon, lat, tags) each."""
    out = ['<osm version="0.6">']
    if remark:
        out.append(f'<remark>{remark}</remark>')
    for i, lon, lat, tags in nodes:
        out.append(f'<node id="{i}" lat="{lat}" lon="{lon}">'
                   + ''.join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()) + '</node>')
    out.append('</osm>')
    return '\n'.join(out).encode()


def ws():
    sqs = {n: Square(name=n, present=True, attrs={}) for n in (A, B)}
    return WorkingSet(centre=A, size=3, squares=sqs)


@pytest.mark.parametrize('text, want', [
    ('430', 430.0), ('430.5', 430.5), ('1,234', 1234.0), ('-12', -12.0), ('300 m', 300.0),
    ('8,635 Ft', 2632.0), ("1000'", 305.0), ('1000 feet', 305.0),
    ('TBD', None), ('', None), ('3.4.5', None), ('12,34', None), (None, None),
])
def test_a_height_reads_in_metres_or_feet_or_not_at_all(text, want):
    assert peaks.metres(text) == (pytest.approx(want, abs=0.06) if want is not None else None)


def test_the_answer_keeps_peaks_volcanoes_and_saddles_with_a_height_and_counts_the_rest():
    got = peaks.parse(answer(
        (1, 125.5, -22.5, {'natural': 'peak', 'name': 'Welfare Peak', 'ele': '430', 'tourism': 'x'}),
        (2, 125.6, -22.5, {'natural': 'saddle', 'ele': '8,635 Ft'}),
        (3, 125.7, -22.5, {'natural': 'volcano', 'ele': 'high'}),
        (4, 125.8, -22.5, {'natural': 'tree', 'ele': '10'}),
    ))
    assert set(got.nodes) == {1, 2}
    assert got.nodes[1].tags == {'natural': 'peak', 'name': 'Welfare Peak', 'ele': '430'}
    assert got.nodes[2].tags['ele'] == '2632'
    assert got.skipped == [(3, 'high', 125.7, -22.5)]
    assert got.answered == {1, 2, 3}


def test_an_answer_cut_short_is_refused():
    with pytest.raises(overpass.IncompleteAnswer):
        peaks.parse(answer(remark='runtime error: Query timed out'))


def test_the_query_asks_for_the_kinds_with_a_height_over_the_box():
    q = peaks.query((125.0, -23.0, 127.0, -22.0))
    assert '[bbox:-23.0,125.0,-22.0,127.0]' in q
    assert 'node["natural"~"^(peak|volcano|saddle)$"]["ele"]' in q


def test_each_goes_into_the_square_it_falls_in_or_the_one_holding_it():
    w = ws()
    got = peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'ele': '100'}),
                             (2, 126.5, -22.5, {'natural': 'peak', 'ele': '200'}),
                             (3, 140.0, -22.5, {'natural': 'peak', 'ele': '300'})))
    placed = peaks.place(got, w)
    assert {n: set(v) for n, v in placed.items()} == {A: {1}, B: {2}}
    assert set(peaks.place(got, w, {2: A})[A]) == {1, 2}, 'a held one goes back where it is held'


def imported(sq, nodes):
    cmd = edits.ImportWater(upstream_owns=peaks.UPSTREAM_OWNS, new_nodes=dict(nodes),
                            name='import spot heights')
    cmd.apply(sq)
    return cmd


def test_a_second_import_keeps_the_height_set_here_and_takes_where_and_name_from_upstream():
    w = ws()
    sq = w.squares[A]
    first = peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'name': 'Old', 'ele': '430'})))
    imported(sq, first.nodes)
    assert sq.nodes[1].tags['ele'] == '430'
    sq.nodes[1] = Node(id=1, lon=125.5, lat=-22.5, tags={**sq.nodes[1].tags, 'ele': '436'})   # set here
    second = peaks.parse(answer((1, 125.501, -22.5, {'natural': 'peak', 'name': 'New', 'ele': '430'})))
    before = edits.snapshot(sq)
    cmd = imported(sq, second.nodes)
    n = sq.nodes[1]
    assert (n.lon, n.tags['name'], n.tags['ele']) == (125.501, 'New', '436')
    cmd.undo(sq)
    assert edits.snapshot(sq) == before


def test_the_import_says_how_many_spot_heights_it_brings():
    sq = ws().squares[A]
    got = peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'ele': '100'}),
                             (2, 125.6, -22.5, {'natural': 'peak', 'ele': '200'})))
    cmd = imported(sq, got.nodes)
    assert cmd.describe() == 'import spot heights: 2 features'
    assert cmd.spots(sq) == {1, 2}


def test_a_held_spot_height_upstream_no_longer_answers_is_reported_not_deleted():
    w = ws()
    sq = w.squares[A]
    imported(sq, peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'name': 'Tulip Hill', 'ele': '200'}),
                                    (2, 125.6, -22.5, {'natural': 'peak', 'ele': '300'}))).nodes)
    sq.nodes[-5] = Node(id=-5, lon=125.7, lat=-22.5, tags={'ele': '250'})      # placed here: never upstream
    again = peaks.parse(answer((2, 125.6, -22.5, {'natural': 'peak', 'ele': '300'})))
    (g,) = peaks.gone(w, again.answered)
    assert (g.kind, g.id, g.name, g.what) == ('node', 1, 'Tulip Hill', 'peak')
    assert 1 in sq.nodes


def test_a_river_vertex_tagged_as_a_peak_is_not_a_spot_height_gone():
    """The water import keeps a natural=peak on a river's vertex that carries
    one; it has no height upstream, so is never answered - and is not ours."""
    from danu.core.square import Way
    w = ws()
    sq = w.squares[A]
    sq.nodes[7] = Node(id=7, lon=125.5, lat=-22.5, tags={'natural': 'peak'})
    sq.nodes[8] = Node(id=8, lon=125.6, lat=-22.5)
    sq.ways[70] = Way(id=70, refs=[7, 8], tags={'waterway': 'stream'})
    assert peaks.gone(w, frozenset()) == [] and peaks.held(w) == {}


def test_a_spot_height_a_line_has_since_been_drawn_through_is_still_held():
    """Snapped to: a contour's vertex now. It carries its height, and stays
    the import's to reconcile and report."""
    from danu.core.square import Way
    w = ws()
    sq = w.squares[A]
    sq.nodes[9] = Node(id=9, lon=125.5, lat=-22.5, tags={'natural': 'peak', 'ele': '300'})
    sq.nodes[-1] = Node(id=-1, lon=125.6, lat=-22.5)
    sq.ways[-2] = Way(id=-2, refs=[9, -1], tags={'ele': '300'})
    assert peaks.held(w) == {9: A}
    assert [g.id for g in peaks.gone(w, frozenset())] == [9]


def contour(sq, pts, ele='100', wid=-50):
    from danu.core.square import Way
    refs = []
    for k, (lon, lat) in enumerate(pts):
        sq.nodes[wid * 100 - k] = Node(id=wid * 100 - k, lon=lon, lat=lat)
        refs.append(wid * 100 - k)
    sq.ways[wid] = Way(id=wid, refs=refs, tags={'ele': ele})


def test_where_the_contours_are_is_the_box_of_their_vertices_per_degree_square():
    """Every way with a numeric ele - and only those: the main map's Kettle
    Lake, ele=1,853 Ft, is no contour. A vertex in the next square counts
    there, as the build's envelope is taken per degree square."""
    w = ws()
    contour(w.squares[A], [(125.2, -22.8), (125.6, -22.4), (126.1, -22.5)])
    contour(w.squares[B], [(126.7, -22.9), (126.8, -22.8)], ele='1,853 Ft', wid=-51)
    boxes = peaks.envelopes(w)
    assert boxes == {A: (125.2, -22.8, 125.6, -22.4), B: (126.1, -22.5, 126.1, -22.5)}


def test_one_beyond_the_contours_is_counted_not_imported_and_one_held_stays():
    w = ws()
    contour(w.squares[A], [(125.2, -22.8), (125.6, -22.4)])
    got = peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'ele': '100'}),       # inside
                             (2, 125.8, -22.5, {'natural': 'peak', 'ele': '200'}),       # past the box
                             (3, 126.5, -22.5, {'natural': 'peak', 'ele': '300'}),       # no contour in B
                             (4, 125.9, -22.9, {'natural': 'peak', 'ele': '400'})))      # beyond, but held
    kept = peaks.within(got, peaks.envelopes(w), {4: A})
    assert set(kept.nodes) == {1, 4} and sorted(kept.beyond) == [2, 3]
    assert kept.answered == {1, 2, 3, 4}, 'one beyond the contours is not gone from upstream'


def test_a_height_the_main_map_now_gives_otherwise_is_listed_and_the_squares_kept():
    """Colonie Hill: imported at 698, set to 286 on the main map since. The
    import keeps the square's and says so - which is right is the mapper's."""
    w = ws()
    sq = w.squares[A]
    imported(sq, peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'name': 'Colonie Hill', 'ele': '698'}),
                                    (2, 125.6, -22.5, {'natural': 'saddle', 'ele': '300'}))).nodes)
    sq.nodes[3] = Node(id=3, lon=125.7, lat=-22.5, tags={'natural': 'peak'})       # no height here
    again = peaks.parse(answer((1, 125.5, -22.5, {'natural': 'peak', 'name': 'Colonie Hill', 'ele': '286'}),
                               (2, 125.6, -22.5, {'natural': 'saddle', 'ele': '300.0'}),
                               (3, 125.7, -22.5, {'natural': 'peak', 'ele': '120'})))
    placed = peaks.place(again, w, peaks.held(w))
    (d,) = peaks.differ(placed, w)
    assert (d.id, d.here, d.upstream) == (1, '698', '286')
    assert d.describe() == 'peak "Colonie Hill" - 698 m here, 286 m on the main map'
    imported(sq, placed[A])
    assert sq.nodes[1].tags['ele'] == '698' and sq.nodes[3].tags['ele'] == '120'
