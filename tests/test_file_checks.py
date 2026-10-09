"""What a square's file says - H1a: long ways (R30), an ele not a number
(R31), a value off the ladder used once or twice. No Qt."""

from danu.checks import files
from danu.core import edits
from danu.core.square import Node, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
_ids = iter(range(1000, 10**7))


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def line(sq, n, tags, lat=-22.5):
    refs = []
    for k in range(n):
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=125.1 + k * 0.8 / n, lat=lat)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags=tags)
    return sq.ways[i]


def ladder(sq):
    """25 m apart, twice each: the square's ladder, nothing off it."""
    for k, ele in enumerate((100, 100, 125, 125, 150, 150, 175, 175)):
        line(sq, 3, {'ele': str(ele)}, lat=-22.9 + k * 0.05)


def test_a_way_over_the_apis_limit_and_one_over_gdals_are_found():
    w, sq = ws()
    ladder(sq)
    a = line(sq, 2001, {'ele': '100'}, lat=-22.1)
    b = line(sq, 10001, {'ele': '125'}, lat=-22.05)
    line(sq, 2000, {'ele': '150'}, lat=-22.0)                     # at the limit: fine
    found = [f for f in files.find(w) if f.kind == 'long']
    assert {f.way for f in found} == {a.id, b.id}
    gdal = next(f for f in found if f.way == b.id)
    assert '10,001 nodes' in gdal.describe() and 'GDAL drops' in gdal.explain()
    assert 'API refuses' in next(f for f in found if f.way == a.id).explain()


def test_an_ele_not_a_number_on_a_way_or_a_node_is_found():
    w, sq = ws()
    ladder(sq)
    lake = line(sq, 4, {'natural': 'water', 'name': 'Kettle Lake', 'ele': '1,853 Ft'}, lat=-22.2)
    sq.nodes[-9] = Node(id=-9, lon=125.5, lat=-22.3, tags={'natural': 'peak', 'ele': 'tbd'})
    line(sq, 4, {'ele': '125.5'}, lat=-22.15)                     # a number
    found = [f for f in files.find(w) if f.kind == 'ele']
    assert {(f.way, f.node) for f in found} == {(lake.id, None), (None, -9)}
    assert next(f for f in found if f.way).describe() == f'water "Kettle Lake", way {lake.id} - ele "1,853 Ft"'


def test_a_value_off_the_ladder_used_once_is_a_row_and_one_on_it_is_not():
    """113 between 100 and 125, on a 25 m ladder: once, so listed. 125 once
    more is on the ladder, and 120 three times is too common to be a typo."""
    w, sq = ws()
    ladder(sq)
    odd = line(sq, 3, {'ele': '113'}, lat=-22.2)
    for k in range(3):
        line(sq, 3, {'ele': '120'}, lat=-22.15 + k * 0.01)
    (f,) = [f for f in files.find(w) if f.kind == 'ladder']
    assert f.way == odd.id and 'the 113 m contour' in f.describe() and 'used once between 100 and 120' in f.describe()


def test_the_index_follows_an_edit():
    w, sq = ws()
    ladder(sq)
    odd = line(sq, 3, {'ele': '113'}, lat=-22.2)
    index = files.Index(w)
    assert [f.way for f in index.findings('ladder')] == [odd.id]
    cmd = edits.SetTags(odd.id, dict(odd.tags), {'ele': '125'})
    cmd.apply(sq)
    index.update(sq, cmd.ways(sq))
    assert index.findings() == []
