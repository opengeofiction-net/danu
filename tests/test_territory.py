"""danu.core.territory: the two published files, joined, asked whose ground a square is."""

import json

from danu.core import territory as T

# the published geometry is [lat, lon]; one entry a bare ring, one a list of
# rings - both spellings are in the real file - and one with a hole
GEOMETRY = json.dumps({
    '1': [[0, 0], [0, 10], [10, 10], [10, 0]],                                   # lon 0..10, lat 0..10
    '2': [[[0, 10], [0, 20], [10, 20], [10, 10]]],                               # lon 10..20
    '3': [[[20, 20], [20, 30], [30, 30], [30, 20]], [[22, 22], [22, 28], [28, 28], [28, 22]]],   # with a hole
    '4': [[50, 50], [50, 51]],                                                   # degenerate, dropped
})
ATTRIBUTES = json.dumps([
    {'ogfId': 'AR001', 'name': 'One', 'rel': 1, 'status': 'owned', 'owner': 'Luciano'},
    {'ogfId': 'AR002', 'name': 'Two', 'rel': 2, 'status': 'collaborative', 'owner': 'admin'},
    {'ogfId': 'AR003', 'name': 'Three', 'rel': 3, 'status': 'reserved', 'owner': 'Alessa;Leowezy'},
    {'ogfId': 'X', 'name': 'no rel', 'status': 'owned', 'owner': 'nobody'},
])


def index():
    return T.TerritoryIndex(T.parse_geometry(GEOMETRY), T.parse_attributes(ATTRIBUTES))


def test_both_spellings_parse_and_axes_are_swapped_to_lon_lat():
    g = T.parse_geometry(GEOMETRY)
    assert set(g) == {1, 2, 3} and len(g[1]) == 1 and len(g[3]) == 2
    assert g[2][0][0] == (10.0, 0.0)                     # [lat 0, lon 10] -> (lon 10, lat 0)
    a = T.parse_attributes(ATTRIBUTES)
    assert set(a) == {1, 2, 3} and a[1].owner == 'Luciano' and a[3].status == 'reserved'


def test_a_point_is_placed_and_a_hole_is_a_hole():
    idx = index()
    assert [t.name for t in idx.at(5, 5)] == ['One']
    assert [t.name for t in idx.at(15, 5)] == ['Two']
    assert [t.name for t in idx.at(21, 21)] == ['Three'] and idx.at(25, 25) == []
    assert idx.at(-5, -5) == [] and idx.at(50.5, 50.5) == []
    assert not idx.contains(999, (5, 5))                # a relation it never saw


def test_a_square_on_a_border_reports_both_with_the_centres_first():
    idx = index()
    assert [t.name for t in idx.under((2, 2, 3, 3))] == ['One']
    assert [t.name for t in idx.under((9.4, 2, 10.4, 3))] == ['One', 'Two']      # centre in One
    assert [t.name for t in idx.under((9.8, 2, 11.8, 3))] == ['Two', 'One']      # centre in Two
    assert [t.name for t in idx.under((21, 21, 29, 29))] == ['Three']            # the hole is inside it: a vertex reaches in
    assert idx.under((40, 40, 41, 41)) == []


def test_a_polygon_without_a_record_is_unknown_not_guessed():
    idx = T.TerritoryIndex(T.parse_geometry(GEOMETRY), {})
    (t,) = idx.at(5, 5)
    assert not t.known and t.describe() == 'unknown territory (relation 1)'


def test_describe_warns_only_for_ground_claimed_by_somebody_else():
    idx = index()
    one, two, three = idx.territory(1), idx.territory(2), idx.territory(3)
    assert T.describe([], 'wangi') == ('no territory here', False)
    assert T.describe([one], '') == ('One (AR001), owned by Luciano', False)          # no user: told, not warned
    assert T.describe([one], 'luciano') == ('One (AR001), owned by Luciano', False)   # case does not matter
    assert T.describe([one], 'wangi') == ('not yours to draw: One (AR001), owned by Luciano', True)
    assert T.describe([two], 'wangi') == ('Two (AR002), collaborative', False)         # collaborative is not a claim
    assert T.describe([three], 'leowezy')[1] is False                                  # one of several owners
    assert T.describe([three], 'wangi')[1] is True
    line, warn = T.describe([T.Territory(9), one], 'wangi')
    assert line.startswith('not yours to draw: unknown territory (relation 9); One') and warn
