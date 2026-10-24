"""danu.core.doubled: a negative contour lying wholly on a main-map way at
its level, as an import of coastline or water leaves recovered squares. No Qt,
no GDAL."""

from danu.core import doubled
from danu.core.square import Member, Node, Relation, Square, SquareName, Way, WorkingSet

A = SquareName(125, -23)
M = 1 / 110540                      # a metre of latitude


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def way(sq, wid, pts, tags):
    refs = []
    for lon, lat in pts:
        nid = (max((abs(i) for i in sq.nodes), default=0) + 1) * (1 if wid > 0 else -1)
        sq.nodes[nid] = Node(id=nid, lon=lon, lat=lat)
        refs.append(nid)
    sq.ways[wid] = Way(id=wid, refs=refs, tags=dict(tags))
    return sq.ways[wid]


COAST = [(125.50, -22.50), (125.51, -22.50), (125.52, -22.505)]


def removed(w):
    return sorted(cmd.way_id for _, step in doubled.commands(w) for cmd in step.commands)


def test_a_negative_copy_on_the_main_maps_coastline_goes_and_the_coastline_stays():
    w, sq = ws()
    way(sq, 4118, COAST, {'natural': 'coastline', 'ele': '0'})
    way(sq, -1, [(lon, lat + 0.5 * M) for lon, lat in COAST[:2]], {'natural': 'coastline', 'ele': '0'})
    way(sq, -2, COAST, {'contour': 'elevation', 'ele': '0'})
    steps = doubled.commands(w)
    assert removed(w) == [-2, -1]
    for s, step in steps:
        step.apply(s)
    assert list(sq.ways) == [4118] and 'doubled' in steps[0][1].describe()


def test_one_doubled_only_in_part_another_level_or_a_relations_member_stays():
    w, sq = ws()
    way(sq, 4118, COAST, {'natural': 'coastline', 'ele': '0'})
    way(sq, -1, [*COAST, (125.53, -22.49)], {'contour': 'elevation', 'ele': '0'})    # runs on past it
    way(sq, -2, COAST, {'contour': 'elevation', 'ele': '10'})                          # another level
    way(sq, -3, [(lon, lat + 5 * M) for lon, lat in COAST], {'ele': '0'})             # 5 m off
    ring = way(sq, -4, COAST, {'ele': '0'})
    sq.relations[-5] = Relation(id=-5, members=[Member('way', ring.id, 'outer')], tags={'natural': 'water'})
    assert removed(w) == []


def test_two_negative_copies_of_each_other_are_left_to_the_panel():
    w, sq = ws()
    way(sq, -1, COAST, {'ele': '0'})
    way(sq, -2, COAST, {'ele': '0'})
    assert removed(w) == []
