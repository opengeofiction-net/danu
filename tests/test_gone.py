"""Gone from upstream, and kept where held - R40, G5b.

No Qt and no GDAL. What is under test is which held features an answer's
silence counts against, the refusal of an answer that says it is incomplete,
and placement putting a feature back in the square that already holds it.
"""

import re

import pytest

from danu.core.square import Member, Node, Relation, SquareName, Way, WorkingSet
from danu.water import overpass
from danu.water.gone import gone

HERE = SquareName(125, -24)
EAST = SquareName(126, -24)


@pytest.fixture
def ws(tmp_path):
    return WorkingSet.open(tmp_path, HERE)


def hold(ws, name, *features):
    sq = ws.squares[name]
    for f in features:
        (sq.relations if isinstance(f, Relation) else sq.ways)[f.id] = f
    return sq


# ------------------------------------------------- what the query asks for

def test_asked_for_is_the_querys_own_selection():
    """Said twice, so held together. Every statement in the query's union is
    read - not only the ones a pattern recognises, so a selector added in
    another syntax fails here rather than slipping past - and each has to pass
    `asked_for`. The things the query was written to leave out must not."""
    q = overpass.query((125.0, -24.0, 126.0, -23.0))
    union = q[q.index('(\n') + 2:q.index('\n);')]
    statements = [line.strip() for line in union.splitlines() if line.strip()]
    selectors = [re.fullmatch(r'(way|relation)\["(\w+)"="(\w+)"\];', st) for st in statements]
    assert all(selectors), (
        f'a statement this test cannot read: '
        f'{[st for st, sel in zip(statements, selectors, strict=True) if not sel]}'
    )
    named = {sel.groups() for sel in selectors}
    assert named == ({('way', 'waterway', k) for k in overpass.LINE_KINDS + overpass.AREA_KINDS}
                     | {('way', 'natural', 'water'), ('relation', 'natural', 'water')})
    for kind, key, value in named:
        assert overpass.asked_for(kind, {key: value}), f'{kind}[{key}={value}] is asked for'
    for kind, tags in (('way', {'waterway': 'drain'}), ('way', {'waterway': 'dam'}),
                       ('way', {'natural': 'coastline'}), ('way', {'ele': '40'}),
                       ('relation', {'waterway': 'river', 'type': 'waterway'}),
                       ('node', {'natural': 'water'})):
        assert not overpass.asked_for(kind, tags), f'{kind} {tags} is not asked for'


# ----------------------------------------------- an answer cut short

def test_an_answer_that_says_it_is_incomplete_is_refused():
    """Overpass sends what it had with an HTTP 200 and a remark. Absence from
    a truncated answer is not deletion upstream, and G5b would say it was."""
    payload = b'''<?xml version="1.0"?><osm version="0.6">
      <node id="1" lat="-23.5" lon="125.2"/>
      <remark> runtime error: Query timed out in "query" at line 3 after 61 seconds. </remark>
    </osm>'''
    with pytest.raises(overpass.IncompleteAnswer, match='timed out'):
        overpass.parse(payload)
    assert issubclass(overpass.IncompleteAnswer, OSError), 'it fails the import like a network error'


def test_a_remark_that_is_not_an_error_is_not_refused():
    payload = b'''<?xml version="1.0"?><osm version="0.6">
      <remark> runtime remark: Timeout is 60 and maxsize is 536870912. </remark>
      <node id="1" lat="-23.5" lon="125.2"/>
    </osm>'''
    assert 1 in overpass.parse(payload).nodes


# ---------------------------------------------------- kept where held

def an_answer():
    """A river whose first node is in EAST and a lake relation whose first
    member's first node is in EAST - so by anchor both land there."""
    w = overpass.Water()
    for i, lon in ((1, 126.2), (2, 125.8), (3, 125.6)):
        w.nodes[i] = Node(id=i, lat=-23.5, lon=lon)
    for i, (lon, lat) in enumerate(((126.3, -23.6), (126.4, -23.6), (126.4, -23.5)), 11):
        w.nodes[i] = Node(id=i, lat=lat, lon=lon)
    w.ways[100] = Way(id=100, refs=[1, 2, 3], tags={'waterway': 'river'})
    w.ways[200] = Way(id=200, refs=[11, 12, 13, 11])
    w.relations[300] = Relation(id=300, tags={'natural': 'water'},
                                members=[Member('way', 200, 'outer')])
    return w


def test_by_anchor_a_feature_lands_where_its_first_node_is(ws):
    placed = overpass.place(an_answer(), ws)
    assert 100 in placed[EAST].ways and 300 in placed[EAST].relations


