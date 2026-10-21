"""danu.core.territory: the two published files, joined, asked whose ground a square is."""

import json

import pytest

from danu.core import territory as T

# the published geometry is [lat, lon]; one entry a bare ring, one a list of
# rings - both spellings are in the real file - and one with a hole
GEOMETRY = json.dumps({
    '1': [[0, 0], [0, 10], [10, 10], [10, 0]],                                   # lon 0..10, lat 0..10
    '2': [[[0, 10], [0, 20], [10, 20], [10, 10]]],                               # lon 10..20
    '3': [[[20, 20], [20, 30], [30, 30], [30, 20]], [[22, 22], [22, 28], [28, 28], [28, 22]]],   # with a hole
    '4': [[50, 50], [50, 51]],                                                   # degenerate, dropped
    '5': [[], [[60, 60], [60, 61], [61, 61]], [[1, 'x'], [2, 3], [3, 4]]],       # an empty and a malformed ring beside a good one
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
    assert set(g) == {1, 2, 3, 5} and len(g[1]) == 1 and len(g[3]) == 2 and len(g[5]) == 1
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
    assert T.describe([one], 'Luciano') == ('One (AR001), owned by Luciano', False)
    assert T.describe([one], 'luciano')[1] is True                                    # OGF's names are exact (H6f)
    assert T.describe([one], 'wangi') == ('not yours to draw: One (AR001), owned by Luciano', True)
    assert T.describe([two], 'wangi') == ('Two (AR002), collaborative', False)         # collaborative is not a claim
    assert T.describe([three], 'Leowezy')[1] is False                                  # one of several owners
    assert T.describe([three], 'wangi')[1] is True
    assert T.describe([one], 'wangi', admin=True) == ('not yours to draw: One (AR001), owned by Luciano (administrator)', True)
    assert T.describe([one], 'Luciano', admin=True) == ('One (AR001), owned by Luciano', False), 'their own: no admin'
    assert T.describe([one], '', admin=True)[0] == 'One (AR001), owned by Luciano', 'no user, no admin'
    # a collaborative territory's owner named, but not admin's; a delegate told (#245's Gobrassanya)
    gob = T.Territory(5, 'UL05a', 'Gobrassanya', 'collaborative', 'wangi')
    assert T.describe([gob], 'wangi', admin=True) == ('Gobrassanya (UL05a), collaborative, owned by wangi', False)
    assert T.describe([gob], 'Luciano', admin=True)[0] == 'Gobrassanya (UL05a), collaborative, owned by wangi (administrator)'
    assert T.describe([two], 'wangi')[0] == 'Two (AR002), collaborative'
    led = T.Territory(6, 'X2', 'Led', 'owned', 'Luciano', ('dem:wangi',))
    assert T.describe([led], 'wangi') == ('Led (X2), owned by Luciano - delegated to you', False)
    assert T.describe([led], 'Luciano')[0] == 'Led (X2), owned by Luciano'
    line, warn = T.describe([T.Territory(9), one], 'wangi')
    assert line.startswith('not yours to draw: unknown territory (relation 9); One') and warn


def test_a_relation_with_no_record_and_an_outline_are_not_under_a_square():
    """A timezone has rings and no ogf:id, so no record (304988 over
    Gobrassanya); an outline is split into the sub-territories under it."""
    geometry = T.parse_geometry(json.dumps({
        '10': [[0, 0], [0, 10], [10, 10], [10, 0]],          # the territory
        '11': [[-5, -5], [-5, 15], [15, 15], [15, -5]],      # a timezone over it
        '12': [[0, 0], [0, 10], [10, 10], [10, 0]],          # an outline over it
    }))
    attrs = {10: T.Territory(10, 'UL05a', 'Gobrassanya', 'owned', 'wangi'),
             12: T.Territory(12, 'UL05', 'Collab:Somewhere', 'outline', 'admin')}
    idx = T.TerritoryIndex(geometry, attrs)
    assert [t.rel for t in idx.under((2, 2, 3, 3))] == [10]
    assert idx.under((12, 12, 13, 13)) == [], 'the timezone alone: no territory'
    assert T.describe(idx.under((2, 2, 3, 3)), 'wangi') == ('Gobrassanya (UL05a), owned by wangi', False)


def test_before_the_records_are_read_every_polygon_is_unknown():
    idx = T.TerritoryIndex(T.parse_geometry(json.dumps({'11': [[-5, -5], [-5, 15], [15, 15], [15, -5]]})), {})
    (t,) = idx.under((2, 2, 3, 3))
    assert t.describe() == 'unknown territory (relation 11)'


# the data drop's permission (#190)

def test_editors_are_the_owners_and_the_dem_delegates_trimmed():
    a = T.parse_attributes(json.dumps([
        {'rel': 1, 'owner': 'lankusiek; Mie; Poissott', 'constraints': ['Desert', 'dem:Alice; Bob', 'DEM:Carol']},
        {'rel': 2, 'owner': 'Kevin J', 'constraints': ['Mountains-S', 7, None]},
        {'rel': 3, 'owner': '', 'constraints': 'dem:Dave'},
        {'rel': 4, 'owner': '', 'constraints': {'not': 'a list'}},
    ]))
    assert a[1].editors == {'lankusiek', 'Mie', 'Poissott', 'Alice', 'Bob', 'Carol'}
    assert a[2].editors == {'Kevin J'} and a[2].constraints == ('Mountains-S',)
    assert a[3].editors == {'Dave'}, 'one constraint, not in a list'
    assert a[4].editors == frozenset() and a[4].constraints == ()
    # describe's warning goes by them too
    t = T.Territory(9, 'X1', 'Ex', 'owned', 'Luciano', ('dem:wangi',))
    assert T.describe([t], 'wangi')[1] is False and T.describe([t], 'Wangi')[1] is True


def test_shares_are_exact_holes_out_and_slivers_dropped():
    idx = index()
    assert idx.shares((2, 2, 3, 3)) == {1: 1.0}
    sh = idx.shares((9.5, 2, 10.5, 3))
    assert sh == pytest.approx({1: 0.5, 2: 0.5})
    assert idx.shares((21, 21, 29, 29)) == pytest.approx({3: (64 - 36) / 64}), 'the hole is not Three'
    assert idx.shares((23, 23, 27, 27)) == {}, 'a square wholly in the hole'
    # a neighbour reaching half a metre into the square is a sliver, not a claim
    assert idx.shares((10 - 5e-6, 2, 11 - 5e-6, 3)) == {2: pytest.approx(1 - 5e-6)}


def test_under_puts_the_centre_first_then_the_larger_share():
    idx = index()
    assert [t.name for t in idx.under((9.4, 2, 10.4, 3))] == ['One', 'Two']
    assert [t.name for t in idx.under((9.8, 2, 11.8, 3))] == ['Two', 'One']
    assert [t.name for t in idx.under((-0.9, 2, 0.1, 3))] == ['One'], 'centre at sea: by share'


def test_permission_yes_partial_no():
    idx = index()
    assert idx.permission((2, 2, 3, 3), 'Luciano').level == T.YES
    assert idx.permission((-0.5, 2, 0.5, 3), 'Luciano').level == T.YES, 'the sea counts for nobody'
    p = idx.permission((9.5, 2, 10.5, 3), 'Luciano')
    assert p.level == T.PARTIAL and [t.name for t in p.mine] == ['One'] and [t.name for t in p.others] == ['Two']
    assert idx.permission((9.5, 2, 10.5, 3), 'admin').level == T.PARTIAL, 'admin the owner, not the role'
    assert idx.permission((2, 2, 3, 3), 'wangi').level == T.NO
    assert idx.permission((2, 2, 3, 3), '').level == T.NO
    assert idx.permission((40, 40, 41, 41), 'Luciano').level == T.NO, 'no territory at all: admins only'
    assert idx.permission((21, 21, 29, 29), 'Leowezy').level == T.YES, 'one of several owners'


def test_a_hole_sharing_a_vertex_with_its_outer_ring_is_still_a_hole():
    # the hole's first vertex is the outer ring's corner (0, 0)
    geometry = T.parse_geometry(json.dumps({'1': [[[0, 0], [0, 10], [10, 10], [10, 0]],
                                                  [[0, 0], [0, 4], [4, 4], [4, 0]]]}))
    idx = T.TerritoryIndex(geometry, {1: T.Territory(1, 'A', 'A', 'owned', 'wangi')})
    assert idx.shares((0, 0, 4, 4)) == {}
    assert idx.shares((0, 0, 10, 10)) == {1: pytest.approx(84 / 100)}


def test_permission_ignores_status():
    geometry = T.parse_geometry(json.dumps({'1': [[0, 0], [0, 10], [10, 10], [10, 0]]}))
    for status in ('owned', 'reserved', 'collaborative', 'available', 'archived'):
        idx = T.TerritoryIndex(geometry, {1: T.Territory(1, 'A', 'A', status, 'wangi')})
        assert idx.permission((2, 2, 3, 3), 'wangi').level == T.YES