def test_a_held_feature_goes_back_where_it_is_held(ws):
    """Upstream redrew the river from its other end, so its anchor crossed a
    degree line though the river did not move. Placed by anchor, the copy
    lands in the neighbour without the elevation set on the held one, and the
    held one stays: one id, two files."""
    held = {('way', 100): HERE, ('relation', 300): HERE}
    placed = overpass.place(an_answer(), ws, held)
    assert 100 in placed[HERE].ways, 'the held river was placed by anchor instead'
    assert 300 in placed[HERE].relations, 'the held lake was placed by anchor instead'
    assert EAST not in placed or not (placed[EAST].ways or placed[EAST].relations), (
        'a held feature was placed into the neighbour as well'
    )
    # and its geometry came with it, as an anchored feature's does
    assert {1, 2, 3, 11, 12, 13} <= set(placed[HERE].nodes)
    assert 200 in placed[HERE].ways, "the lake's ring did not go with the lake"


# ------------------------------------------------------------- gone

def test_a_held_river_the_answer_does_not_name_is_gone(ws):
    hold(ws, HERE, Way(id=100, refs=[], tags={'waterway': 'river', 'name': 'Bosco'}))
    got = gone(ws, frozenset(), frozenset())
    assert [(g.square, g.kind, g.id, g.name, g.what) for g in got] == \
           [(HERE, 'way', 100, 'Bosco', 'river')]
    assert 'Bosco' in got[0].describe() and str(HERE) in got[0].describe()


def test_a_held_river_the_answer_names_is_not_gone(ws):
    hold(ws, HERE, Way(id=100, refs=[], tags={'waterway': 'river'}))
    assert gone(ws, frozenset({100}), frozenset()) == []


def test_named_anywhere_in_the_answer_is_not_gone(ws):
    """The comparison is against the whole answer, not against what was placed
    into the square: a feature placed next door, or dropped for an anchor
    outside the set, is still upstream."""
    hold(ws, HERE, Way(id=100, refs=[], tags={'waterway': 'river'}))
    hold(ws, EAST, Relation(id=300, tags={'natural': 'water'}, members=[]))
    assert gone(ws, frozenset({100}), frozenset({300})) == []


def test_what_the_query_never_asks_for_is_never_gone(ws):
    """Otherwise every contour and coastline is reported missing on every
    import - none of them is in any answer."""
    hold(ws, HERE,
         Way(id=1, refs=[], tags={'ele': '40'}),
         Way(id=2, refs=[], tags={'natural': 'coastline'}),
         Way(id=3, refs=[], tags={'waterway': 'drain'}),
         Way(id=4, refs=[]))
    assert gone(ws, frozenset(), frozenset()) == []


def test_what_was_drawn_here_was_never_upstream(ws):
    """A negative id was allocated in the editor. It cannot have left."""
    hold(ws, HERE, Way(id=-5, refs=[], tags={'natural': 'water'}),
         Relation(id=-6, tags={'natural': 'water'}, members=[]))
    assert gone(ws, frozenset(), frozenset()) == []


def test_a_held_lake_relation_is_gone(ws):
    hold(ws, HERE, Relation(id=300, tags={'natural': 'water', 'name': 'Kinser'},
                            members=[]))
    got = gone(ws, frozenset(), frozenset())
    assert [(g.kind, g.id, g.name) for g in got] == [('relation', 300, 'Kinser')]


def test_a_lake_ring_upstream_replaced_is_reported_though_it_has_no_tags(ws):
    """Upstream redrew the ring under a new id. The relation comes back naming
    the new way, and the old one would be left as an untagged line nothing
    names - which the tag test alone would never find."""
    hold(ws, HERE, Way(id=200, refs=[]),
         Relation(id=300, tags={'natural': 'water'}, members=[Member('way', 200, 'outer')]))
    got = gone(ws, frozenset({201}), frozenset({300}))
    assert [(g.kind, g.id, g.what) for g in got] == [('way', 200, 'lake ring')]


def test_the_report_is_in_a_stable_order(ws):
    hold(ws, EAST, Way(id=7, refs=[], tags={'waterway': 'stream'}))
    hold(ws, HERE, Way(id=9, refs=[], tags={'waterway': 'stream'}),
         Way(id=8, refs=[], tags={'waterway': 'stream'}),
         Relation(id=300, tags={'natural': 'water'}, members=[]))
    got = gone(ws, frozenset(), frozenset())
    assert [(g.square, g.kind, g.id) for g in got] == [
        (HERE, 'relation', 300), (HERE, 'way', 8), (HERE, 'way', 9), (EAST, 'way', 7)]
